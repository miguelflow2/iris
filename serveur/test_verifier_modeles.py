"""Le vérificateur de modèles, sans jamais toucher au réseau.

Constat de l'audit du 6 septembre 2026 : les identifiants de modèles du relais n'étaient validés
contre aucune vraie API, et le vérificateur a immédiatement trouvé « z-ai/glm-5.2:free »,
inexistant. Ces tests gardent l'outil — et un test lit la VRAIE liste du relais pour crier si un
identifiant fantôme y revient.
"""
from __future__ import annotations

import io
import json

import verifier_modeles as vm


class _FausseReponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _faux_ouvrir(charge: dict):
    def ouvrir(_requete, timeout=0):
        return _FausseReponse(json.dumps(charge).encode("utf-8"))
    return ouvrir


def test_le_catalogue_extrait_les_identifiants():
    ouvrir = _faux_ouvrir({"data": [{"id": "a/b:free"}, {"id": "c/d"}, {"sans_id": 1}]})
    assert vm.catalogue_openrouter(ouvrir=ouvrir) == {"a/b:free", "c/d"}


def test_confronter_separe_present_et_absent():
    bilan = vm.confronter(["a/b:free", "x/y:free"], {"a/b:free", "c/d"})
    assert bilan["presents"] == ["a/b:free"]
    assert bilan["absents"] == ["x/y:free"]
    assert bilan["total"] == 2


def test_un_free_retire_compte_comme_absent():
    """Le cas exact qui casse une démo : le modèle existait, sa variante :free a disparu."""
    bilan = vm.confronter(["minimax/minimax-m3:free"], {"minimax/minimax-m3"})
    assert bilan["absents"] == ["minimax/minimax-m3:free"]


def test_le_verificateur_lit_les_vrais_modeles_du_relais():
    """S'il recopiait la liste à la main, il mentirait dès la première divergence."""
    modeles = vm._modeles_du_relais()
    assert "minimax/minimax-m3:free" in modeles
    assert "anthropic/claude-opus-5" in modeles
    # Le fantôme retiré le 6 septembre ne doit jamais revenir.
    assert "z-ai/glm-5.2:free" not in modeles, "un identifiant inexistant est réapparu dans le relais"


def test_main_signale_un_absent_par_son_code_de_sortie(capsys):
    modeles = vm._modeles_du_relais()
    # Catalogue à qui il manque exprès un modèle : main doit sortir 1.
    manquant = modeles[0]
    catalogue = set(modeles) - {manquant}
    vm.catalogue_openrouter = lambda *a, **k: catalogue  # type: ignore[assignment]
    try:
        code = vm.main([])
    finally:
        pass
    sortie = capsys.readouterr().out
    assert code == 1
    assert "INTROUVABLE" in sortie and manquant in sortie
