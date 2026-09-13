"""Pas à pas « mains occupées » : suivre une recette, un montage ou une réparation à la voix.

Pensé pour la personne qui a les mains dans la pâte, un tournevis dans une main et une pièce dans
l'autre, ou qui ne voit pas l'écran. Trois constats guident le module :

- Une étape = une action. Des étapes fournies sont lues telles quelles ; des étapes rédigées par le
  moteur VELA (consentement « Texte de vos demandes », jamais en mode 100 % local sans IA locale)
  sont validées (JSON, longueur, nombre) et annoncées comme rédigées automatiquement, avec la limite
  qui va avec le sujet (notice du fabricant, cuisson, professionnel pour le gaz ou l'électricité).
- Un minuteur ne s'invente pas. `minuteur_s` vient de la durée DITE dans la phrase de l'étape
  (« Faites cuire 10 minutes »), lue sur l'ordinateur ; une étape sans durée n'a pas de minuteur, sauf
  si l'utilisateur en dicte un (« lance un minuteur de 5 minutes »).
- Pas de fausse vérification. « Est-ce que c'est bon ? » décrit UNE photo des lunettes par la vision
  d'accessibilité : c'est un regard, pas une garantie de cuisson ni de sécurité, et la réponse le dit.

Limites dites telles quelles : chaque commande vocale passe par le mot d'activation, sauf pendant la
fenêtre de conversation qui suit une réponse d'IRIS ; les minuteurs tournent sur l'ordinateur (une mise
en veille retarde l'annonce) ; rien de la session n'est conservé.

Ce fichier porte aussi les petits outils de langue parlée partagés par les assistants (nombres dits en
toutes lettres, durées, correspondance stricte des commandes) : entrainement.py et prix.py les importent.

Service exposé sous ctx.pas_a_pas (voir routes_assistants.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

log = logging.getLogger("iris.pas_a_pas")

TYPES: dict[str, str] = {"recette": "Recette", "montage": "Montage", "reparation": "Réparation", "autre": "Pas à pas"}
ACTIONS = ("suivant", "precedent", "repeter", "minuteur", "annuler_minuteur", "verifier", "terminer")
ETAPES_MAX = 40
TEXTE_ETAPE_MAX = 300
SUJET_MAX = 160
MINUTEUR_MAX_S = 24 * 3600
MINUTEURS_MAX = 5  # au-delà, plus personne ne sait quel minuteur sonne pour quoi

CONFIDENTIEL = "Le mode confidentiel est actif : le pas à pas est arrêté et ne peut pas démarrer tant qu'il l'est."
AUCUNE_SESSION = "Aucun pas à pas n'est en cours."
LOCAL_SEULEMENT = (
    "Le mode 100 % local est actif et aucune IA locale n'est configurée : IRIS ne peut pas rédiger les étapes. "
    "Fournissez-les (une par ligne) : elles seront lues sans que rien ne quitte l'ordinateur."
)
MOTEUR_EN_PANNE = "Le moteur VELA n'a pas pu rédiger les étapes. Réessayez dans un instant, ou fournissez les étapes."
REPONSE_ILLISIBLE = (
    "Le moteur VELA n'a pas rendu d'étapes utilisables. Réessayez en précisant le sujet, ou fournissez les étapes."
)
VISION_ABSENTE = (
    "La vérification par la caméra n'est pas disponible sur cet ordinateur : la vision d'accessibilité n'est pas chargée."
)
ECOUTE_ARRETEE = "L'écoute vocale est arrêtée : les commandes à la voix ne seront pas entendues tant qu'elle ne tourne pas."
SANS_DUREE = "Cette étape ne donne pas de durée. Précisez-la, par exemple « lance un minuteur de 5 minutes »."

AVERTISSEMENTS: dict[str, str] = {
    "recette": (
        "Étapes rédigées automatiquement : vérifiez les quantités, les températures et les temps de cuisson. "
        "Pour la viande et la volaille, seul un thermomètre confirme la cuisson."
    ),
    "montage": "Étapes rédigées automatiquement, sans voir votre modèle : la notice du fabricant a priorité.",
    "reparation": (
        "Étapes rédigées automatiquement, sans voir votre appareil : coupez le courant ou l'eau avant d'intervenir, "
        "suivez la notice du fabricant, et faites appel à un professionnel pour le gaz, le panneau électrique ou "
        "tout travail dangereux."
    ),
    "autre": "Étapes rédigées automatiquement : vérifiez-les avant de les suivre.",
}

CONSIGNE_ETAPES = (
    "Tu es IRIS, l'assistante de VELA. Tu prépares des étapes qui seront lues à voix haute, une à la fois, à "
    "quelqu'un qui a les mains occupées. Réponds UNIQUEMENT par un objet JSON, sans texte autour ni bloc de code, "
    "de la forme {\"titre\": \"nom court du sujet\", \"type\": \"recette|montage|reparation|autre\", "
    "\"etapes\": [\"première étape\", \"deuxième étape\"]}. Règles : de 3 à 25 étapes ; une seule action par "
    "étape, en une phrase courte (moins de 25 mots), à l'impératif, en français canadien ; quantités, "
    "températures et durées exactes dans la phrase, les durées écrites en chiffres (« Faites cuire 10 minutes à "
    "feu moyen. ») ; n'invente pas ce que tu ne sais pas : si le sujet est vague, donne des étapes générales et "
    "dis-le dans la première étape. Pour une réparation ou un montage, commence par l'étape de sécurité utile "
    "(débrancher, couper le courant ou l'eau) ; pour le gaz, le panneau électrique ou un travail dangereux, la "
    "première étape recommande un professionnel qualifié. Ne révèle jamais quel modèle ou quelle entreprise te "
    "fait fonctionner : tu es IRIS, de VELA."
)


class RefusPasAPas(HTTPException):
    """Refus documenté : un HTTPException (les routes le laissent remonter) avec sa phrase courte à dire."""

    def __init__(self, statut: int, message: str, detail: Any = None, phrase: str | None = None):
        super().__init__(status_code=statut, detail=detail if detail is not None else message)
        self.message = message
        self.phrase = phrase or message


# =============================================================================== langue parlée (partagé)
def normaliser(texte: str) -> str:
    """Minuscules sans accents, ponctuation remplacée par des espaces : la forme de voice/listener.normalize."""
    # « œuf » n'a pas de décomposition Unicode : sans ce remplacement, il deviendrait « uf ».
    brut = (texte or "").replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    brut = unicodedata.normalize("NFKD", brut).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", brut.lower()).strip()


def jetons(texte: str) -> list[tuple[str, str]]:
    """Mots de la phrase, chacun sous sa forme d'origine ET normalisée : on repère une commande sur la forme
    normalisée, et on rend à l'utilisateur ses propres mots (accents compris) pour un sujet ou un exercice."""
    brut = (texte or "").replace("œ", "oe").replace("Œ", "Oe")
    return [(mot, normaliser(mot)) for mot in re.findall(r"[^\W_]+", brut) if normaliser(mot)]


