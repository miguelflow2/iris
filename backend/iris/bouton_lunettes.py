"""Bouton des lunettes -> « décris ce qu'il y a devant moi », sans toucher au téléphone ni à l'ordinateur.

Pour une personne aveugle, sortir un téléphone pour demander une description est un geste de trop.
Les lunettes ont des boutons physiques, mais leur fabricant ne documente pas ce qu'ils émettent. On
ne devine donc rien : IRIS APPREND le bouton en regardant passer les paquets Bluetooth basse énergie
(événement glasses.packet publié par glasses.py) :

1. référence (2 s) : l'utilisateur ne touche à rien ; tout ce qui passe est du bruit de fond
   (batterie, battements réguliers) ;
2. appui (6 s par défaut) : l'utilisateur appuie sur le bouton ; on retient la signature
   « uuid:hex » la plus fréquente qui n'est PAS apparue pendant la référence.

Ce qui est ignoré : les trames de batterie (lunettes_trames.batterie) et les paquets d'un seul octet
qui se répètent (trois fois ou plus pendant l'appui : un battement, pas un bouton).

L'échec est dit tel quel. Beaucoup de lunettes traitent leurs boutons en interne (volume, lecture)
sans rien envoyer sur le canal basse énergie : dans ce cas aucune application ne peut les utiliser,
et IRIS le dit au lieu de prétendre le contraire. De même, si les lunettes ajoutent un compteur à
chaque appui, la signature exacte ne se répétera jamais : l'apprentissage réussira mais le bouton ne
déclenchera rien, et il faudra le dire aussi (voir LIMITES).

Service exposé sous ctx.bouton (voir routes_alertes.py).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections import Counter
from typing import Any

from . import lunettes_trames

log = logging.getLogger("iris.bouton")

# Horloge de l'anti-rebond, isolée pour que les tests la remplacent sans figer celle d'asyncio.
_horloge = time.monotonic

REFERENCE_S = 2.0
ANTI_REBOND_S = 3.0
APPUI_MIN_S = 2.0
APPUI_MAX_S = 20.0

RIEN_DE_NOUVEAU = (
    "Rien de nouveau n'est arrivé pendant l'appui : vos lunettes n'émettent rien sur le canal Bluetooth "
    "basse énergie pour ce bouton. IRIS ne peut donc pas l'utiliser."
)
NON_CONNECTEES = (
    "Les lunettes ne sont pas connectées en Bluetooth basse énergie : connectez-les d'abord, puis recommencez."
)

LIMITES = [
    "Le fabricant ne documente pas les boutons : IRIS apprend ce que le bouton envoie, sans garantie qu'il "
    "envoie quelque chose.",
    "Si les lunettes changent leur message à chaque appui (compteur), le bouton appris ne déclenchera rien : "
    "recommencez l'apprentissage ou utilisez la voix.",
    "Une photo des lunettes prend quelques secondes ; la description arrive ensuite, jamais en temps réel.",
]


def signature(paquet: dict) -> str:
    return f"{str(paquet.get('uuid', '')).strip().lower()}:{str(paquet.get('hex', '')).strip().lower()}"


def _est_batterie(hexa: str) -> bool:
    try:
        return lunettes_trames.batterie(bytes.fromhex(hexa)) is not None
    except ValueError:
        return False


def choisir_signature(reference: Counter, appui: Counter) -> str | None:
    """La signature du bouton : la plus fréquente pendant l'appui, absente de la référence, ni batterie
    ni battement d'un octet. None s'il n'y a rien de tel. `appui` garde l'ordre d'arrivée (Counter)."""
    candidats = []
    for ordre, (sig, compte) in enumerate(appui.items()):
        if sig in reference:
            continue
        hexa = sig.rsplit(":", 1)[-1]
        if _est_batterie(hexa):
            continue
        if len(hexa) <= 2 and compte >= 3:
            continue
        candidats.append((-compte, ordre, sig))
    if not candidats:
        return None
    return min(candidats)[2]


