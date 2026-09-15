"""Routes du quotidien (interface G du chantier du 2026-09-13) : résumé du jour, rappels liés à une
personne, reçus.

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans quotidien.py,
rappels_contexte.py et recus.py ; ce fichier traduit HTTP <-> services, branche la voix et le hub, et
fait tourner la purge de rétention. Chaque service est construit séparément : un module en panne ne
retire que ses propres routes, jamais celles des deux autres (ni le démarrage d'IRIS).

Attachés à ctx : ctx.resume_quotidien(jour) (async), ctx.rappels_contexte, ctx.recus.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .lunettes_presence import exiger_lunettes, exiger_lunettes_pc

log = logging.getLogger("iris.quotidien.routes")

PURGE_S = 3600.0


class ParlerIn(BaseModel):
    date: str | None = None


class RappelIn(BaseModel):
    personne: str = ""
    texte: str = ""


class ImageIn(BaseModel):
    media_type: str = "image/jpeg"
    data: str = ""


class AnalyserIn(BaseModel):
    source: str = "image"
    image: ImageIn | None = None


def _routes_resume(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list) -> None:
    from .quotidien import ServiceResume

    service = ServiceResume(ctx)
    ctx.resume_quotidien = service.resume_quotidien

    @routeur.get("/api/resume/jour")
    async def resume_jour(date: str | None = Query(default=None)):
        return await service.resumer(date)

    @routeur.post("/api/resume/jour/parler")
    async def resume_jour_parler(body: ParlerIn | None = None):
        exiger_lunettes(ctx, "resume_journee")
        return await service.parler(body.date if body else None)

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)


def _routes_rappels(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, purges: list) -> None:
    from .rappels_contexte import ServiceRappelsContexte

    service = ServiceRappelsContexte(ctx)
    ctx.rappels_contexte = service
    suivi: dict[str, Any] = {"tache": None}

    @routeur.get("/api/rappels-contexte")
    def rappels_liste():
        suspendue = getattr(getattr(ctx, "memory", None), "suspendue", None)
        return {"rappels": service.liste(), "memoire_suspendue": suspendue}

    @routeur.post("/api/rappels-contexte")
    def rappels_creer(body: RappelIn):
        exiger_lunettes(ctx, "rappels_contexte")
        return service.creer(body.personne, body.texte, origine="route")

    @routeur.delete("/api/rappels-contexte/{rappel_id}")
    def rappels_supprimer(rappel_id: str):
        if not service.supprimer(rappel_id):
            raise HTTPException(404, "Rappel introuvable.")
        return {"supprime": True}

    async def suivre_evenements() -> None:
        # Abonné au hub comme un client : chaque phrase entendue, message ou texto est comparé aux rappels
        # en attente. Le tri par type est immédiat ; seul un événement porteur de texte passe par un fil.
        file = ctx.hub.subscribe()
        try:
            while True:
                evenement = await file.get()
                if not service.concerne(evenement):
                    continue
                try:
                    await asyncio.to_thread(service.traiter_evenement, evenement)
                except Exception as exc:  # un événement mal formé ne coupe pas le suivi
                    log.warning("rappels contextuels : événement %s non traité (%s)", evenement.get("type"), exc)
        finally:
            ctx.hub.unsubscribe(file)

    def demarrer() -> None:
        suivi["tache"] = asyncio.get_running_loop().create_task(suivre_evenements())
        service.brancher_voix()

    def arreter() -> None:
        service.debrancher_voix()
        if suivi["tache"] is not None:
            suivi["tache"].cancel()

    demarrages.append(demarrer)
    arrets.append(arreter)
    purges.append(service.purger)


def _routes_recus(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, purges: list) -> None:
    from .recus import ServiceRecus

    service = ServiceRecus(ctx)
    ctx.recus = service

    @routeur.post("/api/recus/analyser")
    async def recus_analyser(body: AnalyserIn):
        # Photo par la caméra reliée à l'ordinateur : lunettes vues par l'ordinateur ; photo du téléphone : attestation.
        (exiger_lunettes_pc if (body.source or "") == "lunettes" else exiger_lunettes)(ctx, "recus")
        return await service.analyser(body.source, image=body.image.model_dump() if body.image else None)

    @routeur.get("/api/recus")
    def recus_liste(debut: str | None = Query(default=None), fin: str | None = Query(default=None)):
        from .recus import LIMITE

        recus = service.liste(debut, fin)
        return {"recus": recus, "totaux": service.totaux(recus), "limite": LIMITE,
                "retention_jours": int(getattr(ctx.settings.user, "retention_days", 0) or 0)}

    @routeur.get("/api/recus/export")
    def recus_export(format: str = Query(default="csv"), debut: str | None = Query(default=None),
                     fin: str | None = Query(default=None)):
        if format != "csv":
            raise HTTPException(422, "Format d'export non pris en charge : csv seulement.")
        contenu = service.exporter_csv(debut, fin)
        nom = "iris-recus" + (f"-{debut}" if debut else "") + (f"-{fin}" if fin else "") + ".csv"
        return Response(contenu.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    @routeur.get("/api/recus/{recu_id}/image")
    def recus_image(recu_id: str):
        octets = service.image(recu_id)
        if octets is None:
            raise HTTPException(404, "Image du reçu introuvable.")
        return Response(octets, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @routeur.patch("/api/recus/{recu_id}")
    def recus_modifier(recu_id: str, patch: dict[str, Any] = Body(...)):
        return service.modifier(recu_id, patch)

    @routeur.delete("/api/recus/{recu_id}")
    def recus_supprimer(recu_id: str):
        if not service.supprimer(recu_id):
            raise HTTPException(404, "Reçu introuvable.")
        return {"supprime": True}

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)
    purges.append(service.purger)


def creer_routeur(ctx) -> APIRouter:
    routeur = APIRouter()
    demarrages: list = []
    arrets: list = []
    purges: list = []
    for nom, brancher in (
        ("résumé du jour", lambda: _routes_resume(routeur, ctx, demarrages, arrets)),
        ("rappels contextuels", lambda: _routes_rappels(routeur, ctx, demarrages, arrets, purges)),
        ("reçus", lambda: _routes_recus(routeur, ctx, demarrages, arrets, purges)),
    ):
        try:
            brancher()
        except Exception as exc:
            log.warning("quotidien : %s non branché (%s)", nom, exc)

    taches: dict[str, Any] = {"purge": None}

    async def boucle_purge() -> None:
        while True:
            for purger in purges:
                try:
                    await asyncio.to_thread(purger)
                except Exception as exc:  # une purge en erreur n'arrête pas les autres
                    log.warning("quotidien : purge en erreur (%s)", exc)
            await asyncio.sleep(PURGE_S)

    async def demarrage() -> None:
        for demarrer in demarrages:
            try:
                demarrer()
            except Exception as exc:
                log.warning("quotidien : démarrage en erreur (%s)", exc)
        if purges:
            taches["purge"] = asyncio.get_running_loop().create_task(boucle_purge())

    async def arret() -> None:
        if taches["purge"] is not None:
            taches["purge"].cancel()
        for arreter in arrets:
            try:
                arreter()
            except Exception as exc:
                log.warning("quotidien : arrêt en erreur (%s)", exc)

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    return routeur
