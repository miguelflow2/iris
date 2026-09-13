"""Entraînement : compter les séries à la voix, chronométrer le repos, garder un historique chiffré.

Pensé pour la séance au sol ou au gym, téléphone dans le sac, mains sur la barre. Ce que le module fait
et ne fait pas, dit tel quel :

- IRIS ne compte PAS les répétitions. Aucun capteur de mouvement des lunettes n'est accessible (le
  fabricant ne documente que la caméra, le micro et le haut-parleur). C'est l'utilisateur qui dit
  « série terminée », « fini » ou « une de plus » ; IRIS compte les séries et chronomètre le repos.
- Le repos est annoncé : « Repos : 90 secondes. », « 10 secondes. », « Repos terminé. Série 4. ». Le
  chrono tourne sur l'ordinateur : une mise en veille retarde l'annonce.
- L'historique (exercice, séries, durée) est chiffré (ctx.crypto), soumis à la durée de conservation
  réglée dans Confidentialité, et rien n'est écrit quand la mémoire est suspendue (mode invité, zone
  sans mémoire). Aucun son n'est gardé : les commandes passent par l'écoute habituelle d'IRIS.

Service exposé sous ctx.entrainement (voir routes_assistants.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from .pas_a_pas import (ECOUTE_ARRETEE, correspond, duree_parlee, jetons, lire_duree, lire_nombre, maintenant_iso,
                        normaliser)

log = logging.getLogger("iris.entrainement")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entrainement_seances (
    id TEXT PRIMARY KEY,
    debut TEXT NOT NULL,
    donnees_enc BLOB NOT NULL,
    retenu_jusqua TEXT
);
CREATE INDEX IF NOT EXISTS idx_entrainement_debut ON entrainement_seances(debut);
"""

ACTIONS = ("serie", "pause", "reprendre", "terminer")
SERIES_MAX = 50
EXERCICE_MAX = 80
REPOS_MIN_S, REPOS_MAX_S = 10, 900
ANNONCE_AVANT_FIN_S = 10  # « 10 secondes. »
HISTORIQUE_MAX = 200

CONFIDENTIEL = "Le mode confidentiel est actif : l'entraînement est arrêté et ne peut pas démarrer tant qu'il l'est."
AUCUNE_SEANCE = "Aucune séance d'entraînement n'est en cours."
DEJA_EN_COURS = "Une séance est déjà en cours : terminez-la avant d'en commencer une autre."
LIMITE = (
    "IRIS ne compte pas les répétitions : aucun capteur de mouvement des lunettes n'est accessible. Dites « série "
    "terminée » à la fin de chaque série. Le repos est chronométré sur l'ordinateur : une mise en veille retarde "
    "l'annonce. L'historique est chiffré et suit la durée de conservation réglée dans Confidentialité."
)


class RefusEntrainement(HTTPException):
    """Refus documenté : un HTTPException avec sa phrase courte à dire à voix haute."""

    def __init__(self, statut: int, message: str, phrase: str | None = None):
        super().__init__(status_code=statut, detail=message)
        self.message = message
        self.phrase = phrase or message


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


# =============================================================================== phrases vocales
PHRASES_SERIE = ("serie terminee", "serie finie", "serie faite", "fini", "finie", "j ai fini", "une de plus",
                 "encore une de faite", "termine la serie", "j ai termine la serie")
NEGATIONS = ("pas", "non", "jamais", "presque")
PHRASES_PAUSE = ("pause", "fais une pause", "mets en pause", "mets pause", "on fait une pause")
PHRASES_REPRENDRE = ("reprendre", "reprends", "reprend", "on reprend", "je reprends", "fin de la pause")
PHRASES_TERMINER = ("termine l entrainement", "fin de l entrainement", "arrete l entrainement",
                    "fin de la seance", "termine la seance", "arrete la seance", "on arrete l entrainement",
                    "c est tout pour aujourd hui", "entrainement termine", "seance terminee")
PHRASES_ETAT = ("on en est ou", "ou j en suis", "ou en suis je", "combien de series", "il reste combien",
                "combien de temps de repos", "combien de repos", "c est quelle serie")
VERBES_DEMARRER = ("demarre", "demarrer", "demarrez", "commence", "commencer", "commencez", "lance", "lancer",
                   "debute", "debuter", "go", "part", "partir")
MOTS_FIN = ("termine", "terminer", "fin", "arrete", "arreter", "finis")
MOTS_ARRET_EXERCICE = ("repos", "avec", "pendant", "series", "serie", "stp", "svp")


