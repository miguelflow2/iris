"""Caméra des lunettes VELA : prendre une photo et rapatrier l'image EN LOCAL.

C'est la fonction différenciante de VELA. Le SDK d'origine (XSX) envoie l'image à des clouds
chinois (Baidu / xinsudian / Aliyun) pour l'analyser ; ici, IRIS déclenche la prise de vue,
récupère le JPEG sur l'appareil, et le confie à SA PROPRE IA. L'image ne part jamais chez un tiers.

Ce module RÉUTILISE la connexion BLE d'IRIS (`GlassesService`, backend/iris/glasses.py) :
même thread Bleak dédié (`_on_ble`), même `BleakClient`. Il ne rouvre pas de connexion.

État de la rétro-ingénierie — à lire avant de s'y fier (détail complet : docs/LUNETTES-CAMERA-PROTOCOLE.md) :

    CERTAIN (vu dans le SDK) :
      - Les lunettes-caméra exposent le service Jieli RCSP `ae00` : écriture sur `ae01`,
        notifications (réponses + fichiers) sur `ae02`.
      - La commande photo porte la charge utile `01 04 00` (photo simple) ou `01 07 00`
        (photo pour reconnaissance IA), dans une trame de type « Camera ».
      - Le fichier revient soit par BLE (trames FileStartTransfer / FilePackTransfer /
        FileTransferFinished sur `ae02`), soit par WiFi (les lunettes ouvrent un point d'accès,
        téléchargement HTTP depuis leur IP locale).

    À CONFIRMER (bytecode obfusqué, non prouvé) :
      - L'EN-TÊTE exact de la trame « Pro » (octet magique, type sur le fil, longueur, CRC).
        On sait seulement qu'il fait 5 octets et dérive probablement du cadre RCSP Jieli
        (magie 0xFE..., cf. LUNETTES-PUCE.md). => `fabriquer_trame_camera()` est donc marquée
        NON CONFIRMÉE et le module REFUSE d'écrire à l'aveugle, sauf réglage « exploration ».
      - Les octets d'acquittement du transfert de fichier BLE.

    NON TESTÉ : rien de tout ceci n'a tourné sur les vraies lunettes-caméra. La paire audio que
    nous avons aujourd'hui n'a NI caméra NI service `ae00` : ce module lèvera une erreur claire
    sur elle. Il faut la paire caméra pour valider.

Le module suit volontairement la même discipline que glasses.py : ne jamais prétendre un effet
qu'on n'a pas constaté ; ne jamais deviner des octets et les écrire dans une puce dont les
commandes voisines portent l'effacement des données.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("iris.lunettes_camera")

# --- UUID du service applicatif des lunettes-caméra (Jieli RCSP « ae00 ») -------------------
# [ÉTABLI] com/xsx/rdbluetooth/utils/BluetoothConstant.class (XSXBluetooth_V1.0.1.aar)
SERVICE_UUID = "0000ae00-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"      # on ÉCRIT les commandes ici
NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"     # on ÉCOUTE réponses + fichiers ici

# --- Charges utiles caméra ------------------------------------------------------------------
# [ÉTABLI] lues dans RDProSendUtils.takeAPicture() / takePictureAndRecognize() (XSXGlass)
PAYLOAD_PHOTO = bytes([0x01, 0x04, 0x00])            # photo simple
PAYLOAD_PHOTO_RECONNAISSANCE = bytes([0x01, 0x07, 0x00])  # photo « à analyser » (mode 0x07)

# --- Types de trame « Pro » (enum ProBeanEnum, ordinal) -------------------------------------
# [ÉTABLI pour l'ordinal ; À CONFIRMER que l'octet sur le fil = l'ordinal]
TYPE_CAMERA = 2
TYPE_FILE_START = 11    # FileStartTransfer  : nom + taille du fichier qui arrive
TYPE_FILE_PACK = 12     # FilePackTransfer   : un paquet de données (répété)
TYPE_FILE_FINISHED = 13  # FileTransferFinished

# En-tête de la trame « Pro » : 5 octets, structure non confirmée (voir docstring / doc §6).
_TAILLE_ENTETE_ESTIMEE = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CameraIndisponible(RuntimeError):
    """Levée quand les lunettes connectées n'exposent pas l'interface caméra (`ae01`/`ae02`)."""


class ProtocoleNonConfirme(RuntimeError):
    """Levée quand on refuse d'écrire une trame dont les octets ne sont pas prouvés."""


