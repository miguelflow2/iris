"""Configuration du serveur de licences.

Règle absolue : aucun secret en dur. Tout vient de variables d'environnement (voir .env.exemple).
Le seul « secret » qui a une valeur par défaut est le secret HMAC des clés, et uniquement parce que
l'application IRIS l'a aujourd'hui en dur dans backend/iris/plans.py : si le serveur en utilisait un
autre, les clés qu'il émet ne seraient reconnues par aucune installation existante. Voir le README,
section « Le secret HMAC », pour la transition vers une variable d'environnement des deux côtés.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("licences.config")

RACINE = Path(__file__).resolve().parent.parent  # dossier server/

# Valeur historique du secret, copiée de backend/iris/plans.py (LICENSE_SECRET).
# Elle sert de repli pour ne pas invalider les clés déjà distribuées à la main.
SECRET_HISTORIQUE = b"VELA-IRIS-2026-license-v1"

# Points d'entrée de l'API PayPal.
PAYPAL_API = {
    "live": "https://api-m.paypal.com",
    "sandbox": "https://api-m.sandbox.paypal.com",
}


def _charger_env(fichier: Path) -> None:
    """Charge un fichier .env très simple (CLE=valeur) sans écraser l'environnement réel."""
    if not fichier.is_file():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle, valeur = cle.strip(), valeur.strip().strip('"').strip("'")
        os.environ.setdefault(cle, valeur)


def _bool(nom: str, defaut: bool = False) -> bool:
    valeur = (os.environ.get(nom) or "").strip().lower()
    if not valeur:
        return defaut
    return valeur in {"1", "oui", "true", "vrai", "yes", "on"}


def _int(nom: str, defaut: int) -> int:
    try:
        return int((os.environ.get(nom) or "").strip() or defaut)
    except ValueError:
        return defaut


def _float(nom: str, defaut: float) -> float:
    try:
        return float((os.environ.get(nom) or "").strip() or defaut)
    except ValueError:
        return defaut


class ConfigurationInvalide(RuntimeError):
    """Le service refuse de démarrer : une combinaison de réglages est dangereuse."""