def action_vocale(texte: str) -> str | None:
    norme = normaliser(texte)
    if not norme:
        return None
    for action, phrases in (("terminer", PHRASES_TERMINER), ("etat", PHRASES_ETAT), ("pause", PHRASES_PAUSE),
                            ("reprendre", PHRASES_REPRENDRE), ("serie", PHRASES_SERIE)):
        if correspond(norme, phrases):
            if action == "serie" and any(m in norme.split() for m in NEGATIONS):
                return None  # « pas fini », « presque fini » : surtout ne rien compter
            return action
    return None


def analyser_demarrage(texte: str) -> dict | None:
    """{exercice, series_cibles, repos_s} si la phrase demande de démarrer un entraînement, sinon None.

    « Démarre l'entraînement », « commence une séance de squats, quatre séries, repos une minute »."""
    js = jetons(texte)
    norm = [n for _o, n in js]
    mots = set(norm)
    if "entrainement" not in mots:
        return None  # « séance » seul est trop large (séance photo, séance de méditation)
    if not (set(VERBES_DEMARRER) & mots) or (set(MOTS_FIN) & mots):
        return None
    if len(norm) > 16:
        return None  # une longue phrase qui parle d'entraînement n'est pas une commande
    t = norm
    resultat: dict[str, Any] = {"exercice": None, "series_cibles": None, "repos_s": None}
    # Séries : un nombre suivi de « série(s) ».
    for i in range(len(t)):
        valeur, j = lire_nombre(t, i)
        if valeur is not None and j < len(t) and t[j] in ("serie", "series"):
            resultat["series_cibles"] = int(valeur)
            break
    # Repos : la durée dite après « repos ».
    if "repos" in t:
        resultat["repos_s"] = lire_duree(" ".join(t[t.index("repos") + 1:]))
    # Exercice : les mots qui suivent « entraînement de », « séance de » ou « séries de ».
    for i, mot in enumerate(t):
        if mot in ("entrainement", "seance", "series", "serie") and i + 1 < len(t) and t[i + 1] in ("de", "d", "du", "des"):
            debut = i + 2
            if debut < len(t) and t[debut] == "entrainement":
                continue  # « séance d'entraînement de squats » : l'exercice vient après
            fin = debut
            while fin < len(t) and t[fin] not in MOTS_ARRET_EXERCICE and fin - debut < 6:
                valeur, j = lire_nombre(t, fin)
                if valeur is not None and j < len(t) and t[j] in ("serie", "series", "minute", "minutes", "seconde", "secondes"):
                    break
                fin += 1
            morceaux = [o for o, _n in js[debut:fin]]
            if morceaux and morceaux[0].lower() in ("la", "le", "les", "l"):
                morceaux = morceaux[1:]
            if morceaux:
                resultat["exercice"] = " ".join(morceaux)[:EXERCICE_MAX]
                break
    return resultat


