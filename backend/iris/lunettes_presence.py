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

Deux présences, pas une (constat du 2026-09-14). Des lunettes attestées par le TÉLÉPHONE sont sur le
nez de quelqu'un qui est dehors : l'ordinateur resté à la maison ne doit alors ouvrir ni son micro, ni
son écran, ni sa caméra (il écouterait la maison, où son propriétaire n'est pas, et un « Dis-moi Iris »
prononcé par un tiers le piloterait). D'où :
- presentes() : toutes les preuves, pour ce dont la donnée vient du téléphone (image fournie,
  interprète par texte, chat, reçu en photo) ;
- presentes_pour_capture_pc() : les lunettes vues PAR L'ORDINATEUR (ou verrou levé, démonstration),
  pour tout ce qui ouvre le micro, l'écran ou la caméra du PC. exiger_capture_pc() refuse en 409 avec
  la raison quand les lunettes ne sont attestées que par le téléphone.

Attestation du téléphone (constat du 2026-09-14) : elle n'est acceptée que pour des lunettes déjà
connectées une première fois à CET ordinateur (nom retenu par une vraie connexion Bluetooth), avec le
nom EXACT, et depuis un appareil associé (identifiant retenu à la première attestation ; un autre
appareil s'associe avec le mot de passe du propriétaire). Sans paire connue de l'ordinateur : 409.

Limite dite telle quelle : c'est un verrou LOGICIEL. Il protège une décision commerciale, pas un
secret ; une personne déterminée qui modifie le programme peut le contourner. L'identifiant Bluetooth
envoyé par le téléphone n'est pas une preuve cryptographique : un défi signé par l'app native reste à
construire.
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
MESSAGE_LUNETTES_AILLEURS = (
    "Tes lunettes sont connectées à ton téléphone, pas à l'ordinateur : l'ordinateur n'ouvre ni son micro, "
    "ni son écran, ni sa caméra pendant ce temps. Connecte les lunettes à l'ordinateur pour utiliser cette fonction."
)
MESSAGE_ASSOCIER_D_ABORD = (
    "Associe d'abord tes lunettes : connecte-les une première fois à l'ordinateur (Profil › Lunettes). "
    "L'ordinateur les reconnaîtra ensuite sur ton téléphone."
)
MESSAGE_AUTRES_LUNETTES = "Ces lunettes ne sont pas celles associées à cet IRIS."
MESSAGE_APPAREIL_NON_ASSOCIE = (
    "Ce téléphone n'est pas encore associé à tes lunettes sur cet IRIS. Pour l'associer, confirme avec le "
    "mot de passe du propriétaire."
)
IDENTIFIANTS_MAX = 4  # app iPhone, page Android, un second téléphone… au-delà, le plus ancien sort


# Finition B du 2026-09-14 : l'attestation du téléphone reste déclarative (aucun défi signé par l'app native n'est
# encore construit) ; la limite est dite là où la présence est affichée, pas seulement dans le code.
LIMITE_PRESENCE = (
    "Verrou logiciel : il s'applique à l'application IRIS, pas au matériel. Quand c'est le téléphone qui atteste "
    "les lunettes, il n'en donne pas de preuve cryptographique : le premier téléphone qui les atteste est associé "
    "d'office (inscrit au registre), les suivants demandent le mot de passe du propriétaire."
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


class LunettesAilleurs(HTTPException):
    """Refus d'une capture sur l'ordinateur : les lunettes sont attestées par le téléphone seulement.
    409 et une phrase simple : ce n'est pas « achète des lunettes », c'est « elles sont ailleurs »."""

    def __init__(self, fonction: str, message: str = MESSAGE_LUNETTES_AILLEURS):
        super().__init__(409, detail=message)
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
        self._fichier_association = Path(data_dir) / "lunettes-association.json"
        self._verrou = threading.Lock()
        self._attestation: dict | None = None
        # Registre de confidentialité (ctx.consent.log), branché par main.py : chaque appareil associé aux
        # lunettes y laisse une ligne visible par le propriétaire (contre-vérification du 2026-09-14).
        self.journal: Callable[..., Any] | None = None

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

    def presentes_pour_capture_pc(self) -> bool:
        """Les lunettes permettent-elles d'ouvrir le micro, l'écran ou la caméra de CET ordinateur ?
        Seulement si l'ordinateur les voit lui-même (ou verrou levé, démonstration) : une attestation du
        téléphone veut dire que leur porteur est ailleurs."""
        return self.source() in ("pc", "demo", "desactive")

    def exiger(self, fonction: str) -> None:
        """Lève LunettesRequises (428) si les lunettes manquent. À appeler en tête de toute fonction
        qui capte (voir, écouter, enregistrer) ou qui agit."""
        if not self.presentes():
            raise LunettesRequises(fonction)

    def exiger_capture_pc(self, fonction: str) -> None:
        """Comme exiger(), pour ce qui ouvre le micro, l'écran ou la caméra de l'ordinateur : 428 sans
        lunettes, 409 (LunettesAilleurs) quand elles ne sont attestées que par le téléphone."""
        source = self.source()
        if source is None:
            raise LunettesRequises(fonction)
        if source == "telephone":
            raise LunettesAilleurs(fonction)

    # ------------------------------------------------------------------ association téléphone ↔ lunettes
    def _lire_association(self) -> dict:
        try:
            donnees = json.loads(self._fichier_association.read_text(encoding="utf-8"))
            return donnees if isinstance(donnees, dict) else {}
        except (OSError, ValueError):
            return {}

    def _ecrire_association(self, donnees: dict) -> None:
        try:
            self._fichier_association.parent.mkdir(parents=True, exist_ok=True)
            self._fichier_association.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("association des lunettes non enregistrée : %s", exc)

    def _paire_connue(self) -> tuple[str, str]:
        """(nom, adresse) des lunettes connectées à cet ordinateur par une vraie connexion Bluetooth."""
        g = self.settings.user.glasses
        return (g.name or "").strip(), (g.address or "").strip()

    def _verifier_nom(self, nom: str) -> str:
        connues, _ = self._paire_connue()
        if not connues:
            raise HTTPException(409, MESSAGE_ASSOCIER_D_ABORD)
        if _compact(nom) != _compact(connues):
            raise HTTPException(403, MESSAGE_AUTRES_LUNETTES)
        return connues

    @staticmethod
    def _nettoyer(nom: str, identifiant: str) -> tuple[str, str]:
        nom = " ".join(str(nom or "").split())
        identifiant = str(identifiant or "").strip()[:120]
        if not nom:
            raise HTTPException(422, "Nom des lunettes manquant.")
        if not identifiant:
            raise HTTPException(422, "Identifiant Bluetooth des lunettes manquant : mets à jour l'app IRIS du téléphone.")
        return nom, identifiant

    def associer(self, nom: str, identifiant: str, mot_de_passe_valide: bool) -> dict:
        """Ajoute un appareil (téléphone, app iPhone) aux appareils associés. Exige le mot de passe du
        propriétaire (vérifié par l'appelant) : sinon n'importe quelle session pourrait déclarer un appareil."""
        nom, identifiant = self._nettoyer(nom, identifiant)
        self._verifier_nom(nom)
        if not mot_de_passe_valide:
            raise HTTPException(403, "Mot de passe incorrect.")
        _, adresse = self._paire_connue()
        with self._verrou:
            association = self._lire_association()
            if association.get("pc_adresse") != adresse:
                association = {}
            ids = [i for i in association.get("identifiants", []) if isinstance(i, str) and i != identifiant]
            ids = (ids + [identifiant])[-IDENTIFIANTS_MAX:]
            self._ecrire_association({"pc_adresse": adresse, "identifiants": ids,
                                      "associe_le": association.get("associe_le") or time.strftime("%Y-%m-%d")})
        self._journaliser("appareil_lunettes_associe", "mot de passe vérifié")
        return {"associe": True, "appareils": len(ids)}

    def _journaliser(self, evenement: str, detail: str) -> None:
        if self.journal is None:
            return
        try:
            self.journal(evenement, detail=detail)
        except Exception as exc:  # pragma: no cover - le registre ne doit jamais bloquer l'attestation
            log.warning("registre : %s non inscrit (%s)", evenement, type(exc).__name__)

    # ------------------------------------------------------------------ attestation du téléphone
    def attester(self, nom: str, identifiant: str = "", batterie: int | None = None, source: str = "telephone") -> dict:
        """L'app téléphone dit « les lunettes sont connectées à moi ».

        Refusé (409) tant que l'ordinateur n'a jamais été connecté à ces lunettes ; refusé (403) si le nom
        n'est pas EXACTEMENT celui retenu par l'ordinateur, ou si l'appareil n'est pas associé. Le premier
        appareil qui atteste des lunettes connues est associé d'office (confiance au premier usage) ; les
        suivants passent par associer(), avec le mot de passe du propriétaire."""
        nom, identifiant = self._nettoyer(nom, identifiant)
        self._verifier_nom(nom)
        _, adresse = self._paire_connue()
        nouveau = False
        with self._verrou:
            association = self._lire_association()
            if association.get("pc_adresse") != adresse or not association.get("identifiants"):
                # Paire neuve (ou lunettes changées sur l'ordinateur) : ce téléphone devient l'appareil associé.
                self._ecrire_association({"pc_adresse": adresse, "identifiants": [identifiant],
                                          "associe_le": time.strftime("%Y-%m-%d")})
                nouveau = True
            elif identifiant not in association.get("identifiants", []):
                raise HTTPException(403, {"code": "appareil_non_associe", "message": MESSAGE_APPAREIL_NON_ASSOCIE})
        self._attestation = {
            "nom": nom[:80],
            "identifiant": str(identifiant or "")[:120],
            "batterie": batterie if isinstance(batterie, int) and 0 <= batterie <= 100 else None,
            "source": source if source in ("telephone", "iphone", "android") else "telephone",
            "a": self.horloge(),
        }
        if nouveau:
            # Confiance au premier usage : limite dite, mais jamais silencieuse.
            self._journaliser("appareil_lunettes_associe", "premier appareil (sans mot de passe)")
        self._publier()
        return self.etat()

    def retirer_attestation(self, identifiant: str | None = None) -> dict:
        """Retire l'attestation en cours. Avec `identifiant`, seulement si c'est cet appareil qui l'a donnée :
        un second téléphone qui perd sa liaison (ou ferme sa page) ne doit pas effacer l'attestation que
        l'appareil réellement relié aux lunettes vient de donner. Sans identifiant, comportement d'origine."""
        with self._verrou:
            att = self._attestation
            demande = str(identifiant or "").strip()[:120]
            if demande and att is not None and att.get("identifiant") != demande:
                log.info("retrait d'attestation ignoré : un autre appareil l'a donnée")
                return self.etat()
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
            "limite": LIMITE_PRESENCE,
            # Les écrans lisent si la caméra des lunettes écrit vraiment la commande photo, au lieu de le
            # supposer (faux tant que le protocole n'est pas confirmé ; voir lunettes_camera.camera_lunettes_active).
            "camera_lunettes_active": self._camera_active(),
        }

    def _camera_active(self) -> bool:
        try:
            from .lunettes_camera import camera_lunettes_active

            return camera_lunettes_active(self.settings)
        except Exception as exc:  # pragma: no cover - module caméra absent : la présence reste servie
            log.debug("état de la caméra des lunettes illisible : %s", exc)
            return False

    def _publier(self) -> None:
        if self.hub is not None:
            try:
                self.hub.publish("lunettes.presence", **self.etat())
            except Exception:  # pragma: no cover
                pass


# ---------------------------------------------------------------------------- aides pour les modules
# Les modules du chantier reçoivent ctx, parfois un faux contexte dans leurs tests : la présence peut
# manquer. Sans service de présence, on ne bloque rien (le verrou vit dans AppContext, pas ailleurs).
def exiger_lunettes(ctx: Any, fonction: str) -> None:
    """Lève LunettesRequises (428) si ctx sait que les lunettes manquent. À appeler AVANT tout travail."""
    presence = getattr(ctx, "presence_lunettes", None)
    if presence is not None:
        presence.exiger(fonction)


def exiger_lunettes_pc(ctx: Any, fonction: str) -> None:
    """Pour ce qui ouvre le micro, l'écran ou la caméra de l'ordinateur : 428 sans lunettes, 409 quand
    elles ne sont attestées que par le téléphone (leur porteur est ailleurs). À appeler AVANT tout travail."""
    presence = getattr(ctx, "presence_lunettes", None)
    if presence is None:
        return
    exiger_pc = getattr(presence, "exiger_capture_pc", None)
    (exiger_pc if callable(exiger_pc) else presence.exiger)(fonction)


def raison_capture_pc(ctx: Any) -> str | None:
    """Pour les boucles de fond qui ouvriraient le micro de l'ordinateur : None si c'est permis, sinon la
    phrase à afficher (lunettes absentes, ou attestées par le téléphone seulement)."""
    presence = getattr(ctx, "presence_lunettes", None)
    if presence is None:
        return None
    try:
        exiger_lunettes_pc(ctx, "fond")
    except LunettesAilleurs as exc:
        return exc.message
    except LunettesRequises:
        return MESSAGE_REQUISES
    except Exception as exc:  # pragma: no cover - une présence illisible ne fait rien planter
        log.warning("présence des lunettes illisible : %s", exc)
        return MESSAGE_REQUISES
    return None


def lunettes_presentes_pc(ctx: Any) -> bool:
    return raison_capture_pc(ctx) is None


def lunettes_presentes(ctx: Any) -> bool:
    """Pour les chemins sans route (voix, outils, boucles de fond) : vrai si rien ne prouve l'absence."""
    presence = getattr(ctx, "presence_lunettes", None)
    if presence is None:
        return True
    # Même porte que les routes (exiger) : une seule définition de « les lunettes sont là » pour une fonction.
    try:
        presence.exiger("fond")
    except LunettesRequises:
        return False
    except Exception as exc:  # pragma: no cover - une présence illisible ne fait rien planter
        log.warning("présence des lunettes illisible : %s", exc)
        return False
    return True
