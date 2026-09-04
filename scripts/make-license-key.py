"""Génère une clé d'abonnement IRIS (à exécuter côté VELA, jamais chez le client).
Usage : backend\\.venv\\Scripts\\python scripts\\make-license-key.py pro 2027-09-02 client@exemple.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from iris.plans import PLANS, make_key, verify_key  # noqa: E402

if len(sys.argv) < 3 or sys.argv[1] not in PLANS:
    print("usage : make-license-key.py <gratuit|essentiel|pro|ultra> <AAAA-MM-JJ> [email]")
    sys.exit(1)
key = make_key(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
print(key)
print("vérification :", verify_key(key))
