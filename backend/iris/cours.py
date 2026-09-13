"""Mode cours : enregistrer un cours, le transcrire sur l'appareil, puis réviser avec des fiches et des questions.

Démarrer un cours, c'est trois choses liées : les sous-titres (reconnaissance hors ligne), un
enregistrement WAV du cours, et une transcription horodatée gardée CHIFFRÉE dans la base. Tout cela
reste sur l'ordinateur. Seule la génération des fiches de révision et des questions d'examen passe
par le moteur VELA — sur demande, avec le consentement « Texte de vos demandes », jamais en mode
100 % local sans IA locale — et chaque envoi est inscrit au registre de confidentialité.

Limites dites à l'utilisateur, sans détour :
- la transcription vient du petit modèle hors ligne : approximative (termes techniques, formules
  dites à voix haute, noms propres), sans ponctuation ni distinction entre l'enseignant et la salle ;
- les fiches et les questions sont rédigées à partir de cette transcription : elles peuvent contenir
  des erreurs et doivent être vérifiées avec les notes et le matériel du cours ;
- l'import n'accepte que le WAV en PCM entier (pas de MP3 ni de M4A) ;
- mémoire suspendue (mode invité, zone sans mémoire) : aucun cours ne démarre, rien n'est écrit.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import math
import re
import threading
import time
import uuid
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .enregistrement_audio import (
    ESPACE_MIN_DEMARRAGE, SessionEnregistrement, annoncer, dossier_audio, espace_libre, memoire_suspendue, nom_libre,
)
from .journal import creer_tables, iso_local, iso_utc, sans_accents
from .sous_titres import EcouteImpossible, empechement_micro, transcrire_pcm
from .voice.robinet import TAUX

log = logging.getLogger("iris.cours")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cours (
    id TEXT PRIMARY KEY,
    debut TEXT NOT NULL,
    fin TEXT,
    duree_s REAL NOT NULL DEFAULT 0,
    titre_enc BLOB NOT NULL,
    matiere_enc BLOB,
    fiches_enc BLOB,
    questions_enc BLOB,
    audio TEXT,
    source TEXT NOT NULL DEFAULT 'direct',
    etat TEXT NOT NULL DEFAULT 'termine',
    erreur TEXT,
    retenu_jusqua TEXT
);
CREATE INDEX IF NOT EXISTS idx_cours_debut ON cours(debut);
CREATE TABLE IF NOT EXISTS cours_lignes (
    cours_id TEXT NOT NULL REFERENCES cours(id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    ts REAL NOT NULL,
    texte_enc BLOB NOT NULL,
    PRIMARY KEY (cours_id, n)
);
"""

NOM_ROBINET = "cours"
TAILLE_TRANCHE = 6000  # caractères envoyés au moteur par appel : assez pour un contexte utile, assez peu pour rester fiable
TRANSCRIPTION_MIN = 200  # en dessous, il n'y a pas de quoi faire des fiches honnêtes
TAILLE_MAX_IMPORT = 600 * 1024 * 1024  # 600 Mo décodés : ≈ 5 h en 16 kHz mono
TYPES_QUESTIONS = ("definition", "application", "comprehension", "calcul", "vrai_faux")
QUESTIONS_MIN, QUESTIONS_MAX = 10, 25
INTERVALLE_ETAT_S = 5.0

AVERTISSEMENT_FICHES = (
    "> Fiches rédigées automatiquement à partir d'une transcription approximative du cours : "
    "vérifiez-les avec vos notes et le matériel du cours."
)
LOCAL_SEULEMENT = (
    "Le mode 100 % local est actif : rédiger à partir de la transcription demande le moteur VELA, "
    "et aucune IA locale n'est configurée. La transcription, elle, reste disponible."
)
MOTEUR_EN_PANNE = "Le moteur VELA n'a pas pu rédiger le texte. Réessayez dans un instant."
FORMAT_REFUSE = (
    "Format non pris en charge : seul le fichier WAV (PCM) est accepté. Convertissez l'enregistrement "
    "(MP3, M4A…) en WAV, idéalement 16 kHz mono, avant de l'importer."
)


# =============================================================================== rédaction par le moteur
class RefusMoteur(Exception):
    """Refus explicable d'un envoi au moteur. `detail` est ce que la route renvoie tel quel."""

    def __init__(self, status: int, detail: Any):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


def agent_pour_texte(ctx, message: str) -> tuple[str, bool]:
    """(moteur, local) que demander_court choisira pour ce message — même sélection, pour vérifier le
    consentement sur le moteur qui recevra VRAIMENT le texte. Lève NoAgentAvailable."""
    chat = ctx.chat
    disponibles = chat.router.available(chat.secrets)
    agent, _raison = chat.router.select(message, False, disponibles, "auto")
    cfg = ctx.settings.user.agents.get(agent)
    return agent, bool(cfg and cfg.local)


