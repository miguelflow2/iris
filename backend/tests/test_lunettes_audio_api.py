"""« Utilise mes lunettes » en un seul geste : ce que l'API doit garantir à l'interface.

L'écran Lunettes pose le micro ET la sortie dans un SEUL appel PATCH. Ce n'est pas un détail
d'implémentation : sous Windows, les deux profils Bluetooth d'un casque s'excluent (le son stéréo
s'éteint dès que le micro mains libres s'ouvre). Un état intermédiaire — micro des lunettes déjà
posé, sortie encore sur le haut-parleur ou sur le profil stéréo — donne une IRIS qui entend
parfaitement et parle dans le vide. Ces tests verrouillent le contrat dont dépendent les deux
boutons de GlassesView : un appel, deux valeurs, jamais de demi-état.
"""

import sys

import pytest

# Noms relevés sur la machine de Miguel (énumération PortAudio en lecture seule, 2026-09-04).
# On les garde tels quels, avec leurs défauts, parce que ce sont EUX que l'interface doit digérer :
# MME tronque à 31 caractères, DirectSound et WASAPI donnent le nom complet de 41 caractères,
# et WDM-KS expose une chaîne de ressource brute du pilote, illisible et inutilisable.
MICRO_LUNETTES_TRONQUE = "Casque (M01 Pro_F444 Hands-Free"
MICRO_LUNETTES_COMPLET = "Casque (M01 Pro_F444 Hands-Free AG Audio)"
SORTIE_LUNETTES_STEREO = "Casque (M01 Pro_F444 Stereo)"
SORTIE_LUNETTES_MAINS_LIBRES = "Casque (M01 Pro_F444 Hands-Free"  # préfixe de 31 car. : correspond aux noms tronqués ET complets
NOM_BRUT_DU_PILOTE = (
    "Casque (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free AG Audio%0\r\n;(M01 Pro_F444))"
)


def _peripheriques_de_la_machine() -> list[dict]:
    """Les 11 lignes que PortAudio donne pour UN seul casque, plus les périphériques du PC."""
    return [
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Microphone (High Definition Audio Device)", "max_input_channels": 2, "max_output_channels": 0},
        {"name": MICRO_LUNETTES_TRONQUE, "max_input_channels": 1, "max_output_channels": 0},  # MME
        {"name": "Haut-parleurs (High Definition Audio Device)", "max_input_channels": 0, "max_output_channels": 2},
        {"name": SORTIE_LUNETTES_STEREO, "max_input_channels": 0, "max_output_channels": 2},  # MME
        {"name": MICRO_LUNETTES_TRONQUE, "max_input_channels": 0, "max_output_channels": 1},  # MME, sortie mains libres
        {"name": MICRO_LUNETTES_COMPLET, "max_input_channels": 1, "max_output_channels": 0},  # DirectSound
        {"name": SORTIE_LUNETTES_STEREO, "max_input_channels": 0, "max_output_channels": 2},  # DirectSound
        {"name": MICRO_LUNETTES_COMPLET, "max_input_channels": 0, "max_output_channels": 1},  # DirectSound
        {"name": SORTIE_LUNETTES_STEREO, "max_input_channels": 0, "max_output_channels": 2},  # WASAPI
        {"name": MICRO_LUNETTES_COMPLET, "max_input_channels": 1, "max_output_channels": 1},  # WASAPI, 16 kHz
        {"name": NOM_BRUT_DU_PILOTE, "max_input_channels": 1, "max_output_channels": 0},  # WDM-KS
        {"name": NOM_BRUT_DU_PILOTE, "max_input_channels": 0, "max_output_channels": 1},  # WDM-KS
    ]


class FauxSounddevice:
    """Faux module sounddevice : énumère, n'ouvre aucun flux, ne joue aucun son.

    Miguel porte ses lunettes pendant que ces tests tournent ; toucher au vrai PortAudio
    reviendrait à lui couper le son au milieu d'une phrase.
    """

    def __init__(self, peripheriques: list[dict]):
        self._peripheriques = peripheriques

    def query_devices(self, device=None, kind=None):
        if device is None:
            return list(self._peripheriques)
        return self._peripheriques[device]


@pytest.fixture()
def peripheriques_simules(monkeypatch):
    """Remplace sounddevice le temps du test ; monkeypatch remet le vrai module ensuite."""
    faux = FauxSounddevice(_peripheriques_de_la_machine())
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    return faux


def test_un_seul_appel_pose_le_micro_et_la_sortie_ensemble(client):
    """Si l'assertion tombe, le bouton « parler et écouter dans mes lunettes » laisse un demi-réglage :
    micro des lunettes posé et sortie restée ailleurs, donc une IRIS muette pour son porteur."""
    reponse = client.patch(
        "/api/glasses/prefs",
        json={"audio_input_device": MICRO_LUNETTES_COMPLET, "audio_output_device": SORTIE_LUNETTES_MAINS_LIBRES},
    )
    assert reponse.status_code == 200
    reglages = client.get("/api/settings").json()
    assert reglages["audio_input_device"] == MICRO_LUNETTES_COMPLET
    assert reglages["audio_output_device"] == SORTIE_LUNETTES_MAINS_LIBRES


