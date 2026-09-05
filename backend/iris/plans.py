"""Plans d'abonnement IRIS : fonctionnalités, modèles et quotas mensuels par palier, clé d'abonnement, compteurs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import date, datetime, timezone

from .config import Settings
from .db import Database
from .events import EventHub

log = logging.getLogger("iris.plans")

# Paiement. paypal.me ouvre une page de paiement avec un montant pré-rempli : c'est un versement unique,
# il ne crée AUCUN abonnement récurrent et ne prévient pas IRIS. Le parcours réel est donc :
# l'utilisateur paie, envoie sa confirmation, et reçoit une clé d'abonnement générée par
# scripts/make-license-key.py, qu'il colle dans « Abonnement ». Pour un renouvellement automatique il
# faudra un compte PayPal Business avec abonnements et notifications, ou Stripe.
PAYPAL_ME = "https://paypal.me/irisvela461"
CURRENCY = "CAD"
SUPPORT_EMAIL = "miguelfreddy65@gmail.com"


def payment_link(amount: float) -> str:
    """Lien de paiement avec le montant déjà rempli (chaîne vide si le montant est nul)."""
    if not amount:
        return ""
    return f"{PAYPAL_ME}/{amount:.2f}{CURRENCY}"


# Secret de signature des clés (à remplacer par un serveur de licences avant la vente à grande échelle)
LICENSE_SECRET = b"VELA-IRIS-2026-license-v1"

PLANS: dict[str, dict] = {
    "gratuit": {
        "label": "Gratuit",
        "price": 0.0,
        "quota_requests": 300,
        "quota_tts_chars": 0,  # voix Windows uniquement
        "features": {"chat", "pc_control", "routines", "reminders", "register"},
        "tts": "windows",
        "models": {"fast": "", "reasoning": "", "vision": ""},  # modèles gratuits, fournis par le relais VELA
        "contents": [
            "Interface vocale continue : contrôle du PC, routines, rappels, mémoire",
            "Modèles gratuits fournis par VELA, voix Windows, reconnaissance hors-ligne",
            "Gouvernance et confidentialité complètes (consentements, registre, mode confidentiel)",
        ],
        "api_cost": 0.0,
    },
    "pro": {
        "label": "Pro",
        "price": 19.99,
        "quota_requests": 600,
        "quota_tts_chars": 60000,
        "features": {"chat", "pc_control", "routines", "reminders", "register", "elevenlabs", "web"},
        "tts": "elevenlabs",
        "models": {"fast": "google/gemini-2.5-flash", "reasoning": "openai/gpt-5-mini", "vision": "google/gemini-2.5-flash"},
        "contents": [
            "Tout Gratuit",
            "Voix ElevenLabs (français naturel)",
            "Gemini 2.5 Flash + GPT-5 mini",
            "Navigation web et comptes enregistrés (Omnivox, portails, outils métier)",
        ],
        "api_cost": 13.0,
    },
    "premium": {
        "label": "Premium",
        "price": 29.99,
        "quota_requests": 1000,
        "quota_tts_chars": 120000,
        "features": {"chat", "pc_control", "routines", "reminders", "register", "elevenlabs", "web", "screen", "memory", "tasks", "dev"},
        "tts": "elevenlabs",
        "models": {"fast": "google/gemini-2.5-flash", "reasoning": "anthropic/claude-sonnet-5", "vision": "anthropic/claude-sonnet-5"},
        "contents": [
            "Tout Pro",
            "Claude Sonnet 5 pour le raisonnement et le code",
            "Contrôle complet de l'écran (vision, OCR, souris)",
            "Tâches asynchrones avec rapport vocal (build, tests, recherches)",
            "Résumé quotidien et mémoire partagée entre agents",
            "Retour vocal développeur (git, tests, build)",
        ],
        "api_cost": 16.0,
    },
    "entreprise": {
        "label": "Entreprise",
        "price": 99.99,
        "quota_requests": 1500,
        "quota_tts_chars": 250000,
        "features": {"chat", "pc_control", "routines", "reminders", "register", "elevenlabs", "web", "screen", "memory", "tasks", "dev", "opus", "enterprise", "content"},
        "tts": "elevenlabs",
        "models": {"fast": "anthropic/claude-sonnet-5", "reasoning": "anthropic/claude-opus-5", "vision": "anthropic/claude-opus-5"},
        "contents": [
            "Tout Premium",
            "Claude Opus 5",
            "Connecteurs d'agents de code et outils PME (à venir)",
            "Création de contenu POV + montage IA (à venir, caméra des lunettes VELA)",
            "Politique de gouvernance d'entreprise et export d'audit (à venir)",
        ],
        "api_cost": 62.0,
    },
}
PLAN_ORDER = ["gratuit", "pro", "premium", "entreprise"]
# Le matériel. L'offre groupée « lunettes + 12 mois » a été retirée : avec un prix affiché
# pour les lunettes, son montant ne correspondait plus à une addition défendable.
LUNETTES = {"label": "Lunettes VELA", "price": 250.0}


class QuotaExceeded(Exception):
    def __init__(self, plan: str, used: int, limit: int):
        self.plan, self.used, self.limit = plan, used, limit
        super().__init__(f"Quota mensuel atteint ({used}/{limit} requêtes, plan {PLANS[plan]['label']}).")


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


# ------------------------------------------------------------------ clés d'abonnement
def make_key(plan: str, expires: str, email: str = "") -> str:
    """Clé IRIS-<payload>-<signature> ; payload = base64(json{plan, exp, email})."""
    if plan not in PLANS:
        raise ValueError("plan inconnu")
    payload = base64.urlsafe_b64encode(json.dumps({"p": plan, "e": expires, "u": email}, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(LICENSE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:20]
    return f"IRIS-{payload}-{sig}"


def verify_key(key: str) -> dict | None:
    try:
        key = (key or "").strip()
        if not key.startswith("IRIS-"):
            return None
        # La charge utile est du base64 « url-safe » : elle peut contenir des « - ».
        # Il faut donc couper la signature par la DROITE, sinon certaines clés valides sont rejetées.
        payload, sig = key[len("IRIS-"):].rsplit("-", 1)
        expected = hmac.new(LICENSE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:20]
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode())
        plan, exp = data.get("p"), data.get("e") or ""
        if plan not in PLANS:
            return None
        if exp and date.fromisoformat(exp) < date.today():
            return {"plan": plan, "expires": exp, "expired": True}
        return {"plan": plan, "expires": exp, "expired": False, "email": data.get("u", "")}
    except Exception:
        return None


class PlanService:
    def __init__(self, db: Database, settings: Settings, hub: EventHub, secrets=None):
        self.db = db
        self.settings = settings
        self.hub = hub
        self.secrets = secrets  # SecretStore (clés personnelles de l'utilisateur)

    # ------------------------------------------------------------------ clés personnelles (BYOK)
    # Les plans vendent des ressources fournies par VELA (modèles, voix, quotas). Quand l'utilisateur apporte sa propre
    # clé (OpenRouter dans le coffre, ELEVENLABS_API_KEY dans .env), ce qu'elle paie n'est jamais bridé par le plan.
    def byok_models(self) -> bool:
        try:
            return bool(self.secrets is not None and self.secrets.has_api_key("openrouter"))
        except Exception:
            return False

    def byok_tts(self) -> bool:
        return bool((os.environ.get("ELEVENLABS_API_KEY") or "").strip())

    # ------------------------------------------------------------------ plan courant
    @property
    def plan(self) -> str:
        u = self.settings.user
        name = u.plan if u.plan in PLANS else "gratuit"
        if name != "gratuit" and u.plan_expires:
            try:
                if date.fromisoformat(u.plan_expires) < date.today():
                    return "gratuit"
            except ValueError:
                pass
        return name

    def info(self) -> dict:
        p = PLANS[self.plan]
        usage = self.usage()
        return {
            "plan": self.plan,
            "label": p["label"],
            "price": p["price"],
            "expires": self.settings.user.plan_expires,
            "demo": self.settings.user.plan_demo,
            "quota_requests": p["quota_requests"],
            "quota_tts_chars": p["quota_tts_chars"],
            "features": sorted(p["features"]),
            "models": p["models"],
            "usage": usage,
            "payment": {
                "paypal_me": PAYPAL_ME,
                "currency": CURRENCY,
                "support_email": SUPPORT_EMAIL,
                "recurring": False,  # paypal.me = versement unique : le renouvellement est manuel pour l'instant
            },
            "byok": {"models": self.byok_models(), "tts": self.byok_tts()},
            "plans": [
                {
                    "name": n,
                    **{k: v for k, v in PLANS[n].items() if k != "features"},
                    "features": sorted(PLANS[n]["features"]),
                    "pay_url": payment_link(PLANS[n]["price"]),
                }
                for n in PLAN_ORDER
            ],
            "lunettes": {**LUNETTES, "pay_url": payment_link(LUNETTES["price"])},
        }

    BYOK_MODEL_FEATURES = {"web", "screen", "memory", "tasks", "dev"}

    def feature_allowed(self, feature: str) -> bool:
        if feature == "elevenlabs" and self.byok_tts():
            return True
        if feature in self.BYOK_MODEL_FEATURES and self.byok_models():
            return True
        return feature in PLANS[self.plan]["features"]

    def models(self) -> dict:
        return dict(PLANS[self.plan]["models"])

    # ------------------------------------------------------------------ quotas
    def usage(self, month: str | None = None) -> dict:
        m = month or month_key()
        row = self.db.one("SELECT * FROM plan_usage WHERE month=?", (m,))
        p = PLANS[self.plan]
        used = int(row["requests"]) if row else 0
        chars = int(row["tts_chars"]) if row else 0
        return {
            "month": m,
            "requests": used,
            "requests_limit": p["quota_requests"],
            "requests_ratio": round(used / p["quota_requests"], 3) if p["quota_requests"] else 0,
            "tts_chars": chars,
            "tts_chars_limit": p["quota_tts_chars"],
        }

    def _bump(self, requests: int = 0, tts_chars: int = 0) -> None:
        m = month_key()
        self.db.execute(
            "INSERT INTO plan_usage(month, requests, tts_chars) VALUES(?,?,?) "
            "ON CONFLICT(month) DO UPDATE SET requests = requests + excluded.requests, tts_chars = tts_chars + excluded.tts_chars",
            (m, requests, tts_chars),
        )

    def check_request(self) -> dict:
        """À appeler avant chaque requête à un agent : compte et lève QuotaExceeded si le quota est dépassé."""
        u = self.usage()
        limit = u["requests_limit"]
        if limit and u["requests"] >= limit and not self.byok_models():
            raise QuotaExceeded(self.plan, u["requests"], limit)
        self._bump(requests=1)
        u = self.usage()
        for threshold in (0.8, 0.95):
            if limit and u["requests"] == int(limit * threshold):
                self.hub.publish("plan.quota", ratio=u["requests_ratio"], used=u["requests"], limit=limit, plan=self.plan,
                                 message=f"Quota mensuel à {int(threshold * 100)} % ({u['requests']}/{limit} requêtes, plan {PLANS[self.plan]['label']}).")
        return u

    def count_tts(self, chars: int) -> None:
        if chars > 0:
            self._bump(tts_chars=chars)

    # ------------------------------------------------------------------ activation
    def activate(self, key: str) -> dict:
        info = verify_key(key)
        if not info:
            raise ValueError("Clé d'abonnement invalide.")
        if info.get("expired"):
            raise ValueError(f"Cette clé a expiré le {info['expires']}.")
        self.settings.update({"plan": info["plan"], "plan_expires": info["expires"], "license_key": key.strip(), "plan_demo": False})
        self.hub.publish("plan.changed", plan=info["plan"])
        return self.info()

    def set_demo(self, plan: str) -> dict:
        """Mode démonstration : change de plan localement sans clé (présentations, tests)."""
        if plan not in PLANS:
            raise ValueError("plan inconnu")
        self.settings.update({"plan": plan, "plan_expires": "", "license_key": "", "plan_demo": plan != "gratuit"})
        self.hub.publish("plan.changed", plan=plan)
        return self.info()
