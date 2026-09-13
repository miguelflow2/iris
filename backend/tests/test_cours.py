"""Mode cours et procès-verbal (interface C) : faux reconnaisseur, faux moteur, WAV générés, sans réseau.

Prouvé ici : cours en direct (sous-titres + WAV + transcription chiffrée), refus en mémoire suspendue,
arrêt par l'entretien, fiches et questions par découpage avec consentement et registre, refus en
mode local, import WAV (rééchantillonnage, refus des autres formats), export Markdown, suppression,
réparation après un arrêt brutal, procès-verbal.
"""
from __future__ import annotations

import base64
import io
import json
import struct
import threading
import time
import wave

import numpy as np
import pytest

from iris import cours as cours_mod
from iris.cours import AVERTISSEMENT_FICHES, decouper, lire_questions, lire_wav

PAROLE = (np.sin(np.arange(4000) * 2 * np.pi * 220 / 16000) * 9000).astype(np.int16).tobytes()
SILENCE = np.zeros(4000, dtype=np.int16).tobytes()


class FauxReconnaisseur:
    """Protocole Vosk : une phrase par rafale de parole suivie d'un silence."""

    def __init__(self, phrases):
        self.phrases = list(phrases)
        self.parole = 0
        self.final = ""

    def AcceptWaveform(self, bloc):
        pic = int(np.abs(np.frombuffer(bloc[: len(bloc) // 2 * 2], dtype=np.int16)).max()) if len(bloc) >= 2 else 0
        if pic > 1000:
            self.parole += 1
            return False
        if self.parole:
            self.parole = 0
            self.final = self.phrases.pop(0) if self.phrases else ""
            return True
        return False

    def Result(self):
        texte, self.final = self.final, ""
        return json.dumps({"text": texte})

    def PartialResult(self):
        return json.dumps({"partial": self.phrases[0] if (self.parole and self.phrases) else ""})

    def FinalResult(self):
        return json.dumps({"text": ""})


def attendre(condition, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture()
def ecoute(app):
    voice = app.state.ctx.voice
    voice._stop.clear()
    fil = threading.Thread(target=voice._stop.wait, daemon=True)
    fil.start()
    voice._thread = fil
    app.state.ctx.tts.speak = lambda *a, **k: True  # pas de voix réelle pendant les tests
    yield voice
    voice._stop.set()
    fil.join(timeout=1)


@pytest.fixture()
def moteur(app, monkeypatch):
    """Faux moteur : consentement accordé, moteur externe « vela », réponses selon la consigne."""
    ctx = app.state.ctx
    ctx.consent.set("transcript", True)
    monkeypatch.setattr(cours_mod, "agent_pour_texte", lambda _ctx, _m: ("vela", False))
    appels: list[tuple[str, str]] = []

    async def demander_court(systeme: str, message: str) -> str:
        appels.append((systeme, message))
        if "tableau JSON" in systeme:
            return "```json\n" + json.dumps([
                {"question": f"Question {len(appels)}-{i} sur la photosynthèse ?", "reponse": "La lumière.",
                 "type": "Vrai faux" if i == 0 else "définition", "difficulte": 7 if i == 1 else 2}
                for i in range(3)
            ] + [{"question": "", "reponse": "invalide"}], ensure_ascii=False) + "\n```"
        if "Fusionne" in message:
            return "## Notions clés\n- fusion"
        if "Partie" in message:
            return "- notes de la partie"
        return "## Points clés\n- La photosynthèse transforme la lumière."

    monkeypatch.setattr(ctx.chat, "demander_court", demander_court)
    return appels


def _wav(pcm: bytes, taux: int = 16000, canaux: int = 1, largeur: int = 2) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(canaux)
        w.setsampwidth(largeur)
        w.setframerate(taux)
        w.writeframes(pcm)
    return tampon.getvalue()


def _cours_avec_transcription(ctx, lignes: list[str]) -> str:
    """Un cours terminé écrit directement en base, pour tester la rédaction sans passer par le direct."""
    import uuid

    cid = uuid.uuid4().hex
    ctx.db.execute("INSERT INTO cours(id, debut, titre_enc, etat) VALUES(?,?,?,?)",
                   (cid, "2026-09-13T13:00:00.000000+00:00", ctx.crypto.encrypt("Biologie 101"), "termine"))
    for n, texte in enumerate(lignes):
        ctx.db.execute("INSERT INTO cours_lignes(cours_id, n, ts, texte_enc) VALUES(?,?,?,?)",
                       (cid, n, float(n * 5), ctx.crypto.encrypt(texte)))
    return cid


def test_cours_en_direct_transcrit_enregistre_et_chiffre(ecoute, client, app):
    ctx = app.state.ctx
    ctx.sous_titres.fabrique_reconnaisseur = lambda: FauxReconnaisseur(
        ["aujourd'hui la photosynthèse", "la chlorophylle capte la lumière"])
    r = client.post("/api/cours/demarrer", json={"titre": "Biologie 101", "matiere": "Biologie"})
    assert r.status_code == 200, r.text
    cours = r.json()
    assert cours["actif"] is True and cours["etat"] == "en_direct" and cours["avertissement"] is None
    assert client.post("/api/cours/demarrer", json={"titre": "Autre"}).status_code == 409, "un seul cours à la fois"
    assert set(ecoute.robinet.abonnes()) >= {"sous-titres", "cours"}
    for rafale in (4, 3):
        for _ in range(rafale):
            ecoute.robinet.publier(PAROLE)
        ecoute.robinet.publier(SILENCE)
    assert attendre(lambda: ctx.cours._actif is not None and ctx.cours._actif["n"] == 2)
    fin = client.post(f"/api/cours/{cours['id']}/arreter").json()
    assert fin["actif"] is False and fin["etat"] == "termine" and fin["lignes"] == 2
    assert fin["audio"] and fin["audio"].startswith("cours-")
    assert client.post(f"/api/cours/{cours['id']}/arreter").status_code == 200, "arrêter deux fois ne casse rien"
    detail = client.get(f"/api/cours/{cours['id']}").json()
    assert [l["texte"] for l in detail["transcription"]] == ["Aujourd'hui la photosynthèse", "La chlorophylle capte la lumière"]
    assert detail["fiches"] is None and detail["questions"] is None and detail["matiere"] == "Biologie"
    with wave.open(str(ctx.settings.data_dir / "captures" / "audio" / fin["audio"]), "rb") as w:
        assert w.getframerate() == 16000 and w.getnframes() == 4000 * 9
    brut = ctx.db.query("SELECT texte_enc FROM cours_lignes") + ctx.db.query("SELECT titre_enc AS texte_enc FROM cours")
    assert all(b"photosynth" not in bytes(r["texte_enc"]) and b"Biologie" not in bytes(r["texte_enc"]) for r in brut)
    liste = client.get("/api/cours").json()["cours"]
    assert liste[0]["id"] == cours["id"] and liste[0]["lignes"] == 2 and liste[0]["audio"] == fin["audio"]
    assert "sous-titres" not in ecoute.robinet.abonnes() and "cours" not in ecoute.robinet.abonnes()


def test_memoire_suspendue_le_cours_refuse_et_lentretien_arrete(ecoute, client, app):
    ctx = app.state.ctx
    ctx.sous_titres.fabrique_reconnaisseur = lambda: FauxReconnaisseur([])
    ctx.memory.suspendre("invite")
    try:
        r = client.post("/api/cours/demarrer", json={"titre": "Chimie"})
        assert r.status_code == 409 and "invite" in r.json()["detail"]
        assert client.get("/api/cours").json()["cours"] == []
        assert client.post("/api/cours/importer", json={"data": base64.b64encode(_wav(SILENCE)).decode()}).status_code == 409
    finally:
        ctx.memory.reprendre("invite")
    cours = client.post("/api/cours/demarrer", json={"titre": "Chimie"}).json()
    ctx.memory.suspendre("zone:Clinique")
    try:
        ctx.ecoute_tic()
        d = client.get(f"/api/cours/{cours['id']}").json()
        assert d["actif"] is False and "zone:Clinique" in (d["erreur"] or "")
    finally:
        ctx.memory.reprendre("zone:Clinique")


def test_fiches_et_questions_par_decoupage_avec_consentement(client, app, moteur):
    ctx = app.state.ctx
    phrase = "la photosynthèse transforme l'énergie lumineuse en énergie chimique dans les chloroplastes " * 4
    cid = _cours_avec_transcription(ctx, [phrase] * 40)  # ≈ 14 000 caractères : trois tranches
    r = client.post(f"/api/cours/{cid}/generer", json={"quoi": "tout"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fiches"].startswith("# Fiches de révision — Biologie 101") and AVERTISSEMENT_FICHES in d["fiches"]
    assert "fusion" in d["fiches"]
    questions = d["questions"]
    assert 1 <= len(questions) <= 25
    assert {q["type"] for q in questions} <= set(cours_mod.TYPES_QUESTIONS)
    assert all(1 <= q["difficulte"] <= 3 and q["question"] and q["reponse"] for q in questions)
    assert questions[0]["type"] == "vrai_faux"
    # 3 tranches + fusion pour les fiches, 3 tranches pour les questions ; aucune tranche au-delà de 6000 caractères.
    assert len(moteur) == 7
    assert all(len(m) < cours_mod.TAILLE_TRANCHE + 1000 for _s, m in moteur)
    registre = [e for e in ctx.consent.events() if e["event_type"] == "external_send" and e["data_type"] == "transcript"]
    assert len(registre) == 7
    liste = client.get("/api/cours").json()["cours"][0]
    assert liste["fiches"] is True and liste["questions"] is True
    md = client.get(f"/api/cours/{cid}/exporter")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "## Questions d'examen probables" in md.text and "[00:00:05]" in md.text


def test_generation_refusee_sans_consentement_en_mode_local_ou_trop_courte(client, app, moteur, monkeypatch):
    ctx = app.state.ctx
    cid = _cours_avec_transcription(ctx, ["un cours assez long pour être résumé honnêtement par le moteur"] * 10)
    court = _cours_avec_transcription(ctx, ["trop court"])
    assert client.post(f"/api/cours/{court}/generer", json={"quoi": "fiches"}).status_code == 422
    ctx.consent.set("transcript", False)
    r = client.post(f"/api/cours/{cid}/generer", json={"quoi": "fiches"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consentement"
    ctx.consent.set("transcript", True)
    ctx.settings.user.local_only = True
    try:
        # Mode local sans IA locale : la sélection du moteur échoue, et rien ne part.
        from iris.router import NoAgentAvailable

        def sans_moteur(_ctx, _m):
            raise NoAgentAvailable("aucune IA locale")

        monkeypatch.setattr(cours_mod, "agent_pour_texte", sans_moteur)
        r = client.post(f"/api/cours/{cid}/generer", json={"quoi": "questions"})
        assert r.status_code == 409 and "local" in r.json()["detail"]
        assert client.post("/api/ecoute/resume", json={"lignes": ["bonjour"]}).status_code == 409
    finally:
        ctx.settings.user.local_only = False
    assert moteur == [], "aucun envoi au moteur n'a eu lieu"
    assert client.post("/api/cours/inconnu/generer", json={"quoi": "tout"}).status_code == 404


def test_mode_local_reel_sans_ia_locale_refuse(client, app):
    ctx = app.state.ctx
    ctx.consent.set("transcript", True)
    ctx.settings.user.local_only = True
    try:
        r = client.post("/api/ecoute/resume", json={"lignes": [{"ts": 1, "texte": "on décide de livrer lundi"}]})
        assert r.status_code == 409 and "local" in r.json()["detail"].lower()
    finally:
        ctx.settings.user.local_only = False


def test_import_wav_reechantillonne_et_transcrit(client, app):
    ctx = app.state.ctx
    ctx.sous_titres.fabrique_reconnaisseur = lambda: FauxReconnaisseur(["premier point du cours", "second point"])
    # 44,1 kHz stéréo : parole 1 s, silence 0,5 s, parole 1 s, silence 0,5 s.
    t = np.arange(44100)
    ton = (np.sin(t * 2 * np.pi * 220 / 44100) * 9000).astype(np.int16)
    muet = np.zeros(22050, dtype=np.int16)
    mono = np.concatenate([ton, muet, ton, muet])
    stereo = np.repeat(mono, 2).astype("<i2").tobytes()
    donnees = base64.b64encode(_wav(stereo, 44100, 2)).decode()
    r = client.post("/api/cours/importer", json={"titre": "", "matiere": "Bio", "nom_fichier": "Cours 3.wav", "data": donnees})
    assert r.status_code == 200, r.text
    cours = r.json()
    assert cours["titre"] == "Cours 3" and cours["source"] == "import" and abs(cours["duree_s"] - 3.0) < 0.05
    assert attendre(lambda: client.get(f"/api/cours/{cours['id']}").json()["etat"] == "termine")
    d = client.get(f"/api/cours/{cours['id']}").json()
    assert [l["texte"] for l in d["transcription"]] == ["Premier point du cours", "Second point"]
    assert d["transcription"][0]["ts"] < d["transcription"][1]["ts"]
    with wave.open(str(ctx.settings.data_dir / "captures" / "audio" / d["audio"]), "rb") as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000) and abs(w.getnframes() - 48000) <= 2
    # Suppression : le cours et son WAV disparaissent.
    assert client.delete(f"/api/cours/{cours['id']}").json() == {"supprime": True}
    assert not (ctx.settings.data_dir / "captures" / "audio" / d["audio"]).exists()
    assert client.get(f"/api/cours/{cours['id']}").status_code == 404


def test_import_refuse_clairement_les_autres_formats(client, app):
    app.state.ctx.sous_titres.fabrique_reconnaisseur = lambda: FauxReconnaisseur([])
    mp3 = base64.b64encode(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 200).decode()
    r = client.post("/api/cours/importer", json={"titre": "x", "data": mp3})
    assert r.status_code == 422 and "WAV" in r.json()["detail"]
    # WAV en virgule flottante (format 3) : refusé avec un message qui dit quoi faire.
    donnees = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + 8, b"WAVE", b"fmt ", 16, 3, 1, 16000, 64000, 4, 32,
                          b"data", 8) + b"\x00" * 8
    r = client.post("/api/cours/importer", json={"titre": "x", "data": base64.b64encode(donnees).decode()})
    assert r.status_code == 422 and "PCM" in r.json()["detail"]
    assert client.post("/api/cours/importer", json={"titre": "x", "data": "pas du base64 !"}).status_code == 422


def test_lire_wav_formats_entiers():
    un_quart = (np.sin(np.arange(12000) * 0.05) * 10000).astype(np.int16)
    pcm, duree = lire_wav(_wav(un_quart.astype("<i2").tobytes(), 48000))
    assert len(pcm) == 4000 * 2 and abs(duree - 0.25) < 1e-6
    huit = ((un_quart[:8000] // 256) + 128).astype(np.uint8).tobytes()
    pcm8, _ = lire_wav(_wav(huit, 8000, 1, 1))
    assert len(pcm8) == 16000 * 2, "8 kHz 8 bits : montée à 16 kHz"
    with pytest.raises(ValueError):
        lire_wav(_wav(b"", 16000))


def test_proces_verbal_decoupe_et_fusionne(client, app, moteur):
    r = client.post("/api/ecoute/resume", json={"lignes": ["on décide de livrer lundi", "Julie prépare la démo"]})
    assert r.status_code == 200 and r.json()["resume"].startswith("## Points clés") and r.json()["local"] is False
    assert len(moteur) == 1 and "procès-verbal" in moteur[0][0]
    moteur.clear()
    longues = [{"ts": i, "texte": "Julie présente le budget du trimestre et les actions à venir " * 5} for i in range(40)]
    assert client.post("/api/ecoute/resume", json={"lignes": longues}).status_code == 200
    assert len(moteur) >= 3 and "Fusionne" in moteur[-1][1]
    assert client.post("/api/ecoute/resume", json={"lignes": []}).status_code == 422


def test_decoupage_et_lecture_des_questions():
    assert decouper("aaa\n" * 3, taille=4) == ["aaa", "aaa", "aaa"]
    assert all(len(t) <= 50 for t in decouper("mot " * 100, taille=50))
    assert lire_questions("rien d'utile") == []
    assert lire_questions('[{"question": "Q ?", "reponse": "R", "type": "calcul", "difficulte": "3"}]')[0]["difficulte"] == 3


def test_reparer_les_cours_interrompus(app):
    ctx = app.state.ctx
    cid = _cours_avec_transcription(ctx, ["une", "deux", "trois"])
    ctx.db.execute("UPDATE cours SET etat='en_direct' WHERE id=?", (cid,))
    ctx.db.execute("INSERT INTO cours(id, debut, titre_enc, etat) VALUES(?,?,?,?)",
                   ("imp", "2026-09-13T13:00:00.000000+00:00", ctx.crypto.encrypt("Import"), "transcription"))
    assert ctx.cours.reparer() == 2
    d = ctx.cours.detail(cid)
    assert d["etat"] == "termine" and d["duree_s"] == 10.0 and "interrompu" in d["erreur"]
    assert ctx.cours.detail("imp")["etat"] == "erreur"