async def demander_moteur(ctx, systeme: str, message: str, detail: str) -> dict:
    """Une question texte au moteur, avec les garanties de confidentialité. Rend {texte, local}.

    Lève RefusMoteur : 403 consentement, 409 mode local ou aucun moteur, 502 panne (le détail du
    fournisseur reste au journal : le client ne voit jamais de nom de fournisseur)."""
    from .connectors.base import ConnectorError
    from .consent import DATA_TYPES, ConsentRequired, LocalOnlyMode
    from .router import NoAgentAvailable

    try:
        agent, local = agent_pour_texte(ctx, message)
        ctx.consent.check("transcript", agent=agent)
    except ConsentRequired as exc:
        libelle = DATA_TYPES.get(exc.data_type, {}).get("label", exc.data_type)
        raise RefusMoteur(403, {
            "code": "consentement", "data_type": exc.data_type, "label": libelle,
            "message": f"Autorisez « {libelle} » dans Confidentialité pour envoyer la transcription au moteur VELA.",
        })
    except LocalOnlyMode:
        raise RefusMoteur(409, LOCAL_SEULEMENT)
    except NoAgentAvailable as exc:
        raise RefusMoteur(409, LOCAL_SEULEMENT if ctx.settings.user.local_only else (str(exc) or MOTEUR_EN_PANNE))
    if not local:
        ctx.consent.log("external_send", data_type="transcript", agent=agent, detail=detail[:200])
    try:
        texte = await ctx.chat.demander_court(systeme, message)
    except ConnectorError as exc:
        log.warning("moteur en erreur (%s) : %s", detail, exc)
        raise RefusMoteur(502, MOTEUR_EN_PANNE)
    except (ConsentRequired, LocalOnlyMode, NoAgentAvailable):
        raise RefusMoteur(409, LOCAL_SEULEMENT)
    texte = (texte or "").strip()
    if not texte:
        raise RefusMoteur(502, MOTEUR_EN_PANNE)
    return {"texte": texte, "local": local}


def decouper(texte: str, taille: int = TAILLE_TRANCHE) -> list[str]:
    """Tranches d'au plus `taille` caractères, coupées entre deux lignes (jamais au milieu d'une phrase
    quand c'est possible) ; une ligne plus longue que la tranche est coupée entre deux mots."""
    tranches: list[str] = []
    courante: list[str] = []
    longueur = 0
    for ligne in (texte or "").splitlines():
        while len(ligne) > taille:
            coupe = ligne.rfind(" ", 0, taille)
            coupe = coupe if coupe > taille // 2 else taille
            morceau, ligne = ligne[:coupe], ligne[coupe:].lstrip()
            if courante:
                tranches.append("\n".join(courante))
                courante, longueur = [], 0
            tranches.append(morceau)
        if longueur + len(ligne) + 1 > taille and courante:
            tranches.append("\n".join(courante))
            courante, longueur = [], 0
        courante.append(ligne)
        longueur += len(ligne) + 1
    if courante and "\n".join(courante).strip():
        tranches.append("\n".join(courante))
    return [t for t in tranches if t.strip()]


def horodatage(secondes: float) -> str:
    s = int(max(0.0, secondes))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def texte_des_lignes(lignes: list[Any]) -> str:
    """Lignes {ts, texte} ou chaînes -> texte brut, une phrase par ligne."""
    sortie = []
    for ligne in lignes or []:
        if isinstance(ligne, dict):
            texte = str(ligne.get("texte") or "").strip()
        else:
            texte = str(ligne or "").strip()
        if texte:
            sortie.append(texte)
    return "\n".join(sortie)


CONSIGNE_FIDELITE = (
    "Tu travailles à partir d'une transcription automatique approximative, sans ponctuation et sans "
    "noms de locuteurs. N'invente rien : aucun nom, chiffre, date, décision ou fait qui ne soit pas "
    "dans le texte. Quand un passage est incompréhensible, dis-le au lieu de deviner. "
    "Écris en français (Canada)."
)


async def rediger_proces_verbal(ctx, lignes: list[Any]) -> dict:
    """Procès-verbal Markdown d'une conversation ou d'une réunion. Rend {resume, local, tranches}."""
    texte = texte_des_lignes(lignes)
    if not texte.strip():
        raise RefusMoteur(422, "Aucune transcription à résumer.")
    tranches = decouper(texte)
    sections = (
        "## Points clés\n## Décisions\n## Actions (qui, quoi, échéance — seulement si c'est dit)\n"
        "## Qui a dit quoi (seulement pour les personnes nommées dans la transcription ; sinon écris "
        "« Non identifiable dans la transcription »)"
    )
    systeme = f"Tu rédiges un procès-verbal fidèle. {CONSIGNE_FIDELITE} Réponds en Markdown."
    local = True
    if len(tranches) == 1:
        r = await demander_moteur(ctx, systeme, f"Rédige le procès-verbal avec exactement ces sections :\n{sections}\n\nTranscription :\n{tranches[0]}",
                                  f"procès-verbal ({len(texte)} caractères)")
        return {"resume": r["texte"], "local": r["local"], "tranches": 1}
    notes = []
    for i, tranche in enumerate(tranches, 1):
        r = await demander_moteur(
            ctx, systeme,
            f"Partie {i} sur {len(tranches)} d'une même réunion. Note les points clés, décisions, actions et "
            f"propos attribuables à une personne nommée, en puces courtes.\n\nTranscription :\n{tranche}",
            f"procès-verbal, partie {i}/{len(tranches)}",
        )
        local = local and r["local"]
        notes.append(f"### Partie {i}\n{r['texte']}")
    r = await demander_moteur(
        ctx, systeme,
        f"Fusionne ces notes partielles en un seul procès-verbal, sans doublons, avec exactement ces sections :\n"
        f"{sections}\n\nNotes :\n" + "\n\n".join(notes),
        f"procès-verbal, fusion de {len(tranches)} parties",
    )
    return {"resume": r["texte"], "local": local and r["local"], "tranches": len(tranches)}


