"""Télécommande : le canal inverse qui laisse le téléphone piloter CET ordinateur, à distance.

L'ordinateur ouvre un WebSocket SORTANT vers le relais (`/appareil/ws`) et s'y annonce avec son
jeton d'appareil. Le relais lui pousse les commandes envoyées par le téléphone du MÊME courriel.
Chaque commande est exécutée ICI, par toute la boucle d'IRIS (`run_and_wait`) : mêmes outils, même
périmètre de fichiers, même règle de confirmation. Une demande d'accord (courriel, SMS, appel,
suppression...) ne s'exécute pas en silence : elle remonte au téléphone, qui répond oui ou non.

Sécurité : opt-in (réglage `telecommande`, désactivé par défaut — une install fraîche n'est jamais
pilotable) ; cloisonné par courriel côté relais ; jeton d'appareil signé ; aucun port ouvert (la
connexion est sortante). Couper le réglage ferme le canal.

Verrouillage à distance (2026-09-13, verrou.py) : le même canal porte aussi les messages « verrou »
({action: verrouiller|effacer, nonce, preuve, defi_page}) venus de la page publique /verrou du relais. La
connexion s'ouvre donc si `telecommande` OU le verrouillage à distance est actif (VerrouIRIS.distant_actif,
dans verrou.json : le désactiver exige le mot de passe) ; quand seul le second l'est, l'ordinateur n'accepte
QUE les messages de verrou et refuse toute commande. La preuve du code de secours est vérifiée ICI (le code,
lui, ne quitte jamais le navigateur de la page). Pendant qu'IRIS est verrouillée, aucune commande distante
n'est exécutée.

Liaison au courriel (constat bloquant du 2026-09-14) : le jeton d'appareil s'obtient pour n'importe quel
courriel, donc une autre machine pouvait se faire passer pour cet ordinateur sur le relais et recevoir les
commandes de verrouillage. Quand le verrouillage à distance est actif, cet ordinateur :
- génère une clé secrète de 32 octets (fichier `telecommande-cle`, jamais envoyée ailleurs qu'au relais) et
  demande sa LIAISON au courriel (POST /api/appareil/liaison) ; le relais envoie un lien de confirmation à
  cette adresse et ne lie rien avant qu'on l'ouvre (`liaison` dit où on en est, l'écran l'affiche) ;
- à chaque connexion, répond au défi du relais (HMAC de la clé sur un nonce) et publie le sel de son code de
  secours ; un ordinateur qui ne prouve pas la clé liée est refusé par le relais ;
- signe la création d'un partage de vision (preuve horodatée, `preuve_horodatee`).

Mode 100 % local (constat du 2026-09-14) : si le verrouillage à distance est actif, le canal reste ouvert
en « verrouillage seulement » (aucune commande du téléphone, aucune donnée : un bonjour signé et les messages
de verrou). Confidentialité le dit.

L'entrée/sortie WebSocket (`run`/`_session`) est isolée de la logique (`_traiter`, `_executer`,
`_on_confirm`, `confirmer`) pour que cette dernière se teste sans réseau.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Callable

log = logging.getLogger("iris.telecommande")

RELIAISON_S = 600.0  # nouvelle demande de liaison au plus toutes les 10 minutes tant qu'elle n'est pas confirmée
MESSAGES_LIAISON = {
    "inconnue": "Liaison au relais pas encore vérifiée.",
    "confirmee": "Cet ordinateur est lié à votre compte : la page /verrou peut l'atteindre.",
    "autre_ordinateur": ("Un autre ordinateur est lié à votre compte sur le relais : la page /verrou ne peut pas "
                         "atteindre celui-ci. Confirmez le courriel de liaison envoyé pour cet ordinateur."),
    "injoignable": "Relais injoignable pour le moment : la liaison sera vérifiée dès qu'il répondra.",
}


class RefusLiaison(Exception):
    """Le relais refuse cet ordinateur : un autre ordinateur est lié au courriel."""


def empreinte_cle(cle: bytes) -> str:
    """Code court de la clé de cet ordinateur (6 caractères base32 de SHA-256). IRIS l'affiche ; la page de
    confirmation du relais demande de le recopier (serveur/relais.py, empreinte_cle : même calcul). Calculé ICI,
    pas lu dans la réponse du relais : c'est la clé de cet ordinateur qui fait foi."""
    return base64.b32encode(hashlib.sha256(cle).digest()).decode("ascii")[:6]


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