# --- Ce que le CLIENT lit quand la caméra refuse (demande de la revue renderer, 2026-09-14) ----------------
# Le texte des exceptions ci-dessus est technique (charge utile en hexadécimal, chemin d'un document interne,
# nom d'un réglage d'exploration qui écrirait des octets non prouvés dans la puce) : il reste au journal. Les
# routes, les outils et la voix rendent {code, message}, avec une phrase qui dit ce qui est vrai.
MESSAGE_CAMERA_NON_CONFIRMEE = (
    "La caméra des lunettes n’est pas encore activée dans IRIS (son protocole est en cours de confirmation) : "
    "aucune photo n’a été prise. En attendant, utilisez une photo prise avec votre téléphone, ou l’écran de "
    "l’ordinateur."
)
MESSAGE_CAMERA_ABSENTE = "Ces lunettes n’exposent pas de caméra utilisable par IRIS : aucune photo n’a été prise."
MESSAGE_LUNETTES_NON_CONNECTEES = "Les lunettes ne sont pas connectées."


def refus_camera_client(exc: BaseException) -> dict:
    """{"code", "message"} à rendre au client pour un refus du module caméra ; le texte technique va au journal.

    Codes : camera_non_confirmee (protocole non prouvé : aucune paire n'écrit la commande photo), camera_absente
    (pas d'interface caméra sur la paire connectée), lunettes_non_connectees."""
    log.info("refus de la caméra des lunettes : %s", exc)
    if isinstance(exc, ProtocoleNonConfirme):
        return {"code": "camera_non_confirmee", "message": MESSAGE_CAMERA_NON_CONFIRMEE}
    if str(exc).strip() == MESSAGE_LUNETTES_NON_CONNECTEES:
        return {"code": "lunettes_non_connectees", "message": MESSAGE_LUNETTES_NON_CONNECTEES}
    return {"code": "camera_absente", "message": MESSAGE_CAMERA_ABSENTE}


def camera_lunettes_active(settings) -> bool:
    """Le module accepte-t-il d'écrire la commande photo ? Faux tant que l'en-tête de trame n'est pas prouvé
    (seul le réglage d'exploration du propriétaire l'autorise). Les écrans le lisent au lieu de le supposer."""
    try:
        return bool(settings.user.lunettes_exploration)
    except Exception:
        return False


@dataclass
class ResultatPhoto:
    """Ce qu'on rapporte APRÈS une tentative de photo. Honnête par construction : dit ce qui a
    été envoyé et ce qui est revenu, sans prétendre à une image qu'on n'aurait pas reçue."""
    ok: bool
    chemin: str | None = None          # chemin du JPEG si on a su le reconstituer
    octets: int = 0                    # taille de l'image reçue
    envoye_hex: str | None = None      # la trame écrite sur ae01 (pour trace)
    paquets_recus: list[str] = field(default_factory=list)  # ae02 bruts (hex), pour analyse
    constat: str = ""                  # phrase lisible pour IRIS / l'utilisateur


def fabriquer_trame_camera(payload: bytes, type_trame: int = TYPE_CAMERA) -> bytes:
    """Construit la trame « Pro » à écrire sur ae01. ⚠ EN-TÊTE NON CONFIRMÉ.

    L'en-tête réel (5 octets) n'a pas pu être lu de façon fiable dans le bytecode. La forme
    ci-dessous est une HYPOTHÈSE plausible (dérivée du cadre RCSP Jieli `FE DC BA … EF` et du
    protocole 0xBC de la même famille : magie + type + longueur 16 bits + CRC-16/MODBUS), mais
    elle N'EST PAS prouvée. Ne pas s'y fier tant qu'un sniff BLE ou une décompilation jadx ne
    l'a pas confirmée.

    TODO(caméra) — à valider sur le vrai matériel / par sniff :
      * octet(s) magique(s) de début (probablement 0xFE… côté Jieli, PAS 0xBC de la paire audio) ;
      * ordre exact type / longueur / index-total de fragment ;
      * présence et position du CRC (CRC-16/MODBUS ? XMODEM ?) ;
      * fragmentation à la taille du MTU (RDProSendUtils.rda utilise RDUtils.splitByteArr).
    """
    # Réutilise le CRC-16/MODBUS déjà validé sur cette famille de lunettes (lunettes_trames.py),
    # au cas où la trame « Pro » partage le même contrôle. À CONFIRMER.
    try:
        from . import lunettes_trames
        crc = lunettes_trames.crc_modbus(payload).to_bytes(2, "little")
    except Exception:  # pragma: no cover - défensif
        crc = b"\x00\x00"
    # HYPOTHÈSE de trame (NON CONFIRMÉE) : 0xFE | type | longueur(2, LE) | CRC(2, LE) | payload
    return bytes([0xFE, type_trame & 0xFF]) + len(payload).to_bytes(2, "little") + crc + payload


