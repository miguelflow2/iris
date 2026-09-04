"""Logique métier : que faire d'un événement PayPal, et comment répondre à IRIS.

Tout ce qui décide (activer, prolonger, annuler, envoyer au traitement manuel) est ici, sans
FastAPI, pour pouvoir être testé directement.
"""
from __future__ import annotations

import logging
from datetime import date

from . import cles, montants, paypal
from .base import Base, normaliser
from .config import Config
from .courriel import Facteur

log = logging.getLogger("licences.service")

# Les événements que le service sait traiter. Tout le reste est journalisé puis ignoré.
EVENEMENTS_CONNUS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
}

# Statut de l'abonnement selon l'événement de fin de vie reçu.
STATUTS = {
    "BILLING.SUBSCRIPTION.CANCELLED": (
        "annule",
        "Abonnement annulé chez PayPal ; la clé en cours reste valable jusqu'à son échéance, "
        "mais elle ne sera plus renouvelée.",
    ),
    "BILLING.SUBSCRIPTION.EXPIRED": (
        "expire",
        "Abonnement expiré chez PayPal ; plus aucun renouvellement.",
    ),
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED": (
        "paiement_echoue",
        "Échec du prélèvement PayPal ; l'accès reste ouvert jusqu'à l'échéance déjà payée.",
    ),
}


