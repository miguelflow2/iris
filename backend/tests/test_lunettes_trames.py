"""Le protocole des lunettes VELA, retrouve a la main.

Quatre trames observees ont suffi a le decoder. La somme de controle est un CRC-16/MODBUS
petit-boutiste calcule sur le CONTENU SEUL : trouve par recherche exhaustive sur quatorze
variantes de CRC et six decoupages de la trame, une seule combinaison colle sur les quatre.

    bc | commande | longueur (2, petit-boutiste) | CRC (2, petit-boutiste) | contenu

Ces tests gardent ce decodage. S'ils tombent, IRIS ne saura plus lire ses lunettes.
"""
from __future__ import annotations

import pytest

from iris.lunettes_trames import batterie, crc_modbus, decrire, fabriquer, lire

# Trames reellement recues des lunettes M01 Pro_F444, micrologiciel AM01C_2.20.04_260122.
OBSERVEES = [
    ("bc7303005e61055600", 86),
    ("bc7303005e91055500", 85),
    ("bc7303005f01055400", 84),
    ("bc7303005d31055300", 83),
]


@pytest.mark.parametrize("hexa, pourcent", OBSERVEES)
def test_les_trames_reelles_se_decodent(hexa, pourcent):
    trame = bytes.fromhex(hexa)
    lu = lire(trame)
    assert lu is not None and lu["crc_valide"], "la somme de controle doit tomber juste"
    assert lu["commande"] == 0x73
    assert batterie(trame) == pourcent


@pytest.mark.parametrize("hexa, pourcent", OBSERVEES)
def test_ce_quon_fabrique_est_identique_a_ce_quelles_envoient(hexa, pourcent):
    """La preuve que le format est juste : la trame reconstruite est identique, octet pour octet."""
    assert fabriquer(0x73, bytes([0x05, pourcent, 0x00])).hex() == hexa


def test_une_somme_falsifiee_est_refusee():
    """Sans ce controle, du bruit radio passerait pour un niveau de batterie."""
    fausse = bytearray(bytes.fromhex(OBSERVEES[0][0]))
    fausse[4] ^= 0xFF
    assert lire(bytes(fausse))["crc_valide"] is False
    assert batterie(bytes(fausse)) is None


def test_ce_qui_nest_pas_une_trame_ne_casse_rien():
    for mauvais in (b"", bytes([0]), bytes.fromhex("deadbeef"), bytes.fromhex("bc73ff00ffff")):
        assert batterie(mauvais) is None


def test_un_niveau_impossible_est_ecarte():
    """Un octet a 200 n'est pas un pourcentage : mieux vaut ne rien dire que d'annoncer 200 %."""
    assert batterie(fabriquer(0x73, bytes([0x05, 200, 0x00]))) is None
    assert batterie(fabriquer(0x73, bytes([0x05, 100, 0x00]))) == 100
    assert batterie(fabriquer(0x73, bytes([0x05, 0, 0x00]))) == 0


def test_une_autre_commande_nest_pas_prise_pour_la_batterie():
    assert batterie(fabriquer(0x01, bytes([0x05, 50, 0x00]))) is None
    assert batterie(fabriquer(0x73, bytes([0x09, 50, 0x00]))) is None


def test_le_crc_est_bien_celui_de_modbus():
    """Valeur de reference du CRC-16/MODBUS pour la chaine 123456789."""
    assert crc_modbus(b"123456789") == 0x4B37


def test_la_description_reste_honnete_sur_ce_quon_ignore():
    """Une trame qu'on ne comprend pas doit le dire, pas etre interpretee au hasard."""
    assert "83" in decrire(bytes.fromhex(OBSERVEES[3][0]))
    inconnue = decrire(fabriquer(0x42, bytes([0x01, 0x02])))
    assert "inconnu" in inconnue


def test_iris_met_a_jour_sa_batterie_en_recevant_une_trame(app):
    """Ces lunettes n'exposent aucune caracteristique de batterie standard : sans ce decodage,
    IRIS affiche « batterie inconnue » en permanence."""
    verres = app.state.ctx.glasses
    verres.battery = None
    verres._on_notify("de5bf729", bytearray(bytes.fromhex(OBSERVEES[0][0])))
    assert verres.battery == 86
    verres._on_notify("de5bf729", bytearray(bytes.fromhex(OBSERVEES[3][0])))
    assert verres.battery == 83
    verres._on_notify("de5bf729", bytearray(b"du bruit"))
    assert verres.battery == 83, "un paquet illisible ne doit jamais effacer ce qu'on sait"
