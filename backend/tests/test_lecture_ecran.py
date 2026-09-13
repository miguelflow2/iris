"""Lecture d'écran fiable pour les malvoyants.

Deux échecs silencieux corrigés ici, tous deux constatés en lisant le code réel :

1. « lis-moi l'écran » / « décris l'écran » ne déclenchaient AUCUN mot de SCREEN_KEYWORDS. Résultat :
   tool_specs(screen=False) retirait take_screenshot, et IRIS « décrivait » de mémoire un écran
   qu'elle n'avait jamais regardé. C'est la première phrase d'un utilisateur qui ne voit pas — elle
   ne peut pas vérifier que la réponse est inventée. On ajoute les déclencheurs, ET on garde toujours
   la capture + la lecture OCR dès que le contrôle d'écran est autorisé.

2. La « lecture » passait par le modèle de vision, qui résume, omet ou invente. read_screen_text
   restitue le texte VERBATIM par OCR local (aucun modèle, fonctionne hors-ligne / en mode local),
   ordonné de haut en bas et de gauche à droite.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from iris.chat import SCREEN_KEYWORDS, SCREEN_READ_KEYWORDS
from iris.router import _has


# --------------------------------------------------------------------------- 1. déclenchement
@pytest.mark.parametrize(
    "phrase",
    [
        "lis-moi l'écran",
        "lis moi l'écran",
        "lis-moi ce qui est écrit",
        "décris l'écran",
        "décris-moi ce qu'il y a",
        "décris ce que tu vois",
        "fais-moi la lecture d'écran",
        "lis tout ce qui est affiché",
        "que dit l'écran",
        "qu'est-ce qu'il y a à l'écran ?",
        "qu'est-ce qui est écrit ?",
    ],
)
def test_les_phrases_de_lecture_declenchent_lecran(phrase):
    """Chacune doit ouvrir l'écran — sinon IRIS répond sans jamais l'avoir regardé."""
    assert _has(phrase.lower(), SCREEN_KEYWORDS), f"pas détecté comme écran : {phrase!r}"


def test_lis_moi_lecran_passe_par_les_nouveaux_declencheurs():
    """Preuve que ce sont bien les AJOUTS qui font le travail, pas un ancien mot-clé."""
    ancien = [k for k in SCREEN_KEYWORDS if k not in SCREEN_READ_KEYWORDS]
    assert not _has("lis-moi l'écran", ancien), "aurait déjà été couvert : le test ne prouverait rien"
    assert _has("lis-moi l'écran", SCREEN_READ_KEYWORDS)


@pytest.mark.parametrize(
    "phrase",
    [
        "utilise le navigateur pour chercher",  # « utilise » contient les lettres l-i-s
        "réalise un résumé de ce texte",
        "analyse ce fichier",
        "personnalise mon profil",
    ],
)
def test_pas_de_faux_declenchement_sur_les_verbes_courants(phrase):
    """« lis » nu piégeait « utilise », « réalise »… : les déclencheurs ne doivent viser QUE la lecture d'écran."""
    assert not _has(phrase.lower(), SCREEN_KEYWORDS), f"faux positif écran : {phrase!r}"


# --------------------------------------------------------------------------- 2. l'outil est offert
def _ctx(computer_use: bool):
    return SimpleNamespace(
        create_task=None,
        settings=SimpleNamespace(user=SimpleNamespace(computer_use=computer_use)),
    )


def test_read_screen_text_est_un_outil_declare():
    from iris.tools import tool_specs

    noms = {s.name for s in tool_specs(SimpleNamespace(create_task=None))}
    assert "read_screen_text" in noms


def test_capture_et_lecture_toujours_offertes_quand_le_controle_ecran_est_actif():
    """Filet de sécurité : même mal classée, une demande de lecture doit pouvoir REGARDER l'écran."""
    from iris.tools import tool_specs

    noms = {s.name for s in tool_specs(_ctx(True), screen=False, keyboard=False, web=False)}
    assert "take_screenshot" in noms, "IRIS doit toujours pouvoir capturer l'écran"
    assert "read_screen_text" in noms, "…et le lire verbatim"
    # mais les outils d'action (souris, clic) restent retirés : on n'offre que la LECTURE.
    assert "mouse_click" not in noms and "click_text" not in noms


