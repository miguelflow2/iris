"""Actions sur l'ordinateur (contrôle vocal) : applications, fichiers, commandes, capture d'écran, état système.
Fonctions bloquantes : à appeler via asyncio.to_thread."""
from __future__ import annotations

import base64
import ctypes
import io
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

KNOWN_APPS: dict[str, list[str]] = {
    "vs code": ["code"], "vscode": ["code"], "visual studio code": ["code"], "code": ["code"],
    "cursor": ["cursor"],
    "chrome": ["chrome"], "google chrome": ["chrome"],
    "edge": ["msedge"], "microsoft edge": ["msedge"],
    "firefox": ["firefox"],
    "bloc-notes": ["notepad"], "bloc notes": ["notepad"], "notepad": ["notepad"],
    "explorateur": ["explorer"], "explorateur de fichiers": ["explorer"], "explorer": ["explorer"],
    "terminal": ["wt", "powershell"], "powershell": ["powershell"], "invite de commande": ["cmd"], "cmd": ["cmd"],
    "calculatrice": ["calc"], "calculator": ["calc"], "calc": ["calc"],
    "paint": ["mspaint"],
    "word": ["winword"], "excel": ["excel"], "powerpoint": ["powerpnt"], "outlook": ["outlook"],
    "spotify": ["spotify"], "discord": ["discord"], "slack": ["slack"], "teams": ["ms-teams", "teams"],
    "paramètres": ["ms-settings:"], "parametres": ["ms-settings:"], "settings": ["ms-settings:"],
    "gestionnaire des tâches": ["taskmgr"], "task manager": ["taskmgr"],
    "navigateur": ["__browser__"], "navigateur internet": ["__browser__"], "browser": ["__browser__"], "internet": ["__browser__"],
    "youtube": ["https://www.youtube.com"], "google": ["https://www.google.com"], "gmail": ["https://mail.google.com"],
    "musique": ["spotify"], "bloc note": ["notepad"], "notes": ["notepad"], "vlc": ["vlc"], "steam": ["steam"], "whatsapp": ["whatsapp"],
}

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "AppData", "$RECYCLE.BIN", ".cache", "Library"}


