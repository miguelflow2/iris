"""Actions sur l'ordinateur (contrôle vocal) : applications, fichiers, commandes, capture d'écran, état système.
Fonctions bloquantes : à appeler via asyncio.to_thread."""
from __future__ import annotations

import base64
import ctypes
import io
import logging
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Iterable

# Ce module appelait déjà `log.warning` (panne d'OCR) sans jamais avoir défini de logger : la
# première panne d'OCR aurait levé un NameError à l'intérieur du gestionnaire d'exception.
log = logging.getLogger("iris.pc.actions")

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


# ---------------------------------------------------------------------------
# Le périmètre des fichiers
# ---------------------------------------------------------------------------
# Jusqu'au 6 septembre 2026, write_file, read_file, open_path et run_command prenaient n'importe
# quel chemin tel quel. Le modèle actif est un modèle gratuit et throttlé ; à qui l'on dit
# « corrige mon site », rien n'interdisait de lire `.env` dans le dépôt d'IRIS (clés ElevenLabs
# et de licence), d'écrire dans C:\Windows, ou de lancer PowerShell sans dossier de travail —
# c'est-à-dire DANS le dépôt d'IRIS, puisque c'est de là que tourne le backend. La seule
# protection était la bonne volonté du modèle. Ce bloc est ce qui la remplace.
#
# Il reprend, trait pour trait, les pièges mesurés pour la délégation à OpenCode (opencode.py) :
# ce sont les mêmes chemins, les mêmes jonctions et la même machine.


class HorsPerimetre(PermissionError):
    """Le chemin sort des dossiers où IRIS a le droit d'agir. Le message est la phrase à dire."""


@dataclass(frozen=True)
class Perimetre:
    """Où IRIS a le droit de lire, d'écrire, d'ouvrir et de lancer des commandes.

    `interdites` prime sur `autorisees` : autoriser ~/Downloads ne doit jamais ouvrir le dépôt
    d'IRIS, qui est dedans sur cette machine (Downloads/startup/iris)."""

    autorisees: tuple[Path, ...]
    interdites: tuple[Path, ...]
    projets: Path  # le dossier où IRIS crée ses projets ; le seul où l'on écrit sans confirmation


_VARIABLE_NON_RESOLUE = re.compile(r"%[^%\\/]+%")
_CARACTERE_DE_CONTROLE = re.compile(r"[\x00-\x1f]")
_LECTEUR_RELATIF = re.compile(r"^[A-Za-z]:(?![\\/])")  # « C:foo », et « C: » tout seul

# Les vrais dossiers de l'utilisateur, tels que Windows les range. Sur cette machine, le registre
# dit que Documents est C:\Users\migue\OneDrive\Documents — pas C:\Users\migue\Documents, qui
# existe pourtant aussi. Le nom physique ne change jamais de langue : « Téléchargements » est un
# habillage de l'Explorateur, le dossier s'appelle Downloads.
_DOSSIERS_CONNUS_WINDOWS = {
    "Desktop": "Desktop",
    "Documents": "Personal",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}


def _dossier_connu_windows(cle: str) -> Path | None:
    """Où Windows range vraiment ce dossier (OneDrive, disque secondaire…), ou None."""
    if not IS_WIN:
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        ) as registre:
            valeur, _ = winreg.QueryValueEx(registre, cle)
    except OSError:
        return None
    chemin = os.path.expandvars(str(valeur or ""))
    if not chemin or _VARIABLE_NON_RESOLUE.search(chemin):
        return None
    return Path(chemin)


def dossier_projets() -> Path:
    """~/Documents/IRIS : là où IRIS crée les sites et les applications qu'on lui demande."""
    return Path.home() / "Documents" / "IRIS"


def _resoudre_racines(bruts: Iterable[Path]) -> tuple[Path, ...]:
    resolus: list[Path] = []
    for chemin in bruts:
        try:
            resolus.append(chemin.expanduser().resolve())
        except OSError:
            continue
    return tuple(dict.fromkeys(resolus))


