"""Outillage commun des tests : configuration isolée, faux PayPal, accès au vrai code de l'application.

Aucun test ne touche à PayPal, au réseau, ni à SMTP.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from fastapi.testclient import TestClient

RACINE_SERVEUR = Path(__file__).resolve().parents[1]
RACINE_DEPOT = RACINE_SERVEUR.parent
sys.path.insert(0, str(RACINE_SERVEUR))

from licences.app import creer_app          # noqa: E402
from licences.base import Base              # noqa: E402
from licences.config import Config          # noqa: E402
from licences.courriel import Facteur       # noqa: E402
from licences.paypal import ClientPaypal    # noqa: E402
from licences.service import Service        # noqa: E402

SIGNATURE_VALIDE = "signature-de-test-valide"
JETON_ADMIN = "jeton-de-test-tres-long-et-aleatoire"

# Valeurs Stripe FACTICES (aucune vraie clé). Le secret de webhook sert à signer les faux webhooks
# dans les tests : son format imite celui de Stripe (whsec_...), mais il ne vaut rien.
STRIPE_WEBHOOK_SECRET = "whsec_FACTICE_pour_les_tests_seulement"
STRIPE_SECRET_KEY = "sk_test_FACTICE_aucune_valeur"
STRIPE_PRIX_PRO = "price_FACTICE_pro"
STRIPE_PRIX_PREMIUM = "price_FACTICE_premium"
STRIPE_PRIX_ENTREPRISE = "price_FACTICE_entreprise"


# --------------------------------------------------------------------------- vrai code de l'application
def plans_application() -> ModuleType:
    """Charge backend/iris/plans.py isolément, pour tester avec le VRAI verify_key du client.

    plans.py importe .config/.db/.events, qui tirent tout le backend (pydantic, keyring…).
    On retire uniquement ces imports relatifs : les fonctions de clés n'en dépendent pas.
    Si quelqu'un modifie make_key/verify_key dans l'application, ces tests le verront.
    """
    fichier = RACINE_DEPOT / "backend" / "iris" / "plans.py"
    if not fichier.is_file():  # pragma: no cover - dépend du dépôt
        pytest.skip("backend/iris/plans.py introuvable")
    source = "\n".join(
        ligne for ligne in fichier.read_text(encoding="utf-8").splitlines()
        if not ligne.startswith("from .")
    )
    module = ModuleType("plans_application")
    module.__dict__["__file__"] = str(fichier)
    exec(compile(source, str(fichier), "exec"), module.__dict__)
    return module


# --------------------------------------------------------------------------- faux PayPal
def transport_paypal(verification: str = "auto", erreur_reseau: bool = False) -> httpx.MockTransport:
    """Simule l'API PayPal.

    verification = "auto"    : SUCCESS si l'en-tête de signature vaut SIGNATURE_VALIDE ;
                   "echec"   : toujours FAILURE ;
    erreur_reseau = True     : toute requête lève une erreur réseau.
    """
    def repondre(requete: httpx.Request) -> httpx.Response:
        if erreur_reseau:
            raise httpx.ConnectError("PayPal injoignable (simulé)", request=requete)
        if requete.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "A21AA-jeton-fictif", "token_type": "Bearer",
                                             "expires_in": 32400, "scope": "https://uri.paypal.com/services/..."})
        if requete.url.path.endswith("/v1/notifications/verify-webhook-signature"):
            import json as _json
            corps = _json.loads(requete.content.decode())
            if verification == "echec":
                statut = "FAILURE"
            else:
                statut = "SUCCESS" if corps.get("transmission_sig") == SIGNATURE_VALIDE else "FAILURE"
            return httpx.Response(200, json={"verification_status": statut})
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})

    return httpx.MockTransport(repondre)


def transport_stripe(url_session: str = "https://checkout.stripe.com/c/pay/cs_test_FACTICE",
                     erreur_reseau: bool = False, statut: int = 200) -> httpx.MockTransport:
    """Simule l'API REST Stripe pour la création de session Checkout (aucun vrai réseau)."""
    def repondre(requete: httpx.Request) -> httpx.Response:
        if erreur_reseau:
            raise httpx.ConnectError("Stripe injoignable (simulé)", request=requete)
        if requete.url.path.endswith("/v1/checkout/sessions"):
            if statut != 200:
                return httpx.Response(statut, json={"error": {"message": "refus simulé"}})
            return httpx.Response(200, json={"id": "cs_test_FACTICE", "object": "checkout.session",
                                             "url": url_session})
        return httpx.Response(404, json={})

    return httpx.MockTransport(repondre)


