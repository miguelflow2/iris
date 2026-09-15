"""Comptes et authentification : protéger l'accès à IRIS depuis le téléphone.

Pourquoi il en faut un. Jusqu'ici, l'unique secret était le jeton contenu dans l'adresse. Une
adresse se retrouve dans l'historique du navigateur, dans une capture d'écran, dans un message
envoyé à soi-même. Or IRIS exécute des commandes sur l'ordinateur : ce n'est pas un secret
qu'on laisse traîner dans une barre d'adresse.

Le principe retenu : un mot de passe choisi par le propriétaire, jamais stocké en clair, et une
session signée qui expire. L'adresse seule ne suffit plus.

Ce que ce module n'est pas : un service de comptes en ligne. IRIS vit sur l'appareil de son
propriétaire ; il n'y a qu'un compte, le sien. L'identité commerciale (abonnement) est gérée
ailleurs, par le courriel d'achat et la clé de licence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path

log = logging.getLogger("iris.comptes")

ITERATIONS = 240_000  # PBKDF2-SHA256 : coût volontairement élevé, on ne vérifie qu'à la connexion
DUREE_SESSION = 30 * 24 * 3600  # 30 jours : on ne veut pas retaper son mot de passe chaque matin
MIN_LONGUEUR = 8
ESSAIS_MAX = 8  # au-delà, on ralentit fortement : un mot de passe local doit résister à la force brute
FENETRE_ESSAIS = 900  # 15 minutes
# Révocations motivées (effacements à distance) gardées au plus : un effacement est rare ; la borne évite
# seulement qu'un fichier grossisse sans fin.
REVOCATIONS_GARDEES = 20


def _b64(donnees: bytes) -> str:
    return urlsafe_b64encode(donnees).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def empreinte(mot_de_passe: str, sel: bytes) -> bytes:
    """PBKDF2-SHA256. Le mot de passe n'est jamais écrit, seulement cette empreinte."""
    return hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, ITERATIONS)


