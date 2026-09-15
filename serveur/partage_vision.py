"""Vision partagée en direct, côté relais : un proche (ou un technicien) voit ce que voit l'utilisateur.

Le scénario : une personne malvoyante est dehors ou devant un appareil qu'elle ne sait pas lire. Son IRIS
crée une session ici, envoie des images JPEG (écran du PC, photos des lunettes, caméra du téléphone), et
un proche ouvre le lien /voir/{code} dans n'importe quel navigateur. Le proche peut écrire ou dicter un
message, que l'ordinateur ou le téléphone lit à voix haute.

Ce que le relais fait, et ne fait pas :
- il transmet, il ne garde pas : aucune image n'est écrite sur le disque ni gardée en mémoire au-delà de
  la file d'envoi de chaque spectateur (2 images au plus, la plus vieille est jetée si le réseau du
  spectateur est lent — mieux vaut une image fraîche qu'un retard qui s'accumule) ;
- les sessions vivent en mémoire : un redémarrage du relais les ferme toutes, et l'émetteur doit en
  recréer une ;
- l'émetteur est authentifié par un jeton de 32 octets reçu à la création, qui n'est gardé que sous
  forme d'empreinte (SHA-256) ; la création exige un jeton d'appareil VELA valide (relais.lire_jeton) ;
- le spectateur n'a que le code à 8 caractères (alphabet sans 0/O, 1/I/L), tiré par `secrets` : environ
  8 × 10¹¹ possibilités, et 10 essais ratés par 15 minutes au plus par adresse IP ;
- bornes : 3 spectateurs, 10 images par seconde, 300 Ko par image, JPEG seulement, 30 minutes de vie
  renouvelables par l'émetteur, 2 sessions par compte ET par adresse IP de création, 100 sessions en tout ;
- constat du 2026-09-14 : le jeton d'appareil s'obtient pour n'importe quel courriel, et « la plus vieille
  session est remplacée » laissait un tiers fermer en boucle le partage d'une personne malvoyante en pleine
  aide à distance. Désormais une session dont l'émetteur est connecté (ou l'a été dans la dernière minute,
  ou créée depuis moins d'une minute) n'est JAMAIS remplacée : la création répond 409 « un partage est déjà
  en cours sur ce compte » ; et quand un ordinateur est lié au compte (relais.liaison_confirmee), la création
  exige sa preuve horodatée (relais.verifier_preuve_horodatee).
  Contre-vérification du 2026-09-14 : le quota de 5 créations par 15 minutes était compté par COMPTE, donc
  partagé avec quiconque connaît le courriel ; un tiers l'épuisait sans fin et la victime recevait 429. Il est
  maintenant compté par (compte, adresse IP) : les créations d'un tiers n'entament pas celui de la victime.
  Finition B du 2026-09-14 : SESSIONS_PAR_COMPTE restait compté par compte seul. Depuis UNE adresse, un tiers
  gardait deux émetteurs connectés et la victime (compte sans ordinateur lié : tous, tant que le courriel de
  liaison n'est pas en service) recevait 409 aussi longtemps qu'il renouvelait, avec un « réessayez dans une
  minute » faux. La limite est maintenant comptée par (compte, adresse IP de création) : les partages d'un tiers
  ne prennent pas la place de ceux de la victime, et « réessayez dans une minute » n'est dit que lorsqu'une
  session cédera réellement sa place au bout d'une minute. Limite dite : derrière une même adresse (même
  réseau Wi-Fi public), un tiers et la victime partagent ce plafond ; lier l'ordinateur (preuve exigée) supprime
  ce revers ;
- aucun code, jeton ni courriel n'est écrit dans les journaux.

Le module ne modifie pas relais.py : il reçoit le module relais lui-même (lire_jeton, normaliser).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("vela.partage_vision")

ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # ni 0/O, ni 1/I/L : un code se lit et se dicte sans ambiguïté
LONGUEUR_CODE = 8
DUREE_SESSION_S = 30 * 60.0
TAILLE_MAX_IMAGE = 300_000  # octets
IMAGES_PAR_SECONDE_MAX = 10
SPECTATEURS_MAX = 3
CONTROLES_MAX = 2
SESSIONS_PAR_COMPTE = 2
SESSIONS_MAX = 100
IMAGES_EN_FILE = 2  # par spectateur : au-delà, la plus vieille est jetée
MESSAGES_EN_FILE = 50
MESSAGE_MAX = 500  # caractères
MESSAGES_PAR_FENETRE = 5
FENETRE_MESSAGES_S = 10.0
ECHECS_MAX = 10
FENETRE_ECHECS_S = 900.0  # 15 minutes
CREATIONS_MAX = 20  # par adresse IP
CREATIONS_PAR_COMPTE = 5  # par (compte, adresse IP) : un tiers n'épuise pas le quota de la victime
REMPLACEMENT_SANS_EMETTEUR_S = 60.0
FENETRE_CREATIONS_S = 900.0
DELAI_HELLO_S = 15.0
TIC_S = 5.0  # cadence des états envoyés et de la vérification d'expiration sur chaque connexion
FENETRE_CADENCE_S = 30.0
SOURCES = ("lunettes", "ecran", "telephone")
SEL_ADRESSES = secrets.token_hex(16)  # tiré au démarrage : les empreintes d'adresses ne vivent qu'en mémoire
DEBUT_JPEG = b"\xff\xd8\xff"

# Codes de fermeture WebSocket (plage 4000-4999 réservée aux applications).
FERMETURE_REMPLACE = 4000
FERMETURE_REFUS = 4001
FERMETURE_COMPLET = 4003
FERMETURE_INCONNU = 4004
FERMETURE_FIN = 4010
FERMETURE_TENTATIVES = 4029

MESSAGES_FIN = {
    "expiree": "Le partage a expiré : 30 minutes sont passées sans prolongation.",
    "arrete": "Votre proche a arrêté le partage.",
    "remplacee": "Ce partage a été remplacé par un nouveau lien.",
}
MESSAGE_DEJA_EN_COURS = (
    "Un partage est déjà en cours sur ce compte : arrêtez-le avant d'en créer un autre, ou réessayez dans une minute."
)
# Les sessions qui occupent la place sont en service (émetteur connecté) : aucune ne cédera d'elle-même dans une minute.
MESSAGE_DEJA_EN_SERVICE = (
    "Deux partages sont déjà en cours sur ce compte depuis cette connexion Internet, et leurs émetteurs sont "
    "connectés : arrêtez-en un avant d'en créer un autre."
)
MESSAGE_PC_NON_LIE = "Cet appareil n'est pas l'ordinateur lié à ce compte VELA : le partage n'est pas créé."
MESSAGE_INCONNU = "Ce lien de partage n'existe pas ou a expiré. Demandez un nouveau lien à votre proche."
MESSAGE_COMPLET = "Trois personnes regardent déjà ce partage : c'est le maximum. Réessayez plus tard."
_HOTE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")


def maintenant() -> float:
    """L'horloge du module (remplaçable dans les tests pour simuler l'expiration)."""
    return time.time()


def iso(horodatage: float) -> str:
    return datetime.fromtimestamp(horodatage, timezone.utc).isoformat(timespec="seconds")


def normaliser_code(brut: str) -> str:
    """« abcd-efgh » ou « ABCD EFGH » : un code dicté ou recopié avec un tiret reste le même code."""
    return re.sub(r"[\s\-]", "", str(brut or "")).upper()[:32]


def code_valide(code: str) -> bool:
    return len(code) == LONGUEUR_CODE and all(c in ALPHABET_CODE for c in code)


def generer_code() -> str:
    return "".join(secrets.choice(ALPHABET_CODE) for _ in range(LONGUEUR_CODE))


def empreinte(jeton: str) -> str:
    return hashlib.sha256(str(jeton or "").encode("utf-8")).hexdigest()


def cadence(horodatages, t: float) -> float:
    """Images par seconde réellement observées sur les 30 dernières secondes. Si le flux s'est arrêté,
    la mesure baisse au lieu de figer la dernière valeur : on ne montre pas une cadence qui n'existe plus."""
    recents = [h for h in horodatages if h > t - FENETRE_CADENCE_S]
    if len(recents) < 2:
        return 0.0
    ecart = recents[-1] - recents[0]
    moyen = ecart / (len(recents) - 1)
    if t - recents[-1] > max(3 * moyen, 2.0):
        ecart = t - recents[0]
    return round((len(recents) - 1) / ecart, 2) if ecart > 0 else 0.0


