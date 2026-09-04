"""Commandes reconnues sans modèle : elles doivent être justes, et surtout ne jamais se déclencher à tort."""
from __future__ import annotations

from datetime import datetime

import pytest

from iris.quick_commands import match

MIDI = datetime(2026, 9, 3, 12, 53)


def resolveur(nom: str) -> str | None:
    """Résolveur d'applications factice : seules ces applications existent sur la machine de test."""
    connues = {"calculatrice": "Calculatrice", "bloc notes": "Bloc-notes", "spotify": "Spotify", "vs code": "VS Code"}
    return connues.get(nom)


# --------------------------------------------------------------------------- heure et date
@pytest.mark.parametrize("phrase", ["quelle heure est il", "il est quelle heure", "Dis-moi quelle heure est-il ?"])
def test_heure(phrase):
    cmd = match(phrase, now=MIDI)
    assert cmd is not None and cmd.kind == "heure" and not cmd.tool
    assert "12 heures 53" in cmd.reply


def test_date():
    cmd = match("on est quel jour", now=MIDI)
    assert cmd is not None and cmd.kind == "date"
    assert "jeudi 3 septembre 2026" in cmd.reply


# --------------------------------------------------------------------------- musique et vidéo
@pytest.mark.parametrize(
    "phrase, attendu",
    [
        ("mets de la musique de daft punk", "daft punk"),
        ("lance une video de mrbeast", "mrbeast"),
        ("ouvre youtube et lance une video de mrbeast", "mrbeast"),
        ("joue la chanson bohemian rhapsody", "bohemian rhapsody"),
        ("mets une musique de jazz sur youtube", "jazz"),
        ("ecoute du lofi", "lofi"),
        ("met de la musique de charlotte cardin s il te plait", "charlotte cardin"),
    ],
)
def test_media(phrase, attendu):
    cmd = match(phrase, app_resolver=resolveur)
    assert cmd is not None, f"non reconnu : {phrase!r}"
    assert cmd.tool == "play_youtube", f"{phrase!r} -> {cmd}"
    assert cmd.args["query"] == attendu


@pytest.mark.parametrize("phrase", ["mets de la musique", "lance une video", "joue une chanson"])
def test_media_sans_objet_pose_une_question(phrase):
    """Sans titre ni artiste, IRIS doit demander plutôt que de lancer n'importe quoi."""
    cmd = match(phrase, app_resolver=resolveur)
    assert cmd is not None and cmd.kind == "precision" and not cmd.tool
    assert cmd.reply.endswith("?")


# --------------------------------------------------------------------------- sites et applications
@pytest.mark.parametrize(
    "phrase, url",
    [
        ("ouvre youtube", "https://www.youtube.com"),
        ("ouvre google", "https://www.google.com"),
        ("va sur netflix", "https://www.netflix.com"),
    ],
)
def test_sites(phrase, url):
    cmd = match(phrase, app_resolver=resolveur)
    assert cmd is not None and cmd.tool == "open_url" and cmd.args["url"] == url


@pytest.mark.parametrize(
    "phrase, app",
    [
        ("ouvre la calculatrice", "Calculatrice"),
        ("lance spotify", "Spotify"),
        ("ouvre mon bloc notes", "Bloc-notes"),
        ("demarre vs code", "VS Code"),
    ],
)
def test_applications(phrase, app):
    cmd = match(phrase, app_resolver=resolveur)
    assert cmd is not None and cmd.tool == "open_application" and cmd.args["name"] == app


# --------------------------------------------------------------------------- prudence : ne pas se déclencher à tort
@pytest.mark.parametrize(
    "phrase",
    [
        "crée un jeu de morpion",
        "explique moi ce que fait la commande git status",
        "regarde mon ecran et dis moi ce que tu vois",
        "ouvre le fichier rapport et corrige les fautes puis envoie le",  # demande composée
        "ouvre truc machin inconnu",  # application introuvable
        "comment ouvrir un compte en banque au quebec",  # question, pas un ordre
        "souviens toi que j ai un examen mardi",
        "connecte toi a omnivox et montre mon horaire",
    ],
)
def test_ne_se_declenche_pas(phrase):
    assert match(phrase, app_resolver=resolveur) is None, f"déclenchement à tort : {phrase!r}"
