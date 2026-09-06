"""IRIS doit se décrire à partir de ce qu'elle sait VRAIMENT faire.

Bogue du 6 septembre 2026 : interrogée sur ses capacités, IRIS a répondu qu'elle « dépendait de
macOS » (elle tourne sur Windows), qu'elle « ne pouvait pas cliquer sur une coordonnée » (mouse_click
existe), « ni faire défiler » (scroll existe), « ni connaître la batterie des lunettes »
(lunettes_etat la lit). Rien dans son code ne lui disait ce qu'elle savait faire : elle inventait
ses limites. Ces tests gardent la liste générée depuis les vrais outils.
"""
from __future__ import annotations

from iris.tools import TOOL_SPECS


def _prompt(app, source="text"):
    chat = app.state.ctx.chat
    return chat._system_prompt("openrouter", has_tools=True, memory_ctx="", source=source)


def test_iris_sait_quelle_tourne_sur_windows_pas_sur_macos(app):
    texte = _prompt(app)
    assert "macOS" in texte and "jamais sur macOS" in texte, "elle doit se voir interdire l'invention macOS"
    assert "Windows" in texte


def test_chaque_outil_reel_figure_dans_la_description(app):
    """La liste est générée depuis TOOL_SPECS : un outil ajouté demain y sera sans qu'on y pense."""
    texte = _prompt(app)
    for spec in TOOL_SPECS:
        assert f"- {spec.name} :" in texte, f"l'outil réel {spec.name} manque à ce qu'IRIS sait d'elle-même"


def test_les_capacites_quelle_niait_sont_affirmees(app):
    """Chacune de ces phrases contredit une fausse limite qu'IRIS a réellement énoncée."""
    texte = _prompt(app)
    for nom in ("mouse_click", "scroll", "lunettes_etat", "traduire_conversation", "retrouver_site"):
        assert nom in texte, nom
    assert "cliquer à une coordonnée" in texte
    assert "faire défiler" in texte
    assert "batterie" in texte


def test_elle_a_ordre_de_ne_pas_inventer_de_limites(app):
    texte = _prompt(app)
    assert "N'invente jamais une capacité" in texte
    assert "n'invente jamais une limite" in texte


def test_les_regles_de_conception_ne_sont_pas_presentees_comme_des_faiblesses(app):
    """Refuser d'envoyer sans accord n'est pas une limite : c'est ce qui protège l'utilisateur."""
    texte = _prompt(app)
    assert "ta conception" in texte
    assert "sans que l'utilisateur voie le contenu et l'approuve" in texte
    assert "coffre" in texte


def test_letat_des_services_est_dit_franchement(app):
    """Courriel non configuré : IRIS doit le SAVOIR et le dire, pas prétendre pouvoir envoyer."""
    texte = _prompt(app)
    assert "courriel" in texte.lower()
    assert "NON configuré" in texte or "configuré" in texte


def test_sans_outils_la_liste_nest_pas_injectee(app):
    """Un agent sans outils ne doit pas se voir promettre des outils qu'il ne peut pas appeler."""
    chat = app.state.ctx.chat
    texte = chat._system_prompt("openrouter", has_tools=False, memory_ctx="", source="text")
    assert "LISTE EXACTE ET COMPLÈTE" not in texte


def test_la_description_survit_a_un_service_absent(app, monkeypatch):
    """Si un service n'est pas injecté (None), on ne plante pas : on omet simplement sa ligne."""
    chat = app.state.ctx.chat
    monkeypatch.setattr(chat, "courriel", None)
    monkeypatch.setattr(chat, "telephonie", None)
    monkeypatch.setattr(chat, "glasses", None)
    texte = chat._capacites_reelles()
    assert "LISTE EXACTE" in texte


# --------------------------------------------------------------------------- deux limites qu'elle s'inventait
def test_la_traduction_a_le_droit_de_parler_la_langue_de_linterlocuteur(app):
    """IRIS s'interdisait tout anglais, meme en mode traduction — contradiction : elle doit pouvoir
    rendre la phrase a dire a l'interlocuteur dans SA langue. C'est tout l'objet de la traduction."""
    texte = _prompt(app)
    assert "UNE SEULE EXCEPTION" in texte
    assert "mode traduction" in texte
    assert "langue de cet interlocuteur" in texte


def test_elle_cherche_au_lieu_de_deviner_les_faits_dates(app):
    """Limite qu'elle a elle-meme nommee : « je devine parfois au lieu de te dire que je bloque »."""
    texte = _prompt(app)
    assert "FAITS ET INCERTITUDE" in texte
    assert "web_search" in texte
    assert "ne devine jamais" in texte
