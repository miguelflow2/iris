"""Vision d'accessibilité : décrire ce qu'il y a devant l'utilisateur, lire un texte, compter l'argent.

Pensé d'abord pour une personne aveugle ou malvoyante, qui NE PEUT PAS vérifier ce qu'IRIS lui dit.
Tout le module découle de ce constat :

- Local d'abord. Lire un texte passe par l'OCR hors-ligne (RapidOCR) avant tout moteur ; la couleur
  a une estimation locale ; l'affichage (numéro de bus, panneau) et l'écran retombent sur le texte lu
  localement quand le moteur n'est pas permis. Rien ne part sans consentement (consent.check), et
  chaque envoi est journalisé par ChatService.demander_image_detail.
- Pas d'invention. Les consignes exigent l'ordre spatial, les mots exacts, les montants exacts et un
  « je ne suis pas sûre » quand c'est le cas. Une remise en ordre de texte par le moteur qui s'écarte
  trop de l'OCR est rejetée au profit du texte brut : un résumé présenté comme une lecture est pire
  qu'une lecture mal ordonnée.
- Pas d'identification. Le mode « personnes » décrit (nombre, position, vêtements, gestes) et ne
  reconnaît personne : la reconnaissance nominative exigerait un consentement exprès et une
  déclaration préalable à la Commission d'accès à l'information du Québec.
- Pas de promesse de sécurité. Les lunettes prennent une photo en quelques secondes ; il n'existe
  aucun flux vidéo. Une description n'est jamais une alerte d'obstacle en temps réel, et la consigne
  interdit au moteur de le laisser croire.

Service exposé sous ctx.accessibilite (voir routes_accessibilite.py).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import io
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .connectors.base import ConnectorError
from .consent import DATA_TYPES, ConsentRequired, LocalOnlyMode
from .lunettes_camera import CameraIndisponible, CameraLunettes, ProtocoleNonConfirme
from .memory import MemoireSuspendue, tokenize
from .pc import actions
from .router import NoAgentAvailable

log = logging.getLogger("iris.accessibilite")

SOURCES = ("lunettes", "ecran", "image")

# Chaque mode dit ce qu'il fait ET sa limite, en une phrase : c'est ce texte que l'écran
# Accessibilité affiche. `local` = le mode donne un résultat sans que rien ne quitte l'appareil.
MODES: dict[str, dict[str, Any]] = {
    "scene": {
        "nom": "Qu'est-ce qu'il y a devant moi ?",
        "description": "Décrit le lieu et ce qui s'y trouve, de gauche à droite et du plus proche au plus loin.",
        "limite": "Décrit une photo prise il y a quelques secondes : ce n'est pas une surveillance en direct ni une alerte d'obstacle. Exige le moteur VELA.",
        "local": False,
        "phrases": ["Qu'est-ce qu'il y a devant moi ?", "Décris ce que je vois"],
    },
    "lecture": {
        "nom": "Lis-moi ça",
        "description": "Lit le texte visible mot pour mot, lu d'abord sur l'appareil par la lecture de texte locale.",
        "limite": "Sans le moteur, les colonnes côte à côte peuvent se mêler et l'écriture manuscrite est mal lue.",
        "local": True,
        "phrases": ["Lis-moi ça", "Lis ce texte"],
    },
    "objet": {
        "nom": "C'est quoi cet objet ?",
        "description": "Nomme l'objet ou le produit tenu devant les lunettes : marque, format, prix affiché, chiffres du code-barres s'ils sont lisibles.",
        "limite": "Un produit peu connu ou mal cadré peut être mal reconnu ; IRIS dit quand elle n'est pas sûre. Exige le moteur VELA.",
        "local": False,
        "phrases": ["C'est quoi cet objet ?"],
    },
    "couleur": {
        "nom": "C'est quelle couleur ?",
        "description": "Dit la couleur de ce qui est au centre de l'image, avec les motifs éventuels.",
        "limite": "L'éclairage peut fausser la couleur. Sans le moteur, IRIS donne une estimation locale du centre de l'image seulement.",
        "local": True,
        "phrases": ["C'est quelle couleur ?"],
    },
    "billets": {
        "nom": "C'est quel billet ?",
        "description": "Reconnaît les billets canadiens (5 $ à 100 $) et les pièces (5 ¢ à 2 $), puis donne le total et le niveau de certitude.",
        "limite": "Un billet plié, caché ou mal éclairé peut être mal lu : vérifiez un montant important. Exige le moteur VELA.",
        "local": False,
        "phrases": ["C'est quel billet ?", "Combien d'argent ?"],
    },
    "personnes": {
        "nom": "Qui est devant moi ?",
        "description": "Décrit les personnes visibles : nombre, position, expression, vêtements, gestes.",
        "limite": "IRIS ne reconnaît personne et ne présume ni l'âge, ni l'origine, ni l'état de santé. Exige le moteur VELA.",
        "local": False,
        "phrases": ["Qui est devant moi ?"],
    },
    "affichage": {
        "nom": "C'est quel bus ?",
        "description": "Lit un affichage utile pour se déplacer ou utiliser un appareil : numéro de bus, panneau, écran d'attente, afficheur.",
        "limite": "Un affichage lointain ou lumineux peut être illisible ; IRIS le dit plutôt que de deviner. Sans le moteur : texte brut seulement.",
        "local": True,
        "phrases": ["C'est quel bus ?", "Lis le panneau"],
    },
    "ecran": {
        "nom": "Décris l'écran",
        "description": "Décrit l'écran de l'ordinateur : application ouverte, zones principales, messages d'erreur.",
        "limite": "Sans le moteur, IRIS lit seulement le texte affiché, sans décrire la mise en page.",
        "local": True,
        "phrases": ["Décris l'écran"],
    },
}

AUCUN_TEXTE = "Je ne vois aucun texte lisible."
DESCRIPTION_RATEE = "Je n'ai pas réussi à décrire l'image."
MOTEUR_EN_PANNE = "Le moteur VELA n'a pas pu décrire l'image. Réessaie dans un instant."
LOCAL_SEULEMENT = (
    "Le mode 100 % local est actif : ce mode de description a besoin du moteur VELA, et aucune IA "
    "locale capable de lire les images n'est configurée."
)
CONFIDENTIEL = "Le mode confidentiel est actif : IRIS ne prend aucune photo ni capture d'écran tant qu'il l'est."
OCR_ABSENT = " La lecture locale du texte n'est pas disponible non plus sur cet ordinateur."
TAILLE_MAX_BASE64 = 20_000_000  # ≈ 15 Mo d'image


class RefusVision(HTTPException):
    """Refus documenté du service : un HTTPException (les routes le laissent remonter tel quel) qui
    porte aussi `message`, la phrase complète, et `phrase`, sa version courte à dire à voix haute."""

    def __init__(self, statut: int, message: str, detail: Any = None, phrase: str | None = None):
        super().__init__(status_code=statut, detail=detail if detail is not None else message)
        self.message = message
        self.phrase = phrase or message


# --------------------------------------------------------------------------- consignes au moteur
_SOURCES_TEXTE = {
    "lunettes": "L'image vient de la caméra des lunettes portées par l'utilisateur : ce qui est au centre est ce qu'il regarde.",
    "ecran": "L'image est une capture de l'écran de l'ordinateur de l'utilisateur.",
    "image": "L'image est une photo fournie par l'utilisateur, souvent prise avec son téléphone.",
}

_LONGUEURS = {
    "concis": "Longueur : une ou deux phrases courtes, l'essentiel d'abord.",
    "normal": "Longueur : trois à cinq phrases, l'essentiel d'abord, puis les détails utiles.",
    "descriptif": (
        "Longueur : description riche et complète, de l'ensemble vers les détails, sans limite stricte ; "
        "l'utilisateur a demandé des descriptions détaillées."
    ),
}

CONSIGNE_COMMUNE = (
    "Tu es IRIS, l'assistante de VELA. Tu décris une image pour une personne aveugle ou malvoyante qui ne "
    "peut pas vérifier ce que tu dis : l'exactitude passe avant tout. Règles : décris seulement ce qui est "
    "visible sur l'image, n'invente rien ; si tu n'es pas sûre de quelque chose, dis « je ne suis pas sûre » ; "
    "si l'image est floue, sombre, coupée ou mal cadrée, dis-le en premier et explique comment reprendre la "
    "photo (plus près, plus de lumière, ne pas bouger). Ordre spatial : de gauche à droite, puis du plus proche "
    "au plus loin, avec des repères simples (à gauche, au centre, à droite, devant, au fond). Les textes "
    "visibles sont cités mot pour mot. Les prix et montants sont donnés exactement tels qu'affichés, avec la "
    "devise. Ne présente jamais ta description comme une garantie de sécurité : c'est une photo, pas une "
    "surveillance en direct. Réponds en français canadien, en phrases parlées, sans markdown, sans liste à "
    "puces ni titre : ta réponse sera lue à voix haute. Ne révèle jamais quel modèle ou quelle entreprise te "
    "fait fonctionner : tu es IRIS, de VELA."
)

CONSIGNES_MODES: dict[str, str] = {
    "scene": (
        "Tâche : dire ce qu'il y a devant l'utilisateur. Commence par une phrase qui situe le lieu (intérieur ou "
        "extérieur, type de pièce ou de rue). Puis les éléments importants, de gauche à droite et du plus proche au "
        "plus loin. Mentionne en priorité ce qui compte pour se déplacer : marche, escalier, porte, objet au sol, "
        "véhicule, bord de trottoir. Cite mot pour mot les panneaux et enseignes importants. Pour les personnes : "
        "nombre et position seulement, sans jamais les identifier."
    ),
    "lecture": (
        "Tâche : lire le texte visible, mot pour mot. Lis tout le texte dans l'ordre naturel de lecture (titres, "
        "puis corps ; colonne par colonne ; de haut en bas). Ne résume pas, ne reformule pas, ne traduis pas, "
        "n'ajoute aucun commentaire avant ou après. Un mot illisible s'écrit [illisible]. La consigne de longueur "
        "ne s'applique pas : lis tout. S'il n'y a aucun texte lisible, réponds exactement : " + AUCUN_TEXTE
    ),
    "objet": (
        "Tâche : identifier l'objet que l'utilisateur tient ou montre, au centre de l'image. Dis ce que c'est ; "
        "pour un produit : la marque, le nom du produit, le format ou la quantité (par exemple 500 ml) et le prix "
        "s'il est affiché, exactement. Si un code-barres est visible et que ses chiffres sont lisibles, lis les "
        "chiffres ; ne les devine jamais. Mentionne les dates de péremption et les avertissements visibles "
        "(allergènes, « ne pas avaler »). Si tu n'es pas sûre de l'objet, dis ce qui est certain (forme, couleur, "
        "texte) et dis que tu n'es pas sûre."
    ),
    "couleur": (
        "Tâche : dire la couleur de l'objet ou du vêtement au centre de l'image. Donne un nom de couleur courant "
        "(bleu marine, rouge vif, beige…), puis les motifs (rayures, carreaux, fleurs) et les couleurs secondaires "
        "s'il y en a. Signale si l'éclairage (lumière jaune, ombre, contre-jour) rend la couleur incertaine."
    ),
    "billets": (
        "Tâche : identifier l'argent visible. Billets canadiens : 5 $ (bleu), 10 $ (violet), 20 $ (vert), 50 $ "
        "(rouge), 100 $ (brun) ; vérifie le chiffre imprimé, la couleur seule ne suffit pas. Pièces canadiennes : "
        "5 ¢, 10 ¢, 25 ¢, 1 $ (le huard, dorée) et 2 $ (bimétallique, centre doré et anneau argenté). Dis combien "
        "de billets et de pièces de chaque valeur tu vois, puis le total exact en dollars. Termine par ton niveau "
        "de certitude : « certaine », « presque certaine » ou « pas sûre », et dis ce qui est caché, plié ou coupé. "
        "Une autre devise, ou une pièce hors de cette liste : dis-le. Ne compte jamais ce que tu ne vois pas "
        "clairement."
    ),
    "personnes": (
        "Tâche : décrire les personnes visibles, sans jamais les identifier. Dis combien il y en a, où elles sont "
        "(à gauche, au centre, à droite, près, loin), si elles regardent vers l'utilisateur, leur expression "
        "apparente (souriante, neutre), leurs vêtements et ce qu'elles font (gestes, main tendue, assises, "
        "debout). INTERDIT : donner un nom ou deviner qui c'est, même si la personne semble connue ; estimer "
        "l'âge, l'origine, la religion, l'orientation, l'état de santé, un handicap ou le poids ; présumer le "
        "genre (dis « une personne »). Si on te demande qui c'est, réponds que tu ne reconnais pas les personnes "
        "et décris seulement ce qui est visible."
    ),
    "affichage": (
        "Tâche : lire un affichage utile pour se déplacer ou utiliser un appareil : numéro et destination d'un "
        "autobus ou d'un train, panneau de rue, enseigne, écran d'attente (numéro appelé), afficheur d'un appareil "
        "(four, thermostat, ascenseur, terminal de paiement). Donne d'abord l'information principale, mot pour mot "
        "et chiffres exacts (par exemple « Autobus 55, direction Centre-ville »), puis le reste du texte utile. Si "
        "le numéro ou la destination n'est pas lisible, dis-le clairement plutôt que de deviner."
    ),
    "ecran": (
        "Tâche : décrire l'écran de l'ordinateur. Dis quelle application ou quel site semble ouvert et le titre de "
        "la fenêtre, puis les zones principales de haut en bas (menus, contenu, boutons importants), et cite mot "
        "pour mot les messages d'erreur et les boîtes de dialogue. Résume les longs textes et propose de les lire "
        "en entier. Ne répète jamais un mot de passe ou un numéro de carte affiché : dis seulement qu'il y en a un."
    ),
}


def consigne_systeme(mode: str, source: str, verbosite: str) -> str:
    """Consigne complète envoyée au moteur pour un mode, une source et la verbosité choisie."""
    return "\n\n".join([
        CONSIGNE_COMMUNE,
        _SOURCES_TEXTE.get(source, _SOURCES_TEXTE["image"]),
        CONSIGNES_MODES[mode],
        _LONGUEURS.get(verbosite, _LONGUEURS["normal"]),
    ])


def message_utilisateur(mode: str, question: str | None, texte_ocr: str | None) -> str:
    morceaux: list[str] = []
    if mode == "lecture" and texte_ocr:
        morceaux.append(
            "Une lecture automatique faite sur l'appareil a donné le texte ci-dessous, dans un ordre qui peut être "
            "mélangé (colonnes, étiquettes). Remets-le dans l'ordre de lecture en te servant de l'image. Garde les "
            "mots lus ; corrige un mot seulement si l'image montre clairement une autre écriture. N'ajoute rien qui "
            "ne soit pas sur l'image.\n<<<\n" + texte_ocr + "\n>>>"
        )
    if question:
        morceaux.append(f"Question précise de l'utilisateur : « {question} ». Réponds d'abord à cette question.")
    if not morceaux:
        morceaux.append("Décris cette image selon la tâche.")
    return "\n\n".join(morceaux)


# --------------------------------------------------------------------------- traitements locaux
def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : la même forme que voice/listener.normalize."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", texte.lower()).strip()


def ouvrir_image(octets: bytes):
    """Ouvre l'image dans le bon sens (orientation EXIF des téléphones) en RVB. ValueError si illisible."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(octets))
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")
    except Exception as exc:
        raise ValueError(f"image illisible : {exc}") from exc


