"""Vérifie que scripts/pointer-cerveau.ps1 réécrit bien la valeur par défaut de `relay_server`
dans backend/iris/config.py, sans abîmer le reste du fichier, et de façon idempotente.

Le test lance le VRAI script PowerShell sur une COPIE de config.py (option -Fichier), avec -SansLive
pour ne toucher à aucun réglage de la machine. Il est ignoré proprement là où PowerShell est absent
(CI non Windows), pour ne jamais casser la suite."""
from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]          # .../iris
SCRIPT = RACINE / "scripts" / "pointer-cerveau.ps1"
CONFIG = RACINE / "backend" / "iris" / "config.py"


def _powershell() -> str | None:
    for exe in ("pwsh", "powershell", "powershell.exe"):
        chemin = shutil.which(exe)
        if chemin:
            return chemin
    return None


pytestmark = pytest.mark.skipif(
    _powershell() is None or not SCRIPT.exists(),
    reason="PowerShell (ou le script) indisponible : test spécifique à l'outil Windows",
)


def _lancer(cible: Path, adresse: str, *extra: str) -> subprocess.CompletedProcess:
    cmd = [
        _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        "-Adresse", adresse, "-Fichier", str(cible), "-SansLive", *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _ligne_relay(texte: str) -> str:
    for ligne in texte.splitlines():
        if ligne.strip().startswith("relay_server"):
            return ligne
    raise AssertionError("ligne relay_server introuvable")


def test_reecrit_la_valeur_par_defaut(tmp_path: Path) -> None:
    cible = tmp_path / "config.py"
    shutil.copyfile(CONFIG, cible)

    res = _lancer(cible, "https://relais.exemple.com")
    assert res.returncode == 0, res.stdout + res.stderr

    texte = cible.read_text(encoding="utf-8")
    assert 'relay_server: str = "https://relais.exemple.com"' in texte
    # l'ancienne valeur a bien disparu (elle n'apparaît nulle part ailleurs dans config.py)
    assert "relais.vela.app" not in texte
    # le reste du fichier reste du Python valide : encodage et lignes voisines intacts
    ast.parse(texte)
    # l'indentation de la ligne est préservée (4 espaces dans la classe)
    assert _ligne_relay(texte).startswith('    relay_server')


def test_idempotent(tmp_path: Path) -> None:
    cible = tmp_path / "config.py"
    shutil.copyfile(CONFIG, cible)

    assert _lancer(cible, "https://relais.exemple.com").returncode == 0
    apres_1 = cible.read_text(encoding="utf-8")
    assert _lancer(cible, "https://relais.exemple.com").returncode == 0
    apres_2 = cible.read_text(encoding="utf-8")
    assert apres_1 == apres_2  # relancer avec la même adresse ne change plus rien


def test_dryrun_n_ecrit_rien(tmp_path: Path) -> None:
    cible = tmp_path / "config.py"
    shutil.copyfile(CONFIG, cible)
    avant = cible.read_text(encoding="utf-8")

    res = _lancer(cible, "https://relais.test.dev", "-DryRun")
    assert res.returncode == 0, res.stdout + res.stderr
    assert cible.read_text(encoding="utf-8") == avant           # fichier inchangé
    assert "relais.test.dev" in (res.stdout + res.stderr)        # mais l'aperçu montre l'adresse


def test_adresse_invalide_refusee(tmp_path: Path) -> None:
    cible = tmp_path / "config.py"
    shutil.copyfile(CONFIG, cible)
    avant = cible.read_text(encoding="utf-8")

    res = _lancer(cible, "pas-une-url")
    assert res.returncode != 0                                   # sortie en erreur
    assert cible.read_text(encoding="utf-8") == avant            # rien touché
