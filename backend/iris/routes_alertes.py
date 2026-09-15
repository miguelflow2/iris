"""Routes des alertes sonores, de l'écoute assistée et du bouton des lunettes (interface D, 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans
alertes_sonores.py, ecoute_assistee.py et bouton_lunettes.py ; ce fichier traduit HTTP <-> services
et tient le seul abonnement au bus d'événements dont ces services ont besoin :
- settings.updated / privacy.mode : les alertes démarrent et s'arrêtent selon alertes_actives, tout
  s'arrête en mode confidentiel ;
- lunettes.presence, glasses.state, glasses.connected, voice.state : des alertes voulues qui attendaient
  les lunettes démarrent dès qu'elles sont là ;
- glasses.packet : les paquets des lunettes vont au bouton (apprentissage et déclenchement).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .alertes_sonores import CONFIDENTIEL, TYPES_ACOUSTIQUES, EcouteRefusee, ServiceAlertes, prenom_depuis
from .bouton_lunettes import ServiceBouton
from .ecoute_assistee import ServiceEcouteAssistee
from .lunettes_presence import exiger_lunettes_pc, raison_capture_pc

log = logging.getLogger("iris.routes_alertes")

# Ce qui peut rendre les lunettes présentes après coup : attestation du téléphone, connexion Bluetooth
# basse énergie, micro des lunettes retrouvé par l'écoute (publié avec voice.state).
EVENEMENTS_PRESENCE = ("lunettes.presence", "glasses.state", "glasses.connected", "voice.state")


class TesterIn(BaseModel):
    type: str = ""


class AssisteeIn(BaseModel):
    gain_db: int | None = None
    reduction: int | None = None


class ApprendreIn(BaseModel):
    secondes: float = 6.0


def etat_ecoute(ctx) -> dict:
    """L'état d'écoute de l'interface C. Construit par l'équipe écoute (ctx.ecoute_etat) quand elle est là ;
    sinon, la même forme avec ce que ce module sait vraiment (rien d'autre n'écoute)."""
    fonction = getattr(ctx, "ecoute_etat", None)
    if callable(fonction):
        try:
            return fonction()
        except Exception as exc:
            log.warning("état d'écoute indisponible : %s", exc)
    alertes = getattr(ctx, "alertes", None)
    assistee = getattr(ctx, "ecoute_assistee", None)
    try:
        modele_pret = bool(ctx.voice.model_ready())
    except Exception:
        modele_pret = False
    return {
        "sous_titres": False,
        "journal": False,
        "enregistrement": {"actif": False, "nom": None, "secondes": 0},
        "assistee": {"actif": bool(assistee and assistee.actif), "latence_ms": assistee.latence_ms if assistee else None},
        "alertes": bool(alertes and alertes.actif),
        "modele_pret": modele_pret,
        "raison": (assistee.raison if assistee and assistee.raison else None) or (alertes.raison if alertes else None),
    }


def creer_routeur(ctx) -> APIRouter:
    alertes = ServiceAlertes(ctx)
    assistee = ServiceEcouteAssistee(ctx)
    bouton = ServiceBouton(ctx)
    # Attachés tout de suite : l'équipe écoute (état d'écoute), la page téléphone et les écrans les
    # trouvent par getattr(ctx, "alertes" / "ecoute_assistee" / "bouton", None).
    ctx.alertes = alertes
    ctx.ecoute_assistee = assistee
    ctx.bouton = bouton

    routeur = APIRouter()
    suivi: dict = {"tache": None, "prenom": prenom_depuis(ctx.settings.user.user_name)}
    verrou_reglages = asyncio.Lock()

    # ------------------------------------------------------------------ alertes
    @routeur.get("/api/alertes")
    def lire_alertes():
        return alertes.etat()

    @routeur.post("/api/alertes/tester")
    async def tester(body: TesterIn):
        try:
            return await asyncio.to_thread(alertes.tester, body.type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                422, f"Type d'alerte inconnu : « {body.type} ». Types : {', '.join(TYPES_ACOUSTIQUES + ('prenom',))}."
            ) from exc

    @routeur.post("/api/alertes/activer")
    async def activer():
        exiger_lunettes_pc(ctx, "alertes_sonores")  # micro de l'ordinateur
        if ctx.settings.user.privacy_mode:
            raise HTTPException(409, CONFIDENTIEL)
        try:
            await asyncio.to_thread(alertes.demarrer)
        except EcouteRefusee as exc:
            raise HTTPException(409, str(exc)) from exc
        user = ctx.settings.update({"alertes_actives": True})
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return alertes.etat()

    @routeur.post("/api/alertes/desactiver")
    async def desactiver():
        user = ctx.settings.update({"alertes_actives": False})
        await asyncio.to_thread(alertes.arreter)
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return alertes.etat()

    # ------------------------------------------------------------------ écoute assistée
    @routeur.get("/api/ecoute/assistee")
    def lire_assistee():
        return assistee.etat()

    @routeur.post("/api/ecoute/assistee/demarrer")
    async def assistee_demarrer(body: AssisteeIn | None = None):
        exiger_lunettes_pc(ctx, "ecoute_assistee")  # micro et haut-parleur de l'ordinateur
        body = body or AssisteeIn()
        try:
            await asyncio.to_thread(assistee.demarrer, body.gain_db, body.reduction)
        except EcouteRefusee as exc:
            raise HTTPException(409, str(exc)) from exc
        return etat_ecoute(ctx)

    @routeur.post("/api/ecoute/assistee/arreter")
    async def assistee_arreter():
        await asyncio.to_thread(assistee.arreter)
        return etat_ecoute(ctx)

    # ------------------------------------------------------------------ bouton des lunettes
    @routeur.get("/api/lunettes/bouton")
    def lire_bouton():
        return bouton.etat()

    @routeur.post("/api/lunettes/bouton/apprendre")
    async def apprendre(body: ApprendreIn | None = None):
        exiger_lunettes_pc(ctx, "bouton_lunettes")  # lien Bluetooth de l'ordinateur
        body = body or ApprendreIn()
        return await bouton.apprendre(body.secondes)

    @routeur.delete("/api/lunettes/bouton")
    def oublier():
        return bouton.oublier()

    # ------------------------------------------------------------------ bus d'événements
    def appliquer_reglages() -> None:
        """Aligne les services sur les réglages (fil de travail : démarrer l'écoute peut prendre du temps)."""
        u = ctx.settings.user
        if u.privacy_mode:
            if alertes.actif:
                alertes.arreter(CONFIDENTIEL)
            if assistee.actif:
                assistee.arreter(CONFIDENTIEL)
            return
        prenom = prenom_depuis(u.user_name)
        if prenom != suivi["prenom"]:
            suivi["prenom"] = prenom
            alertes.recharger_prenom()
        if u.alertes_actives and not alertes.actif:
            raison_pc = raison_capture_pc(ctx)
            if raison_pc is not None:
                # Lunettes d'abord : activées par les réglages, les alertes attendent les lunettes et le disent.
                # Attestées par le téléphone seulement, elles sont dehors : le micro de l'ordinateur reste fermé.
                alertes.raison = raison_pc
                return
            try:
                alertes.demarrer()
            except EcouteRefusee as exc:
                alertes.raison = str(exc)
        elif not u.alertes_actives and alertes.actif:
            alertes.arreter()

    def alertes_en_attente() -> bool:
        u = ctx.settings.user
        return bool(u.alertes_actives) and not u.privacy_mode and not alertes.actif

    async def reagir_reglages() -> None:
        async with verrou_reglages:
            try:
                await asyncio.to_thread(appliquer_reglages)
            except Exception as exc:
                log.warning("réglages des alertes non appliqués : %s", exc)

    async def suivre_evenements() -> None:
        file = ctx.hub.subscribe()
        try:
            while True:
                evenement = await file.get()
                genre = evenement.get("type")
                try:
                    if genre == "glasses.packet":
                        bouton.recevoir_paquet(evenement)
                    elif genre in ("settings.updated", "privacy.mode"):
                        asyncio.get_running_loop().create_task(reagir_reglages())
                    elif genre in EVENEMENTS_PRESENCE and alertes_en_attente():
                        # Lunettes arrivées (téléphone attesté, Bluetooth, micro des lunettes) ou écoute
                        # relancée : des alertes voulues mais pas démarrées démarrent maintenant. Filtré ici
                        # pour ne pas lancer une tâche à chaque changement d'état de la voix.
                        asyncio.get_running_loop().create_task(reagir_reglages())
                except Exception as exc:  # un événement mal formé ne coupe pas le suivi
                    log.warning("événement %s non traité : %s", genre, exc)
        finally:
            ctx.hub.unsubscribe(file)

    async def demarrage() -> None:
        boucle = asyncio.get_running_loop()
        bouton.loop = boucle
        suivi["tache"] = boucle.create_task(suivre_evenements())
        if ctx.settings.user.alertes_actives and not ctx.settings.user.privacy_mode:
            async def plus_tard() -> None:
                # Après l'autodémarrage de l'écoute (main.py la lance une seconde après le démarrage) :
                # deux démarrages simultanés ouvriraient deux flux micro.
                await asyncio.sleep(3.0)
                await reagir_reglages()

            suivi["demarrage"] = boucle.create_task(plus_tard())

    async def arret() -> None:
        for cle in ("tache", "demarrage"):
            tache = suivi.get(cle)
            if tache is not None:
                tache.cancel()
        await asyncio.to_thread(alertes.arreter)
        await asyncio.to_thread(assistee.arreter)

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    return routeur