def preparer_image(octets: bytes, cote_max: int = 1568, qualite: int = 85) -> dict:
    """JPEG redimensionné, prêt pour le moteur (même limite que la capture d'écran existante)."""
    image = ouvrir_image(octets)
    if max(image.size) > cote_max:
        image.thumbnail((cote_max, cote_max))
    tampon = io.BytesIO()
    image.save(tampon, format="JPEG", quality=qualite, optimize=True)
    return {"type": "image", "media_type": "image/jpeg", "data": base64.b64encode(tampon.getvalue()).decode("ascii")}


_VERROU_OCR = threading.Lock()


def ocr_disponible() -> bool:
    return bool(actions.ocr_available())


def _moteur_ocr():
    # Le moteur RapidOCR de la lecture d'écran est réutilisé : le charger deux fois coûterait la
    # mémoire de deux modèles pour rien.
    if actions._ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        actions._ocr_engine = RapidOCR()
    return actions._ocr_engine


def _ocr_items(octets: bytes, largeur_max: int = 1600) -> list[dict]:
    """Fragments de texte lus localement sur une image, au format de pc.actions.ocr_screen."""
    import numpy as np

    image = ouvrir_image(octets)
    ratio = 1.0
    if image.width > largeur_max:
        ratio = image.width / largeur_max
        image = image.resize((largeur_max, int(image.height / ratio)))
    with _VERROU_OCR:
        resultat, _ = _moteur_ocr()(np.array(image))
    items = []
    for boite, texte, score in resultat or []:
        xs = [p[0] * ratio for p in boite]
        ys = [p[1] * ratio for p in boite]
        items.append({
            "text": texte, "confidence": round(float(score), 2),
            "left": int(min(xs)), "top": int(min(ys)), "right": int(max(xs)), "bottom": int(max(ys)),
            "x": int((min(xs) + max(xs)) / 2), "y": int((min(ys) + max(ys)) / 2),
        })
    return items