class Comptes:
    """Le compte du propriétaire de cet IRIS, et les sessions qu'il ouvre depuis ses appareils."""

    def __init__(self, data_dir: Path):
        self.fichier = Path(data_dir) / "compte.json"
        self._essais: list[float] = []

    # ------------------------------------------------------------------ état
    def _lire(self) -> dict:
        try:
            return json.loads(self.fichier.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _ecrire(self, donnees: dict) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        self.fichier.write_text(json.dumps(donnees, indent=2), encoding="utf-8")
        try:  # lisible par le seul propriétaire, quand le système le permet
            self.fichier.chmod(0o600)
        except Exception:
            pass

    @property
    def configure(self) -> bool:
        """Un mot de passe a-t-il déjà été choisi ?"""
        return bool(self._lire().get("hash"))

    def info(self) -> dict:
        d = self._lire()
        return {
            "configure": bool(d.get("hash")),
            "nom": d.get("nom", ""),
            "cree_le": d.get("cree_le", ""),
            "modifie_le": d.get("modifie_le", ""),
        }

    # ------------------------------------------------------------------ création et changement
    def creer(self, mot_de_passe: str, nom: str = "") -> dict:
        """Premier mot de passe. Refuse d'écraser un compte existant : passer par `changer`."""
        if self.configure:
            raise ValueError("un compte existe déjà : utilisez le changement de mot de passe")
        return self._poser(mot_de_passe, nom)

    def changer(self, ancien: str, nouveau: str) -> dict:
        """Change le mot de passe. L'ancien est exigé : sans cela, quiconque a la page pourrait
        se verrouiller le propriétaire dehors."""
        if self.configure and not self.verifier(ancien):
            raise ValueError("ancien mot de passe incorrect")
        nom = self._lire().get("nom", "")
        resultat = self._poser(nouveau, nom)
        log.info("mot de passe changé ; toutes les sessions ouvertes sont révoquées")
        return resultat

    def _poser(self, mot_de_passe: str, nom: str) -> dict:
        mot_de_passe = (mot_de_passe or "").strip()
        if len(mot_de_passe) < MIN_LONGUEUR:
            raise ValueError(f"le mot de passe doit faire au moins {MIN_LONGUEUR} caractères")
        sel = secrets.token_bytes(16)
        maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
        ancien = self._lire()
        self._ecrire(
            {
                "nom": nom or ancien.get("nom", ""),
                "sel": _b64(sel),
                "hash": _b64(empreinte(mot_de_passe, sel)),
                # change à chaque mot de passe : invalide toutes les sessions déjà émises
                "secret_session": _b64(secrets.token_bytes(32)),
                "cree_le": ancien.get("cree_le") or maintenant,
                "modifie_le": maintenant,
                # Un changement de mot de passe (souvent fait juste après la perte d'un téléphone) ne doit pas
                # effacer la trace d'un effacement à distance : le téléphone perdu doit encore l'apprendre.
                "revocations_motivees": self._revocations_valables(ancien),
            }
        )
        self._essais.clear()
        return self.info()

    # ------------------------------------------------------------------ vérification
    def _trop_d_essais(self) -> bool:
        limite = time.time() - FENETRE_ESSAIS
        self._essais = [t for t in self._essais if t > limite]
        return len(self._essais) >= ESSAIS_MAX

    def verifier(self, mot_de_passe: str) -> bool:
        """Compare en temps constant. Ralentit après plusieurs échecs rapprochés."""
        d = self._lire()
        if not d.get("hash"):
            return False
        if self._trop_d_essais():
            log.warning("trop de tentatives de connexion : refus temporaire")
            return False
        attendu = _debase64(d["hash"])
        calcule = empreinte(mot_de_passe or "", _debase64(d["sel"]))
        if hmac.compare_digest(attendu, calcule):
            self._essais.clear()
            return True
        self._essais.append(time.time())
        return False

    # ------------------------------------------------------------------ sessions
    def ouvrir_session(self, duree: int = DUREE_SESSION) -> str:
        """Jeton de session signé : identifiant, échéance, signature. Rien de secret dedans."""
        d = self._lire()
        secret = _debase64(d.get("secret_session", ""))
        if not secret:
            raise ValueError("aucun compte configuré")
        corps = f"{secrets.token_urlsafe(9)}.{int(time.time() + duree)}"
        signature = hmac.new(secret, corps.encode(), hashlib.sha256).digest()[:24]
        return f"{corps}.{_b64(signature)}"

    def session_valide(self, jeton: str) -> bool:
        d = self._lire()
        secret = _debase64(d.get("secret_session", ""))
        if not secret or not jeton:
            return False
        try:
            identifiant, echeance, signature = jeton.rsplit(".", 2)
            corps = f"{identifiant}.{echeance}"
        except ValueError:
            return False
        attendue = hmac.new(secret, corps.encode(), hashlib.sha256).digest()[:24]
        if not hmac.compare_digest(_b64(attendue), signature):
            return False
        try:
            return int(echeance) > time.time()
        except ValueError:
            return False

    def revoquer_tout(self, motif: str = "") -> None:
        """Déconnecte tous les appareils, sans changer le mot de passe.

        `motif` (« effacement » pour l'effacement à distance) est gardé avec l'ANCIEN secret de session, dans une
        LISTE : un téléphone perdu, en arrière-plan au moment de l'effacement, n'a pas vu l'événement verrou.etat ;
        à sa réouverture, sa session refusée doit pouvoir lui dire POURQUOI, pour qu'il retire les copies gardées
        sur lui. Jusqu'au 2026-09-14, seul le dernier motif était gardé : le geste naturel du propriétaire après
        la perte, « Déconnecter tous les appareils » (révocation sans motif), écrasait la trace et le téléphone
        perdu gardait ses cours lisibles. Une révocation sans motif n'efface donc plus rien de la liste ; chaque
        entrée vit jusqu'à l'échéance maximale des sessions émises sous son secret. Seul un jeton réellement émis
        (signature valide sous un secret révoqué) l'apprend : un jeton inventé reçoit le refus ordinaire."""
        d = self._lire()
        if d:
            revocations = self._revocations_valables(d)
            if motif:
                revocations.append({
                    "secret": d.get("secret_session", ""),
                    "motif": motif,
                    # une session émise sous ce secret expire au plus tard DUREE_SESSION après sa révocation
                    "jusqua": int(time.time() + DUREE_SESSION),
                })
            d["revocations_motivees"] = revocations[-REVOCATIONS_GARDEES:]
            d.pop("secret_session_revoque", None)
            d.pop("motif_revocation", None)
            d["secret_session"] = _b64(secrets.token_bytes(32))
            self._ecrire(d)
            log.info("toutes les sessions ont été révoquées")

    @staticmethod
    def _revocations_valables(d: dict) -> list[dict]:
        """Les révocations motivées encore utiles (sessions émises sous leur secret pas toutes expirées).
        Reprend l'ancien format à une seule entrée (secret_session_revoque + motif_revocation) sans le perdre."""
        maintenant = time.time()
        entrees = [e for e in (d.get("revocations_motivees") or []) if isinstance(e, dict)]
        if d.get("secret_session_revoque") and d.get("motif_revocation"):
            entrees.append({"secret": d["secret_session_revoque"], "motif": d["motif_revocation"],
                            "jusqua": int(maintenant + DUREE_SESSION)})
        return [e for e in entrees if e.get("secret") and e.get("motif") and float(e.get("jusqua") or 0) > maintenant]

    def motif_revocation(self, jeton: str) -> str | None:
        """Le motif de la révocation motivée (effacement) sous laquelle ce jeton avait été émis, sinon None.
        Toutes les révocations motivées encore utiles sont regardées, pas seulement la dernière. L'échéance du
        jeton n'est pas regardée : une session expirée entre-temps a tout de même existé sur cet appareil."""
        if not jeton:
            return None
        try:
            identifiant, echeance, signature = jeton.rsplit(".", 2)
        except (ValueError, TypeError):
            return None
        corps = f"{identifiant}.{echeance}".encode()
        for entree in reversed(self._revocations_valables(self._lire())):
            try:
                attendue = hmac.new(_debase64(entree["secret"]), corps, hashlib.sha256).digest()[:24]
            except (ValueError, TypeError):
                continue
            if hmac.compare_digest(_b64(attendue), signature):
                return entree["motif"]
        return None