class ServiceBouton:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.loop: asyncio.AbstractEventLoop | None = None
        self._verrou = threading.Lock()
        self._apprentissage: dict | None = None
        self._dernier_declenchement = -1e9
        self._taches: set = set()
        self.derniere_action: dict | None = None
        self._file_voix: "queue.Queue[str]" = queue.Queue()
        self._verrou_voix = threading.Lock()
        self._fil_voix: threading.Thread | None = None

    # ------------------------------------------------------------------ état
    def _connectees(self) -> bool:
        lunettes = getattr(self.ctx, "glasses", None)
        try:
            return bool(lunettes is not None and lunettes.connected)
        except Exception:
            return False

    def etat(self) -> dict:
        u = self.ctx.settings.user
        return {
            "signature": u.bouton_description_signature or None,
            "mode": u.bouton_description_mode,
            "apprentissage": self._apprentissage is not None,
            "phase": (self._apprentissage or {}).get("phase"),
            "lunettes_connectees": self._connectees(),
            "description_disponible": getattr(self.ctx, "accessibilite", None) is not None,
            "derniere_action": self.derniere_action,
            "limites": LIMITES,
        }

    # ------------------------------------------------------------------ paquets
    def recevoir_paquet(self, paquet: dict) -> None:
        """Appelé pour chaque événement glasses.packet. Rapide : ne bloque jamais la boucle."""
        sig = signature(paquet)
        with self._verrou:
            apprentissage = self._apprentissage
            if apprentissage is not None:
                apprentissage[apprentissage["phase"]][sig] += 1
                return
        voulue = (self.ctx.settings.user.bouton_description_signature or "").strip().lower()
        if not voulue or sig != voulue:
            return
        maintenant = _horloge()
        if maintenant - self._dernier_declenchement < ANTI_REBOND_S:
            return  # un appui envoie parfois plusieurs paquets identiques : une seule description
        self._dernier_declenchement = maintenant
        self._declencher(sig)

    def _publier(self, action: str, sig: str, raison: str | None = None) -> None:
        self.derniere_action = {"action": action, "raison": raison, "ts": time.time()}
        donnees = {"signature": sig, "action": action}
        if raison:
            donnees["raison"] = raison
        self.ctx.hub.publish("bouton.lunettes", **donnees)

    def _dire(self, texte: str) -> None:
        """Dit une phrase SANS bloquer l'appelant. _dire est appelé depuis la boucle asyncio (apprentissage,
        paquets des lunettes) ; or tts.speak peut attendre jusqu'à 15 s le premier démarrage de la voix
        Windows et fait du travail synchrone (conversion des nombres, compteur en base). Un seul fil de
        parole, dans l'ordre d'arrivée : « Appuyez maintenant… » passe avant « Bouton appris. »."""
        tts = getattr(self.ctx, "tts", None)
        if tts is None or self.ctx.settings.user.privacy_mode or not texte:
            return
        self._file_voix.put(texte)
        with self._verrou_voix:
            if self._fil_voix is None or not self._fil_voix.is_alive():
                self._fil_voix = threading.Thread(target=self._parler_en_fond, name="iris-bouton-voix", daemon=True)
                self._fil_voix.start()

    def _parler_en_fond(self) -> None:
        while True:
            try:
                texte = self._file_voix.get(timeout=5.0)
            except queue.Empty:
                with self._verrou_voix:
                    # Vérifié sous verrou : une phrase déposée pendant qu'on s'apprêtait à partir n'est pas perdue.
                    if self._file_voix.empty():
                        self._fil_voix = None
                        return
                continue
            tts = getattr(self.ctx, "tts", None)
            try:
                if tts is not None:
                    tts.speak(texte, force=True)
            except Exception as exc:
                log.debug("phrase du bouton non dite : %s", exc)

    def _declencher(self, sig: str) -> None:
        u = self.ctx.settings.user
        if u.privacy_mode:
            self._publier("refuse", sig, "Mode confidentiel actif : aucune photo n'est prise.")
            return
        service = getattr(self.ctx, "accessibilite", None)
        if service is None:
            raison = "La description visuelle n'est pas disponible sur cet ordinateur."
            self._publier("indisponible", sig, raison)
            self._dire("Bouton reçu, mais " + raison[0].lower() + raison[1:])
            return
        self._publier("decrire", sig)
        coro = self._decrire(service, u.bouton_description_mode or "scene", sig)
        try:
            boucle = asyncio.get_running_loop()
        except RuntimeError:
            boucle = None
        if boucle is not None:
            tache = boucle.create_task(coro)
            self._taches.add(tache)
            tache.add_done_callback(self._taches.discard)
        elif self.loop is not None and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            coro.close()
            self._publier("erreur", sig, "Le service n'est pas encore prêt.")

    async def _decrire(self, service: Any, mode: str, sig: str) -> None:
        try:
            await service.decrire(mode=mode, source="lunettes", parler=True)
        except Exception as exc:
            raison = self._raison(exc)
            log.info("description par le bouton refusée : %s", raison)
            self._publier("erreur", sig, raison)
            self._dire(getattr(exc, "phrase", None) or raison)

    @staticmethod
    def _raison(exc: Exception) -> str:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict):
            if detail.get("code") == "consentement":
                libelle = detail.get("label") or detail.get("data_type") or "images"
                return f"Je ne peux pas décrire : le consentement « {libelle} » n'est pas accordé. Ouvrez Confidentialité dans IRIS."
            return str(detail.get("message") or detail)
        return str(getattr(exc, "message", None) or detail or exc) or "La description a échoué."

    # ------------------------------------------------------------------ apprentissage
    async def apprendre(self, secondes: float = 6.0, reference_s: float | None = None) -> dict:
        secondes = float(min(APPUI_MAX_S, max(APPUI_MIN_S, secondes)))
        reference_s = REFERENCE_S if reference_s is None else float(reference_s)
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        if self.ctx.settings.user.privacy_mode:
            return self._fin_echec("Mode confidentiel actif : l'apprentissage du bouton attend sa désactivation.")
        if not self._connectees():
            return self._fin_echec(NON_CONNECTEES)
        with self._verrou:
            if self._apprentissage is not None:
                return {"etat": "echec", "signature": None, "raison": "Un apprentissage est déjà en cours."}
            self._apprentissage = {"phase": "reference", "reference": Counter(), "appui": Counter()}
        try:
            self.ctx.hub.publish("bouton.apprentissage", etat="reference", secondes=reference_s)
            await asyncio.sleep(reference_s)
            with self._verrou:
                self._apprentissage["phase"] = "appui"
            self.ctx.hub.publish("bouton.apprentissage", etat="appuyez", secondes=secondes)
            self._dire("Appuyez maintenant sur le bouton des lunettes, deux ou trois fois.")
            await asyncio.sleep(secondes)
            with self._verrou:
                reference = self._apprentissage["reference"]
                appui = self._apprentissage["appui"]
        finally:
            with self._verrou:
                self._apprentissage = None
        sig = choisir_signature(reference, appui)
        if sig is None:
            return self._fin_echec(RIEN_DE_NOUVEAU, sum(reference.values()), sum(appui.values()))
        user = self.ctx.settings.update({"bouton_description_signature": sig})
        self.ctx.hub.publish("settings.updated", settings=user.model_dump())
        self.ctx.hub.publish("bouton.apprentissage", etat="appris", signature=sig)
        self._dire("Bouton appris.")
        log.info("bouton des lunettes appris : %s", sig)
        return {"etat": "appris", "signature": sig, "raison": None,
                "paquets_reference": sum(reference.values()), "paquets_appui": sum(appui.values())}

    def _fin_echec(self, raison: str, n_reference: int = 0, n_appui: int = 0) -> dict:
        self.ctx.hub.publish("bouton.apprentissage", etat="echec", raison=raison)
        self._dire(raison)
        return {"etat": "echec", "signature": None, "raison": raison,
                "paquets_reference": n_reference, "paquets_appui": n_appui}

    def oublier(self) -> dict:
        user = self.ctx.settings.update({"bouton_description_signature": ""})
        self.ctx.hub.publish("settings.updated", settings=user.model_dump())
        self.ctx.hub.publish("bouton.apprentissage", etat="oublie")
        return {"ok": True}