def lire_texte_image(octets: bytes) -> str:
    """Texte VERBATIM de l'image, dans l'ordre de lecture (même règle que la lecture d'écran)."""
    return actions.order_ocr_lines(_ocr_items(octets))


def lecture_fidele(texte_ocr: str, sortie: str) -> bool:
    """La remise en ordre du moteur garde-t-elle les mots lus ? Sinon c'est un résumé ou une invention.

    Seuils volontairement tolérants (le moteur corrige des fautes d'OCR, recolle des mots coupés),
    mais un texte qui perd près de la moitié des mots, ou qui en ajoute beaucoup, n'est plus une lecture."""
    mots_ocr = [m for m in normaliser(texte_ocr).split() if len(m) > 1]
    if len(mots_ocr) < 4:
        return True
    mots_sortie = [m for m in normaliser(sortie).split() if len(m) > 1]
    presents = set(mots_sortie)
    couverture = sum(1 for m in mots_ocr if m in presents) / len(mots_ocr)
    rapport = len(mots_sortie) / len(mots_ocr)
    return couverture >= 0.6 and 0.5 <= rapport <= 1.8


def _nom_teinte(degres: float) -> str:
    if degres < 15 or degres >= 340:
        return "rouge"
    if degres < 40:
        return "orange"
    if degres < 70:
        return "jaune"
    if degres < 160:
        return "vert"
    if degres < 195:
        return "turquoise"
    if degres < 255:
        return "bleu"
    if degres < 290:
        return "violet"
    return "rose"


