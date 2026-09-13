"""Routes de confiance (interface I du chantier du 2026-09-13) : empreinte vocale, zones sans mémoire,
mode invité, verrouillage sur place et à distance.

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans verrou_vocal.py,
zones.py, mode_invite.py et verrou.py ; ce fichier traduit HTTP <-> services, branche la voix, le hub et
la télécommande. Chaque service est construit séparément : un module en panne ne retire que ses propres
routes, jamais celles des autres (ni le démarrage d'IRIS).

Attachés à ctx : ctx.verrou_vocal, ctx.zones, ctx.mode_invite, ctx.verrou (lu par main.raison_de_refus).
ctx.verrou est posé DÈS la construction du routeur : une IRIS verrouillée avant son redémarrage doit
refuser la toute première requête, pas celle d'après le démarrage.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("iris.confiance.routes")

INTERVALLE_MINUTERIE_S = 5.0


class ConsentementIn(BaseModel):
    accepte: bool = False


class SecondesIn(BaseModel):
    secondes: float = 4.0


class ZoneIn(BaseModel):
    nom: str = ""
    lat: float | None = None
    lon: float | None = None
    rayon_m: float = 150


class ZoneSignaleeIn(BaseModel):
    zone_id: str | None = None
    source: str = "telephone"


class PositionIn(BaseModel):
    lat: float | None = None
    lon: float | None = None
    precision_m: float | None = None
    source: str = "telephone"


class InviteIn(BaseModel):
    minutes: int | None = None


class CodeIn(BaseModel):
    code: str = ""
    mot_de_passe: str | None = None


class MotDePasseIn(BaseModel):
    mot_de_passe: str = ""


def _refus(exc: Any) -> HTTPException:
    return HTTPException(getattr(exc, "code", 409), getattr(exc, "message", str(exc)))


# ---------------------------------------------------------------------------- empreinte vocale
def _routes_voix(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, reglages: list) -> None:
    from .verrou_vocal import RefusVerrouVocal, VerrouVocal

    service = VerrouVocal(ctx)
    ctx.verrou_vocal = service
    service.appliquer()

    @routeur.get("/api/confiance/voix")
    def voix_etat():
        return service.etat()

    @routeur.post("/api/confiance/voix/consentement")
    def voix_consentement(body: ConsentementIn):
        return service.definir_consentement(bool(body.accepte))

    @routeur.post("/api/confiance/voix/echantillon")
    async def voix_echantillon(body: SecondesIn | None = None):
        if service.consentement() is None:
            raise HTTPException(403, "Consentement biométrique requis avant d'enregistrer votre voix.")
        try:
            pcm = await asyncio.to_thread(service.enregistrer, body.secondes if body else 4.0)
            return await asyncio.to_thread(service.ajouter_echantillon_pcm, pcm)
        except RefusVerrouVocal as exc:
            raise _refus(exc)

    @routeur.post("/api/confiance/voix/tester")
    async def voix_tester(body: SecondesIn | None = None):
        if not service.pret:
            raise HTTPException(409, "Empreinte incomplète : enregistrez d'abord vos échantillons.")
        try:
            pcm = await asyncio.to_thread(service.enregistrer, body.secondes if body else 4.0)
            return await asyncio.to_thread(service.tester_pcm, pcm)
        except RefusVerrouVocal as exc:
            raise _refus(exc)

    @routeur.delete("/api/confiance/voix")
    def voix_effacer():
        service.effacer()
        return service.etat()

    def retirer() -> None:
        voice = getattr(ctx, "voice", None)
        if voice is not None and getattr(voice, "verificateur_locuteur", None) == service.verifier:
            voice.verificateur_locuteur = None

    demarrages.append(service.appliquer)
    arrets.append(retirer)
    reglages.append(service.appliquer)


# ---------------------------------------------------------------------------- zones sans mémoire
def _routes_zones(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, reglages: list) -> None:
    from .zones import RefusZone, ZonesSansMemoire

    service = ZonesSansMemoire(ctx)
    ctx.zones = service

    @routeur.get("/api/confiance/zones")
    def zones_liste():
        return service.etat()

    @routeur.post("/api/confiance/zones")
    def zones_creer(body: ZoneIn):
        try:
            return service.creer(body.nom, body.lat, body.lon, body.rayon_m)
        except RefusZone as exc:
            raise _refus(exc)

    @routeur.delete("/api/confiance/zones/{zone_id}")
    def zones_supprimer(zone_id: str):
        if not service.supprimer(zone_id):
            raise HTTPException(404, "Zone introuvable.")
        return {"supprime": True, **service.etat()}

    @routeur.post("/api/confiance/zone")
    def zone_signalee(body: ZoneSignaleeIn):
        try:
            return service.signaler(body.zone_id, body.source)
        except RefusZone as exc:
            raise _refus(exc)

    @routeur.post("/api/confiance/position")
    def position_evaluee(body: PositionIn):
        # La position n'est ni gardée, ni journalisée, ni renvoyée : seulement la zone qui la contient.
        try:
            etat = service.signaler_position(body.lat, body.lon, body.precision_m, body.source)
        except RefusZone as exc:
            raise _refus(exc)
        return {"dans_zone": etat["zone_active"] is not None, **etat}

    @routeur.get("/api/confiance/position/pc")
    async def position_pc():
        try:
            return await asyncio.to_thread(service.position_pc)
        except RefusZone as exc:
            raise _refus(exc)

    arrets.append(service.arreter)
    reglages.append(service.reconcilier)


# ---------------------------------------------------------------------------- mode invité
def _routes_invite(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, taches: list) -> None:
    from .mode_invite import ModeInvite

    service = ModeInvite(ctx)
    ctx.mode_invite = service

    @routeur.get("/api/confiance/invite")
    def invite_etat():
        return service.etat()

    @routeur.post("/api/confiance/invite/activer")
    def invite_activer(body: InviteIn | None = None):
        return service.activer(body.minutes if body else None)

    @routeur.post("/api/confiance/invite/desactiver")
    async def invite_desactiver():
        return await asyncio.to_thread(service.desactiver)

    async def minuterie() -> None:
        while True:
            try:
                await asyncio.to_thread(service.verifier_echeance)
            except Exception as exc:  # une erreur de ménage n'arrête pas la minuterie
                log.warning("mode invité : minuterie en erreur (%s)", exc)
            await asyncio.sleep(INTERVALLE_MINUTERIE_S)

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)
    taches.append(minuterie)


# ---------------------------------------------------------------------------- verrouillage
def _routes_verrou(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, taches: list) -> None:
    from .verrou import RefusVerrou, VerrouIRIS

    service = VerrouIRIS(ctx)
    ctx.verrou = service
    telecommande = getattr(ctx, "telecommande", None)
    if telecommande is not None:
        telecommande.verrou = service

    @routeur.get("/api/confiance/verrou/etat")
    def verrou_etat():
        return service.etat()

    @routeur.post("/api/confiance/verrou/code")
    def verrou_code(body: CodeIn):
        try:
            return service.definir_code(body.code, body.mot_de_passe)
        except RefusVerrou as exc:
            raise _refus(exc)

    @routeur.post("/api/confiance/verrouiller")
    async def verrouiller():
        try:
            return await service.verrouiller("local")
        except RefusVerrou as exc:
            raise _refus(exc)

    @routeur.post("/api/confiance/deverrouiller")
    async def deverrouiller(body: MotDePasseIn):
        try:
            etat = await asyncio.to_thread(service.deverrouiller, body.mot_de_passe)
        except RefusVerrou as exc:
            raise _refus(exc)
        await asyncio.to_thread(service.relancer_apres_deverrouillage)
        glasses = getattr(ctx, "glasses", None)
        if glasses is not None:
            try:  # les lunettes reviennent si l'utilisateur a choisi la connexion automatique
                asyncio.get_running_loop().create_task(glasses.auto_connect_on_start())
            except Exception as exc:  # pragma: no cover
                log.info("verrou : reconnexion des lunettes non lancée (%s)", exc)
        return etat

    taches.append(service.surveiller)


# ---------------------------------------------------------------------------- routeur
def creer_routeur(ctx: Any) -> APIRouter:
    routeur = APIRouter()
    demarrages: list = []
    arrets: list = []
    reglages: list = []  # appelés à chaque settings.updated
    taches: list = []  # coroutines de fond (sans argument)
    # Le verrou d'abord : s'il plante, les autres restent ; s'il marche, il protège dès maintenant.
    for nom, brancher in (
        ("verrouillage", lambda: _routes_verrou(routeur, ctx, demarrages, arrets, taches)),
        ("mode invité", lambda: _routes_invite(routeur, ctx, demarrages, arrets, taches)),
        ("zones sans mémoire", lambda: _routes_zones(routeur, ctx, demarrages, arrets, reglages)),
        ("empreinte vocale", lambda: _routes_voix(routeur, ctx, demarrages, arrets, reglages)),
    ):
        try:
            brancher()
        except Exception as exc:
            log.warning("confiance : %s non branché (%s)", nom, exc)

    en_cours: list[asyncio.Task] = []

    async def suivre_evenements() -> None:
        # Abonné au hub comme un client : réglages modifiés (verrou vocal, zones) et conversations créées
        # (mode invité). Le tri par type est immédiat ; aucun événement n'attend un autre.
        file = ctx.hub.subscribe()
        try:
            while True:
                evenement = await file.get()
                genre = evenement.get("type")
                try:
                    if genre == "settings.updated":
                        for appliquer in reglages:
                            appliquer()
                    elif genre == "conversation.created":
                        mode = getattr(ctx, "mode_invite", None)
                        conversation = evenement.get("conversation") or {}
                        if mode is not None and isinstance(conversation, dict):
                            mode.noter_conversation(conversation.get("id"))
                except Exception as exc:  # un événement mal formé ne coupe pas le suivi
                    log.warning("confiance : événement %s non traité (%s)", genre, exc)
        finally:
            ctx.hub.unsubscribe(file)

    async def demarrage() -> None:
        boucle = asyncio.get_running_loop()
        en_cours.append(boucle.create_task(suivre_evenements()))
        for tache in taches:
            en_cours.append(boucle.create_task(tache()))
        for demarrer in demarrages:
            try:
                demarrer()
            except Exception as exc:
                log.warning("confiance : démarrage en erreur (%s)", exc)

    async def arret() -> None:
        for tache in en_cours:
            tache.cancel()
        en_cours.clear()
        for arreter in arrets:
            try:
                arreter()
            except Exception as exc:
                log.warning("confiance : arrêt en erreur (%s)", exc)

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    return routeur
