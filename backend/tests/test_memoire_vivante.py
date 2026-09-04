"""Mémoire vivante : elle vient de ce qui a été dit, elle garde sa provenance, elle survit au redémarrage.

Le point capital vérifié ici : IRIS ne fabrique pas de souvenirs. Chaque ligne retenue est rattachée à la
phrase exacte prononcée par l'utilisateur, et rien n'est retenu quand rien n'a été énoncé.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iris.config import Settings
from iris.db import Database
from iris.memory import MemoryService
from iris.presence import Presence, humanize_gap
from iris.recall import doublon, extraire
from iris.security.crypto import Crypto


@pytest.fixture()
def memoire(data_dir: Path) -> MemoryService:
    settings = Settings(data_dir)
    db = Database(data_dir / "memoire.db")
    return MemoryService(db, Crypto(b"0" * 32), settings)


# --------------------------------------------------------------------------- extraction
@pytest.mark.parametrize(
    "phrase, attendu",
    [
        ("Souviens-toi que mon examen est mardi.", "mon examen est mardi"),
        ("Je m'appelle Miguel.", "Miguel"),
        ("J'habite à Trois-Rivières.", "à Trois-Rivières"),
        ("J'utilise Chrome comme navigateur principal.", "Chrome comme navigateur principal"),
        ("Je dois finir le plan financier avant vendredi.", "finir le plan financier avant vendredi"),
    ],
)
def test_extraction_de_faits_enonces(phrase, attendu):
    trouves = extraire(phrase)
    assert trouves and trouves[0]["fait"] == attendu
    # la phrase d'origine est conservée : c'est la preuve que le souvenir n'a pas été inventé
    assert trouves[0]["phrase"] == phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Quelle heure est-il ?",
        "Est-ce que tu peux ouvrir Google ?",
        "ouvre youtube et lance une video de mrbeast",
        "bonjour, souviens-toi de ça",  # aucune information : rien à retenir
        "retiens ce truc",
        "merci",
    ],
)
def test_rien_nest_invente(phrase):
    assert extraire(phrase) == [], f"souvenir inventé à partir de {phrase!r}"


def test_doublon_detecte_les_reformulations_identiques():
    assert doublon("mon examen est mardi", ["Mon examen est mardi."])
    assert not doublon("mon examen est mardi", ["j'habite à Trois-Rivières"])


# --------------------------------------------------------------------------- persistance
def test_capture_enregistre_la_provenance(memoire: MemoryService):
    ajoutes = memoire.capture("Souviens-toi que mon examen est mardi.", conversation_id="conv-1")
    assert len(ajoutes) == 1
    item = memoire.list()[0]
    assert item["text"] == "mon examen est mardi"
    assert item["source_text"] == "Souviens-toi que mon examen est mardi."
    assert item["conversation_id"] == "conv-1"
    assert item["kind"] == "consigne"


def test_capture_ne_duplique_pas(memoire: MemoryService):
    memoire.capture("Souviens-toi que mon examen est mardi.")
    memoire.capture("Souviens-toi que mon examen est mardi.")
    memoire.capture("Mon examen est mardi.")  # pas un motif de mémorisation
    assert memoire.count() == 1


def test_un_souvenir_utilise_remonte_dans_les_resultats(memoire: MemoryService):
    memoire.add("réunion fournisseur le jeudi", source="user")
    autre = memoire.add("réunion d'équipe le lundi", source="user")
    memoire.touch([autre["id"]])
    memoire.touch([autre["id"]])
    resultats = memoire.search("réunion")
    assert resultats[0]["id"] == autre["id"], "un souvenir déjà utile doit remonter"
    assert resultats[0]["uses"] == 2


def test_souvenir_epingle_prime(memoire: MemoryService):
    a = memoire.add("réunion fournisseur le jeudi", source="user")
    memoire.add("réunion d'équipe le lundi", source="user")
    memoire.pin(a["id"])
    assert memoire.search("réunion")[0]["id"] == a["id"]


def test_la_memoire_survit_a_un_redemarrage(data_dir: Path):
    """Une nouvelle instance sur le même fichier retrouve les souvenirs : ils vivent sur l'appareil."""
    settings = Settings(data_dir)
    cle = b"1" * 32
    Database(data_dir / "vie.db").close()
    m1 = MemoryService(Database(data_dir / "vie.db"), Crypto(cle), settings)
    m1.capture("Je m'appelle Miguel.")
    m1.db.close()

    m2 = MemoryService(Database(data_dir / "vie.db"), Crypto(cle), settings)
    assert [i["text"] for i in m2.list()] == ["Miguel"]
    assert m2.list()[0]["source_text"] == "Je m'appelle Miguel."


# --------------------------------------------------------------------------- présence
def test_presence_compte_les_sessions(data_dir: Path):
    db = Database(data_dir / "presence.db")
    p1 = Presence(db)
    p1.start_session()
    assert p1.info()["sessions"] == 1
    p2 = Presence(db)
    info = p2.start_session()
    assert info["sessions"] == 2
    assert info["device_name"]
    assert "installée sur l'ordinateur" in p2.context_line()


def test_presence_retient_le_dernier_echange(data_dir: Path):
    p = Presence(Database(data_dir / "presence2.db"))
    p.start_session()
    assert p.info()["last_interaction_ago"] == ""
    p.note_interaction("voice")
    assert p.info()["last_interaction_ago"] == "à l'instant"
    assert p.info()["interactions"] == 1


@pytest.mark.parametrize(
    "secondes, attendu",
    [(30, "à l'instant"), (600, "il y a 10 minutes"), (7200, "il y a 2 heures"), (86400, "hier"), (86400 * 5, "il y a 5 jours")],
)
def test_ecart_en_francais_parle(secondes, attendu):
    assert humanize_gap(secondes) == attendu
