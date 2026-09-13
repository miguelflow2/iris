"""Journal d'écoute : ce qui a été entendu, mot pour mot, chiffré sur l'appareil.

« Qu'est-ce que Marc a dit mardi à propos du devis ? » Le journal garde les phrases finales des
sous-titres (quand l'utilisateur a activé le journal continu) et celles qu'on lui confie
explicitement. Comme la mémoire, il n'est PAS génératif : aucune ligne n'est reformulée par un
modèle, la recherche se fait localement par mots communs, et chaque entrée garde sa date et sa source.

Trois règles non négociables :
- rien n'est écrit quand la mémoire est suspendue (mode invité, zone sans mémoire) ;
- tout est chiffré (ctx.crypto) avant d'entrer dans la base ;
- la rétention (settings.user.retention_days) s'applique : les entrées trop vieilles sont
  physiquement supprimées par `purger`, appelée périodiquement par routes_ecoute.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger("iris.journal")

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_ecoute (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    texte_enc BLOB NOT NULL,
    source TEXT NOT NULL DEFAULT 'sous-titres',
    retenu_jusqua TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_ecoute_ts ON journal_ecoute(ts);
"""

# Une recherche déchiffre les entrées de la plage demandée. Au-delà de ce plafond (plusieurs
# semaines de journal continu), on ne regarde que les plus récentes : une recherche qui fige
# l'interface dix secondes n'aide personne, et une plage de dates règle le cas des vieilles phrases.
PLAFOND_RECHERCHE = 20000
LONGUEUR_MAX = 2000  # une « phrase » de sous-titres plus longue est tronquée : c'est un bruit de décodage

_MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "en", "au", "aux", "ce", "ca", "cet",
    "cette", "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "est", "sont", "pour", "dans",
    "sur", "que", "qui", "quoi", "pas", "ne", "se", "sa", "son", "ses", "mon", "ma", "mes", "ton", "ta",
    "tes", "a", "y", "avec", "par", "plus", "the", "an", "of", "to", "in", "is", "it", "and", "or",
    "dit", "quand", "quel", "quelle", "est-ce", "moi", "toi", "lui",
}


def creer_tables(db, schema: str) -> None:
    """Crée les tables d'un module sans toucher au schéma central de db.py (un module = ses tables)."""
    for instruction in schema.split(";"):
        if instruction.strip():
            db.execute(instruction)


def sans_accents(texte: str) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces : « Rendez-vous » == « rendez vous »."""
    brut = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", brut.lower()).strip()


def mots(texte: str) -> set[str]:
    return {m for m in sans_accents(texte).split() if len(m) >= 2 and m not in _MOTS_VIDES}


def maintenant_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(moment: datetime) -> str:
    """Format de stockage : UTC, microsecondes, toujours la même longueur — les chaînes se comparent donc
    dans l'ordre chronologique, ce qui permet de filtrer une plage directement en SQL."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def iso_local(valeur: str) -> str:
    """UTC stocké -> heure locale de l'ordinateur avec son fuseau, pour l'affichage."""
    try:
        return datetime.fromisoformat(valeur).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return valeur


def bornes_utc(debut: str | None, fin: str | None) -> tuple[str | None, str | None, bool]:
    """(bas, haut, haut_inclusif) en UTC de stockage, depuis des bornes ISO saisies par l'utilisateur.

    Sans fuseau, une borne est en heure locale de l'ordinateur. Une date seule en `fin` couvre la
    journée entière (borne exclusive au lendemain minuit) ; une fin horodatée est inclusive.
    Lève ValueError sur une date illisible."""

    def lire(valeur: str) -> datetime:
        try:
            moment = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"date invalide : {valeur} (format attendu AAAA-MM-JJ ou AAAA-MM-JJTHH:MM)")
        return moment.astimezone() if moment.tzinfo is None else moment

    bas = haut = None
    inclusif = True
    texte_debut = (debut or "").strip()
    texte_fin = (fin or "").strip()
    if texte_debut:
        bas = iso_utc(lire(texte_debut))
    if texte_fin:
        moment = lire(texte_fin)
        if len(texte_fin) == 10:
            moment += timedelta(days=1)
            inclusif = False
        haut = iso_utc(moment)
    return bas, haut, inclusif


