"""Envoi des courriels (clé d'abonnement, alertes).

Si SMTP est configuré, le message part vraiment. Sinon il est écrit dans `sortie/` et journalisé :
le service ne plante jamais parce que le courriel ne peut pas partir — un abonnement payé doit
être créé même si l'envoi échoue, quitte à ce que Miguel renvoie la clé depuis la page d'administration.
"""
from __future__ import annotations

import logging
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .base import maintenant
from .cles import ETIQUETTES
from .config import Config

log = logging.getLogger("licences.courriel")

_INTERDIT = re.compile(r"[^A-Za-z0-9._@-]")


class Facteur:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ------------------------------------------------------------------ envoi générique
    def envoyer(self, destinataire: str, sujet: str, corps: str) -> dict:
        """Envoie (ou dépose) un courriel. Renvoie {mode, chemin?, erreur?} — n'échoue jamais."""
        message = EmailMessage()
        message["From"] = self.cfg.courriel_expediteur
        message["To"] = destinataire
        message["Subject"] = sujet
        message.set_content(corps)

        if not self.cfg.smtp_configure:
            return self._deposer(destinataire, sujet, message)

        try:
            if self.cfg.smtp_port == 465:
                serveur = smtplib.SMTP_SSL(self.cfg.smtp_hote, self.cfg.smtp_port, timeout=20)
            else:
                serveur = smtplib.SMTP(self.cfg.smtp_hote, self.cfg.smtp_port, timeout=20)
            with serveur:
                if self.cfg.smtp_tls and self.cfg.smtp_port != 465:
                    serveur.starttls()
                if self.cfg.smtp_utilisateur:
                    # Le mot de passe n'est jamais journalisé.
                    serveur.login(self.cfg.smtp_utilisateur, self.cfg.smtp_motdepasse)
                serveur.send_message(message)
            log.info("Courriel envoyé à %s (%s).", destinataire, sujet)
            return {"mode": "smtp"}
        except Exception as erreur:
            log.error("Échec de l'envoi SMTP à %s : %s — le message est déposé dans %s.",
                      destinataire, erreur, self.cfg.dossier_sortie)
            depot = self._deposer(destinataire, sujet, message)
            depot["erreur"] = str(erreur)
            return depot

    def _deposer(self, destinataire: str, sujet: str, message: EmailMessage) -> dict:
        dossier = Path(self.cfg.dossier_sortie)
        dossier.mkdir(parents=True, exist_ok=True)
        horodatage = maintenant().replace(":", "-")
        nom = f"{horodatage}-{_INTERDIT.sub('_', destinataire)[:60]}.eml"
        chemin = dossier / nom
        chemin.write_text(message.as_string(), encoding="utf-8")
        log.info("Courriel déposé dans %s (SMTP non configuré ou en échec) : %s", chemin, sujet)
        return {"mode": "fichier", "chemin": str(chemin)}

    # ------------------------------------------------------------------ messages métier
    def envoyer_cle(self, destinataire: str, plan: str, expiration: str, cle: str, libelle_tarif: str = "") -> dict:
        etiquette = ETIQUETTES.get(plan, plan)
        detail = f"\nOffre : {libelle_tarif}" if libelle_tarif else ""
        corps = f"""Bonjour,

Merci pour votre paiement. Votre abonnement IRIS est actif.

Plan : {etiquette}{detail}
Valide jusqu'au : {expiration}

Votre clé d'abonnement :

{cle}

Pour l'activer : ouvrez IRIS, allez dans « Abonnement », collez la clé et validez.
IRIS peut aussi la récupérer toute seule à partir de votre adresse courriel.

Une question ? Répondez à ce message ou écrivez à {self.cfg.courriel_support}.

— VELA
"""
        return self.envoyer(destinataire, f"Votre clé d'abonnement IRIS ({etiquette})", corps)

    def alerter(self, sujet: str, corps: str) -> dict:
        """Alerte l'exploitant (paiement non reconnu, clé impossible à émettre…)."""
        destinataire = self.cfg.courriel_alerte or self.cfg.courriel_support
        return self.envoyer(destinataire, f"[IRIS licences] {sujet}", corps)
