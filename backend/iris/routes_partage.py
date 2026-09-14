"""Routes de la vision partagée en direct (interface J du chantier du 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans partage.py ; ce
fichier ne fait que traduire HTTP <-> service et brancher la voix.

Attaché à ctx : ctx.partage (ServicePartage). La vision d'accessibilité lit ctx.partage.etat() pour ne
pas éteindre le témoin de la caméra pendant un partage depuis les lunettes.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .partage import ServicePartage


class DemarrerIn(BaseModel):
    source: str = ""
    intervalle_s: float | None = None


def creer_routeur(ctx) -> APIRouter:
    service = ServicePartage(ctx)
    # Attaché tout de suite, avant le démarrage : les voisins le trouvent par getattr(ctx, "partage", None).
    ctx.partage = service

    routeur = APIRouter()

    @routeur.post("/api/partage/demarrer")
    async def demarrer(body: DemarrerIn):
        # RefusPartage est un HTTPException : 409 / 403 / 422 / 429 / 500 / 502 / 503 remontent tels quels.
        return await service.demarrer(body.source, body.intervalle_s)

    @routeur.post("/api/partage/arreter")
    async def arreter():
        return await service.arreter()

    @routeur.post("/api/partage/prolonger")
    async def prolonger():
        return await service.prolonger()

    @routeur.get("/api/partage/etat")
    async def etat():
        return service.etat()

    # L'interception vocale (« arrête le partage ») a besoin de la boucle du service : posée au démarrage.
    routeur.iris_demarrage = service.brancher  # type: ignore[attr-defined]
    routeur.iris_arret = service.fermer  # type: ignore[attr-defined]
    return routeur
