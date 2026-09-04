"""Chiffrement au repos : AES-256-GCM. Clé maîtresse dans le coffre du système (keyring),
avec repli sur un fichier local restreint si le coffre est indisponible."""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("iris.crypto")

SERVICE = "IRIS"
MASTER_KEY_NAME = "master-key"
AAD = b"iris-v1"


def _keyring_get() -> bytes | None:
    try:
        import keyring

        value = keyring.get_password(SERVICE, MASTER_KEY_NAME)
        return base64.b64decode(value) if value else None
    except Exception as exc:  # backend absent, coffre verrouillé...
        log.warning("keyring indisponible en lecture: %s", exc)
        return None


def _keyring_set(key: bytes) -> bool:
    try:
        import keyring

        keyring.set_password(SERVICE, MASTER_KEY_NAME, base64.b64encode(key).decode())
        return _keyring_get() == key
    except Exception as exc:
        log.warning("keyring indisponible en écriture: %s", exc)
        return False


def load_master_key(data_dir: Path, use_keyring: bool = True) -> tuple[bytes, str]:
    """Retourne (clé 32 octets, source) ; source = 'keyring' ou 'file'."""
    if use_keyring:
        key = _keyring_get()
        if key and len(key) == 32:
            return key, "keyring"
    fallback = data_dir / ".master.key"
    if fallback.exists():
        raw = base64.b64decode(fallback.read_text().strip())
        if len(raw) == 32:
            return raw, "file"
    key = AESGCM.generate_key(bit_length=256)
    if use_keyring and _keyring_set(key):
        return key, "keyring"
    fallback.write_text(base64.b64encode(key).decode())
    try:
        os.chmod(fallback, 0o600)
    except OSError:
        pass
    log.warning("Clé maîtresse stockée dans un fichier local (coffre système indisponible).")
    return key, "file"


class Crypto:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("La clé AES-256 doit faire 32 octets")
        self._aes = AESGCM(key)

    def encrypt(self, text: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, text.encode("utf-8"), AAD)

    def decrypt(self, blob: bytes | None) -> str:
        if not blob:
            return ""
        blob = bytes(blob)
        return self._aes.decrypt(blob[:12], blob[12:], AAD).decode("utf-8")