def test_sans_controle_ecran_les_outils_de_capture_disparaissent_avec_le_groupe():
    from iris.tools import tool_specs

    noms = {s.name for s in tool_specs(_ctx(False), screen=False)}
    assert "take_screenshot" not in noms and "read_screen_text" not in noms


# --------------------------------------------------------------------------- 3. lecture VERBATIM, locale
def test_read_screen_text_ordonne_haut_bas_puis_gauche_droite(monkeypatch):
    """Deux fragments à la même hauteur se lisent gauche→droite sur une ligne ; la ligne d'en dessous ensuite."""
    from iris.pc import actions

    faux = [
        {"text": "Miguel", "confidence": 0.99, "left": 100, "top": 12, "right": 180, "bottom": 32, "x": 140, "y": 22},
        {"text": "Bonjour", "confidence": 0.99, "left": 10, "top": 10, "right": 90, "bottom": 30, "x": 50, "y": 20},
        {"text": "Deuxième ligne", "confidence": 0.98, "left": 10, "top": 60, "right": 200, "bottom": 82, "x": 105, "y": 71},
    ]
    monkeypatch.setattr(actions, "ocr_screen", lambda **k: list(faux))
    texte = actions.read_screen_text()
    assert texte == "Bonjour Miguel\nDeuxième ligne"


def test_read_screen_text_est_verbatim(monkeypatch):
    """Le texte n'est ni résumé ni reformulé : les mots exacts, à la ponctuation près."""
    from iris.pc import actions

    faux = [
        {"text": "Erreur 402 : paiement requis.", "confidence": 0.97, "left": 20, "top": 40, "right": 400, "bottom": 62, "x": 210, "y": 51},
    ]
    monkeypatch.setattr(actions, "ocr_screen", lambda **k: list(faux))
    assert actions.read_screen_text() == "Erreur 402 : paiement requis."


def test_read_screen_text_ecran_vide(monkeypatch):
    from iris.pc import actions

    monkeypatch.setattr(actions, "ocr_screen", lambda **k: [])
    assert actions.read_screen_text() == ""


# --------------------------------------------------------------------------- 4. le câblage de l'outil
def _tool_ctx(computer_use: bool):
    from iris.tools import ToolContext

    async def accepter(titre: str, detail: str) -> bool:
        return True

    reglages = SimpleNamespace(user=SimpleNamespace(confirm_commands="dangerous", computer_use=computer_use))
    return ToolContext(
        settings=reglages,
        consent=SimpleNamespace(log=lambda *a, **k: None),
        capture=None,
        memory=None,
        agent="test",
        confirm=accepter,
    )


def test_loutil_rend_le_texte_local_sans_passer_par_un_modele(monkeypatch):
    from iris.pc import actions
    from iris.tools import make_tool_runner

    monkeypatch.setattr(actions, "ocr_available", lambda: True)
    # Si le dispatch appelait ocr_screen puis un modèle, ce texte figé ne remonterait pas tel quel.
    monkeypatch.setattr(actions, "read_screen_text", lambda **k: "Ligne A\nLigne B")
    res = asyncio.run(make_tool_runner(_tool_ctx(True))("read_screen_text", {}))
    assert res == "Ligne A\nLigne B"


def test_loutil_est_bloque_si_le_controle_ecran_est_desactive(monkeypatch):
    from iris.pc import actions
    from iris.tools import make_tool_runner

    monkeypatch.setattr(actions, "ocr_available", lambda: True)
    res = asyncio.run(make_tool_runner(_tool_ctx(False))("read_screen_text", {}))
    assert isinstance(res, dict) and res.get("is_error"), "sans consentement écran, l'outil doit refuser"
