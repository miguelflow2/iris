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

# Applications de lecture autres que YouTube. Si l'utilisateur en nomme une, c'est elle qu'il veut :
# le raccourci YouTube n'a rien à faire là, et l'agent saura piloter l'application à l'écran.
AUTRES_LECTEURS = (
    "spotify", "deezer", "apple music", "soundcloud", "tidal", "amazon music", "napster",
    "netflix", "disney", "prime video", "crave", "tou tv", "vlc", "plex", "itunes",
    "windows media", "groove", "twitch", "audible",
)
# Références à la bibliothèque personnelle : une recherche YouTube n'y a aucun accès.
PERSONNEL = (
    "ma liste", "mes listes", "ma playlist", "mes playlists", "mes chansons", "mes musiques",
    "mes favoris", "mes titres", "mes morceaux", "ma bibliotheque", "mes aimes", "aimee", "aimees",
    "mon historique", "ma selection", "mes videos", "mon album", "mes albums",
)


def _demande_composee(texte: str) -> bool:
    """Deux ordres enchaînés : le filet local n'en exécuterait qu'un."""
    return " et " in texte or " puis " in texte or " ensuite " in texte

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


# Fuseaux horaires. Constat réel : « quelle heure est-il en Chine ? » renvoyait l'heure de
# Trois-Rivières, parce que la reconnaissance locale voyait « quelle heure » et s'arrêtait là.
# Une réponse fausse dite avec assurance est pire qu'une absence de réponse.
FUSEAUX: dict[str, str] = {
    # Amériques
    "quebec": "America/Toronto", "montreal": "America/Toronto", "toronto": "America/Toronto",
    "trois rivieres": "America/Toronto", "ottawa": "America/Toronto", "new york": "America/New_York",
    "vancouver": "America/Vancouver", "calgary": "America/Edmonton", "winnipeg": "America/Winnipeg",
    "halifax": "America/Halifax", "mexique": "America/Mexico_City", "bresil": "America/Sao_Paulo",
    "sao paulo": "America/Sao_Paulo", "los angeles": "America/Los_Angeles", "chicago": "America/Chicago",
    "haiti": "America/Port-au-Prince", "argentine": "America/Argentina/Buenos_Aires",
    # Europe
    "france": "Europe/Paris", "paris": "Europe/Paris", "belgique": "Europe/Brussels",
    "bruxelles": "Europe/Brussels", "suisse": "Europe/Zurich", "geneve": "Europe/Zurich",
    "angleterre": "Europe/London", "londres": "Europe/London", "royaume uni": "Europe/London",
    "espagne": "Europe/Madrid", "madrid": "Europe/Madrid", "allemagne": "Europe/Berlin",
    "berlin": "Europe/Berlin", "italie": "Europe/Rome", "rome": "Europe/Rome",
    "portugal": "Europe/Lisbon", "lisbonne": "Europe/Lisbon", "grece": "Europe/Athens",
    "ukraine": "Europe/Kyiv", "russie": "Europe/Moscow", "moscou": "Europe/Moscow",
    # Afrique
    "maroc": "Africa/Casablanca", "casablanca": "Africa/Casablanca", "algerie": "Africa/Algiers",
    "tunisie": "Africa/Tunis", "senegal": "Africa/Dakar", "dakar": "Africa/Dakar",
    "cote d ivoire": "Africa/Abidjan", "abidjan": "Africa/Abidjan", "cameroun": "Africa/Douala",
    "congo": "Africa/Kinshasa", "kinshasa": "Africa/Kinshasa", "nigeria": "Africa/Lagos",
    "egypte": "Africa/Cairo", "afrique du sud": "Africa/Johannesburg", "kenya": "Africa/Nairobi",
    # Asie et Océanie
    "chine": "Asia/Shanghai", "pekin": "Asia/Shanghai", "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai", "shenzhen": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "japon": "Asia/Tokyo", "tokyo": "Asia/Tokyo", "coree": "Asia/Seoul", "seoul": "Asia/Seoul",
    "inde": "Asia/Kolkata", "vietnam": "Asia/Ho_Chi_Minh", "thailande": "Asia/Bangkok",
    "bangkok": "Asia/Bangkok", "singapour": "Asia/Singapore", "dubai": "Asia/Dubai",
    "emirats": "Asia/Dubai", "israel": "Asia/Jerusalem", "turquie": "Europe/Istanbul",
    "istanbul": "Europe/Istanbul", "australie": "Australia/Sydney", "sydney": "Australia/Sydney",
    "nouvelle zelande": "Pacific/Auckland",
}
# Ce qui suit « à » sans désigner un lieu : « à peu près », « à présent »...
_PAS_UN_LIEU = {"peu", "pres", "present", "maintenant", "cet", "cette", "la", "le", "quelle", "quel", "combien"}
_AILLEURS = re.compile(r"\b(?:en|au|aux|a|chez|dans|sur)\s+([a-z]{2,})")


def fuseau_demande(raw: str) -> tuple[str | None, bool]:
    """(fuseau IANA, un ailleurs est-il évoqué ?) pour une question d'heure ou de date.

    Trois cas. Un lieu connu : on répond juste, hors ligne, grâce à zoneinfo. Un lieu inconnu :
    on ne répond pas, la question part au modèle — plutôt que de servir l'heure d'ici sous un
    autre nom. Aucun lieu : c'est bien l'heure locale qu'on demande."""
    for nom in sorted(FUSEAUX, key=len, reverse=True):  # « afrique du sud » avant « sud »
        if re.search(rf"\b{re.escape(nom)}\b", raw):
            return FUSEAUX[nom], True
    for suite in _AILLEURS.findall(raw):
        if suite not in _PAS_UN_LIEU:
            return None, True
    return None, False


