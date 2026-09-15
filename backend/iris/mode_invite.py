"""Mode invité : prêter IRIS (ou ses lunettes) sans qu'elle retienne quoi que ce soit de la session.

Ce que fait le mode (interface I, 2026-09-13) :
- la mémoire est suspendue (`ctx.memory.suspendre("invite")`) : aucun souvenir, journal, cours, photo
  décrite ou reçu n'est écrit, et les services qui gardent des traces le voient ;
- à la sortie, les conversations créées pendant le mode sont supprimées, ainsi que les messages ajoutés
  pendant le mode aux conversations déjà existantes (la conversation vocale est réutilisée d'une commande
  à l'autre : sans ce second balayage, l'échange de l'invité y resterait) ;
- une minuterie ramène IRIS à la normale après `mode_invite_minutes` (5 à 720) ;
- l'état est écrit sur le disque (sans contenu : dates et identifiants) pour qu'un redémarrage en plein
  mode invité ne laisse ni la mémoire ouverte ni les conversations de l'invité derrière lui.

Ce que le mode ne fait PAS, dit tel quel à l'écran (`LIMITE`) : il ne cache pas les souvenirs déjà
enregistrés (IRIS peut encore s'en servir pour répondre), et il n'efface ni les rappels ni les tâches
créés pendant la session.

Phrases (interception de priorité 10, avant tout le reste) : « mode invité », « active le mode invité »,
« fin du mode invité », « désactive le mode invité ».

Sortir à la voix : l'invité porte les lunettes, et IRIS ne sait pas qui parle. Si « fin du mode invité »
suffisait, l'invité en sortirait et IRIS lui répondrait aussitôt avec les souvenirs du propriétaire. La
phrase de sortie n'est donc acceptée que si le verrou vocal est installé (ctx.voice.verificateur_locuteur :
la commande a alors été admise comme la voix du propriétaire) ET si la phrase vient du micro de cet
ordinateur (voice.listener.ORIGINE_COMMANDE). Une phrase transcrite par le téléphone (POST /api/voix/commande)
n'a aucun audio : le verrou vocal ne l'a jamais vérifiée, elle est refusée même quand il est installé.
Sinon, le mode se termine depuis l'application ou à la fin de la minuterie, et IRIS le dit.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("iris.mode_invite")

RAISON = "invite"
MINUTES_MIN = 5
MINUTES_MAX = 720
NOM_INTERCEPTION = "confiance-mode-invite"

LIMITE = (
    "Le mode invité suspend la mémoire d'IRIS (souvenirs, journal, cours, photos décrites, reçus) et efface les "
    "conversations de la session à la sortie. Pendant le mode, IRIS ne s'appuie pas sur vos souvenirs pour "
    "répondre, mais il ne cache pas vos souvenirs existants dans l'application. Il n'efface ni les rappels ni "
    "les tâches créés pendant la session. IRIS ne sait pas qui parle dans les lunettes : sans verrou vocal, "
    "la phrase « fin du mode invité » est refusée, et le mode se termine depuis l'application ou à la fin de "
    "la minuterie. Le verrou vocal reste une vérification de base : une voix proche peut le tromper."
)
SORTIE_VOCALE_REFUSEE = (
    "Je ne peux pas savoir qui me parle : terminez le mode invité depuis l'application IRIS. "
    "Il se terminera aussi tout seul à {heure}."
)

_POLITESSE = r"(?: s il (?:te|vous) plait)?"
_ACTIVER = re.compile(
    r"^(?:iris )?(?:(?:active|activer|activez|passe|passer|passez|mets|mettre|lance|lancer|demarre|demarrer)"
    r"(?: le| en| au)? )?mode invite" + _POLITESSE + r"$"
)
_DESACTIVER = re.compile(
    r"^(?:iris )?(?:fin|termine|terminer|arrete|arreter|desactive|desactiver|desactivez|quitte|quitter|sors|"
    r"sortir|sortez|stop)(?: du| le| de| la)? mode invite" + _POLITESSE + r"$"
)


_ORIGINE_MICRO_PC = "micro_pc"


def _origine_commande() -> str:
    """Origine de la phrase en cours d'interception (voice.listener.ORIGINE_COMMANDE). Si l'écoute ne peut pas
    être importée, on ne sait pas d'où vient la phrase : on la traite comme non vérifiée."""
    try:
        from .voice.listener import ORIGINE_COMMANDE
    except Exception:  # pragma: no cover - module d'écoute absent ou cassé
        return "inconnue"
    return ORIGINE_COMMANDE.get()