# Mots sans contenu qu'une commande parlée traîne souvent avec elle. « bon » n'y est PAS : « est-ce que
# c'est bon » est une vraie demande.
_REMPLISSAGE = ("s il te plait", "s il vous plait", "stp", "svp", "iris", "ok", "okay", "d accord", "alors",
                "euh", "heu", "vas y", "merci", "hey", "dis moi")


def epurer(texte_norm: str) -> str:
    t = f" {texte_norm} "
    precedent = None
    while precedent != t:
        precedent = t
        for mot in _REMPLISSAGE:
            t = t.replace(f" {mot} ", " ")
    return " ".join(t.split())


def correspond(texte_norm: str, phrases: tuple[str, ...], marge: int = 2) -> bool:
    """La commande EST l'une des phrases (à quelques mots près). Stricte exprès : pendant une session, une
    question ordinaire (« quelle heure est-il ? ») doit continuer d'aller au modèle."""
    t = epurer(texte_norm)
    if not t:
        return False
    n = len(t.split())
    for p in phrases:
        if t == p or (f" {p} " in f" {t} " and n <= len(p.split()) + marge):
            return True
    return False


_NOMBRES: dict[str, int] = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "septante": 70,
    "huitante": 80, "octante": 80, "nonante": 90, "cent": 100, "cents": 100, "mille": 1000,
}
_UNITES: dict[str, int] = {
    "h": 3600, "hr": 3600, "hrs": 3600, "heure": 3600, "heures": 3600,
    "min": 60, "mins": 60, "mn": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "seconde": 1, "secondes": 1,
}


def jetons_nombres(texte: str) -> list[str]:
    """Jetons pour lire nombres et durées : « 1h30 » -> 1, h, 30 ; « 1,5 heure » garde 1,5."""
    brut = unicodedata.normalize("NFKD", (texte or "").lower()).encode("ascii", "ignore").decode()
    brut = re.sub(r"(\d)\s*[-–]\s*(?=\d)", r"\1 a ", brut)  # « 10-12 minutes » est une plage, pas deux nombres
    return re.findall(r"\d+(?:[.,]\d+)?|[a-z]+", brut)