def _normalize(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


_APP_NOISE = ("l'application", "l'app", "application", "app", "le", "la", "les", "mon", "ma", "mes", "un", "une", "de", "du", "web", "windows", "microsoft")


def _resolve_app(name: str) -> list[str]:
    """Nom parlé ('lance-moi mon navigateur web') -> commandes candidates."""
    norm = _normalize(name)
    words = [w for w in norm.replace("-", " ").split() if w not in _APP_NOISE]
    core = " ".join(words) or norm
    if core in KNOWN_APPS:
        return KNOWN_APPS[core]
    # Correspondance par mots entiers, pas par sous-chaîne : « WordPad » ouvrait Word, « Sticky Notes » le
    # Bloc-notes, et « lance une commande » lançait l'invite de commandes. Les clés les plus longues d'abord.
    core_words = set(core.split())
    for key, cmds in sorted(KNOWN_APPS.items(), key=lambda kv: -len(kv[0])):
        key_words = set(key.split())
        if key_words and (key_words <= core_words or core_words <= key_words):
            return cmds
    return [core or name]


_OCR_OK: bool | None = None


def ocr_available() -> bool:
    """L'OCR est-il utilisable sur cette machine ? Testé une seule fois (chargement de DLL natives).
    Sans ce test, une panne d'OCR se traduisait par un message Windows incompréhensible en plein milieu
    d'une commande, et le modèle se mettait à cliquer à l'aveugle."""
    global _OCR_OK
    if _OCR_OK is None:
        try:
            import numpy as _np
            from rapidocr_onnxruntime import RapidOCR

            RapidOCR()(_np.zeros((32, 32, 3), dtype=_np.uint8))
            _OCR_OK = True
        except Exception as exc:
            _OCR_OK = False
            log.warning("OCR indisponible sur cette machine : %s", exc)
    return _OCR_OK


def confident_app(name: str) -> str | None:
    """Nom d'application dont on est sûr, sinon None (le modèle tranchera).
    Sert aux commandes reconnues localement : mieux vaut ne rien affirmer que d'ouvrir la mauvaise application."""
    import difflib

    demande = _normalize(name).replace("-", " ")
    if not demande:
        return None
    if demande in KNOWN_APPS or _normalize(name) in KNOWN_APPS:
        return name  # alias connu et exact (« navigateur », « bloc-notes »…)
    try:
        from .apps import index

        # On n'utilise l'index que s'il est déjà construit : le construire ici (menu Démarrer, Store, Steam)
        # coûterait plusieurs secondes en plein milieu d'une commande vocale.
        if not index.apps:
            return None
        hit = index.best(name)
    except Exception:
        return None
    if not hit:
        return None
    cible = _normalize(hit.get("name") or "").replace("-", " ")
    if cible == demande or demande in cible.split() or difflib.SequenceMatcher(None, demande, cible).ratio() >= 0.85:
        return hit.get("name")
    return None


def open_application(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("nom d'application manquant")
    candidates = _resolve_app(name)
    # index des applications installées (menu Démarrer, Store, Steam) : lancement par le vrai nom
    if candidates == [_normalize(name)] or candidates == [name]:
        from .apps import index

        hit = index.best(name)
        if hit:
            return index.launch(hit)
    if candidates == ["__browser__"]:
        import webbrowser

        webbrowser.open("https://www.google.com")
        return "Navigateur ouvert."
    errors = []
    for cand in candidates:
        try:
            if IS_WIN:
                # 'start' passe par ShellExecute : résout PATH, App Paths (chrome, code…) et les URI (ms-settings:)
                proc = subprocess.run(
                    ["cmd", "/c", "start", "", cand], capture_output=True, text=True, timeout=10
                )
                if proc.returncode == 0:
                    return f"{name} lancé."
                errors.append(proc.stderr.strip() or f"code {proc.returncode}")
            elif IS_MAC:
                proc = subprocess.run(["open", "-a", cand], capture_output=True, text=True, timeout=10)
                if proc.returncode == 0:
                    return f"{name} lancé."
                errors.append(proc.stderr.strip())
            else:
                subprocess.Popen([cand], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"{name} lancé."
        except FileNotFoundError as exc:
            errors.append(str(exc))
        except subprocess.TimeoutExpired:
            return f"{name} : lancement demandé (pas de confirmation du système)."
    raise RuntimeError(
        f"Impossible de lancer « {name} » : {'; '.join(e for e in errors if e) or 'introuvable'}. "
        "Utilise open_url pour un site, ou run_command avec le chemin exact de l'application."
    )


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))


def open_path(path: str) -> str:
    target = _expand(path)
    if not target.exists():
        raise FileNotFoundError(f"Chemin introuvable : {target}")
    if IS_WIN:
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return f"Ouvert : {target}"


def list_directory(path: str, limit: int = 200) -> list[dict]:
    target = _expand(path or "~")
    if not target.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {target}")
    items = []
    with os.scandir(target) as it:
        for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                stat = entry.stat()
                items.append(
                    {
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": None if entry.is_dir() else stat.st_size,
                        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    }
                )
            except OSError:
                continue
            if len(items) >= limit:
                break
    return items


def search_files(query: str, folder: str | None = None, max_results: int = 20, max_visited: int = 60000) -> list[str]:
    query_low = (query or "").lower().strip()
    if not query_low:
        raise ValueError("requête vide")
    root = _expand(folder) if folder else Path.home()
    if not root.exists():
        raise FileNotFoundError(f"Dossier introuvable : {root}")
    results: list[str] = []
    visited = 0
    stack = [root]
    while stack and len(results) < max_results and visited < max_visited:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    visited += 1
                    if entry.name in SKIP_DIRS or entry.name.startswith("."):
                        continue
                    if query_low in entry.name.lower():
                        results.append(str(Path(current) / entry.name))
                        if len(results) >= max_results:
                            break
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(current) / entry.name)
        except (PermissionError, FileNotFoundError, OSError):
            continue
    return results