def racines_autorisees_par_defaut() -> tuple[Path, ...]:
    """Le dossier de projets, le Bureau, Documents et Téléchargements — les deux emplacements
    possibles de chacun (celui du registre et celui du profil), parce que Miguel a des fichiers
    dans les deux."""
    maison = Path.home()
    bruts: list[Path] = [dossier_projets()]
    for nom, cle in _DOSSIERS_CONNUS_WINDOWS.items():
        bruts.append(maison / nom)
        connu = _dossier_connu_windows(cle)
        if connu is not None:
            bruts.append(connu)
    return _resoudre_racines(bruts)


def racines_interdites_par_defaut() -> tuple[Path, ...]:
    """Ce qui reste fermé MÊME sous un dossier autorisé : le système, les programmes, AppData (les
    réglages, les clés et le jeton d'IRIS y vivent), les clés SSH, et le dépôt d'IRIS lui-même."""
    maison = Path.home()
    bruts: list[Path] = []
    for variable in ("SystemRoot", "ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "ProgramData"):
        valeur = os.environ.get(variable)
        if valeur:
            bruts.append(Path(valeur))
    for relatif in ("AppData", ".ssh", ".aws", ".gnupg"):
        bruts.append(maison / relatif)
    try:
        from ..config import default_data_dir

        bruts.append(default_data_dir())
    except Exception:  # pragma: no cover - le périmètre ne dépend pas de la configuration
        pass
    try:
        # backend/iris/pc/actions.py -> pc -> iris -> backend -> la racine du dépôt (ou, une fois
        # installé, le dossier de l'application). On ne retient ce dossier que s'il ne CONTIENT pas
        # le profil de l'utilisateur : à une profondeur inattendue, ce calcul rendrait C:\Users, et
        # la liste noire fermerait tout.
        depot = Path(__file__).resolve().parents[3]
        if depot.parent != depot and not _sous(maison, depot):
            bruts.append(depot)
    except (IndexError, OSError):  # pragma: no cover
        pass
    return _resoudre_racines(bruts)


def perimetre_par_defaut() -> Perimetre:
    projets = _resoudre_racines([dossier_projets()])
    return Perimetre(
        autorisees=racines_autorisees_par_defaut(),
        interdites=racines_interdites_par_defaut(),
        projets=projets[0] if projets else dossier_projets(),
    )


# Surcharge : les tests posent ici un périmètre dans un dossier temporaire (qui est sous AppData,
# donc interdit par défaut). None = le périmètre réel de la machine, calculé à chaque appel : il
# suit les variables d'environnement et le registre, et coûte quelques appels au système.
PERIMETRE: Perimetre | None = None


def perimetre_actif() -> Perimetre:
    return PERIMETRE if PERIMETRE is not None else perimetre_par_defaut()


def _sous(cible: Path, racine: Path) -> bool:
    try:
        return cible == racine or cible.is_relative_to(racine)
    except (OSError, ValueError):
        return False


def _normaliser_chemin(brut: str, perimetre: Perimetre) -> Path:
    """Chaîne -> chemin absolu résolu, ou `HorsPerimetre` avec une phrase française.

    Chaque refus correspond à un piège mesuré sur cette machine (Python 3.13, Windows 10)."""
    chemin = (brut or "").strip().strip('"')
    if not chemin:
        raise HorsPerimetre("Aucun chemin n'a été donné. Je ne devine pas quel fichier tu veux.")
    if _CARACTERE_DE_CONTROLE.search(chemin):
        raise HorsPerimetre("Ce chemin contient un caractère de contrôle (retour à la ligne, nul…) : je ne l'accepte pas.")
    plat = chemin.replace("/", "\\")
    if plat.startswith("\\\\?\\") or plat.startswith("\\\\.\\"):
        # Mesuré : Path(r'\\?\C:\...\..\..\Windows').resolve() rend « C:Users\Windows », qui n'est
        # ni le chemin de départ ni un confinement valable. Ce qui casse la normalisation se refuse.
        raise HorsPerimetre(
            "Ce chemin est écrit en notation périphérique (\\\\?\\ ou \\\\.\\). Je ne sais pas le "
            "vérifier de façon fiable, donc je n'y touche pas. Donne-moi le chemin normal."
        )
    if plat.startswith("\\\\"):
        raise HorsPerimetre(
            "Ce chemin est sur un partage réseau. Je ne lis et n'écris que sur cet ordinateur : "
            "ce qui se passe ailleurs ne se surveille pas, et ne se répare pas."
        )
    if _LECTEUR_RELATIF.match(chemin):
        # « C:site » n'est pas C:\site : mesuré, ça se résout contre le dossier courant du backend,
        # c'est-à-dire dans le dépôt d'IRIS.
        raise HorsPerimetre(
            f"« {chemin} » n'est pas un chemin complet : il est relatif au lecteur, pas à sa racine. "
            "Écris-le en entier, avec la barre après les deux-points."
        )
    etendu = os.path.expandvars(os.path.expanduser(chemin))
    if _VARIABLE_NON_RESOLUE.search(etendu):
        # « %USERPROFILE%\site » arrive tel quel quand un modèle recopie une variable d'un fichier de
        # configuration. Non résolue, elle désigne un dossier littéralement nommé « %…% ».
        raise HorsPerimetre(
            f"« {chemin} » contient une variable d'environnement que personne ne connaît. "
            "Donne-moi le chemin complet."
        )
    if IS_WIN:
        pur = PureWindowsPath(etendu)
        if pur.root and not pur.drive:
            # « \site » : enraciné sans lecteur. Joint à un dossier, il en garde le lecteur et en
            # jette le reste (mesuré : Documents/IRIS joint à « \foo » donne C:\foo).
            raise HorsPerimetre(
                f"« {chemin} » commence par une barre sans lecteur : il désigne la racine du disque, "
                "pas un dossier. Écris le chemin complet, ou un chemin relatif à mon dossier de projets."
            )
    candidat = Path(etendu)
    if not candidat.is_absolute():
        # Un chemin relatif se lit depuis le dossier de projets, jamais depuis le dossier courant
        # du backend (le dépôt d'IRIS). « site/index.html » veut dire Documents/IRIS/site/index.html.
        candidat = perimetre.projets / candidat
    try:
        # C'est `resolve()` qui fait le vrai travail : il règle les « .. » (même sur des segments qui
        # n'existent pas encore — mesuré : Documents/IRIS/nouveau/../../../.ssh/x rend
        # C:\Users\migue\.ssh\x), la casse, les noms courts 8.3 (DOCUME~1 -> Documents), les liens
        # symboliques ET les jonctions Windows. On ne s'appuie jamais sur `is_symlink()`, qui rend
        # False sur une jonction — mesuré sur « C:\Users\migue\Application Data », qui pointe vers
        # AppData\Roaming, et sur une jonction créée pour le test.
        return candidat.resolve()
    except OSError as erreur:
        raise HorsPerimetre(f"Je n'arrive pas à vérifier ce chemin : {erreur}") from None


def _verifier_liste_noire(cible: Path, perimetre: Perimetre) -> None:
    for interdit in perimetre.interdites:
        if _sous(cible, interdit):
            raise HorsPerimetre(
                f"Je ne touche pas à « {cible} » : ce dossier est protégé ({interdit}). Il contient "
                "le système, l'application, ou mes propres réglages et mes clés."
            )


def resoudre_dans_perimetre(chemin: str, perimetre: Perimetre | None = None) -> Path:
    """Rend le chemin RÉSOLU si et seulement s'il est dans le périmètre. Sinon lève `HorsPerimetre`.

    Le résultat est le seul chemin utilisé ensuite — jamais la phrase dite par l'utilisateur, jamais
    celle produite par un modèle : on a mesuré qu'elles peuvent désigner deux endroits différents."""
    perimetre = perimetre or perimetre_actif()
    cible = _normaliser_chemin(chemin, perimetre)
    _verifier_liste_noire(cible, perimetre)  # la liste noire d'abord : elle prime
    if not any(_sous(cible, racine) for racine in perimetre.autorisees):
        liste = ", ".join(str(r) for r in perimetre.autorisees[:4]) or "aucun"
        raise HorsPerimetre(
            f"« {cible} » est hors des dossiers où j'ai le droit d'agir ({liste}). "
            "Je n'y lis rien et je n'y écris rien."
        )
    return cible


def dans_dossier_projets(cible: Path, perimetre: Perimetre | None = None) -> bool:
    """Le seul endroit où IRIS écrit un fichier NEUF sans demander : son propre dossier de projets."""
    perimetre = perimetre or perimetre_actif()
    return _sous(cible, perimetre.projets)


def dossier_de_travail(cwd: str | None = None) -> Path:
    """Le dossier où tourne une commande : celui qu'on donne (dans le périmètre), sinon le dossier
    de projets. Jamais le dossier courant du backend — mesuré, c'est le dépôt d'IRIS."""
    perimetre = perimetre_actif()
    if cwd and cwd.strip():
        dossier = resoudre_dans_perimetre(cwd, perimetre)
        if not dossier.is_dir():
            raise HorsPerimetre(f"« {dossier} » n'est pas un dossier existant : je ne peux pas y lancer de commande.")
        return dossier
    try:
        perimetre.projets.mkdir(parents=True, exist_ok=True)
    except OSError as erreur:
        raise HorsPerimetre(f"Je ne peux pas créer mon dossier de projets « {perimetre.projets} » : {erreur}") from None
    return perimetre.projets


def open_path(path: str) -> str:
    perimetre = perimetre_actif()
    target = _normaliser_chemin(path, perimetre)
    if target.is_dir():
        # Ouvrir un DOSSIER, c'est afficher l'Explorateur : rien ne s'exécute. On ne ferme que les
        # dossiers protégés — « ouvre mon dossier Images » doit marcher, C:\Windows doit rester clos.
        _verifier_liste_noire(target, perimetre)
    else:
        # Ouvrir un FICHIER, c'est lancer l'application associée — et pour un .exe, un .bat, un .lnk
        # ou un .ps1, c'est l'exécuter. Même périmètre que la lecture et l'écriture.
        target = resoudre_dans_perimetre(path, perimetre)
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


def run_command(command: str, timeout: int = 60, cwd: str | None = None) -> dict:
    command = (command or "").strip()
    if not command:
        raise ValueError("commande vide")
    # Sans `cwd`, PowerShell héritait du dossier courant du backend : le dépôt d'IRIS. Un
    # « npm install » ou un « git init » demandé pour un site atterrissait là. Le dossier de
    # travail vient maintenant du périmètre, et une commande dont le dossier est hors périmètre
    # ne démarre pas.
    dossier = dossier_de_travail(cwd)
    if IS_WIN:
        args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        args = ["/bin/sh", "-c", command]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace", cwd=str(dossier)
        )
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
    target = resoudre_dans_perimetre(path)
    if not target.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {target}")
    if target.stat().st_size > 5_000_000:
        raise ValueError("Fichier trop volumineux (> 5 Mo).")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…(tronqué, {len(text)} caractères au total)"
    return text


def write_file(path: str, content: str, append: bool = False) -> str:
    # Le périmètre est vérifié ICI aussi, pas seulement dans tools.py : une routine, une tâche ou
    # un futur appelant direct ne doit pas pouvoir contourner la règle en sautant l'outil.
    target = resoudre_dans_perimetre(path)
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