def lire_nombre(t: list[str], i: int) -> tuple[float | None, int]:
    """(valeur, indice suivant) du nombre qui commence au jeton i : chiffres (« 12 ») ou lettres, comme la
    reconnaissance vocale locale les écrit (« quatre-vingt-dix », « vingt et un »). (None, i) sinon."""
    if i >= len(t):
        return None, i
    if t[i][0].isdigit():
        return float(t[i].replace(",", ".")), i + 1
    if t[i] not in _NOMBRES:
        return None, i
    total, courant, j = 0, 0, i
    while j < len(t):
        mot = t[j]
        if mot == "et" and j > i and j + 1 < len(t) and t[j + 1] in ("un", "une", "onze"):
            j += 1
            continue
        if mot not in _NOMBRES:
            break
        valeur = _NOMBRES[mot]
        if valeur == 1000:
            total += (courant or 1) * 1000
            courant = 0
        elif valeur == 100:
            courant = (courant or 1) * 100
        elif valeur == 20 and courant % 100 == 4:
            courant += 76  # « quatre-vingt » : 4 devient 80
        else:
            courant += valeur
        j += 1
    return float(total + courant), j


def _est_nombre(t: list[str], i: int) -> bool:
    return i < len(t) and lire_nombre(t, i)[0] is not None


def lire_duree(texte: str) -> int | None:
    """Première durée dite dans la phrase, en secondes, ou None.

    « 10 minutes », « 1 h 30 », « une heure et demie », « une demi-heure », « deux minutes trente »,
    « 90 secondes ». Pour une plage (« 10 à 12 minutes »), la borne BASSE : mieux vaut vérifier trop tôt
    que trop tard. Un nombre sans unité (« étape 3 », « 180 degrés ») n'est jamais une durée."""
    t = jetons_nombres(texte)
    total = 0.0
    unite_prec: int | None = None
    i = 0
    while i < len(t):
        n, j = lire_nombre(t, i)
        if n is None and t[i] in ("demi", "demie") and i + 1 < len(t) and t[i + 1] in _UNITES:
            n, j = 0.5, i + 1
        if n is None:
            if unite_prec is not None:
                break  # fin du premier groupe de durée
            i += 1
            continue
        # Plage : « 10 à 12 », « 10 ou 12 », « 10-12 » (le tiret est réécrit « à » par jetons_nombres).
        if j + 1 < len(t) and t[j] in ("a", "ou") and _est_nombre(t, j + 1):
            j = lire_nombre(t, j + 1)[1]
        if j < len(t) and t[j] in ("demi", "demie") and n == 1:
            n, j = 0.5, j + 1  # « une demi-heure »
        if j < len(t) and t[j] in _UNITES:
            unite = _UNITES[t[j]]
            if unite_prec is not None and unite >= unite_prec:
                break  # « 5 minutes … 3 minutes » : c'est une autre durée
            total += n * unite
            unite_prec = unite
            j += 1
            if j + 1 < len(t) and t[j] == "et" and t[j + 1] in ("demi", "demie"):
                total += unite / 2
                j += 2
            elif j + 1 < len(t) and t[j] == "et" and _est_nombre(t, j + 1):
                j += 1
            i = j
            continue
        if unite_prec is not None:
            if unite_prec > 1:
                total += n * (unite_prec // 60)  # « 1 h 30 » : trente minutes ; « 2 min 30 » : trente secondes
            break
        i = j  # un nombre sans unité n'est pas une durée
    if unite_prec is None or total <= 0:
        return None
    return int(round(total))


def duree_parlee(secondes: float) -> str:
    """« 1 heure 30 minutes », « 45 secondes » : ce que la voix dit, sans abréviation."""
    s = max(0, int(math.ceil(secondes - 1e-9)))
    heures, reste = divmod(s, 3600)
    minutes, sec = divmod(reste, 60)
    morceaux: list[str] = []
    if heures:
        morceaux.append(f"{heures} heure{'s' if heures > 1 else ''}")
    if minutes:
        morceaux.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if sec or not morceaux:
        morceaux.append(f"{sec} seconde{'s' if sec > 1 else ''}")
    return " ".join(morceaux)


def maintenant_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# =============================================================================== étapes
def nettoyer_texte(texte: Any, maximum: int) -> str:
    propre = " ".join(str(texte or "").split())
    propre = re.sub(r"^(?:[-*•·]+|\d{1,2}\s*[.):-])\s*", "", propre)  # puce ou numéro recopié
    return propre[:maximum].rstrip()


def construire_etapes(brutes: list[Any]) -> list[dict]:
    """Étapes publiques [{n, texte, minuteur_s}] depuis des chaînes (ou {texte}). Vides retirées, bornées."""
    etapes: list[dict] = []
    for brute in brutes or []:
        if isinstance(brute, dict):
            brute = brute.get("texte") or brute.get("text") or ""
        if not isinstance(brute, (str, int, float)):
            continue
        texte = nettoyer_texte(brute, TEXTE_ETAPE_MAX)
        if not texte:
            continue
        duree = lire_duree(texte)
        if duree is not None and not (1 <= duree <= MINUTEUR_MAX_S):
            duree = None
        etapes.append({"n": len(etapes) + 1, "texte": texte, "minuteur_s": duree})
        if len(etapes) >= ETAPES_MAX:
            break
    return etapes


def lire_reponse_moteur(brut: str) -> dict:
    """{titre, type, etapes: [str]} validé depuis la réponse du moteur. Lève ValueError si inutilisable."""
    texte = (brut or "").strip()
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte)
    debut = min([p for p in (texte.find("{"), texte.find("[")) if p >= 0], default=-1)
    if debut < 0:
        raise ValueError("aucun JSON")
    fin = max(texte.rfind("}"), texte.rfind("]"))
    donnees = json.loads(texte[debut:fin + 1])
    if isinstance(donnees, list):
        donnees = {"etapes": donnees}
    if not isinstance(donnees, dict) or not isinstance(donnees.get("etapes"), list):
        raise ValueError("champ etapes absent")
    etapes = construire_etapes(donnees["etapes"])
    if not etapes:
        raise ValueError("aucune étape")
    type_ = normaliser(str(donnees.get("type") or "")).replace(" ", "")
    return {
        "titre": nettoyer_texte(donnees.get("titre"), SUJET_MAX) or None,
        "type": type_ if type_ in TYPES else None,
        "etapes": etapes,
    }