def nettoyer_message(brut: Any) -> str:
    """Texte d'un spectateur : sans caractères de contrôle, espaces réduits, 500 caractères au plus.
    Il sera lu à voix haute : on ne transmet rien d'autre que du texte simple."""
    texte = "".join(c if c.isprintable() else " " for c in str(brut or ""))
    return " ".join(texte.split())[:MESSAGE_MAX]


def _adresse_ip(entetes, client) -> str:
    """Derrière le mandataire de l'hébergeur, request.client est le mandataire, le même pour tout le
    monde : on prend la DERNIÈRE entrée de X-Forwarded-For, celle qu'ajoute le mandataire le plus proche."""
    transmis = entetes.get("x-forwarded-for", "") or ""
    if transmis.strip():
        return transmis.split(",")[-1].strip()[:64]
    return ((client.host if client else "") or "inconnue")[:64]


class _Canal:
    """Une connexion WebSocket et sa file d'envoi.

    Chaque connexion a sa propre tâche d'envoi : un spectateur au réseau lent ne ralentit ni l'émetteur
    ni les autres spectateurs. `deposer` est appelable depuis une autre boucle (serveur de test) : il
    repasse alors par la boucle propriétaire de la connexion."""

    def __init__(self, ws: WebSocket, role: str, tic=None) -> None:
        self.ws = ws
        self.role = role
        self.boucle = asyncio.get_running_loop()
        self.images: deque[bytes] = deque(maxlen=IMAGES_EN_FILE)
        self.messages: deque[dict] = deque(maxlen=MESSAGES_EN_FILE)
        self.fermeture: int | None = None
        self.reveil = asyncio.Event()
        self.tic = tic
        self.images_jetees = 0
        self.alertes: dict[str, float] = {}
        self.messages_recents: deque[float] = deque()

    def _poser(self, genre: str, contenu: Any) -> None:
        if self.fermeture is not None:
            return
        if genre == "image":
            if len(self.images) == self.images.maxlen:
                self.images_jetees += 1
            self.images.append(contenu)
        elif genre == "message":
            self.messages.append(contenu)
        elif genre == "fermer":
            self.images.clear()
            self.fermeture = int(contenu)
        self.reveil.set()

    def deposer(self, genre: str, contenu: Any) -> None:
        try:
            courante = asyncio.get_running_loop()
        except RuntimeError:
            courante = None
        if courante is self.boucle:
            self._poser(genre, contenu)
            return
        try:
            self.boucle.call_soon_threadsafe(self._poser, genre, contenu)
        except RuntimeError:  # boucle déjà fermée : la connexion n'existe plus
            pass

    def fermer(self, message: dict | None, code: int) -> None:
        if message is not None:
            self.deposer("message", message)
        self.deposer("fermer", code)

    async def pomper(self) -> None:
        """Envoie ce qui attend, dans l'ordre (messages d'abord), puis ferme si demandé."""
        while True:
            try:
                await asyncio.wait_for(self.reveil.wait(), timeout=TIC_S)
            except (asyncio.TimeoutError, TimeoutError):
                if self.tic is not None:
                    try:
                        self.tic(self)
                    except Exception as exc:  # pragma: no cover - défense
                        log.info("partage : tic en erreur (%s)", exc)
            self.reveil.clear()
            while self.messages or self.images:
                if self.messages:
                    await self.ws.send_text(json.dumps(self.messages.popleft(), ensure_ascii=False))
                else:
                    await self.ws.send_bytes(self.images.popleft())
            if self.fermeture is not None:
                try:
                    await self.ws.close(code=self.fermeture)
                except Exception:
                    pass
                return


@dataclass(eq=False)
class _Session:
    code: str
    compte: str
    empreinte: str
    cree_a: float
    expire_a: float
    source: str = ""
    emetteur: _Canal | None = None
    controles: list = field(default_factory=list)
    spectateurs: list = field(default_factory=list)
    images: int = 0
    octets: int = 0
    fenetre: deque = field(default_factory=deque)
    horodatages: deque = field(default_factory=lambda: deque(maxlen=60))
    fermee: bool = False
    emetteur_vu_a: float = 0.0  # dernier instant où un émetteur était connecté
    adresse: str = ""  # empreinte de l'adresse IP de création (jamais l'adresse en clair)


