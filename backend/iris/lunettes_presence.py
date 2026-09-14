"""Présence des lunettes VELA : LA règle commerciale d'IRIS, en un seul endroit (2026-09-13).

VELA vend des lunettes intelligentes ; IRIS est la technologie qu'elles contiennent. Si IRIS faisait
tout sans elles, plus personne n'aurait de raison d'acheter la monture (Miguel, 2026-09-04, renforcé
le 2026-09-13 : « tout doit être lié aux lunettes, même sur le téléphone »). Ce module répond donc à
une seule question, pour toutes les fonctions : les lunettes sont-elles là ?

Trois preuves valent :
1. l'ordinateur les voit (lien Bluetooth basse énergie ou micro des lunettes : voir
   VoiceListener.lunettes_presentes, qui a appris le 5 septembre 2026 à ne pas dépendre du seul
   canal basse énergie) ;
2. l'app téléphone appairée aux lunettes l'atteste, et l'attestation est récente (dehors, les
   lunettes sont connectées au téléphone, pas au PC) ;
3. le verrou est levé par le propriétaire (require_glasses faux) ou le mode démonstration est actif
   (activé par un accès propriétaire caché, jamais depuis un écran client).

Ce qui reste accessible SANS lunettes n'est pas décidé ici mais par les appelants, et doit toujours
se justifier : données de l'utilisateur (Loi 25 : consulter, exporter, effacer), compte, abonnement,
confidentialité, sécurité (verrouillage à distance : il sert justement quand les lunettes sont
perdues), appairage et achat des lunettes. Le chat écrit, lui, a droit à un APERÇU limité
(APERCU_MESSAGES) : de quoi donner envie, pas de quoi remplacer les lunettes.

Limite dite telle quelle : c'est un verrou LOGICIEL. Il protège une décision commerciale, pas un
secret ; une personne déterminée qui modifie le programme peut le contourner.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

log = logging.getLogger("iris.lunettes_presence")

APERCU_MESSAGES = 10  # messages écrits permis sans lunettes, pour toute la vie de l'installation
DUREE_ATTESTATION_S = 150  # l'app téléphone réatteste toutes les 60 s ; au-delà, on ne la croit plus
URL_ACHAT = "https://velaglass.ca/lunettes.html"
MESSAGE_REQUISES = "Cette fonction marche avec les lunettes VELA. Connecte tes lunettes pour l'utiliser."
MESSAGE_VOIX = "Connecte tes lunettes VELA pour parler à IRIS."
MESSAGE_APERCU_EPUISE = (
    "Ton aperçu d'IRIS par écrit est terminé. IRIS s'utilise avec les lunettes VELA : "
    "connecte tes lunettes, ou découvre-les sur velaglass.ca."
)


class LunettesRequises(HTTPException):
    """Refus d'une fonction faute de lunettes. 428 : la condition préalable (les lunettes) manque."""

    def __init__(self, fonction: str, message: str = MESSAGE_REQUISES):
        super().__init__(
            428,
            detail={"code": "lunettes_requises", "fonction": fonction, "message": message, "acheter_url": URL_ACHAT},
        )
        self.fonction = fonction
        self.message = message
        self.phrase = message


