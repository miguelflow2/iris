"""Des réglages qui ne se perdent plus : écriture atomique, sauvegarde, restauration, nettoyage.

Le point de départ est un fichier réel : le settings.corrupt.json retrouvé sur la machine de Miguel,
daté du 4 septembre 2026 à 14 h 57. Il n'était pas corrompu. C'était un JSON valide, réécrit par
PowerShell 5.1 avec une marque d'ordre d'octets en tête, et IRIS l'a jeté pour ça — lunettes, clés
et mot d'activation compris. Aucun test ici ne touche au vrai dossier de données : tout se passe
dans un dossier temporaire.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from iris.config import MOT_ACTIVATION, Settings, UserSettings, construire_reglages, migrer

# Ce que PowerShell 5.1 produit avec `ConvertTo-Json | Out-File` : BOM, quatre espaces, deux
# espaces après les deux-points. Reconstitué d'après la forme du fichier réel, sans ses valeurs.
BOM = "\ufeff"  # EF BB BF : invisible dans un éditeur, et c'est bien le problème


def _ecrire(path: Path, contenu: str, encodage: str = "utf-8") -> None:
    path.write_text(contenu, encoding=encodage)


def _reglages_json(**champs) -> str:
    return json.dumps({"settings_version": 2, **champs}, indent=2)


@pytest.fixture()
def dossier(tmp_path: Path) -> Path:
    d = tmp_path / "iris-data"
    d.mkdir()
    return d


# --------------------------------------------------------------- 1. lire ce qui est lisible
def test_le_bom_de_powershell_nest_plus_pris_pour_une_corruption(dossier, caplog):
    """L'incident du 4 septembre, rejoué : un fichier valide, une marque d'ordre d'octets en tête.
    Il doit se lire comme n'importe quel autre, sans rien mettre de côté."""
    _ecrire(dossier / "settings.json",
            BOM + '{\n    "settings_version":  2,\n    "wake_word":  "Dis-moi Iris",\n'
                  '    "glasses":  {\n        "address":  "65:A2:9F:5C:F4:44",\n        "name":  "M01 Pro_F444"\n    }\n}\n')
    with caplog.at_level(logging.WARNING, logger="iris.config"):
        s = Settings(dossier)
    assert s.user.glasses.name == "M01 Pro_F444"
    assert not (dossier / "settings.corrupt.json").exists(), "rien n'était corrompu"
    assert s.restaure_depuis_sauvegarde is False
    assert [r for r in caplog.records if r.name == "iris.config"] == []


def test_un_champ_refuse_ne_jette_pas_tout_le_reste(dossier, caplog):
    """Un plan d'un vocabulaire inconnu, et hier toute la configuration partait avec lui."""
    _ecrire(dossier / "settings.json", _reglages_json(plan="platine", glasses={"name": "M01 Pro_F444"},
                                                     wake_word="Dis-moi Iris", license_key="VELA-XXXX"))
    with caplog.at_level(logging.WARNING, logger="iris.config"):
        s = Settings(dossier)
    assert s.user.glasses.name == "M01 Pro_F444"
    assert s.user.license_key == "VELA-XXXX"
    assert s.user.plan == "gratuit", "le champ fautif, lui, revient au défaut"
    assert s.champs_remis_au_defaut == ["plan"]
    assert (dossier / "settings.corrupt.json").exists(), "ce qu'on a retiré reste consultable"
    assert any("plan" in r.getMessage() for r in caplog.records), "le journal nomme le champ"


def test_construire_reglages_retire_les_champs_un_par_un():
    user, rejetes = construire_reglages({"plan": "platine", "retention_days": "beaucoup", "user_name": "Miguel"})
    assert user is not None and user.user_name == "Miguel"
    assert sorted(rejetes) == ["plan", "retention_days"]


# --------------------------------------------------------------- 2. écrire sans jamais casser
def test_chaque_ecriture_reussie_laisse_une_sauvegarde_identique(dossier):
    s = Settings(dossier)
    s.update({"glasses": {"name": "M01 Pro_F444", "address": "x", "auto_connect": True}})
    principal = (dossier / "settings.json").read_text(encoding="utf-8")
    sauvegarde = (dossier / "settings.json.bak").read_text(encoding="utf-8")
    assert principal == sauvegarde
    assert json.loads(principal)["glasses"]["name"] == "M01 Pro_F444"
    assert not list(dossier.glob("*.tmp")), "le fichier de travail ne reste pas derrière"


def test_lecriture_ne_laisse_jamais_un_fichier_a_moitie_ecrit(dossier, monkeypatch):
    """Si l'écriture du fichier de travail échoue, l'ancien settings.json est intact."""
    s = Settings(dossier)
    s.update({"user_name": "Miguel"})
    avant = (dossier / "settings.json").read_text(encoding="utf-8")

    import iris.config as config

    def _replace_qui_echoue(src, dst):
        raise OSError("disque plein")

    monkeypatch.setattr(config.os, "replace", _replace_qui_echoue)
    with pytest.raises(OSError):
        s.update({"user_name": "Personne"})
    assert (dossier / "settings.json").read_text(encoding="utf-8") == avant


