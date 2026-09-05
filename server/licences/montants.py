"""Du montant reçu au plan vendu.

Prix de référence (backend/iris/plans.py) :
    19,99 $ → pro,        1 mois
    29,99 $ → premium,    1 mois
    99,99 $ → entreprise, 1 mois
   250,00 $ → lunettes VELA : du matériel, aucun abonnement à activer

Un montant inconnu n'active jamais rien : il part en traitement manuel.
"""
from __future__ import annotations

from dataclasses import dataclass

# (montant, plan, nombre de mois, libellé)
TARIFS: tuple[tuple[float, str, int, str], ...] = (
    (19.99, "pro", 1, "Pro — 1 mois"),
    (29.99, "premium", 1, "Premium — 1 mois"),
    (99.99, "entreprise", 1, "Entreprise — 1 mois"),
)
# 250,00 $ n'est volontairement pas dans ce tableau : c'est l'achat des lunettes. Un paiement de
# matériel ne doit activer aucun abonnement, sous peine d'offrir un mois à chaque client.


@dataclass(frozen=True)
class Tarif:
    plan: str
    mois: int
    libelle: str
    montant_attendu: float


def reconnaitre(montant: float | None, devise: str | None, *,
                devises_acceptees: tuple[str, ...] = ("CAD",),
                tolerance: float = 0.05) -> Tarif | None:
    """Renvoie le tarif correspondant, ou None si le montant/la devise ne correspondent à rien.

    La tolérance absorbe les arrondis et les quelques cents de différence (change, frais).
    Une devise non prévue n'est jamais devinée : mieux vaut un traitement manuel qu'un
    abonnement offert parce que 19,99 USD a été pris pour 19,99 CAD.
    """
    if montant is None:
        return None
    if (devise or "").strip().upper() not in devises_acceptees:
        return None
    for attendu, plan, mois, libelle in TARIFS:
        if abs(float(montant) - attendu) <= tolerance:
            return Tarif(plan=plan, mois=mois, libelle=libelle, montant_attendu=attendu)
    return None