def couleur_dominante(octets: bytes) -> str:
    """Nom de la couleur dominante au centre de l'image, calculé localement (aucun modèle).

    Estimation grossière et assumée : elle ne sait pas distinguer l'objet du fond, et l'éclairage la
    fausse. Elle sert quand le moteur n'est pas permis, et la phrase rendue le dit."""
    import numpy as np

    image = ouvrir_image(octets)
    largeur, hauteur = image.size
    centre = image.crop((int(largeur * 0.3), int(hauteur * 0.3), max(int(largeur * 0.7), 1), max(int(hauteur * 0.7), 1)))
    hsv = np.asarray(centre.resize((48, 48)).convert("HSV"), dtype=np.float32).reshape(-1, 3)
    teinte = hsv[:, 0] * 360.0 / 255.0
    saturation = hsv[:, 1]
    valeur = hsv[:, 2]
    colores = (saturation >= 60) & (valeur >= 60)
    if colores.mean() < 0.35:
        v = float(np.median(valeur))
        if v < 50:
            return "noir"
        if v > 205:
            return "blanc"
        if v > 150:
            return "gris clair"
        if v > 90:
            return "gris"
        return "gris foncé"
    noms = np.array([_nom_teinte(float(d)) for d in teinte[colores]])
    s_col = saturation[colores]
    v_col = valeur[colores]
    valeurs, comptes = np.unique(noms, return_counts=True)
    nom = str(valeurs[int(np.argmax(comptes))])
    part = float(comptes.max()) / float(len(noms))
    choisis = noms == nom
    v_nom = float(np.median(v_col[choisis]))
    s_nom = float(np.median(s_col[choisis]))
    if nom in ("rouge", "orange", "jaune") and v_nom < 140:
        nom = "brun"
    elif nom in ("orange", "jaune") and s_nom < 110 and v_nom > 170:
        nom = "beige"
    elif nom == "rouge" and s_nom < 130 and v_nom > 180:
        nom = "rose"
    if nom not in ("brun", "beige"):
        if v_nom < 110:
            nom += " foncé"
        elif v_nom > 215 and s_nom < 140:
            nom += " clair"
    if part < 0.6:
        return f"surtout {nom}, avec d'autres couleurs"
    return nom


# --------------------------------------------------------------------------- phrases vocales
# Formes normalisées (sans accents ni ponctuation). Un motif qui finit par « $ » doit terminer la
# phrase : « combien d'argent » seul est une demande de billets, « combien d'argent faut-il pour… »
# ne l'est pas. L'ordre compte : le premier groupe reconnu gagne.
_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ecran", (
        "decris l ecran", "decris moi l ecran", "decris mon ecran", "decris moi mon ecran", "decrire l ecran",
        "qu est ce qu il y a a l ecran", "qu est ce qu il y a sur l ecran", "qu est ce qu il y a sur mon ecran",
        "qu y a t il a l ecran",
    )),
    ("ou-est", (
        "ou j ai pose", "ou ai je pose", "ou est ce que j ai pose", "ou j ai mis", "ou ai je mis",
        "ou est ce que j ai mis", "ou j ai laisse", "ou ai je laisse", "ou est ce que j ai laisse",
        "ou j ai range", "ou ai je range", "ou est ce que j ai range",
    )),
    ("ou-est-generique", (
        "ou est mon", "ou est ma", "ou sont mes", "ou est passe mon", "ou est passee ma", "ou sont passes mes",
        "ou sont passees mes", "as tu vu mes", "as tu vu mon", "as tu vu ma", "t as vu mes",
    )),
    ("billets", (
        "c est quel billet", "quel billet", "quels billets", "c est quelle piece", "quelle piece",
        "c est combien d argent", "combien d argent$", "combien d argent j ai$", "combien d argent j ai dans la main",
        "combien d argent je tiens", "combien d argent il y a la", "combien ca fait d argent",
        "compte mon argent", "compte cet argent", "compte ces billets", "compte les billets", "compte la monnaie",
    )),
    ("couleur", (
        "c est quelle couleur", "quelle couleur c est", "c est de quelle couleur", "de quelle couleur est ce",
        "de quelle couleur est cette", "de quelle couleur est ca", "de quelle couleur est mon",
        "de quelle couleur est ma", "de quelle couleur sont mes", "de quelle couleur sont ces",
        "quelle couleur est ce", "quelle couleur est cette", "c est quoi la couleur", "quelle est cette couleur",
    )),
    ("personnes", (
        "qui est devant moi", "il y a qui devant moi", "y a t il quelqu un devant moi",
        "il y a quelqu un devant moi", "est ce qu il y a quelqu un devant moi", "y a quelqu un devant moi",
        "combien de personnes devant moi", "combien de personnes il y a devant moi",
        "combien de personnes autour de moi", "decris les personnes", "decris moi les personnes",
        "decris la personne", "decris moi la personne", "decris les gens", "qui est la$",
    )),
    ("affichage", (
        "c est quel bus", "c est quel autobus", "quel bus$", "quel autobus$", "quel bus arrive",
        "quel autobus arrive", "quel bus est la", "quel est ce bus", "quel est cet autobus",
        "numero du bus", "numero de l autobus", "lis le panneau", "lis moi le panneau", "que dit le panneau",
        "qu est ce que dit le panneau", "qu est ce qui est ecrit sur le panneau", "lis l affiche",
        "lis moi l affiche", "lis l affichage", "lis moi l affichage", "lis l enseigne", "lis moi l enseigne",
        "quel numero est appele", "c est quel numero$",
    )),
    ("objet", (
        "c est quoi cet objet", "c est quoi ce produit", "qu est ce que c est que cet objet", "quel est cet objet",
        "quel est ce produit", "c est quel produit", "qu est ce que je tiens", "qu est ce que j ai dans la main",
        "c est quelle marque", "lis le code barre", "lis moi le code barre", "c est quoi ce truc",
    )),
    ("lecture", (
        "lis moi ca", "lis ca$", "lis moi ceci", "lis ceci", "lis ce texte", "lis moi ce texte", "lis moi le texte",
        "lis ce document", "lis moi ce document", "lis cette lettre", "lis moi cette lettre", "lis l etiquette",
        "lis moi l etiquette", "lis le menu", "lis moi le menu", "lis cette feuille", "lis moi cette feuille",
    )),
    ("scene", (
        "qu est ce qu il y a devant moi", "qu y a t il devant moi", "qu est ce qui est devant moi",
        "il y a quoi devant moi", "decris ce que je vois", "decris moi ce que je vois",
        "decris ce qu il y a devant moi", "decris moi ce qu il y a devant moi", "decris la scene",
        "decris moi la scene", "qu est ce que je regarde", "je regarde quoi", "decris ce que je regarde",
        "decris moi ce que je regarde", "decris l endroit", "decris la piece", "decris ce qu il y a autour de moi",
        "qu est ce qu il y a autour de moi",
    )),
)


