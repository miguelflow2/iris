"""Lancement du serveur de licences.

    server\\.venv\\Scripts\\python -m licences              (port 8080)
    server\\.venv\\Scripts\\python -m licences --port 9000

En production, l'hébergeur lance plutôt :
    uvicorn licences.app:creer_app --factory --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigurationInvalide, charger


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Serveur de licences VELA")
    analyseur.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    analyseur.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    analyseur.add_argument("--recharger", action="store_true", help="rechargement automatique (développement)")
    arguments = analyseur.parse_args()

    try:
        cfg = charger()
    except ConfigurationInvalide as erreur:
        print(f"Configuration refusée : {erreur}", file=sys.stderr)
        return 2

    import uvicorn

    print(f"Serveur de licences VELA — http://{arguments.host}:{arguments.port}")
    print(f"  environnement      : {cfg.environnement}")
    print(f"  PayPal             : {'configuré (' + cfg.paypal_environnement + ')' if cfg.paypal_configure else 'NON configuré'}")
    print(f"  signature vérifiée : {'non (MODE DÉVELOPPEMENT)' if cfg.mode_dev_sans_verification else 'oui'}")
    print(f"  courriels          : {'SMTP ' + cfg.smtp_hote if cfg.smtp_configure else 'dossier ' + str(cfg.dossier_sortie)}")
    print(f"  administration     : {'/admin (jeton requis)' if cfg.jeton_admin else 'désactivée'}")

    uvicorn.run(
        "licences.app:creer_app",
        factory=True,
        host=arguments.host,
        port=arguments.port,
        reload=arguments.recharger,
        proxy_headers=True,
        forwarded_allow_ips="*",  # derrière le reverse proxy de l'hébergeur
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
