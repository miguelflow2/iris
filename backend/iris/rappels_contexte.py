"""Rappels contextuels : « la prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés ».

Un rappel lié à une PERSONNE plutôt qu'à une heure. Le module découle d'un constat : IRIS ne voit
pas qui est devant l'utilisateur. Les lunettes n'envoient pas de flux vidéo, et la reconnaissance
faciale est volontairement exclue (données biométriques : consentement exprès et déclaration
préalable à la Commission d'accès à l'information du Québec). Un rappel ne se déclenche donc que sur
des indices HONNÊTES, qu'IRIS peut réellement constater :

- le nom est entendu dans les sous-titres (phrase finale, mot entier, sans accents) ;
- le nom apparaît dans une commande vocale, ou l'utilisateur dit « je suis avec Marc » ;
- le nom apparaît dans un message écrit à IRIS, un texto reçu, un brouillon de message, ou tout
  événement de courriel ou de téléphonie qui porte du texte.

Règles :
- un rappel ne se déclenche qu'une fois (mise à jour conditionnelle en base : deux sources simultanées
  ne l'annoncent pas deux fois) ;
- la phrase qui CRÉE le rappel ne le déclenche pas, un événement antérieur à la création non plus, et
  les sous-titres sont ignorés pendant un court délai de grâce (IRIS qui répète le nom en confirmant
  ne doit pas se déclencher elle-même par le micro) ;
- personne et texte sont chiffrés (ctx.crypto) ; la rétention s'applique ;
- mémoire suspendue (mode invité, zone sans mémoire) : aucun rappel n'est créé ni déclenché — un
  invité qui porte les lunettes n'a pas à entendre les rappels du propriétaire ;
- mode confidentiel : aucun déclenchement.

Limites dites telles quelles : un appel entrant ne porte qu'un numéro (aucun carnet de contacts n'est
relié), il ne déclenche donc rien ; un nom mal transcrit par la reconnaissance vocale ne déclenche
pas ; un prénom qui est aussi un mot courant (Pierre, Rose) peut déclencher à tort.

Service exposé sous ctx.rappels_contexte (voir routes_quotidien.py).
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

log = logging.getLogger("iris.rappels_contexte")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rappels_contexte (
    id TEXT PRIMARY KEY,
    cree_le TEXT NOT NULL,
    cree_epoch REAL NOT NULL,
    personne_enc BLOB NOT NULL,
    texte_enc BLOB NOT NULL,
    origine TEXT NOT NULL DEFAULT 'route',
    declenche_le TEXT,
    declencheur TEXT,
    retenu_jusqua TEXT
);
CREATE INDEX IF NOT EXISTS idx_rappels_contexte_cree ON rappels_contexte(cree_le);
"""

# IRIS qui confirme « C'est noté pour Marc » peut être captée par les sous-titres : pendant ce délai
# après la création, les sous-titres ne déclenchent pas le rappel. Les autres sources (message écrit,
# « je suis avec Marc ») ne sont pas concernées : elles ne viennent pas du haut-parleur.
GRACE_SOUS_TITRES_S = 45.0
PERSONNE_MAX_MOTS = 4
TEXTE_MAX = 300
PERSONNE_MAX = 60

# Libellés des déclencheurs, tels que rendus par l'API et l'événement rappel.contexte.
DECLENCHEURS = {
    "sous_titres": "nom entendu dans les sous-titres",
    "presence": "« je suis avec… » dit à IRIS",
    "commande_vocale": "nom prononcé dans une commande vocale",
    "message_ecrit": "nom écrit dans un message à IRIS",
    "sms": "nom présent dans un texto reçu",
    "brouillon_message": "nom présent dans un brouillon de message",
    "courriel": "nom présent dans un courriel",
    "telephonie": "nom présent dans un événement de téléphonie",
}

MEMOIRE_SUSPENDUE = "La mémoire est suspendue ({raison}) : aucun rappel n'est créé tant qu'elle l'est."