def _normaliser(texte: str) -> str:
    """Même normalisation que l'écoute (voice/listener.normalize) : sans accents, sans ponctuation."""
    brut = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", brut.lower()).split())


def maintenant_iso() -> str:
    """Même format que chat.now_iso (UTC, à la seconde) : les comparaisons de chaînes en base restent justes."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def heure_locale(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return ""
    return f"{moment.hour} h {moment.minute:02d}"


class ModeInvite:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.fichier = Path(ctx.settings.data_dir) / "mode-invite.json"
        self._verrou = threading.RLock()
        self.actif = False
        self.depuis: str | None = None
        self.jusqua: str | None = None
        self._fin = 0.0  # échéance (secondes epoch)
        self._conversations: set[str] = set()
        self._reprendre_apres_redemarrage()

    # ------------------------------------------------------------------ persistance (sans contenu)
    def _ecrire(self) -> None:
        try:
            if not self.actif:
                self.fichier.unlink(missing_ok=True)
                return
            self.fichier.write_text(json.dumps({
                "actif": True, "depuis": self.depuis, "jusqua": self.jusqua,
                "conversations": sorted(self._conversations),
            }), encoding="utf-8")
        except OSError as exc:
            log.warning("mode invité : état non écrit (%s)", exc)

    def _reprendre_apres_redemarrage(self) -> None:
        """Un mode invité interrompu par un redémarrage reste en vigueur (la mémoire est suspendue AVANT
        toute écriture possible) ; s'il est échu, la boucle de minuterie le termine et fait le ménage."""
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
        except Exception:
            return
        if not donnees.get("actif") or not donnees.get("depuis"):
            return
        try:
            fin = datetime.fromisoformat(str(donnees.get("jusqua"))).timestamp()
        except (TypeError, ValueError):
            fin = 0.0
        self.actif = True
        self.depuis = str(donnees["depuis"])
        self.jusqua = donnees.get("jusqua")
        self._fin = fin
        self._conversations = {str(c) for c in donnees.get("conversations", []) if c}
        self.ctx.memory.suspendre(RAISON)
        log.info("mode invité repris après redémarrage (jusqu'à %s)", self.jusqua)

    # ------------------------------------------------------------------ état
    def etat(self) -> dict:
        with self._verrou:
            restant = max(0, int(-(-(self._fin - time.time()) // 60))) if self.actif else 0
            return {"actif": self.actif, "depuis": self.depuis, "jusqua": self.jusqua,
                    "minutes_restantes": restant, "limite": LIMITE}

    def _publier(self) -> None:
        try:
            self.ctx.hub.publish("invite.etat", actif=self.actif, jusqua=self.jusqua, depuis=self.depuis)
        except Exception as exc:  # pragma: no cover
            log.debug("mode invité : publication (%s)", exc)

    # ------------------------------------------------------------------ activer / désactiver
    def activer(self, minutes: int | None = None, origine: str = "ecran") -> dict:
        if minutes is None:
            minutes = int(getattr(self.ctx.settings.user, "mode_invite_minutes", 120) or 120)
        try:
            minutes = min(MINUTES_MAX, max(MINUTES_MIN, int(minutes)))
        except (TypeError, ValueError):
            minutes = 120
        with self._verrou:
            # La suspension d'abord : entre le clic et la fin de cette méthode, rien ne doit s'écrire.
            self.ctx.memory.suspendre(RAISON)
            maintenant = datetime.now(timezone.utc).replace(microsecond=0)
            if not self.actif:
                self.actif = True
                self.depuis = maintenant.isoformat(timespec="seconds")
                self._conversations = set()
            fin = maintenant + timedelta(minutes=minutes)
            self.jusqua = fin.isoformat(timespec="seconds")
            self._fin = fin.timestamp()
            self._ecrire()
        try:
            self.ctx.consent.log("mode_invite_active", detail=f"{minutes} min ({origine})")
        except Exception:  # pragma: no cover
            pass
        self._publier()
        return self.etat()

    def noter_conversation(self, conversation_id: str | None) -> None:
        """Appelée pour chaque événement conversation.created : retenue seulement pendant le mode."""
        if not conversation_id:
            return
        with self._verrou:
            if self.actif:
                self._conversations.add(str(conversation_id))
                self._ecrire()

    def desactiver(self, origine: str = "ecran") -> dict:
        with self._verrou:
            if not self.actif:
                return {**self.etat(), "effacees": {"conversations": 0, "messages": 0, "erreurs": 0}}
            depuis = self.depuis or maintenant_iso()
            conversations = set(self._conversations)
            effacees = self._effacer_session(depuis, conversations)
            self.actif = False
            self.depuis = None
            self.jusqua = None
            self._fin = 0.0
            self._conversations = set()
            self._ecrire()
            # La mémoire reprend APRÈS le ménage : rien de la session ne peut s'y glisser entre les deux.
            self.ctx.memory.reprendre(RAISON)
        try:
            self.ctx.consent.log("mode_invite_termine", detail=(
                f"{origine} ; {effacees['conversations']} conversation(s), {effacees['messages']} message(s) effacés"))
        except Exception:  # pragma: no cover
            pass
        self._publier()
        return {**self.etat(), "effacees": effacees}

    def _effacer_session(self, depuis: str, conversations: set[str]) -> dict:
        db = self.ctx.db
        chat = getattr(self.ctx, "chat", None)
        erreurs = 0
        try:
            for ligne in db.query("SELECT id FROM conversations WHERE created_at >= ?", (depuis,)):
                conversations.add(ligne["id"])
        except Exception as exc:
            erreurs += 1  # le ménage n'est plus garanti : la phrase de fin le dira
            log.warning("mode invité : recherche des conversations de la session impossible (%s)", exc)
        supprimees = 0
        for conv_id in conversations:
            try:
                if chat is not None:
                    supprimees += 1 if chat.delete_conversation(conv_id) else 0
                else:
                    supprimees += max(0, db.execute("DELETE FROM conversations WHERE id=?", (conv_id,)).rowcount)
            except Exception as exc:
                erreurs += 1
                log.warning("mode invité : conversation %s non supprimée (%s)", conv_id, exc)
        messages = 0
        try:
            touchees = [r["conversation_id"] for r in db.query(
                "SELECT DISTINCT conversation_id FROM messages WHERE created_at >= ?", (depuis,))]
            for conv_id in touchees:
                if chat is not None:
                    try:
                        chat.cancel(conv_id)
                    except Exception:
                        pass
            messages = max(0, db.execute("DELETE FROM messages WHERE created_at >= ?", (depuis,)).rowcount)
            for conv_id in touchees:
                conv = chat.get_conversation(conv_id) if chat is not None else None
                if conv:
                    self.ctx.hub.publish("conversation.updated", conversation=conv)
        except Exception as exc:
            erreurs += 1
            log.warning("mode invité : messages de la session non supprimés (%s)", exc)
        return {"conversations": supprimees, "messages": messages, "erreurs": erreurs}

    def verifier_echeance(self, maintenant: float | None = None) -> bool:
        """Termine le mode si la minuterie est échue. Renvoie True si elle vient de le terminer."""
        with self._verrou:
            echu = self.actif and (maintenant if maintenant is not None else time.time()) >= self._fin
        if not echu:
            return False
        resultat = self.desactiver(origine="minuterie")
        tts = getattr(self.ctx, "tts", None)
        try:
            if tts is not None and getattr(tts, "available", False):
                tts.speak(self._phrase_de_fin(resultat["effacees"], concis=False))
        except Exception:  # pragma: no cover
            pass
        return True

    # ------------------------------------------------------------------ voix
    def interception(self, texte: str) -> str | None:
        propre = _normaliser(texte)
        if "invite" not in propre:
            return None  # la réponse rapide attendue pour toutes les autres phrases
        concis = getattr(self.ctx.settings.user, "verbosite", "normal") == "concis"
        if _DESACTIVER.match(propre):
            if not self.actif:
                return "Le mode invité n'est pas actif."
            if not self._voix_verifiee():
                # L'invité porte les lunettes : sans voix vérifiée, cette phrase peut venir de lui.
                detail = ("commande transcrite par le téléphone, voix non vérifiée"
                          if _origine_commande() != _ORIGINE_MICRO_PC else "verrou vocal absent")
                try:
                    self.ctx.consent.log("mode_invite_sortie_vocale_refusee", detail=detail)
                except Exception:  # pragma: no cover
                    pass
                return SORTIE_VOCALE_REFUSEE.format(heure=heure_locale(self.jusqua))
            resultat = self.desactiver(origine="voix")
            return self._phrase_de_fin(resultat["effacees"], concis)
        if _ACTIVER.match(propre):
            if self.actif:
                return f"Le mode invité est déjà actif jusqu'à {heure_locale(self.jusqua)}."
            etat = self.activer(origine="voix")
            if concis:
                return f"Mode invité activé jusqu'à {heure_locale(etat['jusqua'])}."
            sortie = ("dites « fin du mode invité » pour en sortir." if self._voix_verifiee() else
                      "pour en sortir avant, utilisez l'application : je ne peux pas savoir qui me parle.")
            return (f"Mode invité activé jusqu'à {heure_locale(etat['jusqua'])} : je ne garde pas de souvenirs de "
                    f"cette session, et ses conversations seront effacées à la fin. Quiconque porte les lunettes "
                    f"me parle ; {sortie}")
        return None

    def _voix_verifiee(self) -> bool:
        """Vrai seulement si la phrase vient du micro de cet ordinateur ET que le verrou vocal y est installé :
        la commande a alors été admise comme la voix du propriétaire (VoiceListener._locuteur_admis, appelé sur
        TOUS les chemins du micro qui mènent à une interception : _listen_command pour une commande dite après le mot
        d'activation, et _wake_cycle pour une commande dite dans le même souffle en reconnaissance en ligne). Une phrase
        venue du téléphone (texte, sans audio) n'a été vérifiée par personne : faux, verrou installé ou non."""
        if _origine_commande() != _ORIGINE_MICRO_PC:
            return False
        voice = getattr(self.ctx, "voice", None)
        return callable(getattr(voice, "verificateur_locuteur", None))

    @staticmethod
    def _phrase_de_fin(effacees: dict, concis: bool) -> str:
        if effacees.get("erreurs"):
            return ("Mode invité terminé, mais une partie de la session n'a pas pu être effacée : "
                    "vérifiez l'historique des conversations.")
        if concis:
            return "Mode invité terminé."
        return "Mode invité terminé : les conversations de la session ont été effacées. Je retiens de nouveau."

    def brancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "ajouter_interception"):
            voice.ajouter_interception(NOM_INTERCEPTION, self.interception, priorite=10)

    def debrancher_voix(self) -> None:
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and hasattr(voice, "retirer_interception"):
            voice.retirer_interception(NOM_INTERCEPTION)
