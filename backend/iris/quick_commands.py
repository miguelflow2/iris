"""Commandes courantes reconnues sans passer par un modèle de langage.

Pourquoi : les modèles gratuits d'OpenRouter suivent mal les consignes d'outils. Trace réelle de
« ouvre youtube et lance une vidéo de mrbeast » : douze tours de modèle, une recherche ouverte,
des captures d'écran, des clics à l'aveugle, puis un arrêt de sécurité. Ces demandes-là sont pourtant
sans ambiguïté : on les exécute directement, en une fraction de seconde et sans dépendre du réseau.

Le filet est volontairement étroit : au moindre doute on renvoie None et le modèle reprend la main.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class QuickCommand:
    """Intention reconnue localement. `tool` vide = simple réponse parlée (heure, question de précision)."""

    tool: str = ""
    args: dict = field(default_factory=dict)
    reply: str = ""
    kind: str = ""


# Sites courants : « ouvre YouTube » doit ouvrir le site, pas chercher une application du même nom.
SITES = {
    "youtube": "https://www.youtube.com",
    "you tube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google agenda": "https://calendar.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.ca",
    "wikipedia": "https://fr.wikipedia.org",
    "wikipedia francais": "https://fr.wikipedia.org",
    "twitch": "https://www.twitch.tv",
    "linkedin": "https://www.linkedin.com",
    "chat gpt": "https://chat.openai.com",
    "reddit": "https://www.reddit.com",
    "le devoir": "https://www.ledevoir.com",
    "radio canada": "https://ici.radio-canada.ca",
}

# Mots qui signalent une demande de vidéo ou de musique (donc YouTube, jamais une recherche web).
MEDIA_MARKERS = ("musique", "chanson", "chansons", "video", "videos", "clip", "clips", "playlist", "morceau", "album", "radio")
# Verbes de lecture (« joue », « écoute ») : à eux seuls ils désignent déjà un média.
PLAY_VERBS = ("joue", "jouer", "ecoute", "ecouter", "fais jouer", "fait jouer", "passe")
# Verbes d'ouverture, avec les variantes que produit la reconnaissance vocale (« ouvres », « mais »).
OPEN_VERBS = ("ouvre", "ouvres", "ouvrir", "lance", "lances", "lancer", "demarre", "demarres", "demarrer", "affiche", "va sur", "vas sur")
SET_VERBS = ("mets", "met", "mais", "mettre")

_FILLERS = (
    "moi", "nous", "s il te plait", "s il vous plait", "stp", "svp", "merci", "maintenant", "tout de suite",
    "pour moi", "un peu", "de la", "du", "des", "le", "la", "les", "l", "un", "une", "mon", "ma", "mes", "sur",
)
_TRAILING = ("sur youtube", "sur you tube", "sur internet", "sur le web", "s il te plait", "s il vous plait", "stp", "svp", "merci")


def _strip_words(text: str, words) -> str:
    out = text
    for w in sorted(words, key=len, reverse=True):
        out = re.sub(rf"(?:^|\s){re.escape(w)}(?=\s|$)", " ", out)
    return _squeeze(out)


def _strip_trailing(text: str) -> str:
    out = _squeeze(text)
    changed = True
    while changed:
        changed = False
        for t in _TRAILING:
            if out.endswith(" " + t) or out == t:
                out = _squeeze(out[: len(out) - len(t)])
                changed = True
    return out


def _clock_reply(now: datetime) -> str:
    heure = now.hour
    minute = now.minute
    if minute == 0:
        return f"Il est {heure} heure{'s' if heure > 1 else ''} pile."
    return f"Il est {heure} heure{'s' if heure > 1 else ''} {minute}."


_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _date_reply(now: datetime) -> str:
    return f"Nous sommes le {_JOURS[now.weekday()]} {now.day} {_MOIS[now.month - 1]} {now.year}."


def _media_query(text: str) -> str | None:
    """Extrait ce qu'il faut chercher sur YouTube, ou "" si l'utilisateur n'a pas dit quoi lancer."""
    rest = text
    # « ouvre youtube et lance une vidéo de mrbeast » : on jette seulement le préfixe d'ouverture.
    # Jamais un « sur youtube » placé en fin de phrase, qui n'est pas la demande elle-même.
    rest = re.sub(rf"^(?:{'|'.join(OPEN_VERBS)})\s+(?:you tube|youtube)\s*(?:et|puis)?\s*", "", rest)
    verbs = "|".join(sorted(PLAY_VERBS + SET_VERBS + ("lance", "lances", "lancer", "regarde", "montre"), key=len, reverse=True))
    m = re.search(rf"(?:^|\s)(?:{verbs})\s+(?P<q>.*)$", rest)
    query = m.group("q") if m else rest
    query = _strip_trailing(query)
    # retire l'objet générique : « une vidéo de X » -> « X », « de la musique » -> « »
    query = re.sub(rf"^(?:moi\s+)?(?:une|un|de la|de l|du|des|la|le|les)?\s*(?:{'|'.join(MEDIA_MARKERS)})\b", "", query)
    query = re.sub(r"^\s*(?:de|du|d|avec|par|pour)\b", "", query)
    query = _strip_trailing(_squeeze(query))
    if query in ("", "ca", "quelque chose", "n importe quoi"):
        return ""
    return query