# --------------------------------------------------------------- 3. restaurer plutôt que repartir de zéro
def test_un_fichier_tronque_est_restaure_depuis_la_sauvegarde(dossier, caplog):
    """Coupure de courant, disque plein, éditeur maladroit : le fichier s'arrête au milieu d'une
    ligne. Hier : réglages neufs, lunettes à réappairer, clé à retaper. Aujourd'hui : rien à faire."""
    s = Settings(dossier)
    s.update({"glasses": {"name": "M01 Pro_F444", "address": "x", "auto_connect": True},
              "wake_word": "Dis-moi Iris", "license_key": "VELA-XXXX"})
    entier = (dossier / "settings.json").read_text(encoding="utf-8")
    _ecrire(dossier / "settings.json", entier[: len(entier) // 2])

    with caplog.at_level(logging.WARNING, logger="iris.config"):
        s2 = Settings(dossier)
    assert s2.user.glasses.name == "M01 Pro_F444"
    assert s2.user.license_key == "VELA-XXXX"
    assert s2.restaure_depuis_sauvegarde is True
    assert (dossier / "settings.corrupt.json").exists(), "le fichier fautif est gardé pour comprendre"
    assert json.loads((dossier / "settings.json").read_text(encoding="utf-8"))["glasses"]["name"] == "M01 Pro_F444"
    assert any("RESTAUR" in r.getMessage() for r in caplog.records), "le journal doit le dire"


def test_sans_sauvegarde_on_repart_de_zero_en_le_disant(dossier, caplog):
    _ecrire(dossier / "settings.json", "{ceci n'est pas du JSON")
    with caplog.at_level(logging.ERROR, logger="iris.config"):
        s = Settings(dossier)
    assert s.user.wake_word == MOT_ACTIVATION
    assert s.restaure_depuis_sauvegarde is False
    assert any("zéro" in r.getMessage() for r in caplog.records)
    assert (dossier / "settings.json.bak").exists(), "le nouveau départ est lui-même sauvegardé"


def test_une_sauvegarde_elle_meme_illisible_ne_bloque_pas_le_demarrage(dossier):
    _ecrire(dossier / "settings.json", "")
    _ecrire(dossier / "settings.json.bak", "\x00\x00")
    s = Settings(dossier)
    assert s.user.wake_word == MOT_ACTIVATION
    assert (dossier / "settings.json").exists()


def test_un_fichier_lisible_mais_sans_rien_de_recuperable_passe_par_la_sauvegarde(dossier):
    s = Settings(dossier)
    s.update({"user_name": "Miguel"})
    _ecrire(dossier / "settings.json", "[1, 2, 3]")  # du JSON, mais pas un objet de réglages
    s2 = Settings(dossier)
    assert s2.user.user_name == "Miguel"
    assert s2.restaure_depuis_sauvegarde is True


# --------------------------------------------------------------- 4. le mot d'activation
def test_le_defaut_est_le_nom_vendu_et_iris_tout_court_en_alias():
    u = UserSettings()
    assert u.wake_word == "Dis-moi Iris"
    assert "iris" in u.wake_aliases
    assert not any("irisse" in a or "hiris" in a for a in u.wake_aliases), "Vosk ne les connaît pas : ils sont morts"


def test_lespace_en_tete_du_mot_dactivation_est_retiree_a_la_lecture(dossier):
    """Le réglage réel de la machine de Miguel : «  Iris », espace en tête, un seul mot."""
    _ecrire(dossier / "settings.json", _reglages_json(wake_word=" Iris", wake_aliases=["  dis iris ", "", "dis iris", "iris"]))
    s = Settings(dossier)
    assert s.user.wake_word == "Iris"
    assert s.user.wake_aliases == ["dis iris", "iris"], "espaces retirés, vide écarté, doublon fondu"


def test_un_mot_dactivation_vide_revient_au_nom_vendu(dossier):
    s = Settings(dossier)
    s.update({"wake_word": "   "})
    assert s.user.wake_word == MOT_ACTIVATION


def test_les_alias_morts_sont_retires_a_la_migration(dossier):
    """La liste par défaut d'avant, telle qu'elle dort dans les settings.json déjà écrits."""
    anciens = ["dis moi iris", "dis iris", "iris", "dis moi irisse", "dis moi hiris", "dit moi iris"]
    _ecrire(dossier / "settings.json", _reglages_json(wake_aliases=anciens))
    s = Settings(dossier)
    assert s.user.wake_aliases == ["dis moi iris", "dis iris", "iris", "dit moi iris"]
    assert s.user.settings_version == 3


def test_la_migration_ne_touche_pas_aux_alias_appris_par_calibration():
    """Ce que la calibration enregistre vient du plein vocabulaire : c'est par définition prononçable."""
    raw = migrer({"settings_version": 2, "wake_aliases": ["dis moi iris", "dit moi irise", "hiris"]})
    assert raw["wake_aliases"] == ["dis moi iris", "dit moi irise"]


def test_un_numero_de_version_illisible_nempeche_pas_de_lire_le_reste():
    user, rejetes = construire_reglages({"settings_version": "abc", "user_name": "Miguel"})
    assert user is not None and user.user_name == "Miguel"
