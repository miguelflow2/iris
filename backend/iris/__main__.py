"""Point d'entrée : `python -m iris --data-dir <dossier>`.
Choisit un port libre, génère un jeton de session et annonce `IRIS_READY {...}` sur stdout pour Electron."""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
from pathlib import Path

# Un seul thread pour les bibliothèques de calcul : sur un portable 2 cœurs, les pools d'OpenBLAS/OMP
# réservent ~200 Mo et 3 threads inutiles (le décodage vocal est mono-thread). À définir AVANT numpy/vosk.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")


def selftest() -> int:
    """Vérifie, dans l'exécutable empaqueté, que les bibliothèques natives se chargent dans l'ordre réel de l'app.
    Utilisé par scripts/build-backend.ps1 : une DLL manquante ou incompatible fait échouer la construction."""
    import numpy

    steps: list[tuple[str, object]] = []

    def check(label, fn):
        try:
            fn()
            steps.append((label, True))
        except Exception as exc:  # pragma: no cover - dépend de la machine
            steps.append((label, f"{type(exc).__name__}: {exc}"))

    check("winrt (Bluetooth/lunettes)", lambda: __import__("winrt.windows.foundation", fromlist=["*"]))
    check("bleak", lambda: __import__("bleak"))

    def _ocr():
        from rapidocr_onnxruntime import RapidOCR

        RapidOCR()(numpy.zeros((64, 64, 3), dtype=numpy.uint8))

    check("OCR (rapidocr + onnxruntime)", _ocr)
    check("vosk", lambda: __import__("vosk"))
    check("sounddevice", lambda: __import__("sounddevice"))

    def _piper():
        # Charge le VRAI modèle et synthétise : vérifie d'un coup que le paquet piper, sa passerelle
        # native espeakbridge.pyd, ses données espeak-ng ET le modèle de voix sont tous dans le
        # bundle. Un « module/DLL/donnée absent » découvert au premier mot français chez un client
        # serait exactement le raté qu'on ne peut plus se permettre.
        from piper import PiperVoice

        from iris.voice.piper import DEFAULT_VOICE, _espeak_data_dir, trouver_modele

        modele = trouver_modele(DEFAULT_VOICE)
        assert modele is not None, "modèle de voix Piper absent du bundle (piper_voices/)"
        espeak = _espeak_data_dir()
        voix = PiperVoice.load(str(modele), espeak_data_dir=espeak) if espeak is not None else PiperVoice.load(str(modele))
        produits = sum(len(c.audio_int16_bytes) for c in voix.synthesize("Bonjour, je suis Iris."))
        assert produits > 0, "Piper n'a produit aucun audio"

    check("voix française locale (Piper + espeak-ng)", _piper)

    def _num():
        from num2words import num2words

        assert num2words(21, lang="fr") == "vingt et un"

    check("num2words fr", _num)
    check("playwright", lambda: __import__("playwright.sync_api", fromlist=["*"]))
    ok = True
    for label, res in steps:
        if res is True:
            print(f"  OK    {label}")
        else:
            ok = False
            print(f"  ECHEC {label} -> {res}")
    print("autotest : " + ("tout est chargeable" if ok else "AU MOINS UNE BIBLIOTHEQUE NE SE CHARGE PAS"))
    return 0 if ok else 1


PORT_MOBILE = 8765  # port fixe quand l'accès téléphone est actif, pour que l'adresse reste valable


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def port_stable(host: str, depart: int = PORT_MOBILE) -> int:
    """Premier port libre à partir de `depart`. L'adresse enregistrée sur le téléphone doit
    rester la même d'un démarrage à l'autre, sinon le favori ne marche plus le lendemain."""
    for candidat in range(depart, depart + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, candidat))
                return candidat
        except OSError:
            continue
    return free_port(host)


def reglages_bruts(data_dir: Path | None) -> dict:
    """Lecture minimale des réglages, avant la construction de l'application."""
    if data_dir is None:
        return {}
    try:
        return json.loads((Path(data_dir) / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def jeton_persistant(data_dir: Path) -> str:
    """Jeton conservé entre deux démarrages, pour que l'adresse du téléphone reste valable.
    Supprimer ce fichier révoque immédiatement tous les appareils qui l'utilisaient."""
    fichier = Path(data_dir) / "remote-token"
    try:
        existant = fichier.read_text(encoding="utf-8").strip()
        if len(existant) >= 20:
            return existant
    except Exception:
        pass
    nouveau = secrets.token_urlsafe(32)
    try:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(nouveau, encoding="utf-8")
        try:  # lisible par le seul propriétaire, quand le système le permet
            fichier.chmod(0o600)
        except Exception:
            pass
    except Exception:
        pass
    return nouveau


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iris", description="Backend local IRIS")
    parser.add_argument("--data-dir", default=os.environ.get("IRIS_DATA_DIR"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("IRIS_PORT") or 0))
    parser.add_argument("--token", default=os.environ.get("IRIS_TOKEN"))
    parser.add_argument("--no-token", action="store_true", help="désactive l'authentification (dev uniquement)")
    parser.add_argument("--no-keyring", action="store_true", help="n'utilise pas le coffre système (tests)")
    parser.add_argument("--log-level", default=os.environ.get("IRIS_LOG_LEVEL", "info"))
    parser.add_argument("--selftest", action="store_true", help="vérifie le chargement des bibliothèques natives puis sort")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    import uvicorn

    from .main import create_app

    data_dir = Path(args.data_dir) if args.data_dir else None
    # Quand l'accès téléphone est actif, l'adresse doit rester la même d'un jour à l'autre :
    # port fixe et jeton conservé sur le disque. Sinon le favori du téléphone serait mort au réveil.
    mobile = bool(reglages_bruts(data_dir).get("remote_access"))
    if args.no_token:
        token = None
    elif args.token:
        token = args.token
    elif mobile and data_dir is not None:
        token = jeton_persistant(data_dir)
    else:
        token = secrets.token_urlsafe(32)
    port = args.port or (port_stable(args.host) if mobile else free_port(args.host))
    app = create_app(data_dir=data_dir, token=token, use_keyring=not args.no_keyring)

    # Accès mobile : on écoute aussi sur le réseau local quand l'utilisateur l'a autorisé.
    # 127.0.0.1 reste joignable, donc Electron n'est pas affecté.
    host = args.host
    try:
        if app.state.ctx.settings.user.remote_access and host in ("127.0.0.1", "localhost"):
            host = "0.0.0.0"  # noqa: S104 - réseau local uniquement, jamais exposé par un routeur
            logging.getLogger("iris").info("accès mobile activé : écoute sur le réseau local")
    except Exception:
        pass

    ready = {"port": port, "host": args.host, "token": token, "data_dir": str(app.state.ctx.settings.data_dir)}
    sys.stdout.write("IRIS_READY " + json.dumps(ready) + "\n")
    sys.stdout.flush()

    uvicorn.run(app, host=host, port=port, log_level=args.log_level.lower(), access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
