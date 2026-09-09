"""Base du serveur de licences.

Par défaut, tout se passe sur **SQLite**, exactement comme avant : le développement et les tests
ne changent pas d'un iota. En **production**, si la variable d'environnement ``DATABASE_URL``
désigne une base Postgres (« postgresql://... » ou « postgres://... », typiquement Neon ou
Supabase), le même code parle à Postgres via psycopg (v3). L'API publique de la classe ``Base``
est rigoureusement identique dans les deux cas : service.py, app.py et cles.py n'ont rien à
changer, et les lignes renvoyées restent accessibles par nom de colonne (``ligne["colonne"]``).

Trois tables :
  - abonnements   : un enregistrement par courriel (le plan actif, sa date de fin, son statut) ;
  - evenements    : chaque événement PayPal reçu, avec des contraintes d'unicité qui garantissent
                    l'idempotence (un même paiement ne peut jamais créditer deux fois) ;
  - manuel        : les paiements que le serveur n'a pas su interpréter, à traiter à la main.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("licences.base")

# Schéma de référence, écrit en dialecte SQLite. Le chemin Postgres le traduit à la volée
# (voir _creer_schema_postgres) : c'est la seule et unique définition des tables.
SCHEMA = """
CREATE TABLE IF NOT EXISTS abonnements (
    courriel        TEXT PRIMARY KEY,          -- normalisé en minuscules
    plan            TEXT NOT NULL,
    expire_le       TEXT NOT NULL,             -- AAAA-MM-JJ
    statut          TEXT NOT NULL,             -- actif | annule | expire | paiement_echoue
    abonnement_paypal TEXT,                    -- identifiant d'abonnement PayPal (I-XXXX), si applicable
    derniere_cle    TEXT,
    cree_le         TEXT NOT NULL,
    maj_le          TEXT NOT NULL,
    note            TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS evenements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evenement_id    TEXT UNIQUE,               -- id de l'événement PayPal (rejeu des relances)
    transaction_id  TEXT UNIQUE,               -- id de la ressource (capture/abonnement) : idempotence du crédit
    type            TEXT NOT NULL,
    courriel        TEXT,
    montant         REAL,
    devise          TEXT,
    plan            TEXT,
    resultat        TEXT NOT NULL,             -- active | prolonge | annule | expire | echec_paiement | manuel | ignore
    recu_le         TEXT NOT NULL,
    detail          TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS manuel (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    courriel        TEXT,
    montant         REAL,
    devise          TEXT,
    transaction_id  TEXT,
    raison          TEXT NOT NULL,
    cree_le         TEXT NOT NULL,
    resolu          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_evenements_courriel ON evenements(courriel);
CREATE INDEX IF NOT EXISTS idx_abonnements_paypal  ON abonnements(abonnement_paypal);
"""


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _url_postgres() -> str | None:
    """Renvoie l'URL Postgres si DATABASE_URL en désigne une, sinon None (→ SQLite).

    C'est le seul aiguillage : DATABASE_URL absente → SQLite comme aujourd'hui ; présente et
    pointant vers Postgres → backend Postgres. On accepte les deux préfixes usuels.
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return url
    return None


class Base:
    """Accès à la base protégé par un verrou (uvicorn peut servir plusieurs requêtes à la fois).

    Deux backends possibles, choisis une fois pour toutes à la construction :
      - SQLite (par défaut) : identique à la version historique, verrou + commit par écriture ;
      - Postgres (si DATABASE_URL) : psycopg v3, lignes en dictionnaires, reconnexion automatique.
    """

    def __init__(self, chemin: Path | str):
        self.chemin = str(chemin)
        self._verrou = threading.Lock()
        self._url = _url_postgres()
        self._postgres = self._url is not None
        if self._postgres:
            self._init_postgres()
        else:
            self._init_sqlite()

    # ------------------------------------------------------------------ mise en route SQLite
    def _init_sqlite(self) -> None:
        besoin_dossier = self.chemin != ":memory:"
        if besoin_dossier:
            Path(self.chemin).parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(self.chemin, check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.executescript(SCHEMA)
        self.cx.commit()
        # Familles d'erreurs pour la couche commune. SQLite ne « perd » jamais sa connexion :
        # le tuple vide fait que la reconnexion ne se déclenche jamais.
        self._erreurs_connexion: tuple = ()
        self._erreurs_integrite: tuple = (sqlite3.IntegrityError,)

    # ------------------------------------------------------------------ mise en route Postgres
    def _init_postgres(self) -> None:
        # Import volontairement tardif : psycopg n'est requis qu'en production Postgres, si bien
        # que « import licences.base » et tout le dev/tests SQLite fonctionnent sans l'installer.
        import psycopg
        from psycopg import errors as erreurs_pg
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self._dict_row = dict_row
        # Une coupure de connexion se manifeste par OperationalError ou InterfaceError.
        self._erreurs_connexion = (psycopg.OperationalError, psycopg.InterfaceError)
        # Violation d'unicité : UniqueViolation (sous-classe d'IntegrityError) côté psycopg.
        self._erreurs_integrite = (erreurs_pg.UniqueViolation, psycopg.IntegrityError)
        self._brancher_postgres()
        self._creer_schema_postgres()

    def _brancher_postgres(self) -> None:
        """(Re)ouvre la connexion Postgres.

        autocommit=True valide chaque requête immédiatement — l'équivalent du « commit par
        écriture » du chemin SQLite — et garantit qu'une erreur (ex. violation d'unicité) ne
        laisse jamais la connexion dans un état de transaction avortée. Les lignes sortent en
        dictionnaires (dict_row) pour rester accessibles par nom de colonne, comme sqlite3.Row.
        """
        self.cx = self._psycopg.connect(self._url, autocommit=True, row_factory=self._dict_row)

    def _creer_schema_postgres(self) -> None:
        """Crée tables et index un par un (Postgres n'a pas d'executescript), en traduisant le
        dialecte : « INTEGER PRIMARY KEY AUTOINCREMENT » → « BIGSERIAL PRIMARY KEY », « REAL »
        → « DOUBLE PRECISION » ; TEXT est commun aux deux."""
        schema = (
            SCHEMA
            .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            .replace("REAL", "DOUBLE PRECISION")
        )
        for instruction in schema.split(";"):
            if instruction.strip():
                self.cx.execute(instruction)

    def fermer(self) -> None:
        try:
            self.cx.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ couche commune
    def _traduire(self, sql: str) -> str:
        """Postgres attend « %s » là où le code écrit « ? ». Le « ? » ne sert QUE de paramètre
        dans tout ce module : la substitution est donc sûre. Sur SQLite, on ne touche à rien."""
        return sql.replace("?", "%s") if self._postgres else sql

    def _lancer(self, sql: str, params: tuple, *, recuperer: str):
        """Cœur d'exécution partagé par les deux backends.

        recuperer ∈ {"curseur", "un", "tous", "id"} — dicte ce qu'on renvoie et si l'on valide.
        Sur Postgres, si la connexion a été fermée (Neon/Supabase coupent les connexions
        inactives), on se rebranche et on réessaie **une seule fois**. Sur SQLite, la liste
        d'erreurs de connexion est vide : le comportement est strictement celui d'avant.
        """
        sql_final = self._traduire(sql)
        with self._verrou:
            try:
                return self._executer_une_fois(sql_final, params, recuperer)
            except self._erreurs_connexion as exc:
                log.warning("Connexion à la base perdue (%s) : reconnexion et nouvel essai.", exc)
                self._brancher_postgres()
                return self._executer_une_fois(sql_final, params, recuperer)

    def _executer_une_fois(self, sql: str, params: tuple, recuperer: str):
        """Une passe d'exécution (sans gestion de reconnexion). En cas d'erreur sur Postgres,
        on annule la transaction avortée avant de propager, pour que la connexion reste utilisable."""
        try:
            if recuperer == "id" and self._postgres:
                # Postgres ne fournit pas de lastrowid : on récupère l'id engendré via RETURNING.
                cur = self.cx.execute(sql + " RETURNING id", params)
                ligne = cur.fetchone()
                resultat = int(ligne["id"]) if ligne else 0
            else:
                cur = self.cx.execute(sql, params)
                if recuperer == "un":
                    resultat = cur.fetchone()
                elif recuperer == "tous":
                    resultat = cur.fetchall()
                elif recuperer == "id":            # SQLite : l'id vient de lastrowid
                    resultat = int(cur.lastrowid or 0)
                else:                              # "curseur" : on rend le curseur tel quel
                    resultat = cur
            # Validation : sur SQLite, aux mêmes endroits qu'avant (écritures : executer + inserts
            # avec id) ; sur Postgres, autocommit a déjà tout validé.
            if not self._postgres and recuperer in ("curseur", "id"):
                self.cx.commit()
            return resultat
        except Exception:
            if self._postgres:
                try:
                    self.cx.rollback()
                except Exception:
                    pass
            raise

    # ------------------------------------------------------------------ utilitaires
    def executer(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._lancer(sql, params, recuperer="curseur")

    def un(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._lancer(sql, params, recuperer="un")

    def tous(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._lancer(sql, params, recuperer="tous")

    def _inserer_avec_id(self, sql: str, params: tuple) -> int:
        """INSERT dont on a besoin de l'identifiant engendré, quel que soit le backend
        (lastrowid sur SQLite, RETURNING id sur Postgres)."""
        return self._lancer(sql, params, recuperer="id")

    # ------------------------------------------------------------------ idempotence
    def reserver_evenement(self, evenement_id: str | None, transaction_id: str | None,
                           type_evenement: str) -> int | None:
        """Pose l'événement en base **avant** tout crédit. Renvoie son identifiant, ou None
        s'il a déjà été traité.

        C'est le cœur de l'idempotence, et c'est volontairement une écriture et non une lecture :
        la contrainte UNIQUE tranche en une seule opération atomique. Un « SELECT puis INSERT »
        laisserait deux webhooks simultanés créditer deux fois le même paiement.

        Sans identifiant exploitable (les deux à NULL), SQLite comme Postgres considèrent les
        NULL comme distincts : l'insertion réussit, rien n'est dédupliqué — c'est le comportement
        voulu, faute de mieux.
        """
        try:
            return self._inserer_avec_id(
                "INSERT INTO evenements(evenement_id, transaction_id, type, resultat, recu_le) VALUES(?,?,?,?,?)",
                (evenement_id or None, transaction_id or None, type_evenement or "inconnu", "en_cours", maintenant()),
            )
        except self._erreurs_integrite:
            log.info("Événement déjà reçu, ignoré (evenement=%s transaction=%s).", evenement_id, transaction_id)
            return None

    def liberer_evenement(self, identifiant: int) -> None:
        """Retire une réservation après un échec inattendu, pour que la relance de PayPal serve."""
        self.executer("DELETE FROM evenements WHERE id=?", (identifiant,))

    def conclure_evenement(
        self,
        identifiant: int,
        *,
        courriel: str | None = None,
        montant: float | None = None,
        devise: str | None = None,
        plan: str | None = None,
        resultat: str = "ignore",
        detail: str = "",
    ) -> None:
        """Complète la ligne réservée avec le résultat du traitement."""
        self.executer(
            "UPDATE evenements SET courriel=?, montant=?, devise=?, plan=?, resultat=?, detail=? WHERE id=?",
            (courriel, montant, devise, plan, resultat, detail, identifiant),
        )

    # ------------------------------------------------------------------ abonnements
    def abonnement(self, courriel: str) -> sqlite3.Row | None:
        return self.un("SELECT * FROM abonnements WHERE courriel=?", (normaliser(courriel),))

    def abonnement_par_paypal(self, abonnement_paypal: str) -> sqlite3.Row | None:
        if not abonnement_paypal:
            return None
        return self.un("SELECT * FROM abonnements WHERE abonnement_paypal=?", (abonnement_paypal,))

    def enregistrer_abonnement(
        self,
        courriel: str,
        plan: str,
        expire_le: str,
        statut: str = "actif",
        abonnement_paypal: str | None = None,
        derniere_cle: str | None = None,
        note: str = "",
    ) -> None:
        courriel = normaliser(courriel)
        ts = maintenant()
        # Upsert compatible SQLite ET Postgres : la cible ON CONFLICT(courriel) s'appuie sur la clé
        # primaire, « excluded » (insensible à la casse des deux côtés) désigne la ligne proposée,
        # et « abonnements.x » désigne la ligne existante — syntaxe valable pour les deux moteurs.
        self.executer(
            "INSERT INTO abonnements(courriel, plan, expire_le, statut, abonnement_paypal, derniere_cle, cree_le, maj_le, note) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(courriel) DO UPDATE SET plan=excluded.plan, expire_le=excluded.expire_le, "
            "  statut=excluded.statut, "
            "  abonnement_paypal=COALESCE(excluded.abonnement_paypal, abonnements.abonnement_paypal), "
            "  derniere_cle=COALESCE(excluded.derniere_cle, abonnements.derniere_cle), "
            "  maj_le=excluded.maj_le, note=excluded.note",
            (courriel, plan, expire_le, statut, abonnement_paypal, derniere_cle, ts, ts, note),
        )

    def changer_statut(self, courriel: str, statut: str, note: str = "") -> bool:
        cur = self.executer(
            "UPDATE abonnements SET statut=?, maj_le=?, note=? WHERE courriel=?",
            (statut, maintenant(), note, normaliser(courriel)),
        )
        return cur.rowcount > 0

    # ------------------------------------------------------------------ à traiter manuellement
    def ajouter_manuel(self, courriel: str | None, montant: float | None, devise: str | None,
                       transaction_id: str | None, raison: str) -> int:
        return self._inserer_avec_id(
            "INSERT INTO manuel(courriel, montant, devise, transaction_id, raison, cree_le) VALUES(?,?,?,?,?,?)",
            (normaliser(courriel or ""), montant, devise, transaction_id, raison, maintenant()),
        )

    def manuels(self, seulement_ouverts: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM manuel"
        if seulement_ouverts:
            sql += " WHERE resolu=0"
        return self.tous(sql + " ORDER BY id DESC LIMIT 200")


def normaliser(courriel: str) -> str:
    """Un courriel = une clé de compte : minuscules, sans espaces autour."""
    return (courriel or "").strip().lower()
