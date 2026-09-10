"""Caméra des lunettes VELA — on verrouille ici la DISCIPLINE d'honnêteté du module.

La caméra est la fonction phare, mais son protocole de trame n'est pas encore prouvé sur le vrai
matériel (voir lunettes_camera.py + docs/LUNETTES-CAMERA-PROTOCOLE.md). Ces tests garantissent que,
tant que ce n'est pas confirmé, IRIS :
  - refuse proprement sur une paire SANS caméra (pas de service ae00) — CameraIndisponible ;
  - refuse d'écrire une trame non prouvée si l'exploration n'est pas activée — ProtocoleNonConfirme ;
  - ne prétend JAMAIS une image qu'elle n'a pas reçue (assembler_image rend None sans marqueurs JPEG).

Aucun matériel requis : on imite GlassesService juste assez (un _on_ble qui exécute la coroutine
en ligne, un client BLE factice avec ou sans les caractéristiques ae01/ae02).
"""
from __future__ import annotations

import asyncio

import pytest

from iris import lunettes_camera
from iris.lunettes_camera import (
    CameraIndisponible,
    CameraLunettes,
    ProtocoleNonConfirme,
    _CollecteurFichier,
)


# --------------------------------------------------------------------- doublures BLE
class _FakeChar:
    def __init__(self, uuid: str, props=("write",)):
        self.uuid = uuid
        self.properties = list(props)


class _FakeService:
    def __init__(self, chars):
        self.characteristics = chars


class _FakeClient:
    def __init__(self, services, connected=True):
        self.services = services
        self.is_connected = connected


class _FakeUser:
    def __init__(self, exploration=False):
        self.lunettes_exploration = exploration


class _FakeSettings:
    def __init__(self, exploration=False, data_dir=None):
        self.user = _FakeUser(exploration)
        self.data_dir = data_dir


class _FakeGlasses:
    """Imite GlassesService : _on_ble exécute la coroutine directement (pas de thread Bleak en test)."""

    def __init__(self, client, settings):
        self.client = client
        self.settings = settings

    async def _on_ble(self, coro):
        return await coro

    def _on_notify(self, sender, data):  # présent pour le réabonnement
        pass


def _client_camera():
    write = _FakeChar(lunettes_camera.WRITE_UUID, ("write", "write-without-response"))
    notify = _FakeChar(lunettes_camera.NOTIFY_UUID, ("notify",))
    return _FakeClient([_FakeService([write, notify])])


def _client_audio():
    # Paire audio : aucun service ae00, donc ni ae01 ni ae02. Une autre caractéristique quelconque.
    autre = _FakeChar("0000de5b-0000-1000-8000-00805f9b34fb", ("notify",))
    return _FakeClient([_FakeService([autre])])


# --------------------------------------------------------------------- structure de trame
def test_fabriquer_trame_structure():
    """La trame caméra est bien celle documentée comme HYPOTHÈSE : 0xFE | type | len(2 LE) | crc(2) | payload.
    On fige la forme pour qu'une régression soit visible — sans prétendre qu'elle est confirmée."""
    trame = lunettes_camera.fabriquer_trame_camera(lunettes_camera.PAYLOAD_PHOTO)
    assert trame[0] == 0xFE
    assert trame[1] == lunettes_camera.TYPE_CAMERA
    # longueur du payload sur 2 octets, petit-boutiste
    assert int.from_bytes(trame[2:4], "little") == len(lunettes_camera.PAYLOAD_PHOTO)
    # les derniers octets sont la charge utile
    assert trame.endswith(lunettes_camera.PAYLOAD_PHOTO)


# --------------------------------------------------------------------- reconstitution honnête
def test_assembler_image_sans_marqueurs_rend_none():
    """Sans bornes JPEG (FF D8 … FF D9), on ne rend RIEN — jamais une image inventée."""
    c = _CollecteurFichier()
    c.paquets = [b"\x00\x11\x22\x33", b"pas un jpeg"]
    assert c.assembler_image() is None


def test_assembler_image_extrait_jpeg_plausible():
    """Avec des bornes JPEG et une taille plausible, on extrait le flux entre FF D8 FF et le dernier FF D9."""
    corps = b"\xff\xd8\xff" + b"\x42" * 700 + b"\xff\xd9"
    c = _CollecteurFichier()
    c.paquets = [b"\xfe\x0d\x00", corps[:300], corps[300:]]  # un « en-tête » parasite + 2 paquets
    image = c.assembler_image()
    assert image is not None
    assert image.startswith(b"\xff\xd8\xff") and image.endswith(b"\xff\xd9")


# --------------------------------------------------------------------- refus honnêtes
def test_photo_refuse_sur_paire_sans_camera():
    """Paire audio (pas de ae01/ae02) : CameraIndisponible, message clair, aucune écriture."""
    glasses = _FakeGlasses(_client_audio(), _FakeSettings(exploration=False))
    cam = CameraLunettes(glasses)
    with pytest.raises(CameraIndisponible):
        asyncio.run(cam.prendre_photo())


def test_photo_refuse_sans_exploration_meme_avec_camera():
    """Interface caméra présente MAIS en-tête de trame non confirmé + exploration désactivée :
    on refuse d'écrire des octets devinés. C'est la garde qui protège la puce."""
    glasses = _FakeGlasses(_client_camera(), _FakeSettings(exploration=False))
    cam = CameraLunettes(glasses)
    with pytest.raises(ProtocoleNonConfirme):
        asyncio.run(cam.prendre_photo())


def test_photo_refuse_si_non_connectees():
    """Client déconnecté : CameraIndisponible, on ne tente rien."""
    glasses = _FakeGlasses(_FakeClient([], connected=False), _FakeSettings())
    cam = CameraLunettes(glasses)
    with pytest.raises(CameraIndisponible):
        asyncio.run(cam.prendre_photo())
