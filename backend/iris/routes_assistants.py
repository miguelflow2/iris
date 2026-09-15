"""Routes des assistants (interface H du chantier du 2026-09-13) : pas à pas, entraînement, prix.

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans pas_a_pas.py,
entrainement.py et prix.py ; ce fichier traduit HTTP <-> services, branche la voix, arrête tout quand le
mode confidentiel s'allume et fait tourner la purge de l'historique des séances. Chaque service est
construit séparément : un module en panne ne retire que ses propres routes, jamais celles des deux autres
(ni le démarrage d'IRIS).

Attachés à ctx : ctx.pas_a_pas, ctx.entrainement, ctx.prix.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .lunettes_presence import exiger_lunettes, exiger_lunettes_pc

log = logging.getLogger("iris.assistants.routes")

PURGE_S = 3600.0
# Commandes qui arrêtent ou suspendent : permises sans lunettes (seules les actions d'IRIS les exigent).
ACTIONS_D_ARRET = frozenset({"terminer", "annuler_minuteur", "pause"})


class ImageIn(BaseModel):
    media_type: str = "image/jpeg"
    data: str = ""


class PasAPasDemarrerIn(BaseModel):
    sujet: str = ""
    type: str = "autre"
    etapes: list[Any] | None = None
    parler: bool = True


class PasAPasCommandeIn(BaseModel):
    action: str
    secondes: int | None = None  # « lance un minuteur de 5 minutes » : durée dite quand l'étape n'en a pas
    image: ImageIn | None = None  # « est-ce que c'est bon ? » depuis le téléphone (sinon : photo des lunettes)
    parler: bool = True


class EntrainementDemarrerIn(BaseModel):
    exercice: str | None = None
    series_cibles: int | None = None
    repos_s: int | None = None
    parler: bool = True


class EntrainementCommandeIn(BaseModel):
    action: str
    parler: bool = True


class CleRechercheIn(BaseModel):
    cle: str = ""
    fournisseur: str | None = None  # "tavily" | "brave" | None (détecté d'après la clé)


class ComparerIn(BaseModel):
    source: str = "image"
    image: ImageIn | None = None
    requete: str | None = None
    parler: bool = False


def _routes_pas_a_pas(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, interruptions: list) -> None:
    from .pas_a_pas import ServicePasAPas

    service = ServicePasAPas(ctx)
    ctx.pas_a_pas = service

    @routeur.post("/api/pas-a-pas/demarrer")
    async def pas_a_pas_demarrer(body: PasAPasDemarrerIn):
        exiger_lunettes(ctx, "pas_a_pas")
        return await service.demarrer(body.sujet, body.type, body.etapes, parler=body.parler)

    @routeur.post("/api/pas-a-pas/commande")
    async def pas_a_pas_commande(body: PasAPasCommandeIn):
        # Arrêter reste toujours permis : on ne retient personne dans une session parce que ses lunettes
        # se sont éteintes.
        if body.action not in ACTIONS_D_ARRET:
            exiger_lunettes(ctx, "pas_a_pas")
        return await service.commande(body.action, secondes=body.secondes, parler=body.parler,
                                      image=body.image.model_dump() if body.image else None)

    @routeur.get("/api/pas-a-pas/etat")
    async def pas_a_pas_etat():
        return service.etat()

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)
    arrets.append(lambda: service.interrompre("arrêt du service"))
    interruptions.append(service.interrompre)


def _routes_entrainement(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list, interruptions: list,
                         purges: list) -> None:
    from .entrainement import ServiceEntrainement

    service = ServiceEntrainement(ctx)
    ctx.entrainement = service

    @routeur.post("/api/entrainement/demarrer")
    async def entrainement_demarrer(body: EntrainementDemarrerIn):
        exiger_lunettes(ctx, "entrainement")
        return await service.demarrer(body.exercice, body.series_cibles, body.repos_s, parler=body.parler)

    @routeur.post("/api/entrainement/commande")
    async def entrainement_commande(body: EntrainementCommandeIn):
        if body.action not in ACTIONS_D_ARRET:
            exiger_lunettes(ctx, "entrainement")
        return await service.commande(body.action, parler=body.parler)

    @routeur.get("/api/entrainement/etat")
    async def entrainement_etat():
        return service.etat()

    @routeur.get("/api/entrainement/seances")
    def entrainement_seances():
        return {"seances": service.seances(), "memoire_suspendue": getattr(ctx.memory, "suspendue", None),
                "retention_jours": int(getattr(ctx.settings.user, "retention_days", 0) or 0)}

    @routeur.delete("/api/entrainement/seances/{seance_id}")
    def entrainement_supprimer(seance_id: str):
        if not service.supprimer(seance_id):
            raise HTTPException(404, "Séance introuvable.")
        return {"supprime": True}

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)
    arrets.append(lambda: service.interrompre("arrêt du service"))
    interruptions.append(service.interrompre)
    purges.append(service.purger)


def _routes_prix(routeur: APIRouter, ctx: Any, demarrages: list, arrets: list) -> None:
    from .prix import ServicePrix

    service = ServicePrix(ctx)
    ctx.prix = service

    @routeur.post("/api/achats/comparer")
    async def achats_comparer(body: ComparerIn):
        # Photo par la caméra reliée à l'ordinateur : lunettes vues par l'ordinateur ; photo ou texte du téléphone : attestation.
        (exiger_lunettes_pc if (body.source or "") == "lunettes" and not body.requete else exiger_lunettes)(ctx, "comparer_prix")
        return await service.comparer(body.source, image=body.image.model_dump() if body.image else None,
                                      requete=body.requete, parler=body.parler)

    demarrages.append(service.brancher_voix)
    arrets.append(service.debrancher_voix)


def _routes_cle_recherche(routeur: APIRouter, ctx: Any) -> None:
    """Clé de la recherche web (coffre « recherche ») : la comparaison de prix en dépend, et aucun écran ne
    permettait de la saisir. Écran avancé (apportez votre clé) : la clé n'est JAMAIS renvoyée en clair."""
    from . import recherche_web
    from .security.secrets import SecretStore

    def etat() -> dict:
        secrets = getattr(ctx, "secrets", None)
        coffre = ""
        if secrets is not None:
            try:
                coffre = (secrets.get_api_key(recherche_web.COFFRE_CLE) or "").strip()
            except Exception:  # coffre indisponible : « non configurée » plutôt qu'une erreur 500
                coffre = ""
        env = recherche_web.resoudre_cle(None)
        resolue = recherche_web.resoudre_cle(secrets)
        return {
            "configuree": resolue is not None,
            # L'environnement (fichier .env) passe avant le coffre : le dire, sinon changer la clé ici
            # semblerait sans effet.
            "source": "environnement" if env else ("coffre" if coffre else None),
            "fournisseur": resolue[0] if resolue else None,
            "cle_masquee": SecretStore.mask(resolue[1]) if resolue else None,
            "coffre_defini": bool(coffre),
            "note": "La recherche web envoie la requête (nom du produit) au service de recherche choisi.",
        }

    @routeur.get("/api/recherche/cle")
    def cle_etat():
        return etat()

    @routeur.post("/api/recherche/cle")
    def cle_enregistrer(body: CleRechercheIn):
        cle = "".join((body.cle or "").split())
        if len(cle) < 8 or len(cle) > 400:
            raise HTTPException(422, "Clé de recherche invalide : collez la clé complète fournie par le service.")
        fournisseur = (body.fournisseur or "").strip().lower() or None
        if fournisseur not in (None, "tavily", "brave"):
            raise HTTPException(422, "Service de recherche inconnu : tavily ou brave.")
        secrets = getattr(ctx, "secrets", None)
        if secrets is None:
            raise HTTPException(409, "Le coffre des clés n'est pas disponible sur cet ordinateur.")
        secrets.set_api_key(recherche_web.COFFRE_CLE, f"{fournisseur}:{cle}" if fournisseur else cle)
        ctx.consent.log("cle_recherche_enregistree", detail=fournisseur or "détectée")
        return etat()

    @routeur.delete("/api/recherche/cle")
    def cle_effacer():
        secrets = getattr(ctx, "secrets", None)
        if secrets is not None:
            secrets.delete_api_key(recherche_web.COFFRE_CLE)
            ctx.consent.log("cle_recherche_effacee")
        return etat()