def test_la_sortie_demandee_explicitement_gagne_sur_le_rattrapage_automatique(client):
    """Si l'assertion tombe, le serveur réécrit en douce une valeur que l'interface vient de poser :
    l'écran afficherait un choix que la machine n'applique pas."""
    reponse = client.patch(
        "/api/glasses/prefs",
        # micro mains libres + sortie stéréo : combinaison que le serveur a tendance à « corriger » tout seul.
        json={"audio_input_device": MICRO_LUNETTES_COMPLET, "audio_output_device": SORTIE_LUNETTES_STEREO},
    )
    assert reponse.status_code == 200
    assert client.get("/api/settings").json()["audio_output_device"] == SORTIE_LUNETTES_STEREO


def test_la_valeur_vide_veut_dire_peripherique_par_defaut_du_systeme(client):
    """Si l'assertion tombe, le choix « je parle dans le micro du PC » ne peut plus s'exprimer :
    une chaîne vide doit être acceptée et STOCKÉE, pas ignorée comme un champ absent."""
    client.patch("/api/glasses/prefs", json={"audio_input_device": MICRO_LUNETTES_COMPLET})
    reponse = client.patch(
        "/api/glasses/prefs",
        json={"audio_input_device": "", "audio_output_device": SORTIE_LUNETTES_STEREO},
    )
    assert reponse.status_code == 200
    reglages = client.get("/api/settings").json()
    assert reglages["audio_input_device"] == ""  # "" = micro par défaut du système
    assert reglages["audio_output_device"] == SORTIE_LUNETTES_STEREO


def test_revenir_au_pc_efface_les_deux_reglages_dun_coup(client):
    """Si l'assertion tombe, retirer ses lunettes laisse IRIS attachée à un périphérique absent :
    elle écouterait et parlerait dans un point de terminaison mort, sans le dire."""
    client.patch(
        "/api/glasses/prefs",
        json={"audio_input_device": MICRO_LUNETTES_COMPLET, "audio_output_device": SORTIE_LUNETTES_MAINS_LIBRES},
    )
    client.patch("/api/glasses/prefs", json={"audio_input_device": "", "audio_output_device": ""})
    reglages = client.get("/api/settings").json()
    assert reglages["audio_input_device"] == "" and reglages["audio_output_device"] == ""


def test_regler_seulement_le_micro_des_lunettes_entraine_la_sortie_des_lunettes(client):
    """Filet du réglage manuel (les deux listes déroulantes repliées) : si l'assertion tombe,
    choisir le micro des lunettes seul laisse la sortie sur le haut-parleur du PC, alors que
    Windows vient justement d'éteindre la stéréo du casque en ouvrant ce micro."""
    reponse = client.patch("/api/glasses/prefs", json={"audio_input_device": MICRO_LUNETTES_COMPLET})
    assert reponse.status_code == 200
    sortie = client.get("/api/settings").json()["audio_output_device"]
    # le rattrapage doit viser le profil mains libres du MÊME casque, pas la stéréo
    assert "Hands-Free" in sortie and sortie.startswith("Casque (M01 Pro_F444")


def test_la_liste_des_peripheriques_rend_les_lignes_brutes_que_l_interface_doit_regrouper(
    client, peripheriques_simules
):
    """Si l'assertion tombe, l'interface a construit ses deux boutons sur une liste imaginaire.

    Le contrat est déplaisant mais réel : /api/voice/devices renvoie des chaînes nues, un même
    casque apparaît plusieurs fois, un nom sur deux est tronqué à 31 caractères et une entrée est
    une chaîne de ressource du pilote. C'est à l'écran de regrouper et de nettoyer.
    """
    corps = client.get("/api/voice/devices").json()
    micros, sorties = corps["devices"], corps["outputs"]

    # le même micro, plusieurs fois, sous deux orthographes : le regroupement de l'interface est indispensable
    assert micros.count(MICRO_LUNETTES_COMPLET) >= 2
    assert MICRO_LUNETTES_TRONQUE in micros
    assert NOM_BRUT_DU_PILOTE in micros  # entrée illisible : l'interface doit l'écarter, pas l'afficher

    # côté sorties, le serveur déduplique par nom mais laisse les deux profils du casque côte à côte
    assert sorties.count(SORTIE_LUNETTES_STEREO) == 1
    # la sortie mains libres porte exactement le même nom tronqué que le micro mains libres
    assert MICRO_LUNETTES_TRONQUE in sorties


def test_les_deux_profils_du_casque_partagent_un_prefixe_commun(peripheriques_simules):
    """Ce préfixe est la seule chose qui relie « Stereo » et « Hands-Free » à un même casque.

    Si l'assertion tombe, l'interface ne peut plus apparier les deux profils et l'utilisateur
    retombe sur quatre listes déroulantes et un savoir Bluetooth qu'il n'a pas à posséder.
    """
    def base(nom: str) -> str:
        return nom.split(" Hands-Free")[0].split(" Stereo)")[0]

    assert base(MICRO_LUNETTES_COMPLET) == base(SORTIE_LUNETTES_STEREO) == "Casque (M01 Pro_F444"
    # et le préfixe stocké pour la sortie mains libres est bien contenu dans les deux orthographes
    assert SORTIE_LUNETTES_MAINS_LIBRES in MICRO_LUNETTES_COMPLET
    assert SORTIE_LUNETTES_MAINS_LIBRES in MICRO_LUNETTES_TRONQUE