@dataclass
class Config:
    # --- environnement --------------------------------------------------
    environnement: str = "developpement"   # « production » verrouille les modes de test
    mode_dev_sans_verification: bool = False  # saute la vérification de signature PayPal — JAMAIS en production

    # --- PayPal ---------------------------------------------------------
    paypal_client_id: str = ""
    paypal_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_environnement: str = "sandbox"   # « sandbox » ou « live »

    # --- Stripe ---------------------------------------------------------
    # S'ajoute à PayPal, ne le remplace pas. Tous ces champs viennent de variables d'environnement.
    stripe_secret_key: str = ""             # STRIPE_SECRET_KEY  (sk_... — SECRET, jamais journalisé)
    stripe_webhook_secret: str = ""         # STRIPE_WEBHOOK_SECRET (whsec_... — SECRET, vérif signature)
    stripe_publishable_key: str = ""        # STRIPE_PUBLISHABLE_KEY (pk_... — publique, sans risque)
    stripe_prix_pro: str = ""               # STRIPE_PRIX_PRO        (price_... du plan Pro)
    stripe_prix_premium: str = ""           # STRIPE_PRIX_PREMIUM    (price_... du plan Premium)
    stripe_prix_entreprise: str = ""        # STRIPE_PRIX_ENTREPRISE (price_... du plan Entreprise)

    # --- clés d'abonnement ---------------------------------------------
    secret_hmac: bytes = SECRET_HISTORIQUE
    secret_hmac_fourni: bool = False       # vrai si IRIS_LICENSE_SECRET était défini

    # --- base et fichiers ----------------------------------------------
    base_donnees: Path = field(default_factory=lambda: RACINE / "licences.db")
    dossier_sortie: Path = field(default_factory=lambda: RACINE / "sortie")

    # --- courriel -------------------------------------------------------
    smtp_hote: str = ""
    smtp_port: int = 587
    smtp_utilisateur: str = ""
    smtp_motdepasse: str = ""
    smtp_tls: bool = True
    courriel_expediteur: str = "VELA <miguelfreddy65@gmail.com>"
    courriel_support: str = "miguelfreddy65@gmail.com"
    courriel_alerte: str = ""              # destinataire des alertes « à traiter manuellement »

    # --- administration -------------------------------------------------
    jeton_admin: str = ""                  # vide = page d'administration désactivée

    # --- limitation de débit -------------------------------------------
    limite_requetes: int = 20              # requêtes autorisées…
    limite_fenetre: int = 60               # …par fenêtre de N secondes, par adresse IP
    limite_licence_requetes: int = 10      # plus strict sur /api/licence (anti-énumération)

    # --- montants -------------------------------------------------------
    devises_acceptees: tuple[str, ...] = ("CAD",)
    tolerance_montant: float = 0.05        # écart accepté, en dollars

    @property
    def smtp_configure(self) -> bool:
        return bool(self.smtp_hote)

    @property
    def paypal_configure(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_secret and self.paypal_webhook_id)

    @property
    def base_paypal(self) -> str:
        return PAYPAL_API.get(self.paypal_environnement, PAYPAL_API["sandbox"])

    @property
    def stripe_configure(self) -> bool:
        """Stripe est utilisable pour recevoir des webhooks : clé secrète + secret de webhook."""
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def stripe_amorce(self) -> bool:
        """Au moins une variable Stripe est définie : l'intention d'utiliser Stripe est là."""
        return any((
            self.stripe_secret_key, self.stripe_webhook_secret, self.stripe_publishable_key,
            self.stripe_prix_pro, self.stripe_prix_premium, self.stripe_prix_entreprise,
        ))

    @property
    def correspondance_prix_stripe(self) -> dict[str, str]:
        """Table {identifiant de prix Stripe -> plan interne}, sans les prix non configurés."""
        table: dict[str, str] = {}
        for prix, plan in (
            (self.stripe_prix_pro, "pro"),
            (self.stripe_prix_premium, "premium"),
            (self.stripe_prix_entreprise, "entreprise"),
        ):
            if prix:
                table[prix] = plan
        return table

    def prix_stripe_du_plan(self, plan: str) -> str:
        """Identifiant de prix Stripe d'un plan (pour créer une session Checkout), ou chaîne vide."""
        return {
            "pro": self.stripe_prix_pro,
            "premium": self.stripe_prix_premium,
            "entreprise": self.stripe_prix_entreprise,
        }.get(plan, "")

    @property
    def production(self) -> bool:
        return self.environnement.lower().startswith("prod")


