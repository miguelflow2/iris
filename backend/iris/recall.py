"""Capture de souvenirs : ce qu'IRIS retient vient de ce que l'utilisateur a réellement dit.

Principe : la mémoire d'IRIS n'est **pas générative**. Aucun modèle n'invente ni ne reformule un souvenir.
Un souvenir est une phrase que l'utilisateur a prononcée, repérée par des motifs explicites, stockée
telle quelle avec sa date et sa provenance. IRIS peut donc toujours répondre « tu me l'as dit le 3 septembre »,
et l'utilisateur peut relire, corriger ou supprimer chaque ligne.

Le filet est volontairement étroit : mieux vaut ne rien retenir que retenir une invention.
"""
from __future__ import annotations

import re
import unicodedata

# Motifs de faits durables. Chaque motif décrit une formulation où l'utilisateur énonce
# explicitement quelque chose qui vaut la peine d'être retenu au-delà de la conversation.
_MOTIFS: list[tuple[str, str]] = [
    # demande explicite de mémorisation
    (r"\b(?:souviens[- ]toi|rappelle[- ]toi|retiens|note|n'oublie pas)\s+(?:bien\s+)?(?:que\s+|de\s+|:\s*)?(?P<fait>.{4,220})", "consigne"),
    # identité et rattachements
    (r"\b(?:je m'appelle|mon nom est|moi c'est)\s+(?P<fait>.{2,60})", "identite"),
    (r"\b(?:j'habite|je vis|je reste)\s+(?P<fait>(?:à|au|en|dans|sur)\s+.{2,80})", "identite"),
    (r"\b(?:je travaille|j'étudie|je suis étudiant|je suis inscrit)\s+(?P<fait>(?:à|au|en|chez|dans|pour)\s+.{2,90})", "identite"),
    # préférences et habitudes
    (r"\b(?:je préfère|j'aime mieux|je déteste|j'aime pas|je n'aime pas|j'aime)\s+(?P<fait>.{3,140})", "preference"),
    (r"\b(?:j'utilise|je me sers de|mon navigateur est|mon éditeur est)\s+(?P<fait>.{2,90})", "preference"),
    (r"\b(?:appelle[- ]moi|tu peux m'appeler)\s+(?P<fait>.{2,50})", "preference"),
    # engagements datés
    (r"\b(?:j'ai|je passe|je dois passer)\s+(?P<fait>(?:un |une |mon |ma )?(?:examen|entrevue|interview|rendez[- ]vous|réunion|présentation|remise|test)\b.{0,140})", "engagement"),
    (r"\b(?:je dois|il faut que je|faut que je)\s+(?P<fait>.{4,160})", "engagement"),
]

_COMPILES = [(re.compile(motif, re.IGNORECASE), genre) for motif, genre in _MOTIFS]

# Une phrase qui interroge n'énonce pas un fait à retenir.
_QUESTION = re.compile(r"^\s*(?:est[- ]ce|qu'est|quoi|qui|quand|où|ou est|comment|pourquoi|combien|quel|quelle)\b", re.IGNORECASE)
_COUPE = re.compile(r"\s+(?:mais|donc|alors|et puis|parce que|pour que)\s+", re.IGNORECASE)


def _normalise(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", t.lower()).strip()


def _nettoie(fait: str) -> str:
    """Coupe la phrase à sa proposition principale et retire la ponctuation finale."""
    fait = fait.strip().strip("«»\"'")
    coupe = _COUPE.split(fait, maxsplit=1)[0]
    fait = coupe if len(coupe) >= 8 else fait
    fait = re.split(r"[.!?;]\s", fait, maxsplit=1)[0]
    return fait.strip().rstrip(".,;: ").strip()


def extraire(texte: str) -> list[dict]:
    """Faits durables énoncés dans `texte`. Retourne le fait ET la phrase d'origine, mot pour mot."""
    trouves: list[dict] = []
    vus: set[str] = set()
    for phrase in re.split(r"(?<=[.!?])\s+|\n+", (texte or "").strip()):
        phrase = phrase.strip()
        if len(phrase) < 6 or phrase.endswith("?") or _QUESTION.match(phrase):
            continue
        for motif, genre in _COMPILES:
            m = motif.search(phrase)
            if not m:
                continue
            fait = _nettoie(m.group("fait"))
            cle = _normalise(fait)
            if len(cle) < 4 or cle in vus or not _substantiel(fait):
                continue
            vus.add(cle)
            trouves.append({"fait": fait, "kind": genre, "phrase": phrase})
            break  # un fait par phrase : on ne multiplie pas les doublons
    return trouves


# Mots trop pauvres pour constituer un souvenir à eux seuls.
_VIDES = {
    "ca", "cela", "ceci", "ce", "cette", "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "moi", "toi", "lui", "eux", "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "y", "en",
    "tout", "tous", "rien", "truc", "chose", "ici", "la bas", "bien", "aussi", "plus", "tres",
}


def _substantiel(fait: str) -> bool:
    """Un souvenir doit porter une information. « de ça », « ce truc », « bien » n'en sont pas.
    Sans ce filtre, IRIS accumulait des lignes vides qui polluaient ses rappels."""
    mots = [m for m in _normalise(fait).split() if m and m not in _VIDES]
    if not mots:
        return False
    if len(mots) == 1 and len(mots[0]) < 4:
        return False
    return sum(len(m) for m in mots) >= 5


def doublon(fait: str, existants: list[str]) -> bool:
    """Le fait est-il déjà en mémoire ? Comparaison sur le texte normalisé, sans modèle."""
    cle = _normalise(fait)
    if not cle:
        return True
    for autre in existants:
        a = _normalise(autre)
        if not a:
            continue
        if cle == a or cle in a or a in cle:
            return True
    return False
