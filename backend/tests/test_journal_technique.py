"""Journal technique (constat du 2026-09-14) : backend.log n'est ni chiffré, ni soumis à la rétention, ni au mode
invité. Ce que ces tests protègent :
- les lignes qui recopiaient le texte des commandes vocales, du mot d'activation, du mot d'arrêt, de la sortie
  du mode traduction et des souvenirs ne passent plus que des métadonnées ;
- le filtre posé au démarrage masque, sous WARNING, tout argument formaté par %r et toute longue chaîne ;
- le registre de confidentialité ne reçoit que le NOM d'une photo des lunettes, pas son chemin.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from iris.__main__ import FiltreTexteJournal

RACINE = Path(__file__).resolve().parents[1] / "iris"


def test_aucune_ligne_ne_recopie_ce_qui_a_ete_dit():
    listener = (RACINE / "voice" / "listener.py").read_text(encoding="utf-8")
    chat = (RACINE / "chat.py").read_text(encoding="utf-8")
    for motif in (r'log\.info\("stt cloud: %r', r"log\.info\(\"mot d'arret entendu : %r", r"mot d'activation reconnu : %r",
                  r"sortie demandée \(%r\)", r'"stt %s: %r'):
        assert not re.search(motif, listener), motif
    assert 'log.info("mémoire : %r' not in chat
    for fichier in (RACINE / "main.py", RACINE / "accessibilite.py", RACINE / "tools.py"):
        texte = fichier.read_text(encoding="utf-8")
        assert 'consent.log("lunettes_photo", detail=res.chemin)' not in texte
        assert 'detail=resultat.chemin)' not in texte


def _journal() -> tuple[logging.Logger, io.StringIO]:
    flux = io.StringIO()
    gestionnaire = logging.StreamHandler(flux)
    gestionnaire.addFilter(FiltreTexteJournal())
    journal = logging.getLogger("iris.essai-filtre")
    journal.handlers = [gestionnaire]
    journal.setLevel(logging.DEBUG)
    journal.propagate = False
    return journal, flux


def test_le_filtre_masque_le_texte_mais_garde_le_diagnostic():
    journal, flux = _journal()
    journal.info("commande : %r", "envoie mon code de porte 1234 à Julie")
    journal.info("micro %s à %d Hz", "Casque (M01)", 16000)
    journal.info("réponse %s", "x" * 400)
    journal.info("pourcentage %d%% et %s", 5, "court")
    journal.warning("panne : %r", "détail gardé pour le diagnostic")
    sortie = flux.getvalue()
    assert "code de porte" not in sortie and "<texte masqué : 37 caractères>" in sortie
    assert "micro Casque (M01) à 16000 Hz" in sortie
    assert "x" * 200 not in sortie and "<texte masqué : 400 caractères>" in sortie
    assert "pourcentage 5% et court" in sortie
    assert "détail gardé pour le diagnostic" in sortie