class CameraLunettes:
    """Pilote la caméra en s'appuyant sur la connexion BLE existante d'IRIS.

    Usage :
        cam = CameraLunettes(ctx.glasses)
        res = await cam.prendre_photo()
    """

    def __init__(self, glasses, settings=None) -> None:
        # `glasses` : instance de GlassesService (backend/iris/glasses.py).
        self.glasses = glasses
        # settings est optionnel : par défaut on prend celui du GlassesService.
        self.settings = settings if settings is not None else getattr(glasses, "settings", None)

    # ------------------------------------------------------------------ helpers BLE
    @property
    def _client(self):
        return getattr(self.glasses, "client", None)

    def _caracteristiques(self):
        """Retrouve les caractéristiques d'écriture (ae01) et de notification (ae02).

        Lève CameraIndisponible si elles manquent — c'est le cas de la paire AUDIO actuelle,
        qui n'a ni caméra ni service ae00. On le dit clairement plutôt que d'échouer en silence."""
        client = self._client
        if client is None or not getattr(client, "is_connected", False):
            raise CameraIndisponible(MESSAGE_LUNETTES_NON_CONNECTEES)
        ecriture = notification = None
        for service in client.services:
            for car in service.characteristics:
                uuid = str(car.uuid).lower()
                if uuid == WRITE_UUID:
                    ecriture = car
                elif uuid == NOTIFY_UUID:
                    notification = car
        if ecriture is None or notification is None:
            raise CameraIndisponible(
                "Ces lunettes n'exposent pas l'interface caméra (service ae00, caractéristiques "
                "ae01/ae02). C'est normal sur la paire AUDIO actuelle : elle n'a pas de caméra. "
                "Le module caméra vise la paire caméra de VELA."
            )
        return ecriture, notification

    def _exploration_autorisee(self) -> bool:
        """La même garde que glasses.py : on n'écrit une trame non confirmée que si l'utilisateur
        a explicitement activé « lunettes_exploration », en connaissance de cause."""
        try:
            return bool(self.settings.user.lunettes_exploration)
        except Exception:
            return False

    def _dossier_captures(self) -> Path:
        try:
            base = Path(self.settings.data_dir) / "captures"
        except Exception:
            base = Path.home() / "iris-captures"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ------------------------------------------------------------------ prise de photo
    async def prendre_photo(self, reconnaissance: bool = False, timeout: float = 20.0) -> ResultatPhoto:
        """Déclenche une photo et tente de rapatrier l'image par BLE.

        `reconnaissance=False` -> charge utile 01 04 00 (photo simple, chemin 100 % local).
        `reconnaissance=True`  -> charge utile 01 07 00 (le SDK d'origine l'envoyait au cloud ;
                                  ici on récupère juste l'image, l'analyse restera locale).

        Renvoie un ResultatPhoto HONNÊTE : si l'en-tête de trame n'est pas encore confirmé et que
        l'exploration n'est pas activée, on NE tente PAS d'écrire dans la puce et on l'explique.
        Si on écrit (exploration activée), on capture les paquets ae02 et on tente une
        reconstitution ; à défaut, on renvoie les paquets bruts pour analyse — jamais une image
        inventée.
        """
        # 1) L'interface caméra est-elle là ? (échoue proprement sur la paire audio)
        ecriture, notification = await self.glasses._on_ble(self._caracteristiques_async())

        payload = PAYLOAD_PHOTO_RECONNAISSANCE if reconnaissance else PAYLOAD_PHOTO
        trame = fabriquer_trame_camera(payload, TYPE_CAMERA)

        # 2) Garde de sécurité : l'en-tête n'est pas prouvé. Écrire des octets devinés dans une
        #    puce Jieli est risqué (les commandes voisines portent l'effacement). On refuse, sauf
        #    exploration explicite. C'est la leçon de glasses.py, appliquée telle quelle.
        if not self._exploration_autorisee():
            raise ProtocoleNonConfirme(
                "La commande photo est identifiée (charge utile " + payload.hex() + "), mais "
                "l'en-tête exact de la trame n'est pas encore confirmé (voir "
                "docs/LUNETTES-CAMERA-PROTOCOLE.md §6). Par prudence, IRIS n'écrit pas d'octets "
                "non prouvés dans les lunettes. Pour tester en connaissance de cause, activez "
                "« lunettes_exploration » dans les réglages, avec la vraie paire caméra."
            )

        # 3) Exploration activée : on capture ae02, on écrit la trame, on attend le fichier.
        collecteur = _CollecteurFichier()
        try:
            await self.glasses._on_ble(self._ecouter_puis_envoyer(
                notification, ecriture, trame, collecteur, timeout))
        finally:
            # Rendre la main au gestionnaire de notifications normal des lunettes (batterie, etc.).
            try:
                await self.glasses._on_ble(self._reabonner_glasses(notification))
            except Exception as exc:  # pragma: no cover
                log.debug("réabonnement ae02 échoué : %s", exc)

        paquets_hex = [p.hex() for p in collecteur.paquets]
        image = collecteur.assembler_image()
        if image:
            chemin = self._enregistrer(image, reconnaissance)
            return ResultatPhoto(
                ok=True, chemin=str(chemin), octets=len(image), envoye_hex=trame.hex(),
                paquets_recus=paquets_hex,
                constat="Photo reçue ({} octets) et enregistrée.".format(len(image)),
            )
        return ResultatPhoto(
            ok=False, envoye_hex=trame.hex(), paquets_recus=paquets_hex,
            constat=(
                "Trame envoyée, {} paquet(s) reçu(s) sur ae02, mais je n'ai pas su reconstituer "
                "d'image (format de transfert à confirmer). Les paquets bruts sont joints pour "
                "analyse.".format(len(paquets_hex))
            ),
        )

    # -- coroutines exécutées sur le thread Bleak dédié (via glasses._on_ble) -----------------
    async def _caracteristiques_async(self):
        return self._caracteristiques()

    async def _ecouter_puis_envoyer(self, notification, ecriture, trame, collecteur, timeout):
        client = self._client
        # On remplace temporairement le handler de notif de ae02 par notre collecteur.
        await client.start_notify(notification, collecteur.on_notify)
        sans_reponse = "write-without-response" in ecriture.properties
        log.info("caméra : écriture trame %s sur ae01", trame.hex())
        await client.write_gatt_char(ecriture, trame, response=not sans_reponse)
        # Attendre soit la fin de transfert, soit le timeout.
        try:
            await asyncio.wait_for(collecteur.termine.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            log.info("caméra : délai dépassé, %d paquet(s) reçus", len(collecteur.paquets))

    async def _reabonner_glasses(self, notification):
        client = self._client
        if client is None:
            return
        handler = getattr(self.glasses, "_on_notify", None)
        if handler is not None:
            await client.start_notify(notification, handler)

    def _enregistrer(self, image: bytes, reconnaissance: bool) -> Path:
        horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffixe = "-reco" if reconnaissance else ""
        chemin = self._dossier_captures() / f"lunettes-{horodatage}{suffixe}.jpg"
        chemin.write_bytes(image)
        log.info("caméra : image enregistrée -> %s", chemin)
        return chemin


class _CollecteurFichier:
    """Rassemble les paquets ae02 pendant une capture et tente de reconstituer le fichier.

    Le découpage exact des trames FileStart/FilePack/FileFinished est À CONFIRMER ; en attendant,
    ce collecteur (1) garde tous les paquets bruts pour analyse, et (2) tente une reconstitution
    « best effort » en repérant les bornes JPEG (FF D8 … FF D9), ce qui suffit souvent à extraire
    l'image même sans décoder l'en-tête propriétaire.
    """

    def __init__(self) -> None:
        self.paquets: list[bytes] = []
        self.termine = asyncio.Event()

    def on_notify(self, _sender, data: bytearray) -> None:
        brut = bytes(data)
        self.paquets.append(brut)
        # TODO(caméra) : décoder l'en-tête « Pro » pour lire type/index/total et détecter
        # proprement FileTransferFinished (type 13). En attendant, on s'arrête sur le marqueur
        # de fin de JPEG s'il apparaît.
        if b"\xff\xd9" in brut and any(b"\xff\xd8" in p for p in self.paquets):
            self.termine.set()

    def assembler_image(self) -> bytes | None:
        """Extrait le JPEG du flux concaténé si les marqueurs sont présents. Sinon None.

        Heuristique honnête et sans en-tête propriétaire : on cherche FF D8 (début JPEG) et le
        dernier FF D9 (fin JPEG) dans la concaténation brute. Cela contourne l'en-tête « Pro »
        de chaque paquet — imparfait (l'en-tête de 5 octets pollue le flux), mais utile pour un
        premier test, et remplaçable dès que le format de trame est confirmé (voir TODO ci-dessus).
        """
        flux = b"".join(self.paquets)
        debut = flux.find(b"\xff\xd8\xff")
        fin = flux.rfind(b"\xff\xd9")
        if debut != -1 and fin != -1 and fin > debut:
            candidat = flux[debut:fin + 2]
            if len(candidat) > 512:  # un JPEG plausible, pas un fragment
                return candidat
        return None
