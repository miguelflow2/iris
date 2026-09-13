"""Journal d'écoute (interface C) et effacement de la mémoire par plage.

Prouvé ici : recherche par mots communs sans accents, plages ISO (heure locale, date seule = journée
entière), chiffrement au repos, rien d'écrit en mémoire suspendue, rétention, routes, et
MemoryService.supprimer_plage.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from iris.config import Settings
from iris.db import Database
from iris.journal import JournalEcoute, bornes_utc
from iris.memory import MemoryService
from iris.security.crypto import Crypto


@pytest.fixture()
def pile(tmp_path):
    settings = Settings(tmp_path)
    db = Database(tmp_path / "iris.db")
    crypto = Crypto(os.urandom(32))
    memoire = MemoryService(db, crypto, settings)
    yield JournalEcoute(db, crypto, settings, memory=memoire), memoire, db, settings
    db.close()


def local(annee, mois, jour, heure=12, minute=0):
    """Un moment en heure locale de l'ordinateur (c'est ce que l'utilisateur tape dans une plage)."""
    return datetime(annee, mois, jour, heure, minute).astimezone()


def test_recherche_sans_accents_et_chiffrement_au_repos(pile):
    journal, _m, db, _s = pile
    journal.ajouter("Rendez-vous chez le médecin jeudi à dix heures", "sous-titres", local(2026, 9, 10, 9))
    journal.ajouter("Marc a envoyé le devis pour la toiture", "sous-titres", local(2026, 9, 11, 14))
    journal.ajouter("On se voit à la cabane", "manuel", local(2026, 9, 12, 20))
    trouves = journal.chercher("quand est mon rendez vous medecin")
    assert trouves and trouves[0]["texte"].startswith("Rendez-vous chez le médecin")
    assert journal.chercher("DEVIS toiture")[0]["texte"].startswith("Marc")
    assert journal.chercher("facturation") == []
    recents = journal.chercher(None, limit=2)
    assert [e["source"] for e in recents] == ["manuel", "sous-titres"]
    brut = db.query("SELECT texte_enc FROM journal_ecoute")
    assert all(b"devis" not in bytes(r["texte_enc"]) for r in brut), "le texte doit être chiffré"


def test_plages_iso_et_effacement(pile):
    journal, _m, _db, _s = pile
    for jour in (10, 11, 12):
        journal.ajouter(f"note du {jour} septembre", "manuel", local(2026, 9, jour, 23, 30))
    # Date seule en fin : toute la journée, jusqu'à 23 h 59 comprise.
    assert len(journal.chercher(None, debut="2026-09-11", fin="2026-09-11")) == 1
    assert len(journal.chercher("note", debut="2026-09-11")) == 2
    assert len(journal.chercher("note", fin="2026-09-11T12:00")) == 1
    with pytest.raises(ValueError):
        journal.chercher("note", debut="hier")
    with pytest.raises(ValueError):
        journal.supprimer_plage(None, None)
    assert journal.supprimer_plage("2026-09-11", "2026-09-12") == 2
    assert [e["texte"] for e in journal.chercher(None)] == ["note du 10 septembre"]
    assert journal.supprimer_plage(None, None, tout=True) == 1 and journal.compter() == 0


def test_bornes_utc_heure_locale_et_fuseau_explicite():
    bas, haut, inclusif = bornes_utc("2026-09-13T08:00:00+00:00", "2026-09-13")
    assert bas.startswith("2026-09-13T08:00:00") and not inclusif
    attendu = (datetime(2026, 9, 14).astimezone()).astimezone(timezone.utc)
    assert haut == attendu.isoformat(timespec="microseconds")


def test_rien_nest_ecrit_quand_la_memoire_est_suspendue(pile):
    journal, memoire, _db, _s = pile
    memoire.suspendre("invite")
    assert journal.ajouter("mon code de porte est 4321") is None
    assert journal.compter() == 0 and journal.ignorees_suspension == 1
    memoire.reprendre("invite")
    assert journal.ajouter("une phrase ordinaire")["texte"] == "une phrase ordinaire"
    assert journal.compter() == 1


def test_retention_purge_les_vieilles_entrees(pile):
    journal, _m, _db, settings = pile
    maintenant = datetime.now(timezone.utc)
    journal.ajouter("vieille phrase", moment=maintenant - timedelta(days=40))
    journal.ajouter("phrase récente", moment=maintenant - timedelta(hours=1))
    assert journal.purger() == 0, "rétention illimitée par défaut"
    settings.user.retention_days = 30
    assert journal.purger() == 1
    assert [e["texte"] for e in journal.chercher(None)] == ["phrase récente"]


def test_memoire_supprimer_plage(pile):
    _j, memoire, db, _s = pile
    for texte, quand in (("avant", "2026-09-01T12:00:00+00:00"), ("pendant", "2026-09-05T12:00:00+00:00"),
                         ("après", "2026-09-09T12:00:00+00:00")):
        item = memoire.add(texte, pinned=texte == "pendant")
        db.execute("UPDATE memories SET created_at=? WHERE id=?", (quand, item["id"]))
    with pytest.raises(ValueError):
        memoire.supprimer_plage(None, "")
    with pytest.raises(ValueError):
        memoire.supprimer_plage("n'importe quoi", None)
    assert memoire.supprimer_plage("2026-09-04", "2026-09-06") == 1, "épinglé compris : la demande porte sur la période"
    assert sorted(m["text"] for m in memoire.list()) == ["après", "avant"]
    assert memoire.supprimer_plage("2026-09-09T12:00:00+00:00", None) == 1


def test_routes_du_journal_et_de_la_memoire(client, app):
    ctx = app.state.ctx
    ctx.journal.ajouter("La réunion budget est déplacée à mardi", "sous-titres")
    corps = client.get("/api/journal", params={"q": "reunion budget"}).json()
    assert corps["entrees"][0]["texte"].startswith("La réunion budget")
    assert set(corps["entrees"][0]) >= {"id", "ts", "texte", "source"}
    assert client.get("/api/journal", params={"debut": "pas une date"}).status_code == 422
    assert client.delete("/api/journal").status_code == 422, "une plage absente n'efface pas tout"
    aujourdhui = datetime.now().date().isoformat()
    assert client.delete("/api/journal", params={"debut": aujourdhui, "fin": aujourdhui}).json() == {"supprimees": 1}
    ctx.memory.add("souvenir d'aujourd'hui")
    r = client.delete("/api/ecoute/memoire/plage", params={"debut": aujourdhui})
    assert r.status_code == 200 and r.json() == {"supprimes": 1}
    assert client.delete("/api/ecoute/memoire/plage").status_code == 422


@pytest.mark.xfail(strict=False, reason="main.py déclare DELETE /api/memory/{memory_id} avant ce routeur : "
                                         "« plage » y est pris pour un identifiant (demande faite à la fondation)")
def test_chemin_du_contrat_pour_la_memoire_par_plage(client, app):
    app.state.ctx.memory.add("souvenir à effacer")
    r = client.delete("/api/memory/plage", params={"debut": datetime.now().date().isoformat()})
    assert r.json() == {"supprimes": 1}
