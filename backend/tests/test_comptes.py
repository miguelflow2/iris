"""Compte et authentification : c'est ce qui protège l'ordinateur d'un accès depuis le réseau.

IRIS exécute des commandes. Ces tests vérifient qu'un mot de passe est réellement exigé, qu'il
n'est jamais stocké en clair, et qu'un changement de mot de passe déconnecte tous les appareils.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from iris.comptes import MIN_LONGUEUR, Comptes


@pytest.fixture()
def comptes(tmp_path) -> Comptes:
    return Comptes(tmp_path)


# --------------------------------------------------------------------------- création
def test_aucun_compte_au_depart(comptes: Comptes):
    assert not comptes.configure
    assert comptes.verifier("n'importe quoi") is False


def test_creation_puis_verification(comptes: Comptes):
    comptes.creer("motdepasse-solide", nom="Miguel")
    assert comptes.configure
    assert comptes.verifier("motdepasse-solide") is True
    assert comptes.verifier("motdepasse-solidE") is False
    assert comptes.info()["nom"] == "Miguel"


@pytest.mark.parametrize("faible", ["", "court", "1234567"])
def test_mot_de_passe_trop_court_refuse(comptes: Comptes, faible):
    with pytest.raises(ValueError, match=str(MIN_LONGUEUR)):
        comptes.creer(faible)


def test_creation_refusee_si_compte_existant(comptes: Comptes):
    comptes.creer("motdepasse-solide")
    with pytest.raises(ValueError, match="existe déjà"):
        comptes.creer("autre-motdepasse")


# --------------------------------------------------------------------------- stockage
def test_le_mot_de_passe_nest_jamais_ecrit_en_clair(comptes: Comptes, tmp_path):
    comptes.creer("phrase-secrete-unique-42")
    brut = (tmp_path / "compte.json").read_text(encoding="utf-8")
    assert "phrase-secrete-unique-42" not in brut
    d = json.loads(brut)
    assert set(d) >= {"sel", "hash", "secret_session"}


def test_deux_comptes_meme_mot_de_passe_donnent_des_empreintes_differentes(tmp_path):
    a, b = Comptes(tmp_path / "a"), Comptes(tmp_path / "b")
    a.creer("le-meme-mot-de-passe")
    b.creer("le-meme-mot-de-passe")
    ha = json.loads((tmp_path / "a" / "compte.json").read_text())["hash"]
    hb = json.loads((tmp_path / "b" / "compte.json").read_text())["hash"]
    assert ha != hb, "le sel doit rendre les empreintes différentes"


# --------------------------------------------------------------------------- changement
def test_changement_exige_lancien(comptes: Comptes):
    comptes.creer("premier-motdepasse")
    with pytest.raises(ValueError, match="incorrect"):
        comptes.changer("mauvais", "nouveau-motdepasse")
    comptes.changer("premier-motdepasse", "nouveau-motdepasse")
    assert comptes.verifier("nouveau-motdepasse") and not comptes.verifier("premier-motdepasse")


# --------------------------------------------------------------------------- sessions
def test_session_valide_puis_revoquee(comptes: Comptes):
    comptes.creer("motdepasse-solide")
    jeton = comptes.ouvrir_session()
    assert comptes.session_valide(jeton)

    comptes.revoquer_tout()
    assert not comptes.session_valide(jeton), "révoquer doit déconnecter les appareils"


def test_changer_le_mot_de_passe_deconnecte_tout(comptes: Comptes):
    """Si quelqu'un a eu accès, changer le mot de passe doit suffire à le mettre dehors."""
    comptes.creer("premier-motdepasse")
    jeton = comptes.ouvrir_session()
    comptes.changer("premier-motdepasse", "nouveau-motdepasse")
    assert not comptes.session_valide(jeton)


def test_session_expiree_refusee(comptes: Comptes):
    comptes.creer("motdepasse-solide")
    assert not comptes.session_valide(comptes.ouvrir_session(duree=-1))


@pytest.mark.parametrize("faux", ["", "n'importe.quoi", "a.b.c", "abc.9999999999.signature"])
def test_jeton_falsifie_refuse(comptes: Comptes, faux):
    comptes.creer("motdepasse-solide")
    assert not comptes.session_valide(faux)


def test_signature_modifiee_refusee(comptes: Comptes):
    comptes.creer("motdepasse-solide")
    jeton = comptes.ouvrir_session()
    corps, signature = jeton.rsplit(".", 1)
    altere = corps + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    assert not comptes.session_valide(altere)


def test_echeance_modifiee_refusee(comptes: Comptes):
    """Prolonger sa propre session en changeant la date doit casser la signature."""
    comptes.creer("motdepasse-solide")
    identifiant, _echeance, signature = comptes.ouvrir_session().rsplit(".", 2)
    assert not comptes.session_valide(f"{identifiant}.{int(time.time()) + 999999}.{signature}")


# --------------------------------------------------------------------------- force brute
def test_les_tentatives_repetees_sont_bloquees(comptes: Comptes):
    comptes.creer("motdepasse-solide")
    for _ in range(9):
        comptes.verifier("mauvais")
    assert comptes.verifier("motdepasse-solide") is False, "le blocage doit tenir même pour le bon mot de passe"
    comptes._essais.clear()  # la fenêtre passée, l'accès revient
    assert comptes.verifier("motdepasse-solide") is True


# --------------------------------------------------------------------------- la première ouverture
# Constat réel : IRIS démarrait sans jamais demander de compte, et la protection du téléphone
# restait donc désactivée sans que personne le sache. L'assistant d'accueil doit la réclamer.
ACCUEIL = Path(__file__).resolve().parents[2] / "renderer" / "src" / "views" / "Onboarding.tsx"


def test_laccueil_demande_un_compte():
    source = ACCUEIL.read_text(encoding="utf-8")
    assert "'Compte'" in source, "l'étape doit figurer dans la barre de progression"
    assert "/api/compte/connexion" in source, "un compte déjà posé doit pouvoir se déverrouiller"
    assert "Créer mon compte" in source and "Se connecter" in source


def test_on_ne_peut_pas_passer_letape_sans_mot_de_passe():
    """Un bouton « Ignorer » suffirait à ramener le problème d'origine."""
    source = ACCUEIL.read_text(encoding="utf-8")
    debut = source.index("{step === 1 ? (")
    etape = source[debut:source.index("{step === 2 ? (")]
    assert "disabled={compteOccupe || !mdp.trim()}" in etape
    for echappatoire in ("Ignorer", "Passer", "Plus tard"):
        assert echappatoire not in etape, f"échappatoire trouvée : {echappatoire}"


def test_le_mot_de_passe_nest_jamais_renvoye_au_serveur_de_licences():
    """Le courriel sert à activer l'abonnement ; le mot de passe reste sur la machine."""
    source = ACCUEIL.read_text(encoding="utf-8")
    ligne = [l for l in source.splitlines() if "licence_email" in l]
    assert ligne and all("mdp" not in l for l in ligne)
