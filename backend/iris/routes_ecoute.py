"""Routes de l'écoute locale et du mode cours (interface C du chantier du 2026-09-13).

Branché par main._brancher_modules, derrière l'authentification. Le travail vit dans
sous_titres.py, journal.py, enregistrement_audio.py et cours.py ; ce fichier traduit HTTP <-> services,
publie l'état d'écoute, et fait tourner l'entretien (journal continu, mode confidentiel, mémoire
suspendue, rétention).

Services attachés à ctx : ctx.sous_titres, ctx.journal, ctx.enregistreur, ctx.cours,
ctx.ecoute_etat() -> dict et ctx.publier_ecoute_etat() (publie l'événement ecoute.etat).

Hors contrat minimal : POST /api/cours/importer-wav (corps = le fichier WAV en octets bruts, paramètres
titre, matiere, nom_fichier) pour les longs enregistrements ; POST /api/cours/{id}/generer répond 202
avec « en_arriere_plan » quand la transcription dépasse 5 parties.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from .cours import (
    PREFIXE_FLUX, TAILLE_MAX_FLUX, TAILLE_MAX_IMPORT, TROP_VOLUMINEUX, TROP_VOLUMINEUX_FLUX, RefusMoteur, ServiceCours,
    rediger_proces_verbal,
)
from .enregistrement_audio import (
    ESPACE_MIN_DEMARRAGE, EnregistreurAudio, arret_par_suspension, dossier_audio, espace_libre, purger_fichiers,
)
from .journal import JournalEcoute
from .sous_titres import CONFIDENTIEL, EcouteImpossible, SousTitres
from .lunettes_presence import exiger_lunettes, exiger_lunettes_pc, raison_capture_pc

log = logging.getLogger("iris.ecoute")

TIC_S = 2.0  # cadence de l'entretien : mode confidentiel et mémoire suspendue sont appliqués en moins de 2 s
PREMIER_TIC_S = 5.0  # laisse l'écoute automatique démarrer d'abord (un seul flux micro à la fois)
REESSAI_JOURNAL_S = 60.0
# Sous-titres démarrés depuis une session distante (téléphone connecté avec le mot de passe) : ils ouvrent le
# micro d'une pièce de la maison. Sans aucune consultation de cette session pendant ce délai (page fermée,
# téléphone éteint sans que l'arrêt parte), l'ordinateur les arrête lui-même.
DUREE_MAX_DISTANT_S = 30 * 60.0
ARRET_DISTANT = ("Sous-titres arrêtés : démarrés depuis le téléphone, ils n'ont pas été consultés depuis "
                 "30 minutes. Le micro de l'ordinateur ne reste pas ouvert sans personne pour les lire.")
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
                                 "dernier_essai_journal": 0.0, "derniere_purge": None,
                                 # Bail des sous-titres démarrés à distance : heure (monotone) de la dernière
                                 # consultation par une session distante, None s'ils ont été démarrés ici.
                                 "distant_vu": None, "raison_distant": None}

    def requete_distante(request: Request | None) -> bool:
        """La requête vient-elle d'une session distante (mot de passe, téléphone) ou d'un intermédiaire ?
        L'application de bureau présente le jeton maître depuis cet ordinateur : elle n'est pas distante."""
        if request is None:
            return False
        for entete in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "forwarded", "x-forwarded-host"):
            if request.headers.get(entete):
                return True
        entete = request.headers.get("authorization", "")
        jeton = entete[7:] if entete.lower().startswith("bearer ") else request.query_params.get("token", "")
        comptes = getattr(ctx, "comptes", None)
        try:
            return bool(jeton) and comptes is not None and bool(comptes.session_valide(jeton))
        except Exception as exc:  # pragma: no cover - un compte illisible ne bloque pas l'écoute
            log.debug("session illisible : %s", exc)
            return False

    def consulter_depuis(request: Request | None) -> None:
        if entretien["distant_vu"] is not None and requete_distante(request):
            entretien["distant_vu"] = time.monotonic()

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
                raison = (sous_titres.raison or enregistreur.raison or entretien["raison_journal"]
                          or entretien["raison_distant"])
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
            vu = entretien["distant_vu"]
            if vu is not None and "ecran" not in sous_titres.demandes():
                entretien["distant_vu"] = None  # arrêtés autrement : plus de bail à surveiller
            elif vu is not None and time.monotonic() - vu >= DUREE_MAX_DISTANT_S:
                entretien["distant_vu"] = None
                entretien["raison_distant"] = ARRET_DISTANT
                log.info("sous-titres distants arrêtés : aucune consultation depuis %.0f s", DUREE_MAX_DISTANT_S)
                sous_titres.arreter("ecran")
                publier_ecoute_etat()
            suspendue = getattr(getattr(ctx, "memory", None), "suspendue", None)
            if enregistreur.actif and suspendue:
                # Mode invité ou zone sans mémoire : l'enregistrement en cours s'arrête aussi, même si
                # aucun bloc n'arrive (la session le vérifie à chaque bloc ; ce tour couvre le micro muet).
                try:
                    enregistreur.arreter()
                except EcouteImpossible:
                    pass  # déjà terminé seul par la session, qui a noté sa raison
                enregistreur.derniere_raison = arret_par_suspension(suspendue)
                publier_ecoute_etat()
            veut = bool(u.journal_continu)
            present = "journal" in sous_titres.demandes()
            if veut and not (present and sous_titres.actif):
                maintenant = time.monotonic()
                vient_d_activer = not entretien["voulait_journal"]
                ecoute_arretee_par_l_utilisateur = (voice is not None and not voice.running
                                                    and getattr(voice, "stopped_by_user", False))
                raison_pc = raison_capture_pc(ctx)
                if raison_pc is not None:
                    # Lunettes d'abord : le journal continu attend les lunettes (l'écoute refuserait de
                    # toute façon d'ouvrir le micro) et le dit, au lieu de réessayer en silence. Des
                    # lunettes attestées par le téléphone ne suffisent pas : le micro serait celui de
                    # l'ordinateur, dans une maison où leur porteur n'est pas.
                    raison = f"Journal continu en attente : {raison_pc}"
                    if raison != entretien["raison_journal"]:
                        entretien["raison_journal"] = raison
                        publier_ecoute_etat()
                elif ecoute_arretee_par_l_utilisateur and not vient_d_activer:
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
        try:
            await cours.annuler_generations()
        except Exception as exc:  # pragma: no cover - l'arrêt continue quoi qu'il arrive
            log.warning("générations de cours non annulées : %s", exc)

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
    def etat(request: Request):
        consulter_depuis(request)
        return ecoute_etat()

    @routeur.post("/api/ecoute/sous-titres/demarrer")
    def sous_titres_demarrer(request: Request):
        exiger_lunettes_pc(ctx, "sous_titres")  # micro de l'ordinateur
        deja = sous_titres.actif and "ecran" in sous_titres.demandes()
        try:
            sous_titres.demarrer("ecran")
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        entretien["raison_distant"] = None
        if requete_distante(request):
            # Démarrés (ou redemandés) à distance : bail de DUREE_MAX_DISTANT_S, renouvelé à chaque consultation
            # distante. Déjà démarrés ici, sur l'ordinateur : pas de bail, l'utilisateur est devant l'écran.
            if not deja or entretien["distant_vu"] is not None:
                entretien["distant_vu"] = time.monotonic()
        else:
            entretien["distant_vu"] = None
        return ecoute_etat()

    @routeur.post("/api/ecoute/sous-titres/arreter")
    def sous_titres_arreter():
        lignes = sous_titres.arreter("ecran")
        entretien["distant_vu"] = None
        entretien["raison_distant"] = None
        return {"etat": ecoute_etat(), "lignes": lignes}

    @routeur.get("/api/ecoute/transcription")
    def transcription(request: Request):
        consulter_depuis(request)
        return {"lignes": sous_titres.lignes()}

    @routeur.post("/api/ecoute/resume")
    async def resume(body: ResumeIn):
        exiger_lunettes(ctx, "proces_verbal")
        lignes = body.lignes if body.lignes is not None else sous_titres.lignes()
        try:
            r = await rediger_proces_verbal(ctx, lignes)
        except RefusMoteur as exc:
            raise HTTPException(exc.status, exc.detail)
        return {"resume": r["resume"], "local": r["local"]}

    @routeur.post("/api/ecoute/enregistrement/demarrer")
    def enregistrement_demarrer():
        exiger_lunettes_pc(ctx, "enregistrement_audio")  # micro de l'ordinateur
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
        if not tout:
            return {"supprimees": n}
        # Tout le journal : le journal technique (backend.log, non chiffré) est vidé aussi.
        try:
            from .verrou import purger_journal_technique

            techniques = purger_journal_technique(None)
        except Exception as exc:  # pragma: no cover - l'effacement demandé a déjà eu lieu
            log.warning("journal technique non vidé : %s", exc)
            techniques = 0
        return {"supprimees": n, "journal_technique": techniques}

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
        exiger_lunettes_pc(ctx, "cours")  # micro de l'ordinateur
        try:
            return cours.demarrer(body.titre, body.matiere)
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)

    @routeur.post("/api/cours/importer")
    async def cours_importer(request: Request):
        exiger_lunettes(ctx, "cours")
        # Corps lu sans le décoder dans la boucle : analyser 200 Mo de JSON la figerait (voix, WebSocket).
        longueur = request.headers.get("content-length", "")
        if longueur.isdigit() and int(longueur) > TAILLE_MAX_IMPORT * 4 // 3 + 64 * 1024:
            raise HTTPException(422, TROP_VOLUMINEUX)
        corps = await request.body()

        def importer() -> dict:
            try:
                body = ImportIn.model_validate_json(corps)
            except ValidationError:
                raise HTTPException(422, "Demande illisible : titre, matiere, nom_fichier et data (WAV en base64) attendus.")
            return cours.importer(body.titre, body.matiere, body.nom_fichier, body.data)

        try:
            return await asyncio.to_thread(importer)
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @routeur.post("/api/cours/importer-wav")
    async def cours_importer_wav(request: Request, titre: str = Query(default=""),
                                 matiere: str | None = Query(default=None), nom_fichier: str | None = Query(default=None)):
        """Import d'un long enregistrement : le corps est le fichier WAV lui-même (octets bruts), écrit sur le
        disque au fil de la réception. Rien n'est gardé en mémoire ni encodé en base64."""
        exiger_lunettes(ctx, "cours")
        try:
            cours.verifier_import()  # refus immédiat, avant de recevoir des centaines de mégaoctets
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        longueur = request.headers.get("content-length", "")
        if longueur.isdigit() and int(longueur) > TAILLE_MAX_FLUX:
            raise HTTPException(422, TROP_VOLUMINEUX_FLUX)
        dossier = dossier_audio(ctx)
        if longueur.isdigit() and espace_libre(dossier) < ESPACE_MIN_DEMARRAGE + 2 * int(longueur):
            raise HTTPException(409, "Espace disque insuffisant pour importer ce cours.")
        chemin = dossier / f"{PREFIXE_FLUX}{uuid.uuid4().hex}.partiel"
        remis = False
        try:
            recu = 0
            tampon = bytearray()
            with open(chemin, "wb") as fichier:
                async for morceau in request.stream():
                    recu += len(morceau)
                    if recu > TAILLE_MAX_FLUX:
                        raise HTTPException(422, TROP_VOLUMINEUX_FLUX)
                    tampon += morceau
                    if len(tampon) >= 4 * 1024 * 1024:
                        await asyncio.to_thread(fichier.write, bytes(tampon))
                        tampon.clear()
                if tampon:
                    await asyncio.to_thread(fichier.write, bytes(tampon))
            if recu == 0:
                raise HTTPException(422, "Fichier manquant.")
            remis = True  # importer_fichier efface lui-même le fichier s'il refuse
            return await asyncio.to_thread(cours.importer_fichier, titre, matiere, nom_fichier, chemin)
        except EcouteImpossible as exc:
            raise HTTPException(exc.code, exc.message)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        finally:
            if not remis:
                try:
                    chemin.unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("fichier d'import incomplet non effacé : %s", exc)

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
        exiger_lunettes(ctx, "cours")
        try:
            resultat = await cours.generer(cours_id, body.quoi)
            if resultat.get("en_arriere_plan"):
                # Long cours : accepté, rédigé en arrière-plan (progression par cours.etat).
                return JSONResponse(status_code=202, content=resultat)
            return resultat
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