class Service:
    def __init__(self, cfg: Config, base: Base, facteur: Facteur | None = None):
        self.cfg = cfg
        self.base = base
        self.facteur = facteur or Facteur(cfg)

    # ================================================================== webhooks
    def traiter(self, evenement: dict) -> dict:
        """Traite un événement PayPal **déjà authentifié**. Renvoie un compte rendu.

        Ne lève pas pour un contenu inattendu : un webhook mal formé doit produire un
        enregistrement à traiter à la main, pas une erreur 500 qui ferait relancer PayPal en boucle.
        """
        type_evenement = (evenement or {}).get("event_type") or ""
        evenement_id = (evenement or {}).get("id") or ""
        transaction_id = paypal.identifiant_transaction(evenement)

        # --- idempotence : la réservation est posée AVANT tout crédit --------------
        reservation = self.base.reserver_evenement(evenement_id or None, transaction_id or None, type_evenement)
        if reservation is None:
            return {"resultat": "deja_traite", "type": type_evenement}

        try:
            return self._traiter_reserve(reservation, evenement, type_evenement, transaction_id)
        except Exception:
            # La réservation est retirée : la relance de PayPal pourra retenter le traitement.
            self.base.liberer_evenement(reservation)
            raise

    def _traiter_reserve(self, reservation: int, evenement: dict, type_evenement: str,
                         transaction_id: str) -> dict:
        courriel = paypal.courriel_du_payeur(evenement)
        montant, devise = paypal.montant_de(evenement)

        if type_evenement not in EVENEMENTS_CONNUS:
            self.base.conclure_evenement(
                reservation, courriel=courriel or None, montant=montant, devise=devise,
                resultat="ignore", detail="Type d'événement non traité par ce service.",
            )
            return {"resultat": "ignore", "type": type_evenement}

        if type_evenement in ("PAYMENT.CAPTURE.COMPLETED", "BILLING.SUBSCRIPTION.ACTIVATED"):
            return self._crediter(reservation, evenement, type_evenement, transaction_id,
                                  courriel, montant, devise)

        statut, note = STATUTS[type_evenement]
        return self._changer_statut(reservation, evenement, type_evenement, courriel, statut, note)

    # ------------------------------------------------------------------ paiement reçu
    def _crediter(self, reservation, evenement, type_evenement, transaction_id,
                  courriel, montant, devise) -> dict:
        # Le courriel est indispensable : sans lui, on ne sait pas qui créditer.
        if not courriel:
            return self._vers_manuel(reservation, type_evenement, transaction_id, courriel, montant, devise,
                                     "Paiement reçu sans adresse courriel exploitable.")

        tarif = montants.reconnaitre(
            montant, devise,
            devises_acceptees=self.cfg.devises_acceptees,
            tolerance=self.cfg.tolerance_montant,
        )
        if tarif is None:
            return self._vers_manuel(reservation, type_evenement, transaction_id, courriel, montant, devise,
                                     f"Montant non reconnu : {montant} {devise}. Aucun plan activé.")

        existant = self.base.abonnement(courriel)
        expiration_actuelle = existant["expire_le"] if existant else None
        # Reconduction du même plan : les mois se cumulent. Changement de plan : on repart d'aujourd'hui.
        if existant and existant["plan"] != tarif.plan:
            expiration_actuelle = None
        expiration = cles.prolonger(expiration_actuelle, tarif.mois)

        try:
            cle, note = cles.emettre(tarif.plan, expiration, courriel, self.cfg.secret_hmac)
        except ValueError as erreur:
            return self._vers_manuel(reservation, type_evenement, transaction_id, courriel,
                                     montant, devise, str(erreur))

        ressource = (evenement or {}).get("resource") or {}
        abonnement_paypal = ressource.get("id") if type_evenement == "BILLING.SUBSCRIPTION.ACTIVATED" else None

        self.base.enregistrer_abonnement(
            courriel=courriel, plan=tarif.plan, expire_le=expiration, statut="actif",
            abonnement_paypal=abonnement_paypal, derniere_cle=cle, note=note,
        )
        resultat = "prolonge" if existant else "active"
        self.base.conclure_evenement(
            reservation, courriel=courriel, montant=montant, devise=devise, plan=tarif.plan,
            resultat=resultat,
            detail=f"{tarif.libelle} ; valide jusqu'au {expiration}." + (f" {note}" if note else ""),
        )
        envoi = self.facteur.envoyer_cle(courriel, tarif.plan, expiration, cle, tarif.libelle)
        log.info("Abonnement %s pour %s jusqu'au %s (courriel : %s).",
                 tarif.plan, courriel, expiration, envoi.get("mode"))
        return {"resultat": resultat, "courriel": courriel, "plan": tarif.plan,
                "expire_le": expiration, "cle": cle, "courriel_envoi": envoi.get("mode")}

    # ------------------------------------------------------------------ annulation / expiration / échec
    def _changer_statut(self, reservation, evenement, type_evenement, courriel, statut, note) -> dict:
        ressource = (evenement or {}).get("resource") or {}
        abonnement_paypal = str(ressource.get("id") or "")

        ligne = self.base.abonnement(courriel) if courriel else None
        if ligne is None:
            ligne = self.base.abonnement_par_paypal(abonnement_paypal)
        if ligne is None:
            self.base.conclure_evenement(
                reservation, courriel=courriel or None, resultat="ignore",
                detail="Aucun abonnement connu pour cet événement.",
            )
            return {"resultat": "inconnu", "type": type_evenement}

        self.base.changer_statut(ligne["courriel"], statut, note)
        self.base.conclure_evenement(
            reservation, courriel=ligne["courriel"], plan=ligne["plan"], resultat=statut, detail=note,
        )
        log.info("Statut de %s : %s.", ligne["courriel"], statut)
        return {"resultat": statut, "courriel": ligne["courriel"], "plan": ligne["plan"]}

    # ------------------------------------------------------------------ traitement manuel
    def _vers_manuel(self, reservation, type_evenement, transaction_id, courriel, montant, devise, raison) -> dict:
        identifiant = self.base.ajouter_manuel(courriel, montant, devise, transaction_id or None, raison)
        self.base.conclure_evenement(
            reservation, courriel=courriel or None, montant=montant, devise=devise,
            resultat="manuel", detail=raison,
        )
        log.warning("À traiter manuellement (#%s) : %s", identifiant, raison)
        self.facteur.alerter(
            "Paiement à traiter manuellement",
            "Un paiement n'a pas pu être transformé en abonnement.\n\n"
            f"Raison : {raison}\n"
            f"Courriel : {courriel or '(inconnu)'}\n"
            f"Montant : {montant} {devise}\n"
            f"Transaction : {transaction_id or '(inconnue)'}\n"
            f"Événement : {type_evenement}\n\n"
            "Ouvrez la page d'administration pour émettre une clé à la main.\n",
        )
        return {"resultat": "manuel", "id": identifiant, "raison": raison}

    # ================================================================== interrogation par IRIS
    def licence(self, courriel: str, aujourdhui: date | None = None) -> dict:
        """Réponse à IRIS. Volontairement pauvre : rien ne permet de distinguer
        « ce courriel est inconnu » de « ce courriel n'a pas d'abonnement actif ».
        """
        aujourdhui = aujourdhui or date.today()
        neutre = {"actif": False, "plan": "gratuit", "expire_le": None, "cle": None}

        ligne = self.base.abonnement(courriel)
        if ligne is None or ligne["statut"] == "expire":
            return neutre
        try:
            if date.fromisoformat(ligne["expire_le"]) < aujourdhui:
                return neutre
        except (ValueError, TypeError):
            return neutre

        cle = ligne["derniere_cle"]
        if not cle or not cles.cle_utilisable(cle, self.cfg.secret_hmac):
            # Clé absente, ou émise avec un autre secret (rotation) : on la réémet.
            try:
                cle, _ = cles.emettre(ligne["plan"], ligne["expire_le"], ligne["courriel"], self.cfg.secret_hmac)
                self.base.executer("UPDATE abonnements SET derniere_cle=? WHERE courriel=?",
                                   (cle, ligne["courriel"]))
            except ValueError:
                return neutre
        return {"actif": True, "plan": ligne["plan"], "expire_le": ligne["expire_le"], "cle": cle}

    def verifier(self, cle: str) -> dict:
        """Valide une clé sans toucher à la base : la vérification est purement cryptographique."""
        info = cles.verifier_cle(cle, self.cfg.secret_hmac)
        if info is None:
            return {"valide": False, "raison": "Clé invalide ou signature incorrecte."}
        if info.get("expiree"):
            return {"valide": False, "raison": f"Clé expirée le {info['expiration']}.",
                    "plan": info["plan"], "expire_le": info["expiration"]}
        return {"valide": True, "plan": info["plan"], "expire_le": info["expiration"]}

    # ================================================================== administration
    def emettre_manuellement(self, courriel: str, plan: str, mois: int = 1,
                             raison: str = "paiement hors PayPal") -> dict:
        """Filet de sécurité : virement, comptant, geste commercial, renvoi d'une clé perdue."""
        courriel = normaliser(courriel)
        if not courriel or "@" not in courriel:
            raise ValueError("Courriel invalide.")
        if plan not in cles.PLANS:
            raise ValueError("Plan inconnu.")
        existant = self.base.abonnement(courriel)
        depart = existant["expire_le"] if existant and existant["plan"] == plan else None
        expiration = cles.prolonger(depart, mois)
        cle, note = cles.emettre(plan, expiration, courriel, self.cfg.secret_hmac)
        self.base.enregistrer_abonnement(
            courriel=courriel, plan=plan, expire_le=expiration, statut="actif",
            derniere_cle=cle, note=(note or raison),
        )
        reservation = self.base.reserver_evenement(None, None, "MANUEL")
        if reservation:
            self.base.conclure_evenement(
                reservation, courriel=courriel, plan=plan, resultat="active",
                detail=f"Clé émise à la main ({raison}) jusqu'au {expiration}.",
            )
        envoi = self.facteur.envoyer_cle(courriel, plan, expiration, cle)
        return {"courriel": courriel, "plan": plan, "expire_le": expiration, "cle": cle,
                "courriel_envoi": envoi.get("mode")}
