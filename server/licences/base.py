"""Base SQLite du serveur de licences.

Trois tables :
  - abonnements   : un enregistrement par courriel (le plan actif, sa date de fin, son statut) ;
  - evenements    : chaque événement PayPal reçu, avec des contraintes d'unicité qui garantissent
                    l'idempotence (un même paiement ne peut jamais créditer deux fois) ;
  - manuel        : les paiements que le serveur n'a pas su interpréter, à traiter à la main.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("licences.base")

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


class Base:
    """Accès SQLite protégé par un verrou (uvicorn peut servir plusieurs requêtes à la fois)."""

    def __init__(self, chemin: Path | str):
        self.chemin = str(chemin)
        self._verrou = threading.Lock()
        besoin_dossier = self.chemin != ":memory:"
        if besoin_dossier:
            Path(self.chemin).parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(self.chemin, check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.executescript(SCHEMA)
        self.cx.commit()

    def fermer(self) -> None:
        try:
            self.cx.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ utilitaires
    def executer(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._verrou:
            cur = self.cx.execute(sql, params)
            self.cx.commit()
            return cur

    def un(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._verrou:
            return self.cx.execute(sql, params).fetchone()

    def tous(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._verrou:
            return self.cx.execute(sql, params).fetchall()

    # ------------------------------------------------------------------ idempotence
    def reserver_evenement(self, evenement_id: str | None, transaction_id: str | None,
                           type_evenement: str) -> int | None:
        """Pose l'événement en base **avant** tout crédit. Renvoie son identifiant, ou None
        s'il a déjà été traité.

        C'est le cœur de l'idempotence, et c'est volontairement une écriture et non une lecture :
        la contrainte UNIQUE de SQLite tranche en une seule opération atomique. Un « SELECT puis
        INSERT » laisserait deux webhooks simultanés créditer deux fois le même paiement.

        Sans identifiant exploitable (les deux à NULL), SQLite considère les NULL comme distincts :
        l'insertion réussit, rien n'est dédupliqué — c'est le comportement voulu, faute de mieux.
        """
        try:
            cur = self.executer(
                "INSERT INTO evenements(evenement_id, transaction_id, type, resultat, recu_le) VALUES(?,?,?,?,?)",
                (evenement_id or None, transaction_id or None, type_evenement or "inconnu", "en_cours", maintenant()),
            )
            return int(cur.lastrowid or 0)
        except sqlite3.IntegrityError:
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
        cur = self.executer(
            "INSERT INTO manuel(courriel, montant, devise, transaction_id, raison, cree_le) VALUES(?,?,?,?,?,?)",
            (normaliser(courriel or ""), montant, devise, transaction_id, raison, maintenant()),
        )
        return int(cur.lastrowid or 0)

    def manuels(self, seulement_ouverts: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM manuel"
        if seulement_ouverts:
            sql += " WHERE resolu=0"
        return self.tous(sql + " ORDER BY id DESC LIMIT 200")


def normaliser(courriel: str) -> str:
    """Un courriel = une clé de compte : minuscules, sans espaces autour."""
    return (courriel or "").strip().lower()
