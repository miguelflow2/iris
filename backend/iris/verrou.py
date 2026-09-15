"""Verrouillage d'IRIS, sur place ou à distance, et effacement à distance (interface I, 2026-09-13).

Le cas d'usage est la perte ou le vol de l'ordinateur. Trois gestes :
- VERROUILLER : l'écoute s'arrête, les lunettes sont coupées, les services qui captent ou parlent
  (sous-titres, alertes, écoute assistée, enregistrement, cours, interprète, partage, pas à pas et
  entraînement avec leurs minuteurs) s'arrêtent, et TOUTES les routes protégées répondent 401
  (main.raison_de_refus lit `ctx.verrou.verrouille`). L'état est écrit sur le disque : un redémarrage ne
  déverrouille pas.
- DÉVERROUILLER : seulement avec le mot de passe du propriétaire (comptes.py), avec le même
  ralentissement après plusieurs échecs. Sans mot de passe défini, on refuse de verrouiller : un verrou
  sans clé enfermerait le propriétaire dehors.
- EFFACER (à distance) : mémoire, rappels liés aux personnes, journal d'écoute, cours, reçus,
  conversations, tâches, rappels, veilles, routines, séances d'entraînement, historique d'activité
  (table presence), captures (photos et audio), empreinte vocale, zones sans mémoire, jetons (sessions
  des téléphones, code d'appairage, clés d'API et identifiants enregistrés, profil du navigateur piloté),
  lunettes oubliées. Le registre de confidentialité est remis à zéro (ses détails reprennent des extraits
  de messages et de requêtes ; le vider ligne à ligne casserait sa chaîne) : il repart d'une entrée
  « effacement_a_distance ». Le compte et le mot de passe restent, pour pouvoir déverrouiller ; le jeton
  d'appareil du relais reste aussi, pour que l'ordinateur reste verrouillable.
  Constat du 2026-09-14 : TOUTE table de la base est vidée, sauf une liste blanche explicite
  (TABLES_CONSERVEES : consentements, compteur d'usage du forfait) — une table ajoutée plus tard ne peut
  plus être oubliée. S'y ajoutent la copie de secours des réglages (settings.json.bak, settings.corrupt.json),
  l'état du mode invité, l'association téléphone-lunettes, les clés d'API écrites dans le .env du dossier de
  données et le journal technique (backend.log et ses copies, dossier transmis par Electron).

Activation du verrouillage à distance : elle vit dans verrou.json (`distant_actif`), pas dans un réglage
ordinaire. L'allumer est permis ; l'éteindre exige le mot de passe du propriétaire (route
POST /api/confiance/verrou/distant) : sinon le voleur d'un portable resté ouvert le neutraliserait en un
clic. Le réglage `verrou_distant_actif` n'en est plus que le reflet, pour les écrans existants : l'allumer
active ; l'éteindre par PATCH /api/settings exige aussi le mot de passe ({mot_de_passe} dans le corps, 403
sinon, main.py) ; changé autrement sans mot de passe, il est rétabli (événement verrou.distant).

Code de secours : le relais ne connaît pas le mot de passe (il ne doit jamais le voir). La page
publique /verrou demande donc un CODE DE SECOURS choisi ici. Constat bloquant du 2026-09-14 : le code
transitait EN CLAIR par le relais, et toute machine qui se faisait passer pour cet ordinateur le recevait.
Désormais le code ne quitte jamais le navigateur :
- ici, on garde (chiffrée par ctx.crypto) la clé cle = PBKDF2-SHA256(code, sel, PREUVE_ITERATIONS), et on
  publie au relais le sel et le nombre d'itérations (pas le code, pas la clé) ;
- la page calcule la même clé, puis preuve = HMAC-SHA256(cle, « vela-verrou|v1|action|nonce ») avec un nonce
  horodaté tiré par le relais ; on la vérifie, on refuse un nonce déjà vu (gardé NONCE_AGE_MAX_S) ou trop
  vieux : rien n'est rejouable ;
- la réponse porte confirmation = HMAC-SHA256(cle, « vela-verrou-resultat|v1|etat|nonce|defi_page ») : la page
  n'affiche un succès que si elle la vérifie, ce que ni le relais ni une autre machine ne peuvent imiter.
Les messages « verrou » n'arrivent que si cet ordinateur est LIÉ au courriel sur le relais (telecommande.py :
clé propre à l'ordinateur, confirmée par courriel, puis défi-réponse). Un code défini avant cette version
n'a pas de clé de preuve : il doit être choisi de nouveau (`code_a_redefinir`). Les échecs de code sont
persistés dans verrou.json : un redémarrage ne remet plus la fenêtre d'essais à zéro. Limite : une preuve
permet à qui la détient (le relais, par exemple) d'essayer des codes hors ligne ; un code long l'en empêche.

Limites dites telles quelles :
- rien ne se passe si l'ordinateur est éteint ou hors ligne (le relais garde la commande en mémoire
  jusqu'à la reconnexion, et la perd s'il redémarre) ;
- ce n'est pas un chiffrement du disque : quelqu'un qui démarre l'ordinateur sur un autre système lit
  les fichiers (chiffrés par IRIS, mais avec une clé gardée sur la même machine). Le chiffrement du
  disque de Windows (BitLocker) reste la protection contre le vol ;
- l'effacement supprime les lignes et les fichiers, puis compacte la base (VACUUM) ; il ne garantit pas
  qu'un outil de récupération ne retrouve rien sur un disque non chiffré ;
- les fichiers exportés hors d'IRIS (dossier Images) et ce qui a déjà été copié ailleurs ne sont pas
  effacés ;
- un WebSocket /ws DÉJÀ ouvert avant le verrouillage n'est pas fermé par ce module (main.py ne vérifie le
  verrou qu'à l'ouverture) : l'événement verrou.etat est publié, mais la fermeture est demandée à main.py ;
- quand le verrouillage à distance est actif, changer l'adresse du relais ou le courriel du compte exige le
  mot de passe du propriétaire (main.py) ; le mode 100 % local, lui, garde le canal « verrouillage
  seulement » ouvert (telecommande.py), et Confidentialité le dit.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("iris.verrou")

CODE_MIN = 6
CODE_MAX = 64
ESSAIS_CODE_MAX = 5
FENETRE_ESSAIS_S = 900  # 15 minutes
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
PBKDF2_ITERATIONS = 240_000
# Clé de preuve du code de secours : PBKDF2-SHA256, même coût que la page /verrou du relais (WebCrypto) et que
# le sel factice qu'il rend pour un courriel inconnu (serveur/verrou_distant.py, ITERATIONS_DEFAUT).
PREUVE_ITERATIONS = 240_000
NONCE_AGE_MAX_S = 80 * 3600  # 72 h d'attente au relais, plus une marge
NONCE_AVANCE_MAX_S = 3600  # horloges du relais et de l'ordinateur décalées
DELAI_LUNETTES_S = 10.0

VERROUILLEE = "IRIS est verrouillée. Déverrouillez-la avec le mot de passe du propriétaire."
SANS_MOT_DE_PASSE = (
    "Choisissez d'abord un mot de passe (Profil › Compte et sécurité) : sans lui, personne ne pourrait "
    "déverrouiller IRIS."
)
LIMITE = (
    "Le verrouillage à distance n'agit que si l'ordinateur est allumé, connecté et lié à votre compte par le "
    "courriel de confirmation. Le code de secours ne quitte pas le navigateur de la page : seule une preuve à "
    "usage unique transite, ce qui rend un code long indispensable. Il ne remplace pas le chiffrement du disque "
    "(BitLocker) contre le vol. L'effacement à distance remet aussi à zéro le registre de confidentialité : il "
    "repart de l'effacement."
)
CODE_A_REDEFINIR = (
    "Choisissez de nouveau votre code de secours sur l'ordinateur : le code défini avant la mise à jour de "
    "sécurité du 14 septembre 2026 ne peut plus servir à distance."
)
DESACTIVER_EXIGE_MOT_DE_PASSE = (
    "Pour désactiver le verrouillage à distance, confirmez avec le mot de passe du propriétaire."
)
LOT_GARDE_S = 120.0  # un lot de commandes différées jamais clos (relais tombé) est compté après ce délai

# Tables vidées par l'effacement à distance, dans cet ordre (les messages avant leurs conversations).
TABLES_EFFACEES: tuple[tuple[str, str], ...] = (
    ("memoire", "memories"),
    ("rappels_contexte", "rappels_contexte"),
    ("journal", "journal_ecoute"),
    ("cours_lignes", "cours_lignes"),
    ("cours", "cours"),
    ("recus", "recus"),
    ("messages", "messages"),
    ("conversations", "conversations"),
    ("taches", "tasks"),
    ("rappels", "reminders"),
    ("veilles_evenements", "watch_events"),
    ("veilles", "watches"),
    ("seances_entrainement", "entrainement_seances"),
    ("routines", "routines"),
    ("presence", "presence"),
)
# Tables GARDÉES par l'effacement : tout le reste est vidé (voir effacer_donnees). consents : les choix de
# consentement de l'utilisateur (les garder ne révèle rien de sa vie) ; plan_usage : compteurs du forfait ;
# privacy_events : remis à zéro à part, en dernier ; sqlite_* : tables internes de SQLite.
TABLES_CONSERVEES = frozenset(("consents", "plan_usage", "privacy_events"))
# Fichiers du dossier de données qui gardent des données personnelles hors de la base.
FICHIERS_EFFACES = ("settings.corrupt.json", "settings.json.bak", "mode-invite.json", "lunettes-association.json")
# Variables du .env du dossier de données qui sont des secrets (clé de voix personnelle, etc.).
SUFFIXES_SECRETS_ENV = ("_API_KEY", "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_MOT_DE_PASSE")
COFFRE_CLES = ("recherche",)  # clés d'API hors agents (recherche_web.py)
COFFRE_IDENTIFIANTS = ("courriel", "telephonie", "telephonie-numero")  # courriel.py, telephonie.py


class RefusVerrou(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.message = message
        self.code = code


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def hacher_code(code: str, sel: bytes | None = None) -> dict:
    """Empreinte du code de secours : scrypt (sel de 16 octets), ou PBKDF2-SHA256 si scrypt manque."""
    sel = sel or secrets.token_bytes(16)
    brut = code.encode("utf-8")
    try:
        empreinte = hashlib.scrypt(brut, salt=sel, dklen=32, **SCRYPT)
        return {"algo": "scrypt", **SCRYPT, "sel": _b64(sel), "hash": _b64(empreinte)}
    except (AttributeError, ValueError):
        empreinte = hashlib.pbkdf2_hmac("sha256", brut, sel, PBKDF2_ITERATIONS)
        return {"algo": "pbkdf2", "iterations": PBKDF2_ITERATIONS, "sel": _b64(sel), "hash": _b64(empreinte)}


def code_conforme(stocke: dict, code: str) -> bool:
    try:
        sel = _debase64(stocke["sel"])
        attendu = _debase64(stocke["hash"])
        brut = (code or "").encode("utf-8")
        if stocke.get("algo") == "scrypt":
            calcule = hashlib.scrypt(brut, salt=sel, dklen=len(attendu), n=int(stocke["n"]),
                                     r=int(stocke["r"]), p=int(stocke["p"]))
        else:
            calcule = hashlib.pbkdf2_hmac("sha256", brut, sel, int(stocke.get("iterations") or PBKDF2_ITERATIONS))
        return hmac.compare_digest(attendu, calcule)
    except Exception as exc:
        log.warning("code de secours illisible : %s", exc)
        return False


def deriver_cle_preuve(code: str, sel: bytes, iterations: int = PREUVE_ITERATIONS) -> bytes:
    """Même dérivation que la page /verrou (WebCrypto PBKDF2, SHA-256, 256 bits, code en UTF-8 sans espaces autour)."""
    return hashlib.pbkdf2_hmac("sha256", (code or "").strip().encode("utf-8"), sel, int(iterations), dklen=32)


def preuve_commande(cle: bytes, action: str, nonce: str) -> str:
    return _b64(hmac.new(cle, f"vela-verrou|v1|{action}|{nonce}".encode("utf-8"), hashlib.sha256).digest())


def confirmation_resultat(cle: bytes, etat: str, nonce: str, defi_page: str) -> str:
    message = f"vela-verrou-resultat|v1|{etat}|{nonce}|{defi_page}"
    return _b64(hmac.new(cle, message.encode("utf-8"), hashlib.sha256).digest())


def nonce_acceptable(nonce: Any, maintenant: float | None = None) -> bool:
    """Nonce du relais : « horodatage.aléatoire ». Refusé s'il est mal formé, trop vieux ou venu du futur."""
    if not isinstance(nonce, str) or not 20 <= len(nonce) <= 96 or "." not in nonce:
        return False
    horodatage, _, aleatoire = nonce.partition(".")
    if not horodatage.isdigit() or len(aleatoire) < 16:
        return False
    maintenant = time.time() if maintenant is None else maintenant
    instant = int(horodatage)
    return maintenant - NONCE_AGE_MAX_S <= instant <= maintenant + NONCE_AVANCE_MAX_S


