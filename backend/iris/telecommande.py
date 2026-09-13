"""Télécommande : le canal inverse qui laisse le téléphone piloter CET ordinateur, à distance.

L'ordinateur ouvre un WebSocket SORTANT vers le relais (`/appareil/ws`) et s'y annonce avec son
jeton d'appareil. Le relais lui pousse les commandes envoyées par le téléphone du MÊME courriel.
Chaque commande est exécutée ICI, par toute la boucle d'IRIS (`run_and_wait`) : mêmes outils, même
périmètre de fichiers, même règle de confirmation. Une demande d'accord (courriel, SMS, appel,
suppression...) ne s'exécute pas en silence : elle remonte au téléphone, qui répond oui ou non.

Sécurité : opt-in (réglage `telecommande`, désactivé par défaut — une install fraîche n'est jamais
pilotable) ; cloisonné par courriel côté relais ; jeton d'appareil signé ; aucun port ouvert (la
connexion est sortante). Couper le réglage ferme le canal.

L'entrée/sortie WebSocket (`run`/`_session`) est isolée de la logique (`_traiter`, `_executer`,
`_on_confirm`, `confirmer`) pour que cette dernière se teste sans réseau.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Callable

log = logging.getLogger("iris.telecommande")


class Telecommande:
    def __init__(self, chat, settings, obtenir_jeton: Callable[[], str]):
        self.chat = chat
        self.settings = settings
        self._obtenir_jeton = obtenir_jeton  # () -> jeton d'appareil (str), "" si absent
        self._ws = None
        self._reqs: dict[str, str] = {}  # conv_id réel -> req_id (pour router les demandes d'accord)
        self._stop = False
        self._pairing = ""
        chat.set_sink_confirm_distant(self._on_confirm)

    def pairing(self) -> str:
        """Le code d'appairage de cet ordinateur : le SECOND facteur qu'un téléphone doit présenter
        pour piloter la machine (connaître le courriel ne suffit pas). Généré une fois, persistant.

        Affiché à l'utilisateur (journal + fichier `telecommande-pairing`) : c'est lui qui le saisit
        dans le téléphone. Le supprimer force un nouveau code (revocation simple)."""
        if self._pairing:
            return self._pairing
        try:
            fichier = Path(self.settings.data_dir) / "telecommande-pairing"
            if fichier.is_file():
                self._pairing = fichier.read_text(encoding="utf-8").strip()
            if not self._pairing:
                self._pairing = uuid.uuid4().hex[:8]
                fichier.parent.mkdir(parents=True, exist_ok=True)
                fichier.write_text(self._pairing, encoding="utf-8")
                try:
                    import os
                    os.chmod(fichier, 0o600)
                except OSError:
                    pass
        except Exception:
            # Pas de disque accessible : un code de session, mieux que pas de second facteur du tout.
            self._pairing = self._pairing or uuid.uuid4().hex[:8]
        return self._pairing

    # ------------------------------------------------------------------ état
    def url(self) -> str:
        base = (self.settings.user.relay_server or "").strip().rstrip("/")
        if not base:
            return ""
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + "/appareil/ws"
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):] + "/appareil/ws"
        return base + "/appareil/ws"

    def actif(self) -> bool:
        """La télécommande ne tourne que si l'utilisateur l'a activée ET qu'un relais + un jeton
        existent. Désactivée par défaut : c'est le coupe-circuit."""
        return (
            bool(getattr(self.settings.user, "telecommande", False))
            and not self.settings.user.local_only
            and bool(self.url())
            and bool(self._obtenir_jeton())
        )

    # ------------------------------------------------------------------ logique (testable sans réseau)
    async def _traiter(self, msg: dict) -> None:
        """Aiguille un message reçu du relais."""
        t = msg.get("type")
        if t == "commande":
            req_id = str(msg.get("req_id") or uuid.uuid4().hex)
            asyncio.get_running_loop().create_task(self._executer(req_id, str(msg.get("texte") or "")))
        elif t == "confirm_reponse":
            self.confirmer(str(msg.get("confirm_id") or ""), bool(msg.get("approved")))

    async def _executer(self, req_id: str, texte: str) -> None:
        """Exécute une commande via toute la boucle d'IRIS, puis renvoie le résultat au téléphone."""
        conv_id = None
        reponse = ""
        try:
            conv = self.chat.create_conversation(title="Télécommande", agent="auto", kind="remote")
            conv_id = conv["id"]
            self._reqs[conv_id] = req_id  # pour router une éventuelle demande d'accord vers ce téléphone
            res = await self.chat.run_and_wait(conv_id, texte, agent="auto", source="distant")
            message = (res or {}).get("message") or {}
            reponse = (message.get("text") if isinstance(message, dict) else str(message)) or (res or {}).get("error") or ""
        except Exception as exc:
            reponse = "Je n'ai pas pu exécuter cette commande."
            log.info("telecommande : echec de la commande %s (%s)", req_id, exc)
        finally:
            if conv_id:
                self._reqs.pop(conv_id, None)
            await self._envoyer({"type": "resultat", "req_id": req_id, "reponse": reponse})

    def _on_confirm(self, conv_id: str, confirm_id: str, title: str, detail: str) -> None:
        """Sink appelé par ChatService quand une commande distante réclame un accord : on relaie la
        question au téléphone qui a lancé cette commande. La réponse reviendra via `confirmer`."""
        req_id = self._reqs.get(conv_id)
        if not req_id:
            return
        message = {"type": "confirm", "req_id": req_id, "confirm_id": confirm_id, "title": title, "detail": detail}
        try:
            asyncio.get_running_loop().create_task(self._envoyer(message))
        except RuntimeError:  # pas de boucle (contexte de test synchrone) : ignoré
            pass

    def confirmer(self, confirm_id: str, approved: bool) -> None:
        """Le téléphone a répondu oui/non : on résout le même futur que l'écran et la voix."""
        try:
            self.chat.resolve_confirm(confirm_id, approved)
        except Exception as exc:  # pragma: no cover - défense
            log.info("telecommande : accord %s non résolu (%s)", confirm_id, exc)

    async def _envoyer(self, message: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(message))
        except Exception as exc:  # pragma: no cover - défense
            log.info("telecommande : envoi impossible (%s)", exc)

    # ------------------------------------------------------------------ boucle réseau
    async def run(self) -> None:
        """Boucle de vie : (re)connexion tant que la télécommande est active. Ne lève jamais."""
        import websockets  # import tardif : la télécommande peut être absente sans casser le démarrage

        while not self._stop:
            if not self.actif():
                await asyncio.sleep(5)
                continue
            url = self.url()
            jeton = self._obtenir_jeton()
            try:
                async with websockets.connect(url, max_size=2**20, open_timeout=15) as ws:
                    self._ws = ws
                    code = self.pairing()
                    await ws.send(json.dumps({"type": "hello", "jeton": jeton, "pairing": code}))
                    premier = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                    if premier.get("type") != "pret":
                        continue
                    log.info("telecommande : connectee au relais. Code d'appairage a saisir dans le telephone : %s", code)
                    async for brut in ws:
                        if self._stop or not self.actif():  # coupe-circuit
                            break
                        try:
                            await self._traiter(json.loads(brut))
                        except Exception as exc:  # pragma: no cover - défense
                            log.info("telecommande : message ignore (%s)", exc)
            except Exception as exc:
                log.info("telecommande : deconnectee (%s), nouvelle tentative bientot", exc)
            finally:
                self._ws = None
            await asyncio.sleep(5)  # petit délai avant de retenter

    def arreter(self) -> None:
        self._stop = True