# Mots de relation ou de politesse : « ma sœur Julie » se déclenche sur « Julie », pas sur « sœur ».
_MOTS_RELATION = {
    "mon", "ma", "mes", "le", "la", "les", "l", "un", "une", "ce", "cette", "notre", "nos", "votre", "vos",
    "monsieur", "madame", "mademoiselle", "m", "mme", "mr", "dr", "dre", "docteur", "docteure", "me", "maitre",
    "ami", "amie", "amis", "copain", "copine", "chum", "blonde", "conjoint", "conjointe", "mari", "femme",
    "frere", "soeur", "pere", "mere", "papa", "maman", "fils", "fille", "oncle", "tante", "cousin", "cousine",
    "grand", "grande", "grand-mere", "grand-pere", "mamie", "papi", "beau", "belle", "collegue", "patron",
    "patronne", "boss", "voisin", "voisine", "prof", "professeur", "professeure", "coach", "gerant", "gerante",
    "client", "cliente", "petit", "petite", "de", "du", "des", "d",
}


# Premiers mots qui montrent que le « nom » capté n'en est pas un (« quand je vois que… »).
_DEBUTS_IMPOSSIBLES = {"que", "qu", "si", "comment", "pourquoi", "ou", "quoi", "ca", "cela", "ceci", "il", "elle",
                       "ils", "elles", "on", "tout", "rien", "combien", "quel", "quelle"}


class RefusRappel(HTTPException):
    """Refus documenté : un HTTPException (les routes le laissent remonter) avec sa phrase à dire."""

    def __init__(self, statut: int, message: str, phrase: str | None = None):
        super().__init__(status_code=statut, detail=message)
        self.message = message
        self.phrase = phrase or message