def purger_journal_technique(jours: int | None = None, dossier: str | Path | None = None) -> int:
    """Vide le journal technique d'IRIS (constat du 2026-09-14 : il n'est pas chiffré).

    Le dossier vient d'Electron (variable IRIS_JOURNAL_TECHNIQUE) : backend.log et ses copies mises de côté
    (backend-*.log). `jours=None` (effacement à distance) : tout est vidé ; `jours > 0` (rétention) : seuls
    les fichiers plus vieux que `jours` jours le sont. Le fichier courant est TRONQUÉ plutôt que supprimé :
    Electron le garde ouvert en ajout. Renvoie le nombre de fichiers vidés ; ne lève jamais."""
    import os

    dossier = dossier or os.environ.get("IRIS_JOURNAL_TECHNIQUE") or ""
    if not dossier:
        return 0
    racine = Path(dossier)
    if not racine.is_dir():
        return 0
    limite = None if not jours or jours <= 0 else time.time() - int(jours) * 86400
    if jours is not None and limite is None:
        return 0  # rétention illimitée
    vides = 0
    for fichier in list(racine.glob("backend*.log")):
        try:
            if limite is not None and fichier.stat().st_mtime >= limite:
                continue
            if fichier.name == "backend.log":
                with open(fichier, "r+b") as flux:
                    flux.truncate(0)
            else:
                fichier.unlink()
            vides += 1
        except OSError as exc:
            log.info("journal technique : %s non vidé (%s)", fichier.name, exc)
    return vides


