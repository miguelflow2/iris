# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller : empaquette le backend IRIS en dossier autonome (aucun Python requis sur la machine cible)."""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in (
    "vosk",
    "sounddevice",
    "_sounddevice_data",
    "pyttsx3",
    "comtypes",
    "keyring",
    "anthropic",
    "openai",
    "google.genai",
    "mss",
    "speech_recognition",
    "pyautogui",
    "pyscreeze",
    "pymsgbox",
    "pytweening",
    "mouseinfo",
    "yt_dlp",
    "playwright",
    "rapidocr_onnxruntime",
    "onnxruntime",
    # Voix française LOCALE (mode indépendant). collect_all embarque le paquet piper, sa passerelle
    # native espeakbridge.pyd ET ses données de phonèmes piper/espeak-ng-data — sans elles, la
    # synthèse lève au premier mot chez le client. Le modèle de voix lui-même est ajouté plus bas.
    "piper",
    "bleak",
    "winrt",
    "certifi",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # paquet absent sur cette plateforme
        print(f"[spec] {pkg} ignoré : {exc}")

hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("num2words")
# Lecture de PDF (iris/lecture_fichiers.py). Import paresseux dans une fonction : on l'ajoute
# explicitement pour que l'exécutable l'embarque à coup sûr — un « module absent » découvert chez
# un client sur son premier PDF serait exactement le genre de raté qu'on ne peut plus se permettre.
hiddenimports += collect_submodules("pypdf")
hiddenimports += ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "pyttsx3.drivers.nsss", "pyttsx3.drivers.espeak"]
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
hiddenimports += ["PIL.Image", "PIL.JpegImagePlugin", "PIL.PngImagePlugin", "psutil", "numpy"]

# Icônes de l'application téléphone : sans elles, Android ne propose pas l'installation.
datas += [("iris/assets/icone-192.png", "iris/assets"), ("iris/assets/icone-512.png", "iris/assets")]
# Coquille de la page téléphone (index.html, app.css, js/*.js, sw.js, manifeste), lue par iris/mobile.py et
# servie par iris/routes_mobile.py à côté du module (Path(__file__).parent / "mobile_static"). Sans ce
# dossier, /m afficherait seulement « la page téléphone n'est pas installée correctement ».
datas += [("iris/mobile_static", "iris/mobile_static")]

# Modèle de voix française locale Piper. Déposé dans piper_voices/ à la racine du bundle : c'est là
# que iris/voice/piper.py::_dossiers_voix le cherche via sys._MEIPASS. Sans ce fichier embarqué, une
# install fraîche n'a pas de voix française hors-ligne (elle retomberait sur l'accent Windows).
import os as _os  # local au .spec, n'affecte pas le runtime empaqueté
for _f in ("fr_FR-siwis-medium.onnx", "fr_FR-siwis-medium.onnx.json"):
    _src = _os.path.join("piper_voices", _f)
    if _os.path.isfile(_src):
        datas += [(_src, "piper_voices")]
    else:
        print(f"[spec] ATTENTION voix Piper absente : {_src} — la voix française locale ne sera pas empaquetée")

a = Analysis(
    ["run_backend.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook", "pytest", "torch", "tensorflow"],
    noarchive=False,
)
# winrt-runtime embarque un msvcp140.dll 14.29 ; chargé avant onnxruntime (qui exige 14.40+),
# il provoque « DLL load failed ... Une routine d'initialisation d'une DLL a échoué » (erreur Windows 1114)
# et casse l'OCR. On le retire : les .pyd winrt utiliseront le 14.50 de _internal (ou celui du système).
_before = len(a.binaries)
a.binaries = [b for b in a.binaries if not b[0].replace("\\", "/").lower().endswith("winrt/msvcp140.dll")]
print(f"[spec] msvcp140 winrt retire : {_before - len(a.binaries)} fichier(s)")

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iris-backend",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="iris-backend")