# =============================================================================== service
class ServiceEntrainement:
    def __init__(self, ctx: Any, maintenant: Callable[[], float] | None = None,
                 dormir: Callable[[float], Awaitable[Any]] | None = None):
        self.ctx = ctx
        self.maintenant: Callable[[], float] = maintenant or time.monotonic
        self.dormir: Callable[[float], Awaitable[Any]] = dormir or asyncio.sleep
        self._seance: dict | None = None
        self._tache_repos: asyncio.Task | None = None
        self._fin_repos: float | None = None
        for instruction in SCHEMA.split(";"):
            if instruction.strip():
                ctx.db.execute(instruction)

    # ------------------------------------------------------------------ utilitaires
    @property
    def actif(self) -> bool:
        return self._seance is not None

    def _user(self) -> Any:
        return self.ctx.settings.user

    def _suspendue(self) -> str | None:
        memoire = getattr(self.ctx, "memory", None)
        return getattr(memoire, "suspendue", None) if memoire is not None else None

    async def dire(self, texte: str) -> None:
        tts = getattr(self.ctx, "tts", None)
        if tts is None or not texte or getattr(self._user(), "privacy_mode", False):
            return
        try:
            await asyncio.to_thread(tts.speak, texte, True)
        except Exception as exc:  # pragma: no cover
            log.debug("lecture à voix haute impossible : %s", exc)

    def _repos_restant(self) -> int:
        s = self._seance
        if s is None:
            return 0
        if s["etat"] == "pause":
            return int(s["_repos_gele_s"] or 0)
        if s["etat"] == "repos" and self._fin_repos is not None:
            return max(0, int(math.ceil(self._fin_repos - self.maintenant() - 1e-9)))
        return 0

    def _duree_active(self, s: dict, fin: float | None = None) -> int:
        maintenant = fin if fin is not None else self.maintenant()
        pauses = s["_pauses_s"] + ((maintenant - s["_pause_depuis"]) if s["_pause_depuis"] is not None else 0.0)
        return max(0, int(round(maintenant - s["_debut_mono"] - pauses)))

    def _public(self, s: dict) -> dict:
        return {
            "id": s["id"], "exercice": s["exercice"], "series": s["series"], "series_cibles": s["series_cibles"],
            "repos_s": s["repos_s"], "repos_restant_s": self._repos_restant(), "debut": s["debut"],
            "actif": s["actif"], "etat": s["etat"], "en_pause": s["etat"] == "pause",
            "duree_s": self._duree_active(s), "fin": s.get("fin"), "limite": self.limite(),
            "memoire_suspendue": self._suspendue(), "ecoute_active": self._ecoute_active(),
        }

    def _ecoute_active(self) -> bool:
        voice = getattr(self.ctx, "voice", None)
        return bool(voice is not None and getattr(voice, "state", "off") != "off")

    def limite(self) -> str:
        return LIMITE if self._ecoute_active() else f"{ECOUTE_ARRETEE} {LIMITE}"

    def etat(self) -> dict:
        if self._seance is None:
            return {"actif": False, "limite": self.limite()}
        return self._public(self._seance)

    def _publier(self, seance: dict, annonce: str | None) -> None:
        try:
            self.ctx.hub.publish("entrainement.etat", seance=seance, annonce=annonce)
        except Exception as exc:  # pragma: no cover
            log.debug("événement entrainement.etat non publié : %s", exc)

    def _verifier_confidentiel(self) -> None:
        if getattr(self._user(), "privacy_mode", False):
            if self._seance is not None:
                self.interrompre("mode confidentiel")
            raise RefusEntrainement(409, CONFIDENTIEL, phrase="Le mode confidentiel est actif : l'entraînement est arrêté.")

    async def _conclure(self, phrase: str, parler: bool) -> dict:
        public = self.etat()
        self._publier(public, phrase)
        if parler:
            await self.dire(phrase)
        return {**public, "phrase": phrase}

    # ------------------------------------------------------------------ séance
    async def demarrer(self, exercice: str | None = None, series_cibles: int | None = None,
                       repos_s: int | None = None, parler: bool = True) -> dict:
        """Ouvre une séance. Lève RefusEntrainement 409 (déjà en cours, confidentiel) ou 422."""
        self._verifier_confidentiel()
        if self._seance is not None:
            raise RefusEntrainement(409, DEJA_EN_COURS, phrase=self._phrase_deja_en_cours())
        exercice = " ".join(str(exercice or "").split())[:EXERCICE_MAX] or None
        if series_cibles is not None:
            try:
                series_cibles = int(series_cibles)
            except (TypeError, ValueError):
                raise RefusEntrainement(422, "Nombre de séries illisible.")
            if not 1 <= series_cibles <= SERIES_MAX:
                raise RefusEntrainement(422, f"Le nombre de séries visé va de 1 à {SERIES_MAX}.")
        if repos_s is None:
            repos_s = int(getattr(self._user(), "entrainement_repos_s", 90) or 90)
        try:
            repos_s = int(repos_s)
        except (TypeError, ValueError):
            raise RefusEntrainement(422, "Durée de repos illisible.")
        if not REPOS_MIN_S <= repos_s <= REPOS_MAX_S:
            raise RefusEntrainement(422, f"Le repos dure de {REPOS_MIN_S} secondes à {REPOS_MAX_S // 60} minutes.")
        self._seance = {
            "id": uuid.uuid4().hex, "exercice": exercice, "series": 0, "series_cibles": series_cibles,
            "repos_s": repos_s, "debut": maintenant_iso(), "actif": True, "etat": "effort",
            "_debut_mono": self.maintenant(), "_debut_utc": _iso_utc(datetime.now()), "_pauses_s": 0.0,
            "_pause_depuis": None, "_avant_pause": None, "_repos_gele_s": None,
        }
        phrase = "Entraînement démarré" + (f" : {exercice}" if exercice else "") + "."
        if series_cibles:
            phrase += f" Objectif : {series_cibles} série{'s' if series_cibles > 1 else ''}."
        phrase += f" Repos : {duree_parlee(repos_s)}. Dites « série terminée » après chaque série."
        if getattr(self._user(), "verbosite", "normal") != "concis":
            phrase += " Je ne compte pas les répétitions."
        self.ctx.consent.log("entrainement_debut", detail=self._seance["id"])
        return await self._conclure(phrase, parler)

    def _phrase_deja_en_cours(self) -> str:
        s = self._seance
        if s is None:
            return DEJA_EN_COURS
        nom = f" de {s['exercice']}" if s["exercice"] else ""
        return f"Une séance{nom} est déjà en cours : {s['series']} série{'s' if s['series'] > 1 else ''} faite{'s' if s['series'] > 1 else ''}."

    def _phrase_etat(self) -> str:
        s = self._seance
        assert s is not None
        cible = f" sur {s['series_cibles']}" if s["series_cibles"] else ""
        phrase = f"{s['series']} série{'s' if s['series'] > 1 else ''}{cible} faite{'s' if s['series'] > 1 else ''}."
        if s["etat"] == "repos":
            phrase += f" Repos : {duree_parlee(self._repos_restant())} restantes."
        elif s["etat"] == "pause":
            phrase += " La séance est en pause."
        else:
            phrase += f" Série {s['series'] + 1} en cours."
        return phrase

    async def commande(self, action: str, parler: bool = True) -> dict:
        """Lève RefusEntrainement 409 (aucune séance, confidentiel) ou 422 (action inconnue)."""
        self._verifier_confidentiel()
        action = normaliser(action or "")
        if action not in ACTIONS and action != "etat":
            raise RefusEntrainement(422, f"Action inconnue : « {action} ». Actions : {', '.join(ACTIONS)}.")
        s = self._seance
        if s is None:
            raise RefusEntrainement(409, AUCUNE_SEANCE, phrase="Aucune séance n'est en cours.")
        if action == "etat":
            return await self._conclure(self._phrase_etat(), parler)
        if action == "serie":
            return await self._conclure(self._serie(s), parler)
        if action == "pause":
            return await self._conclure(self._pause(s), parler)
        if action == "reprendre":
            return await self._conclure(self._reprendre(s), parler)
        return await self.terminer(parler)

    def _sortir_de_pause(self, s: dict) -> None:
        if s["_pause_depuis"] is not None:
            s["_pauses_s"] += self.maintenant() - s["_pause_depuis"]
        s["_pause_depuis"] = None
        s["_repos_gele_s"] = None

    def _serie(self, s: dict) -> str:
        self._annuler_repos()
        self._sortir_de_pause(s)
        if s["series"] >= SERIES_MAX:
            s["etat"] = "effort"
            return f"{SERIES_MAX} séries comptées : c'est le maximum pour une séance. Dites « termine l'entraînement »."
        s["series"] += 1
        n, cible = s["series"], s["series_cibles"]
        if cible and n >= cible:
            s["etat"] = "effort"
            if n == cible:
                return f"Série {n} sur {cible} terminée : objectif atteint. Dites « termine l'entraînement » pour le bilan."
            return f"Série {n} terminée, au-delà de l'objectif de {cible}."
        s["etat"] = "repos"
        self._lancer_repos(s, s["repos_s"])
        return f"Série {n}{f' sur {cible}' if cible else ''} terminée. Repos : {duree_parlee(s['repos_s'])}."

    def _pause(self, s: dict) -> str:
        if s["etat"] == "pause":
            return "La séance est déjà en pause. Dites « reprends » pour continuer."
        s["_repos_gele_s"] = self._repos_restant() if s["etat"] == "repos" else None
        self._annuler_repos()
        s["_avant_pause"] = "repos" if s["_repos_gele_s"] else "effort"
        s["etat"] = "pause"
        s["_pause_depuis"] = self.maintenant()
        return "Pause. Dites « reprends » pour continuer."

    def _reprendre(self, s: dict) -> str:
        if s["etat"] != "pause":
            return "La séance n'est pas en pause. " + self._phrase_etat()
        restant = int(s["_repos_gele_s"] or 0)
        avant = s["_avant_pause"]
        self._sortir_de_pause(s)
        if avant == "repos" and restant > 0:
            s["etat"] = "repos"
            self._lancer_repos(s, restant)
            return f"On reprend : repos, {duree_parlee(restant)}."
        s["etat"] = "effort"
        return f"On reprend. Série {s['series'] + 1}."

    async def terminer(self, parler: bool = True) -> dict:
        s = self._seance
        if s is None:
            raise RefusEntrainement(409, AUCUNE_SEANCE, phrase="Aucune séance n'est en cours.")
        final = self._arreter(s)
        enregistree, suspendue = await asyncio.to_thread(self._garder_si_permis, s, final)
        phrase = "Séance terminée" + (f" : {s['exercice']}" if s["exercice"] else "") + ". "
        phrase += f"{s['series']} série{'s' if s['series'] > 1 else ''} en {duree_parlee(final['duree_s'])}."
        if s["series_cibles"]:
            phrase += f" Objectif : {s['series_cibles']}."
        if suspendue:
            phrase += " Séance non enregistrée : la mémoire est suspendue."
        elif s["series"] == 0:
            phrase += " Aucune série comptée : rien n'est enregistré."
        elif not enregistree:
            phrase += " La séance n'a pas pu être enregistrée dans l'historique."
        final["phrase"] = phrase
        self._publier({k: v for k, v in final.items() if k != "phrase"}, phrase)
        if parler:
            await self.dire(phrase)
        return final

    def _arreter(self, s: dict) -> dict:
        """Arrête le chrono et retire la séance. Dans la boucle : le repos est une tâche de cette boucle."""
        fin_mono = self.maintenant()
        self._annuler_repos()
        if s["_pause_depuis"] is not None:
            s["_pauses_s"] += fin_mono - s["_pause_depuis"]
            s["_pause_depuis"] = None
        s["actif"] = False
        s["etat"] = "termine"
        s["fin"] = maintenant_iso()
        s["_repos_gele_s"] = None
        self._seance = None
        final = self._public(s)
        final["duree_s"] = self._duree_active(s, fin_mono)
        return final

    def _garder_si_permis(self, s: dict, final: dict) -> tuple[bool, str | None]:
        """Enregistre la séance (chiffrée) si elle compte au moins une série et que la mémoire écrit."""
        suspendue = self._suspendue()
        enregistree = False
        if s["series"] > 0 and not suspendue:
            try:
                self._enregistrer(s, final)
                enregistree = True
            except Exception as exc:
                log.warning("séance d'entraînement non enregistrée : %s", exc)
        final["enregistree"] = enregistree
        final["memoire_suspendue"] = suspendue
        self.ctx.consent.log("entrainement_fin", detail=f"{s['id']} / {'enregistrée' if enregistree else 'non enregistrée'}")
        return enregistree, suspendue

    def interrompre(self, raison: str) -> None:
        """Arrêt immédiat, sans voix (mode confidentiel, arrêt du service). La séance faite est gardée si permis."""
        s = self._seance
        if s is None:
            return
        log.info("entraînement interrompu : %s", raison)
        final = self._arreter(s)
        self._garder_si_permis(s, final)  # une seule écriture SQLite locale : acceptable hors fil
        self._publier(final, None)

    # ------------------------------------------------------------------ repos
    def _lancer_repos(self, s: dict, duree: int) -> None:
        self._annuler_repos()
        self._fin_repos = self.maintenant() + duree
        self._tache_repos = asyncio.get_running_loop().create_task(self._tourner_repos(s["id"], self._fin_repos))

    def _annuler_repos(self) -> None:
        tache = self._tache_repos
        self._tache_repos = None
        self._fin_repos = None
        if tache is None:
            return
        try:
            courante = asyncio.current_task()
        except RuntimeError:
            courante = None
        if tache is not courante:
            tache.cancel()

    async def _dormir_jusqua(self, moment: float) -> None:
        while (restant := moment - self.maintenant()) > 0:
            await self.dormir(restant)

    def _repos_toujours_la(self, seance_id: str, fin: float) -> bool:
        s = self._seance
        return s is not None and s["id"] == seance_id and s["etat"] == "repos" and self._fin_repos == fin

    async def _tourner_repos(self, seance_id: str, fin: float) -> None:
        if fin - self.maintenant() > ANNONCE_AVANT_FIN_S + 3:
            await self._dormir_jusqua(fin - ANNONCE_AVANT_FIN_S)
            if not self._repos_toujours_la(seance_id, fin):
                return
            self._publier(self.etat(), "10 secondes.")
            await self.dire("10 secondes.")
        await self._dormir_jusqua(fin)
        if not self._repos_toujours_la(seance_id, fin):
            return
        s = self._seance
        assert s is not None
        s["etat"] = "effort"
        self._fin_repos = None
        self._tache_repos = None
        annonce = f"Repos terminé. Série {s['series'] + 1}."
        self._publier(self.etat(), annonce)
        await self.dire(annonce)

    # ------------------------------------------------------------------ historique
    def _retenu_jusqua(self, moment: datetime) -> str | None:
        jours = int(getattr(self._user(), "retention_days", 0) or 0)
        return _iso_utc(moment + timedelta(days=jours)) if jours > 0 else None

    def _enregistrer(self, s: dict, final: dict) -> None:
        donnees = {
            "exercice": s["exercice"], "series": s["series"], "series_cibles": s["series_cibles"],
            "repos_s": s["repos_s"], "debut": s["debut"], "fin": s["fin"], "duree_s": final["duree_s"],
            "pauses_s": int(round(s["_pauses_s"])),
        }
        self.ctx.db.execute(
            "INSERT INTO entrainement_seances(id, debut, donnees_enc, retenu_jusqua) VALUES(?,?,?,?)",
            (s["id"], s["_debut_utc"], self.ctx.crypto.encrypt(json.dumps(donnees, ensure_ascii=False)),
             self._retenu_jusqua(datetime.now())),
        )

    def purger(self) -> int:
        """Retire les séances au-delà de la durée de conservation ACTUELLE (et de celle fixée à l'écriture)."""
        maintenant = datetime.now()
        supprimees = self.ctx.db.execute(
            "DELETE FROM entrainement_seances WHERE retenu_jusqua IS NOT NULL AND retenu_jusqua < ?",
            (_iso_utc(maintenant),)).rowcount or 0
        jours = int(getattr(self._user(), "retention_days", 0) or 0)
        if jours > 0:
            supprimees += self.ctx.db.execute(
                "DELETE FROM entrainement_seances WHERE debut < ?",
                (_iso_utc(maintenant - timedelta(days=jours)),)).rowcount or 0
        return supprimees

    def seances(self, limite: int = HISTORIQUE_MAX) -> list[dict]:
        self.purger()
        lignes = self.ctx.db.query(
            "SELECT * FROM entrainement_seances ORDER BY debut DESC LIMIT ?", (max(1, min(int(limite), HISTORIQUE_MAX)),))
        seances: list[dict] = []
        for ligne in lignes:
            try:
                donnees = json.loads(self.ctx.crypto.decrypt(ligne["donnees_enc"]))
            except Exception:
                log.warning("séance d'entraînement illisible ignorée : %s", ligne.get("id"))
                continue
            seances.append({"id": ligne["id"], **donnees})
        return seances

    def supprimer(self, seance_id: str) -> bool:
        return (self.ctx.db.execute("DELETE FROM entrainement_seances WHERE id=?", (seance_id,)).rowcount or 0) > 0

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str):
        """Commandes de séance (priorité 20). None tout de suite hors séance ou hors commande."""
        if self._seance is None:
            return None
        action = action_vocale(texte)
        if action is None:
            return None
        return self._commande_vocale(action)

    async def _commande_vocale(self, action: str) -> str:
        try:
            resultat = await self.commande(action, parler=False)  # la réponse est dite par l'écoute
        except RefusEntrainement as exc:
            return exc.phrase
        except Exception:
            log.exception("commande vocale de l'entraînement en erreur")
            return "Je n'ai pas réussi à le faire."
        return resultat.get("phrase") or ""

    def interception_demarrage(self, texte: str):
        """« Démarre l'entraînement (de squats) » : permanente (priorité 60)."""
        demande = analyser_demarrage(texte)
        if demande is None:
            return None
        return self._demarrage_vocal(demande)

    async def _demarrage_vocal(self, demande: dict) -> str:
        if self._seance is not None:
            return self._phrase_deja_en_cours()
        repos = demande.get("repos_s")
        if repos is not None and not REPOS_MIN_S <= repos <= REPOS_MAX_S:
            repos = None  # une durée mal entendue ne doit pas bloquer le démarrage : réglage par défaut
        series = demande.get("series_cibles")
        if series is not None and not 1 <= series <= SERIES_MAX:
            series = None
        try:
            resultat = await self.demarrer(demande.get("exercice"), series, repos, parler=False)
        except RefusEntrainement as exc:
            return exc.phrase
        except Exception:
            log.exception("démarrage vocal de l'entraînement en erreur")
            return "Je n'ai pas réussi à démarrer l'entraînement."
        return resultat.get("phrase") or ""

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception("assistants-entrainement", self.interception, priorite=20)
            voice.ajouter_interception("assistants-entrainement-demarrer", self.interception_demarrage, priorite=60)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception("assistants-entrainement")
            voice.retirer_interception("assistants-entrainement-demarrer")
