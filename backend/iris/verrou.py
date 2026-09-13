"""Verrouillage d'IRIS, sur place ou à distance, et effacement à distance (interface I, 2026-09-13).

Le cas d'usage est la perte ou le vol de l'ordinateur. Trois gestes :
- VERROUILLER : l'écoute s'arrête, les lunettes sont coupées, les services qui captent (sous-titres,
  alertes, écoute assistée, enregistrement, cours, interprète, partage) s'arrêtent, et TOUTES les routes
  protégées répondent 401 (main.raison_de_refus lit `ctx.verrou.verrouille`). L'état est écrit sur le
  disque : un redémarrage ne déverrouille pas.
- DÉVERROUILLER : seulement avec le mot de passe du propriétaire (comptes.py), avec le même
  ralentissement après plusieurs échecs. Sans mot de passe défini, on refuse de verrouiller : un verrou
  sans clé enfermerait le propriétaire dehors.
- EFFACER (à distance) : mémoire, rappels liés aux personnes, journal d'écoute, cours, reçus,
  conversations, tâches, rappels, veilles, captures (photos et audio), empreinte vocale, zones sans
  mémoire, jetons (sessions des téléphones, code d'appairage, clés d'API et identifiants enregistrés,
  profil du navigateur piloté), lunettes oubliées. Le compte et le mot de passe restent, pour pouvoir
  déverrouiller ; le jeton d'appareil du relais reste aussi, pour que l'ordinateur reste verrouillable.

Code de secours : le relais ne connaît pas le mot de passe (il ne doit jamais le voir). La page
publique /verrou demande donc un CODE DE SECOURS choisi ici, haché localement (scrypt, sel aléatoire ;
PBKDF2-SHA256 si scrypt manque) : l'ordinateur vérifie le code qu'on lui transmet, le relais ne peut
rien vérifier ni rejouer hors de ce transit.

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
  verrou qu'à l'ouverture) : l'événement verrou.etat est publié, mais la fermeture est demandée à main.py.
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
DELAI_LUNETTES_S = 10.0

VERROUILLEE = "IRIS est verrouillée. Déverrouillez-la avec le mot de passe du propriétaire."
SANS_MOT_DE_PASSE = (
    "Choisissez d'abord un mot de passe (Profil › Compte et sécurité) : sans lui, personne ne pourrait "
    "déverrouiller IRIS."
)
LIMITE = (
    "Le verrouillage à distance n'agit que si l'ordinateur est allumé et connecté. Il ne remplace pas le "
    "chiffrement du disque (BitLocker) contre le vol."
)

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
)
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
        if self.verrouille:
            log.warning("IRIS démarre verrouillée (%s, depuis %s)", self.raison, self.depuis)

    # ------------------------------------------------------------------ persistance
    def _lire(self) -> dict:
        try:
            return json.loads(self.fichier.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _ecrire(self) -> None:
        contenu = {"verrouille": self.verrouille, "depuis": self.depuis, "raison": self.raison, "code": self._code}
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
        return bool(self._code and self._code.get("hash"))

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
            "actif_distance": bool(getattr(user, "verrou_distant_actif", False)),
            "code_defini": self.code_defini,
            "mot_de_passe_defini": self._mot_de_passe_defini(),
            "courriel_defini": bool((getattr(user, "licence_email", "") or "").strip()),
            "relais_connecte": bool(getattr(telecommande, "connecte", False)),
            "limite": LIMITE,
        }

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
        with self._verrou:
            self._code = hacher_code(code)
            self._echecs_code.clear()
            self._ecrire()
        self._journaliser("verrou_code_defini")
        return self.etat()

    def _trop_d_echecs(self) -> bool:
        limite = time.time() - FENETRE_ESSAIS_S
        self._echecs_code = [t for t in self._echecs_code if t > limite]
        return len(self._echecs_code) >= ESSAIS_CODE_MAX

    def verifier_code(self, code: str) -> str:
        """« ok », « refuse » ou « trop_de_tentatives ». Le code n'est ni journalisé ni gardé."""
        with self._verrou:
            if not self.code_defini:
                return "refuse"
            if self._trop_d_echecs():
                return "trop_de_tentatives"
            if code_conforme(self._code or {}, code):
                self._echecs_code.clear()
                return "ok"
            self._echecs_code.append(time.time())
            return "refuse"

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
        try:  # une copie mise de côté des anciens réglages garderait les zones et les comptes web
            (Path(ctx.settings.data_dir) / "settings.corrupt.json").unlink(missing_ok=True)
        except OSError as exc:
            rapport["erreurs"].append(f"réglages mis de côté : {exc}")
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
                comptes.revoquer_tout()  # tous les téléphones connectés doivent se reconnecter
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
            for nom in sites + list(COFFRE_IDENTIFIANTS):
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
    async def commande_distante(self, action: str, code: str) -> dict:
        """Traite {action, code} reçu par la télécommande. Ne lève pas : renvoie {ok, etat, message}."""
        if not getattr(self.ctx.settings.user, "verrou_distant_actif", False):
            return {"ok": False, "etat": "desactive",
                    "message": "Le verrouillage à distance est désactivé sur cet ordinateur."}
        if not self.code_defini:
            return {"ok": False, "etat": "sans_code",
                    "message": "Aucun code de secours n'est défini sur cet ordinateur."}
        if action not in ("verrouiller", "effacer"):
            return {"ok": False, "etat": "action_inconnue", "message": "Action inconnue."}
        verdict = self.verifier_code(code)
        if verdict == "trop_de_tentatives":
            self._journaliser("verrou_distant_refuse", detail="trop de tentatives")
            return {"ok": False, "etat": "trop_de_tentatives",
                    "message": "Trop de codes erronés : l'ordinateur refuse pendant 15 minutes."}
        if verdict != "ok":
            self._journaliser("verrou_distant_refuse", detail="code erroné")
            return {"ok": False, "etat": "code_refuse", "message": "Code de secours incorrect."}
        try:
            if action == "verrouiller":
                await self.verrouiller("distance")
                return {"ok": True, "etat": "verrouille", "message": "L'ordinateur est verrouillé."}
            resultat = await self.effacer()
            erreurs = resultat["efface"].get("erreurs") or []
            message = "Les données d'IRIS ont été effacées sur l'ordinateur"
            message += " et il est verrouillé." if resultat["verrouille"] else (
                ". Aucun mot de passe n'étant défini, il n'a pas pu être verrouillé.")
            if erreurs:
                message += f" Effacement incomplet : {len(erreurs)} élément(s) n'ont pas pu être supprimés."
            return {"ok": True, "etat": "efface_partiel" if erreurs else "efface", "message": message,
                    "verrouille": resultat["verrouille"], "erreurs": len(erreurs)}
        except RefusVerrou as exc:
            return {"ok": False, "etat": "sans_mot_de_passe" if exc.code == 409 else "refuse", "message": exc.message}
        except Exception as exc:
            log.warning("verrou : commande distante en erreur (%s)", exc)
            return {"ok": False, "etat": "erreur", "message": "L'ordinateur n'a pas pu exécuter la commande."}
