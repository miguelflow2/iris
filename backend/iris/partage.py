"""Vision partagée en direct, côté service (interface J du chantier du 2026-09-13).

Le scénario : une personne malvoyante veut qu'un proche voie ce qu'elle a devant elle, ou un technicien
veut voir l'écran d'un client. IRIS crée une session sur le relais VELA (serveur/partage_vision.py),
envoie des images JPEG, et le proche ouvre le lien /voir/<code> dans son navigateur. Ce qu'il écrit ou
dicte revient ici et est lu à voix haute.

Trois sources, trois réalités, dites telles quelles à l'utilisateur :
- « ecran » : l'écran principal de cet ordinateur, capturé en mémoire (mss), réduit à 1280 px et
  compressé en JPEG, 2 à 5 images par seconde selon l'intervalle choisi et la machine ;
- « lunettes » : les lunettes n'ont PAS de flux vidéo. IRIS prend une photo par Bluetooth basse
  énergie, l'envoie, puis recommence : une image toutes les quelques secondes. La cadence affichée
  est MESURÉE, jamais promise. La photo, écrite sur le disque par le module caméra, est effacée
  aussitôt lue. Tant que le protocole photo des lunettes n'est pas confirmé (réglage
  lunettes_exploration), le partage refuse de démarrer avec le message exact du module caméra ;
- « telephone » : c'est le téléphone qui envoie les images de sa propre caméra au relais. L'ordinateur
  crée la session (il détient le jeton d'appareil), renvoie au téléphone son jeton émetteur, puis suit
  l'état (spectateurs, messages) par une connexion « contrôle » qui ne reçoit aucune image.

Règles de confiance appliquées ici :
- consentement : « screen » pour l'écran, « image » pour les lunettes et le téléphone, vérifié au
  démarrage ET chaque seconde pendant le partage (le retirer arrête tout) ; début et fin journalisés
  dans le registre (jamais le code, le lien ni le jeton) ;
- mode confidentiel, mode 100 % local ou verrouillage à distance : refus de démarrer (409) et arrêt
  immédiat d'un partage en cours ;
- indicateur de capture : écran ou caméra allumés pendant tout le partage, et éteints à la fin seulement
  si personne d'autre ne s'en sert ;
- rien n'est conservé : ni image (seule la dernière reste en mémoire vive, pour la vision d'accessibilité,
  et disparaît à l'arrêt), ni message du proche ;
- l'expiration de 30 minutes n'est jamais prolongée en silence : l'utilisateur prolonge (route ou voix),
  et IRIS le prévient deux minutes avant la fin.

Le réseau (HTTP et WebSocket vers le relais) passe par `client_relais`, remplaçable : les tests utilisent
un faux relais, sans réseau. La capture d'écran (`capture_ecran`) et la caméra (`fabrique_camera`) aussi.
"""
from __future__ import annotations

import asyncio
import io
import inspect
import json
import logging
import math
import re
import time
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .consent import DATA_TYPES, ConsentRequired, LocalOnlyMode

log = logging.getLogger("iris.partage")

SOURCES = ("lunettes", "ecran", "telephone")
LIBELLES_SOURCES = {
    "lunettes": "la caméra des lunettes",
    "ecran": "l'écran de l'ordinateur",
    "telephone": "la caméra du téléphone",
}
TAILLE_MAX_IMAGE = 300_000  # octets : la borne du relais
COTE_MAX = 1280
QUALITE_JPEG = 60
# Paliers de compression quand une image dépasse la borne du relais (écran très chargé, photo détaillée).
PALIERS_COMPRESSION = ((COTE_MAX, QUALITE_JPEG), (COTE_MAX, 45), (960, 40), (640, 35))
INTERVALLE_ECRAN_DEFAUT_S = 0.33  # ≈ 3 images par seconde
INTERVALLE_ECRAN_MIN_S = 0.2  # 5 images par seconde au plus : au-delà, le processeur et le réseau paient pour rien
INTERVALLE_ECRAN_MAX_S = 5.0
PAUSE_LUNETTES_DEFAUT_S = 0.5  # entre deux photos : laisse le Bluetooth respirer (batterie, boutons)
PAUSE_LUNETTES_MAX_S = 60.0
DELAI_RELAIS_S = 15.0
DELAI_PHOTO_S = 30.0  # le module caméra attend lui-même 20 s le fichier
DELAI_FERMETURE_S = 3.0
SURVEILLANCE_S = 1.0
PUBLICATION_ETAT_S = 5.0
AVERTISSEMENT_EXPIRATION_S = 120
RECONNEXIONS_MAX = 5
ATTENTE_RECONNEXION_MAX_S = 30.0
ECHECS_CAPTURE_MAX = 3
MESSAGES_GARDES = 20  # en mémoire vive, pour l'écran d'IRIS ; effacés à l'arrêt
MESSAGE_MAX = 500
FENETRE_CADENCE_S = 30.0
DEBUT_JPEG = b"\xff\xd8\xff"

# Codes de fermeture du relais (serveur/partage_vision.py) : la session n'existe plus, inutile de réessayer.
FERMETURES_DEFINITIVES = (4003, 4004, 4010)

# ------------------------------------------------------------------ textes montrés ou dits
CONFIDENTIEL = "Le mode confidentiel est actif : aucun partage de vision ne démarre tant qu'il l'est."
CONFIDENTIEL_ARRET = "Mode confidentiel activé : le partage de vision est arrêté."
LOCAL_SEULEMENT = (
    "Le mode 100 % local est actif : le partage de vision passe par le relais VELA sur Internet, "
    "il ne peut donc pas démarrer."
)
LOCAL_SEULEMENT_ARRET = "Mode 100 % local activé : le partage de vision est arrêté."
VERROU_ARRET = "IRIS a été verrouillée : le partage de vision est arrêté."
SANS_RELAIS = "Aucun relais VELA n'est configuré : le partage de vision en a besoin pour joindre votre proche."
SANS_ACCES = (
    "IRIS n'a pas encore obtenu son accès au relais VELA. Vérifiez la connexion Internet, puis réessayez."
)
RELAIS_INJOIGNABLE = "Le relais VELA ne répond pas. Vérifiez la connexion Internet, puis réessayez."
DEJA_ACTIF = "Un partage de vision est déjà en cours. Arrêtez-le avant d'en démarrer un autre."
DEMARRAGE_EN_COURS = "Un partage de vision est déjà en train de démarrer."
AUCUN_PARTAGE = "Aucun partage de vision n'est en cours."
LUNETTES_NON_CONNECTEES = "Les lunettes ne sont pas connectées : le partage depuis leur caméra est impossible."
LUNETTES_DECONNECTEES = "Les lunettes se sont déconnectées : le partage de vision est arrêté."
CAMERA_OCCUPEE = "La caméra des lunettes est occupée par une autre photo. Réessayez dans quelques secondes."
PHOTO_RATEE = "La prise de photo des lunettes a échoué."
PHOTO_VIDE = "Aucune image n'est revenue des lunettes."
ECRAN_RATE = "La capture de l'écran a échoué."
CAMERA_ABSENTE = "Le module caméra des lunettes n'est pas disponible sur cet ordinateur."
CONNEXION_PERDUE = "La connexion au relais VELA est perdue : le partage de vision est arrêté."
SESSION_PERDUE = (
    "Le relais VELA a fermé ce partage (service redémarré ou partage expiré). Démarrez un nouveau partage."
)
EXPIRE = "Le partage a expiré : 30 minutes sont passées sans prolongation."
ARRETE = "Partage de vision arrêté."
ARRET_IRIS = "IRIS s'arrête : le partage de vision est terminé."
REMPLACE = "Un autre appareil émet maintenant pour ce partage : l'ordinateur a cessé d'envoyer ses images."
MESSAGES_FIN_RELAIS = {
    "expiree": EXPIRE,
    "arrete": ARRETE,
    "remplacee": "Ce partage a été remplacé par un nouveau lien.",
    "remplace": REMPLACE,
}

