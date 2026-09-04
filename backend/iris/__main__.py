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


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


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

    token = None if args.no_token else (args.token or secrets.token_urlsafe(32))
    port = args.port or free_port(args.host)
    data_dir = Path(args.data_dir) if args.data_dir else None
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