def lire_questions(brut: str) -> list[dict]:
    """Extrait la liste JSON de questions d'une réponse du moteur, en ignorant ce qui ne respecte pas le format."""
    texte = re.sub(r"```(?:json)?", "", brut or "")
    debut, fin = texte.find("["), texte.rfind("]")
    if debut < 0 or fin <= debut:
        return []
    try:
        donnees = json.loads(texte[debut:fin + 1])
    except ValueError:
        return []
    questions = []
    for q in donnees if isinstance(donnees, list) else []:
        if not isinstance(q, dict):
            continue
        question = str(q.get("question") or "").strip()
        reponse = str(q.get("reponse") or q.get("réponse") or "").strip()
        if not question or not reponse:
            continue
        genre = sans_accents(str(q.get("type") or "")).replace(" ", "_")
        try:
            difficulte = int(q.get("difficulte", q.get("difficulté", 2)))
        except (TypeError, ValueError):
            difficulte = 2
        questions.append({
            "question": question[:1000],
            "reponse": reponse[:3000],
            "type": genre if genre in TYPES_QUESTIONS else "comprehension",
            "difficulte": min(3, max(1, difficulte)),
        })
    return questions


# =============================================================================== fichiers WAV
def lire_wav(octets: bytes) -> tuple[bytes, float]:
    """WAV PCM entier (8, 16, 24 ou 32 bits, mono ou multicanal, toute fréquence) -> PCM int16 mono 16 kHz.

    Traité par tranches d'une minute : un fichier de plusieurs heures ne doit pas faire exploser la
    mémoire. Le rééchantillonnage est linéaire, précédé d'un lissage quand on descend en fréquence
    (atténue le repliement ; la parole utile au modèle est sous 8 kHz). Lève ValueError avec un
    message à montrer tel quel."""
    import numpy as np

    if len(octets) < 12 or octets[:4] != b"RIFF" or octets[8:12] != b"WAVE":
        raise ValueError(FORMAT_REFUSE)
    try:
        lecteur = wave.open(io.BytesIO(octets), "rb")
    except (wave.Error, EOFError) as exc:
        raise ValueError(
            "WAV non pris en charge (compressé ou en virgule flottante) : seul le PCM entier est accepté. "
            "Réexportez le fichier en WAV PCM 16 bits."
        ) from exc
    with lecteur:
        canaux, largeur, taux, total = lecteur.getnchannels(), lecteur.getsampwidth(), lecteur.getframerate(), lecteur.getnframes()
        if largeur not in (1, 2, 3, 4) or canaux < 1:
            raise ValueError("WAV non pris en charge : échantillons de 8, 16, 24 ou 32 bits entiers seulement.")
        if not 4000 <= taux <= 384000:
            raise ValueError(f"Fréquence d'échantillonnage non prise en charge ({taux} Hz).")
        if total <= 0:
            raise ValueError("Le fichier WAV ne contient aucun son.")
        sorties: list[bytes] = []
        par_tranche = taux * 60
        position = 0
        lissage = int(taux // TAUX) + 1 if taux > TAUX else 1
        while position < total:
            brut = lecteur.readframes(par_tranche)
            if not brut:
                break
            n = len(brut) // (largeur * canaux)
            if n == 0:
                break
            brut = brut[: n * largeur * canaux]
            if largeur == 1:
                x = (np.frombuffer(brut, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
            elif largeur == 2:
                x = np.frombuffer(brut, dtype="<i2").astype(np.float32)
            elif largeur == 3:
                b = np.frombuffer(brut, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
                v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                v = np.where(v >= 1 << 23, v - (1 << 24), v)
                x = (v / 256.0).astype(np.float32)
            else:
                x = (np.frombuffer(brut, dtype="<i4") / 65536.0).astype(np.float32)
            if canaux > 1:
                x = x.reshape(-1, canaux).mean(axis=1)
            if taux != TAUX:
                if lissage > 1:
                    x = np.convolve(x, np.ones(lissage, dtype=np.float32) / lissage, mode="same")
                premier = math.ceil(position * TAUX / taux)
                dernier = math.ceil((position + n) * TAUX / taux)
                cibles = np.arange(premier, dernier, dtype=np.float64) * taux / TAUX - position
                x = np.interp(cibles, np.arange(n, dtype=np.float64), x)
            sorties.append(np.clip(np.round(x), -32768, 32767).astype("<i2").tobytes())
            position += n
    pcm = b"".join(sorties)
    if not pcm:
        raise ValueError("Le fichier WAV ne contient aucun son.")
    return pcm, len(pcm) / 2 / TAUX


def ecrire_wav(chemin: Path, pcm: bytes) -> None:
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAUX)
        w.writeframes(pcm)


def nom_sur(nom: str | None) -> str | None:
    """Un nom de fichier du dossier audio, jamais un chemin (pas de ../ ni de lecteur)."""
    if not nom or "/" in nom or "\\" in nom or ":" in nom or nom.startswith("."):
        return None
    return nom


# =============================================================================== service
class ServiceCours:
    def __init__(self, ctx, sous_titres):
        self.ctx = ctx
        self.sous_titres = sous_titres
        self._verrou = threading.RLock()
        self._actif: dict | None = None
        self._imports: dict[str, dict] = {}
        self._generations: set[str] = set()
        self._dernier_etat = 0.0
        self.notifier = lambda: None  # branché par routes_ecoute sur ecoute.etat
        creer_tables(ctx.db, SCHEMA)

    # ------------------------------------------------------------------ utilitaires
    def _dechiffrer(self, blob) -> str | None:
        if not blob:
            return None
        try:
            return self.ctx.crypto.decrypt(blob)
        except Exception:
            log.warning("donnée de cours illisible (clé changée ?)")
            return None

    def _chiffrer(self, texte: str | None) -> bytes | None:
        return self.ctx.crypto.encrypt(texte) if texte else None

    def _retenu_jusqua(self) -> str | None:
        jours = int(getattr(self.ctx.settings.user, "retention_days", 0) or 0)
        return iso_utc(datetime.now(timezone.utc) + timedelta(days=jours)) if jours > 0 else None

    def _ligne(self, cours_id: str) -> dict | None:
        return self.ctx.db.one("SELECT * FROM cours WHERE id=?", (cours_id,))

    def _nb_lignes(self, cours_id: str) -> int:
        row = self.ctx.db.one("SELECT COUNT(*) AS n FROM cours_lignes WHERE cours_id=?", (cours_id,))
        return int(row["n"]) if row else 0

    def _audio_existant(self, nom: str | None) -> str | None:
        nom = nom_sur(nom)
        if not nom:
            return None
        return nom if (dossier_audio(self.ctx) / nom).exists() else None

    def _resume(self, row: dict, lignes: int | None = None) -> dict:
        en_cours = self._actif  # référence locale : arreter() peut le remettre à None pendant ce calcul
        actif = en_cours is not None and en_cours["id"] == row["id"]
        imp = self._imports.get(row["id"])
        duree = float(row.get("duree_s") or 0)
        if actif and en_cours is not None:
            duree = round(time.time() - en_cours["debut_epoch"], 1)
        return {
            "id": row["id"],
            "titre": self._dechiffrer(row["titre_enc"]) or "",
            "matiere": self._dechiffrer(row.get("matiere_enc")),
            "debut": iso_local(row["debut"]),
            "fin": iso_local(row["fin"]) if row.get("fin") else None,
            "duree_s": duree,
            "lignes": self._nb_lignes(row["id"]) if lignes is None else lignes,
            "fiches": bool(row.get("fiches_enc")),
            "questions": bool(row.get("questions_enc")),
            "audio": self._audio_existant(row.get("audio")),
            "actif": actif,
            "source": row.get("source") or "direct",
            "etat": row.get("etat") or "termine",
            "progression": round(imp["progression"], 3) if imp else None,
            "erreur": row.get("erreur"),
        }

    def _publier(self, cours_id: str, **extra) -> None:
        row = self._ligne(cours_id)
        if row is None:
            return
        r = self._resume(row)
        self.ctx.hub.publish("cours.etat", id=cours_id, actif=r["actif"], secondes=r["duree_s"], lignes=r["lignes"],
                             etat=r["etat"], progression=r["progression"], **extra)

    def _notifier(self) -> None:
        try:
            self.notifier()
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------ lecture
    def cours_actif(self) -> dict | None:
        with self._verrou:
            actif = self._actif
        if actif is None:
            return None
        row = self._ligne(actif["id"])
        return self._resume(row) if row else None

    def liste(self) -> list[dict]:
        rows = self.ctx.db.query("SELECT * FROM cours ORDER BY debut DESC")
        comptes = {r["cours_id"]: int(r["n"]) for r in self.ctx.db.query(
            "SELECT cours_id, COUNT(*) AS n FROM cours_lignes GROUP BY cours_id")}
        return [self._resume(r, comptes.get(r["id"], 0)) for r in rows]

    def transcription(self, cours_id: str) -> list[dict]:
        rows = self.ctx.db.query("SELECT ts, texte_enc FROM cours_lignes WHERE cours_id=? ORDER BY n", (cours_id,))
        sortie = []
        for r in rows:
            texte = self._dechiffrer(r["texte_enc"])
            if texte:
                sortie.append({"ts": round(float(r["ts"]), 2), "texte": texte})
        return sortie

    def detail(self, cours_id: str) -> dict | None:
        row = self._ligne(cours_id)
        if row is None:
            return None
        transcription = self.transcription(cours_id)
        questions_brutes = self._dechiffrer(row.get("questions_enc"))
        try:
            questions = json.loads(questions_brutes) if questions_brutes else None
        except ValueError:
            questions = None
        return {**self._resume(row, len(transcription)), "transcription": transcription,
                "fiches": self._dechiffrer(row.get("fiches_enc")), "questions": questions}

    # ------------------------------------------------------------------ cours en direct
    def demarrer(self, titre: str, matiere: str | None = None) -> dict:
        """Lève EcouteImpossible (409) avec la raison exacte."""
        titre = (titre or "").strip()[:200] or f"Cours du {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        matiere = (matiere or "").strip()[:120] or None
        with self._verrou:
            if self._actif is not None:
                row = self._ligne(self._actif["id"])
                nom = self._dechiffrer(row["titre_enc"]) if row else ""
                raise EcouteImpossible(f"Un cours est déjà en cours : « {nom} ». Arrêtez-le avant d'en commencer un autre.")
            raison = empechement_micro(self.ctx)
            if raison:
                raise EcouteImpossible(raison)
            suspendue = memoire_suspendue(self.ctx)
            if suspendue:
                raise EcouteImpossible(
                    f"Mémorisation suspendue ({suspendue}) : aucun cours n'est enregistré tant que ce mode est actif."
                )
            self.sous_titres.demarrer(NOM_ROBINET)  # lève EcouteImpossible : écoute, modèle, micro
            cours_id = uuid.uuid4().hex
            maintenant = datetime.now(timezone.utc)
            avertissement = None
            try:
                self.ctx.db.execute(
                    "INSERT INTO cours(id, debut, titre_enc, matiere_enc, source, etat, retenu_jusqua) VALUES(?,?,?,?,?,?,?)",
                    (cours_id, iso_utc(maintenant), self._chiffrer(titre), self._chiffrer(matiere), "direct", "en_direct",
                     self._retenu_jusqua()),
                )
                session = None
                dossier = dossier_audio(self.ctx)
                try:
                    session = SessionEnregistrement(self.ctx, dossier / nom_libre(dossier, "cours"), NOM_ROBINET,
                                                    fin=self._audio_fini)
                    session.demarrer()
                    self.ctx.db.execute("UPDATE cours SET audio=? WHERE id=?", (session.nom, cours_id))
                except EcouteImpossible as exc:
                    session, avertissement = None, f"Le cours est transcrit, mais pas enregistré : {exc.message}"
                except Exception as exc:
                    log.warning("enregistrement du cours impossible : %s", exc)
                    session, avertissement = None, "Le cours est transcrit, mais l'enregistrement audio n'a pas pu démarrer."
                self._actif = {"id": cours_id, "debut_epoch": maintenant.timestamp(), "session": session, "n": 0}
                self.sous_titres.abonner_finals(NOM_ROBINET, self._nouvelle_ligne)
            except Exception:
                self._actif = None
                self.sous_titres.arreter(NOM_ROBINET)
                self.ctx.db.execute("DELETE FROM cours WHERE id=?", (cours_id,))
                raise
        annoncer(self.ctx, "Enregistrement du cours.")
        self.ctx.consent.log("cours_debut", detail=cours_id)
        self._publier(cours_id)
        self._notifier()
        resume = self.cours_actif() or {}
        return {**resume, "avertissement": avertissement}

    def _nouvelle_ligne(self, moment: float, texte: str) -> None:
        """Abonné des sous-titres : chaque phrase finale du cours est écrite, chiffrée, dès qu'elle arrive."""
        with self._verrou:
            actif = self._actif
            if actif is None:
                return
            if memoire_suspendue(self.ctx):
                return  # la surveillance arrête le cours ; d'ici là, rien n'est écrit
            n = actif["n"]
            actif["n"] = n + 1
            ts = max(0.0, moment - actif["debut_epoch"])
            self.ctx.db.execute(
                "INSERT INTO cours_lignes(cours_id, n, ts, texte_enc) VALUES(?,?,?,?)",
                (actif["id"], n, round(ts, 2), self.ctx.crypto.encrypt(texte)),
            )
            cours_id = actif["id"]
            secondes = round(time.time() - actif["debut_epoch"], 1)
        self.ctx.hub.publish("cours.etat", id=cours_id, actif=True, secondes=secondes, lignes=n + 1,
                             etat="en_direct", progression=None)

    def _audio_fini(self, resultat: dict) -> None:
        if resultat.get("octets", 0) > 44:  # un WAV sans un seul bloc (micro jamais arrivé) est supprimé par arreter()
            self.ctx.hub.publish("album.nouveau", nom=resultat["nom"], genre="audio", octets=resultat["octets"])
        if resultat.get("automatique") and resultat.get("raison"):
            log.info("enregistrement du cours arrêté seul : %s", resultat["raison"])

    def arreter(self, cours_id: str, raison: str | None = None) -> dict | None:
        """Arrête le cours en direct. Idempotent : un cours déjà terminé est simplement renvoyé. None si inconnu."""
        with self._verrou:
            actif = self._actif if (self._actif is not None and self._actif["id"] == cours_id) else None
        if actif is None:
            row = self._ligne(cours_id)
            return self._resume(row) if row else None
        # Les sous-titres d'abord : s'ils s'arrêtent, leur dernière phrase arrive encore dans le cours.
        try:
            self.sous_titres.arreter(NOM_ROBINET)
        finally:
            with self._verrou:
                self._actif = None
            self.sous_titres.desabonner_finals(NOM_ROBINET)
        session = actif.get("session")
        audio = None
        if session is not None:
            resultat = session.arreter()
            audio = resultat["nom"] if resultat.get("octets", 0) > 44 else None
            if audio is None:
                try:
                    (dossier_audio(self.ctx) / session.nom).unlink(missing_ok=True)
                except OSError:
                    pass
        fin = datetime.now(timezone.utc)
        self.ctx.db.execute(
            "UPDATE cours SET fin=?, duree_s=?, etat='termine', audio=?, erreur=? WHERE id=?",
            (iso_utc(fin), round(fin.timestamp() - actif["debut_epoch"], 1), audio, raison, cours_id),
        )
        self.ctx.consent.log("cours_fin", detail=cours_id)
        self._publier(cours_id, raison=raison)
        self._notifier()
        row = self._ligne(cours_id)
        return self._resume(row) if row else None

    def verifier(self) -> None:
        """Appelée périodiquement : mode confidentiel ou mémoire suspendue arrêtent le cours ; sinon l'état est publié."""
        with self._verrou:
            actif = self._actif
        if actif is None:
            return
        if self.ctx.settings.user.privacy_mode:
            self.arreter(actif["id"], raison="Cours arrêté : le mode confidentiel a été activé.")
            return
        suspendue = memoire_suspendue(self.ctx)
        if suspendue:
            self.arreter(actif["id"], raison=f"Cours arrêté : mémorisation suspendue ({suspendue}). Ce qui précède est gardé.")
            return
        if time.monotonic() - self._dernier_etat >= INTERVALLE_ETAT_S:
            self._dernier_etat = time.monotonic()
            self._publier(actif["id"])

    # ------------------------------------------------------------------ import
    def importer(self, titre: str, matiere: str | None, nom_fichier: str | None, data: str) -> dict:
        """Importe un WAV et le transcrit localement dans un fil. Lève EcouteImpossible (409) ou ValueError (422)."""
        if self.ctx.settings.user.privacy_mode:
            raise EcouteImpossible("Mode confidentiel actif : aucune transcription ne démarre.")
        suspendue = memoire_suspendue(self.ctx)
        if suspendue:
            raise EcouteImpossible(f"Mémorisation suspendue ({suspendue}) : aucun cours n'est enregistré tant que ce mode est actif.")
        fabrique = self.sous_titres.fabrique_reconnaisseur
        if fabrique == self.sous_titres._reconnaisseur_vosk and not self.sous_titres.modele_pret():
            from .sous_titres import MODELE_ABSENT

            raise EcouteImpossible(MODELE_ABSENT)
        if not data:
            raise ValueError("Fichier manquant.")
        if len(data) > TAILLE_MAX_IMPORT * 4 // 3 + 16:
            raise ValueError("Fichier trop volumineux (plus de 600 Mo) : enregistrez en 16 kHz mono ou découpez le fichier.")
        try:
            octets = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Fichier illisible : le contenu n'est pas du base64 valide.")
        pcm, duree = lire_wav(octets)
        del octets
        dossier = dossier_audio(self.ctx)
        if espace_libre(dossier) < ESPACE_MIN_DEMARRAGE + len(pcm):
            raise EcouteImpossible("Espace disque insuffisant pour importer ce cours.")
        try:
            reconnaisseur = fabrique()
        except EcouteImpossible:
            raise
        except Exception as exc:
            log.warning("reconnaisseur hors ligne indisponible pour l'import : %s", exc)
            raise EcouteImpossible("La reconnaissance hors ligne n'a pas pu démarrer. Réinstallez le modèle dans Paramètres › Voix.")
        nom = nom_libre(dossier, "cours-import")
        ecrire_wav(dossier / nom, pcm)
        titre = (titre or "").strip()[:200] or (Path(nom_fichier or "").stem[:200] if nom_fichier else "") or "Cours importé"
        cours_id = uuid.uuid4().hex
        self.ctx.db.execute(
            "INSERT INTO cours(id, debut, fin, duree_s, titre_enc, matiere_enc, audio, source, etat, retenu_jusqua) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cours_id, iso_utc(datetime.now(timezone.utc)), None, round(duree, 1), self._chiffrer(titre),
             self._chiffrer((matiere or "").strip()[:120] or None), nom, "import", "transcription", self._retenu_jusqua()),
        )
        arret = threading.Event()
        self._imports[cours_id] = {"progression": 0.0, "arret": arret}
        threading.Thread(target=self._transcrire_import, args=(cours_id, reconnaisseur, pcm, arret),
                         name="iris-cours-import", daemon=True).start()
        self.ctx.hub.publish("album.nouveau", nom=nom, genre="audio", octets=(dossier / nom).stat().st_size)
        row = self._ligne(cours_id)
        return self._resume(row, 0)  # type: ignore[arg-type]

    def _transcrire_import(self, cours_id: str, reconnaisseur: Any, pcm: bytes, arret: threading.Event) -> None:
        dernier = [0.0]

        def progression(fraction: float) -> None:
            imp = self._imports.get(cours_id)
            if imp is not None:
                imp["progression"] = fraction
            if time.monotonic() - dernier[0] >= 1.0:
                dernier[0] = time.monotonic()
                self._publier(cours_id)

        etat, erreur = "termine", None
        try:
            lignes = transcrire_pcm(reconnaisseur, pcm, TAUX, arret=arret, progression=progression)
            if arret.is_set():
                etat, erreur = "erreur", "Transcription interrompue (arrêt d'IRIS ou suppression)."
            elif memoire_suspendue(self.ctx):
                etat, erreur = "erreur", "Mémorisation suspendue pendant la transcription : rien n'a été écrit. Réimportez le fichier."
            else:
                for n, ligne in enumerate(lignes):
                    self.ctx.db.execute(
                        "INSERT INTO cours_lignes(cours_id, n, ts, texte_enc) VALUES(?,?,?,?)",
                        (cours_id, n, ligne["ts"], self.ctx.crypto.encrypt(ligne["texte"])),
                    )
        except Exception as exc:
            log.exception("transcription d'un cours importé")
            etat, erreur = "erreur", "La transcription a échoué (erreur de reconnaissance). Réimportez le fichier."
        finally:
            self._imports.pop(cours_id, None)
        if self._ligne(cours_id) is None:
            return  # supprimé pendant la transcription
        self.ctx.db.execute("UPDATE cours SET etat=?, erreur=?, fin=? WHERE id=?",
                            (etat, erreur, iso_utc(datetime.now(timezone.utc)), cours_id))
        self._publier(cours_id)

    # ------------------------------------------------------------------ génération
    async def generer(self, cours_id: str, quoi: str) -> dict:
        """Fiches et/ou questions. Lève RefusMoteur (403/409/422/502) ou LookupError si le cours n'existe pas."""
        quoi = (quoi or "tout").strip().lower()
        if quoi not in ("fiches", "questions", "tout"):
            raise RefusMoteur(422, "« quoi » doit valoir fiches, questions ou tout.")
        row = self._ligne(cours_id)
        if row is None:
            raise LookupError(cours_id)
        if row.get("etat") == "transcription":
            raise RefusMoteur(409, "La transcription de ce cours n'est pas terminée : réessayez quand elle l'est.")
        suspendue = memoire_suspendue(self.ctx)
        if suspendue:
            raise RefusMoteur(409, f"Mémorisation suspendue ({suspendue}) : rien n'est écrit tant que ce mode est actif.")
        texte = texte_des_lignes(self.transcription(cours_id))
        if len(texte) < TRANSCRIPTION_MIN:
            raise RefusMoteur(422, "La transcription est trop courte pour rédiger des fiches ou des questions honnêtes.")
        with self._verrou:
            if cours_id in self._generations:
                raise RefusMoteur(409, "Une génération est déjà en cours pour ce cours.")
            self._generations.add(cours_id)
        try:
            titre = self._dechiffrer(row["titre_enc"]) or "Cours"
            matiere = self._dechiffrer(row.get("matiere_enc"))
            tranches = decouper(texte)
            if quoi in ("fiches", "tout"):
                fiches = await self._rediger_fiches(titre, matiere, tranches)
                self.ctx.db.execute("UPDATE cours SET fiches_enc=? WHERE id=?", (self._chiffrer(fiches), cours_id))
            if quoi in ("questions", "tout"):
                questions = await self._rediger_questions(titre, matiere, tranches, len(texte))
                self.ctx.db.execute("UPDATE cours SET questions_enc=? WHERE id=?",
                                    (self._chiffrer(json.dumps(questions, ensure_ascii=False)), cours_id))
        finally:
            with self._verrou:
                self._generations.discard(cours_id)
        self._publier(cours_id)
        return self.detail(cours_id)  # type: ignore[return-value]

    def _entete(self, titre: str, matiere: str | None) -> str:
        return f"Cours : « {titre} »" + (f" (matière : {matiere})" if matiere else "")

    async def _rediger_fiches(self, titre: str, matiere: str | None, tranches: list[str]) -> str:
        systeme = f"Tu prépares des fiches de révision pour un étudiant. {CONSIGNE_FIDELITE} Réponds en Markdown."
        sections = (
            "## Notions clés\n## Définitions\n## Formules (seulement celles qui sont dites ; sinon écris « Aucune formule "
            "dans la transcription »)\n## Exemples\n## Résumé par section"
        )
        entete = self._entete(titre, matiere)
        if len(tranches) == 1:
            r = await demander_moteur(self.ctx, systeme,
                                      f"{entete}\nRédige les fiches de révision avec exactement ces sections :\n{sections}\n\n"
                                      f"Transcription :\n{tranches[0]}", f"fiches de révision ({titre})")
            corps = r["texte"]
        else:
            notes = []
            for i, tranche in enumerate(tranches, 1):
                r = await demander_moteur(
                    self.ctx, systeme,
                    f"{entete}\nPartie {i} sur {len(tranches)}. Note en puces : notions clés, définitions, formules "
                    f"dites, exemples, et un résumé de cette partie.\n\nTranscription :\n{tranche}",
                    f"fiches de révision ({titre}), partie {i}/{len(tranches)}",
                )
                notes.append(f"### Partie {i}\n{r['texte']}")
            r = await demander_moteur(
                self.ctx, systeme,
                f"{entete}\nFusionne ces notes en fiches de révision, sans doublons, avec exactement ces sections "
                f"(le résumé par section suit l'ordre des parties) :\n{sections}\n\nNotes :\n" + "\n\n".join(notes),
                f"fiches de révision ({titre}), fusion de {len(tranches)} parties",
            )
            corps = r["texte"]
        return f"# Fiches de révision — {titre}\n\n{AVERTISSEMENT_FICHES}\n\n{corps.strip()}\n"

    async def _rediger_questions(self, titre: str, matiere: str | None, tranches: list[str], longueur: int) -> list[dict]:
        # 10 à 25 questions, selon la matière disponible ; un cours très court en donne moins plutôt
        # que des questions inventées.
        cible = min(QUESTIONS_MAX, max(QUESTIONS_MIN, longueur // 1200))
        court = longueur < 2500
        par_tranche = max(2, math.ceil(cible / len(tranches)) + 1)
        systeme = (
            "Tu prépares des questions d'examen probables pour un étudiant, avec leurs réponses. "
            f"{CONSIGNE_FIDELITE} Les questions portent UNIQUEMENT sur ce qui est enseigné dans la transcription. "
            "Réponds SEULEMENT par un tableau JSON, sans texte autour : "
            '[{"question": "...", "reponse": "...", "type": "definition|application|comprehension|calcul|vrai_faux", '
            '"difficulte": 1|2|3}]'
        )
        entete = self._entete(titre, matiere)
        par_partie: list[list[dict]] = []
        for i, tranche in enumerate(tranches, 1):
            combien = (f"jusqu'à {cible} questions, seulement autant que le contenu le permet" if court
                       else f"{par_tranche} questions")
            r = await demander_moteur(
                self.ctx, systeme,
                f"{entete}\nPartie {i} sur {len(tranches)}. Propose {combien}, en variant les types et les difficultés."
                f"\n\nTranscription :\n{tranche}",
                f"questions d'examen ({titre}), partie {i}/{len(tranches)}",
            )
            par_partie.append(lire_questions(r["texte"]))
        # Tour de rôle entre les parties : les questions couvrent tout le cours, pas seulement le début.
        retenues: list[dict] = []
        vues: set[str] = set()
        rang = 0
        while len(retenues) < cible and any(rang < len(p) for p in par_partie):
            for partie in par_partie:
                if rang < len(partie) and len(retenues) < cible:
                    cle = sans_accents(partie[rang]["question"])
                    if cle not in vues:
                        vues.add(cle)
                        retenues.append(partie[rang])
            rang += 1
        if not retenues:
            raise RefusMoteur(502, "Le moteur VELA n'a pas rendu de questions exploitables. Réessayez dans un instant.")
        return retenues

    # ------------------------------------------------------------------ export, suppression, entretien
    def exporter(self, cours_id: str) -> str | None:
        d = self.detail(cours_id)
        if d is None:
            return None
        lignes = [f"# {d['titre']}", ""]
        if d.get("matiere"):
            lignes.append(f"- Matière : {d['matiere']}")
        lignes += [f"- Début : {d['debut']}", f"- Durée : {horodatage(d['duree_s'])}",
                   f"- Phrases transcrites : {d['lignes']}", "",
                   "> Transcription automatique faite sur l'ordinateur : approximative, sans ponctuation.", ""]
        if d.get("fiches"):
            lignes += [d["fiches"].strip(), ""]
        if d.get("questions"):
            lignes += ["## Questions d'examen probables", ""]
            for i, q in enumerate(d["questions"], 1):
                lignes += [f"{i}. **{q['question']}** _({q['type'].replace('_', ' ')}, difficulté {q['difficulte']}/3)_",
                           f"   - Réponse : {q['reponse']}"]
            lignes.append("")
        lignes += ["## Transcription", ""]
        lignes += [f"- [{horodatage(l['ts'])}] {l['texte']}" for l in d["transcription"]] or ["(vide)"]
        return "\n".join(lignes) + "\n"

    def supprimer(self, cours_id: str) -> bool:
        row = self._ligne(cours_id)
        if row is None:
            return False
        if self._actif is not None and self._actif["id"] == cours_id:
            self.arreter(cours_id)
            row = self._ligne(cours_id) or row
        imp = self._imports.get(cours_id)
        if imp is not None:
            imp["arret"].set()
        self.ctx.db.execute("DELETE FROM cours_lignes WHERE cours_id=?", (cours_id,))
        self.ctx.db.execute("DELETE FROM cours WHERE id=?", (cours_id,))
        nom = nom_sur(row.get("audio"))
        if nom:
            try:
                (dossier_audio(self.ctx) / nom).unlink(missing_ok=True)
            except OSError as exc:
                log.warning("fichier du cours non supprimé (%s) : %s", nom, exc)
        self.ctx.consent.log("cours_supprime", detail=cours_id)
        self._notifier()
        return True

    def fichiers_en_cours(self) -> set[str]:
        with self._verrou:
            session = (self._actif or {}).get("session")
        return {session.nom} if session is not None else set()

    def reparer(self) -> int:
        """Au démarrage : un cours resté « en direct » ou « en transcription » a été coupé par l'arrêt d'IRIS."""
        n = 0
        for row in self.ctx.db.query("SELECT id, debut FROM cours WHERE etat='en_direct'"):
            dernier = self.ctx.db.one("SELECT MAX(ts) AS t FROM cours_lignes WHERE cours_id=?", (row["id"],))
            duree = float((dernier or {}).get("t") or 0)
            fin = datetime.fromisoformat(row["debut"]) + timedelta(seconds=duree)
            self.ctx.db.execute(
                "UPDATE cours SET etat='termine', fin=?, duree_s=?, erreur=? WHERE id=?",
                (iso_utc(fin), round(duree, 1),
                 "Cours interrompu par l'arrêt d'IRIS : la transcription est gardée jusqu'à la dernière phrase.", row["id"]),
            )
            n += 1
        cur = self.ctx.db.execute(
            "UPDATE cours SET etat='erreur', erreur=? WHERE etat='transcription'",
            ("Transcription interrompue par l'arrêt d'IRIS : importez le fichier de nouveau.",),
        )
        return n + max(0, cur.rowcount)

    def purger(self) -> int:
        """Rétention : supprime les cours expirés (jamais le cours en direct), avec leur fichier audio."""
        maintenant = datetime.now(timezone.utc)
        jours = int(getattr(self.ctx.settings.user, "retention_days", 0) or 0)
        rows = self.ctx.db.query(
            "SELECT id FROM cours WHERE retenu_jusqua IS NOT NULL AND retenu_jusqua < ?", (iso_utc(maintenant),))
        if jours > 0:
            rows += self.ctx.db.query("SELECT id FROM cours WHERE debut < ?",
                                      (iso_utc(maintenant - timedelta(days=jours)),))
        n = 0
        for cours_id in {r["id"] for r in rows}:
            if (self._actif is not None and self._actif["id"] == cours_id) or cours_id in self._imports:
                continue
            if self.supprimer(cours_id):
                n += 1
        return n

    def fermer(self) -> None:
        """Arrêt d'IRIS : le cours en direct est terminé proprement (WAV fermé), les imports interrompus."""
        with self._verrou:
            actif = self._actif
        if actif is not None:
            try:
                self.arreter(actif["id"], raison="Cours arrêté par la fermeture d'IRIS.")
            except Exception as exc:  # pragma: no cover
                log.warning("arrêt du cours à la fermeture : %s", exc)
        for imp in list(self._imports.values()):
            imp["arret"].set()