def _correspond(texte_norm: str, motif: str) -> bool:
    if motif.endswith("$"):
        motif = motif[:-1]
        return texte_norm == motif or texte_norm.endswith(" " + motif)
    return f" {motif} " in f" {texte_norm} "


def reconnaitre_demande(texte: str) -> tuple[str, str] | None:
    """(mode, source) pour une phrase de vision, ou None très vite si la phrase ne nous concerne pas.
    Le mode vaut aussi « ou-est » ou « ou-est-generique » pour la recherche d'objet."""
    t = normaliser(texte)
    if not t:
        return None
    for mode, motifs in _PHRASES:
        if any(_correspond(t, m) for m in motifs):
            ecran = " ecran" in f" {t}"
            if mode in ("ecran",):
                return "ecran", "ecran"
            if mode == "scene" and ecran:
                return "ecran", "ecran"
            if mode in ("lecture", "affichage") and ecran:
                return mode, "ecran"
            return mode, "lunettes"
    return None


# --------------------------------------------------------------------------- où ai-je posé…
_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
         "novembre", "décembre")
_DETERMINANTS = {"mon", "ma", "mes", "le", "la", "les", "l", "un", "une", "des", "du", "de", "ton", "ta", "tes",
                 "son", "sa", "ses", "notre", "nos", "votre", "vos", "cet", "cette", "ces", "ce"}
_MOTS_QUESTION = {"où", "ou", "j'ai", "ai-je", "est-ce", "que", "qu'est-ce", "est", "sont", "posé", "posée",
                  "posés", "mis", "mise", "laissé", "laissée", "rangé", "rangée", "passé", "passée", "passés",
                  "as-tu", "vu", "t'as", "iris", "dis-moi", "je", "ai", "tu", "as"}
_EXTRACTION = re.compile(
    r"(?:o[uù])\s+(?:est[- ]ce\s+que\s+)?(?:j['’ ]\s*ai|ai[- ]je)\s+(?:pos[ée]e?s?|mise?s?|laiss[ée]e?s?|rang[ée]e?s?)\s+(?P<a>.+)"
    r"|o[uù]\s+(?:est|sont)\s+(?:pass[ée]e?s?\s+)?(?P<b>.+)"
    r"|(?:as[- ]tu|t['’ ]\s*as)\s+vu\s+(?P<c>.+)",
    re.IGNORECASE,
)


def extraire_objet(question: str) -> str:
    """« Où j'ai posé mes clés ? » -> « mes clés ». Sans forme reconnue, la question entière."""
    q = " ".join((question or "").split()).strip()
    m = _EXTRACTION.search(q)
    objet = next((g for g in (m.group("a"), m.group("b"), m.group("c")) if g), "") if m else ""
    objet = re.sub(r"[?!.,;]+$", "", objet or q).strip()
    return objet or q


_MOT = re.compile(r"[\wàâäéèêëïîôöùûüÿç'-]{2,}", re.IGNORECASE)


def mots_recherche(objet: str) -> list[str]:
    """Les mots utiles d'un objet, dans l'ordre, avec leur singulier (« clés » -> « clés », « clé »)."""
    mots = [m.lower() for m in _MOT.findall(objet or "")]
    mots = [m for m in mots if m not in _DETERMINANTS and m not in _MOTS_QUESTION and m in tokenize(m)]
    variantes: list[str] = []
    for mot in mots:
        variantes.append(mot)
        if len(mot) > 3 and mot[-1] in "sx":
            variantes.append(mot[:-1])
    return list(dict.fromkeys(variantes))


