"""Index des applications installées : raccourcis du menu Démarrer / bureau et jeux Steam.
Permet de lancer n'importe quel programme ou jeu par son nom, sans deviner."""
from __future__ import annotations

import difflib
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("iris.apps")

SKIP_WORDS = ("uninstall", "désinstall", "desinstall", "readme", "help", "aide", "documentation", "website", "site web")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


class AppIndex:
    def __init__(self):
        self.apps: list[dict] = []
        self.built_at = 0.0
        self._lock = threading.Lock()
        self._building = False

    # ------------------------------------------------------------------ construction
    def build(self) -> list[dict]:
        with self._lock:
            if self._building:
                return self.apps
            self._building = True
        try:
            found: dict[str, dict] = {}
            for app in self._start_menu():
                found.setdefault(normalize(app["name"]), app)
            for game in self._steam():
                found[normalize(game["name"]) + "|steam"] = game
            for app in self._start_apps():
                found.setdefault(normalize(app["name"]), app)
            self.apps = sorted(found.values(), key=lambda a: a["name"].lower())
            self.built_at = time.time()
            log.info("index applications : %d entrées", len(self.apps))
            return self.apps
        finally:
            self._building = False

    def _start_menu(self) -> list[dict]:
        out: list[dict] = []
        if sys.platform != "win32":
            return out
        roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path.home() / "Desktop",
            Path(os.environ.get("PUBLIC", "")) / "Desktop",
        ]
        for root in roots:
            if not root.is_dir():
                continue
            try:
                for lnk in root.rglob("*.lnk"):
                    name = lnk.stem.strip()
                    low = name.lower()
                    if any(w in low for w in SKIP_WORDS):
                        continue
                    out.append({"name": name, "kind": "shortcut", "path": str(lnk), "folder": lnk.parent.name})
            except Exception as exc:
                log.debug("menu démarrer illisible (%s): %s", root, exc)
        return out

    def _start_apps(self) -> list[dict]:
        """Applications du menu Démarrer (y compris Microsoft Store) via Get-StartApps ; lancement par AppID."""
        out: list[dict] = []
        if sys.platform != "win32":
            return out
        try:
            import json
            import subprocess

            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=25, encoding="utf-8", errors="replace",
            )
            data = json.loads(proc.stdout or "[]")
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = (item.get("Name") or "").strip()
                appid = (item.get("AppID") or "").strip()
                if name and appid and not any(w in name.lower() for w in SKIP_WORDS):
                    out.append({"name": name, "kind": "store", "appid": appid, "launch": f"shell:AppsFolder\\{appid}"})
        except Exception as exc:
            log.debug("Get-StartApps indisponible: %s", exc)
        return out

    def _steam(self) -> list[dict]:
        out: list[dict] = []
        if sys.platform != "win32":
            return out
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                install = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except Exception:
            return out
        libraries = [install]
        vdf = install / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libraries.append(Path(m.group(1).replace("\\\\", "\\")))
        seen = set()
        for lib in libraries:
            apps_dir = lib / "steamapps"
            if not apps_dir.is_dir():
                continue
            for acf in apps_dir.glob("appmanifest_*.acf"):
                try:
                    text = acf.read_text(encoding="utf-8", errors="replace")
                    appid = re.search(r'"appid"\s+"(\d+)"', text)
                    name = re.search(r'"name"\s+"([^"]+)"', text)
                    if appid and name and appid.group(1) not in seen:
                        seen.add(appid.group(1))
                        out.append({"name": name.group(1), "kind": "steam", "appid": appid.group(1), "launch": f"steam://rungameid/{appid.group(1)}"})
                except Exception:
                    continue
        return out

    # ------------------------------------------------------------------ recherche / lancement
    def ensure(self, max_age: float = 3600) -> None:
        if not self.apps or time.time() - self.built_at > max_age:
            self.build()

    def search(self, query: str, limit: int = 8) -> list[dict]:
        self.ensure()
        q = normalize(query)
        if not q:
            return []
        exact = [a for a in self.apps if normalize(a["name"]) == q]
        contains = [a for a in self.apps if q in normalize(a["name"]) and a not in exact]
        contains.sort(key=lambda a: len(a["name"]))
        results = exact + contains
        if len(results) < limit:
            names = {normalize(a["name"]): a for a in self.apps}
            for close in difflib.get_close_matches(q, list(names), n=limit, cutoff=0.6):
                if names[close] not in results:
                    results.append(names[close])
        return results[:limit]

    def best(self, query: str) -> dict | None:
        hits = self.search(query, limit=1)
        return hits[0] if hits else None

    @staticmethod
    def launch(app: dict) -> str:
        target = app.get("launch") or app.get("path")
        if not target:
            raise ValueError("entrée sans cible")
        if sys.platform == "win32":
            if app.get("kind") == "store":
                import subprocess

                subprocess.Popen(["explorer.exe", target])
            else:
                os.startfile(target)  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", target])
        return f"{app['name']} lancé{' (Steam)' if app.get('kind') == 'steam' else ''}."


index = AppIndex()