def _clock_reply_ailleurs(zone: str) -> str | None:
    """Heure d'un fuseau. None si les données de fuseaux manquent : mieux vaut se taire."""
    try:
        from zoneinfo import ZoneInfo

        return _clock_reply(datetime.now(ZoneInfo(zone)))
    except Exception:
        return None


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


# « Traduis ce qu'il dit » : reconnu ICI, sans passer par le modèle.
#
# Par la voix, ce chemin existe déjà et il est déterministe (voice/listener.py). Par écrit, non :
# interrogée le 5 septembre 2026, IRIS a répondu « Bien sûr ! Dis-moi ce qu'il a dit et je te le
# traduis » — une réponse polie qui n'ouvre rien. L'outil était pourtant offert : c'est le modèle
# gratuit qui n'a pas su le choisir. Quand une intention est aussi nette, on ne la confie pas à un
# modèle qu'on ne maîtrise pas.
DEMANDE_TRADUCTION = (
    "traduis ce qu il dit", "traduis ce qu elle dit", "traduis ce qu ils disent",
    "traduis moi ce qu il dit", "traduis moi ce qu elle dit", "traduis la conversation",
    "traduis ce qu on me dit", "peux tu traduire ce qu il dit", "peux tu traduire ce qu elle dit",
    "traduis moi cette personne", "traduis cette personne", "mode traduction",
    "active la traduction", "commence la traduction", "traduis en direct", "traduis en temps reel",
)
FIN_TRADUCTION = (
    "arrete la traduction", "arrete de traduire", "stop la traduction", "coupe la traduction",
    "ferme la traduction", "desactive la traduction", "fin de la traduction",
)


def match(text: str, app_resolver=None, now: datetime | None = None) -> QuickCommand | None:
    """Reconnaît une commande simple. `app_resolver(nom)` renvoie un nom d'application sûr, ou None."""
    raw = _squeeze(normalize(text))
    # phrase longue = demande composée ou nuancée : on laisse le modèle la traiter
    if not raw or len(raw.split()) > 14:
        return None
    now = now or datetime.now()

    # La fermeture d'abord : « arrête la traduction » contient « traduis », et l'ordre inverse
    # rouvrirait le mode avec la phrase censée le clore.
    if any(f in raw for f in FIN_TRADUCTION):
        return QuickCommand(tool="arreter_traduction", args={}, kind="traduction")
    if any(d in raw for d in DEMANDE_TRADUCTION):
        return QuickCommand(tool="traduire_conversation", args={}, kind="traduction")

    # ------------------------------------------------------------------ heure et date
    if re.search(r"\b(quelle heure|il est quelle heure|heure est il|heure qu il est)\b", raw):
        zone, ailleurs = fuseau_demande(raw)
        if zone:
            dit = _clock_reply_ailleurs(zone)
            return QuickCommand(reply=dit, kind="heure") if dit else None
        if ailleurs:
            return None  # un lieu qu'on ne connaît pas : au modèle de répondre, jamais l'heure d'ici
        return QuickCommand(reply=_clock_reply(now), kind="heure")
    if re.search(r"\b(quelle date|quel jour|quelle est la date|on est quel jour|date d aujourd hui)\b", raw):
        _, ailleurs = fuseau_demande(raw)
        if ailleurs:
            return None
        return QuickCommand(reply=_date_reply(now), kind="date")

    words = raw.split()
    has_media = any(w in MEDIA_MARKERS for w in words) or any(raw.startswith(v + " ") or f" {v} " in f" {raw} " for v in PLAY_VERBS)
    has_open = any(raw.startswith(v + " ") for v in OPEN_VERBS) or any(f" {v} " in f" {raw} " for v in OPEN_VERBS)
    has_set = any(raw.startswith(v + " ") for v in SET_VERBS)

    # ------------------------------------------------------------------ musique / vidéo
    if has_media and (has_open or has_set or any(v in raw for v in PLAY_VERBS)):
        # Une autre application de lecture est nommée : c'est elle qu'il faut piloter.
        if any(app in raw for app in AUTRES_LECTEURS):
            return None
        # L'utilisateur parle de SA bibliothèque : YouTube ne peut pas y accéder.
        if any(ref in raw for ref in PERSONNEL):
            return None
        # Demande en plusieurs étapes, sauf si tout se joue sur YouTube.
        if _demande_composee(raw) and "youtube" not in raw and "you tube" not in raw:
            return None
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
        if _demande_composee(" " + cible + " "):
            return None  # demande composée : le modèle gère mieux
        if any(ref in raw for ref in PERSONNEL):
            return None  # « ouvre mes photos de vacances » demande de chercher, pas d'ouvrir
        if cible in SITES:
            return QuickCommand(tool="open_url", args={"url": SITES[cible]}, reply=f"J'ouvre {cible}.", kind="site")
        if app_resolver is not None:
            nom = app_resolver(cible)
            if nom:
                return QuickCommand(tool="open_application", args={"name": nom}, reply=f"J'ouvre {nom}.", kind="app")
        return None

    return None