def date_parlee(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local = moment.astimezone()
        return f"du {local.day} {_MOIS[local.month - 1]} à {local.hour} h {local.minute:02d}"
    except Exception:
        return ""


_PREFIXE_SOUVENIR = re.compile(r"^\[(?:Photo|Écran)\s+\d{1,2}:\d{2}\]\s*")


# --------------------------------------------------------------------------- service
class ServiceAccessibilite:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        # Fabrique de caméra remplaçable (tests, futur pilote) : la vraie caméra réutilise la
        # connexion basse énergie des lunettes.
        self.fabrique_camera: Callable[[], Any] = lambda: CameraLunettes(ctx.glasses)
        self._verrou_camera = asyncio.Lock()

    # ------------------------------------------------------------------ description
    def modes(self) -> list[dict]:
        return [
            {"id": ident, "nom": m["nom"], "description": m["description"], "local": bool(m["local"]),
             "limite": m["limite"], "phrases": list(m["phrases"])}
            for ident, m in MODES.items()
        ]

    def moteur_utilisable(self) -> bool:
        """Un moteur est-il choisissable pour une image, consentement mis à part ?"""
        try:
            self.ctx.chat.agent_pour_vision()
            return True
        except Exception:
            return False

    def modes_possibles(self) -> list[str]:
        """Les modes réellement utilisables maintenant (sert à ne pas offrir au modèle une porte fermée)."""
        if self.moteur_utilisable():
            return list(MODES)
        return [m for m, d in MODES.items() if d["local"]]

    def _refus_consentement(self, data_type: str) -> RefusVision:
        libelle = DATA_TYPES.get(data_type, {}).get("label", data_type)
        message = (
            f"Pour ce mode, IRIS doit envoyer des données au moteur VELA. Autorisez « {libelle} » dans "
            "Confidentialité, puis réessayez."
        )
        return RefusVision(
            403, message,
            detail={"code": "consentement", "data_type": data_type, "label": libelle, "message": message},
            phrase=f"Je ne peux pas le faire sans ton accord : autorise « {libelle} » dans Confidentialité.",
        )

    def _verifier_moteur(self, types: tuple[str, ...]) -> None:
        """Lève RefusVision si le moteur ne peut pas recevoir ces données maintenant."""
        chat = self.ctx.chat
        try:
            agent, _local = chat.agent_pour_vision()
            for type_donnee in types:
                self.ctx.consent.check(type_donnee, agent=agent)
        except ConsentRequired as exc:
            raise self._refus_consentement(exc.data_type)
        except LocalOnlyMode:
            raise RefusVision(409, LOCAL_SEULEMENT)
        except NoAgentAvailable as exc:
            if self.ctx.settings.user.local_only:
                raise RefusVision(409, LOCAL_SEULEMENT)
            raise RefusVision(409, str(exc) or "Aucune IA n'est prête pour décrire l'image.")

    async def _dire(self, texte: str) -> None:
        tts = getattr(self.ctx, "tts", None)
        if tts is None or not texte:
            return
        try:
            await asyncio.to_thread(tts.speak, texte, True)
        except Exception as exc:  # pragma: no cover - la voix ne doit jamais faire échouer une description
            log.debug("lecture à voix haute impossible : %s", exc)

    def _camera_utilisee_ailleurs(self) -> bool:
        """Le partage de vision en direct peut garder la caméra des lunettes : ne pas éteindre son témoin."""
        partage = getattr(self.ctx, "partage", None)
        if partage is None:
            return False
        try:
            etat = partage.etat() if callable(getattr(partage, "etat", None)) else {
                "actif": getattr(partage, "actif", False), "source": getattr(partage, "source", None)}
            return bool(etat.get("actif")) and etat.get("source") == "lunettes"
        except Exception:
            return False

    async def _photo_lunettes(self) -> tuple[bytes, str]:
        if self._verrou_camera.locked():
            raise RefusVision(409, "Une photo des lunettes est déjà en cours. Attends qu'elle se termine.")
        async with self._verrou_camera:
            camera = self.fabrique_camera()
            lunettes = getattr(camera, "glasses", None)
            if lunettes is not None and not getattr(lunettes, "connected", False):
                raise RefusVision(409, "Les lunettes ne sont pas connectées.",
                                  phrase="Les lunettes ne sont pas connectées : je ne peux pas prendre de photo.")
            # « Photo. » prévient les personnes autour. On ne l'annonce pas quand on sait déjà que le
            # module refusera d'écrire la commande (protocole non confirmé) : ce serait annoncer une
            # photo qui n'aura pas lieu.
            garde = getattr(camera, "_exploration_autorisee", None)
            refus_connu = callable(garde) and not garde()
            if self.ctx.settings.user.annonce_capture and not refus_connu:
                await self._dire("Photo.")
            deja_allumee = bool(self.ctx.capture.snapshot().get("camera"))
            self.ctx.capture.set(camera=True)
            try:
                resultat = await camera.prendre_photo(reconnaissance=False)
            except ProtocoleNonConfirme as exc:
                raise RefusVision(409, str(exc), phrase=(
                    "La caméra des lunettes n'est pas encore activée sur cet appareil : son protocole n'est pas "
                    "confirmé, alors je ne prends pas de photo."))
            except CameraIndisponible as exc:
                court = str(exc) if len(str(exc)) < 90 else "Ces lunettes n'ont pas de caméra utilisable : je ne peux pas prendre de photo."
                raise RefusVision(409, str(exc), phrase=court)
            except RefusVision:
                raise
            except Exception:
                log.exception("échec de la photo des lunettes pour une description")
                raise RefusVision(500, "La prise de photo a échoué.")
            finally:
                if not deja_allumee and not self._camera_utilisee_ailleurs():
                    self.ctx.capture.set(camera=False)
        if not getattr(resultat, "ok", False) or not getattr(resultat, "chemin", None):
            raise RefusVision(409, getattr(resultat, "constat", "") or "Aucune image n'est revenue des lunettes.",
                              phrase="Aucune image n'est revenue des lunettes.")
        octets = await asyncio.to_thread(Path(resultat.chemin).read_bytes)
        self.ctx.consent.log("lunettes_photo", detail=resultat.chemin)
        return octets, str(resultat.chemin)

    async def _capture_ecran(self) -> bytes:
        try:
            capture = await asyncio.to_thread(actions.take_screenshot, 1568, 85)
        except Exception:
            log.exception("échec de la capture d'écran pour une description")
            raise RefusVision(500, "La capture de l'écran a échoué.")
        self.ctx.capture.pulse_screen()
        return base64.b64decode(capture["data"])

    @staticmethod
    def _decoder_image(image: Any) -> bytes:
        if hasattr(image, "model_dump"):
            image = image.model_dump()
        if not isinstance(image, dict) or not image.get("data"):
            raise RefusVision(422, "Image manquante : la source « image » exige une image (media_type et data en base64).")
        donnees = "".join(str(image["data"]).split())
        if donnees.startswith("data:") and "," in donnees:
            donnees = donnees.split(",", 1)[1]
        if len(donnees) > TAILLE_MAX_BASE64:
            raise RefusVision(422, "Image trop lourde : 15 Mo au plus.")
        try:
            return base64.b64decode(donnees, validate=True)
        except (binascii.Error, ValueError):
            raise RefusVision(422, "Image illisible : le contenu n'est pas du base64 valide.")

    async def _ocr(self, octets: bytes) -> str | None:
        """Texte lu localement, "" s'il n'y en a pas, None si la lecture locale est indisponible."""
        try:
            if not await asyncio.to_thread(ocr_disponible):
                return None
            return (await asyncio.to_thread(lire_texte_image, octets)).strip()
        except Exception as exc:
            log.warning("lecture locale du texte impossible : %s", exc)
            return None

    async def _moteur(self, mode: str, source: str, octets: bytes, question: str | None,
                      types: tuple[str, ...], texte_ocr: str | None) -> dict:
        try:
            image = await asyncio.to_thread(preparer_image, octets)
        except ValueError:
            raise RefusVision(422, "Image illisible : format non reconnu.")
        systeme = consigne_systeme(mode, source, self.ctx.settings.user.verbosite)
        message = message_utilisateur(mode, question, texte_ocr)
        try:
            return await self.ctx.chat.demander_image_detail(systeme, message, [image], consentement=types)
        except ConsentRequired as exc:
            raise self._refus_consentement(exc.data_type)
        except LocalOnlyMode:
            raise RefusVision(409, LOCAL_SEULEMENT)
        except NoAgentAvailable as exc:
            raise RefusVision(409, str(exc) or LOCAL_SEULEMENT)
        except ConnectorError as exc:
            # Le détail peut nommer le fournisseur : il reste au journal, jamais dans la réponse.
            log.warning("moteur de vision en erreur (%s) : %s", mode, exc)
            raise RefusVision(502, MOTEUR_EN_PANNE)

    async def _analyser(self, mode: str, source: str, octets: bytes, question: str | None,
                        types: tuple[str, ...], refus: RefusVision | None) -> tuple[str, bool, bool]:
        """(texte, local, utile). `utile` = le résultat mérite d'être retenu."""
        def sans_moteur(refus_base: RefusVision | None) -> RefusVision:
            base = refus_base or RefusVision(409, LOCAL_SEULEMENT)
            detail = base.detail
            if isinstance(detail, dict):
                detail = {**detail, "message": base.message + OCR_ABSENT}
            return RefusVision(base.status_code, base.message + OCR_ABSENT,
                               detail=detail if isinstance(detail, dict) else None, phrase=base.phrase)

        if mode == "couleur":
            if refus is None:
                try:
                    r = await self._moteur(mode, source, octets, question, types, None)
                    if r.get("texte"):
                        return r["texte"], bool(r.get("local")), True
                except RefusVision as exc:
                    if exc.status_code in (403, 409, 422):
                        raise
            try:
                nom = await asyncio.to_thread(couleur_dominante, octets)
            except ValueError:
                raise RefusVision(422, "Image illisible : format non reconnu.")
            return f"Estimation locale, au centre de l'image : {nom}. L'éclairage peut fausser cette couleur.", True, True

        if mode in ("lecture", "affichage", "ecran"):
            texte_ocr = await self._ocr(octets)
            if refus is None:
                try:
                    r = await self._moteur(mode, source, octets, question,
                                           types, texte_ocr if mode == "lecture" else None)
                except RefusVision as exc:
                    if exc.status_code != 502 or not texte_ocr:
                        raise
                    r = {"texte": "", "local": False}
                sortie = (r.get("texte") or "").strip()
                if sortie:
                    if mode == "lecture" and texte_ocr and not question and not lecture_fidele(texte_ocr, sortie):
                        log.info("remise en ordre du texte rejetée : trop éloignée de la lecture locale")
                        return texte_ocr, bool(r.get("local")), True
                    return sortie, bool(r.get("local")), sortie != AUCUN_TEXTE
                if texte_ocr is None:
                    return DESCRIPTION_RATEE, bool(r.get("local")), False
                local = bool(r.get("local"))
            else:
                if texte_ocr is None:
                    raise sans_moteur(refus)
                local = True
            if mode == "lecture":
                return (texte_ocr or AUCUN_TEXTE), local, bool(texte_ocr)
            if mode == "affichage":
                if not texte_ocr:
                    return "Je ne vois aucun texte lisible sur cet affichage.", local, False
                return "Lecture locale du texte visible, sans interprétation : " + texte_ocr, local, True
            if not texte_ocr:
                return "L'écran ne contient aucun texte lisible, et je ne peux pas décrire sa mise en page sans le moteur VELA.", local, False
            return ("Sans le moteur VELA, je ne peux pas décrire la mise en page de l'écran. Voici le texte qui y est "
                    "affiché : " + texte_ocr), local, True

        # scene, objet, billets, personnes : le moteur est indispensable (refus levé avant la capture).
        r = await self._moteur(mode, source, octets, question, types, None)
        sortie = (r.get("texte") or "").strip()
        return (sortie or DESCRIPTION_RATEE), bool(r.get("local")), bool(sortie)

    async def decrire(self, mode: str, source: str = "lunettes", image: Any = None, question: str | None = None,
                      parler: bool = True, memoriser: bool = True) -> dict:
        """Décrit ce que voit la source. Renvoie {ok, mode, source, texte, chemin, duree_ms, local, note}.
        Lève RefusVision (HTTPException) : 409 caméra/local/confidentiel, 403 consentement, 422, 500, 502."""
        debut = time.monotonic()
        mode = (mode or "").strip().lower()
        if mode not in MODES:
            raise RefusVision(422, f"Mode de description inconnu : « {mode} ». Modes : {', '.join(MODES)}.")
        source = (source or "lunettes").strip().lower()
        if source not in SOURCES:
            raise RefusVision(422, f"Source inconnue : « {source} ». Sources : {', '.join(SOURCES)}.")
        if mode == "ecran" and source == "lunettes":
            source = "ecran"  # « décris l'écran » vise l'écran de l'ordinateur, pas la caméra
        question = " ".join((question or "").split())[:500] or None
        u = self.ctx.settings.user
        if u.privacy_mode:
            raise RefusVision(409, CONFIDENTIEL)
        octets_fournis = self._decoder_image(image) if source == "image" else b""

        types = ("screen" if source == "ecran" else "image",) + (("transcript",) if question else ())
        refus: RefusVision | None = None
        try:
            self._verifier_moteur(types)
        except RefusVision as exc:
            # On refuse AVANT de photographier quand le mode n'a pas de chemin local : prendre une photo
            # pour rien, c'est capter une scène (et des passants) sans raison.
            if not MODES[mode]["local"]:
                raise
            refus = exc

        chemin: str | None = None
        if source == "lunettes":
            octets, chemin = await self._photo_lunettes()
        elif source == "ecran":
            octets = await self._capture_ecran()
        else:
            octets = octets_fournis

        try:
            texte, local, utile = await self._analyser(mode, source, octets, question, types, refus)
        except BaseException:
            await self._oublier_photo_si_suspendue(chemin)
            raise
        duree_ms = int((time.monotonic() - debut) * 1000)

        suspendue = self.ctx.memory.suspendue
        if chemin and suspendue:
            await self._oublier_photo_si_suspendue(chemin)
            chemin = None
        elif chemin:
            nom = Path(chemin).name
            octets_photo = len(octets)
            self.ctx.hub.publish("glasses.photo", chemin=chemin, octets=octets_photo)
            # « genre » et non « type » : EventHub.publish place le type d'événement sous la clé « type »,
            # qu'un champ du même nom écraserait (l'événement deviendrait « photo »).
            self.ctx.hub.publish("album.nouveau", nom=nom, genre="photo", octets=octets_photo)
        if memoriser and utile and not suspendue:
            await asyncio.to_thread(self._memoriser, texte, source, chemin)

        note = refus.message if refus is not None else None
        if suspendue and memoriser:
            note = ((note + " ") if note else "") + "Mémoire suspendue : cette description n'a pas été retenue."
        resultat = {"ok": True, "mode": mode, "source": source, "texte": texte, "chemin": chemin,
                    "duree_ms": duree_ms, "local": bool(local), "note": note}
        self.ctx.consent.log("vision_description", detail=f"{mode} / {source} / {'local' if local else 'moteur'}")
        self.ctx.hub.publish("vision.resultat", mode=mode, source=source, texte=texte, chemin=chemin,
                             duree_ms=duree_ms, local=bool(local))
        if parler:
            await self._dire(texte)
        return resultat

    async def _oublier_photo_si_suspendue(self, chemin: str | None) -> None:
        """Mode invité ou zone sans mémoire : la photo prise pour décrire n'est pas gardée."""
        if not chemin or not self.ctx.memory.suspendue:
            return
        try:
            await asyncio.to_thread(Path(chemin).unlink, True)
        except Exception as exc:  # pragma: no cover
            log.warning("photo non effacée malgré la mémoire suspendue : %s", exc)

    def _memoriser(self, texte: str, source: str, chemin: str | None) -> None:
        court = " ".join(texte.split())
        if len(court) > 300:
            court = court[:300].rsplit(" ", 1)[0] + "…"
        etiquette = "Écran" if source == "ecran" else "Photo"
        origine = Path(chemin).name if chemin else ("écran" if source == "ecran" else "image fournie")
        try:
            self.ctx.memory.add(f"[{etiquette} {datetime.now().strftime('%H:%M')}] {court}",
                                source="photo", kind="vision", source_text=origine)
            self.ctx.hub.publish("memory.updated", count=self.ctx.memory.count())
        except MemoireSuspendue:
            return
        except Exception as exc:
            log.warning("description non mémorisée : %s", exc)
        journal = getattr(self.ctx, "journal", None)
        if journal is not None:
            try:
                retour = journal.ajouter(texte, "photo")
                if inspect.isawaitable(retour):  # pragma: no cover - le journal est synchrone par contrat
                    retour.close()
            except Exception as exc:
                log.warning("description non ajoutée au journal : %s", exc)

    # ------------------------------------------------------------------ où ai-je posé…
    def _chercher_souvenirs(self, objet: str) -> list[dict]:
        mots = mots_recherche(objet)
        if not mots:
            return []
        trouves = self.ctx.memory.search(" ".join(mots), limit=20)
        trouves.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        trouves.sort(key=lambda s: 0 if s.get("source") == "photo" else 1)
        souvenirs = [{"id": s["id"], "texte": s["text"], "date": s["created_at"], "source": s.get("source")}
                     for s in trouves[:5]]
        journal = getattr(self.ctx, "journal", None)
        if journal is not None:
            try:
                retour = journal.chercher(" ".join(mots), limit=5)
                entrees = retour.get("entrees", []) if isinstance(retour, dict) else list(retour or [])
                deja = {normaliser(s["texte"])[:80] for s in souvenirs}
                for e in entrees:
                    texte = str(e.get("texte") or "")
                    if texte and normaliser(texte)[:80] not in deja:
                        souvenirs.append({"id": str(e.get("id", "")), "texte": texte, "date": str(e.get("ts", "")),
                                          "source": "journal"})
            except Exception as exc:
                log.warning("recherche dans le journal impossible : %s", exc)
        return souvenirs

    async def ou_est(self, question: str, parler: bool = False) -> dict:
        """Cherche dans les souvenirs réels où un objet a été vu ou posé. Ne répond jamais de mémoire de modèle."""
        question = " ".join((question or "").split())[:500]
        if not question:
            raise RefusVision(422, "Dis-moi quel objet chercher.")
        objet = extraire_objet(question)
        souvenirs = await asyncio.to_thread(self._chercher_souvenirs, objet)
        local = True
        if not souvenirs:
            mots = mots_recherche(objet)
            libelle = " ".join(mots[:1]) if mots else objet
            reponse = (f"Je n'ai aucun souvenir qui parle de « {libelle} ». Je ne retiens que ce que j'ai décrit "
                       "ou ce que tu m'as dit.")
        else:
            meilleur = souvenirs[0]
            quand = date_parlee(meilleur["date"])
            reponse = (f"Mon dernier souvenir à ce sujet date {quand} : " if quand else "Mon dernier souvenir à ce sujet : ") \
                + _PREFIXE_SOUVENIR.sub("", meilleur["texte"]).rstrip(". ") + ". L'objet a pu être déplacé depuis."
            systeme = (
                "Tu es IRIS, l'assistante de VELA. L'utilisateur cherche un objet. Réponds en une ou deux phrases "
                "parlées, en français canadien, sans markdown, en te fondant UNIQUEMENT sur les souvenirs datés "
                "fournis (le plus récent compte le plus). Dis la date et l'heure du souvenir utilisé. Si aucun "
                "souvenir ne répond vraiment à la question, dis que tu n'en as pas trace. N'invente jamais un lieu, "
                "et rappelle que l'objet a pu être déplacé depuis."
            )
            lignes = "\n".join(f"- {date_parlee(s['date']) or s['date']} : {s['texte']}" for s in souvenirs)
            message = f"Question : « {question} »\nSouvenirs :\n{lignes}"
            try:
                r = await self.ctx.chat.demander_image_detail(systeme, message, [],
                                                              consentement=("transcript", "memory"))
                if (r.get("texte") or "").strip():
                    reponse = r["texte"].strip()
                    local = bool(r.get("local"))
            except (ConsentRequired, LocalOnlyMode, NoAgentAvailable):
                pass  # sans accord, le meilleur souvenir tel quel : il est vrai, et il ne sort pas d'ici
            except Exception as exc:
                log.warning("formulation de « où est » impossible, souvenir brut rendu : %s", exc)
        if parler:
            await self._dire(reponse)
        return {"reponse": reponse,
                "souvenirs": [{"id": s["id"], "texte": s["texte"], "date": s["date"]} for s in souvenirs],
                "local": local}

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str):
        """Consultée par l'écoute pour chaque commande : None tout de suite si ce n'est pas pour nous,
        sinon une coroutine que l'écoute exécute dans la boucle du service."""
        reconnu = reconnaitre_demande(texte)
        if reconnu is None:
            return None
        return self._traiter_phrase(texte, *reconnu)

    async def _traiter_phrase(self, texte: str, mode: str, source: str) -> str | None:
        try:
            if mode in ("ou-est", "ou-est-generique"):
                if mode == "ou-est-generique":
                    souvenirs = await asyncio.to_thread(self._chercher_souvenirs, extraire_objet(texte))
                    if not any(s.get("source") in ("photo", "journal") for s in souvenirs):
                        return None  # « où est ma commande ? » : pas un objet vu, le modèle s'en charge
                r = await self.ou_est(texte, parler=False)
                return r["reponse"]
            r = await self.decrire(mode, source, parler=False, memoriser=True)
            return r["texte"]
        except RefusVision as exc:
            return exc.phrase
        except Exception:
            log.exception("description vocale en erreur")
            return DESCRIPTION_RATEE

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("vision", self.interception, priorite=40)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("vision")