def run_command(command: str, timeout: int = 60) -> dict:
    command = (command or "").strip()
    if not command:
        raise ValueError("commande vide")
    if IS_WIN:
        args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        args = ["/bin/sh", "-c", command]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"code": -1, "output": f"Commande interrompue après {timeout}s."}
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    output = output.strip()
    if len(output) > 6000:
        output = output[:6000] + "\n…(sortie tronquée)"
    return {"code": proc.returncode, "output": output or "(aucune sortie)"}


def take_screenshot(max_width: int = 1568, quality: int = 80) -> dict:
    """Capture l'écran principal → JPEG base64 redimensionné (limite de taille des API vision)."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"media_type": "image/jpeg", "data": data, "width": image.width, "height": image.height}


def active_window_title() -> str:
    if IS_WIN:
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""
    return ""


def system_status() -> dict:
    info: dict = {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.node(),
        "python": platform.python_version(),
        "active_window": active_window_title(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        import psutil

        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        info["memory"] = {"used_gb": round(mem.used / 1e9, 1), "total_gb": round(mem.total / 1e9, 1), "percent": mem.percent}
        disk = psutil.disk_usage(str(Path.home().anchor or "/"))
        info["disk"] = {"free_gb": round(disk.free / 1e9, 1), "total_gb": round(disk.total / 1e9, 1)}
        battery = psutil.sensors_battery()
        if battery:
            info["battery"] = {"percent": battery.percent, "plugged": battery.power_plugged}
        info["uptime_hours"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    except Exception:
        pass
    return info


def lock_computer() -> str:
    if IS_WIN:
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "Session verrouillée."
    if IS_MAC:
        subprocess.Popen(["pmset", "displaysleepnow"])
        return "Écran mis en veille."
    subprocess.Popen(["loginctl", "lock-session"])
    return "Session verrouillée."


# ---------------------------------------------------------------------------
# Web, médias, fichiers, clavier
# ---------------------------------------------------------------------------
DANGEROUS_PATTERNS = (
    r"\brm\b", r"\bdel\b", r"\berase\b", r"remove-item", r"\brmdir\b", r"\brd\b", r"\bformat\b", r"\bdiskpart\b",
    r"shutdown", r"restart-computer", r"stop-computer", r"\breg\b", r"regedit", r"set-itemproperty .*hklm",
    r"\bnet user\b", r"\bicacls\b", r"\btakeown\b", r"\bbcdedit\b", r"\bcipher\b", r"\bmkfs", r"\bdd\b",
    r"\bchmod\b", r"\bchown\b", r"\bsudo\b", r"invoke-webrequest .*\|\s*iex", r"\biex\b", r"curl .*\|\s*(sh|bash)",
    r"\bgit (push|reset --hard|clean)", r"\bnpm publish\b", r"\bpip uninstall\b", r"taskkill", r"stop-process",
    r"set-executionpolicy", r"\bschtasks\b", r"\bwmic\b", r"\bpowercfg\b",
)


def is_dangerous_command(command: str) -> bool:
    import re

    low = (command or "").lower()
    return any(re.search(p, low) for p in DANGEROUS_PATTERNS)


def open_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("URL manquante")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    import webbrowser

    webbrowser.open(url)
    return f"Ouvert dans le navigateur : {url}"


def youtube_search(query: str, max_results: int = 3) -> list[dict]:
    """Recherche YouTube via yt-dlp (métadonnées seulement, rien n'est téléchargé)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "noplaylist": True, "socket_timeout": 8, "retries": 1, "extractor_retries": 1}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
    out = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        vid = entry.get("id")
        out.append(
            {
                "id": vid,
                "title": entry.get("title"),
                "channel": entry.get("channel") or entry.get("uploader"),
                "duration": entry.get("duration"),
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return out


def play_youtube(query: str) -> dict:
    results = youtube_search(query, max_results=3)
    if not results:
        raise RuntimeError(f"Aucune vidéo trouvée pour « {query} ».")
    first = results[0]
    open_url(first["url"] + "&autoplay=1")
    return {"playing": first, "alternatives": results[1:]}


MAX_READ = 200_000


def read_file(path: str, max_chars: int = MAX_READ) -> str:
    target = _expand(path)
    if not target.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {target}")
    if target.stat().st_size > 5_000_000:
        raise ValueError("Fichier trop volumineux (> 5 Mo).")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…(tronqué, {len(text)} caractères au total)"
    return text


def write_file(path: str, content: str, append: bool = False) -> str:
    target = _expand(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    with open(target, "a" if append else "w", encoding="utf-8", newline="") as fh:
        fh.write(content or "")
    verb = "complété" if append else ("remplacé" if existed else "créé")
    return f"Fichier {verb} : {target} ({len(content or '')} caractères)"


def type_text(text: str, interval: float = 0.01) -> str:
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.write(text or "", interval=interval) if (text or "").isascii() else _type_unicode(text)
    return f"Texte saisi ({len(text or '')} caractères)."


def _type_unicode(text: str) -> None:
    """pyautogui.write ne gère pas les accents : on passe par le presse-papiers + Ctrl+V."""
    import pyautogui

    try:
        import subprocess as _sp

        if IS_WIN:
            _sp.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], input=text, text=True, timeout=5)
        elif IS_MAC:
            _sp.run(["pbcopy"], input=text, text=True, timeout=5)
        else:
            _sp.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=5)
        pyautogui.hotkey("command" if IS_MAC else "ctrl", "v")
    except Exception:
        for ch in text:
            pyautogui.write(ch) if ch.isascii() else pyautogui.typewrite(ch)


# ---------------------------------------------------------------------------
# Souris, écran et OCR (contrôle complet de l'écran)
# ---------------------------------------------------------------------------
_SHOT_MAX_WIDTH = 1568


def screen_size() -> dict:
    import pyautogui

    w, h = pyautogui.size()
    scale = min(1.0, _SHOT_MAX_WIDTH / w)
    return {"width": w, "height": h, "screenshot_width": int(w * scale), "screenshot_height": int(h * scale), "scale": round(scale, 4)}


def _to_screen(x: float, y: float, space: str = "screenshot") -> tuple[int, int]:
    """Convertit des coordonnées exprimées dans la capture (réduite) en pixels écran réels."""
    if space == "screen":
        return int(x), int(y)
    info = screen_size()
    return int(x / info["scale"]), int(y / info["scale"])


def mouse_move(x: float, y: float, space: str = "screenshot") -> str:
    import pyautogui

    sx, sy = _to_screen(x, y, space)
    pyautogui.moveTo(sx, sy, duration=0.15)
    return f"Souris déplacée en ({sx}, {sy})."


def mouse_click(x: float | None = None, y: float | None = None, button: str = "left", clicks: int = 1, space: str = "screenshot") -> str:
    import pyautogui

    button = (button or "left").lower()
    if button not in ("left", "right", "middle"):
        button = "left"
    if x is not None and y is not None:
        sx, sy = _to_screen(x, y, space)
        pyautogui.moveTo(sx, sy, duration=0.12)
        pyautogui.click(sx, sy, clicks=max(1, min(int(clicks or 1), 3)), interval=0.08, button=button)
        return f"Clic {button}{' double' if clicks == 2 else ''} en ({sx}, {sy})."
    pyautogui.click(clicks=max(1, min(int(clicks or 1), 3)), interval=0.08, button=button)
    return f"Clic {button} à la position actuelle."


def mouse_drag(x1: float, y1: float, x2: float, y2: float, space: str = "screenshot", duration: float = 0.5) -> str:
    import pyautogui

    a = _to_screen(x1, y1, space)
    b = _to_screen(x2, y2, space)
    pyautogui.moveTo(*a, duration=0.1)
    pyautogui.dragTo(b[0], b[1], duration=max(0.2, min(float(duration or 0.5), 3.0)), button="left")
    return f"Glissé de {a} à {b}."


def scroll(amount: int = -5, x: float | None = None, y: float | None = None, space: str = "screenshot") -> str:
    import pyautogui

    if x is not None and y is not None:
        sx, sy = _to_screen(x, y, space)
        pyautogui.moveTo(sx, sy, duration=0.1)
    pyautogui.scroll(int(amount or -5))
    return f"Défilement de {amount} crans."


_ocr_engine = None
_ocr_cache: dict = {"at": 0.0, "items": []}


def ocr_screen(max_width: int = 1280, cache_seconds: float = 2.0) -> list[dict]:
    """Lit le texte à l'écran (OCR hors-ligne). Coordonnées renvoyées dans l'espace de la capture (échelle screen_size)."""
    global _ocr_engine
    if time.time() - _ocr_cache["at"] < cache_seconds and _ocr_cache["items"]:
        return _ocr_cache["items"]
    import numpy as np
    from PIL import Image

    try:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _ocr_engine = RapidOCR()
    except Exception as exc:
        raise RuntimeError(f"OCR indisponible : {exc}")
    shot = take_screenshot(max_width=_SHOT_MAX_WIDTH, quality=85)
    image = Image.open(io.BytesIO(base64.b64decode(shot["data"])))
    ratio = 1.0
    if image.width > max_width:
        ratio = image.width / max_width
        image = image.resize((max_width, int(image.height / ratio)))
    result, _ = _ocr_engine(np.array(image))
    items = []
    for box, text, score in result or []:
        xs = [p[0] * ratio for p in box]
        ys = [p[1] * ratio for p in box]
        items.append({
            "text": text, "confidence": round(float(score), 2),
            "x": int((min(xs) + max(xs)) / 2), "y": int((min(ys) + max(ys)) / 2),
            "left": int(min(xs)), "top": int(min(ys)), "right": int(max(xs)), "bottom": int(max(ys)),
        })
    _ocr_cache.update({"at": time.time(), "items": items})
    return items


def _norm_text(t: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in t if ch.isalnum())


def find_on_screen(text: str, limit: int = 8) -> list[dict]:
    """Zones de l'écran dont le texte contient `text` (insensible à la casse, aux accents et aux espaces)."""
    wanted = _norm_text(text)
    if not wanted:
        raise ValueError("texte à chercher vide")
    hits = [it for it in ocr_screen() if wanted in _norm_text(it["text"])]
    if not hits:  # tolérance aux fautes d'OCR
        import difflib

        for it in ocr_screen():
            if difflib.SequenceMatcher(None, wanted, _norm_text(it["text"])).ratio() >= 0.8:
                hits.append(it)
    hits.sort(key=lambda h: (-(h["confidence"]), h["top"], h["left"]))
    return hits[:limit]


def click_text(text: str, button: str = "left", clicks: int = 1, occurrence: int = 1) -> str:
    hits = find_on_screen(text, limit=10)
    if not hits:
        raise RuntimeError(f"Texte « {text} » introuvable à l'écran.")
    hit = hits[max(0, min(len(hits) - 1, int(occurrence or 1) - 1))]
    _ocr_cache["at"] = 0.0  # l'écran va changer
    return mouse_click(hit["x"], hit["y"], button=button, clicks=clicks) + f" (sur « {hit['text']} »)"


def press_keys(combo: str) -> str:
    """combo : 'enter', 'ctrl+l', 'alt+tab', 'win+d', 'ctrl+shift+t'…"""
    import pyautogui

    keys = [k.strip().lower() for k in (combo or "").replace(" ", "").split("+") if k.strip()]
    if not keys:
        raise ValueError("combinaison vide")
    alias = {"windows": "win", "cmd": "command", "control": "ctrl", "return": "enter", "esc": "escape", "échap": "escape"}
    keys = [alias.get(k, k) for k in keys]
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return f"Touches envoyées : {'+'.join(keys)}"