# --------------------------------------------------------------------------- texte
def normaliser(texte: str) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces (même forme que listener.normalize)."""
    # « sœur » n'a pas de décomposition Unicode : sans ce remplacement, elle devient « sur ».
    brut = (texte or "").replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    brut = unicodedata.normalize("NFKD", brut).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", brut.lower()).strip()


def cles_personne(personne: str) -> list[str]:
    """Formes qui déclenchent le rappel : le nom complet, et le premier mot significatif (le prénom).

    « Marc Tremblay » -> ["marc tremblay", "marc"] ; « ma sœur Julie » -> ["ma soeur julie", "julie"] ;
    « mon patron » -> ["mon patron"] (aucun mot significatif : seul le groupe entier compte)."""
    complet = normaliser(personne)
    if not complet:
        return []
    cles = [complet]
    significatifs = [m for m in complet.split() if len(m) >= 2 and m not in _MOTS_RELATION]
    if significatifs and significatifs[0] != complet:
        cles.append(significatifs[0])
    return cles


def mentionne(texte_normalise: str, cles: list[str]) -> bool:
    """Le texte (déjà normalisé) contient-il l'une des clés en mots entiers ? « marcel » n'est pas « marc »."""
    enveloppe = f" {texte_normalise} "
    return any(f" {cle} " in enveloppe for cle in cles if cle)


# « si » est volontairement absent : « si je vois bien, rappelle-moi… » créerait un rappel pour « bien ».
_DEBUT = r"(?:la\s+prochaine\s+fois\s+(?:que\s+|qu')|quand\s+|lorsque\s+|lorsqu'|d[eè]s\s+que\s+|d[eè]s\s+qu')"
_JE = r"(?:je\s+|j')"
_VERBE = (
    r"(?:(?:suis|serai)\s+(?:avec|en\s+compagnie\s+de)"
    r"|(?:parle|parlerai|t[ée]l[ée]phone|t[ée]l[ée]phonerai|[ée]cris|[ée]crirai)\s+(?:à|a|avec|au)"
    r"|vois|verrai|revois|reverrai|croise|croiserai|rencontre|rencontrerai|appelle|appellerai"
    r"|texte|texterai|tombe\s+sur)"
)
_DEMANDE = (
    r"(?:rappelle[\s-]*moi|rappelles[\s-]*moi|tu\s+me\s+rappelles|dis[\s-]*moi|fais[\s-]*moi\s+penser"
    r"|fais[\s-]*moi\s+souvenir|pense\s+à\s+me\s+(?:rappeler|dire)|n'oublie\s+pas\s+de\s+me\s+(?:rappeler|dire))"
)
_LIAISON = r"(?:\s+(?:de\s+|d'|que\s+|qu'|à\s+|a\s+)|\s*[,:]\s*)?"
_FORME_A = re.compile(
    rf"^{_DEBUT}{_JE}{_VERBE}\s+(?P<personne>.+?)\s*[,;:]?\s+{_DEMANDE}{_LIAISON}\s*(?P<texte>.+)$", re.IGNORECASE
)
_FORME_B = re.compile(
    rf"^{_DEMANDE}{_LIAISON}\s*(?P<texte>.+?)\s*[,;:]?\s+{_DEBUT}{_JE}{_VERBE}\s+(?P<personne>.+?)$", re.IGNORECASE
)
_PRESENCE = re.compile(
    r"\b(?:je\s+suis\s+(?:avec|en\s+compagnie\s+de|chez)|je\s+parle\s+(?:à|a|avec)|je\s+vois|je\s+rencontre"
    r"|je\s+viens\s+de\s+(?:croiser|rencontrer|voir))\s+\S",
    re.IGNORECASE,
)
_APPEL_IRIS = re.compile(r"^\s*(?:dis[\s-]*moi\s+)?iris\s*[,:]?\s*", re.IGNORECASE)
_QUEUE_PERSONNE = re.compile(
    r"\s+(?:au\s+t[ée]l[ée]phone|par\s+t[ée]l[ée]phone|demain|ce\s+soir|aujourd'hui|cette\s+semaine"
    r"|la\s+semaine\s+prochaine|au\s+bureau|à\s+l'?[ée]cole)$",
    re.IGNORECASE,
)


def _simplifier(texte: str) -> str:
    texte = (texte or "").replace("’", "'").replace("‘", "'")
    texte = " ".join(texte.split())
    return _APPEL_IRIS.sub("", texte).strip()


def analyser_demande(texte: str) -> tuple[str, str] | None:
    """(personne, rappel) si la phrase CRÉE un rappel contextuel, sinon None (rapide).

    « La prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés » -> ("Marc", "Lui rendre ses clés").
    « Rappelle-moi de lui demander le devis quand je parle à Julie » -> ("Julie", "Lui demander le devis")."""
    simple = _simplifier(texte)
    if len(simple) < 12:
        return None
    t = simple.lower()
    # Garde rapide : pas de verbe de demande, pas de rappel. La plupart des phrases s'arrêtent ici.
    if not any(m in t for m in ("rappel", "dis-moi", "dis moi", "fais-moi", "fais moi", "pense à me", "oublie pas")):
        return None
    m = _FORME_A.match(simple) or _FORME_B.match(simple)
    if not m:
        return None
    personne = _QUEUE_PERSONNE.sub("", m.group("personne").strip(" ,;:.!?")).strip()
    rappel = m.group("texte").strip(" ,;:.!?").strip()
    if not personne or not rappel or len(personne.split()) > PERSONNE_MAX_MOTS or any(c.isdigit() for c in personne):
        return None
    mots_personne = normaliser(personne).split()
    if not mots_personne or mots_personne[0] in _DEBUTS_IMPOSSIBLES or not cles_personne(personne):
        return None  # « quand je vois que le colis arrive » ne nomme personne
    if simple == simple.lower() and mots_personne[0] not in ("le", "la", "les", "l", "un", "une"):
        # La reconnaissance vocale écrit tout en minuscules : « marc » s'affiche « Marc », « ma sœur » reste
        # tel quel, et « le dentiste » n'est pas un nom propre.
        personne = " ".join(
            m if normaliser(m) in _MOTS_RELATION else "-".join(p[:1].upper() + p[1:] for p in m.split("-"))
            for m in personne.split()
        )
    return personne[:PERSONNE_MAX], (rappel[0].upper() + rappel[1:])[:TEXTE_MAX]


def phrase_annonce(personne: str, texte: str) -> str:
    fin = "" if texte.rstrip().endswith((".", "!", "?")) else "."
    return f"Rappel pour {personne} : {texte}{fin}"


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _iso_local(valeur: str | None) -> str | None:
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return valeur


# --------------------------------------------------------------------------- service
class ServiceRappelsContexte:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._verrou = threading.RLock()
        # Rappels en attente, déchiffrés en mémoire vive : chaque phrase entendue est comparée à cette
        # liste sans toucher la base (les sous-titres produisent une phrase toutes les quelques secondes).
        self._attente: list[dict] = []
        for instruction in SCHEMA.split(";"):
            if instruction.strip():
                ctx.db.execute(instruction)
        self._recharger()

    # ------------------------------------------------------------------ utilitaires
    def _suspendue(self) -> str | None:
        memoire = getattr(self.ctx, "memory", None)
        return getattr(memoire, "suspendue", None) if memoire is not None else None

    def _dechiffrer(self, blob: Any) -> str:
        try:
            return self.ctx.crypto.decrypt(blob)
        except Exception:
            log.warning("rappel contextuel illisible (clé changée ?)")
            return ""

    def _public(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "personne": self._dechiffrer(row["personne_enc"]),
            "texte": self._dechiffrer(row["texte_enc"]),
            "cree_le": _iso_local(row["cree_le"]),
            "declenche_le": _iso_local(row.get("declenche_le")),
            "declencheur": row.get("declencheur"),
        }

    def _recharger(self) -> None:
        rows = self.ctx.db.query(
            "SELECT * FROM rappels_contexte WHERE declenche_le IS NULL ORDER BY cree_le ASC")
        attente = []
        for row in rows:
            public = self._public(row)
            cles = cles_personne(public["personne"])
            if cles and public["texte"]:
                attente.append({**public, "cles": cles, "cree_epoch": float(row["cree_epoch"])})
        with self._verrou:
            self._attente = attente

    def _retenu_jusqua(self, moment: datetime) -> str | None:
        jours = int(getattr(self.ctx.settings.user, "retention_days", 0) or 0)
        return _iso_utc(moment + timedelta(days=jours)) if jours > 0 else None

    def _publier(self, type_: str, **donnees: Any) -> None:
        try:
            self.ctx.hub.publish(type_, **donnees)
        except Exception as exc:  # pragma: no cover - un événement perdu ne doit pas casser un rappel
            log.warning("publication %s impossible : %s", type_, exc)

    # ------------------------------------------------------------------ lecture et écriture
    def liste(self) -> list[dict]:
        rows = self.ctx.db.query("SELECT * FROM rappels_contexte ORDER BY cree_le DESC")
        return [self._public(r) for r in rows]

    def en_attente(self) -> list[dict]:
        with self._verrou:
            return [{k: v for k, v in r.items() if k not in ("cles", "cree_epoch")} for r in self._attente]

    def creer(self, personne: str, texte: str, origine: str = "route") -> dict:
        """Crée un rappel. Lève RefusRappel 422 (vide) ou 409 (mémoire suspendue)."""
        personne = " ".join((personne or "").split()).strip(" ,;:.!?")[:PERSONNE_MAX]
        texte = " ".join((texte or "").split()).strip()[:TEXTE_MAX]
        if not personne or not cles_personne(personne):
            raise RefusRappel(422, "Précisez la personne (par exemple « Marc »).")
        if not texte:
            raise RefusRappel(422, "Précisez ce qu'il faut rappeler.")
        suspendue = self._suspendue()
        if suspendue:
            message = MEMOIRE_SUSPENDUE.format(raison=suspendue)
            raise RefusRappel(409, message, phrase="La mémoire est suspendue : je ne crée pas de rappel pour l'instant.")
        maintenant = datetime.now(timezone.utc)
        rid = uuid.uuid4().hex
        self.ctx.db.execute(
            "INSERT INTO rappels_contexte(id, cree_le, cree_epoch, personne_enc, texte_enc, origine, retenu_jusqua) "
            "VALUES(?,?,?,?,?,?,?)",
            (rid, _iso_utc(maintenant), time.time(), self.ctx.crypto.encrypt(personne),
             self.ctx.crypto.encrypt(texte), (origine or "route")[:20], self._retenu_jusqua(maintenant)),
        )
        self._recharger()
        rappel = self._public(self.ctx.db.one("SELECT * FROM rappels_contexte WHERE id=?", (rid,)))  # type: ignore[arg-type]
        # Le registre dit qu'un rappel existe, sans recopier la personne ni le texte.
        self.ctx.consent.log("rappel_contexte_cree", detail=f"origine : {origine}")
        self._publier("rappels_contexte.maj", en_attente=len(self._attente))
        return rappel

    def supprimer(self, rappel_id: str) -> bool:
        cur = self.ctx.db.execute("DELETE FROM rappels_contexte WHERE id=?", (rappel_id,))
        if cur.rowcount:
            self._recharger()
            self._publier("rappels_contexte.maj", en_attente=len(self._attente))
        return cur.rowcount > 0

    def purger(self) -> int:
        """Suppression physique au-delà de la rétention : date notée à l'écriture, puis durée actuelle."""
        maintenant = datetime.now(timezone.utc)
        n = max(0, self.ctx.db.execute(
            "DELETE FROM rappels_contexte WHERE retenu_jusqua IS NOT NULL AND retenu_jusqua < ?",
            (_iso_utc(maintenant),)).rowcount)
        jours = int(getattr(self.ctx.settings.user, "retention_days", 0) or 0)
        if jours > 0:
            n += max(0, self.ctx.db.execute(
                "DELETE FROM rappels_contexte WHERE cree_le < ?", (_iso_utc(maintenant - timedelta(days=jours)),)).rowcount)
        if n:
            self._recharger()
        return n

    # ------------------------------------------------------------------ déclenchement
    def _declenchement_possible(self) -> bool:
        if self._suspendue():
            return False
        return not bool(getattr(self.ctx.settings.user, "privacy_mode", False))

    def _declencher(self, rappel: dict, declencheur: str, annoncer: bool = True) -> dict | None:
        """Marque le rappel déclenché (une seule fois, même si deux sources arrivent ensemble), l'annonce."""
        with self._verrou:
            cur = self.ctx.db.execute(
                "UPDATE rappels_contexte SET declenche_le=?, declencheur=? WHERE id=? AND declenche_le IS NULL",
                (_iso_utc(datetime.now(timezone.utc)), declencheur, rappel["id"]),
            )
            self._attente = [r for r in self._attente if r["id"] != rappel["id"]]
        if not cur.rowcount:
            return None
        phrase = phrase_annonce(rappel["personne"], rappel["texte"])
        self._publier("rappel.contexte", id=rappel["id"], personne=rappel["personne"], texte=rappel["texte"],
                      declencheur=declencheur)
        self.ctx.consent.log("rappel_contexte_declenche", detail=DECLENCHEURS.get(declencheur, declencheur))
        if annoncer:
            tts = getattr(self.ctx, "tts", None)
            if tts is not None:
                try:
                    tts.speak(phrase)
                except Exception as exc:  # pragma: no cover - la voix ne doit jamais perdre le rappel
                    log.warning("annonce du rappel contextuel impossible : %s", exc)
        return {**{k: v for k, v in rappel.items() if k not in ("cles", "cree_epoch")},
                "declencheur": declencheur, "phrase": phrase}

    def verifier_texte(self, texte: str, declencheur: str, moment: float | None = None,
                       annoncer: bool = True) -> list[dict]:
        """Déclenche les rappels dont la personne est nommée dans `texte`. Renvoie ceux déclenchés."""
        with self._verrou:
            attente = list(self._attente)
        if not attente or not texte or not self._declenchement_possible():
            return []
        # La phrase qui crée un rappel nomme forcément la personne : elle ne doit pas le déclencher.
        if analyser_demande(texte) is not None:
            return []
        norme = normaliser(texte)
        moment = time.time() if moment is None else float(moment)
        declenches = []
        for rappel in attente:
            if moment <= rappel["cree_epoch"]:
                continue  # événement antérieur à la création (arrivé en retard dans la file)
            if declencheur == "sous_titres" and moment - rappel["cree_epoch"] < GRACE_SOUS_TITRES_S:
                continue
            if mentionne(norme, rappel["cles"]):
                fait = self._declencher(rappel, declencheur, annoncer=annoncer)
                if fait is not None:
                    declenches.append(fait)
        return declenches

    @staticmethod
    def _textes_evenement(evenement: dict, profondeur: int = 0) -> list[str]:
        """Textes lisibles d'un événement de message (courriel, téléphonie), sans les métadonnées."""
        textes: list[str] = []
        for cle, valeur in evenement.items():
            if cle in ("type", "ts", "id", "numero", "lien_ios", "lien_android", "reference"):
                continue
            if isinstance(valeur, str) and valeur.strip():
                textes.append(valeur)
            elif isinstance(valeur, dict) and profondeur < 2:
                textes.extend(ServiceRappelsContexte._textes_evenement(valeur, profondeur + 1))
        return textes

    def traiter_evenement(self, evenement: dict) -> list[dict]:
        """Examine un événement du hub. Rapide et sans effet pour tout ce qui ne porte pas de texte humain."""
        genre = str(evenement.get("type") or "")
        moment = evenement.get("ts")
        if genre == "ecoute.sous_titre":
            final = evenement.get("final")
            return self.verifier_texte(final, "sous_titres", moment) if isinstance(final, str) else []
        if genre == "voice.transcript":
            texte = evenement.get("text") or ""
            if not texte:
                return []
            declencheur = "presence" if _PRESENCE.search(_simplifier(texte)) else "commande_vocale"
            return self.verifier_texte(texte, declencheur, moment)
        if genre == "chat.user_message":
            message = evenement.get("message") or {}
            source = str((message.get("meta") or {}).get("source") or "")
            if source == "task":
                return []  # consigne de tâche de fond : personne n'est « rencontré »
            return self.verifier_texte(message.get("text") or "", "message_ecrit", moment)
        if genre == "telephone.sms_entrant":
            return self.verifier_texte(" ".join(self._textes_evenement(evenement)), "sms", moment)
        if genre == "telephone.brouillon":
            brouillon = evenement.get("brouillon") or {}
            texte = " ".join(str(brouillon.get(c) or "") for c in ("titre", "texte"))
            return self.verifier_texte(texte, "brouillon_message", moment)
        if genre.startswith("courriel."):
            return self.verifier_texte(" ".join(self._textes_evenement(evenement)), "courriel", moment)
        if genre.startswith("telephone.") and genre not in ("telephone.statut", "telephone.brouillon_ferme"):
            return self.verifier_texte(" ".join(self._textes_evenement(evenement)), "telephonie", moment)
        return []

    TYPES_SUIVIS = ("ecoute.sous_titre", "voice.transcript", "chat.user_message")
    PREFIXES_SUIVIS = ("telephone.", "courriel.")

    def concerne(self, evenement: dict) -> bool:
        genre = str(evenement.get("type") or "")
        return genre in self.TYPES_SUIVIS or genre.startswith(self.PREFIXES_SUIVIS)

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str) -> str | None:
        """Consultée par l'écoute pour chaque commande (priorité 50). None tout de suite si ce n'est pas pour nous."""
        demande = analyser_demande(texte)
        if demande is not None:
            personne, rappel = demande
            try:
                self.creer(personne, rappel, origine="voix")
            except RefusRappel as exc:
                return exc.phrase
            except Exception:
                log.exception("création vocale d'un rappel contextuel en erreur")
                return "Je n'ai pas réussi à noter ce rappel."
            if getattr(self.ctx.settings.user, "verbosite", "normal") == "concis":
                return f"C'est noté pour {personne}."
            return (f"C'est noté pour {personne} : {rappel[0].lower() + rappel[1:]}. Je te le dirai quand ce nom "
                    f"apparaîtra dans une commande, un message ou les sous-titres, ou quand tu me diras "
                    f"« je suis avec {personne} ».")
        # « Je suis avec Marc » : si un rappel attend Marc, IRIS le dit tout de suite, à la place du modèle.
        with self._verrou:
            attente = bool(self._attente)
        if not attente or not _PRESENCE.search(_simplifier(texte)):
            return None
        declenches = self.verifier_texte(texte, "presence", annoncer=False)
        if not declenches:
            return None
        return " ".join(d["phrase"] for d in declenches)

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("quotidien-rappels", self.interception, priorite=50)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("quotidien-rappels")
