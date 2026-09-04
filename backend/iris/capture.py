"""Indicateur de capture logiciel non désactivable : état du micro, de l'écran et de la caméra,
diffusé au process principal Electron qui affiche la pastille flottante."""
from __future__ import annotations

import threading

from .events import EventHub


class CaptureIndicator:
    def __init__(self, hub: EventHub):
        self.hub = hub
        self._lock = threading.Lock()
        self.state = {"mic": False, "screen": False, "camera": False, "listening": False}

    def set(self, **flags: bool) -> dict:
        with self._lock:
            changed = False
            for key, value in flags.items():
                if key in self.state and self.state[key] != bool(value):
                    self.state[key] = bool(value)
                    changed = True
            snapshot = dict(self.state)
        if changed:
            self.hub.publish("capture.state", **snapshot)
        return snapshot

    def pulse_screen(self) -> None:
        """Signale une capture d'écran ponctuelle."""
        with self._lock:
            base = dict(self.state)
        self.hub.publish("capture.state", **{**base, "screen": True})
        self.hub.publish("capture.state", **base)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)