async def _servir(canal: _Canal, lire) -> None:
    """Fait tourner l'envoi et la lecture d'une connexion ; s'arrête dès que l'un des deux finit."""
    pompe = asyncio.create_task(canal.pomper())
    lecture = asyncio.create_task(lire())
    try:
        await asyncio.wait({pompe, lecture}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for tache in (pompe, lecture):
            if not tache.done():
                tache.cancel()
        # asyncio.wait et non gather : si le serveur annule la connexion pendant ce ménage, c'est SON
        # annulation qui remonte, intacte. gather la remplacerait par celle d'une tâche enfant, que le
        # serveur ne reconnaît pas comme la sienne — la fermeture d'une connexion finirait en erreur.
        await asyncio.wait({pompe, lecture})
        for tache in (pompe, lecture):
            if tache.done() and not tache.cancelled():
                tache.exception()  # lue : pas d'avertissement « exception jamais récupérée »


async def _lire_brut(ws: WebSocket) -> dict | None:
    """Le prochain message, ou None si le client s'est déconnecté."""
    try:
        message = await ws.receive()
    except Exception:
        return None
    if message.get("type") == "websocket.disconnect":
        return None
    return message


def creer_routeur_partage(relais: Any) -> APIRouter:
    routeur = APIRouter()
    sessions: dict[str, _Session] = {}
    par_jeton: dict[str, _Session] = {}
    echecs: dict[str, list[float]] = {}
    creations: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ limitation
    def _recentes(registre: dict[str, list[float]], cle: str, fenetre: float) -> list[float]:
        t = maintenant()
        if len(registre) > 5000:  # ménage : les clés sans tentative récente disparaissent
            for vieille in [c for c, v in registre.items() if not v or v[-1] < t - fenetre]:
                registre.pop(vieille, None)
        recentes = [h for h in registre.get(cle, []) if h > t - fenetre]
        registre[cle] = recentes
        return recentes

    def _delai_blocage(ip: str) -> float:
        recentes = _recentes(echecs, ip, FENETRE_ECHECS_S)
        if len(recentes) >= ECHECS_MAX:
            return recentes[0] + FENETRE_ECHECS_S - maintenant()
        return 0.0

    def _noter_echec(ip: str) -> None:
        _recentes(echecs, ip, FENETRE_ECHECS_S).append(maintenant())

    def _message_tentatives(delai: float) -> str:
        minutes = max(1, int(-(-delai // 60)))
        return f"Trop de tentatives depuis cette adresse. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}."

    # ------------------------------------------------------------------ sessions
    def _canaux(session: _Session) -> list[_Canal]:
        return ([session.emetteur] if session.emetteur else []) + list(session.controles) + list(session.spectateurs)

    def _fermer(session: _Session, raison: str) -> None:
        if session.fermee:
            return
        session.fermee = True
        sessions.pop(session.code, None)
        par_jeton.pop(session.empreinte, None)
        fin = {"type": "fin", "raison": raison, "message": MESSAGES_FIN.get(raison, "Le partage est terminé.")}
        for canal in _canaux(session):
            canal.fermer(fin, FERMETURE_FIN)
        log.info("partage : session fermée (%s), %s image(s) transmises", raison, session.images)

    def _vivante(session: _Session | None) -> _Session | None:
        if session is None or session.fermee:
            return None
        if maintenant() >= session.expire_a:
            _fermer(session, "expiree")
            return None
        return session

    def _purger() -> None:
        for session in list(sessions.values()):
            _vivante(session)

    def _etat_spectateur(session: _Session) -> dict:
        t = maintenant()
        return {"type": "etat", "source": session.source or None, "emetteur_connecte": session.emetteur is not None,
                "spectateurs": len(session.spectateurs), "expire_a": iso(session.expire_a),
                "expire_dans_s": max(0, int(session.expire_a - t))}

    def _stats(session: _Session) -> dict:
        t = maintenant()
        return {"type": "stats", "source": session.source or None, "spectateurs": len(session.spectateurs),
                "images": session.images, "fps_reel": cadence(session.horodatages, t),
                "emetteur_connecte": session.emetteur is not None,
                "expire_a": iso(session.expire_a), "expire_dans_s": max(0, int(session.expire_a - t))}

    def _prevenir_proprietaire(session: _Session, message: dict) -> bool:
        """Envoie à l'émetteur et aux contrôles. Vrai si au moins une connexion l'a reçu."""
        remis = False
        for canal in ([session.emetteur] if session.emetteur else []) + list(session.controles):
            canal.deposer("message", message)
            remis = True
        return remis

    def _prevenir_spectateurs(session: _Session) -> None:
        etat = _etat_spectateur(session)
        for canal in session.spectateurs:
            canal.deposer("message", etat)

    def _renouveler(session: _Session) -> None:
        session.expire_a = maintenant() + DUREE_SESSION_S
        t = maintenant()
        _prevenir_proprietaire(session, {"type": "expiration", "expire_a": iso(session.expire_a),
                                         "expire_dans_s": int(session.expire_a - t)})
        _prevenir_spectateurs(session)

    def _refuser(canal: _Canal, raison: str, message: str, **extra: Any) -> None:
        """Une alerte par raison et par seconde au plus : un émetteur fautif ne fait pas déborder sa file."""
        t = maintenant()
        if t - canal.alertes.get(raison, -10.0) < 1.0:
            return
        canal.alertes[raison] = t
        canal.deposer("message", {"type": "refus", "raison": raison, "message": message, **extra})

    def _recevoir_image(session: _Session, canal: _Canal, donnees: bytes) -> None:
        if _vivante(session) is None:
            return
        if len(donnees) > TAILLE_MAX_IMAGE:
            _refuser(canal, "taille", f"Image refusée : {len(donnees)} octets, maximum {TAILLE_MAX_IMAGE}.",
                     max_octets=TAILLE_MAX_IMAGE)
            return
        if not donnees.startswith(DEBUT_JPEG):
            _refuser(canal, "format", "Image refusée : seules les images JPEG sont transmises.")
            return
        t = maintenant()
        while session.fenetre and session.fenetre[0] <= t - 1.0:
            session.fenetre.popleft()
        if len(session.fenetre) >= IMAGES_PAR_SECONDE_MAX:
            _refuser(canal, "debit", f"Image refusée : {IMAGES_PAR_SECONDE_MAX} images par seconde au plus.",
                     max_par_seconde=IMAGES_PAR_SECONDE_MAX)
            return
        session.fenetre.append(t)
        session.horodatages.append(t)
        session.images += 1
        session.octets += len(donnees)
        for spectateur in session.spectateurs:
            spectateur.deposer("image", donnees)

    def _tic_proprietaire(session: _Session):
        def tic(canal: _Canal) -> None:
            if _vivante(session) is not None:
                canal.deposer("message", _stats(session))
        return tic

    def _tic_spectateur(session: _Session):
        def tic(canal: _Canal) -> None:
            if _vivante(session) is not None:
                canal.deposer("message", _etat_spectateur(session))
        return tic

    def _base_publique(request: Request) -> str:
        """L'adresse publique du relais, pour construire le lien du spectateur. VELA_URL_PUBLIQUE prime ;
        sinon on suit les en-têtes du mandataire (l'hébergeur termine le TLS, request.url dit « http »)."""
        imposee = os.environ.get("VELA_URL_PUBLIQUE", "").strip().rstrip("/")
        if imposee:
            return imposee
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
        if proto not in ("http", "https"):
            proto = "https"
        hote = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        if not _HOTE.match(hote):
            hote = request.url.netloc
        return f"{proto}://{hote}"

    async def _corps(request: Request) -> dict:
        # Corps lu à la main : une erreur de validation automatique renverrait les valeurs reçues, jeton compris.
        try:
            corps = await request.json()
        except Exception:
            corps = None
        return corps if isinstance(corps, dict) else {}

    def _session_du_jeton(jeton: str) -> _Session | None:
        if not jeton:
            return None
        return _vivante(par_jeton.get(empreinte(jeton)))

    # ------------------------------------------------------------------ HTTP
    @routeur.post("/api/partage/creer")
    async def creer(request: Request):
        corps = await _corps(request)
        jeton = str(corps.get("jeton_appareil") or "").strip()
        if not jeton:
            entete = request.headers.get("authorization", "")
            jeton = entete[7:].strip() if entete.lower().startswith("bearer ") else ""
        ip = _adresse_ip(request.headers, request.client)
        info = relais.lire_jeton(jeton)
        if not info:
            return JSONResponse({"detail": "Jeton d'appareil invalide ou expiré. Relancez IRIS pour en obtenir un nouveau."},
                                status_code=401)
        compte = relais.normaliser(info.get("courriel") or "") or "anonyme:" + str(info.get("machine") or "?")
        lie = getattr(relais, "liaison_confirmee", None)
        if callable(lie) and not compte.startswith("anonyme:") and lie(compte):
            preuve = corps.get("preuve_pc") if isinstance(corps.get("preuve_pc"), dict) else {}
            if not relais.verifier_preuve_horodatee(compte, "vela-partage-creer", preuve.get("horodatage"),
                                                    str(preuve.get("preuve") or "")):
                return JSONResponse({"detail": MESSAGE_PC_NON_LIE}, status_code=403)
        cles_quota = ((f"ip:{ip}", CREATIONS_MAX), (f"compte:{compte}|ip:{ip}", CREATIONS_PAR_COMPTE))
        for cle, plafond in cles_quota:
            recentes = _recentes(creations, cle, FENETRE_CREATIONS_S)
            if len(recentes) >= plafond:
                delai = recentes[0] + FENETRE_CREATIONS_S - maintenant()
                minutes = max(1, int(-(-delai // 60)))
                return JSONResponse(
                    {"detail": f"Trop de partages créés en peu de temps. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}."},
                    status_code=429, headers={"Retry-After": str(int(delai) + 1)})
        _purger()
        t_creation = maintenant()
        adresse = hashlib.sha256(f"partage-ip|{SEL_ADRESSES}|{compte}|{ip}".encode("utf-8")).hexdigest()[:24]
        # Compté par (compte, adresse de création) : les partages d'un tiers ne prennent pas la place de la victime.
        du_compte = sorted((s for s in sessions.values() if s.compte == compte and s.adresse == adresse),
                           key=lambda s: s.cree_a)

        def _remplacable(s: _Session) -> bool:
            # Jamais une session en service : émetteur connecté, ou vu (ou créée) il y a moins d'une minute.
            return s.emetteur is None and t_creation - max(s.cree_a, s.emetteur_vu_a) > REMPLACEMENT_SANS_EMETTEUR_S

        while len(du_compte) >= SESSIONS_PAR_COMPTE:
            candidates = [s for s in du_compte if _remplacable(s)]
            if not candidates:
                # « Réessayez dans une minute » n'est vrai que si une session cédera sa place d'ici là.
                en_service = all(s.emetteur is not None for s in du_compte)
                return JSONResponse({"detail": MESSAGE_DEJA_EN_SERVICE if en_service else MESSAGE_DEJA_EN_COURS},
                                    status_code=409)
            du_compte.remove(candidates[0])
            _fermer(candidates[0], "remplacee")
        if len(sessions) >= SESSIONS_MAX:
            log.warning("partage : plafond de %s sessions atteint", SESSIONS_MAX)
            return JSONResponse({"detail": "Le partage de vision est momentanément saturé. Réessayez dans quelques minutes."},
                                status_code=503)
        for cle, _ in cles_quota:
            creations[cle].append(maintenant())
        code = generer_code()
        while code in sessions:
            code = generer_code()
        jeton_emetteur = secrets.token_urlsafe(32)
        t = maintenant()
        session = _Session(code=code, compte=compte, empreinte=empreinte(jeton_emetteur), cree_a=t,
                           expire_a=t + DUREE_SESSION_S, adresse=adresse)
        sessions[code] = session
        par_jeton[session.empreinte] = session
        base = _base_publique(request)
        base_ws = ("wss://" + base[len("https://"):]) if base.startswith("https://") else ("ws://" + base.split("://", 1)[-1])
        log.info("partage : session créée (%s en cours)", len(sessions))
        return {"code": code, "jeton_emetteur": jeton_emetteur, "expire_a": iso(session.expire_a),
                "expire_dans_s": int(DUREE_SESSION_S), "url_spectateur": f"{base}/voir/{code}",
                "ws_emetteur": f"{base_ws}/partage/emetteur"}

    @routeur.post("/api/partage/renouveler")
    async def renouveler(request: Request):
        session = _session_du_jeton(str((await _corps(request)).get("jeton_emetteur") or ""))
        if session is None:
            return JSONResponse({"detail": "Partage introuvable ou expiré."}, status_code=404)
        _renouveler(session)
        return {"expire_a": iso(session.expire_a), "expire_dans_s": int(session.expire_a - maintenant())}

    @routeur.post("/api/partage/fermer")
    async def fermer(request: Request):
        session = _session_du_jeton(str((await _corps(request)).get("jeton_emetteur") or ""))
        if session is None:
            return JSONResponse({"ok": False, "detail": "Partage introuvable ou déjà terminé."}, status_code=404)
        _fermer(session, "arrete")
        return {"ok": True}

    @routeur.post("/api/partage/etat")
    async def etat(request: Request):
        session = _session_du_jeton(str((await _corps(request)).get("jeton_emetteur") or ""))
        if session is None:
            return JSONResponse({"actif": False, "detail": "Partage introuvable ou expiré."}, status_code=404)
        stats = _stats(session)
        stats.pop("type", None)
        return {"actif": True, **stats}

    @routeur.get("/voir/{code}", response_class=HTMLResponse)
    async def voir(code: str, request: Request):  # async : l'état des sessions ne vit que dans la boucle
        ip = _adresse_ip(request.headers, request.client)
        entetes = {"Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                   "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex"}
        delai = _delai_blocage(ip)
        if delai > 0:
            return HTMLResponse(page_message("Trop de tentatives", _message_tentatives(delai)), status_code=429,
                                headers={**entetes, "Retry-After": str(int(delai) + 1),
                                         "Content-Security-Policy": CSP_MESSAGE})
        code = normaliser_code(code)
        if not code_valide(code) or _vivante(sessions.get(code)) is None:
            _noter_echec(ip)
            return HTMLResponse(page_message("Partage introuvable", MESSAGE_INCONNU), status_code=404,
                                headers={**entetes, "Content-Security-Policy": CSP_MESSAGE})
        hote = request.headers.get("host", "")
        connexions = "'self'" + (f" wss://{hote} ws://{hote}" if _HOTE.match(hote) else "")
        csp = ("default-src 'none'; img-src blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
               f"connect-src {connexions}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        return HTMLResponse(PAGE_SPECTATEUR, headers={**entetes, "Content-Security-Policy": csp})

    # ------------------------------------------------------------------ WebSocket de l'émetteur
    @routeur.websocket("/partage/emetteur")
    async def ws_emetteur(ws: WebSocket):
        await ws.accept()
        jeton = ws.query_params.get("jeton") or ""
        role = ws.query_params.get("role") or "emetteur"
        source = ws.query_params.get("source") or ""
        if not jeton:
            # Le jeton peut aussi venir dans un premier message : il n'apparaît alors dans aucun journal d'accès.
            try:
                premier = await asyncio.wait_for(ws.receive_json(), timeout=DELAI_HELLO_S)
            except Exception:
                premier = None
            if isinstance(premier, dict) and premier.get("type") == "hello":
                jeton = str(premier.get("jeton") or "")
                role = str(premier.get("role") or role)
                source = str(premier.get("source") or source)
        # Pas de limitation par adresse ici : le jeton émetteur fait 32 octets (rien à deviner), et compter ses
        # échecs bloquerait les spectateurs qui partagent la même adresse (réseau d'un cégep, d'un bureau).
        session = _session_du_jeton(jeton)
        if session is None:
            await _refuser_connexion(ws, "inconnu", "Partage introuvable ou expiré.", FERMETURE_INCONNU)
            return
        role = "controle" if role == "controle" else "emetteur"
        canal = _Canal(ws, role, tic=_tic_proprietaire(session))
        if role == "emetteur":
            ancien = session.emetteur
            if ancien is not None:
                ancien.fermer({"type": "fin", "raison": "remplace",
                               "message": "Un autre appareil émet maintenant pour ce partage."}, FERMETURE_REMPLACE)
            session.emetteur = canal
            session.emetteur_vu_a = maintenant()
            if source in SOURCES:
                session.source = source
        else:
            session.controles.append(canal)
            while len(session.controles) > CONTROLES_MAX:
                session.controles.pop(0).fermer(None, FERMETURE_REMPLACE)
        t = maintenant()
        canal.deposer("message", {"type": "pret", "role": role, "code": session.code,
                                  "expire_a": iso(session.expire_a), "expire_dans_s": int(session.expire_a - t),
                                  "spectateurs": len(session.spectateurs)})
        if role == "emetteur":
            _prevenir_spectateurs(session)

        async def lire() -> None:
            while True:
                message = await _lire_brut(ws)
                if message is None:
                    return
                donnees = message.get("bytes")
                if donnees is not None:
                    if canal.role == "emetteur" and session.emetteur is canal:
                        _recevoir_image(session, canal, donnees)
                    continue
                try:
                    commande = json.loads(message.get("text") or "")
                except ValueError:
                    continue
                if not isinstance(commande, dict) or _vivante(session) is None:
                    continue
                genre = commande.get("type")
                if genre == "renouveler":
                    _renouveler(session)
                elif genre == "fin":
                    _fermer(session, "arrete")
                elif genre == "source" and canal.role == "emetteur" and commande.get("source") in SOURCES:
                    session.source = str(commande["source"])
                    _prevenir_spectateurs(session)
                elif genre == "etat":
                    canal.deposer("message", _stats(session))
                elif genre == "ping":
                    canal.deposer("message", {"type": "pong"})

        try:
            await _servir(canal, lire)
        finally:
            if session.emetteur is canal:
                session.emetteur = None
                session.emetteur_vu_a = maintenant()
                if not session.fermee:
                    _prevenir_spectateurs(session)
            if canal in session.controles:
                session.controles.remove(canal)

    # ------------------------------------------------------------------ WebSocket du spectateur
    @routeur.websocket("/partage/spectateur/{code}")
    async def ws_spectateur(ws: WebSocket, code: str):
        await ws.accept()
        ip = _adresse_ip(ws.headers, ws.client)
        delai = _delai_blocage(ip)
        if delai > 0:
            await _refuser_connexion(ws, "trop_de_tentatives", _message_tentatives(delai), FERMETURE_TENTATIVES)
            return
        code = normaliser_code(code)
        session = _vivante(sessions.get(code)) if code_valide(code) else None
        if session is None:
            _noter_echec(ip)
            await _refuser_connexion(ws, "inconnu", MESSAGE_INCONNU, FERMETURE_INCONNU)
            return
        if len(session.spectateurs) >= SPECTATEURS_MAX:
            await _refuser_connexion(ws, "complet", MESSAGE_COMPLET, FERMETURE_COMPLET)
            return
        canal = _Canal(ws, "spectateur", tic=_tic_spectateur(session))
        session.spectateurs.append(canal)
        canal.deposer("message", _etat_spectateur(session))
        _prevenir_proprietaire(session, {"type": "spectateurs", "nombre": len(session.spectateurs)})

        async def lire() -> None:
            while True:
                message = await _lire_brut(ws)
                if message is None:
                    return
                texte_brut = message.get("text")
                if not texte_brut:
                    continue  # un spectateur n'envoie pas d'images
                try:
                    commande = json.loads(texte_brut)
                except ValueError:
                    continue
                if not isinstance(commande, dict) or _vivante(session) is None:
                    continue
                if commande.get("type") == "ping":
                    canal.deposer("message", {"type": "pong"})
                    continue
                if commande.get("type") != "message":
                    continue
                texte = nettoyer_message(commande.get("texte"))
                if not texte:
                    continue
                t = maintenant()
                while canal.messages_recents and canal.messages_recents[0] <= t - FENETRE_MESSAGES_S:
                    canal.messages_recents.popleft()
                if len(canal.messages_recents) >= MESSAGES_PAR_FENETRE:
                    canal.deposer("message", {"type": "refus", "raison": "messages",
                                              "message": "Trop de messages d'un coup : attendez quelques secondes."})
                    continue
                canal.messages_recents.append(t)
                remis = _prevenir_proprietaire(session, {"type": "message", "texte": texte, "ts": iso(t)})
                canal.deposer("message", {"type": "message_envoye", "remis": remis})

        try:
            await _servir(canal, lire)
        finally:
            if canal in session.spectateurs:
                session.spectateurs.remove(canal)
                if not session.fermee:
                    _prevenir_proprietaire(session, {"type": "spectateurs", "nombre": len(session.spectateurs)})

    # Accès réservé aux tests (état en mémoire, jamais exposé par une route).
    routeur.partage_etat = {"sessions": sessions, "par_jeton": par_jeton, "echecs": echecs,  # type: ignore[attr-defined]
                            "creations": creations}
    return routeur


async def _refuser_connexion(ws: WebSocket, raison: str, message: str, code: int) -> None:
    try:
        await ws.send_json({"type": "refus", "raison": raison, "message": message})
        await ws.close(code=code)
    except Exception:
        pass


CSP_MESSAGE = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def page_message(titre: str, message: str) -> str:
    """Petite page autonome pour un lien introuvable ou bloqué (textes fixes, aucun contenu reçu)."""
    return PAGE_MESSAGE.replace("{{TITRE}}", titre).replace("{{MESSAGE}}", message)


PAGE_MESSAGE = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{TITRE}} · Vision partagée VELA</title>
<style>
:root { --fond:#f6f7f9; --carte:#ffffff; --texte:#14161a; --doux:#4a505a; --ligne:#c9ced6; }
@media (prefers-color-scheme: dark) { :root { --fond:#0f1115; --carte:#181b21; --texte:#eef0f3; --doux:#b4bac4; --ligne:#3a404a; } }
body { margin:0; background:var(--fond); color:var(--texte); font:18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:36rem; margin:0 auto; padding:2rem 1rem; }
.carte { background:var(--carte); border:1px solid var(--ligne); border-radius:14px; padding:1.25rem; }
h1 { font-size:1.5rem; margin:0 0 .75rem; }
p { margin:0; color:var(--doux); }
</style>
</head>
<body>
<main>
<div class="carte" role="alert">
<h1>{{TITRE}}</h1>
<p>{{MESSAGE}}</p>
</div>
</main>
</body>
</html>
"""


PAGE_SPECTATEUR = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="referrer" content="no-referrer">
<title>Vision partagée · VELA</title>
<style>
:root { --fond:#f6f7f9; --carte:#ffffff; --texte:#14161a; --doux:#4a505a; --ligne:#c9ced6; --accent:#1f4fd1;
  --danger:#b3261e; --ok:#1b6e3a; --attente:#8a5a00; --focus:#ffb300; --cadre:#e6e9ee; }
@media (prefers-color-scheme: dark) { :root { --fond:#0f1115; --carte:#181b21; --texte:#eef0f3; --doux:#b4bac4;
  --ligne:#3a404a; --accent:#8fb0ff; --danger:#ff8a80; --ok:#7ddc9c; --attente:#ffcc66; --cadre:#23272f; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--fond); color:var(--texte); font:18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:56rem; margin:0 auto; padding:1rem 1rem 3rem; }
h1 { font-size:1.6rem; margin:.5rem 0 .25rem; }
h2 { font-size:1.2rem; margin:0 0 .5rem; }
h3 { font-size:1rem; margin:1rem 0 .25rem; }
.intro { margin:0 0 1rem; color:var(--doux); }
.bandeau { display:flex; align-items:center; gap:.6rem; min-height:2rem; }
.bandeau p { margin:0; font-weight:600; }
.pastille { width:.9rem; height:.9rem; border-radius:50%; flex:none; background:var(--attente); }
.pastille.ok { background:var(--ok); } .pastille.fin { background:var(--danger); }
figure { margin:.75rem 0 0; background:var(--cadre); border:1px solid var(--ligne); border-radius:14px; overflow:hidden;
  display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:14rem; }
figure img { display:block; width:100%; height:auto; max-height:75vh; object-fit:contain; background:#000; }
figure:fullscreen { background:#000; } figure:fullscreen img { max-height:100vh; height:100%; }
.attente-image { margin:2rem 1rem; color:var(--doux); text-align:center; }
figcaption { width:100%; padding:.4rem .75rem; font-size:.95rem; color:var(--doux); background:var(--carte); }
.mesures { margin:.5rem 0; color:var(--doux); font-variant-numeric:tabular-nums; }
.carte { background:var(--carte); border:1px solid var(--ligne); border-radius:14px; padding:1.25rem; margin:1rem 0; }
label { display:block; font-weight:600; margin:0 0 .35rem; }
textarea { width:100%; font:inherit; padding:.7rem; border-radius:10px; border:2px solid var(--ligne); background:var(--fond);
  color:var(--texte); resize:vertical; }
.actions { display:flex; gap:.6rem; flex-wrap:wrap; margin-top:.6rem; }
button { min-height:3rem; padding:0 1.2rem; font-size:1.05rem; font-weight:700; border:none; border-radius:12px;
  background:var(--accent); color:#fff; cursor:pointer; }
button.secondaire { background:transparent; color:var(--texte); border:2px solid var(--ligne); }
button[aria-pressed=true] { background:var(--danger); }
button[disabled] { opacity:.55; cursor:not-allowed; }
@media (prefers-color-scheme: dark) { button { color:#0f1115; } button.secondaire { color:var(--texte); } }
:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
.aide { color:var(--doux); font-size:.95rem; margin:.5rem 0 0; }
.retour { min-height:1.5rem; font-weight:600; margin:.5rem 0 0; }
.historique { margin:0; padding-left:1.2rem; } .historique li { margin:.25rem 0; }
.historique .statut { color:var(--doux); font-size:.9rem; }
ul { padding-left:1.2rem; margin:0; } li { margin:.3rem 0; }
[hidden] { display:none !important; }
</style>
</head>
<body>
<main>
<h1>Vision partagée</h1>
<p class="intro">Vous voyez les images que votre proche partage depuis IRIS. Vos messages lui sont lus à voix haute.</p>

<div class="bandeau">
  <span id="pastille" class="pastille" aria-hidden="true"></span>
  <p id="etat" role="status" aria-live="polite">Connexion au partage…</p>
</div>

<figure id="cadre">
  <img id="image" alt="Aucune image reçue pour le moment." hidden>
  <p id="attente-image" class="attente-image">En attente de la première image…</p>
  <figcaption id="legende">Source : pas encore connue.</figcaption>
</figure>
<p id="mesures" class="mesures">Aucune image reçue.</p>
<div class="actions">
  <button id="agrandir" type="button" class="secondaire">Agrandir l'image</button>
</div>

<section class="carte" aria-labelledby="titre-message">
  <h2 id="titre-message">Envoyer un message</h2>
  <form id="formulaire" novalidate>
    <label for="message">Votre message, lu à voix haute à votre proche</label>
    <textarea id="message" rows="2" maxlength="500" autocomplete="off" aria-describedby="aide-message"></textarea>
    <p id="aide-message" class="aide">Entrée pour envoyer, Maj + Entrée pour aller à la ligne. 500 caractères au plus.</p>
    <div class="actions">
      <button id="envoyer" type="submit">Envoyer</button>
      <button id="parler" type="button" aria-pressed="false">Parler</button>
    </div>
    <p id="note-dictee" class="aide"></p>
    <p id="retour" class="retour" role="status" aria-live="polite"></p>
  </form>
  <h3 id="titre-historique">Messages envoyés</h3>
  <ol id="historique" class="historique" aria-labelledby="titre-historique"></ol>
</section>

<section class="carte" aria-labelledby="titre-limites">
  <h2 id="titre-limites">À savoir</h2>
  <ul>
    <li>Rien n'est enregistré : ni par le relais VELA, ni par cette page. Chaque image remplace la précédente.</li>
    <li>Ce n'est pas une vidéo. Depuis les lunettes, une photo arrive toutes les quelques secondes ; depuis un écran ou un téléphone, quelques images par seconde selon le réseau.</li>
    <li>Chaque image arrive avec du retard, parfois plusieurs secondes. Ne guidez jamais une traversée de rue, un escalier ou un danger immédiat à partir de ces images : demandez plutôt à votre proche de s'arrêter.</li>
    <li>Trois personnes au plus peuvent regarder en même temps. Le lien expire 30 minutes après sa création, sauf si votre proche le prolonge.</li>
    <li>Ne transmettez pas ce lien : toute personne qui l'a peut regarder tant qu'il est valide.</li>
  </ul>
</section>
</main>
<script>
(function () {
  'use strict';
  var correspondance = location.pathname.match(/\\/voir\\/([A-Za-z0-9-]+)\\/?$/);
  var code = correspondance ? correspondance[1] : '';
  var prefixe = correspondance ? location.pathname.slice(0, location.pathname.length - correspondance[0].length) : '';
  var adresse = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + prefixe + '/partage/spectateur/' + encodeURIComponent(code);

  var elEtat = document.getElementById('etat');
  var pastille = document.getElementById('pastille');
  var image = document.getElementById('image');
  var attenteImage = document.getElementById('attente-image');
  var legende = document.getElementById('legende');
  var mesures = document.getElementById('mesures');
  var cadre = document.getElementById('cadre');
  var formulaire = document.getElementById('formulaire');
  var champ = document.getElementById('message');
  var boutonEnvoyer = document.getElementById('envoyer');
  var boutonParler = document.getElementById('parler');
  var noteDictee = document.getElementById('note-dictee');
  var retour = document.getElementById('retour');
  var historique = document.getElementById('historique');

  var SOURCES = { lunettes: 'caméra des lunettes', ecran: "écran de l'ordinateur", telephone: 'caméra du téléphone' };
  var ws = null, fini = false, delai = 1000, urlImage = null, arrivees = [], echeance = null;
  var source = null, emetteurConnecte = true, premiereImage = true, enAttenteDeRemise = [];

  function dire(texte, genre) {
    if (elEtat.textContent !== texte) { elEtat.textContent = texte; }
    pastille.className = 'pastille' + (genre ? ' ' + genre : '');
  }
  function signaler(texte) { retour.textContent = texte; }
  function heure(date) {
    function deux(n) { return (n < 10 ? '0' : '') + n; }
    return deux(date.getHours()) + ' h ' + deux(date.getMinutes()) + ' min ' + deux(date.getSeconds()) + ' s';
  }
  function nombre(n) { return n.toLocaleString('fr-CA', { maximumFractionDigits: 1 }); }
  function libelleSource() { return source && SOURCES[source] ? SOURCES[source] : 'source inconnue'; }

  function terminer(texte) {
    fini = true;
    dire(texte, 'fin');
    boutonEnvoyer.disabled = true;
    boutonParler.disabled = true;
    champ.disabled = true;
  }

  function afficher(blob) {
    var url = URL.createObjectURL(blob);
    var precedente = urlImage;
    urlImage = url;
    image.src = url;
    if (precedente) { URL.revokeObjectURL(precedente); }
    var quand = new Date();
    arrivees.push(quand.getTime());
    if (arrivees.length > 60) { arrivees.shift(); }
    image.alt = 'Image de la ' + libelleSource() + ', reçue à ' + heure(quand) + '. Photo brute, sans description automatique.';
    image.hidden = false;
    attenteImage.hidden = true;
    if (premiereImage) { premiereImage = false; dire('Connecté. Les images arrivent.', 'ok'); }
  }

  function majMesures() {
    var t = Date.now();
    var recents = arrivees.filter(function (h) { return h > t - 30000; });
    var texte;
    if (!arrivees.length) {
      texte = 'Aucune image reçue.';
    } else {
      var ecoule = Math.round((t - arrivees[arrivees.length - 1]) / 1000);
      if (recents.length >= 2) {
        var ecart = (recents[recents.length - 1] - recents[0]) / 1000;
        var moyen = ecart / (recents.length - 1);
        if ((t - recents[recents.length - 1]) / 1000 > Math.max(3 * moyen, 2)) { ecart = (t - recents[0]) / 1000; }
        var fps = ecart > 0 ? (recents.length - 1) / ecart : 0;
        texte = fps >= 1 ? nombre(fps) + ' images par seconde' : (fps > 0 ? '1 image toutes les ' + nombre(1 / fps) + ' secondes' : '');
      } else {
        texte = '';
      }
      texte = (texte ? texte + ' · ' : '') + 'dernière image il y a ' + ecoule + ' s';
    }
    if (echeance) {
      var restant = Math.max(0, Math.round((echeance - t) / 60000));
      texte += ' · le lien expire dans ' + (restant <= 1 ? 'moins de 2 minutes' : restant + ' minutes');
    }
    mesures.textContent = texte;
  }
  setInterval(majMesures, 1000);

  function ajouterHistorique(texte) {
    var li = document.createElement('li');
    var quand = document.createElement('span');
    quand.className = 'statut';
    quand.textContent = ' (' + heure(new Date()) + ', en cours d\\'envoi)';
    li.appendChild(document.createTextNode(texte));
    li.appendChild(quand);
    historique.insertBefore(li, historique.firstChild);
    enAttenteDeRemise.push(quand);
  }

  function traiter(msg) {
    if (!msg || typeof msg.type !== 'string') { return; }
    if (msg.type === 'etat') {
      if (msg.source) { source = msg.source; }
      legende.textContent = 'Source : ' + libelleSource() + '.' + (msg.spectateurs ? ' Personnes qui regardent : ' + msg.spectateurs + '.' : '');
      if (typeof msg.expire_dans_s === 'number') { echeance = Date.now() + msg.expire_dans_s * 1000; }
      emetteurConnecte = !!msg.emetteur_connecte;
      if (!emetteurConnecte) { dire('Votre proche est momentanément déconnecté. La page attend son retour.', ''); }
      else if (premiereImage) { dire('Connecté. En attente de la prochaine image…', 'ok'); }
      else { dire('Connecté. Les images arrivent.', 'ok'); }
    } else if (msg.type === 'fin') {
      terminer(msg.message || 'Le partage est terminé.');
    } else if (msg.type === 'refus') {
      if (msg.raison === 'messages') { signaler(msg.message); return; }
      terminer(msg.message || 'Connexion refusée.');
    } else if (msg.type === 'message_envoye') {
      var statut = enAttenteDeRemise.shift();
      var texteStatut = msg.remis ? 'remis' : 'non remis : votre proche n\\'est pas connecté pour le moment';
      if (statut) { statut.textContent = ' (' + texteStatut + ')'; }
      signaler(msg.remis ? 'Message remis à votre proche.' : 'Message non remis : votre proche n\\'est pas connecté pour le moment.');
    }
  }

  function connecter() {
    if (fini) { return; }
    if (!code) { terminer('Adresse de partage invalide.'); return; }
    ws = new WebSocket(adresse);
    ws.binaryType = 'blob';
    ws.onopen = function () { delai = 1000; dire('Connecté. En attente de la prochaine image…', 'ok'); };
    ws.onmessage = function (ev) {
      if (typeof ev.data !== 'string') { afficher(ev.data); return; }
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      traiter(msg);
    };
    ws.onclose = function () {
      ws = null;
      if (fini) { return; }
      var secondes = Math.round(delai / 1000);
      dire('Connexion perdue. Nouvelle tentative dans ' + secondes + ' seconde' + (secondes > 1 ? 's' : '') + '…', '');
      setTimeout(connecter, delai);
      delai = Math.min(delai * 2, 30000);
    };
  }

  function envoyer(texte) {
    texte = (texte || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
    if (!texte) { signaler('Écrivez un message avant de l\\'envoyer.'); champ.focus(); return; }
    if (!ws || ws.readyState !== 1) { signaler('Pas de connexion au partage : le message n\\'a pas été envoyé.'); return; }
    ws.send(JSON.stringify({ type: 'message', texte: texte }));
    ajouterHistorique(texte);
    champ.value = '';
    signaler('Message envoyé…');
  }

  formulaire.addEventListener('submit', function (e) { e.preventDefault(); envoyer(champ.value); });
  champ.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer(champ.value); }
  });

  document.getElementById('agrandir').addEventListener('click', function () {
    if (document.fullscreenElement) { document.exitFullscreen(); return; }
    if (cadre.requestFullscreen) { cadre.requestFullscreen(); }
    else { signaler("L'agrandissement n'est pas disponible dans ce navigateur."); }
  });

  var Reconnaissance = window.SpeechRecognition || window.webkitSpeechRecognition;
  var reconnaissance = null, enDictee = false;
  function etatDictee(actif) {
    enDictee = actif;
    boutonParler.setAttribute('aria-pressed', actif ? 'true' : 'false');
    boutonParler.textContent = actif ? 'Arrêter la dictée' : 'Parler';
  }
  if (!Reconnaissance) {
    boutonParler.hidden = true;
    noteDictee.textContent = "La dictée n'est pas disponible dans ce navigateur : tapez votre message.";
  } else {
    noteDictee.textContent = "« Parler » utilise la reconnaissance vocale de votre navigateur, qui peut transmettre votre voix à son éditeur. Le message part dès la fin de la phrase.";
    boutonParler.addEventListener('click', function () {
      if (enDictee && reconnaissance) { reconnaissance.stop(); return; }
      var final = '';
      reconnaissance = new Reconnaissance();
      reconnaissance.lang = 'fr-CA';
      reconnaissance.interimResults = true;
      reconnaissance.continuous = false;
      reconnaissance.onresult = function (ev) {
        var provisoire = '';
        for (var i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) { final += ev.results[i][0].transcript; }
          else { provisoire += ev.results[i][0].transcript; }
        }
        champ.value = (final + ' ' + provisoire).trim();
      };
      reconnaissance.onerror = function (ev) {
        final = '';
        etatDictee(false);
        signaler(ev.error === 'not-allowed' || ev.error === 'service-not-allowed'
          ? 'Micro refusé : autorisez le micro pour cette page, ou tapez votre message.'
          : "La dictée n'a pas fonctionné. Réessayez ou tapez votre message.");
      };
      reconnaissance.onend = function () {
        etatDictee(false);
        if (final.trim()) { envoyer(final); }
      };
      try { reconnaissance.start(); etatDictee(true); signaler('Parlez, je vous écoute…'); }
      catch (e) { etatDictee(false); signaler("La dictée n'a pas pu démarrer."); }
    });
  }

  connecter();
})();
</script>
</body>
</html>
"""