def charger(fichier_env: Path | None = None) -> Config:
    """Construit la configuration à partir de l'environnement (+ un .env facultatif)."""
    _charger_env(fichier_env or (RACINE / ".env"))

    secret_env = (os.environ.get("IRIS_LICENSE_SECRET") or "").strip()
    devises = tuple(
        d.strip().upper()
        for d in (os.environ.get("IRIS_DEVISES") or "CAD").split(",")
        if d.strip()
    ) or ("CAD",)

    cfg = Config(
        environnement=(os.environ.get("IRIS_ENV") or "developpement").strip(),
        mode_dev_sans_verification=_bool("IRIS_WEBHOOK_SANS_VERIFICATION", False),
        paypal_client_id=(os.environ.get("PAYPAL_CLIENT_ID") or "").strip(),
        paypal_secret=(os.environ.get("PAYPAL_SECRET") or "").strip(),
        paypal_webhook_id=(os.environ.get("PAYPAL_WEBHOOK_ID") or "").strip(),
        paypal_environnement=(os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower(),
        stripe_secret_key=(os.environ.get("STRIPE_SECRET_KEY") or "").strip(),
        stripe_webhook_secret=(os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip(),
        stripe_publishable_key=(os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip(),
        stripe_prix_pro=(os.environ.get("STRIPE_PRIX_PRO") or "").strip(),
        stripe_prix_premium=(os.environ.get("STRIPE_PRIX_PREMIUM") or "").strip(),
        stripe_prix_entreprise=(os.environ.get("STRIPE_PRIX_ENTREPRISE") or "").strip(),
        secret_hmac=secret_env.encode() if secret_env else SECRET_HISTORIQUE,
        secret_hmac_fourni=bool(secret_env),
        base_donnees=Path(os.environ.get("IRIS_BASE") or (RACINE / "licences.db")),
        dossier_sortie=Path(os.environ.get("IRIS_SORTIE") or (RACINE / "sortie")),
        smtp_hote=(os.environ.get("IRIS_SMTP_HOTE") or "").strip(),
        smtp_port=_int("IRIS_SMTP_PORT", 587),
        smtp_utilisateur=(os.environ.get("IRIS_SMTP_UTILISATEUR") or "").strip(),
        smtp_motdepasse=os.environ.get("IRIS_SMTP_MOTDEPASSE") or "",
        smtp_tls=_bool("IRIS_SMTP_TLS", True),
        courriel_expediteur=(os.environ.get("IRIS_COURRIEL_EXPEDITEUR") or "VELA <miguelfreddy65@gmail.com>").strip(),
        courriel_support=(os.environ.get("IRIS_COURRIEL_SUPPORT") or "miguelfreddy65@gmail.com").strip(),
        courriel_alerte=(os.environ.get("IRIS_COURRIEL_ALERTE") or "").strip(),
        jeton_admin=os.environ.get("IRIS_JETON_ADMIN") or "",
        limite_requetes=_int("IRIS_LIMITE_REQUETES", 20),
        limite_fenetre=_int("IRIS_LIMITE_FENETRE", 60),
        limite_licence_requetes=_int("IRIS_LIMITE_LICENCE", 10),
        devises_acceptees=devises,
        tolerance_montant=_float("IRIS_TOLERANCE_MONTANT", 0.05),
    )
    valider(cfg)
    return cfg


def valider(cfg: Config) -> None:
    """Refuse les combinaisons dangereuses, et avertit sur les manques non bloquants."""
    # Le garde-fou principal : impossible de sauter la vérification de signature en production.
    if cfg.production and cfg.mode_dev_sans_verification:
        raise ConfigurationInvalide(
            "IRIS_WEBHOOK_SANS_VERIFICATION=1 est interdit quand IRIS_ENV=production : "
            "le service refuserait de vérifier la signature des webhooks PayPal."
        )
    # Garde-fou pour Stripe : s'il est amorcé (au moins une variable posée) mais incomplet, on
    # refuse tout de suite. Sans STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET, aucune signature de
    # webhook Stripe n'est vérifiable — c'est équivalent à désactiver la vérification en production.
    # (On garde ce message précis avant le garde-fou plus général ci-dessous.)
    if cfg.production and cfg.stripe_amorce and not cfg.stripe_configure:
        raise ConfigurationInvalide(
            "En production, si Stripe est utilisé, STRIPE_SECRET_KEY et STRIPE_WEBHOOK_SECRET "
            "sont obligatoires (sans eux, aucune signature de webhook Stripe ne peut être vérifiée)."
        )
    # Nouvelle règle : en production, il faut AU MOINS UN fournisseur de paiement configuré,
    # PayPal OU Stripe. On lance aujourd'hui en Stripe seul, donc un Stripe configuré suffit,
    # même sans PayPal. On ne refuse QUE si NI PayPal NI Stripe n'est prêt.
    if cfg.production and not cfg.paypal_configure and not cfg.stripe_configure:
        raise ConfigurationInvalide(
            "En production, au moins un fournisseur de paiement doit être configuré : "
            "soit PayPal (PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_WEBHOOK_ID), "
            "soit Stripe (STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET)."
        )
    if cfg.production and not cfg.jeton_admin:
        log.warning("Aucun IRIS_JETON_ADMIN : la page d'administration sera désactivée.")
    if cfg.production and not cfg.secret_hmac_fourni:
        log.warning(
            "IRIS_LICENSE_SECRET n'est pas défini : le serveur utilise le secret historique de plans.py. "
            "Cela fonctionne, mais le secret est alors lisible dans le code source de l'application."
        )
    if cfg.mode_dev_sans_verification:
        log.warning(
            "MODE DÉVELOPPEMENT : les signatures de webhook PayPal ne sont PAS vérifiées. "
            "N'importe qui pouvant joindre ce service peut créer des abonnements."
        )
    if not cfg.smtp_configure:
        log.info("SMTP non configuré : les courriels seront écrits dans %s.", cfg.dossier_sortie)
