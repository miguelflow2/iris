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


# --------------------------------------------------------------------------- ne pas détourner
@pytest.mark.parametrize(
    "phrase",
    [
        # Constat réel : « ouvre Spotify et mets ma liste aimée » ouvrait YouTube.
        "ouvre mon application spotify et mets la musique dans ma liste de musique aimee",
        "mets ma liste de musique aimee sur spotify",
        "mets de la musique sur spotify",
        "joue mes chansons aimees",
        "ouvre spotify et joue ma playlist",
        "mets un film sur netflix",
        "lance ma playlist sur deezer",
        "joue mes favoris",
    ],
)
def test_une_autre_application_ou_sa_bibliotheque_nest_jamais_detournee(phrase):
    """Une recherche YouTube n'a aucun accès à la bibliothèque de l'utilisateur.
    Ces demandes doivent revenir à l'agent, qui saura piloter l'application à l'écran."""
    assert match(phrase, app_resolver=resolveur) is None, f"détourné : {phrase!r}"


@pytest.mark.parametrize(
    "phrase, attendu",
    [
        ("mets de la musique de daft punk", "play_youtube"),
        ("ouvre youtube et lance une video de mrbeast", "play_youtube"),
        ("ouvre spotify", "open_application"),
    ],
)
def test_les_cas_simples_restent_instantanes(phrase, attendu):
    """Le filet local garde son intérêt : ces demandes-là n'ont pas besoin d'un modèle."""
    cmd = match(phrase, app_resolver=resolveur)
    assert cmd is not None and cmd.tool == attendu


# --------------------------------------------------------------------------- l'heure ailleurs
# Constat réel : « quelle heure est-il en Chine ? » renvoyait l'heure de Trois-Rivières. La
# reconnaissance locale voyait « quelle heure » et s'arrêtait là. Une réponse fausse dite avec
# assurance est pire qu'une absence de réponse.
@pytest.mark.parametrize(
    "phrase, zone",
    [
        ("quelle heure est il en chine", "Asia/Shanghai"),
        ("quelle heure est-il à Tokyo ?", "Asia/Tokyo"),
        ("il est quelle heure à Paris", "Europe/Paris"),
        ("quelle heure est il au maroc", "Africa/Casablanca"),
        ("quelle heure est il en afrique du sud", "Africa/Johannesburg"),
    ],
)
def test_lheure_dun_autre_pays_est_juste(phrase, zone):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cmd = match(phrase)
    assert cmd is not None and cmd.kind == "heure"
    attendu = datetime.now(ZoneInfo(zone))
    assert str(attendu.hour) in cmd.reply, f"{phrase} -> {cmd.reply} (attendu {attendu.hour} h)"


@pytest.mark.parametrize("phrase", ["quelle heure est il au burkina faso", "quelle heure est il a kuala lumpur",
                                    "quel jour on est en chine"])
def test_un_lieu_inconnu_part_au_modele_plutot_que_de_mentir(phrase):
    """Ne pas savoir est acceptable. Servir l'heure d'ici sous un autre nom ne l'est pas."""
    assert match(phrase) is None


@pytest.mark.parametrize("phrase", ["quelle heure est il", "il est quelle heure a peu pres",
                                    "il est quelle heure a present"])
def test_sans_lieu_cest_bien_lheure_dici(phrase):
    cmd = match(phrase, now=MIDI)
    assert cmd is not None and "12 heures 53" in cmd.reply