def retirer_secrets_env(data_dir: str | Path) -> int:
    """Retire du .env du dossier de données les lignes de secrets (clés d'API, jetons) et les oublie de
    l'environnement du service. Renvoie le nombre de lignes retirées."""
    import os

    chemin = Path(data_dir) / ".env"
    if not chemin.is_file():
        return 0
    gardees: list[str] = []
    retirees = 0
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        cle = ligne.split("=", 1)[0].strip() if "=" in ligne and not ligne.strip().startswith("#") else ""
        if cle and cle.upper().endswith(SUFFIXES_SECRETS_ENV):
            os.environ.pop(cle, None)
            retirees += 1
            continue
        gardees.append(ligne)
    if retirees:
        chemin.write_text("\n".join(gardees) + ("\n" if gardees else ""), encoding="utf-8")
    return retirees


async def _appeler(fonction: Any, *args: Any) -> Any:
    """Appelle une méthode d'un module voisin (sync ou async) sans connaître sa signature exacte."""
    try:
        inspect.signature(fonction).bind(*args)
    except TypeError:
        args = ()
    except ValueError:  # signature introuvable (fonction native) : on tente sans argument
        args = ()
    if inspect.iscoroutinefunction(fonction):
        return await fonction(*args)
    resultat = await asyncio.to_thread(fonction, *args)
    if inspect.isawaitable(resultat):
        return await resultat
    return resultat