class Telecommande:
    def __init__(self, chat, settings, obtenir_jeton: Callable[[], str]):
        self.chat = chat
        self.settings = settings
        self._obtenir_jeton = obtenir_jeton  # () -> jeton d'appareil (str), "" si absent
        self._ws = None
        self._reqs: dict[str, str] = {}  # conv_id réel -> req_id (pour router les demandes d'accord)
        self._stop = False
        self._pairing = ""
        self._cle: bytes | None = None
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._derniere_liaison = 0.0
        # État de la liaison au courriel sur le relais, affiché tel quel par l'écran Verrouillage à distance.
        self.liaison: dict = {"etat": "inconnue", "message": MESSAGES_LIAISON["inconnue"]}
        # Service de verrouillage (verrou.VerrouIRIS), posé par routes_confiance ; None = pas de verrou.
        self.verrou = None
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

    # ------------------------------------------------------------------ clé de l'ordinateur
    def cle(self) -> bytes:
        """Clé secrète de cet ordinateur (32 octets), générée une fois. Elle ne sert qu'à prouver au relais que
        c'est bien l'ordinateur lié au courriel ; la perdre oblige à confirmer une nouvelle liaison."""
        if self._cle:
            return self._cle
        fichier = Path(self.settings.data_dir) / "telecommande-cle"
        try:
            if fichier.is_file():
                brut = _debase64(fichier.read_text(encoding="utf-8").strip())
                if len(brut) == 32:
                    self._cle = brut
                    return brut
            self._cle = secrets.token_bytes(32)
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(_b64(self._cle), encoding="utf-8")
            try:
                import os
                os.chmod(fichier, 0o600)
            except OSError:
                pass
        except Exception as exc:
            log.warning("telecommande : clé de l'ordinateur non enregistrée (%s)", type(exc).__name__)
            self._cle = self._cle or secrets.token_bytes(32)
        return self._cle

    def _courriel(self) -> str:
        """Le courriel tel que le relais le lit : celui du jeton d'appareil (courriel.machine.échéance.signature),
        à défaut celui du compte. Les deux peuvent différer juste après un changement de courriel."""
        try:
            morceaux = (self._obtenir_jeton() or "").rsplit(".", 3)
            if len(morceaux) == 4:
                return _debase64(morceaux[0]).decode("utf-8").strip().lower()
        except Exception:
            pass
        return str(getattr(self.settings.user, "licence_email", "") or "").strip().lower()

    def preuve_defi(self, nonce: str, courriel: str | None = None) -> str:
        courriel = (courriel if courriel is not None else self._courriel()).strip().lower()
        message = f"vela-appareil-ws|v1|{courriel}|{nonce}".encode("utf-8")
        return _b64(hmac.new(self.cle(), message, hashlib.sha256).digest())

    def preuve_horodatee(self, contexte: str) -> dict:
        """Preuve sans aller-retour pour le relais (création d'un partage) : {horodatage, preuve}."""
        instant = int(time.time())
        message = f"{contexte}|v1|{self._courriel()}|{instant}".encode("utf-8")
        return {"horodatage": instant, "preuve": _b64(hmac.new(self.cle(), message, hashlib.sha256).digest())}

    def _poser_liaison(self, etat: str, message: str | None = None) -> None:
        self.liaison = {"etat": etat, "message": message or MESSAGES_LIAISON.get(etat) or ""}

    def empreinte(self) -> str | None:
        """Contre-vérification du 2026-09-14 : le courriel de liaison ne désigne plus l'ordinateur par son nom
        (choisi par l'appelant) ; la page de confirmation demande ce code, que seul l'écran d'IRIS montre."""
        try:
            return empreinte_cle(self.cle())
        except Exception:  # pragma: no cover - clé illisible : l'écran n'affiche pas de code
            return None

    def _base_relais(self) -> str:
        return (self.settings.user.relay_server or "").strip().rstrip("/")

    async def demander_liaison(self, forcer: bool = False) -> dict:
        """POST /api/appareil/liaison : lie cet ordinateur au courriel du jeton (confirmation par courriel côté
        relais). Au plus toutes les RELIAISON_S secondes tant que la liaison n'est pas confirmée. Ne lève pas."""
        maintenant = time.time()
        if not forcer and (self.liaison.get("etat") == "confirmee" or maintenant - self._derniere_liaison < RELIAISON_S):
            return self.liaison
        base, jeton = self._base_relais(), self._obtenir_jeton()
        if not base or not jeton:
            return self.liaison
        self._derniere_liaison = maintenant
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20) as client:
                reponse = await client.post(f"{base}/api/appareil/liaison", json={
                    "jeton": jeton, "cle": _b64(self.cle()), "machine": socket.gethostname()[:64]})
            corps = reponse.json() if reponse.headers.get("content-type", "").startswith("application/json") else {}
            etat = str(corps.get("etat") or ("confirmee" if reponse.status_code == 200 else "inconnue"))
            self._poser_liaison(etat, str(corps.get("message") or "") or None)
        except Exception as exc:
            log.info("telecommande : liaison au relais non vérifiée (%s)", type(exc).__name__)
            self._poser_liaison("injoignable")
        return self.liaison

    def publier_infos_verrou(self) -> None:
        """Le code de secours a changé : le nouveau sel part au relais par le canal ouvert (s'il l'est)."""
        boucle, ws = self._boucle, self._ws
        if boucle is None or ws is None or self.verrou is None:
            return
        message = {"type": "verrou_info", "verrou": self.verrou.infos_preuve()}
        try:
            asyncio.run_coroutine_threadsafe(self._envoyer(message), boucle)
        except RuntimeError:  # pragma: no cover - boucle fermée
            pass

    def relancer(self) -> None:
        """Le verrouillage à distance vient d'être activé : la liaison est demandée tout de suite, et un canal déjà
        ouvert (télécommande) est rouvert pour faire la preuve de la clé."""
        self._derniere_liaison = 0.0
        boucle, ws = self._boucle, self._ws
        if boucle is None or ws is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(ws.close(), boucle)
        except RuntimeError:  # pragma: no cover - boucle fermée
            pass

    # ------------------------------------------------------------------ état
    def url(self) -> str:
        base = self._base_relais()
        if not base:
            return ""
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + "/appareil/ws"
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):] + "/appareil/ws"
        return base + "/appareil/ws"

    def pilotage_permis(self) -> bool:
        """Le téléphone peut-il envoyer des commandes ? Seulement si l'utilisateur a activé la télécommande, et
        jamais en mode 100 % local (le canal n'y sert qu'au verrouillage)."""
        return bool(getattr(self.settings.user, "telecommande", False)) and not bool(
            getattr(self.settings.user, "local_only", False))

    def verrou_distant_permis(self) -> bool:
        """L'activation fait foi dans verrou.json (VerrouIRIS.distant_actif) : la désactiver exige le mot de
        passe, alors qu'un réglage ordinaire se couperait depuis une session laissée ouverte. Le réglage
        n'est lu qu'en l'absence du service de verrouillage (qui répond alors « indisponible »)."""
        actif = getattr(self.verrou, "distant_actif", None) if self.verrou is not None else None
        if actif is None:
            return bool(getattr(self.settings.user, "verrou_distant_actif", False))
        return bool(actif)

    def actif(self) -> bool:
        """Le canal ne s'ouvre que si l'utilisateur a activé la télécommande OU le verrouillage à distance,
        ET qu'un relais + un jeton existent. Les deux sont désactivés par défaut : c'est le coupe-circuit. En
        mode 100 % local, seul le verrouillage à distance le garde ouvert (« verrouillage seulement »)."""
        if not self.url() or not self._obtenir_jeton():
            return False
        if self.settings.user.local_only:
            return self.verrou_distant_permis()
        return self.pilotage_permis() or self.verrou_distant_permis()

    @property
    def connecte(self) -> bool:
        return self._ws is not None

    def _verrouillee(self) -> bool:
        return bool(getattr(self.verrou, "verrouille", False))

    # ------------------------------------------------------------------ logique (testable sans réseau)
    async def _traiter(self, msg: dict) -> None:
        """Aiguille un message reçu du relais."""
        t = msg.get("type")
        boucle = asyncio.get_running_loop()
        if t == "commande":
            req_id = str(msg.get("req_id") or uuid.uuid4().hex)
            refus = None
            if not self.pilotage_permis():
                refus = "La télécommande est désactivée sur cet ordinateur."
            elif self._verrouillee():
                refus = "IRIS est verrouillée : aucune commande à distance n'est exécutée."
            if refus:
                boucle.create_task(self._envoyer({"type": "resultat", "req_id": req_id, "reponse": refus}))
                return
            boucle.create_task(self._executer(req_id, str(msg.get("texte") or "")))
        elif t == "confirm_reponse":
            if self.pilotage_permis() and not self._verrouillee():
                self.confirmer(str(msg.get("confirm_id") or ""), bool(msg.get("approved")))
        elif t == "verrou":
            req_id = str(msg.get("req_id") or uuid.uuid4().hex)
            lot: dict = {}
            reste = msg.get("reste")
            if msg.get("differee") and msg.get("lot") and isinstance(reste, int) and not isinstance(reste, bool):
                # Commande livrée depuis la file du relais : ses échecs se jugent par lot (verrou.py).
                lot = {"differee": True, "lot": str(msg.get("lot"))[:64], "reste": reste}
            boucle.create_task(self._verrou_distant(
                req_id, str(msg.get("action") or ""), str(msg.get("preuve") or ""), str(msg.get("nonce") or ""),
                str(msg.get("defi_page") or ""), **lot))

    async def _verrou_distant(self, req_id: str, action: str, preuve: str, nonce: str, defi_page: str, **lot) -> None:
        """Verrouiller ou effacer à la demande de la page /verrou du relais. Seule une preuve du code arrive ici
        (jamais le code) ; elle n'est ni journalisée ni conservée."""
        if not self.verrou_distant_permis():
            resultat = {"ok": False, "etat": "desactive",
                        "message": "Le verrouillage à distance est désactivé sur cet ordinateur."}
        elif self.verrou is None:
            resultat = {"ok": False, "etat": "indisponible",
                        "message": "Le verrouillage n'est pas disponible sur cet ordinateur."}
        elif not preuve or not nonce:
            resultat = {"ok": False, "etat": "protocole_perime",
                        "message": "Commande d'un ancien format refusée : rechargez la page de verrouillage."}
        else:
            try:
                resultat = await self.verrou.commande_distante(action, preuve, nonce, defi_page, **lot)
            except Exception as exc:  # commande_distante ne lève pas ; défense quand même
                log.info("telecommande : verrou distant en erreur (%s)", exc)
                resultat = {"ok": False, "etat": "erreur", "message": "L'ordinateur n'a pas pu exécuter la commande."}
        await self._envoyer({"type": "resultat", "req_id": req_id, "verrou": True, **resultat})

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

    async def _poignee_de_main(self, ws, jeton: str, code: str) -> dict:
        """hello → (defi → preuve) → pret. Renvoie le message « pret » ; lève si le relais refuse."""
        await ws.send(json.dumps({"type": "hello", "jeton": jeton, "pairing": code, "preuve": 1}))
        premier = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if premier.get("type") == "defi":
            infos = self.verrou.infos_preuve() if self.verrou is not None else None
            await ws.send(json.dumps({"type": "preuve", "preuve": self.preuve_defi(str(premier.get("nonce") or "")),
                                      "verrou": infos}))
            premier = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if premier.get("type") == "refus":
            self._poser_liaison("autre_ordinateur", str(premier.get("message") or "") or None)
            raise RefusLiaison("le relais refuse cet ordinateur : un autre ordinateur est lié au courriel")
        if premier.get("type") != "pret":
            raise ConnectionError("le relais n'a pas accepté la connexion")
        if premier.get("prouve"):
            self._poser_liaison("confirmee")
        elif premier.get("liaison") == "absente" and self.liaison.get("etat") == "confirmee":
            self._poser_liaison("inconnue")
        return premier

    # ------------------------------------------------------------------ boucle réseau
    async def run(self) -> None:
        """Boucle de vie : (re)connexion tant que la télécommande est active. Ne lève jamais."""
        import websockets  # import tardif : la télécommande peut être absente sans casser le démarrage

        self._boucle = asyncio.get_running_loop()
        while not self._stop:
            if not self.actif():
                await asyncio.sleep(5)
                continue
            url = self.url()
            jeton = self._obtenir_jeton()
            attente = 5
            if self.verrou_distant_permis() and self.liaison.get("etat") != "confirmee":
                await self.demander_liaison()
            try:
                async with websockets.connect(url, max_size=2**20, open_timeout=15) as ws:
                    self._ws = ws
                    code = self.pairing()
                    await self._poignee_de_main(ws, jeton, code)
                    log.info("telecommande : connectee au relais. Code d'appairage a saisir dans le telephone : %s", code)
                    async for brut in ws:
                        if self._stop or not self.actif():  # coupe-circuit
                            break
                        try:
                            await self._traiter(json.loads(brut))
                        except Exception as exc:  # pragma: no cover - défense
                            log.info("telecommande : message ignore (%s)", exc)
            except RefusLiaison as exc:
                log.info("telecommande : %s", exc)
                attente = 60  # un autre ordinateur est lié : inutile de réessayer toutes les 5 secondes
            except Exception as exc:
                log.info("telecommande : deconnectee (%s), nouvelle tentative bientot", exc)
            finally:
                self._ws = None
            await asyncio.sleep(attente)  # petit délai avant de retenter

    def arreter(self) -> None:
        self._stop = True