class JournalEcoute:
    def __init__(self, db, crypto, settings, memory=None):
        self.db = db
        self.crypto = crypto
        self.settings = settings
        self.memory = memory
        self.ignorees_suspension = 0  # phrases NON écrites parce que la mémoire était suspendue
        creer_tables(db, SCHEMA)

    # ------------------------------------------------------------------ écriture
    def suspendu(self) -> str | None:
        return getattr(self.memory, "suspendue", None) if self.memory is not None else None

    def _retenu_jusqua(self, moment: datetime) -> str | None:
        jours = int(getattr(self.settings.user, "retention_days", 0) or 0)
        return iso_utc(moment + timedelta(days=jours)) if jours > 0 else None

    def ajouter(self, texte: str, source: str = "sous-titres", moment: datetime | None = None) -> dict | None:
        """Ajoute une phrase. Renvoie l'entrée écrite, ou None si rien n'a été écrit (texte vide, mémoire
        suspendue). Ne lève jamais pour une mémoire suspendue : les sous-titres continuent de s'afficher,
        c'est seulement la trace qui n'est pas gardée."""
        texte = (texte or "").strip()[:LONGUEUR_MAX]
        if not texte:
            return None
        if self.suspendu():
            self.ignorees_suspension += 1
            return None
        moment = moment or maintenant_utc()
        entree = {"id": uuid.uuid4().hex, "ts": iso_utc(moment), "source": (source or "sous-titres")[:40]}
        self.db.execute(
            "INSERT INTO journal_ecoute(id, ts, texte_enc, source, retenu_jusqua) VALUES(?,?,?,?,?)",
            (entree["id"], entree["ts"], self.crypto.encrypt(texte), entree["source"], self._retenu_jusqua(moment)),
        )
        return {**entree, "ts": iso_local(entree["ts"]), "texte": texte}

    # ------------------------------------------------------------------ lecture
    def _lignes(self, debut: str | None, fin: str | None, plafond: int) -> list[dict]:
        bas, haut, inclusif = bornes_utc(debut, fin)
        conditions: list[str] = []
        params: list = []
        if bas:
            conditions.append("ts >= ?")
            params.append(bas)
        if haut:
            conditions.append("ts <= ?" if inclusif else "ts < ?")
            params.append(haut)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(int(plafond))
        rows = self.db.query(f"SELECT * FROM journal_ecoute {where} ORDER BY ts DESC LIMIT ?", params)
        sortie = []
        for r in rows:
            try:
                texte = self.crypto.decrypt(r["texte_enc"])
            except Exception:  # une ligne illisible (clé changée) ne doit pas masquer les autres
                log.warning("entrée de journal illisible ignorée : %s", r["id"])
                continue
            sortie.append({"id": r["id"], "ts": iso_local(r["ts"]), "texte": texte, "source": r["source"]})
        return sortie

    def chercher(self, question: str | None, debut: str | None = None, fin: str | None = None, limit: int = 20) -> list[dict]:
        """Entrées les plus proches de la question, par mots communs (sans accents, sans mots vides).

        Sans question, les entrées les plus récentes de la plage. Un mot de cinq lettres ou plus
        compte aussi s'il partage son début avec un mot entendu (« devis » / « devise » : tant pis,
        « facturation » / « facture » : tant mieux). Lève ValueError sur une date illisible."""
        limit = max(1, min(int(limit or 20), 500))
        cherches = mots(question or "")
        if not cherches:
            return self._lignes(debut, fin, limit)
        resultats: list[tuple[float, dict]] = []
        for entree in self._lignes(debut, fin, PLAFOND_RECHERCHE):
            presents = mots(entree["texte"])
            if not presents:
                continue
            communs = cherches & presents
            if not communs:
                communs = {c for c in cherches if len(c) >= 5 and any(p.startswith(c[:5]) for p in presents)}
            if communs:
                score = len(communs) / len(cherches) + 0.1 * len(communs) / len(presents)
                resultats.append((score, entree))
        # plus pertinent d'abord ; à pertinence égale, le plus récent (tri stable sur une liste déjà récente d'abord)
        resultats.sort(key=lambda s: -s[0])
        return [{**e, "score": round(s, 3)} for s, e in resultats[:limit]]

    def compter(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM journal_ecoute")
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ effacement
    def supprimer_plage(self, debut: str | None, fin: str | None, tout: bool = False) -> int:
        """Efface les entrées de la plage. Sans borne, il faut `tout=True` : un oubli de paramètre ne doit
        jamais effacer le journal entier. Lève ValueError sur une date illisible ou une plage absente."""
        bas, haut, inclusif = bornes_utc(debut, fin)
        if not bas and not haut:
            if not tout:
                raise ValueError("précisez debut ou fin (ou tout=true pour effacer tout le journal)")
            cur = self.db.execute("DELETE FROM journal_ecoute")
            return max(0, cur.rowcount)
        conditions: list[str] = []
        params: list = []
        if bas:
            conditions.append("ts >= ?")
            params.append(bas)
        if haut:
            conditions.append("ts <= ?" if inclusif else "ts < ?")
            params.append(haut)
        cur = self.db.execute(f"DELETE FROM journal_ecoute WHERE {' AND '.join(conditions)}", params)
        return max(0, cur.rowcount)

    def purger(self) -> int:
        """Suppression physique de ce qui a dépassé la rétention. Deux règles, parce que la rétention
        peut avoir été raccourcie après l'écriture : la date d'expiration notée à l'écriture, et la
        durée ACTUELLE appliquée à la date de chaque entrée."""
        maintenant = maintenant_utc()
        supprimees = max(0, self.db.execute(
            "DELETE FROM journal_ecoute WHERE retenu_jusqua IS NOT NULL AND retenu_jusqua < ?", (iso_utc(maintenant),)
        ).rowcount)
        jours = int(getattr(self.settings.user, "retention_days", 0) or 0)
        if jours > 0:
            limite = iso_utc(maintenant - timedelta(days=jours))
            supprimees += max(0, self.db.execute("DELETE FROM journal_ecoute WHERE ts < ?", (limite,)).rowcount)
        return supprimees