def match(text: str, app_resolver=None, now: datetime | None = None) -> QuickCommand | None:
    """Reconnaît une commande simple. `app_resolver(nom)` renvoie un nom d'application sûr, ou None."""
    raw = _squeeze(normalize(text))
    # phrase longue = demande composée ou nuancée : on laisse le modèle la traiter
    if not raw or len(raw.split()) > 14:
        return None
    now = now or datetime.now()

    # ------------------------------------------------------------------ heure et date
    if re.search(r"\b(quelle heure|il est quelle heure|heure est il|heure qu il est)\b", raw):
        return QuickCommand(reply=_clock_reply(now), kind="heure")
    if re.search(r"\b(quelle date|quel jour|quelle est la date|on est quel jour|date d aujourd hui)\b", raw):
        return QuickCommand(reply=_date_reply(now), kind="date")

    words = raw.split()
    has_media = any(w in MEDIA_MARKERS for w in words) or any(raw.startswith(v + " ") or f" {v} " in f" {raw} " for v in PLAY_VERBS)
    has_open = any(raw.startswith(v + " ") for v in OPEN_VERBS) or any(f" {v} " in f" {raw} " for v in OPEN_VERBS)
    has_set = any(raw.startswith(v + " ") for v in SET_VERBS)

    # ------------------------------------------------------------------ musique / vidéo
    if has_media and (has_open or has_set or any(v in raw for v in PLAY_VERBS)):
        query = _media_query(raw)
        if query is None:
            return None
        if not query:
            return QuickCommand(reply="Quelle musique veux-tu ?", kind="precision")
        return QuickCommand(tool="play_youtube", args={"query": query}, reply=f"Je lance {query} sur YouTube.", kind="media")

    # ------------------------------------------------------------------ ouvrir un site ou une application
    if has_open:
        verbs = "|".join(sorted(OPEN_VERBS, key=len, reverse=True))
        m = re.match(rf"^(?:{verbs})\s+(?P<cible>.+)$", raw)
        if not m:
            return None
        cible = _strip_trailing(m.group("cible"))
        cible = re.sub(r"^(?:moi|nous)\s+", "", cible)
        cible = _strip_words(cible, ("mon", "ma", "mes", "le", "la", "les", "l", "un", "une", "s il te plait", "stp"))
        if not cible or len(cible.split()) > 4:
            return None
        if " et " in cible or " puis " in cible:
            return None  # demande composée : le modèle gère mieux
        if cible in SITES:
            return QuickCommand(tool="open_url", args={"url": SITES[cible]}, reply=f"J'ouvre {cible}.", kind="site")
        if app_resolver is not None:
            nom = app_resolver(cible)
            if nom:
                return QuickCommand(tool="open_application", args={"name": nom}, reply=f"J'ouvre {nom}.", kind="app")
        return None

    return None