class VerrouIRIS:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.fichier = Path(ctx.settings.data_dir) / "verrou.json"
        self._verrou = threading.RLock()
        self._echecs_code: list[float] = []
        donnees = self._lire()
        self.verrouille: bool = bool(donnees.get("verrouille"))
        self.depuis: str | None = donnees.get("depuis") if self.verrouille else None
        self.raison: str | None = donnees.get("raison") if self.verrouille else None
        self._code: dict | None = donnees.get("code") if isinstance(donnees.get("code"), dict) else None
        # Clé de preuve du code de secours (sel, itérations, clé chiffrée) : voir l'en-tête du module.
        self._preuve: dict | None = donnees.get("preuve") if isinstance(donnees.get("preuve"), dict) else None
        # Nonces déjà acceptés (nonce -> instant) et échecs de code : persistés, un redémarrage ne les oublie pas.
        vus = donnees.get("nonces_vus")
        self._nonces_vus: dict[str, float] = {str(n): float(t) for n, t in vus.items()} if isinstance(vus, dict) else {}
        echecs = donnees.get("echecs_code")
        self._echecs_code = [float(t) for t in echecs if isinstance(t, (int, float))] if isinstance(echecs, list) else []
        # Première lecture après la mise à jour : l'activation reprend l'ancien réglage, puis verrou.json fait foi.
        if "distant_actif" in donnees:
            self.distant_actif: bool = bool(donnees.get("distant_actif"))
        else:
            self.distant_actif = bool(getattr(ctx.settings.user, "verrou_distant_actif", False))
        # Lots de commandes livrées depuis la file du relais : lot -> {valide, echecs, a}.
        self._lots: dict[str, dict] = {}
        # Constat du 2026-09-14 : sur l'ordinateur, l'application s'ouvre sans mot de passe (jeton local). Si
        # l'utilisateur le choisit, IRIS démarre verrouillée et attend le mot de passe du propriétaire. Rien
        # n'est écrit ici : chaque démarrage reverrouille, et le déverrouillage vaut pour la session.
        self.ouverture_verrouillee: bool = bool(donnees.get("ouverture_verrouillee"))
        if self.ouverture_verrouillee and not self.verrouille and self._mot_de_passe_defini():
            self.verrouille, self.depuis, self.raison = True, maintenant_iso(), "ouverture"
        if self.verrouille:
            log.warning("IRIS démarre verrouillée (%s, depuis %s)", self.raison, self.depuis)

    # ------------------------------------------------------------------ persistance
    def _lire(self) -> dict:
        try:
            return json.loads(self.fichier.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _ecrire(self) -> None:
        contenu = {"verrouille": self.verrouille, "depuis": self.depuis, "raison": self.raison, "code": self._code,
                   "distant_actif": self.distant_actif, "ouverture_verrouillee": self.ouverture_verrouillee,
                   "preuve": self._preuve, "nonces_vus": self._nonces_vus,
                   "echecs_code": self._echecs_code[-50:]}
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self.fichier.with_suffix(".tmp")
        temporaire.write_text(json.dumps(contenu, indent=2), encoding="utf-8")
        temporaire.replace(self.fichier)
        try:
            self.fichier.chmod(0o600)
        except Exception:
            pass

    def _journaliser(self, evenement: str, detail: str = "") -> None:
        try:
            self.ctx.consent.log(evenement, detail=detail)
        except Exception as exc:  # pragma: no cover
            log.debug("registre de confidentialité : %s", exc)

    # ------------------------------------------------------------------ état
    @property
    def code_defini(self) -> bool:
        return bool(self._code and self._code.get("hash")) or bool(self._preuve and self._preuve.get("cle"))

    @property
    def code_a_redefinir(self) -> bool:
        """Un code défini avant la preuve à usage unique n'a pas de clé de preuve : il ne sert plus à distance."""
        return self.code_defini and not (self._preuve and self._preuve.get("cle"))

    def infos_preuve(self) -> dict | None:
        """Ce que l'ordinateur publie au relais pour la page /verrou : le sel et le coût. Jamais le code ni la clé."""
        if not self._preuve or not self._preuve.get("cle"):
            return None
        return {"sel": self._preuve.get("sel"), "iterations": int(self._preuve.get("iterations") or PREUVE_ITERATIONS)}

    def _cle_preuve(self) -> bytes | None:
        try:
            brut = _debase64(str((self._preuve or {})["cle"]))
            if (self._preuve or {}).get("chiffree"):
                return _debase64(self.ctx.crypto.decrypt(brut))
            return brut
        except Exception as exc:
            log.warning("clé de preuve du code de secours illisible : %s", type(exc).__name__)
            return None

    def _mot_de_passe_defini(self) -> bool:
        comptes = getattr(self.ctx, "comptes", None)
        return bool(comptes is not None and comptes.configure)

    def etat(self) -> dict:
        user = self.ctx.settings.user
        telecommande = getattr(self.ctx, "telecommande", None)
        return {
            "verrouille": self.verrouille,
            "depuis": self.depuis,
            "raison": self.raison,
            "actif_distance": self.distant_actif,
            "ouverture_verrouillee": self.ouverture_verrouillee,
            "desactivation_exige_mot_de_passe": self._mot_de_passe_defini(),
            "code_defini": self.code_defini,
            "code_a_redefinir": self.code_a_redefinir,
            "mot_de_passe_defini": self._mot_de_passe_defini(),
            "courriel_defini": bool((getattr(user, "licence_email", "") or "").strip()),
            "relais_connecte": bool(getattr(telecommande, "connecte", False)),
            # Liaison de cet ordinateur au courriel sur le relais (confirmée par courriel) : sans elle, la page
            # /verrou ne peut pas l'atteindre. {etat, message} tels que la télécommande les a obtenus.
            "liaison_relais": dict(getattr(telecommande, "liaison", None) or {}) or None,
            # Code de 6 caractères à recopier sur la page de confirmation du relais (telecommande.empreinte_cle).
            "empreinte_liaison": self._empreinte_liaison(telecommande),
            "limite": LIMITE,
        }

    @staticmethod
    def _empreinte_liaison(telecommande: Any) -> str | None:
        empreinte = getattr(telecommande, "empreinte", None)
        if not callable(empreinte):
            return None
        try:
            return empreinte()
        except Exception:  # pragma: no cover
            return None

    def _publier(self) -> None:
        try:
            self.ctx.hub.publish("verrou.etat", verrouille=self.verrouille, depuis=self.depuis, raison=self.raison)
        except Exception as exc:  # pragma: no cover
            log.debug("verrou : publication (%s)", exc)

    # ------------------------------------------------------------------ code de secours
    def definir_code(self, code: str, mot_de_passe: str | None = None) -> dict:
        if self.verrouille:
            raise RefusVerrou(VERROUILLEE, 423)
        code = (code or "").strip()
        if not CODE_MIN <= len(code) <= CODE_MAX:
            raise RefusVerrou(f"Le code de secours doit faire de {CODE_MIN} à {CODE_MAX} caractères.", 422)
        comptes = getattr(self.ctx, "comptes", None)
        if self.code_defini and comptes is not None and comptes.configure:
            # Remplacer un code existant exige le mot de passe : sinon quiconque trouve la session ouverte
            # pourrait priver le propriétaire du verrouillage à distance.
            if not mot_de_passe or not comptes.verifier(mot_de_passe):
                raise RefusVerrou("Pour remplacer le code de secours, confirmez avec le mot de passe du propriétaire.", 403)
        sel = secrets.token_bytes(16)
        cle = deriver_cle_preuve(code, sel, PREUVE_ITERATIONS)
        crypto = getattr(self.ctx, "crypto", None)
        if crypto is not None:
            cle_gardee, chiffree = _b64(crypto.encrypt(_b64(cle))), True
        else:  # pragma: no cover - contexte minimal sans chiffrement : le fichier reste en 0600
            cle_gardee, chiffree = _b64(cle), False
        with self._verrou:
            self._code = hacher_code(code)
            self._preuve = {"algo": "pbkdf2-sha256", "iterations": PREUVE_ITERATIONS, "sel": _b64(sel),
                            "cle": cle_gardee, "chiffree": chiffree}
            self._echecs_code.clear()
            self._ecrire()
        self._journaliser("verrou_code_defini")
        # Nouveau sel : la télécommande le republie au relais (sinon la page calculerait avec l'ancien).
        publier = getattr(getattr(self.ctx, "telecommande", None), "publier_infos_verrou", None)
        if callable(publier):
            try:
                publier()
            except Exception as exc:  # pragma: no cover
                log.info("verrou : sel non republié (%s)", exc)
        return self.etat()

    # ------------------------------------------------------------------ activation à distance
    def definir_distant(self, actif: bool, mot_de_passe: str | None = None) -> dict:
        """Active ou désactive le verrouillage à distance. Activer ajoute une protection : permis. Désactiver
        la retire : le mot de passe du propriétaire est exigé dès qu'un compte existe, pour la même raison que
        remplacer le code de secours — une session laissée ouverte ne doit pas suffire."""
        if self.verrouille:
            raise RefusVerrou(VERROUILLEE, 423)
        actif = bool(actif)
        if not actif and self.distant_actif:
            comptes = getattr(self.ctx, "comptes", None)
            if comptes is not None and comptes.configure:
                trop = getattr(comptes, "_trop_d_essais", None)
                if callable(trop) and trop():
                    raise RefusVerrou("Trop de tentatives : réessayez dans quelques minutes.", 429)
                if not mot_de_passe or not comptes.verifier(mot_de_passe):
                    self._journaliser("verrou_distant_desactivation_refusee")
                    raise RefusVerrou(DESACTIVER_EXIGE_MOT_DE_PASSE, 403)
        with self._verrou:
            change = actif != self.distant_actif
            self.distant_actif = actif
            self._ecrire()
        self._refleter_reglage()
        if change:
            self._journaliser("verrou_distant_active" if actif else "verrou_distant_desactive")
            self._publier_distant(None)
            relancer = getattr(getattr(self.ctx, "telecommande", None), "relancer", None)
            if actif and callable(relancer):
                try:
                    relancer()  # liaison au courriel demandée tout de suite (telecommande.py)
                except Exception as exc:  # pragma: no cover
                    log.info("verrou : liaison non relancée (%s)", exc)
        return self.etat()

    def definir_ouverture(self, actif: bool, mot_de_passe: str | None = None) -> dict:
        """« Demander le mot de passe à l'ouverture d'IRIS ». L'activer exige qu'un mot de passe existe (sinon
        personne ne pourrait rouvrir IRIS) ; le désactiver exige ce mot de passe (une session laissée ouverte
        ne doit pas suffire à retirer la protection)."""
        if self.verrouille:
            raise RefusVerrou(VERROUILLEE, 423)
        actif = bool(actif)
        comptes = getattr(self.ctx, "comptes", None)
        if actif and not self._mot_de_passe_defini():
            raise RefusVerrou(SANS_MOT_DE_PASSE, 409)
        if not actif and self.ouverture_verrouillee and comptes is not None and comptes.configure:
            trop = getattr(comptes, "_trop_d_essais", None)
            if callable(trop) and trop():
                raise RefusVerrou("Trop de tentatives : réessayez dans quelques minutes.", 429)
            if not mot_de_passe or not comptes.verifier(mot_de_passe):
                raise RefusVerrou("Pour ne plus demander le mot de passe à l'ouverture d'IRIS, confirmez avec le mot "
                                  "de passe du propriétaire.", 403)
        with self._verrou:
            change = actif != self.ouverture_verrouillee
            self.ouverture_verrouillee = actif
            self._ecrire()
        if change:
            self._journaliser("verrou_ouverture_active" if actif else "verrou_ouverture_desactive")
        return self.etat()

    def _refleter_reglage(self) -> None:
        """Garde `settings.user.verrou_distant_actif` égal à l'état réel : les écrans existants le lisent."""
        user = self.ctx.settings.user
        if bool(getattr(user, "verrou_distant_actif", False)) == self.distant_actif:
            return
        try:
            user = self.ctx.settings.update({"verrou_distant_actif": self.distant_actif})
            self.ctx.hub.publish("settings.updated", settings=user.model_dump())
        except Exception as exc:  # le reflet est une commodité d'affichage : l'état réel reste verrou.json
            log.warning("verrou : reflet du réglage non écrit (%s)", exc)

    def _publier_distant(self, message: str | None) -> None:
        try:
            self.ctx.hub.publish("verrou.distant", actif=self.distant_actif, message=message)
        except Exception as exc:  # pragma: no cover
            log.debug("verrou : publication (%s)", exc)

    def synchroniser_reglage(self) -> None:
        """Appelée à chaque settings.updated. Le réglage allumé active le verrouillage à distance ; éteint sans
        mot de passe (PATCH /api/settings le refuse déjà en 403 ; ceci couvre les autres chemins), il ne le
        désactive PAS : le reflet est rétabli et on dit pourquoi."""
        voulu = bool(getattr(self.ctx.settings.user, "verrou_distant_actif", False))
        if voulu == self.distant_actif or self.verrouille:
            return
        comptes = getattr(self.ctx, "comptes", None)
        if voulu or comptes is None or not comptes.configure:
            self.definir_distant(voulu)
            return
        self._journaliser("verrou_distant_desactivation_refusee", detail="réglage modifié sans mot de passe")
        self._refleter_reglage()
        self._publier_distant(DESACTIVER_EXIGE_MOT_DE_PASSE)

    # ------------------------------------------------------------------ vérification du code
    def _trop_d_echecs(self) -> bool:
        limite = time.time() - FENETRE_ESSAIS_S
        self._echecs_code = [t for t in self._echecs_code if t > limite]
        return len(self._echecs_code) >= ESSAIS_CODE_MAX

    def _noter_echecs(self, nombre: int = 1) -> None:
        self._echecs_code.extend([time.time()] * nombre)
        try:
            self._ecrire()
        except OSError as exc:  # pragma: no cover
            log.warning("verrou : échec de code non persisté (%s)", exc)

    def verifier_preuve(self, action: str, nonce: str, preuve: str, compter_echec: bool = True) -> str:
        """« ok », « refuse », « trop_de_tentatives », « rejouee » ou « code_a_redefinir ». Rien n'est journalisé."""
        with self._verrou:
            if not self.code_defini:
                return "refuse"
            if self.code_a_redefinir:
                return "code_a_redefinir"
            if self._trop_d_echecs():
                return "trop_de_tentatives"
            maintenant = time.time()
            for vieux in [n for n, t in self._nonces_vus.items() if t < maintenant - NONCE_AGE_MAX_S - NONCE_AVANCE_MAX_S]:
                self._nonces_vus.pop(vieux, None)
            cle = self._cle_preuve()
            if cle is None:
                return "code_a_redefinir"
            valide = (nonce_acceptable(nonce, maintenant) and isinstance(preuve, str)
                      and hmac.compare_digest(preuve_commande(cle, action, nonce), preuve))
            if not valide:
                if compter_echec:
                    self._noter_echecs()
                return "refuse"
            if nonce in self._nonces_vus:
                return "rejouee"
            self._nonces_vus[nonce] = maintenant
            self._echecs_code.clear()
            self._ecrire()
            return "ok"

    def verifier_code(self, code: str, compter_echec: bool = True) -> str:
        """« ok », « refuse » ou « trop_de_tentatives ». Le code n'est ni journalisé ni gardé.
        `compter_echec=False` : un échec n'est pas inscrit tout de suite (commande d'un lot différé)."""
        with self._verrou:
            if not self.code_defini:
                return "refuse"
            if self._trop_d_echecs():
                return "trop_de_tentatives"
            if code_conforme(self._code or {}, code):
                self._echecs_code.clear()
                return "ok"
            if compter_echec:
                self._noter_echecs()
            return "refuse"

    def _verifier_preuve_differee(self, action: str, nonce: str, preuve: str, lot: str, reste: int) -> str:
        """Commande livrée depuis la file du relais. Quiconque connaît le courriel peut y glisser des preuves
        bidon ; elles consommeraient les essais de l'ordinateur avant la bonne preuve du propriétaire. Les
        échecs d'un lot ne sont donc comptés qu'à sa clôture, et seulement si aucune preuve du lot n'était
        bonne. Un lot jamais clos (relais tombé) est compté après LOT_GARDE_S."""
        with self._verrou:
            limite = time.time() - LOT_GARDE_S
            for cle in [c for c, l in self._lots.items() if l["a"] < limite and c != lot]:
                self._clore_lot(cle)
            suivi = self._lots.setdefault(lot, {"valide": False, "echecs": 0, "a": time.time()})
            verdict = self.verifier_preuve(action, nonce, preuve, compter_echec=False)
            if verdict == "ok":
                suivi.update(valide=True, echecs=0)
            elif verdict == "refuse" and not suivi["valide"]:
                suivi["echecs"] += 1
            if reste <= 0:
                self._clore_lot(lot)
            return verdict

    def _clore_lot(self, lot: str) -> None:
        suivi = self._lots.pop(lot, None)
        if suivi and not suivi["valide"] and suivi["echecs"]:
            self._noter_echecs(suivi["echecs"])

    # ------------------------------------------------------------------ verrouiller
    async def verrouiller(self, raison: str = "local") -> dict:
        if not self._mot_de_passe_defini():
            raise RefusVerrou(SANS_MOT_DE_PASSE, 409)
        with self._verrou:
            deja = self.verrouille
            if not deja:
                self.verrouille = True
                self.depuis = maintenant_iso()
                self.raison = raison
                self._ecrire()
        if not deja:
            log.warning("IRIS verrouillée (%s)", raison)
            self._journaliser("verrouillage", detail=raison)
        self._publier()
        await self.couper_captures()
        return self.etat()

    async def couper_captures(self) -> None:
        """Arrête tout ce qui écoute, capte ou parle. Chaque arrêt est isolé : un service en panne n'empêche pas les autres."""
        ctx = self.ctx
        voice = getattr(ctx, "voice", None)
        if voice is not None and voice.running:
            try:
                await asyncio.to_thread(voice.stop, True)
            except Exception as exc:
                log.warning("verrou : arrêt de l'écoute en erreur (%s)", exc)
        tts = getattr(ctx, "tts", None)
        if tts is not None:
            try:
                tts.stop()
            except Exception:
                pass
        arrets: list[tuple[str, str, tuple]] = [
            ("sous_titres", "arreter_tout", ()),
            ("alertes", "arreter", ("verrouillage",)),
            ("ecoute_assistee", "arreter", ("verrouillage",)),
            ("interprete", "arreter", ("verrouillage",)),
            ("partage", "arreter", ()),
        ]
        for nom, methode, args in arrets:
            service = getattr(ctx, nom, None)
            fonction = getattr(service, methode, None) if service is not None else None
            if not callable(fonction) or (nom != "sous_titres" and not getattr(service, "actif", True)):
                continue
            try:
                await _appeler(fonction, *args)
            except Exception as exc:
                log.info("verrou : arrêt de %s (%s)", nom, exc)
        # Pas à pas et entraînement : leurs minuteurs continueraient d'annoncer à voix haute (« Repos terminé.
        # Série 4. ») sur un ordinateur verrouillé, et révéleraient l'activité du propriétaire.
        for nom in ("pas_a_pas", "entrainement"):
            service = getattr(ctx, nom, None)
            interrompre = getattr(service, "interrompre", None) if service is not None else None
            if not callable(interrompre):
                continue
            try:
                interrompre("verrouillage")
            except Exception as exc:
                log.info("verrou : arrêt de %s (%s)", nom, exc)
        enregistreur = getattr(ctx, "enregistreur", None)
        if enregistreur is not None and getattr(enregistreur, "actif", False):
            try:
                await asyncio.to_thread(enregistreur.arreter)
            except Exception as exc:
                log.info("verrou : arrêt de l'enregistrement (%s)", exc)
        cours = getattr(ctx, "cours", None)
        try:
            actif = cours.cours_actif() if cours is not None else None
            if actif:
                await asyncio.to_thread(cours.arreter, actif["id"], "verrouillage")
        except Exception as exc:
            log.info("verrou : arrêt du cours (%s)", exc)
        glasses = getattr(ctx, "glasses", None)
        if glasses is not None and getattr(glasses, "connected", False):
            try:
                await asyncio.wait_for(glasses.disconnect(), timeout=DELAI_LUNETTES_S)
            except Exception as exc:
                log.warning("verrou : lunettes non coupées (%s)", exc)

    async def surveiller(self, intervalle: float = 1.0) -> None:
        """Tant qu'IRIS est verrouillée, rien ne se rallume : ni l'écoute (démarrage automatique, chien de
        garde) ni les lunettes (reconnexion automatique). Ne lève jamais."""
        while True:
            try:
                if self.verrouille:
                    voice = getattr(self.ctx, "voice", None)
                    glasses = getattr(self.ctx, "glasses", None)
                    if (voice is not None and voice.running) or (glasses is not None and getattr(glasses, "connected", False)):
                        await self.couper_captures()
            except Exception as exc:  # pragma: no cover
                log.debug("verrou : surveillance (%s)", exc)
            await asyncio.sleep(intervalle)

    # ------------------------------------------------------------------ déverrouiller
    def deverrouiller(self, mot_de_passe: str) -> dict:
        comptes = getattr(self.ctx, "comptes", None)
        if comptes is None or not comptes.configure:
            raise RefusVerrou(SANS_MOT_DE_PASSE, 409)
        trop = getattr(comptes, "_trop_d_essais", None)
        if callable(trop) and trop():
            raise RefusVerrou("Trop de tentatives : réessayez dans quelques minutes.", 429)
        if not comptes.verifier(mot_de_passe or ""):
            self._journaliser("deverrouillage_refuse")
            raise RefusVerrou("Mot de passe incorrect.", 403)
        with self._verrou:
            etait = self.verrouille
            self.verrouille = False
            self.depuis = None
            self.raison = None
            self._ecrire()
        if etait:
            log.warning("IRIS déverrouillée avec le mot de passe du propriétaire")
            self._journaliser("deverrouillage")
        self._publier()
        return self.etat()

    def relancer_apres_deverrouillage(self) -> None:
        """Rend à l'écoute l'état que l'utilisateur a choisi (démarrage automatique), sans forcer."""
        user = self.ctx.settings.user
        voice = getattr(self.ctx, "voice", None)
        if voice is None or user.privacy_mode or not user.voice_autostart or getattr(voice, "muted", False):
            return
        try:
            voice.start()
        except Exception as exc:  # pragma: no cover
            log.info("verrou : écoute non relancée (%s)", exc)

    # ------------------------------------------------------------------ effacement
    def effacer_donnees(self) -> dict:
        """Efface les données personnelles d'IRIS sur cet ordinateur (bloquant : dans un fil).

        Renvoie ce qui a été effacé, et la liste des erreurs : un effacement partiel se dit comme tel."""
        ctx = self.ctx
        rapport: dict[str, Any] = {"erreurs": []}
        db = ctx.db
        try:
            existantes = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        except Exception as exc:
            existantes = set()
            rapport["erreurs"].append(f"base : {exc}")
        chat = getattr(ctx, "chat", None)
        if chat is not None and "conversations" in existantes:
            for ligne in db.query("SELECT id FROM conversations"):
                try:
                    chat.cancel(ligne["id"])
                except Exception:
                    pass
        for cle, table in TABLES_EFFACEES:
            if table not in existantes:
                continue
            try:
                rapport[cle] = max(0, db.execute(f"DELETE FROM {table}").rowcount)
            except Exception as exc:
                rapport["erreurs"].append(f"{cle} : {exc}")
        # Toute autre table (ajoutée après l'écriture de TABLES_EFFACEES) est vidée aussi, sauf la liste blanche.
        connues = {table for _, table in TABLES_EFFACEES}
        for table in sorted(existantes - connues - TABLES_CONSERVEES):
            if table.startswith("sqlite_") or not table.replace("_", "").isalnum():
                continue
            try:
                rapport[f"table_{table}"] = max(0, db.execute(f'DELETE FROM "{table}"').rowcount)
            except Exception as exc:
                rapport["erreurs"].append(f"{table} : {exc}")
        for fichier_ou_dossier, cle in (("captures", "captures"), ("recus", "images_recus")):
            chemin = Path(ctx.settings.data_dir) / fichier_ou_dossier
            rapport[cle] = self._vider_dossier(chemin, rapport["erreurs"])
        # Empreinte vocale et zones : par leurs services quand ils existent (ils retirent aussi leurs effets).
        verrou_vocal = getattr(ctx, "verrou_vocal", None)
        try:
            if verrou_vocal is not None:
                verrou_vocal.definir_consentement(False)
            else:
                for nom in ("empreinte-vocale.bin", "empreinte-vocale-consentement.json"):
                    (Path(ctx.settings.data_dir) / nom).unlink(missing_ok=True)
            rapport["empreinte_vocale"] = True
        except Exception as exc:
            rapport["erreurs"].append(f"empreinte vocale : {exc}")
        try:
            zones = getattr(ctx, "zones", None)
            if zones is not None:
                rapport["zones"] = zones.effacer_tout()
            else:
                rapport["zones"] = len(ctx.settings.user.zones_sans_memoire or [])
                ctx.settings.update({"zones_sans_memoire": []})
        except Exception as exc:
            rapport["erreurs"].append(f"zones : {exc}")
        rapport.update(self._effacer_jetons(rapport["erreurs"]))
        try:
            glasses = getattr(ctx, "glasses", None)
            if glasses is not None:
                glasses.forget()
            else:
                ctx.settings.update({"glasses": {"address": "", "name": "", "auto_connect": False}})
            rapport["lunettes_oubliees"] = True
        except Exception as exc:
            rapport["erreurs"].append(f"lunettes : {exc}")
        # Copies de secours des réglages (zones, comptes web, lunettes), état du mode invité, association des
        # téléphones aux lunettes : hors de la base, mais personnels.
        for nom in FICHIERS_EFFACES:
            try:
                (Path(ctx.settings.data_dir) / nom).unlink(missing_ok=True)
            except OSError as exc:
                rapport["erreurs"].append(f"{nom} : {exc}")
        try:
            rapport["secrets_env"] = retirer_secrets_env(ctx.settings.data_dir)
        except Exception as exc:
            rapport["erreurs"].append(f".env : {exc}")
        rapport["journal_technique"] = purger_journal_technique(None)
        # Registre de confidentialité en DERNIER (les étapes précédentes y écrivent) : ses détails reprennent
        # des extraits de messages envoyés et de requêtes. Effacer ces détails ligne à ligne casserait sa chaîne
        # d'empreintes ; on le remet à zéro, et l'entrée « effacement_a_distance » écrite juste après en est la tête.
        if "privacy_events" in existantes:
            try:
                rapport["registre_confidentialite"] = max(0, db.execute("DELETE FROM privacy_events").rowcount)
            except Exception as exc:
                rapport["erreurs"].append(f"registre de confidentialité : {exc}")
        try:  # compacter : les pages libérées ne gardent pas les anciennes lignes
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("VACUUM")
        except Exception as exc:
            rapport["erreurs"].append(f"compactage : {exc}")
        try:
            user = ctx.settings.user
            ctx.hub.publish("settings.updated", settings=user.model_dump())
        except Exception:  # pragma: no cover
            pass
        self._journaliser("effacement_a_distance", detail=f"{len(rapport['erreurs'])} erreur(s)")
        return rapport

    @staticmethod
    def _vider_dossier(dossier: Path, erreurs: list[str]) -> int:
        if not dossier.exists():
            return 0
        supprimes = 0
        for element in sorted(dossier.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                if element.is_dir():
                    element.rmdir()
                else:
                    element.unlink()
                    supprimes += 1
            except OSError as exc:
                erreurs.append(f"{element.name} : {exc}")
        return supprimes

    def _effacer_jetons(self, erreurs: list[str]) -> dict:
        ctx = self.ctx
        rapport: dict[str, Any] = {}
        comptes = getattr(ctx, "comptes", None)
        try:
            if comptes is not None:
                # Tous les téléphones connectés doivent se reconnecter ; le motif permet à un téléphone qui
                # n'a pas vu l'événement (app en arrière-plan) d'apprendre l'effacement à sa réouverture.
                comptes.revoquer_tout(motif="effacement")
            rapport["sessions_revoquees"] = True
        except Exception as exc:
            erreurs.append(f"sessions : {exc}")
        dossier = Path(ctx.settings.data_dir)
        for nom in ("telecommande-pairing", "remote-token"):
            try:
                (dossier / nom).unlink(missing_ok=True)
            except OSError as exc:
                erreurs.append(f"{nom} : {exc}")
        telecommande = getattr(ctx, "telecommande", None)
        if telecommande is not None:
            telecommande._pairing = ""  # un nouveau code d'appairage sera généré à la prochaine connexion
        coffre = getattr(ctx, "secrets", None)
        cles = 0
        if coffre is not None:
            user = ctx.settings.user
            # Le jeton d'appareil « vela » reste : c'est lui qui garde l'ordinateur verrouillable à distance.
            agents = [a for a in (getattr(user, "agents", {}) or {}) if a != "vela"]
            for nom in agents + list(COFFRE_CLES):
                try:
                    if coffre.get_api_key(nom):
                        coffre.delete_api_key(nom)
                        cles += 1
                except Exception as exc:
                    erreurs.append(f"clé {nom} : {exc}")
            sites = list((getattr(user, "sites", {}) or {}).keys())
            # Les identifiants importés du navigateur ne sont pas dans le réglage `sites` : le coffre les liste.
            lister = getattr(coffre, "sites_enregistres", None)
            try:
                importes = list(lister()) if callable(lister) else []
            except Exception as exc:
                importes = []
                erreurs.append(f"liste des identifiants : {exc}")
            for nom in list(dict.fromkeys(sites + importes + list(COFFRE_IDENTIFIANTS))):
                try:
                    if coffre.get_site(nom):
                        coffre.delete_site(nom)
                        cles += 1
                except Exception as exc:
                    erreurs.append(f"identifiants {nom} : {exc}")
            try:
                if sites:
                    ctx.settings.update({"sites": {}})
            except Exception as exc:
                erreurs.append(f"comptes web : {exc}")
        rapport["identifiants_supprimes"] = cles
        web = getattr(ctx, "web", None)
        profil = getattr(web, "profile_dir", None)
        if profil is not None:
            try:
                web.close()
            except Exception:
                pass
            rapport["profil_navigateur"] = self._vider_dossier(Path(profil), erreurs)
        return rapport

    async def effacer(self) -> dict:
        """Coupe les captures, efface, puis verrouille (si un mot de passe existe)."""
        await self.couper_captures()
        rapport = await asyncio.to_thread(self.effacer_donnees)
        verrouillee = False
        if self._mot_de_passe_defini():
            await self.verrouiller("effacement")
            verrouillee = True
        return {"efface": rapport, "verrouille": verrouillee}

    # ------------------------------------------------------------------ commande venue du relais
    async def commande_distante(self, action: str, preuve: str = "", nonce: str = "", defi_page: str = "",
                                differee: bool = False, lot: str | None = None, reste: int | None = None) -> dict:
        """Traite {action, nonce, preuve, defi_page} reçu par la télécommande. Ne lève pas : renvoie
        {ok, etat, message} et, quand la preuve est bonne, `confirmation` (vérifiée par la page).
        `differee`, `lot`, `reste` : commande livrée depuis la file du relais (voir _verifier_preuve_differee)."""
        if not self.distant_actif:
            return {"ok": False, "etat": "desactive",
                    "message": "Le verrouillage à distance est désactivé sur cet ordinateur."}
        if not self.code_defini:
            return {"ok": False, "etat": "sans_code",
                    "message": "Aucun code de secours n'est défini sur cet ordinateur."}
        if action not in ("verrouiller", "effacer"):
            return {"ok": False, "etat": "action_inconnue", "message": "Action inconnue."}
        if differee and lot and isinstance(reste, int) and not isinstance(reste, bool):
            verdict = self._verifier_preuve_differee(action, nonce, preuve, str(lot)[:64], reste)
        else:
            verdict = self.verifier_preuve(action, nonce, preuve)
        if verdict == "code_a_redefinir":
            return {"ok": False, "etat": "code_a_redefinir", "message": CODE_A_REDEFINIR}
        if verdict == "trop_de_tentatives":
            self._journaliser("verrou_distant_refuse", detail="trop de tentatives")
            return {"ok": False, "etat": "trop_de_tentatives",
                    "message": "Trop de codes erronés : l'ordinateur refuse pendant 15 minutes."}
        if verdict == "rejouee":
            self._journaliser("verrou_distant_refuse", detail="commande rejouée")
            return {"ok": False, "etat": "rejouee",
                    "message": "Cette commande a déjà été reçue : elle n'est pas exécutée deux fois."}
        if verdict != "ok":
            self._journaliser("verrou_distant_refuse", detail="code erroné")
            return {"ok": False, "etat": "code_refuse", "message": "Code de secours incorrect."}
        cle = self._cle_preuve()

        def confirmer(reponse: dict) -> dict:
            if cle is not None and isinstance(defi_page, str) and 16 <= len(defi_page) <= 64:
                reponse["confirmation"] = confirmation_resultat(cle, reponse["etat"], nonce, defi_page)
            return reponse

        try:
            if action == "verrouiller":
                await self.verrouiller("distance")
                return confirmer({"ok": True, "etat": "verrouille", "message": "L'ordinateur est verrouillé."})
            resultat = await self.effacer()
            erreurs = resultat["efface"].get("erreurs") or []
            message = "Les données d'IRIS ont été effacées sur l'ordinateur"
            message += " et il est verrouillé." if resultat["verrouille"] else (
                ". Aucun mot de passe n'étant défini, il n'a pas pu être verrouillé.")
            if erreurs:
                message += f" Effacement incomplet : {len(erreurs)} élément(s) n'ont pas pu être supprimés."
            return confirmer({"ok": True, "etat": "efface_partiel" if erreurs else "efface", "message": message,
                              "verrouille": resultat["verrouille"], "erreurs": len(erreurs)})
        except RefusVerrou as exc:
            return {"ok": False, "etat": "sans_mot_de_passe" if exc.code == 409 else "refuse", "message": exc.message}
        except Exception as exc:
            log.warning("verrou : commande distante en erreur (%s)", exc)
            return {"ok": False, "etat": "erreur", "message": "L'ordinateur n'a pas pu exécuter la commande."}
