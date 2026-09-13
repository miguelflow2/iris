"""Zones sans mémoire : dans un lieu choisi (clinique, bureau d'un client…), IRIS ne retient rien.

Principe (interface I, 2026-09-13). L'utilisateur déclare des cercles (centre + rayon) dans le réglage
`zones_sans_memoire`. Quand un appareil signale qu'il est dans l'un d'eux, la mémoire est suspendue
(`ctx.memory.suspendre("zone:<nom>")`) : ni souvenirs, ni journal, ni cours, ni photos décrites, ni
reçus. À la sortie, elle reprend.

La position est une donnée sensible, d'où ces règles :
- le TÉLÉPHONE évalue lui-même sa position contre la liste des zones et n'envoie QUE l'identifiant de
  la zone (ou null) : la position ne quitte pas le téléphone ;
- quand un appareil ne sait pas évaluer (POST /api/confiance/position), la position est comparée ici
  puis oubliée sur-le-champ : jamais écrite, jamais journalisée, jamais publiée ;
- la position de l'ordinateur (Windows) n'est lue qu'à la demande explicite de l'utilisateur.

Limites dites telles quelles :
- rien ne tourne en arrière-plan : c'est l'appareil qui signale l'entrée et la sortie. Tant qu'il n'a
  pas signalé la sortie, la mémoire reste suspendue (c'est le côté sûr de l'erreur) ;
- l'état n'est pas conservé : après un redémarrage d'IRIS, l'appareil doit signaler la zone de nouveau ;
- une position imprécise compte comme « peut-être dans la zone » jusqu'à un rayon de plus (on préfère
  suspendre la mémoire à tort que retenir à tort).
"""
from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
import threading
import uuid
from typing import Any

log = logging.getLogger("iris.zones")

RAYON_MIN_M = 30
RAYON_MAX_M = 5000
NOM_MAX = 60
ZONES_MAX = 50
SOURCES = ("telephone", "pc")
RAYON_TERRE_M = 6_371_000.0
DELAI_POSITION_PC_S = 12

LIMITE = (
    "C'est l'appareil qui signale l'entrée et la sortie de zone : tant que la sortie n'est pas signalée, "
    "la mémoire reste suspendue. Après un redémarrage d'IRIS, la zone doit être signalée de nouveau."
)
POSITION_PC_INDISPONIBLE = (
    "La position de cet ordinateur n'est pas disponible : activez la localisation de Windows "
    "(Paramètres › Confidentialité › Position) ou utilisez la position du téléphone."
)


