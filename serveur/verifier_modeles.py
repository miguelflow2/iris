"""Vérifie que les modèles d'IA que le relais promet existent VRAIMENT chez OpenRouter.

Constat de l'audit du 6 septembre 2026 : les identifiants de modèles du relais
(`anthropic/claude-sonnet-5`, `openai/gpt-5-mini`, `minimax/minimax-m3:free`…) ne sont validés
contre aucune vraie API. Le jour où l'un est renommé ou retiré chez OpenRouter, une réponse échoue
EN DIRECT et rien ne l'avait vu venir.

Ce programme interroge la liste PUBLIQUE des modèles d'OpenRouter (`GET /api/v1/models`, gratuite,
sans clé) et dit, pour chaque identifiant que le relais utilise : présent, ou introuvable. Il
n'achète rien, il n'appelle aucun modèle — il lit un catalogue.

    python serveur/verifier_modeles.py
    python serveur/verifier_modeles.py --json      (sortie machine, pour un script)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

URL_CATALOGUE = "https://openrouter.ai/api/v1/models"


def _modeles_du_relais() -> list[str]:
    """Les identifiants que le relais promet, lus DANS le relais — jamais recopiés à la main, sinon
    ce vérificateur mentirait dès la première divergence."""
    import relais

    vus: list[str] = []
    for liste in relais.MODELES_PAR_PLAN.values():
        for identifiant in liste:
            if identifiant not in vus:
                vus.append(identifiant)
    return vus


def catalogue_openrouter(url: str = URL_CATALOGUE, ouvrir=urllib.request.urlopen) -> set[str]:
    """L'ensemble des identifiants de modèles connus d'OpenRouter aujourd'hui.

    `ouvrir` est injectable pour les tests : aucun test ne touche le réseau."""
    requete = urllib.request.Request(url, headers={"User-Agent": "VELA-verifier-modeles"})
    with ouvrir(requete, timeout=20) as reponse:
        charge = json.loads(reponse.read().decode("utf-8"))
    connus: set[str] = set()
    for entree in charge.get("data", []):
        identifiant = entree.get("id")
        if identifiant:
            connus.add(identifiant)
    return connus


def confronter(demandes: list[str], connus: set[str]) -> dict:
    """Sépare ce qui existe de ce qui manque. Un « :free » retiré compte comme manquant : c'est
    exactement le cas qui casse une démo sur le forfait gratuit."""
    presents = [m for m in demandes if m in connus]
    absents = [m for m in demandes if m not in connus]
    return {"presents": presents, "absents": absents, "total": len(demandes), "catalogue": len(connus)}


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Vérifie les identifiants de modèles du relais VELA.")
    parseur.add_argument("--json", action="store_true", help="sortie JSON")
    args = parseur.parse_args(argv)

    demandes = _modeles_du_relais()
    try:
        connus = catalogue_openrouter()
    except urllib.error.URLError as exc:
        message = f"Impossible de joindre OpenRouter : {exc}. Vérifie ta connexion."
        print(json.dumps({"erreur": message}) if args.json else message, file=sys.stderr)
        return 2

    bilan = confronter(demandes, connus)
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=2))
        return 1 if bilan["absents"] else 0

    print(f"{bilan['catalogue']} modèles au catalogue OpenRouter.\n")
    for m in bilan["presents"]:
        print(f"  [présent]     {m}")
    for m in bilan["absents"]:
        print(f"  [INTROUVABLE] {m}")
    if bilan["absents"]:
        print(f"\n{len(bilan['absents'])} identifiant(s) INTROUVABLE(S) : à corriger dans "
              "serveur/relais.py (MODELES_PAR_PLAN) avant de déployer, sinon ces modèles échouent en direct.")
        return 1
    print("\nTous les modèles promis existent chez OpenRouter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
