"""Routes de l'album local et de la traduction de l'écran (interface E du chantier du 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans album.py ; ce
fichier ne fait que traduire HTTP <-> service et poser les crochets de démarrage et d'arrêt.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .album import ServiceAlbum


class NomIn(BaseModel):
    nom: str = ""


class ExporterIn(BaseModel):
    nom: str = ""
    filigrane: bool | None = None


class TraductionEcranIn(BaseModel):
    langue_cible: str = "fr"


def creer_routeur(ctx) -> APIRouter:
    service = ServiceAlbum(ctx)
    # Attaché tout de suite : les modules voisins le trouvent par getattr(ctx, "album", None).
    ctx.album = service

    routeur = APIRouter()

    @routeur.get("/api/album")
    def lister(type: str = "tout"):  # noqa: A002 - « type » est le nom du paramètre du contrat
        return service.lister(type)

    @routeur.get("/api/album/fichier/{nom}")
    def fichier(nom: str):
        chemin, media_type = service.fichier(nom)
        # FileResponse lit en flux (un WAV de cours pèse des centaines de Mo) et gère les plages
        # d'octets, ce qu'exige la lecture audio avec avance rapide. Rien n'est mis en cache.
        return FileResponse(chemin, media_type=media_type, headers={"Cache-Control": "no-store"})

    @routeur.delete("/api/album/{nom}")
    def supprimer(nom: str):
        return service.supprimer(nom)

    @routeur.post("/api/album/bd")
    async def bd(body: NomIn):
        return await service.bd(body.nom)

    @routeur.post("/api/album/exporter")
    async def exporter(body: ExporterIn):
        return await service.exporter(body.nom, body.filigrane)

    @routeur.post("/api/traduction/ecran")
    async def traduction_ecran(body: TraductionEcranIn):
        return await service.traduire_ecran(body.langue_cible)

    routeur.iris_demarrage = service.demarrer  # type: ignore[attr-defined]
    routeur.iris_arret = service.arreter  # type: ignore[attr-defined]
    return routeur