def entetes_paypal(signature: str = SIGNATURE_VALIDE, complets: bool = True) -> dict:
    """Les cinq en-têtes de signature que PayPal envoie avec chaque webhook."""
    if not complets:
        return {"paypal-transmission-id": "d1f0b8a0-8901-11f0-9b3a-6b6d1a2c3d4e"}
    return {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-360caa42-fca2a594-a5cafa77",
        "paypal-transmission-id": "d1f0b8a0-8901-11f0-9b3a-6b6d1a2c3d4e",
        "paypal-transmission-sig": signature,
        "paypal-transmission-time": "2026-09-03T14:22:13Z",
        "content-type": "application/json",
    }


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def config(tmp_path) -> Config:
    """Configuration de test : base et courriels dans un dossier temporaire, PayPal simulé."""
    return Config(
        environnement="test",
        mode_dev_sans_verification=False,
        paypal_client_id="id-fictif",
        paypal_secret="secret-fictif",
        paypal_webhook_id="WH-FICTIF-0001",
        paypal_environnement="sandbox",
        base_donnees=tmp_path / "licences.db",
        dossier_sortie=tmp_path / "sortie",
        jeton_admin=JETON_ADMIN,
        limite_requetes=100,
        limite_fenetre=60,
        limite_licence_requetes=100,
        stripe_secret_key=STRIPE_SECRET_KEY,
        stripe_webhook_secret=STRIPE_WEBHOOK_SECRET,
        stripe_prix_pro=STRIPE_PRIX_PRO,
        stripe_prix_premium=STRIPE_PRIX_PREMIUM,
        stripe_prix_entreprise=STRIPE_PRIX_ENTREPRISE,
    )


@pytest.fixture
def base(config) -> Base:
    b = Base(config.base_donnees)
    yield b
    b.fermer()


@pytest.fixture
def service(config, base) -> Service:
    return Service(config, base, Facteur(config))


@pytest.fixture
def fabrique_client(config, base):
    """Fabrique un TestClient avec le comportement PayPal voulu."""
    clients: list[TestClient] = []

    def fabriquer(verification: str = "auto", erreur_reseau: bool = False,
                  transport_stripe: httpx.BaseTransport | None = None, **remplacements) -> TestClient:
        for cle, valeur in remplacements.items():
            setattr(config, cle, valeur)
        faux_paypal = ClientPaypal(
            config.base_paypal, config.paypal_client_id, config.paypal_secret, config.paypal_webhook_id,
            transport=transport_paypal(verification, erreur_reseau),
        )
        app = creer_app(cfg=config, base=base, client_paypal=faux_paypal, transport_stripe=transport_stripe)
        client = TestClient(app)
        clients.append(client)
        return client

    yield fabriquer
    for c in clients:
        c.close()


@pytest.fixture
def client(fabrique_client) -> TestClient:
    """Client HTTP avec un PayPal qui valide les signatures reconnues."""
    return fabrique_client()


def poster_webhook(client: TestClient, charge: dict, signature: str = SIGNATURE_VALIDE,
                   entetes_complets: bool = True):
    return client.post("/paypal/webhook", json=charge,
                       headers=entetes_paypal(signature, entetes_complets))


def signer_stripe(corps_brut: bytes, secret: str = STRIPE_WEBHOOK_SECRET,
                  horodatage: int | None = None) -> str:
    """Construit un en-tête `Stripe-Signature` valide pour un corps brut donné (secret FACTICE)."""
    import hashlib as _hashlib
    import hmac as _hmac
    import time as _time

    t = horodatage if horodatage is not None else int(_time.time())
    charge = f"{t}.{corps_brut.decode('utf-8')}".encode("utf-8")
    signature = _hmac.new(secret.encode("utf-8"), charge, _hashlib.sha256).hexdigest()
    return f"t={t},v1={signature}"


def poster_webhook_stripe(client: TestClient, evenement: dict, *, secret: str = STRIPE_WEBHOOK_SECRET,
                          horodatage: int | None = None, signature_override: str | None = None,
                          corps_override: bytes | None = None):
    """POST un webhook Stripe avec le CORPS BRUT exact qui a été signé.

    On n'utilise surtout pas `json=` : httpx re-sérialiserait le JSON et la signature, calculée sur
    d'autres octets, ne correspondrait plus. On signe puis on envoie les mêmes bytes.
    """
    import json as _json

    corps = corps_override if corps_override is not None else _json.dumps(evenement).encode("utf-8")
    entete = signature_override if signature_override is not None else signer_stripe(corps, secret, horodatage)
    return client.post("/stripe/webhook", content=corps,
                       headers={"stripe-signature": entete, "content-type": "application/json"})