def creer_routeur(ctx) -> APIRouter:
    routeur = APIRouter()
    demarrages: list = []
    arrets: list = []
    interruptions: list = []
    purges: list = []
    for nom, brancher in (
        ("pas à pas", lambda: _routes_pas_a_pas(routeur, ctx, demarrages, arrets, interruptions)),
        ("entraînement", lambda: _routes_entrainement(routeur, ctx, demarrages, arrets, interruptions, purges)),
        ("comparaison de prix", lambda: _routes_prix(routeur, ctx, demarrages, arrets)),
        ("clé de recherche web", lambda: _routes_cle_recherche(routeur, ctx)),
    ):
        try:
            brancher()
        except Exception as exc:
            log.warning("assistants : %s non branché (%s)", nom, exc)

    taches: dict[str, Any] = {"purge": None, "confidentiel": None}

    async def boucle_purge() -> None:
        while True:
            for purger in purges:
                try:
                    await asyncio.to_thread(purger)
                except Exception as exc:  # une purge en erreur n'arrête pas les autres
                    log.warning("assistants : purge en erreur (%s)", exc)
            await asyncio.sleep(PURGE_S)

    async def suivre_confidentiel() -> None:
        # Le mode confidentiel coupe la voix : une session ou une séance qui continuerait d'annoncer ses
        # minuteurs dans le vide mentirait sur son état. On arrête tout dès l'événement.
        file = ctx.hub.subscribe()
        try:
            while True:
                evenement = await file.get()
                if evenement.get("type") != "privacy.mode" or not evenement.get("enabled"):
                    continue
                for interrompre in interruptions:
                    try:
                        interrompre("mode confidentiel")
                    except Exception as exc:
                        log.warning("assistants : interruption en erreur (%s)", exc)
        finally:
            ctx.hub.unsubscribe(file)

    async def demarrage() -> None:
        for demarrer in demarrages:
            try:
                demarrer()
            except Exception as exc:
                log.warning("assistants : démarrage en erreur (%s)", exc)
        boucle = asyncio.get_running_loop()
        if interruptions:
            taches["confidentiel"] = boucle.create_task(suivre_confidentiel())
        if purges:
            taches["purge"] = boucle.create_task(boucle_purge())

    async def arret() -> None:
        for cle in ("purge", "confidentiel"):
            if taches[cle] is not None:
                taches[cle].cancel()
        for arreter in arrets:
            try:
                arreter()
            except Exception as exc:
                log.warning("assistants : arrêt en erreur (%s)", exc)

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    return routeur
