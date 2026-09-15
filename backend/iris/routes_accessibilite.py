"""Routes de la vision d'accessibilité (interface A du chantier du 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans
accessibilite.py ; ce fichier ne fait que traduire HTTP <-> service, et brancher la voix.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .accessibilite import ServiceAccessibilite
from .lunettes_presence import exiger_lunettes, exiger_lunettes_pc


class ImageIn(BaseModel):
    media_type: str = "image/jpeg"
    data: str = ""


class DecrireIn(BaseModel):
    mode: str
    source: str = "lunettes"
    image: ImageIn | None = None
    question: str | None = None
    parler: bool = True
    memoriser: bool = True


class OuEstIn(BaseModel):
    question: str = ""


def creer_routeur(ctx) -> APIRouter:
    service = ServiceAccessibilite(ctx)
    # Attaché tout de suite, avant le démarrage : le bouton des lunettes, la page téléphone et les
    # outils du chat le trouvent par getattr(ctx, "accessibilite", None).
    ctx.accessibilite = service
    chat = getattr(ctx, "chat", None)
    if chat is not None:
        chat.accessibilite = service

    routeur = APIRouter()

    @routeur.get("/api/accessibilite/modes")
    def modes():
        return {"modes": service.modes()}

    @routeur.post("/api/accessibilite/decrire")
    async def decrire(body: DecrireIn):
        # Caméra reliée à l'ordinateur ou écran de l'ordinateur : les lunettes doivent être vues PAR l'ordinateur.
        # Une photo fournie par le téléphone (source « image ») se contente de l'attestation du téléphone.
        if (body.source or "lunettes") in ("lunettes", "ecran") or (body.mode or "") == "ecran":
            exiger_lunettes_pc(ctx, "vision")
        else:
            exiger_lunettes(ctx, "vision")
        # RefusVision est un HTTPException : 409 / 403 / 422 / 500 / 502 remontent tels quels.
        return await service.decrire(
            body.mode, body.source, image=body.image.model_dump() if body.image else None,
            question=body.question, parler=body.parler, memoriser=body.memoriser,
        )

    @routeur.post("/api/accessibilite/ou-est")
    async def ou_est(body: OuEstIn):
        """« Où ai-je posé… ? » exige les lunettes : choix DÉCLARÉ (demande iOS du 2026-09-14). C'est IRIS qui
        cherche, rédige et répond (à voix haute, avec le moteur pour les souvenirs de photo), donc une fonction
        qui agit. La CONSULTATION des mêmes données reste libre sans lunettes (Loi 25) : GET /api/memory?q=
        et GET /api/journal?q= (vérifié par test_garde_lunettes.ROUTES_LIBRES)."""
        exiger_lunettes(ctx, "ou_est")
        return await service.ou_est(body.question)

    # L'interception vocale a besoin de la boucle du service : elle est posée au démarrage.
    routeur.iris_demarrage = service.brancher_voix  # type: ignore[attr-defined]
    routeur.iris_arret = service.debrancher_voix  # type: ignore[attr-defined]
    return routeur
