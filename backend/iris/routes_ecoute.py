"""Routes de l'écoute locale et du mode cours (interface C du chantier du 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans
sous_titres.py, journal.py, enregistrement_audio.py et cours.py ; ce fichier traduit HTTP <-> services,
publie l'état d'écoute, et fait tourner l'entretien (journal continu, mode confidentiel, mémoire
suspendue, rétention).

Services attachés à ctx : ctx.sous_titres, ctx.journal, ctx.enregistreur, ctx.cours,
ctx.ecoute_etat() -> dict et ctx.publier_ecoute_etat() (publie l'événement ecoute.etat).
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .cours import RefusMoteur, ServiceCours, rediger_proces_verbal
from .enregistrement_audio import EnregistreurAudio, dossier_audio, purger_fichiers
from .journal import JournalEcoute
from .sous_titres import CONFIDENTIEL, EcouteImpossible, SousTitres

log = logging.getLogger("iris.ecoute")

TIC_S = 2.0  # cadence de l'entretien : mode confidentiel et mémoire suspendue sont appliqués en moins de 2 s
PREMIER_TIC_S = 5.0  # laisse l'écoute automatique démarrer d'abord (un seul flux micro à la fois)
REESSAI_JOURNAL_S = 60.0
PURGE_S = 3600.0


class ResumeIn(BaseModel):
    lignes: list[Any] | None = None


class CoursIn(BaseModel):
    titre: str = ""
    matiere: str | None = None


class GenererIn(BaseModel):
    quoi: str = "tout"


class ImportIn(BaseModel):
    titre: str = ""
    matiere: str | None = None
    nom_fichier: str | None = None
    data: str = ""


def _etat_service(service: Any, champ_actif: tuple[str, ...]) -> dict | None:
    """État d'un service d'une autre équipe (alertes, écoute assistée), lu sans rien supposer de sa forme.

    Les attributs d'abord : appeler leur etat() pourrait les faire rappeler ecoute_etat() en retour."""
    if service is None:
        return None
    for nom in champ_actif:
        valeur = getattr(service, nom, None)
        if valeur is not None and not callable(valeur):
            return {"actif": bool(valeur), "latence_ms": getattr(service, "latence_ms", None)}
    etat = getattr(service, "etat", None)
    if callable(etat):
        resultat = etat()
        if isinstance(resultat, dict):
            actif = next((resultat[n] for n in champ_actif if n in resultat), False)
            return {"actif": bool(actif), "latence_ms": resultat.get("latence_ms")}
    return None


