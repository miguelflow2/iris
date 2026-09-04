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
hiddenimports += ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "pyttsx3.drivers.nsss", "pyttsx3.drivers.espeak"]
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
hiddenimports += ["PIL.Image", "PIL.JpegImagePlugin", "PIL.PngImagePlugin", "psutil", "numpy"]

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
