"""Lunettes VELA : détection et connexion Bluetooth LE (modèle de production, ou M01 Pro en développement).
Le canal de contrôle passe par BLE ; l'audio des lunettes passe par l'appairage casque Bluetooth de Windows
(les lunettes deviennent alors le micro / haut-parleur d'IRIS). Le flux caméra dépendra du SDK du fournisseur matériel retenu (à valider)."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone

from . import lunettes_trames
from .capture import CaptureIndicator
from .config import Settings
from .events import EventHub

log = logging.getLogger("iris.glasses")

BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"
# Indices de nom d'appareil : génériques et propres à VELA, sans nommer de fournisseur.
GLASSES_HINTS = ("m01", "vela", "iris", "glass", "lunette", "smart")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GlassesService:
    def __init__(self, settings: Settings, hub: EventHub, capture: CaptureIndicator):
        self.settings = settings
        self.hub = hub
        self.capture = capture
        self.client = None
        self.device: dict | None = None
        self.services: list[dict] = []
        self.packets: deque[dict] = deque(maxlen=50)
        self.last_scan: list[dict] = []
        self._found: dict[str, object] = {}  # BLEDevice par adresse (dernier scan)
        self.scanning = False
        self.connecting = False
        self.error: str | None = None
        self.battery: int | None = None
        self.connected_at: str | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ble_loop: asyncio.AbstractEventLoop | None = None
        self._ble_thread: threading.Thread | None = None
        self._ble_ready = threading.Event()

    # ------------------------------------------------------------------ état
    @property
    def connected(self) -> bool:
        return bool(self.client is not None and getattr(self.client, "is_connected", False))

    def status(self) -> dict:
        g = self.settings.user.glasses
        return {
            "connected": self.connected,
            "connecting": self.connecting,
            "scanning": self.scanning,
            "device": self.device,
            "battery": self.battery,
            "connected_at": self.connected_at,
            "services": self.services,
            "packets": list(self.packets)[-20:],
            "packet_count": len(self.packets),
            "last_scan": self.last_scan,
            "error": self.error,
            "remembered": {"address": g.address, "name": g.name, "auto_connect": g.auto_connect},
        }

    def _publish(self) -> None:
        self.hub.publish("glasses.state", **self.status())

    # ------------------------------------------------------------------ thread Bluetooth dédié
    def _ensure_ble_thread(self) -> None:
        """Bleak (WinRT) exige un thread COM en MTA sans boucle GUI : on lui réserve un thread + une boucle asyncio."""
        if self._ble_thread is not None and self._ble_thread.is_alive():
            return

        def runner() -> None:
            if sys.platform == "win32":
                try:
                    from bleak.backends.winrt.util import uninitialize_sta

                    uninitialize_sta()
                except Exception:
                    pass
            loop = asyncio.new_event_loop()
            self._ble_loop = loop
            asyncio.set_event_loop(loop)
            self._ble_ready.set()
            loop.run_forever()

        self._ble_ready.clear()
        self._ble_thread = threading.Thread(target=runner, name="iris-ble", daemon=True)
        self._ble_thread.start()
        self._ble_ready.wait(timeout=10)

    async def _on_ble(self, coro):
        """Exécute une coroutine Bleak sur le thread Bluetooth et attend son résultat depuis la boucle principale."""
        self._ensure_ble_thread()
        assert self._ble_loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._ble_loop)
        return await asyncio.wrap_future(fut)

    # ------------------------------------------------------------------ appareils appairés (Windows)
    @staticmethod
    def _paired_devices_sync() -> list[dict]:
        """Appareils Bluetooth appairés dans Windows (présents), avec leur adresse : visibles même s'ils n'émettent pas."""
        if sys.platform != "win32":
            return []
        cmd = (
            "Get-PnpDevice -Class Bluetooth -PresentOnly | Where-Object { $_.InstanceId -match 'DEV_[0-9A-F]{12}' } | "
            "ForEach-Object { $_.FriendlyName + '|' + $_.Status + '|' + $_.InstanceId }"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            log.debug("Get-PnpDevice indisponible: %s", exc)
            return []
        out: dict[str, dict] = {}
        for line in proc.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            name, status, instance = parts[0].strip(), parts[1].strip(), parts[2]
            m = re.search(r"DEV_([0-9A-F]{12})", instance, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).upper()
            address = ":".join(raw[i : i + 2] for i in range(0, 12, 2))
            entry = out.setdefault(address, {"address": address, "name": name or address, "rssi": None, "paired": True,
                                             "le": False, "status": status,
                                             "likely_glasses": any(h in (name or "").lower() for h in GLASSES_HINTS)})
            if instance.upper().startswith("BTHLE"):
                entry["le"] = True
        return list(out.values())

    async def paired_devices(self) -> list[dict]:
        return await asyncio.to_thread(self._paired_devices_sync)

    # ------------------------------------------------------------------ scan
    async def scan(self, seconds: float = 6.0) -> list[dict]:
        if self.scanning:
            return self.last_scan
        self.scanning = True
        self.error = None
        self._publish()
        try:
            from bleak import BleakScanner

            found = await self._on_ble(BleakScanner.discover(timeout=seconds, return_adv=True))
            devices = []
            self._found = {}
            for address, (dev, adv) in found.items():
                self._found[address.upper()] = dev
                name = dev.name or adv.local_name or ""
                low = name.lower()
                devices.append(
                    {
                        "address": address,
                        "name": name or "(sans nom)",
                        "rssi": getattr(adv, "rssi", None),
                        "likely_glasses": any(h in low for h in GLASSES_HINTS),
                    }
                )
            for d in devices:
                d["paired"] = False
            # fusion avec les appareils appairés dans Windows (lunettes connectées en casque : pas d'annonce BLE)
            try:
                for pd in await self.paired_devices():
                    hit = next((d for d in devices if d["address"].upper() == pd["address"]), None)
                    if hit:
                        hit["paired"] = True
                        if hit["name"] == "(sans nom)":
                            hit["name"] = pd["name"]
                        hit["likely_glasses"] = hit["likely_glasses"] or pd["likely_glasses"]
                    else:
                        devices.append(pd)
            except Exception as exc:
                log.debug("appareils appairés indisponibles: %s", exc)
            devices.sort(key=lambda d: (not d["likely_glasses"], not d.get("paired"), d["name"] == "(sans nom)", -(d["rssi"] or -999)))
            self.last_scan = devices
            return devices
        except Exception as exc:
            self.error = f"Recherche Bluetooth impossible : {exc}"
            log.warning(self.error)
            try:
                self.last_scan = await self.paired_devices()
                return self.last_scan
            except Exception:
                return []
        finally:
            self.scanning = False
            self._publish()

    # ------------------------------------------------------------------ connexion
    async def connect(self, address: str, name: str | None = None, attempts: int = 3) -> dict:
        """Connexion BLE robuste : les lunettes n'émettent pas en continu, on rescane entre les tentatives."""
        from bleak import BleakClient
        from bleak.backends.device import BLEDevice
        from bleak.exc import BleakDeviceNotFoundError, BleakError

        if self.connected:
            await self.disconnect()
        self.connecting = True
        self.error = None
        self._loop = asyncio.get_running_loop()
        self._publish()
        address_key = address.upper()
        last_error = ""
        try:
            for attempt in range(1, max(1, attempts) + 1):
                self.hub.publish("glasses.connecting", attempt=attempt, attempts=attempts, address=address)
                # 1re tentative : connexion directe par adresse (fonctionne pour un appareil appairé, sans annonce BLE) ;
                # ensuite : appareil issu du dernier scan.
                target = self._found.get(address_key) if attempt > 1 else None
                if target is None:
                    target = BLEDevice(address, name, None)
                try:
                    client = await self._on_ble(self._ble_connect(BleakClient, target))
                except BleakDeviceNotFoundError:
                    last_error = "lunettes non détectées"
                    log.info("tentative %s : %s introuvable, nouveau scan", attempt, address)
                    if attempt < attempts:
                        await self.scan(5.0)
                    continue
                except (asyncio.TimeoutError, TimeoutError):
                    last_error = "délai de connexion dépassé"
                    if attempt < attempts:
                        await self.scan(4.0)
                    continue
                except BleakError as exc:
                    last_error = str(exc) or type(exc).__name__
                    if attempt < attempts:
                        await asyncio.sleep(2.0)
                    continue
                except Exception as exc:  # erreur interne WinRT/Bleak quand l'appareil est injoignable
                    last_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                    log.info("tentative %s : %s (%s), nouveau scan", attempt, address, last_error)
                    if attempt < attempts:
                        await self.scan(4.0)
                    continue
                self.client = client
                self.device = {"address": address, "name": name or getattr(target, "name", None) or address}
                self.connected_at = now_iso()
                self.services = await self._on_ble(self._ble_subscribe(client))
                await self._on_ble(self._read_basics(client))
                self.settings.update({"glasses": {"address": address, "name": self.device["name"], "auto_connect": self.settings.user.glasses.auto_connect}})
                self.hub.publish("glasses.connected", device=self.device)
                return self.status()
            self.error = (
                f"Connexion impossible à {name or address} après {attempts} tentative(s) ({last_error}). "
                "Vérifiez que les lunettes sont allumées, à moins de 2 m, et qu'elles ne sont pas déjà connectées "
                "en Bluetooth à un téléphone ou une autre application."
            )
            log.warning(self.error)
            return self.status()
        except Exception as exc:
            self.client = None
            self.error = f"Connexion impossible à {name or address} : {str(exc) or type(exc).__name__}"
            log.warning(self.error)
            return self.status()
        finally:
            self.connecting = False
            self._publish()

    async def _ble_connect(self, BleakClient, target):
        client = BleakClient(target, disconnected_callback=self._on_disconnect, timeout=30.0)
        await client.connect()
        return client

    async def _ble_subscribe(self, client) -> list[dict]:
        services = []
        for service in client.services:
            chars = []
            for char in service.characteristics:
                props = list(char.properties)
                chars.append({"uuid": str(char.uuid), "description": char.description, "properties": props})
                if "notify" in props or "indicate" in props:
                    try:
                        await client.start_notify(char, self._on_notify)
                    except Exception as exc:  # certaines caractéristiques refusent l'abonnement
                        log.debug("notify refusé sur %s: %s", char.uuid, exc)
            services.append({"uuid": str(service.uuid), "description": service.description, "characteristics": chars})
        return services

    async def _read_basics(self, client) -> None:
        try:
            raw = await client.read_gatt_char(DEVICE_NAME_UUID)
            text = raw.decode(errors="ignore").strip()
            if text and self.device:
                self.device["name"] = text
        except Exception:
            pass
        try:
            raw = await client.read_gatt_char(BATTERY_LEVEL_UUID)
            if raw:
                self.battery = int(raw[0])
        except Exception:
            self.battery = None

    # Le canal par lequel les lunettes annoncent leur batterie ; c'est donc par lui qu'on répond.
    CANAL_COMMANDE = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
    # Les caractéristiques du fabricant (ae01, ae03, ae3b) ne sont JAMAIS atteintes par ici : sur
    # ces puces, ce sont elles qui portent la mise à jour du micrologiciel.
    COMMANDES_CONNUES = {0x73}

    async def envoyer_trame(self, commande: int, contenu: bytes = b"") -> dict:
        """Envoie une trame aux lunettes et rapporte ce qui revient, honnêtement.

        Le format est connu et vérifié (voir lunettes_trames.py). Ce qui ne l'est pas, c'est la
        liste des commandes : aucune trame montante n'a jamais obtenu de réponse. Le rapport dit
        donc ce qui a été envoyé et ce qui est revenu — rien de plus, pour qu'IRIS n'invente pas
        un effet qu'elle n'a pas constaté."""
        if not self.connected:
            raise ValueError("Les lunettes ne sont pas connectées.")
        if not 0 <= int(commande) <= 255:
            raise ValueError("La commande doit tenir sur un octet (0 à 255).")
        if int(commande) not in self.COMMANDES_CONNUES and not self.settings.user.lunettes_exploration:
            raise ValueError(
                "Seule la commande 0x73 est connue de ces lunettes. Les autres ne sont pas essayées : "
                "sur cette puce, les commandes voisines portent l'écriture du micrologiciel, et une "
                "séquence mal devinée rendrait les lunettes inutilisables. Pour explorer quand même, "
                "il faut activer « lunettes_exploration » dans les réglages, en connaissance de cause."
            )
        trame = lunettes_trames.fabriquer(int(commande), contenu)
        avant = len(self.packets)
        await self._on_ble(self._ecrire_trame(trame))
        await asyncio.sleep(3.0)  # laisser le temps d'une réponse éventuelle
        revenus = [p["hex"] for p in list(self.packets)[avant:]]
        log.info("trame envoyée aux lunettes : %s — %d réponse(s)", trame.hex(), len(revenus))
        return {
            "envoye": trame.hex(),
            "commande": "0x{:02x}".format(int(commande)),
            "reponses": revenus,
            "constat": "Aucune réponse en 3 secondes." if not revenus else "{} paquet(s) reçus après l'envoi.".format(len(revenus)),
        }

    async def _ecrire_trame(self, trame: bytes) -> None:
        client = self.client
        if client is None:
            raise ValueError("Les lunettes ne sont pas connectées.")
        cible = None
        for service in client.services:
            for car in service.characteristics:
                if str(car.uuid).lower() == self.CANAL_COMMANDE:
                    cible = car
        if cible is None:
            raise ValueError("Ces lunettes n'exposent pas le canal de commande attendu.")
        sans_reponse = "write-without-response" in cible.properties
        await client.write_gatt_char(cible, trame, response=not sans_reponse)

    async def refresh_battery(self) -> int | None:
        if self.connected:
            await self._on_ble(self._read_basics(self.client))
            self._publish()
        return self.battery

    async def disconnect(self) -> dict:
        client = self.client
        self.client = None
        if client is not None:
            try:
                await self._on_ble(client.disconnect())
            except Exception:
                pass
        self.device = None
        self.services = []
        self.battery = None
        self.connected_at = None
        self.hub.publish("glasses.disconnected")
        self._publish()
        return self.status()

    def forget(self) -> None:
        self.settings.update({"glasses": {"address": "", "name": "", "auto_connect": False}})
        self._publish()

    # ------------------------------------------------------------------ callbacks
    def _on_notify(self, sender, data: bytearray) -> None:
        brut = bytes(data)
        packet = {"ts": now_iso(), "uuid": str(getattr(sender, "uuid", sender)), "hex": brut.hex(), "len": len(brut)}
        self.packets.append(packet)
        self.hub.publish("glasses.packet", **packet)
        # Ces lunettes n'exposent aucune caractéristique de batterie standard : la lecture GATT
        # habituelle renvoie vide, et IRIS affichait « batterie inconnue » en permanence. Le niveau
        # n'arrive que dans leur trame maison, décodée dans lunettes_trames.py.
        niveau = lunettes_trames.batterie(brut)
        if niveau is not None and niveau != self.battery:
            self.battery = niveau
            log.info("batterie des lunettes : %s %%", niveau)
            self._publish()
            return
        # Tout autre événement des lunettes est publié tel quel, sans être interprété : personne
        # n'a encore associé un geste à un contenu. C'est ce qui permettra de dresser la table —
        # toucher la branche, regarder quel contenu arrive.
        evenement = lunettes_trames.evenement(brut)
        if evenement is not None:
            log.info("événement des lunettes : %s", evenement["contenu"])
            self.hub.publish("glasses.event", **evenement)

    def _on_disconnect(self, _client) -> None:
        was = self.device
        self.client = None
        self.device = None
        self.services = []
        self.hub.publish("glasses.disconnected", device=was)
        self._publish()
        if self.settings.user.glasses.auto_connect and self.settings.user.glasses.address and self._loop:
            self._reconnect_task = self._loop.create_task(self._reconnect_later())

    async def _reconnect_later(self, delay: float = 5.0) -> None:
        await asyncio.sleep(delay)
        g = self.settings.user.glasses
        if g.auto_connect and g.address and not self.connected:
            await self.connect(g.address, g.name)

    async def auto_connect_on_start(self) -> None:
        g = self.settings.user.glasses
        if g.auto_connect and g.address:
            await self.connect(g.address, g.name)

    async def close(self) -> None:
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self.connected:
            try:
                await self._on_ble(self.client.disconnect())
            except Exception:
                pass
