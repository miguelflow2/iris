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

    def revoquer_tout(self) -> None:
        """Déconnecte tous les appareils, sans changer le mot de passe."""
        d = self._lire()
        if d:
            d["secret_session"] = _b64(secrets.token_bytes(32))
            self._ecrire(d)
            log.info("toutes les sessions ont été révoquées")