NOTES = {
    "ecran": (
        "L'écran principal de l'ordinateur est envoyé tel qu'il s'affiche, quelques images par seconde : "
        "tout ce qui y apparaît (notifications, messages, mots de passe affichés) est visible par la personne qui regarde."
    ),
    "lunettes": (
        "Les lunettes n'envoient pas de vidéo : IRIS prend une photo, l'envoie, puis recommence. Comptez une image "
        "toutes les quelques secondes ; la cadence réelle est mesurée et affichée."
    ),
    "telephone": (
        "C'est le téléphone qui envoie les images de sa caméra, directement au relais VELA : l'ordinateur ne voit "
        "pas ces images, il suit seulement le partage."
    ),
}
LIMITES = [
    "Rien n'est enregistré, ni par le relais VELA ni par IRIS : chaque image remplace la précédente. "
    "Les photos des lunettes prises pour le partage sont effacées de l'ordinateur aussitôt lues.",
    "Ce n'est pas une vidéo en direct : chaque image arrive avec du retard, parfois plusieurs secondes. "
    "Ce partage ne remplace pas une aide sur place pour traverser une rue, un escalier ou un danger immédiat.",
    "Trois personnes au plus peuvent regarder. Le lien expire 30 minutes après sa création, sauf si vous le prolongez.",
    "Toute personne qui a le lien peut regarder tant qu'il est valide : ne le donnez qu'à quelqu'un de confiance.",
    "Le partage exige Internet, sur cet ordinateur comme chez la personne qui regarde.",
    "Les messages de la personne qui regarde sont lus à voix haute ; ils ne sont pas conservés.",
]


class RefusPartage(HTTPException):
    """Refus expliqué : un HTTPException (la route le renvoie tel quel) qui porte aussi la phrase à dire."""

    def __init__(self, statut: int, message: str, detail: Any = None, phrase: str | None = None):
        super().__init__(status_code=statut, detail=detail if detail is not None else message)
        self.message = message
        self.phrase = phrase or message


class ErreurRelais(Exception):
    """Le relais a refusé (statut HTTP) ou n'a pas répondu (statut None)."""

    def __init__(self, statut: int | None, message: str = ""):
        super().__init__(message or f"relais : statut {statut}")
        self.statut = statut
        self.message = message


class _FinRelais(Exception):
    """Le relais a mis fin à la session (expiration, arrêt, remplacement, session inconnue)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------- utilitaires
def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : la même forme que voice/listener.normalize."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", texte.lower()).strip()


def cadence(horodatages, t: float) -> float:
    """Images par seconde réellement observées sur les 30 dernières secondes (même calcul que le relais).
    Si le flux s'est arrêté, la mesure baisse au lieu de figer la dernière valeur."""
    recents = [h for h in horodatages if h > t - FENETRE_CADENCE_S]
    if len(recents) < 2:
        return 0.0
    ecart = recents[-1] - recents[0]
    moyen = ecart / (len(recents) - 1)
    if t - recents[-1] > max(3 * moyen, 2.0):
        ecart = t - recents[0]
    return round((len(recents) - 1) / ecart, 2) if ecart > 0 else 0.0


def _nombre(valeur: float) -> str:
    return f"{valeur:.1f}".replace(".", ",")


def cadence_texte(fps: float) -> str | None:
    """« 3,0 images par seconde » ou « 1 image toutes les 4,2 secondes » : dit comme c'est mesuré."""
    if fps <= 0:
        return None
    if fps >= 1:
        return f"{_nombre(fps)} images par seconde (mesuré)"
    return f"1 image toutes les {_nombre(1 / fps)} secondes (mesuré)"


def nettoyer_message(brut: Any) -> str:
    """Texte d'un proche : caractères de contrôle retirés, espaces réduits, 500 caractères au plus."""
    texte = "".join(c if c.isprintable() else " " for c in str(brut or ""))
    return " ".join(texte.split())[:MESSAGE_MAX]


def compresser_jpeg(image) -> bytes:
    """Réduit (côté le plus long ≤ 1280 px) et compresse en JPEG sous la borne de 300 Ko du relais.
    ValueError si même le plus petit palier dépasse encore la borne."""
    from PIL import Image

    if image.mode != "RGB":
        image = image.convert("RGB")
    for cote, qualite in PALIERS_COMPRESSION:
        copie = image
        if max(image.size) > cote:
            copie = image.copy()
            copie.thumbnail((cote, cote), Image.LANCZOS)
        tampon = io.BytesIO()
        copie.save(tampon, format="JPEG", quality=qualite, optimize=True)
        donnees = tampon.getvalue()
        if len(donnees) <= TAILLE_MAX_IMAGE:
            return donnees
    raise ValueError("image impossible à ramener sous 300 Ko")


def preparer_photo(octets: bytes) -> bytes:
    """Une photo des lunettes, remise dans le bon sens, réduite et compressée pour le relais."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(octets))
        image.load()
        image = ImageOps.exif_transpose(image)
    except Exception:
        # Illisible pour Pillow : on ne l'envoie telle quelle que si c'est bien un JPEG sous la borne.
        if octets.startswith(DEBUT_JPEG) and len(octets) <= TAILLE_MAX_IMAGE:
            return octets
        raise ValueError("photo illisible")
    return compresser_jpeg(image)


def capturer_ecran_jpeg() -> bytes:
    """L'écran principal, en mémoire seulement (jamais écrit sur le disque), prêt pour le relais."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        moniteur = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        cliche = sct.grab(moniteur)
        image = Image.frombytes("RGB", cliche.size, cliche.rgb)
    return compresser_jpeg(image)


def _lire_puis_effacer(chemin: Path) -> bytes:
    """Lit la photo puis l'efface, dans le même fil : même si le partage est annulé pendant la lecture,
    le fichier ne reste pas sur le disque."""
    try:
        return chemin.read_bytes()
    finally:
        try:
            chemin.unlink()
        except OSError as exc:
            log.warning("photo de partage non effacée (%s)", exc)