# =============================================================================== phrases vocales
PHRASES_SUIVANT = ("suivant", "suivante", "etape suivante", "prochaine etape", "c est fait", "cest fait",
                   "la suite", "et apres", "on continue", "j ai fini l etape", "etape faite")
PHRASES_PRECEDENT = ("precedent", "precedente", "etape precedente", "reviens en arriere", "retourne en arriere",
                     "retour en arriere", "etape d avant", "l etape d avant", "reviens a l etape precedente")
PHRASES_REPETER = ("repete", "repeter", "repetes", "repete l etape", "tu peux repeter", "peux tu repeter",
                   "redis le", "redis", "relis l etape", "relis")
PHRASES_OU = ("on en est ou", "ou on en est", "ou en est on", "ou j en suis", "ou en suis je", "quelle etape",
              "c est quelle etape", "on est a quelle etape")
PHRASES_TERMINER = ("c est fini", "cest fini", "c est termine", "j ai termine", "termine le pas a pas",
                    "arrete le pas a pas", "fin du pas a pas", "on arrete le pas a pas", "quitte le pas a pas")
PHRASES_VERIFIER = ("est ce que c est bon", "c est bon comme ca", "est ce que ca a l air bon",
                    "est ce que c est correct", "est ce que c est bien fait", "est ce que c est cuit",
                    "verifie l etape", "regarde si c est bon", "est ce que ca va comme ca", "verifie")
MOTS_ANNULER = ("annule", "annuler", "arrete", "arreter", "stop", "coupe", "couper")
MARQUEURS_DEMARRAGE = ("pas a pas", "etape par etape")
VERBES_DEMARRAGE = ("guide", "aide", "montre", "explique", "demarre", "commence", "lance", "fais", "donne",
                    "recette", "comment", "pour", "accompagne")


def action_vocale(texte: str) -> tuple[str, int | None] | None:
    """(action, secondes dites) si la phrase est une commande de session, sinon None — tout de suite."""
    norme = normaliser(texte)
    if not norme:
        return None
    mots = norme.split()
    if ("minuteur" in mots or "minuteurs" in mots) and len(mots) <= 10:
        if any(m in mots for m in MOTS_ANNULER):
            return "annuler_minuteur", None
        if any(m in mots for m in ("reste", "restant", "restent", "combien", "ou")):
            return "ou", None  # une question sur le minuteur ne doit jamais en lancer un
        return "minuteur", lire_duree(texte)
    for action, phrases in (("terminer", PHRASES_TERMINER), ("verifier", PHRASES_VERIFIER),
                            ("suivant", PHRASES_SUIVANT), ("precedent", PHRASES_PRECEDENT),
                            ("repeter", PHRASES_REPETER), ("ou", PHRASES_OU)):
        if correspond(norme, phrases):
            return action, None
    return None