def _compact(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return "".join(c for c in sans_accents.lower() if c.isalnum())


class PresenceLunettes:
    def __init__(
        self,
        settings: Any,
        data_dir: Path | str,
        voice: Any = None,
        glasses: Any = None,
        hub: Any = None,
        horloge: Callable[[], float] = time.time,
    ):
        self.settings = settings
        self.voice = voice
        self.glasses = glasses
        self.hub = hub
        self.horloge = horloge
        self._fichier_apercu = Path(data_dir) / "apercu-chat.json"
        self._verrou = threading.Lock()
        self._attestation: dict | None = None

    # ------------------------------------------------------------------ présence
    def verrou_actif(self) -> bool:
        u = self.settings.user
        return bool(u.require_glasses) and not bool(u.demo_sans_lunettes)

    def _preuve_ordinateur(self) -> bool:
        try:
            if self.voice is not None and hasattr(self.voice, "lunettes_presentes"):
                return bool(self.voice.lunettes_presentes())
            if self.glasses is not None:
                return bool(getattr(self.glasses, "connected", False))
        except Exception as exc:  # la présence ne doit jamais faire planter une demande
            log.warning("preuve de présence des lunettes illisible : %s", exc)
        return False

    def _attestation_valide(self) -> dict | None:
        att = self._attestation
        if att and self.horloge() - att["a"] <= DUREE_ATTESTATION_S:
            return att
        return None

    def source(self) -> str | None:
        """D'où vient la présence : desactive, demo, pc, telephone — ou None si absentes."""
        u = self.settings.user
        if not u.require_glasses:
            return "desactive"
        if u.demo_sans_lunettes:
            return "demo"
        if self._preuve_ordinateur():
            return "pc"
        if self._attestation_valide():
            return "telephone"
        return None

    def presentes(self) -> bool:
        return self.source() is not None

    def exiger(self, fonction: str) -> None:
        """Lève LunettesRequises (428) si les lunettes manquent. À appeler en tête de toute fonction
        qui capte (voir, écouter, enregistrer) ou qui agit."""
        if not self.presentes():
            raise LunettesRequises(fonction)

    # ------------------------------------------------------------------ attestation du téléphone
    def attester(self, nom: str, identifiant: str = "", batterie: int | None = None, source: str = "telephone") -> dict:
        """L'app téléphone dit « les lunettes sont connectées à moi ». Refusé si ce ne sont pas les
        lunettes associées à cet IRIS (quand une paire est mémorisée)."""
        nom = " ".join(str(nom or "").split())
        if not nom:
            raise HTTPException(422, "Nom des lunettes manquant.")
        connues = (self.settings.user.glasses.name or "").strip()
        if connues:
            tete = _compact(connues.split()[0]) if connues.split() else ""
            if _compact(connues) not in _compact(nom) and not (len(tete) >= 3 and tete in _compact(nom)):
                raise HTTPException(403, "Ces lunettes ne sont pas celles associées à cet IRIS.")
        self._attestation = {
            "nom": nom[:80],
            "identifiant": str(identifiant or "")[:120],
            "batterie": batterie if isinstance(batterie, int) and 0 <= batterie <= 100 else None,
            "source": source if source in ("telephone", "iphone", "android") else "telephone",
            "a": self.horloge(),
        }
        self._publier()
        return self.etat()

    def retirer_attestation(self) -> dict:
        self._attestation = None
        self._publier()
        return self.etat()

    # ------------------------------------------------------------------ aperçu du chat écrit
    def _lire_apercu(self) -> int:
        try:
            return max(0, int(json.loads(self._fichier_apercu.read_text(encoding="utf-8")).get("utilises", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    def apercu_restant(self) -> int:
        return max(0, APERCU_MESSAGES - self._lire_apercu())

    def consommer_apercu(self) -> bool:
        """Consomme un message de l'aperçu ; False s'il n'en reste plus."""
        with self._verrou:
            utilises = self._lire_apercu()
            if utilises >= APERCU_MESSAGES:
                return False
            try:
                self._fichier_apercu.parent.mkdir(parents=True, exist_ok=True)
                self._fichier_apercu.write_text(json.dumps({"utilises": utilises + 1}), encoding="utf-8")
            except OSError as exc:
                # Sans écriture possible, on ne donne pas d'aperçu illimité : on refuse.
                log.warning("aperçu du chat non enregistrable : %s", exc)
                return False
        return True

    # ------------------------------------------------------------------ état
    def etat(self) -> dict:
        att = self._attestation_valide()
        return {
            "presentes": self.presentes(),
            "source": self.source(),
            "verrou_actif": self.verrou_actif(),
            "nom": (att or {}).get("nom") or (self.settings.user.glasses.name or None),
            "attestation_age_s": round(self.horloge() - att["a"], 1) if att else None,
            "apercu_restant": self.apercu_restant(),
            "apercu_total": APERCU_MESSAGES,
            "acheter_url": URL_ACHAT,
            "limite": "Verrou logiciel : il s'applique à l'application IRIS, pas au matériel.",
        }

    def _publier(self) -> None:
        if self.hub is not None:
            try:
                self.hub.publish("lunettes.presence", **self.etat())
            except Exception:  # pragma: no cover
                pass
