"""Stockage des clés API des agents externes. Jamais exposées au renderer.
Coffre système (keyring) en priorité, sinon fichier chiffré AES-256-GCM."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .crypto import Crypto

log = logging.getLogger("iris.secrets")
SERVICE = "IRIS"


class SecretStore:
    def __init__(self, crypto: Crypto, data_dir: Path, use_keyring: bool = True):
        self._crypto = crypto
        self._file = data_dir / "secrets.enc"
        self._use_keyring = use_keyring and self._probe_keyring()

    @staticmethod
    def _probe_keyring() -> bool:
        try:
            import keyring

            keyring.set_password(SERVICE, "probe", "ok")
            ok = keyring.get_password(SERVICE, "probe") == "ok"
            try:
                keyring.delete_password(SERVICE, "probe")
            except Exception:
                pass
            return ok
        except Exception as exc:
            log.warning("keyring indisponible, repli sur fichier chiffré: %s", exc)
            return False

    @property
    def backend(self) -> str:
        return "keyring" if self._use_keyring else "encrypted-file"

    def _read_file(self) -> dict:
        if not self._file.exists():
            return {}
        try:
            return json.loads(self._crypto.decrypt(self._file.read_bytes()))
        except Exception:
            return {}

    def _write_file(self, data: dict) -> None:
        self._file.write_bytes(self._crypto.encrypt(json.dumps(data)))

    def set_api_key(self, agent: str, key: str) -> None:
        key = (key or "").strip()
        if not key:
            self.delete_api_key(agent)
            return
        if self._use_keyring:
            import keyring

            keyring.set_password(SERVICE, f"api-key:{agent}", key)
        else:
            data = self._read_file()
            data[agent] = key
            self._write_file(data)

    def get_api_key(self, agent: str) -> str | None:
        if self._use_keyring:
            try:
                import keyring

                return keyring.get_password(SERVICE, f"api-key:{agent}")
            except Exception:
                return None
        return self._read_file().get(agent)

    def delete_api_key(self, agent: str) -> None:
        if self._use_keyring:
            try:
                import keyring

                keyring.delete_password(SERVICE, f"api-key:{agent}")
            except Exception:
                pass
        else:
            data = self._read_file()
            data.pop(agent, None)
            self._write_file(data)

    # --- comptes web (identifiant + mot de passe d'un site) ---
    def set_site(self, name: str, username: str, password: str) -> None:
        payload = json.dumps({"username": username or "", "password": password or ""})
        if self._use_keyring:
            import keyring

            keyring.set_password(SERVICE, f"site:{name}", payload)
        else:
            data = self._read_file()
            data[f"site:{name}"] = payload
            self._write_file(data)

    def get_site(self, name: str) -> dict | None:
        raw = None
        if self._use_keyring:
            try:
                import keyring

                raw = keyring.get_password(SERVICE, f"site:{name}")
            except Exception:
                raw = None
        else:
            raw = self._read_file().get(f"site:{name}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def delete_site(self, name: str) -> None:
        if self._use_keyring:
            try:
                import keyring

                keyring.delete_password(SERVICE, f"site:{name}")
            except Exception:
                pass
        else:
            data = self._read_file()
            data.pop(f"site:{name}", None)
            self._write_file(data)

    def has_api_key(self, agent: str) -> bool:
        return bool(self.get_api_key(agent))

    @staticmethod
    def mask(key: str | None) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "••••"
        return f"{key[:4]}…{key[-4:]}"