def base_ws(base: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    return base


# --------------------------------------------------------------------------- réseau réel
class ConnexionWebsocket:
    """Une connexion WebSocket vers le relais (bibliothèque websockets), derrière une interface minimale."""

    def __init__(self, ws: Any):
        self._ws = ws

    async def envoyer_texte(self, texte: str) -> None:
        await self._ws.send(texte)

    async def envoyer_octets(self, donnees: bytes) -> None:
        await self._ws.send(donnees)

    async def recevoir(self) -> str | bytes | None:
        """Le prochain message, ou None quand la connexion est fermée."""
        try:
            return await self._ws.recv()
        except Exception:
            return None

    async def fermer(self) -> None:
        try:
            await self._ws.close()
        except Exception:
            pass

    @property
    def code_fermeture(self) -> int | None:
        return getattr(self._ws, "close_code", None)


class ClientRelais:
    """Le relais VELA, par Internet. Les tests le remplacent par un faux qui a les mêmes méthodes."""

    def __init__(self, delai_s: float = DELAI_RELAIS_S):
        self.delai_s = delai_s
        self._ssl: Any = None

    async def _contexte_ssl(self) -> Any:
        """Contexte TLS construit une seule fois, dans un fil : le charger coûte 1 à 3 secondes sur un PC
        Windows (mesuré le 2026-09-13), et le faire à chaque requête bloquerait toute la boucle d'IRIS."""
        if self._ssl is None:
            import httpx

            self._ssl = await asyncio.to_thread(httpx.create_ssl_context)
        return self._ssl

    async def _post(self, url: str, corps: dict) -> dict:
        import httpx

        try:
            contexte = await self._contexte_ssl()
            async with httpx.AsyncClient(timeout=self.delai_s, verify=contexte) as client:
                reponse = await client.post(url, json=corps)
        except Exception as exc:
            raise ErreurRelais(None, type(exc).__name__) from None
        try:
            donnees = reponse.json()
        except ValueError:
            donnees = {}
        if reponse.status_code >= 400:
            detail = donnees.get("detail") if isinstance(donnees, dict) else None
            raise ErreurRelais(reponse.status_code, detail if isinstance(detail, str) else "")
        return donnees if isinstance(donnees, dict) else {}

    async def obtenir_jeton(self, base: str, courriel: str, machine: str) -> str:
        donnees = await self._post(f"{base}/api/appareil", {"machine": machine, "email": courriel})
        return str(donnees.get("jeton") or "").strip()

    async def creer(self, base: str, jeton_appareil: str, preuve_pc: dict | None = None) -> dict:
        corps: dict = {"jeton_appareil": jeton_appareil}
        if preuve_pc:
            corps["preuve_pc"] = preuve_pc  # preuve horodatée de l'ordinateur lié (serveur/partage_vision.py)
        return await self._post(f"{base}/api/partage/creer", corps)

    async def renouveler(self, base: str, jeton_emetteur: str) -> dict:
        return await self._post(f"{base}/api/partage/renouveler", {"jeton_emetteur": jeton_emetteur})

    async def fermer(self, base: str, jeton_emetteur: str) -> None:
        await self._post(f"{base}/api/partage/fermer", {"jeton_emetteur": jeton_emetteur})

    async def connecter(self, url: str) -> ConnexionWebsocket:
        import websockets  # import tardif : un module absent ne doit pas empêcher IRIS de démarrer

        options: dict[str, Any] = {"max_size": 2**16, "open_timeout": self.delai_s}
        if url.startswith("wss://"):
            options["ssl"] = await self._contexte_ssl()
        ws = await websockets.connect(url, **options)
        return ConnexionWebsocket(ws)


# --------------------------------------------------------------------------- session
@dataclass(eq=False)
class _Session:
    code: str
    url_spectateur: str
    jeton_emetteur: str
    ws_emetteur: str
    base: str
    source: str
    type_donnee: str
    intervalle_s: float | None
    expire_a: str | None
    expire_ts: float
    spectateurs: int = 0
    images_envoyees: int = 0
    octets_envoyes: int = 0
    images_refusees: int = 0
    images_relais: int = 0
    fps_relais: float = 0.0
    emetteur_connecte: bool = False
    horodatages: deque = field(default_factory=lambda: deque(maxlen=60))
    derniere_image_ts: float | None = None
    derniere_image: bytes | None = None
    messages: deque = field(default_factory=lambda: deque(maxlen=MESSAGES_GARDES))
    raison: str | None = None
    averti_expiration: bool = False
    connexion: Any = None
    taches: list = field(default_factory=list)
    fin: bool = False
    termine: asyncio.Event = field(default_factory=asyncio.Event)
    camera_deja: bool = False
    ecran_deja: bool = False


class ServicePartage:
    def __init__(self, ctx: Any, client_relais: Any = None):
        self.ctx = ctx
        self.client_relais = client_relais or ClientRelais()
        # Remplaçables (tests) : capture d'écran synchrone -> JPEG, et fabrique de caméra des lunettes.
        self.capture_ecran: Callable[[], bytes] = capturer_ecran_jpeg
        self.fabrique_camera: Callable[[], Any] = self._camera_par_defaut
        self._session: _Session | None = None
        self._derniere_raison: str | None = None
        self._demarrage = asyncio.Lock()
        self._verrou_camera_local = asyncio.Lock()
        self._voix: set[asyncio.Task] = set()
        self._photos: set[asyncio.Task] = set()  # photos des lunettes en cours (protégées de l'annulation)
        self._eteindre_camera_ensuite = False
        self._derniere_publication = 0.0

    # ------------------------------------------------------------------ état
    @property
    def actif(self) -> bool:
        return self._session is not None

    @property
    def source(self) -> str | None:
        return self._session.source if self._session else None

    def etat(self) -> dict:
        s = self._session
        if s is None:
            return {
                "actif": False, "code": None, "url_spectateur": None, "source": None, "spectateurs": 0,
                "images_envoyees": 0, "fps_reel": 0.0, "expire_a": None, "expire_dans_s": None,
                "intervalle_s": None, "emetteur_connecte": False, "images_refusees": 0, "octets_envoyes": None,
                "derniere_image_il_y_a_s": None, "cadence_texte": None, "messages": [],
                "raison": self._derniere_raison, "note": None, "limites": list(LIMITES), "local": False,
            }
        maintenant = time.time()
        if s.source == "telephone":
            # Le téléphone émet lui-même : seules les mesures du relais disent ce qui passe.
            fps, images = s.fps_relais, s.images_relais
        else:
            fps, images = cadence(s.horodatages, time.monotonic()), s.images_envoyees
        return {
            "actif": True,
            "code": s.code,
            "url_spectateur": s.url_spectateur,
            "source": s.source,
            "spectateurs": s.spectateurs,
            "images_envoyees": images,
            "fps_reel": fps,
            "expire_a": s.expire_a,
            "expire_dans_s": max(0, int(s.expire_ts - maintenant)),
            "intervalle_s": s.intervalle_s,
            "emetteur_connecte": s.emetteur_connecte,
            "images_refusees": s.images_refusees,
            # Données réellement envoyées : dehors, sur un forfait mobile, ça compte.
            "octets_envoyes": s.octets_envoyes if s.source != "telephone" else None,
            "derniere_image_il_y_a_s": (round(maintenant - s.derniere_image_ts, 1)
                                        if s.derniere_image_ts is not None else None),
            "cadence_texte": cadence_texte(fps),
            "messages": list(s.messages),
            "raison": s.raison,
            "note": NOTES[s.source],
            "limites": list(LIMITES),
            "local": False,
        }

    def derniere_image(self, age_max_s: float = 10.0) -> bytes | None:
        """La dernière image envoyée par l'ordinateur (mémoire vive), si elle a moins de `age_max_s` secondes.
        Pendant un partage depuis les lunettes, la vision d'accessibilité peut la décrire au lieu de
        demander une seconde photo (les deux se disputeraient la caméra)."""
        s = self._session
        if s is None or s.derniere_image is None or s.derniere_image_ts is None:
            return None
        if time.time() - s.derniere_image_ts > age_max_s:
            return None
        return s.derniere_image

    def _publier_etat(self) -> None:
        self._derniere_publication = time.monotonic()
        try:
            self.ctx.hub.publish("partage.etat", **self.etat())
        except Exception as exc:  # pragma: no cover - un événement ne doit jamais casser le partage
            log.debug("état du partage non publié : %s", exc)

    # ------------------------------------------------------------------ garde-fous
    def _raison_d_arret(self, s: _Session | None = None) -> str | None:
        """Pourquoi un partage ne peut pas continuer (ou démarrer) maintenant, ou None."""
        u = self.ctx.settings.user
        if u.privacy_mode:
            return CONFIDENTIEL_ARRET
        if u.local_only:
            return LOCAL_SEULEMENT_ARRET
        if bool(getattr(getattr(self.ctx, "verrou", None), "verrouille", False)):
            return VERROU_ARRET
        if s is not None:
            try:
                if not self.ctx.consent.is_granted(s.type_donnee):
                    libelle = DATA_TYPES.get(s.type_donnee, {}).get("label", s.type_donnee)
                    return f"Consentement « {libelle} » retiré : le partage de vision est arrêté."
            except Exception as exc:  # pragma: no cover - base momentanément indisponible
                log.debug("consentement illisible : %s", exc)
        return None

    def _verifier_consentement(self, type_donnee: str) -> None:
        try:
            self.ctx.consent.check(type_donnee)
        except ConsentRequired as exc:
            libelle = DATA_TYPES.get(exc.data_type, {}).get("label", exc.data_type)
            message = (
                f"Le partage de vision envoie des images au relais VELA. Autorisez « {libelle} » dans "
                "Confidentialité, puis réessayez."
            )
            raise RefusPartage(
                403, message,
                detail={"code": "consentement", "data_type": exc.data_type, "label": libelle, "message": message},
                phrase=f"Je ne peux pas partager sans ton accord : autorise « {libelle} » dans Confidentialité.",
            )
        except LocalOnlyMode:
            raise RefusPartage(409, LOCAL_SEULEMENT)

    # ------------------------------------------------------------------ voix
    async def _dire_maintenant(self, texte: str) -> None:
        tts = getattr(self.ctx, "tts", None)
        if tts is None or not texte:
            return
        try:
            await asyncio.to_thread(tts.speak, texte, True)
        except Exception as exc:  # pragma: no cover - la voix ne doit jamais faire échouer un partage
            log.debug("lecture à voix haute impossible : %s", exc)

    def _dire(self, texte: str) -> None:
        """Parle sans bloquer la lecture des messages du relais."""
        try:
            tache = asyncio.get_running_loop().create_task(self._dire_maintenant(texte))
        except RuntimeError:
            return
        self._voix.add(tache)
        tache.add_done_callback(self._voix.discard)

    # ------------------------------------------------------------------ images
    def _camera_par_defaut(self) -> Any:
        try:
            from .lunettes_camera import CameraLunettes
        except Exception:
            raise RefusPartage(409, CAMERA_ABSENTE)
        return CameraLunettes(self.ctx.glasses)

    def _verrou_camera(self) -> asyncio.Lock:
        """Le verrou commun de la caméra : deux photos simultanées se disputeraient le Bluetooth."""
        verrou = getattr(getattr(self.ctx, "accessibilite", None), "_verrou_camera", None)
        return verrou if isinstance(verrou, asyncio.Lock) else self._verrou_camera_local

    async def _capturer_ecran(self) -> bytes:
        try:
            return await asyncio.to_thread(self.capture_ecran)
        except Exception:
            log.exception("capture d'écran pour le partage en échec")
            raise RefusPartage(500, ECRAN_RATE)

    async def _photo_lunettes(self, attente_verrou_s: float | None = None, annoncer: bool = False) -> bytes:
        """Une photo des lunettes, lue puis effacée du disque, prête pour le relais.
        Lève RefusPartage avec le message exact du module caméra quand elle est impossible."""
        camera = self.fabrique_camera()
        lunettes = getattr(camera, "glasses", None)
        if lunettes is not None and not getattr(lunettes, "connected", False):
            raise RefusPartage(409, LUNETTES_NON_CONNECTEES)
        garde = getattr(camera, "_exploration_autorisee", None)
        refus_connu = callable(garde) and not garde()
        if annoncer and self.ctx.settings.user.annonce_capture and not refus_connu:
            # « Photo. » prévient les personnes autour, comme la vision d'accessibilité — une seule fois, au
            # démarrage : répété à chaque image, ce serait du bruit. On ne l'annonce pas quand le module
            # caméra refusera de toute façon (protocole non confirmé) : ce serait annoncer une photo fantôme.
            await self._dire_maintenant("Photo.")
        verrou = self._verrou_camera()
        if attente_verrou_s is not None:
            try:
                await asyncio.wait_for(verrou.acquire(), timeout=attente_verrou_s)
            except (asyncio.TimeoutError, TimeoutError):
                raise RefusPartage(409, CAMERA_OCCUPEE)
        else:
            await verrou.acquire()
        try:
            tache = asyncio.get_running_loop().create_task(self._photo_protegee(camera, verrou))
        except BaseException:
            verrou.release()
            raise
        self._photos.add(tache)
        tache.add_done_callback(self._photo_finie)
        return await asyncio.shield(tache)

    async def _photo_protegee(self, camera: Any, verrou: asyncio.Lock) -> bytes:
        """La photo elle-même, protégée de l'annulation (asyncio.shield) : un partage arrêté pendant la prise
        de vue la laisse finir. Elle garde ainsi le verrou jusqu'au bout (pas de seconde photo simultanée sur
        le Bluetooth) et efface quand même son fichier — sans cela, une photo terminée à l'instant de l'arrêt
        resterait sur le disque, et son résultat serait perdu."""
        try:
            from .lunettes_camera import CameraIndisponible, ProtocoleNonConfirme, refus_camera_client
        except Exception:  # pragma: no cover - module caméra absent : aucune exception à reconnaître
            CameraIndisponible = ProtocoleNonConfirme = ()  # type: ignore[assignment,misc]
            refus_camera_client = lambda exc: {"code": "camera_absente", "message": str(exc)}  # noqa: E731
        try:
            try:
                resultat = await asyncio.wait_for(camera.prendre_photo(reconnaissance=False), timeout=DELAI_PHOTO_S)
            except (ProtocoleNonConfirme, CameraIndisponible) as exc:  # type: ignore[misc]
                refus = refus_camera_client(exc)
                raise RefusPartage(409, refus["message"], detail=refus)
            except RefusPartage:
                raise
            except (asyncio.TimeoutError, TimeoutError):
                raise RefusPartage(504, PHOTO_VIDE)
            except Exception:
                log.exception("photo des lunettes pour le partage en échec")
                raise RefusPartage(500, PHOTO_RATEE)
        finally:
            verrou.release()
        chemin = getattr(resultat, "chemin", None)
        if not getattr(resultat, "ok", False) or not chemin:
            raise RefusPartage(409, getattr(resultat, "constat", "") or PHOTO_VIDE)
        octets = await asyncio.to_thread(_lire_puis_effacer, Path(chemin))
        try:
            return await asyncio.to_thread(preparer_photo, octets)
        except ValueError:
            raise RefusPartage(500, PHOTO_RATEE)

    def _photo_finie(self, tache: asyncio.Task) -> None:
        self._photos.discard(tache)
        if not tache.cancelled():
            tache.exception()  # lue : une photo orpheline en erreur ne laisse pas d'avertissement
        if self._eteindre_camera_ensuite and not self._photos:
            self._eteindre_camera_ensuite = False
            self._eteindre_capture("lunettes", False, False)

    async def _image(self, source: str, attente_verrou_s: float | None = None, annoncer: bool = False) -> bytes:
        if source == "ecran":
            return await self._capturer_ecran()
        return await self._photo_lunettes(attente_verrou_s, annoncer=annoncer)

    # ------------------------------------------------------------------ relais
    async def _jeton_appareil(self, base: str, renouveler: bool = False) -> str:
        """Le jeton d'appareil VELA déjà obtenu pour le cerveau ; sinon (ou s'il est refusé) on en demande
        un au relais, exactement comme AppContext.assurer_acces_vela."""
        secrets = self.ctx.secrets
        if not renouveler:
            jeton = (secrets.get_api_key("vela") or "").strip()
            if jeton:
                return jeton
        courriel = (getattr(self.ctx.settings.user, "licence_email", "") or "").strip().lower()
        try:
            jeton = await self.client_relais.obtenir_jeton(base, courriel, f"{uuid.getnode():x}")
        except ErreurRelais as exc:
            log.info("partage : jeton d'appareil non obtenu (statut %s)", exc.statut)
            raise RefusPartage(502 if exc.statut is None else 409, RELAIS_INJOIGNABLE if exc.statut is None else SANS_ACCES)
        if not jeton:
            raise RefusPartage(409, SANS_ACCES)
        secrets.set_api_key("vela", jeton)
        return jeton

    async def _creer_session_relais(self, base: str) -> dict:
        jeton = await self._jeton_appareil(base)
        for essai in range(2):
            try:
                # Constat du 2026-09-14 : quand cet ordinateur est lié au courriel sur le relais, la création exige
                # sa preuve (sinon un tiers qui connaît le courriel fermait en boucle le partage en cours).
                preuve = getattr(getattr(self.ctx, "telecommande", None), "preuve_horodatee", None)
                preuve_pc = preuve("vela-partage-creer") if callable(preuve) else None
                creer = self.client_relais.creer
                try:
                    inspect.signature(creer).bind(base, jeton, preuve_pc)
                    avec_preuve = preuve_pc is not None
                except (TypeError, ValueError):  # client de relais d'une version antérieure
                    avec_preuve = False
                reponse = await (creer(base, jeton, preuve_pc) if avec_preuve else creer(base, jeton))
            except ErreurRelais as exc:
                if exc.statut == 401 and essai == 0:
                    jeton = await self._jeton_appareil(base, renouveler=True)
                    continue
                if exc.statut in (403, 409, 429, 503) and exc.message:
                    raise RefusPartage(exc.statut, exc.message)  # message du relais : français, sans détail technique
                log.info("partage : création refusée par le relais (statut %s)", exc.statut)
                raise RefusPartage(502, RELAIS_INJOIGNABLE)
            if not reponse.get("code") or not reponse.get("jeton_emetteur"):
                raise RefusPartage(502, RELAIS_INJOIGNABLE)
            return reponse
        raise RefusPartage(409, SANS_ACCES)  # pragma: no cover - la boucle rend ou lève toujours

    async def _fermer_session_relais(self, s: _Session) -> None:
        try:
            await asyncio.wait_for(self.client_relais.fermer(s.base, s.jeton_emetteur), timeout=DELAI_FERMETURE_S + 2)
        except Exception as exc:
            log.info("partage : fermeture sur le relais non confirmée (%s)", type(exc).__name__)

    async def _ouvrir(self, s: _Session) -> Any:
        """Connexion WebSocket annoncée (jeton dans le premier message, jamais dans l'adresse), jusqu'à « pret »."""
        role = "controle" if s.source == "telephone" else "emetteur"
        cx = await asyncio.wait_for(self.client_relais.connecter(s.ws_emetteur), timeout=DELAI_RELAIS_S)
        try:
            await cx.envoyer_texte(json.dumps({"type": "hello", "jeton": s.jeton_emetteur, "role": role,
                                               "source": s.source}))
            echeance = time.monotonic() + DELAI_RELAIS_S
            while True:
                brut = await asyncio.wait_for(cx.recevoir(), timeout=max(0.1, echeance - time.monotonic()))
                if brut is None:
                    if getattr(cx, "code_fermeture", None) in FERMETURES_DEFINITIVES:
                        raise _FinRelais(SESSION_PERDUE)
                    raise ErreurRelais(None, "connexion fermée avant « pret »")
                if isinstance(brut, (bytes, bytearray)):
                    continue
                message = json.loads(brut)
                if not isinstance(message, dict):
                    continue
                genre = message.get("type")
                if genre == "pret":
                    self._traiter(s, message)
                    return cx
                if genre == "refus" and message.get("raison") == "inconnu":
                    raise _FinRelais(SESSION_PERDUE)
                if genre == "fin":
                    raise _FinRelais(MESSAGES_FIN_RELAIS.get(str(message.get("raison")), SESSION_PERDUE))
        except BaseException:
            await cx.fermer()
            raise

    def _traiter(self, s: _Session, message: dict) -> None:
        """Un message JSON du relais. Lève _FinRelais quand la session se termine."""
        genre = message.get("type")
        if "expire_dans_s" in message:
            try:
                reste = float(message["expire_dans_s"])
                if math.isfinite(reste):
                    nouvelle = time.time() + max(0.0, reste)
                    if nouvelle > s.expire_ts + 60:
                        s.averti_expiration = False  # prolongé : on pourra prévenir de nouveau
                    s.expire_ts = nouvelle
                    s.expire_a = str(message.get("expire_a") or s.expire_a)
            except (TypeError, ValueError):
                pass
        if genre == "pret":
            s.emetteur_connecte = True
            s.spectateurs = int(message.get("spectateurs") or 0)
            s.raison = None
            self._publier_etat()
        elif genre == "stats":
            s.spectateurs = int(message.get("spectateurs") or 0)
            s.fps_relais = float(message.get("fps_reel") or 0.0)
            s.images_relais = int(message.get("images") or 0)
            if s.source == "telephone":
                s.emetteur_connecte = bool(message.get("emetteur_connecte"))
            self._publier_etat()
        elif genre == "spectateurs":
            nombre = int(message.get("nombre") or 0)
            arrivee = nombre > s.spectateurs
            s.spectateurs = nombre
            if arrivee and s.source != "telephone" and self.ctx.settings.user.annonce_capture:
                # Savoir qu'on est regardé fait partie de la confiance : IRIS le dit à chaque arrivée.
                self._dire("Une personne regarde maintenant votre partage.")
            self._publier_etat()
        elif genre == "message":
            texte = nettoyer_message(message.get("texte"))
            if not texte:
                return
            quand = str(message.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"))
            s.messages.append({"texte": texte, "ts": quand})
            # Dehors avec le téléphone, l'ordinateur est resté à la maison : c'est le téléphone qui lit.
            lu = s.source != "telephone"
            if lu:
                self._dire(f"Message de votre proche : {texte}")
            self.ctx.hub.publish("partage.message", texte=texte, ts=quand, source=s.source, lu_a_voix_haute=lu)
        elif genre == "refus":
            raison = str(message.get("raison") or "")
            if raison in ("inconnu", "complet", "trop_de_tentatives"):
                raise _FinRelais(SESSION_PERDUE)
            s.images_refusees += 1
            s.raison = str(message.get("message") or "") or None
            log.info("partage : image refusée par le relais (%s)", raison)
        elif genre == "fin":
            raison = str(message.get("raison") or "")
            raise _FinRelais(MESSAGES_FIN_RELAIS.get(raison) or str(message.get("message") or SESSION_PERDUE))

    async def _lire(self, s: _Session, cx: Any) -> None:
        while True:
            brut = await cx.recevoir()
            if brut is None:
                if getattr(cx, "code_fermeture", None) in FERMETURES_DEFINITIVES:
                    raise _FinRelais(SESSION_PERDUE)
                return
            if isinstance(brut, (bytes, bytearray)):
                continue
            try:
                message = json.loads(brut)
            except ValueError:
                continue
            if isinstance(message, dict):
                self._traiter(s, message)

    # ------------------------------------------------------------------ boucles
    async def _boucle_connexion(self, s: _Session, cx: Any) -> None:
        """Lit le relais et se reconnecte après une coupure réseau, tant que la session vit.

        Émetteur (écran, lunettes) : 5 tentatives au plus (≈ 1 minute), puis arrêt dit clairement.
        Téléphone : l'ordinateur ne fait que suivre ; perdre ce suivi ne doit pas couper le partage du
        téléphone, qui continue d'émettre. On réessaie donc jusqu'à l'expiration."""
        essais = 0
        while not s.fin:
            if cx is None:
                try:
                    cx = await self._ouvrir(s)
                except _FinRelais as fin:
                    await self._terminer(s, fin.message, fermer_relais=False)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.info("partage : connexion au relais impossible (%s)", type(exc).__name__)
                    cx = None
            if cx is not None:
                s.connexion = cx
                if s.source != "telephone":
                    s.emetteur_connecte = True
                ouverte_a = time.monotonic()
                try:
                    await self._lire(s, cx)
                except _FinRelais as fin:
                    await self._terminer(s, fin.message, fermer_relais=False)
                    return
                if s.fin:
                    return
                s.connexion = None
                await cx.fermer()
                cx = None
                if s.source != "telephone":
                    s.emetteur_connecte = False
                if time.monotonic() - ouverte_a > 60:
                    essais = 0  # une connexion qui a tenu une minute : la coupure est nouvelle
            essais += 1
            if essais > RECONNEXIONS_MAX and s.source != "telephone":
                await self._terminer(s, CONNEXION_PERDUE, fermer_relais=True)
                return
            s.raison = ("Suivi du partage momentanément indisponible : nouvelle tentative en cours."
                        if s.source == "telephone" else
                        "Connexion au relais VELA perdue : nouvelle tentative en cours.")
            self._publier_etat()
            await asyncio.sleep(min(2 ** essais, ATTENTE_RECONNEXION_MAX_S))

    async def _boucle_emission(self, s: _Session) -> None:
        """Écran : une capture par intervalle. Lunettes : photo, envoi, courte pause, et on recommence."""
        echecs = 0
        # La première image est déjà partie au démarrage : on attend un intervalle avant la suivante.
        await asyncio.sleep(s.intervalle_s if s.intervalle_s is not None else PAUSE_LUNETTES_DEFAUT_S)
        while not s.fin:
            debut = time.monotonic()
            if s.connexion is None:
                await asyncio.sleep(0.5)  # pas de capture pendant une coupure : rien à envoyer
                continue
            try:
                image = await self._image(s.source)
                echecs = 0
            except RefusPartage as exc:
                if s.fin:
                    return
                if exc.status_code == 409:  # lunettes déconnectées, caméra refusée : inutile d'insister
                    message = LUNETTES_DECONNECTEES if exc.message == LUNETTES_NON_CONNECTEES else exc.message
                    await self._terminer(s, message, fermer_relais=True)
                    return
                echecs += 1
                if echecs >= ECHECS_CAPTURE_MAX:
                    await self._terminer(s, exc.message, fermer_relais=True)
                    return
                await asyncio.sleep(1.0)
                continue
            # Dernier contrôle juste avant l'envoi : une image captée avant le mode confidentiel ne part pas.
            if s.fin or self._raison_d_arret(s):
                return
            await self._envoyer_image(s, image)
            if s.source == "ecran":
                await asyncio.sleep(max(0.0, (s.intervalle_s or INTERVALLE_ECRAN_DEFAUT_S) - (time.monotonic() - debut)))
            else:
                await asyncio.sleep(s.intervalle_s if s.intervalle_s is not None else PAUSE_LUNETTES_DEFAUT_S)

    async def _envoyer_image(self, s: _Session, image: bytes) -> None:
        cx = s.connexion
        if cx is None or not image:
            return
        if len(image) > TAILLE_MAX_IMAGE:
            s.images_refusees += 1
            return
        try:
            await cx.envoyer_octets(image)
        except Exception as exc:
            log.info("partage : image non envoyée (%s)", type(exc).__name__)
            return
        s.images_envoyees += 1
        s.octets_envoyes += len(image)
        s.horodatages.append(time.monotonic())
        s.derniere_image_ts = time.time()
        s.derniere_image = image

    async def _boucle_surveillance(self, s: _Session) -> None:
        """Chaque seconde : confidentialité, consentement, verrou, expiration ; et l'état publié toutes les 5 s."""
        while not s.fin:
            await asyncio.sleep(SURVEILLANCE_S)
            if s.fin:
                return
            raison = self._raison_d_arret(s)
            if raison:
                await self._terminer(s, raison, fermer_relais=True)
                return
            reste = s.expire_ts - time.time()
            if reste <= 0:
                await self._terminer(s, EXPIRE, fermer_relais=True)
                return
            if reste <= AVERTISSEMENT_EXPIRATION_S and not s.averti_expiration:
                s.averti_expiration = True
                if s.source != "telephone":
                    self._dire("Le partage de vision se termine dans deux minutes. Dites « prolonge le partage » pour le garder.")
                self._publier_etat()
            if time.monotonic() - self._derniere_publication >= PUBLICATION_ETAT_S:
                self._publier_etat()

    # ------------------------------------------------------------------ cycle de vie
    async def demarrer(self, source: str, intervalle_s: float | None = None) -> dict:
        source = (source or "").strip().lower()
        if source not in SOURCES:
            raise RefusPartage(422, f"Source inconnue : « {source} ». Sources : {', '.join(SOURCES)}.")
        u = self.ctx.settings.user
        if u.privacy_mode:
            raise RefusPartage(409, CONFIDENTIEL)
        if self._session is not None:
            raise RefusPartage(409, DEJA_ACTIF)
        if self._demarrage.locked():
            raise RefusPartage(409, DEMARRAGE_EN_COURS)
        async with self._demarrage:
            return await self._demarrer(source, intervalle_s)

    def _intervalle(self, source: str, intervalle_s: float | None) -> float | None:
        if source == "telephone":
            return None  # c'est le téléphone qui décide de sa cadence
        valide = intervalle_s is not None and isinstance(intervalle_s, (int, float)) and math.isfinite(intervalle_s)
        if source == "ecran":
            valeur = float(intervalle_s) if valide else INTERVALLE_ECRAN_DEFAUT_S  # type: ignore[arg-type]
            return round(min(INTERVALLE_ECRAN_MAX_S, max(INTERVALLE_ECRAN_MIN_S, valeur)), 2)
        valeur = float(intervalle_s) if valide else PAUSE_LUNETTES_DEFAUT_S  # type: ignore[arg-type]
        return round(min(PAUSE_LUNETTES_MAX_S, max(0.0, valeur)), 2)

    async def _demarrer(self, source: str, intervalle_s: float | None) -> dict:
        ctx = self.ctx
        u = ctx.settings.user
        if u.local_only:
            raise RefusPartage(409, LOCAL_SEULEMENT)
        type_donnee = "screen" if source == "ecran" else "image"
        self._verifier_consentement(type_donnee)
        try:
            from .connectors import base_relais_effective

            base = base_relais_effective(ctx.settings)
        except Exception:  # pragma: no cover - connecteurs indisponibles
            base = (u.relay_server or "").strip().rstrip("/")
        if not base:
            raise RefusPartage(409, SANS_RELAIS)
        intervalle = self._intervalle(source, intervalle_s)

        # Première image AVANT de créer quoi que ce soit sur le relais : si la caméra ou la capture
        # refuse, aucun lien n'existe et le message exact remonte (409 du module caméra, par exemple).
        capture = ctx.capture.snapshot()
        camera_deja, ecran_deja = bool(capture.get("camera")), bool(capture.get("screen"))
        premiere: bytes | None = None
        if source != "telephone":
            ctx.capture.set(**({"screen": True} if source == "ecran" else {"camera": True}))
            try:
                premiere = await self._image(source, attente_verrou_s=DELAI_PHOTO_S, annoncer=True)
            except BaseException:
                self._eteindre_capture(source, camera_deja, ecran_deja, pendant_demarrage=True)
                raise
        try:
            reponse = await self._creer_session_relais(base)
            expire_dans = float(reponse.get("expire_dans_s") or 1800)
            ws = (str(reponse.get("ws_emetteur") or "") if source == "telephone" else "") or f"{base_ws(base)}/partage/emetteur"
            s = _Session(
                code=str(reponse["code"]), url_spectateur=str(reponse.get("url_spectateur") or f"{base}/voir/{reponse['code']}"),
                jeton_emetteur=str(reponse["jeton_emetteur"]), ws_emetteur=ws, base=base, source=source,
                type_donnee=type_donnee, intervalle_s=intervalle, expire_a=reponse.get("expire_a"),
                expire_ts=time.time() + expire_dans, camera_deja=camera_deja, ecran_deja=ecran_deja,
            )
            cx = None
            if source != "telephone":
                try:
                    cx = await self._ouvrir(s)
                except BaseException as exc:
                    await self._fermer_session_relais(s)
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    log.info("partage : connexion émettrice impossible (%s)", type(exc).__name__)
                    raise RefusPartage(502, RELAIS_INJOIGNABLE)
                s.connexion = cx
                await self._envoyer_image(s, premiere or b"")
        except BaseException:
            self._eteindre_capture(source, camera_deja, ecran_deja, pendant_demarrage=True)
            raise

        self._session = s
        self._derniere_raison = None
        boucle = asyncio.get_running_loop()
        s.taches.append(boucle.create_task(self._boucle_connexion(s, cx)))
        if source != "telephone":
            s.taches.append(boucle.create_task(self._boucle_emission(s)))
        s.taches.append(boucle.create_task(self._boucle_surveillance(s)))
        try:
            ctx.consent.log("partage_vision_demarre", data_type=type_donnee, detail=f"source={source}")
        except Exception as exc:  # pragma: no cover
            log.warning("registre de confidentialité indisponible : %s", exc)
        log.info("partage : démarré (source %s)", source)
        if source != "telephone" and u.annonce_capture:
            self._dire(f"Partage de vision démarré depuis {LIBELLES_SOURCES[source]}.")
        self._publier_etat()
        return {
            "code": s.code,
            "url_spectateur": s.url_spectateur,
            "expire_a": s.expire_a,
            "source": source,
            # Le jeton émetteur ne sort d'ici que vers le téléphone, qui émet lui-même.
            "jeton_emetteur": s.jeton_emetteur if source == "telephone" else None,
            "ws_emetteur": s.ws_emetteur if source == "telephone" else None,
            "actif": True,
            "expire_dans_s": int(expire_dans),
            "intervalle_s": intervalle,
            "note": NOTES[source],
            "limites": list(LIMITES),
            "local": False,
        }

    def _eteindre_capture(self, source: str, camera_deja: bool, ecran_deja: bool, pendant_demarrage: bool = False) -> None:
        """Éteint le témoin allumé par le partage, sauf s'il l'était déjà ou si un autre service s'en sert."""
        if source == "ecran" and not ecran_deja:
            self.ctx.capture.set(screen=False)
        elif source == "lunettes" and not camera_deja:
            if self._photos:
                # Une photo protégée se termine encore : le témoin reste allumé jusqu'à sa fin réelle.
                self._eteindre_camera_ensuite = True
                return
            if (self._demarrage.locked() and not pendant_demarrage) or (
                    self._session is not None and self._session.source == "lunettes"):
                return  # un nouveau partage depuis les lunettes démarre ou tourne : la caméra sert encore
            verrou = getattr(getattr(self.ctx, "accessibilite", None), "_verrou_camera", None)
            if not (isinstance(verrou, asyncio.Lock) and verrou.locked()):
                self.ctx.capture.set(camera=False)

    async def _terminer(self, s: _Session, raison: str, fermer_relais: bool = True, par_utilisateur: bool = False) -> None:
        courante = asyncio.current_task()
        if s.fin:
            if courante not in s.taches:
                await s.termine.wait()  # un autre chemin termine déjà : on attend qu'il ait fini
            return
        s.fin = True
        if self._session is s:
            self._session = None
        self._derniere_raison = raison
        # La connexion est prise AVANT d'annuler les boucles : c'est par elle qu'on dit « fin » au relais.
        cx, s.connexion = s.connexion, None
        autres = [t for t in s.taches if t is not courante and not t.done()]
        for tache in autres:
            tache.cancel()
        if autres:
            await asyncio.wait(autres, timeout=DELAI_FERMETURE_S)
        try:
            if fermer_relais:
                envoye = False
                if cx is not None:
                    try:
                        await asyncio.wait_for(cx.envoyer_texte(json.dumps({"type": "fin"})), timeout=DELAI_FERMETURE_S)
                        envoye = True
                    except Exception:
                        envoye = False
                if not envoye:
                    await self._fermer_session_relais(s)
            if cx is not None:
                try:
                    await asyncio.wait_for(cx.fermer(), timeout=DELAI_FERMETURE_S)
                except Exception:
                    pass
        finally:
            self._eteindre_capture(s.source, s.camera_deja, s.ecran_deja)
            s.derniere_image = None
            s.messages.clear()
            try:
                self.ctx.consent.log("partage_vision_arrete", data_type=s.type_donnee,
                                     detail=f"source={s.source} ; {s.images_envoyees} image(s) envoyée(s) ; {raison}")
            except Exception as exc:  # pragma: no cover
                log.warning("registre de confidentialité indisponible : %s", exc)
            log.info("partage : terminé (%s image(s) envoyée(s))", s.images_envoyees)
            # Mode confidentiel ou verrouillage : IRIS se tait. Sinon, une fin non demandée est dite.
            if not par_utilisateur and s.source != "telephone" and raison not in (CONFIDENTIEL_ARRET, VERROU_ARRET):
                self._dire(raison)
            self._publier_etat()
            s.termine.set()

    async def arreter(self, raison: str | None = None) -> dict:
        s = self._session
        if s is not None:
            await self._terminer(s, raison or ARRETE, fermer_relais=True, par_utilisateur=True)
        return self.etat()

    async def prolonger(self) -> dict:
        s = self._session
        if s is None:
            raise RefusPartage(409, AUCUN_PARTAGE)
        try:
            reponse = await self.client_relais.renouveler(s.base, s.jeton_emetteur)
        except ErreurRelais as exc:
            if exc.statut == 404:
                await self._terminer(s, SESSION_PERDUE, fermer_relais=False)
                raise RefusPartage(409, SESSION_PERDUE)
            raise RefusPartage(502, RELAIS_INJOIGNABLE)
        self._traiter(s, {"type": "expiration", **reponse})
        s.averti_expiration = False
        try:
            self.ctx.consent.log("partage_vision_prolonge", data_type=s.type_donnee, detail=f"source={s.source}")
        except Exception:  # pragma: no cover
            pass
        self._publier_etat()
        return self.etat()

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str):
        """Arrêter, prolonger ou demander qui regarde, à la voix. None tout de suite si ce n'est pas pour nous.

        Le démarrage à la voix n'est volontairement pas offert : une phrase mal reconnue ne doit jamais
        diffuser l'écran ou la caméra à qui a le lien."""
        t = f" {normaliser(texte)} "
        if " partag" not in t:  # le mot « partage » est exigé : « arrête de regarder la télé » n'est pas pour nous
            return None
        vise_vision = any(m in t for m in (" vision", " vue ", " camera", " ecran", " lunettes"))
        if not self.actif and not vise_vision:
            return None  # « arrête le partage de connexion » sans partage en cours : le modèle s'en charge
        if any(m in t for m in (" arrete ", " arreter ", " arretes ", " stop ", " stoppe ", " coupe ", " couper ",
                                " termine ", " terminer ", " fin du partage", " fin de partage", " ferme ", " fermer ")):
            return self._voix_arreter()
        if any(m in t for m in (" prolonge", " garde le partage", " renouvelle")):
            return self._voix_prolonger()
        if any(m in t for m in (" qui regarde", " quelqu un regarde", " combien de personnes", " partage est il",
                                " partage actif", " etat du partage", " ou en est le partage")):
            return self._voix_etat()
        return None

    async def _voix_arreter(self) -> str:
        if not self.actif:
            return AUCUN_PARTAGE
        await self.arreter()
        return ARRETE

    async def _voix_prolonger(self) -> str:
        try:
            etat = await self.prolonger()
        except RefusPartage as exc:
            return exc.phrase
        minutes = max(1, int((etat.get("expire_dans_s") or 0) // 60))
        return f"Partage prolongé : il reste {minutes} minutes."

    async def _voix_etat(self) -> str:
        etat = self.etat()
        if not etat["actif"]:
            return AUCUN_PARTAGE
        n = etat["spectateurs"]
        qui = "Personne ne regarde" if n == 0 else ("Une personne regarde" if n == 1 else f"{n} personnes regardent")
        minutes = max(0, int((etat.get("expire_dans_s") or 0) // 60))
        return f"{qui} votre partage depuis {LIBELLES_SOURCES[etat['source']]}. Il reste {minutes} minutes."

    def brancher(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("partage", self.interception, priorite=60)

    async def fermer(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("partage")
        if self._session is not None:
            await self.arreter(ARRET_IRIS)