# =============================================================================== service
class ServicePasAPas:
    def __init__(self, ctx: Any, maintenant: Callable[[], float] | None = None,
                 dormir: Callable[[float], Awaitable[Any]] | None = None):
        self.ctx = ctx
        # Horloge et attente injectables : les tests font avancer le temps sans attendre dix minutes.
        self.maintenant: Callable[[], float] = maintenant or time.monotonic
        self.dormir: Callable[[float], Awaitable[Any]] = dormir or asyncio.sleep
        self._session: dict | None = None
        self._minuteurs: dict[int, dict] = {}  # n de l'étape -> {tache, fin, duree_s}

    # ------------------------------------------------------------------ utilitaires
    @property
    def actif(self) -> bool:
        return self._session is not None

    def _user(self) -> Any:
        return self.ctx.settings.user

    def _verbosite(self) -> str:
        return getattr(self._user(), "verbosite", "normal") or "normal"

    async def dire(self, texte: str) -> None:
        """Lecture à voix haute (file de la synthèse, non bloquante). Jamais en mode confidentiel."""
        tts = getattr(self.ctx, "tts", None)
        if tts is None or not texte or getattr(self._user(), "privacy_mode", False):
            return
        try:
            await asyncio.to_thread(tts.speak, texte, True)
        except Exception as exc:  # pragma: no cover - la voix ne doit jamais faire échouer une commande
            log.debug("lecture à voix haute impossible : %s", exc)

    def _ecoute_active(self) -> bool:
        voice = getattr(self.ctx, "voice", None)
        return bool(voice is not None and getattr(voice, "state", "off") != "off")

    def limite(self) -> str:
        u = self._user()
        fenetre = int(getattr(u, "voice_conversation_seconds", 0) or 0)
        mot = getattr(u, "wake_word", "") or "Dis-moi Iris"
        voix = (f"Chaque commande vocale commence par « {mot} », sauf dans les {fenetre} secondes qui suivent une "
                "réponse d'IRIS." if fenetre > 0 else f"Chaque commande vocale commence par « {mot} ».")
        if not self._ecoute_active():
            voix = ECOUTE_ARRETEE + " " + voix
        return (voix + " Les minuteurs tournent sur l'ordinateur : une mise en veille retarde l'annonce. "
                "« Est-ce que c'est bon ? » décrit une seule photo des lunettes : ce n'est pas une garantie. "
                "Rien de la session n'est conservé.")

    def _minuteurs_publics(self) -> list[dict]:
        maintenant = self.maintenant()
        return [{"etape": n, "duree_s": m["duree_s"], "restant_s": max(0, int(math.ceil(m["fin"] - maintenant)))}
                for n, m in sorted(self._minuteurs.items())]

    def etat(self) -> dict:
        s = self._session
        if s is None:
            return {"actif": False}
        public = {k: v for k, v in s.items() if not k.startswith("_")}
        public["etapes"] = [dict(e) for e in s["etapes"]]
        public["minuteurs"] = self._minuteurs_publics()
        public["ecoute_active"] = self._ecoute_active()
        public["limite"] = self.limite()
        return public

    def _publier(self, annonce: str | None = None) -> None:
        try:
            # La session est imbriquée : son champ « type » écraserait le type de l'événement.
            self.ctx.hub.publish("pas_a_pas.etat", session=self.etat(), annonce=annonce)
        except Exception as exc:  # pragma: no cover
            log.debug("événement pas_a_pas.etat non publié : %s", exc)

    def _etape_courante(self) -> dict:
        s = self._session
        assert s is not None
        return s["etapes"][s["index"]]

    def phrase_etape(self, etape: dict | None = None) -> str:
        s = self._session
        assert s is not None
        etape = etape or self._etape_courante()
        total = len(s["etapes"])
        if self._verbosite() == "concis":
            phrase = f"Étape {etape['n']} : {etape['texte']}"
        else:
            phrase = f"Étape {etape['n']} sur {total} : {etape['texte']}"
        if not phrase.rstrip().endswith((".", "!", "?", "…")):
            phrase += "."
        if etape.get("minuteur_s") and etape["n"] not in self._minuteurs and self._verbosite() != "concis":
            phrase += f" Dites « lance le minuteur » pour {duree_parlee(etape['minuteur_s'])}."
        return phrase

    def _verifier_confidentiel(self) -> None:
        if getattr(self._user(), "privacy_mode", False):
            if self._session is not None:
                self.interrompre("mode confidentiel")
            raise RefusPasAPas(409, CONFIDENTIEL, phrase="Le mode confidentiel est actif : le pas à pas est arrêté.")

    # ------------------------------------------------------------------ rédaction par le moteur
    async def _rediger(self, sujet: str, type_: str | None) -> dict:
        """{titre, type, etapes} rédigé par le moteur. Lève RefusPasAPas 403, 409, 502."""
        from .connectors.base import ConnectorError
        from .consent import DATA_TYPES, ConsentRequired, LocalOnlyMode
        from .router import NoAgentAvailable

        message = f"Demande : « {sujet} ».\nType : {type_ or 'à déterminer'}."
        try:
            reponse = await self.ctx.chat.demander_image_detail(CONSIGNE_ETAPES, message, [],
                                                                consentement=("transcript",))
        except ConsentRequired as exc:
            libelle = DATA_TYPES.get(exc.data_type, {}).get("label", exc.data_type)
            texte = (f"Pour rédiger les étapes, IRIS doit envoyer le sujet au moteur VELA. Autorisez « {libelle} » "
                     "dans Confidentialité, ou fournissez les étapes.")
            raise RefusPasAPas(403, texte, detail={"code": "consentement", "data_type": exc.data_type,
                                                   "label": libelle, "message": texte},
                               phrase=f"Je ne peux pas rédiger les étapes sans ton accord : autorise « {libelle} » dans Confidentialité.")
        except LocalOnlyMode:
            raise RefusPasAPas(409, LOCAL_SEULEMENT, phrase="Le mode 100 % local est actif : je ne peux pas rédiger les étapes.")
        except NoAgentAvailable:
            if getattr(self._user(), "local_only", False):
                raise RefusPasAPas(409, LOCAL_SEULEMENT, phrase="Le mode 100 % local est actif : je ne peux pas rédiger les étapes.")
            raise RefusPasAPas(409, "Aucune IA n'est prête pour rédiger les étapes. Fournissez-les, ou vérifiez IRIS › IA.")
        except ConnectorError as exc:
            # Le détail peut nommer le fournisseur : il reste au journal, jamais dans la réponse.
            log.warning("pas à pas : moteur en erreur (%s)", exc)
            raise RefusPasAPas(502, MOTEUR_EN_PANNE, phrase="Le moteur VELA n'a pas répondu. Réessaie dans un instant.")
        try:
            lu = lire_reponse_moteur(reponse.get("texte") or "")
        except (ValueError, json.JSONDecodeError) as exc:
            log.info("pas à pas : réponse du moteur rejetée (%s)", exc)
            raise RefusPasAPas(502, REPONSE_ILLISIBLE, phrase="Je n'ai pas obtenu d'étapes utilisables. Réessaie en précisant le sujet.")
        lu["local"] = bool(reponse.get("local"))
        return lu

    # ------------------------------------------------------------------ session
    async def demarrer(self, sujet: str = "", type_: str = "autre", etapes: list[Any] | None = None,
                       parler: bool = True, _depuis_voix: bool = False) -> dict:
        """Ouvre une session (remplace la précédente). Lève RefusPasAPas 403, 409, 422, 502."""
        self._verifier_confidentiel()
        sujet = nettoyer_texte(sujet, SUJET_MAX)
        type_norm = normaliser(type_ or "autre").replace(" ", "")
        if type_norm not in TYPES:
            raise RefusPasAPas(422, f"Type inconnu : « {type_} ». Types : recette, montage, reparation, autre.")
        fournies = construire_etapes(etapes or [])
        if etapes and not fournies:
            raise RefusPasAPas(422, "Les étapes fournies sont vides.")
        local = True
        avertissement = None
        if fournies:
            liste, source = fournies, "fournies"
            sujet = sujet or TYPES[type_norm]
        else:
            if not sujet:
                raise RefusPasAPas(422, "Précisez le sujet (par exemple « crêpes » ou « changer un joint de robinet »), "
                                        "ou fournissez les étapes.")
            redige = await self._rediger(sujet, None if _depuis_voix else type_norm)
            liste, source, local = redige["etapes"], "moteur", redige["local"]
            if _depuis_voix:
                type_norm = redige["type"] or type_norm
                sujet = redige["titre"] or sujet
            avertissement = AVERTISSEMENTS[type_norm]
        self._verifier_confidentiel()  # la rédaction a pu durer : le mode a pu changer entre-temps
        self._annuler_minuteurs()
        self._session = {
            "id": uuid.uuid4().hex, "sujet": sujet, "type": type_norm, "etapes": liste, "index": 0, "actif": True,
            "source_etapes": source, "local": local, "avertissement": avertissement, "debut": maintenant_iso(),
        }
        phrase = f"{TYPES[type_norm]} : {sujet}. {len(liste)} étape{'s' if len(liste) > 1 else ''}."
        if avertissement and type_norm == "reparation":
            # Une personne qui n'a que la voix doit entendre la consigne de sécurité, même en mode concis.
            phrase += " " + avertissement
        elif avertissement and self._verbosite() != "concis":
            phrase += " Étapes rédigées automatiquement : vérifiez-les."
        phrase += " " + self.phrase_etape()
        self.ctx.consent.log("pas_a_pas_debut", detail=f"{type_norm} / {source} / {len(liste)} étapes")
        return await self._conclure(phrase, parler)

    async def _conclure(self, phrase: str, parler: bool, **extra: Any) -> dict:
        self._publier(phrase)
        if parler:
            await self.dire(phrase)
        return {**self.etat(), **extra, "phrase": phrase}

    async def commande(self, action: str, secondes: int | None = None, parler: bool = True,
                       image: Any = None) -> dict:
        """Applique une commande à la session. Lève RefusPasAPas 409 (aucune session, confidentiel), 422."""
        self._verifier_confidentiel()
        action = normaliser(action or "").replace(" ", "_")
        if action not in ACTIONS and action != "ou":
            raise RefusPasAPas(422, f"Action inconnue : « {action} ». Actions : {', '.join(ACTIONS)}.")
        s = self._session
        if s is None:
            raise RefusPasAPas(409, AUCUNE_SESSION, phrase="Aucun pas à pas n'est en cours.")
        dernier = len(s["etapes"]) - 1
        if action == "suivant":
            if s["index"] >= dernier:
                phrase = "C'était la dernière étape. Dites « c'est fini » pour terminer."
            else:
                s["index"] += 1
                phrase = self.phrase_etape()
            return await self._conclure(phrase, parler)
        if action == "precedent":
            if s["index"] <= 0:
                phrase = "Vous êtes à la première étape. " + self.phrase_etape()
            else:
                s["index"] -= 1
                phrase = self.phrase_etape()
            return await self._conclure(phrase, parler)
        if action == "repeter":
            return await self._conclure(self.phrase_etape(), parler)
        if action == "ou":
            return await self._conclure(self._phrase_ou(), parler)
        if action == "minuteur":
            return await self._conclure(self.lancer_minuteur(secondes), parler)
        if action == "annuler_minuteur":
            return await self._conclure(self.annuler_minuteur(), parler)
        if action == "verifier":
            verification = await self.verifier(image=image)
            return await self._conclure(verification["phrase"], parler, verification=verification)
        return await self.terminer(parler)

    def _phrase_ou(self) -> str:
        s = self._session
        assert s is not None
        phrase = f"{TYPES[s['type']]} : {s['sujet']}. " + self.phrase_etape()
        for m in self._minuteurs_publics():
            phrase += f" Minuteur de l'étape {m['etape']} : {duree_parlee(m['restant_s'])} restantes."
        return phrase

    async def terminer(self, parler: bool = True) -> dict:
        s = self._session
        if s is None:
            raise RefusPasAPas(409, AUCUNE_SESSION, phrase="Aucun pas à pas n'est en cours.")
        annules = len(self._minuteurs)
        self._annuler_minuteurs()
        final = {**self.etat(), "actif": False, "fin": maintenant_iso(), "minuteurs": []}
        self._session = None
        phrase = "Pas à pas terminé."
        if annules:
            phrase += f" {annules} minuteur{'s' if annules > 1 else ''} annulé{'s' if annules > 1 else ''}."
        self.ctx.consent.log("pas_a_pas_fin", detail=f"{s['type']} / étape {s['index'] + 1} sur {len(s['etapes'])}")
        self._publier(phrase)
        if parler:
            await self.dire(phrase)
        return {**final, "phrase": phrase}

    def interrompre(self, raison: str) -> None:
        """Arrêt immédiat, sans voix (mode confidentiel, arrêt du service)."""
        if self._session is None and not self._minuteurs:
            return
        self._annuler_minuteurs()
        self._session = None
        log.info("pas à pas interrompu : %s", raison)
        self._publier(None)

    # ------------------------------------------------------------------ minuteurs
    def lancer_minuteur(self, secondes: int | None = None) -> str:
        s = self._session
        assert s is not None
        etape = self._etape_courante()
        duree = int(secondes) if secondes else etape.get("minuteur_s")
        if not duree:
            raise RefusPasAPas(422, SANS_DUREE)
        if not 1 <= duree <= MINUTEUR_MAX_S:
            raise RefusPasAPas(422, "Un minuteur dure de 1 seconde à 24 heures.")
        n = etape["n"]
        if n in self._minuteurs:
            restant = self._minuteurs[n]["fin"] - self.maintenant()
            return f"Le minuteur de l'étape {n} tourne déjà : {duree_parlee(restant)} restantes."
        if len(self._minuteurs) >= MINUTEURS_MAX:
            raise RefusPasAPas(409, f"Déjà {MINUTEURS_MAX} minuteurs en cours : attendez qu'un se termine ou annulez-en un.")
        fin = self.maintenant() + duree
        tache = asyncio.get_running_loop().create_task(self._tourner_minuteur(s["id"], n, fin))
        self._minuteurs[n] = {"tache": tache, "fin": fin, "duree_s": duree}
        return f"Minuteur lancé : {duree_parlee(duree)} pour l'étape {n}."

    def annuler_minuteur(self) -> str:
        if not self._minuteurs:
            return "Aucun minuteur en cours."
        n = self._etape_courante()["n"] if self._session else None
        if n in self._minuteurs:
            self._minuteurs.pop(n)["tache"].cancel()
            return f"Minuteur de l'étape {n} annulé."
        nombre = len(self._minuteurs)
        self._annuler_minuteurs()
        return f"{nombre} minuteur{'s' if nombre > 1 else ''} annulé{'s' if nombre > 1 else ''}."

    def _annuler_minuteurs(self) -> None:
        courante = asyncio.current_task() if _boucle_active() else None
        for m in self._minuteurs.values():
            if m["tache"] is not courante:
                m["tache"].cancel()
        self._minuteurs.clear()

    async def _tourner_minuteur(self, session_id: str, n: int, fin: float) -> None:
        while (restant := fin - self.maintenant()) > 0:
            await self.dormir(restant)
        s = self._session
        m = self._minuteurs.get(n)
        if s is None or s["id"] != session_id or m is None or m["fin"] != fin:
            return
        self._minuteurs.pop(n, None)
        annonce = f"Minuteur terminé pour l'étape {n}."
        self._publier(annonce)
        await self.dire(annonce)

    # ------------------------------------------------------------------ vérification par la caméra
    async def verifier(self, image: Any = None) -> dict:
        """Décrit une photo au regard de l'étape. {phrase, texte, local, duree_ms}. Lève les refus de la vision."""
        s = self._session
        assert s is not None
        acces = getattr(self.ctx, "accessibilite", None)
        if acces is None or not callable(getattr(acces, "decrire", None)):
            raise RefusPasAPas(409, VISION_ABSENTE, phrase="Je ne peux pas regarder : la vision n'est pas disponible.")
        etape = self._etape_courante()
        question = (
            f"L'utilisateur suit un pas à pas ({TYPES[s['type']].lower()} : {s['sujet'][:80]}). Étape {etape['n']} : "
            f"« {etape['texte'][:200]} ». Il demande si c'est bon. Dis ce que la photo montre d'utile pour cette étape ; "
            "si ça ne se voit pas, dis-le ; n'affirme jamais qu'un aliment est cuit à point ni qu'un montage est sécuritaire."
        )
        resultat = await acces.decrire("scene", "image" if image else "lunettes", image=image, question=question,
                                       parler=False, memoriser=False)
        texte = (resultat.get("texte") or "").strip()
        phrase = f"D'après la photo : {texte}" if texte else "Je n'ai rien pu tirer de la photo."
        return {"phrase": phrase, "texte": texte, "local": bool(resultat.get("local")),
                "duree_ms": resultat.get("duree_ms")}

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str):
        """Commandes de session (priorité 20). None tout de suite hors session ou hors commande."""
        if self._session is None:
            return None
        trouve = action_vocale(texte)
        if trouve is None:
            return None
        return self._commande_vocale(*trouve)

    async def _commande_vocale(self, action: str, secondes: int | None) -> str:
        try:
            # La réponse est dite par l'écoute elle-même : ne pas la lire une seconde fois.
            resultat = await self.commande(action, secondes=secondes, parler=False)
        except RefusPasAPas as exc:
            return exc.phrase
        except HTTPException as exc:
            return str(getattr(exc, "phrase", "") or "Je ne peux pas le faire pour l'instant.")
        except Exception:
            log.exception("commande vocale du pas à pas en erreur")
            return "Je n'ai pas réussi à le faire."
        return resultat.get("phrase") or ""

    def interception_demarrage(self, texte: str):
        """« Guide-moi pas à pas pour faire des crêpes » (priorité 60, permanente)."""
        norme = normaliser(texte)
        if not any(f" {m} " in f" {norme} " for m in MARQUEURS_DEMARRAGE):
            return None
        mots = set(norme.split())
        if correspond(norme, PHRASES_TERMINER) or not any(v in mots for v in VERBES_DEMARRAGE):
            return None
        return self._demarrage_vocal(texte)

    async def _demarrage_vocal(self, texte: str) -> str:
        if self._session is not None:
            return "Un pas à pas est déjà en cours. Dites « c'est fini » pour l'arrêter d'abord."
        try:
            resultat = await self.demarrer(texte, "autre", None, parler=False, _depuis_voix=True)
        except RefusPasAPas as exc:
            return exc.phrase
        except Exception:
            log.exception("démarrage vocal du pas à pas en erreur")
            return "Je n'ai pas réussi à préparer les étapes."
        return resultat.get("phrase") or ""

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("assistants-pas-a-pas", self.interception, priorite=20)
            voice.ajouter_interception("assistants-pas-a-pas-demarrer", self.interception_demarrage, priorite=60)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("assistants-pas-a-pas")
            voice.retirer_interception("assistants-pas-a-pas-demarrer")


def _boucle_active() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
