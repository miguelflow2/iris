"""Activation automatique de l'abonnement : IRIS va chercher elle-même la clé du client.

Parcours visé : le client paie, le serveur de licences VELA reçoit la notification de PayPal, génère sa clé
et la met à disposition. IRIS interroge ce serveur avec le courriel du client et s'active seule, sans qu'il
ait à copier quoi que ce soit. Elle revérifie chaque jour, ce qui gère aussi le renouvellement, l'expiration
et l'annulation.

Si le serveur n'est pas configuré ou injoignable, rien ne casse : IRIS garde le plan déjà activé et
l'utilisateur peut toujours coller une clé à la main.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from .config import Settings
from .events import EventHub
from .plans import PlanService, verify_key

log = logging.getLogger("iris.licence")

TIMEOUT = 8.0


class LicenceSync:
    """Interroge le serveur de licences et applique le résultat au plan local."""

    def __init__(self, settings: Settings, plans: PlanService, hub: EventHub):
        self.settings = settings
        self.plans = plans
        self.hub = hub
        self.last_check: str = ""
        self.last_result: str = ""

    # ------------------------------------------------------------------ état
    @property
    def configured(self) -> bool:
        u = self.settings.user
        return bool((u.licence_server or "").strip() and (u.licence_email or "").strip())

    def status(self) -> dict:
        u = self.settings.user
        return {
            "configured": self.configured,
            "server": u.licence_server,
            "email": u.licence_email,
            "auto": u.licence_auto,
            "last_check": self.last_check,
            "last_result": self.last_result,
        }

    # ------------------------------------------------------------------ synchronisation
    def sync(self, force: bool = False) -> dict:
        """Demande au serveur l'abonnement du client et l'applique. Ne lève jamais : renvoie un compte rendu."""
        u = self.settings.user
        if not self.configured:
            return self._resultat("non configuré", "Renseignez votre courriel d'achat dans Abonnement pour l'activation automatique.")
        if not u.licence_auto and not force:
            return self._resultat("désactivé", "L'activation automatique est désactivée.")
        if u.local_only:
            return self._resultat("mode local", "Mode 100 % local : aucune vérification en ligne.")

        base = u.licence_server.rstrip("/")
        try:
            import httpx

            with httpx.Client(timeout=TIMEOUT) as client:
                # En POST, avec le courriel dans le CORPS. En GET il partait dans l'URL, où il
                # se retrouvait dans les journaux du serveur, ceux de tout intermédiaire, et dans
                # les en-têtes de provenance. Un courriel est une donnée personnelle : elle n'a
                # rien à faire dans une adresse. Le GET reste accepté par les serveurs plus
                # anciens, d'où le repli.
                resp = client.post(f"{base}/api/licence", json={"email": u.licence_email})
                if resp.status_code in (404, 405):
                    resp = client.get(f"{base}/api/licence", params={"email": u.licence_email})
            if resp.status_code == 404:
                return self._resultat("aucun abonnement", "Aucun abonnement actif pour ce courriel.")
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.info("serveur de licences injoignable : %s", exc)
            return self._resultat("injoignable", f"Serveur de licences injoignable ({type(exc).__name__}). Le plan actuel est conservé.")

        cle = (data.get("key") or data.get("cle") or "").strip()
        if not cle:
            return self._resultat("aucun abonnement", data.get("message") or "Aucun abonnement actif pour ce courriel.")

        info = verify_key(cle)
        if not info:
            log.warning("le serveur a renvoyé une clé invalide")
            return self._resultat("clé invalide", "La clé reçue n'est pas valide. Contactez le support.")
        if info.get("expired"):
            self._retrograder(f"Votre abonnement a expiré le {info['expires']}.")
            return self._resultat("expiré", f"Abonnement expiré le {info['expires']}.")

        deja = u.license_key.strip() == cle and self.plans.plan == info["plan"] and u.plan_expires == info["expires"]
        if deja:
            return self._resultat("à jour", f"Plan {info['plan']} actif jusqu'au {info['expires'] or 'sans échéance'}.")

        self.plans.activate(cle)
        message = f"Abonnement {info['plan']} activé automatiquement" + (f", valable jusqu'au {info['expires']}." if info["expires"] else ".")
        log.info("activation automatique : plan %s jusqu'au %s", info["plan"], info["expires"] or "—")
        self.hub.publish("plan.synced", plan=info["plan"], expires=info["expires"], message=message)
        return self._resultat("activé", message)

    # ------------------------------------------------------------------ expiration locale
    def check_expiry(self) -> None:
        """Prévient avant l'échéance et rétrograde proprement une fois la date passée."""
        u = self.settings.user
        if not u.plan_expires or u.plan_demo:
            return
        try:
            fin = date.fromisoformat(u.plan_expires)
        except ValueError:
            return
        restant = (fin - date.today()).days
        if restant < 0:
            self._retrograder(f"Votre abonnement a expiré le {u.plan_expires}. IRIS repasse au plan Gratuit.")
        elif restant in (7, 3, 1):
            self.hub.publish(
                "plan.expiring",
                days=restant,
                expires=u.plan_expires,
                message=f"Votre abonnement se termine dans {restant} jour{'s' if restant > 1 else ''} ({u.plan_expires}).",
            )

    def _retrograder(self, message: str) -> None:
        # On regarde le plan ENREGISTRÉ, pas le plan calculé : ce dernier renvoie déjà « gratuit »
        # dès que la date est passée, ce qui empêcherait le nettoyage des réglages.
        if (self.settings.user.plan or "gratuit") == "gratuit":
            return
        self.settings.update({"plan": "gratuit", "plan_expires": "", "license_key": "", "plan_demo": False})
        self.hub.publish("plan.changed", plan="gratuit", message=message)
        log.info("abonnement expiré : retour au plan Gratuit")

    def _resultat(self, etat: str, message: str) -> dict:
        self.last_check = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.last_result = etat
        return {"state": etat, "message": message, "checked_at": self.last_check, **self.status()}