def creer_routeur(ctx) -> APIRouter:
    journal = JournalEcoute(ctx.db, ctx.crypto, ctx.settings, memory=getattr(ctx, "memory", None))
    sous_titres = SousTitres(ctx)
    enregistreur = EnregistreurAudio(ctx)
    cours = ServiceCours(ctx, sous_titres)
    # Attachés tout de suite : les autres équipes (interprète, quotidien, page téléphone) les trouvent
    # par getattr(ctx, "journal", None) avant même le démarrage.
    ctx.sous_titres = sous_titres
    ctx.journal = journal
    ctx.enregistreur = enregistreur
    ctx.cours = cours

    garde = threading.local()  # évite une récursion si un service voisin rappelle ecoute_etat()
    entretien: dict[str, Any] = {"tache": None, "raison_journal": None, "voulait_journal": False,
                                 "dernier_essai_journal": 0.0, "derniere_purge": None}

    def ecoute_etat() -> dict:
        if getattr(garde, "actif", False):
            return {}
        garde.actif = True
        try:
            u = ctx.settings.user
            demandes = sous_titres.demandes()
            try:
                assistee = _etat_service(getattr(ctx, "ecoute_assistee", None), ("actif", "active")) or {}
            except Exception as exc:
                log.debug("état de l'écoute assistée illisible : %s", exc)
                assistee = {}
            try:
                alertes = _etat_service(getattr(ctx, "alertes", None), ("actives", "actif", "active")) or {}
            except Exception as exc:
                log.debug("état des alertes illisible : %s", exc)
                alertes = {}
            suspendue = getattr(getattr(ctx, "memory", None), "suspendue", None)
            raison = None
            if u.privacy_mode and (demandes or u.journal_continu):
                raison = CONFIDENTIEL
            else:
                raison = sous_titres.raison or enregistreur.raison or entretien["raison_journal"]
            if not raison and suspendue and (u.journal_continu or cours.cours_actif()):
                raison = f"Mémorisation suspendue ({suspendue}) : le journal et les cours n'écrivent rien."
            actif = cours.cours_actif()
            return {
                "sous_titres": sous_titres.actif and "ecran" in demandes,
                "journal": bool(u.journal_continu) and sous_titres.actif and "journal" in demandes and not suspendue,
                "enregistrement": enregistreur.etat(),
                "assistee": {"actif": bool(assistee.get("actif")), "latence_ms": assistee.get("latence_ms")},
                "alertes": bool(alertes.get("actif")),
                "modele_pret": sous_titres.modele_pret(),
                "raison": raison,
                # Compléments (hors contrat minimal) : ce qui fait tourner la reconnaissance, et le cours en direct.
                "transcription_active": sous_titres.actif,
                "demandes": demandes,
                "memoire_suspendue": suspendue,
                "cours": ({"id": actif["id"], "titre": actif["titre"], "secondes": actif["duree_s"], "lignes": actif["lignes"]}
                          if actif else None),
            }
        finally:
            garde.actif = False

    def publier_ecoute_etat() -> None:
        try:
            etat = ecoute_etat()
        except Exception as exc:  # pragma: no cover - l'état ne doit jamais faire tomber un service
            log.warning("état d'écoute impossible à calculer : %s", exc)
            return
        if etat:
            ctx.hub.publish("ecoute.etat", **etat)

    ctx.ecoute_etat = ecoute_etat
    ctx.publier_ecoute_etat = publier_ecoute_etat
    sous_titres.notifier = publier_ecoute_etat
    enregistreur.notifier = publier_ecoute_etat
    cours.notifier = publier_ecoute_etat

    def journaliser_phrase(moment: float, texte: str) -> None:
        # Le journal continu garde les phrases finales, et seulement s'il est activé (réglage explicite).
        if ctx.settings.user.journal_continu:
            journal.ajouter(texte, "sous-titres", datetime.fromtimestamp(moment, timezone.utc))

    sous_titres.abonner_finals("journal", journaliser_phrase)

    # ------------------------------------------------------------------ entretien
    def tic() -> None:
        u = ctx.settings.user
        voice = getattr(ctx, "voice", None)
        if u.privacy_mode:
            # Mode confidentiel : tout s'arrête, tout de suite, et rien ne redémarre tant qu'il est actif.
            # Le cours d'abord : il garde ainsi sa dernière phrase et la raison de son arrêt.
            cours.verifier()
            if sous_titres.actif or sous_titres.demandes():
                sous_titres.arreter_tout()
            if enregistreur.actif:
                try:
                    enregistreur.arreter()
                except EcouteImpossible:
                    pass
            entretien["voulait_journal"] = False
        else:
            cours.verifier()
            veut = bool(u.journal_continu)
            present = "journal" in sous_titres.demandes()
            if veut and not (present and sous_titres.actif):
                maintenant = time.monotonic()
                vient_d_activer = not entretien["voulait_journal"]
                ecoute_arretee_par_l_utilisateur = (voice is not None and not voice.running
                                                    and getattr(voice, "stopped_by_user", False))
                if ecoute_arretee_par_l_utilisateur and not vient_d_activer:
                    # On ne relance pas une écoute que l'utilisateur a lui-même arrêtée ou mise en pause.
                    raison = "Journal continu en attente : l'écoute a été arrêtée."
                    if raison != entretien["raison_journal"]:
                        entretien["raison_journal"] = raison
                        publier_ecoute_etat()
                elif vient_d_activer or maintenant - entretien["dernier_essai_journal"] >= REESSAI_JOURNAL_S:
                    entretien["dernier_essai_journal"] = maintenant
                    try:
                        sous_titres.demarrer("journal")
                        entretien["raison_journal"] = None
                    except EcouteImpossible as exc:
                        raison = f"Journal continu : {exc.message}"
                        if raison != entretien["raison_journal"]:
                            entretien["raison_journal"] = raison
                            publier_ecoute_etat()
            elif not veut and present:
                sous_titres.arreter("journal")
                entretien["raison_journal"] = None
            elif veut and entretien["raison_journal"]:
                entretien["raison_journal"] = None
                publier_ecoute_etat()
            entretien["voulait_journal"] = veut
        # Première purge au premier tour (horloge monotone = temps depuis l'allumage : ne pas attendre une heure).
        if entretien["derniere_purge"] is None or time.monotonic() - entretien["derniere_purge"] >= PURGE_S:
            entretien["derniere_purge"] = time.monotonic()
            purger()

    def purger() -> dict:
        resultat = {"journal": 0, "cours": 0, "audio": 0}
        try:
            resultat["journal"] = journal.purger()
            resultat["cours"] = cours.purger()
            jours = int(getattr(ctx.settings.user, "retention_days", 0) or 0)
            resultat["audio"] = len(purger_fichiers(dossier_audio(ctx), jours,
                                                    epargnes=enregistreur.fichiers_en_cours() | cours.fichiers_en_cours()))
        except Exception as exc:
            log.warning("purge de l'écoute en erreur : %s", exc)
        if any(resultat.values()):
            ctx.hub.publish("ecoute.purge", **resultat)
        return resultat

    async def boucle_entretien() -> None:
        await asyncio.sleep(PREMIER_TIC_S)
        while True:
            try:
                await asyncio.to_thread(tic)
            except Exception as exc:  # une erreur d'entretien n'arrête pas la boucle
                log.warning("entretien de l'écoute : %s", exc)
            await asyncio.sleep(TIC_S)

    async def demarrage() -> None:
        try:
            await asyncio.to_thread(cours.reparer)
        except Exception as exc:
            log.warning("réparation des cours interrompus : %s", exc)
        entretien["tache"] = asyncio.get_running_loop().create_task(boucle_entretien())

    async def arret() -> None:
        tache = entretien.get("tache")
        if tache is not None:
            tache.cancel()

        def fermer() -> None:
            cours.fermer()
            if enregistreur.actif:
                try:
                    enregistreur.arreter()
                except EcouteImpossible:
                    pass
            sous_titres.arreter_tout()

        await asyncio.to_thread(fermer)

    # ------------------------------------------------------------------ routes
    routeur = APIRouter()

    @routeur.get("/api/ecoute/etat")
    def etat():
        return ecoute_etat()

    @routeur.post("/api/ecoute/sous-titres/demarrer")
    def sous_titres_demarrer():
        try:
            sous_titres.demarrer("ecran")
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        return ecoute_etat()

    @routeur.post("/api/ecoute/sous-titres/arreter")
    def sous_titres_arreter():
        lignes = sous_titres.arreter("ecran")
        return {"etat": ecoute_etat(), "lignes": lignes}

    @routeur.get("/api/ecoute/transcription")
    def transcription():
        return {"lignes": sous_titres.lignes()}

    @routeur.post("/api/ecoute/resume")
    async def resume(body: ResumeIn):
        lignes = body.lignes if body.lignes is not None else sous_titres.lignes()
        try:
            r = await rediger_proces_verbal(ctx, lignes)
        except RefusMoteur as exc:
            raise HTTPException(exc.status, exc.detail)
        return {"resume": r["resume"], "local": r["local"]}

    @routeur.post("/api/ecoute/enregistrement/demarrer")
    def enregistrement_demarrer():
        try:
            return enregistreur.demarrer()
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)

    @routeur.post("/api/ecoute/enregistrement/arreter")
    def enregistrement_arreter():
        try:
            return enregistreur.arreter()
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)

    # ------------------------------------------------------------------ journal
    @routeur.get("/api/journal")
    def journal_lire(q: str | None = Query(default=None), debut: str | None = Query(default=None),
                     fin: str | None = Query(default=None), limit: int = Query(default=50)):
        try:
            entrees = journal.chercher(q, debut=debut, fin=fin, limit=limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"entrees": entrees}

    @routeur.delete("/api/journal")
    def journal_effacer(debut: str | None = Query(default=None), fin: str | None = Query(default=None),
                        tout: bool = Query(default=False)):
        try:
            n = journal.supprimer_plage(debut, fin, tout=tout)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        ctx.consent.log("journal_efface", detail=f"{n} entrée(s) ; debut={debut or '-'} fin={fin or '-'}")
        return {"supprimees": n}

    # ------------------------------------------------------------------ mémoire par plage
    def memoire_plage(debut: str | None, fin: str | None) -> dict:
        try:
            n = ctx.memory.supprimer_plage(debut, fin)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        ctx.consent.log("memory_range_deleted", detail=f"{n} souvenir(s) ; debut={debut or '-'} fin={fin or '-'}")
        ctx.hub.publish("memory.updated", count=ctx.memory.count())
        return {"supprimes": n}

    # Chemin du contrat. ATTENTION : main.py déclare DELETE /api/memory/{memory_id} avant que ce routeur
    # soit branché, et c'est lui qui reçoit « plage » tant que main.py ne déclare pas ce chemin avant
    # le sien (voir le rapport de l'équipe écoute). Le chemin ci-dessous fonctionne dès aujourd'hui.
    @routeur.delete("/api/memory/plage")
    def memoire_plage_contrat(debut: str | None = Query(default=None), fin: str | None = Query(default=None)):
        return memoire_plage(debut, fin)

    @routeur.delete("/api/ecoute/memoire/plage")
    def memoire_plage_ecoute(debut: str | None = Query(default=None), fin: str | None = Query(default=None)):
        return memoire_plage(debut, fin)

    # ------------------------------------------------------------------ cours
    @routeur.post("/api/cours/demarrer")
    def cours_demarrer(body: CoursIn):
        try:
            return cours.demarrer(body.titre, body.matiere)
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)

    @routeur.post("/api/cours/importer")
    def cours_importer(body: ImportIn):
        try:
            return cours.importer(body.titre, body.matiere, body.nom_fichier, body.data)
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @routeur.get("/api/cours")
    def cours_liste():
        return {"cours": cours.liste()}

    @routeur.get("/api/cours/{cours_id}")
    def cours_detail(cours_id: str):
        d = cours.detail(cours_id)
        if d is None:
            raise HTTPException(404, "Cours introuvable.")
        return d

    @routeur.post("/api/cours/{cours_id}/arreter")
    def cours_arreter(cours_id: str):
        r = cours.arreter(cours_id)
        if r is None:
            raise HTTPException(404, "Cours introuvable.")
        return r

    @routeur.post("/api/cours/{cours_id}/generer")
    async def cours_generer(cours_id: str, body: GenererIn):
        try:
            return await cours.generer(cours_id, body.quoi)
        except LookupError:
            raise HTTPException(404, "Cours introuvable.")
        except RefusMoteur as exc:
            raise HTTPException(exc.status, exc.detail)

    @routeur.get("/api/cours/{cours_id}/exporter")
    def cours_exporter(cours_id: str):
        md = cours.exporter(cours_id)
        if md is None:
            raise HTTPException(404, "Cours introuvable.")
        titre = (cours.detail(cours_id) or {}).get("titre") or "cours"
        ascii_ = re.sub(r"[^A-Za-z0-9_-]+", "-", titre).strip("-")[:60] or "cours"
        entete = f"attachment; filename=\"{ascii_}.md\"; filename*=UTF-8''{quote(titre[:60] + '.md')}"
        return Response(content=md, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": entete})

    @routeur.delete("/api/cours/{cours_id}")
    def cours_supprimer(cours_id: str):
        if not cours.supprimer(cours_id):
            raise HTTPException(404, "Cours introuvable.")
        return {"supprime": True}

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    # Un tour d'entretien et une purge sans attendre la boucle (tests, diagnostic).
    ctx.ecoute_tic = tic
    ctx.ecoute_purger = purger
    return routeur