class RefusZone(Exception):
    def __init__(self, message: str, code: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à la surface de la Terre (formule de haversine), en mètres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(min(1.0, math.sqrt(a)))


def _nombre(valeur: Any, nom: str, minimum: float, maximum: float) -> float:
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        raise RefusZone(f"{nom} invalide.")
    if not math.isfinite(nombre) or not minimum <= nombre <= maximum:
        raise RefusZone(f"{nom} hors limites ({minimum:g} à {maximum:g}).")
    return nombre


class ZonesSansMemoire:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._verrou = threading.RLock()
        self._par_source: dict[str, str | None] = {}  # source -> identifiant de zone signalée
        self._suspendues: dict[str, str] = {}  # identifiant de zone -> raison posée dans la mémoire
        self.lire_position_pc = lire_position_windows  # remplaçable (tests, autre OS)

    # ------------------------------------------------------------------ liste
    def zones(self) -> list[dict]:
        propres = []
        for z in list(getattr(self.ctx.settings.user, "zones_sans_memoire", []) or []):
            if isinstance(z, dict) and z.get("id") and z.get("nom"):
                propres.append(z)
        return propres

    def _zone(self, zone_id: str | None) -> dict | None:
        return next((z for z in self.zones() if z.get("id") == zone_id), None) if zone_id else None

    def _enregistrer(self, zones: list[dict]) -> None:
        user = self.ctx.settings.update({"zones_sans_memoire": zones})
        try:
            self.ctx.hub.publish("settings.updated", settings=user.model_dump())
        except Exception as exc:  # pragma: no cover
            log.debug("zones : publication des réglages (%s)", exc)

    def creer(self, nom: Any, lat: Any, lon: Any, rayon_m: Any) -> dict:
        nom = " ".join(str(nom or "").split())[:NOM_MAX]
        if not nom:
            raise RefusZone("Donnez un nom à la zone.")
        zone = {
            "id": uuid.uuid4().hex[:12],
            "nom": nom,
            "lat": round(_nombre(lat, "Latitude", -90, 90), 6),
            "lon": round(_nombre(lon, "Longitude", -180, 180), 6),
            "rayon_m": int(round(_nombre(rayon_m, "Rayon", RAYON_MIN_M, RAYON_MAX_M))),
        }
        with self._verrou:
            zones = self.zones()
            if len(zones) >= ZONES_MAX:
                raise RefusZone(f"Au plus {ZONES_MAX} zones.", 409)
            if any(z["nom"].lower() == nom.lower() for z in zones):
                raise RefusZone("Une zone porte déjà ce nom.", 409)
            self._enregistrer(zones + [zone])
        return zone

    def supprimer(self, zone_id: str) -> bool:
        with self._verrou:
            zones = self.zones()
            restantes = [z for z in zones if z.get("id") != zone_id]
            if len(restantes) == len(zones):
                return False
            self._enregistrer(restantes)
            for source, signalee in list(self._par_source.items()):
                if signalee == zone_id:
                    self._par_source[source] = None
            self.reconcilier()
        return True

    def effacer_tout(self) -> int:
        with self._verrou:
            n = len(self.zones())
            if n:
                self._enregistrer([])
            self._par_source.clear()
            self.reconcilier()
        return n

    # ------------------------------------------------------------------ présence dans une zone
    def signaler(self, zone_id: str | None, source: str) -> dict:
        """Un appareil signale la zone où il se trouve (identifiant seulement, ou None pour « aucune »)."""
        if source not in SOURCES:
            raise RefusZone("Source inconnue : telephone ou pc.")
        with self._verrou:
            if zone_id and self._zone(zone_id) is None:
                raise RefusZone("Zone inconnue.", 404)
            self._par_source[source] = zone_id or None
            self.reconcilier()
            return self.etat()

    def evaluer_position(self, lat: Any, lon: Any, precision_m: Any = None) -> dict | None:
        """La zone qui contient cette position, ou None. La position n'est ni gardée ni journalisée.

        Une position imprécise compte comme « peut-être dedans » jusqu'à un rayon de plus."""
        la = _nombre(lat, "Latitude", -90, 90)
        lo = _nombre(lon, "Longitude", -180, 180)
        try:
            precision = max(0.0, float(precision_m)) if precision_m is not None else 0.0
        except (TypeError, ValueError):
            precision = 0.0
        meilleure: tuple[float, dict] | None = None
        for z in self.zones():
            try:
                d = distance_m(la, lo, float(z["lat"]), float(z["lon"]))
                rayon = float(z["rayon_m"])
            except (KeyError, TypeError, ValueError):
                continue
            if d <= rayon + min(precision, rayon):
                marge = d - rayon
                if meilleure is None or marge < meilleure[0]:
                    meilleure = (marge, z)
        return meilleure[1] if meilleure else None

    def signaler_position(self, lat: Any, lon: Any, precision_m: Any = None, source: str = "telephone") -> dict:
        zone = self.evaluer_position(lat, lon, precision_m)
        return self.signaler(zone["id"] if zone else None, source)

    def reconcilier(self) -> None:
        """Aligne les suspensions de la mémoire sur les zones signalées (et encore existantes)."""
        memoire = getattr(self.ctx, "memory", None)
        with self._verrou:
            existantes = {z["id"]: z for z in self.zones()}
            for source, zone_id in list(self._par_source.items()):
                if zone_id and zone_id not in existantes:
                    self._par_source[source] = None
            voulues = {zid for zid in self._par_source.values() if zid}
            avant = bool(self._suspendues)
            nom_avant = self._nom_actif()
            for zid in list(self._suspendues):
                if zid not in voulues:
                    raison = self._suspendues.pop(zid)
                    if memoire is not None:
                        memoire.reprendre(raison)
            for zid in sorted(voulues):
                if zid not in self._suspendues:
                    raison = f"zone:{existantes[zid]['nom']}"
                    self._suspendues[zid] = raison
                    if memoire is not None:
                        memoire.suspendre(raison)
            apres = bool(self._suspendues)
            nom_apres = self._nom_actif()
        if avant != apres or nom_avant != nom_apres:
            try:
                self.ctx.hub.publish("zone.etat", dans_zone=apres, zone_nom=nom_apres)
            except Exception as exc:  # pragma: no cover
                log.debug("zones : publication de l'état (%s)", exc)
            # Rien dans le registre de confidentialité ni dans le journal : l'heure d'entrée dans une
            # zone sensible est déjà une information de position.

    def _nom_actif(self) -> str | None:
        if not self._suspendues:
            return None
        return sorted(r.split(":", 1)[1] for r in self._suspendues.values())[0]

    def zone_active(self) -> dict | None:
        with self._verrou:
            if not self._suspendues:
                return None
            zones = {z["id"]: z for z in self.zones()}
            actives = sorted((zones[zid] for zid in self._suspendues if zid in zones), key=lambda z: z["nom"])
            return {"id": actives[0]["id"], "nom": actives[0]["nom"]} if actives else None

    def etat(self) -> dict:
        return {"zones": self.zones(), "zone_active": self.zone_active(), "limite": LIMITE}

    def arreter(self) -> None:
        """À l'arrêt d'IRIS : lever les suspensions posées par les zones (l'état n'est pas conservé)."""
        with self._verrou:
            self._par_source.clear()
            self.reconcilier()

    # ------------------------------------------------------------------ position de l'ordinateur
    def position_pc(self) -> dict:
        """Lecture ponctuelle (bloquante : à appeler dans un fil). Lève RefusZone(409) si indisponible."""
        if self.ctx.settings.user.privacy_mode:
            raise RefusZone("Mode confidentiel actif : la position de l'ordinateur n'est pas lue.", 409)
        try:
            position = self.lire_position_pc()
        except Exception as exc:
            log.info("position de l'ordinateur indisponible (%s)", exc)
            position = None
        if not position:
            raise RefusZone(POSITION_PC_INDISPONIBLE, 409)
        try:
            self.ctx.consent.log("position_pc_lue")  # le fait, jamais la position
        except Exception:  # pragma: no cover
            pass
        return position


def lire_position_windows() -> dict | None:
    """Position de l'ordinateur par le service de localisation de Windows, ou None.

    Deux chemins, sans dépendance ajoutée : le composant winrt de géolocalisation s'il est présent,
    sinon l'API de localisation de .NET (System.Device) par PowerShell. Les deux respectent le réglage
    de confidentialité « Position » de Windows : s'il est coupé, la réponse est None."""
    if sys.platform != "win32":
        return None
    try:
        return _position_winrt()
    except ImportError:
        pass
    except Exception as exc:
        log.info("géolocalisation winrt : %s", exc)
    script = (
        "Add-Type -AssemblyName System.Device;"
        "$w = New-Object System.Device.Location.GeoCoordinateWatcher('High');"
        "$null = $w.TryStart($false, [TimeSpan]::FromSeconds(3));"
        "$fin = (Get-Date).AddSeconds(8);"
        "while ($w.Position.Location.IsUnknown -and (Get-Date) -lt $fin) { Start-Sleep -Milliseconds 250 };"
        "$c = $w.Position.Location; $w.Stop();"
        "if ($c.IsUnknown) { 'null' } else { "
        "@{lat=$c.Latitude; lon=$c.Longitude; precision_m=$c.HorizontalAccuracy} | ConvertTo-Json -Compress }"
    )
    try:
        sortie = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=DELAI_POSITION_PC_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log.info("géolocalisation Windows : %s", exc)
        return None
    try:
        donnees = json.loads((sortie.stdout or "").strip() or "null")
    except ValueError:
        return None
    if not isinstance(donnees, dict):
        return None
    try:
        return {"lat": float(donnees["lat"]), "lon": float(donnees["lon"]),
                "precision_m": float(donnees.get("precision_m") or 0)}
    except (KeyError, TypeError, ValueError):
        return None


def _position_winrt() -> dict | None:
    import asyncio

    from winrt.windows.devices.geolocation import Geolocator  # type: ignore[import-not-found]

    async def lire() -> dict | None:
        position = await Geolocator().get_geoposition_async()
        point = position.coordinate.point.position
        return {"lat": float(point.latitude), "lon": float(point.longitude),
                "precision_m": float(position.coordinate.accuracy or 0)}

    return asyncio.run(asyncio.wait_for(lire(), timeout=DELAI_POSITION_PC_S))
