"""Détection du mot d'activation : grammaire Vosk, faux positifs, rattrapage de la commande.

Les tests qui ont besoin du modèle Vosk français sont ignorés s'il n'est pas installé sur la machine.
Les fichiers audio de référence sont générés une fois dans release/wake-test/ (voix de synthèse française).
"""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import pytest

from iris.voice.listener import contains_wake, find_wake_phrase, normalize, wake_phrases

WAKE = "Dis-moi Iris"
ALIASES = ["dis moi iris", "dis iris", "iris", "dit moi iris"]
AUDIO_DIR = Path(__file__).resolve().parents[2] / "release" / "wake-test"


def _model_path() -> Path | None:
    p = Path(os.path.expandvars(r"%APPDATA%\IRIS\iris-data\models\vosk-model-small-fr-0.22"))
    return p if p.is_dir() else None


# --------------------------------------------------------------------------- sans modèle
def test_wake_phrases_normalise_et_dedoublonne():
    phrases = wake_phrases(WAKE, ALIASES)
    assert phrases[0] == "dis moi iris"
    assert len(phrases) == len(set(phrases))
    assert "iris" in phrases


@pytest.mark.parametrize(
    "words, attendu",
    [
        (["dis", "moi", "iris"], 3),
        (["dis", "iris"], 2),
        (["iris"], 1),
        (["dis"], -1),  # mot isolé de la grammaire : ce n'est pas une activation
        (["moi"], -1),
        ([], -1),
    ],
)
def test_find_wake_phrase(words, attendu):
    assert find_wake_phrase(words, wake_phrases(WAKE, ALIASES)) == attendu


@pytest.mark.parametrize("phrase", ["j irais bien au cinema", "ris", "dis moi i risque", "le riz est cuit"])
def test_contains_wake_refuse_les_faux_positifs(phrase):
    """Ces phrases déclenchaient IRIS avant le durcissement de la correspondance d'un alias d'un seul mot."""
    found, _rest = contains_wake(phrase, WAKE, aliases=ALIASES)
    assert not found, f"faux positif sur {phrase!r}"


@pytest.mark.parametrize(
    "phrase, reste",
    [
        ("dis moi iris ouvre mon navigateur", "ouvre mon navigateur"),
        ("dis iris quelle heure est il", "quelle heure est il"),
        ("iris ouvre youtube", "ouvre youtube"),
    ],
)
def test_contains_wake_accepte_et_rend_la_commande(phrase, reste):
    found, rest = contains_wake(phrase, WAKE, aliases=ALIASES)
    assert found and rest == reste


# --------------------------------------------------------------------------- avec le modèle Vosk
def _read_wav_16k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return w.readframes(w.getnframes())


@pytest.mark.skipif(_model_path() is None, reason="modèle Vosk français absent")
@pytest.mark.skipif(not AUDIO_DIR.is_dir(), reason="échantillons audio absents")
def test_grammaire_detecte_ce_que_le_plein_vocabulaire_perd():
    """« Dis-moi Iris » et « Iris » sont perdus en plein vocabulaire (mesuré : « dis-moi », « arès »).
    La grammaire restreinte les reconnaît, et refuse les phrases sans mot d'activation."""
    from iris.voice.stt import VoskEngine

    engine = VoskEngine(_model_path())
    phrases = wake_phrases(WAKE, ALIASES)
    cas = {"w0.wav": True, "w1.wav": True, "w2.wav": True, "w3.wav": True, "w4.wav": False, "w5.wav": False}
    for nom, attendu in cas.items():
        fichier = AUDIO_DIR / nom
        if not fichier.exists():
            continue
        rec = engine.recognizer(phrases, words=True)
        rec.AcceptWaveform(_read_wav_16k(fichier))
        mots = [m for m in VoskEngine.text_of(rec.FinalResult()).split() if m != "[unk]"]
        detecte = find_wake_phrase(mots, phrases) >= 0
        assert detecte is attendu, f"{nom} : détecté={detecte}, attendu={attendu} (mots {mots})"


@pytest.mark.skipif(_model_path() is None, reason="modèle Vosk français absent")
@pytest.mark.skipif(not (AUDIO_DIR / "w1.wav").exists(), reason="échantillon audio absent")
def test_commande_dite_dans_le_meme_souffle_est_rejouee():
    """« Dis-moi Iris, ouvre mon navigateur » : la grammaire rend « [unk] » pour la commande.
    Les horodatages de mots permettent de rejouer cet audio dans le reconnaisseur complet."""
    from iris.voice import stt
    from iris.voice.stt import VoskEngine

    engine = VoskEngine(_model_path())
    phrases = wake_phrases(WAKE, ALIASES)
    pcm = _read_wav_16k(AUDIO_DIR / "w1.wav")

    rec = engine.recognizer(phrases, words=True)
    resultat, pending, offset = "", [], 0
    for i in range(0, len(pcm), 8000):
        bloc = pcm[i : i + 8000]
        pending.append((offset, bloc))
        offset += len(bloc) // 2
        if rec.AcceptWaveform(bloc):
            resultat = rec.Result()
            break
    resultat = resultat or rec.FinalResult()
    mots = [m for m in VoskEngine.text_of(resultat).split() if m != "[unk]"]
    cut = find_wake_phrase(mots, phrases)
    assert cut > 0

    parles = [m for m in (json.loads(resultat).get("result") or []) if m.get("word") != "[unk]"]
    fin_activation = float(parles[cut - 1]["end"])
    assert (len(pcm) / 2 / stt.SAMPLE_RATE) - fin_activation >= 0.3  # il reste bien de la parole après « Iris »

    # On rejoue l'énoncé entier dans le reconnaisseur complet, puis on retire le mot d'activation du texte.
    rec2 = engine.recognizer()
    rec2.AcceptWaveform(pcm)
    tout = VoskEngine.text_of(rec2.FinalResult())
    trouve, commande = contains_wake(tout, WAKE, aliases=ALIASES)
    assert trouve, f"mot d'activation absent du rejeu : {tout!r}"
    assert "ouvre" in commande and "navigateur" in commande, f"commande rejouée : {commande!r}"


# --------------------------------------------------------------------------- fenêtre de dialogue
# Demande de Miguel : « je ne veux plus avoir à dire IRIS à chaque fois que je veux donner une
# commande ». Après une réponse, IRIS reste ouverte un moment ; chaque échange relance le compte ;
# « arrête » referme la fenêtre et le mot d'activation redevient nécessaire.
def _preparer(voice, monkeypatch, dits):
    traites: list[str] = []
    restants = list(dits)
    monkeypatch.setattr(voice, "_drain", lambda: None)
    monkeypatch.setattr(voice, "_set_state", lambda *a, **k: None)
    monkeypatch.setattr(voice, "_listen_command", lambda *a, **k: restants.pop(0) if restants else "")
    monkeypatch.setattr(voice, "_process", lambda texte, **k: traites.append(texte))
    voice._one_shot = False
    voice._stop.clear()
    return traites


def test_on_enchaine_sans_repeter_le_mot_dactivation(app, monkeypatch):
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"voice_conversation_seconds": 30})
    traites = _preparer(voice, monkeypatch, ["ouvre spotify", "monte le son", "arrête"])
    voice._fenetre_dialogue()
    assert traites == ["ouvre spotify", "monte le son"], "« arrête » ne doit pas être traité comme une demande"


def test_le_nom_redit_pendant_la_fenetre_nest_pas_pris_pour_la_demande(app, monkeypatch):
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"voice_conversation_seconds": 30})
    traites = _preparer(voice, monkeypatch, ["dis moi iris ouvre google", "stop"])
    voice._fenetre_dialogue()
    assert traites == ["ouvre google"]


def test_le_silence_referme_la_fenetre_tout_seul(app, monkeypatch):
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"voice_conversation_seconds": 1})
    traites = _preparer(voice, monkeypatch, [])  # personne ne parle
    voice._fenetre_dialogue()
    assert traites == []


def test_la_fenetre_peut_etre_desactivee(app, monkeypatch):
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"voice_conversation_seconds": 0})
    appels: list[str] = []
    monkeypatch.setattr(voice, "_listen_command", lambda *a, **k: appels.append("écoute") or "")
    voice._one_shot = False
    voice._stop.clear()
    voice._fenetre_dialogue()
    assert appels == [], "à 0 seconde, IRIS ne doit pas rester ouverte du tout"


def test_les_mots_darret_sont_ceux_des_reglages(app):
    voice = app.state.ctx.voice
    for ordre in ("arrête", "stop", "chut", "ça suffit", "tais-toi", "ok arrête merci"):
        assert voice._est_arret(ordre), ordre
    # Le piège : ces phrases contiennent un mot d'arrêt mais sont des commandes.
    for commande in ("arrête la musique", "stop le minuteur", "ouvre spotify", ""):
        assert not voice._est_arret(commande), commande


# --------------------------------------------------------------------------- le verrou des lunettes
# Décision commerciale de Miguel : « il faudrait sans faute qu'IRIS marche quand on est connecté
# avec des lunettes », pour que personne ne se dise que l'application suffit. Le verrou porte sur
# le pilotage vocal, pas sur le chat écrit.
def test_sans_lunettes_la_voix_refuse_de_demarrer(app):
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    etat = voice.start()
    assert etat["state"] == "off"
    assert "lunettes" in (etat["error"] or "").lower()
    assert voice.running is False


def test_le_message_dit_ce_qui_reste_possible(app):
    """Un refus sec ferait croire à une panne. Le chat écrit, lui, reste ouvert."""
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    message = voice.lunettes_requises()
    assert "VELA" in message and "écrit" in message


def test_avec_les_lunettes_le_verrou_seffance(app):
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: True
    assert voice.lunettes_requises() is None


def test_lechappatoire_de_demonstration_existe_et_reste_hors_interface(app):
    """Sur scène, une déconnexion Bluetooth ne doit pas faire taire IRIS."""
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    app.state.ctx.settings.update({"demo_sans_lunettes": True})
    assert voice.lunettes_requises() is None

    reglages = Path(__file__).resolve().parents[2] / "renderer" / "src" / "views" / "SettingsView.tsx"
    assert "demo_sans_lunettes" not in reglages.read_text(encoding="utf-8"),         "ce réglage ne doit apparaître dans aucun écran vu par un client"


def test_letat_publie_la_raison_du_verrou(app):
    """L'interface doit pouvoir expliquer le silence plutôt que de laisser croire à un bogue."""
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    assert voice.status()["glasses_required"]
    voice.glasses_connected = lambda: True
    assert voice.status()["glasses_required"] is None


# --------------------------------------------------------------------------- la preuve de presence
# Erreur de conception trouvee par une relecture adverse. Le verrou exigeait une preuve Bluetooth
# BASSE ENERGIE, alors qu'IRIS parle et ecoute par le Bluetooth CLASSIQUE. Le 5 septembre 2026, les
# services du fabricant ont disparu du canal basse energie pendant que le casque fonctionnait
# parfaitement : le verrou aurait fait taire IRIS sur scene, sans raison.
def test_le_micro_des_lunettes_prouve_leur_presence(app, monkeypatch):
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False  # aucune preuve basse energie
    app.state.ctx.settings.update({"glasses": {"address": "65:A2:9F:5C:F4:44", "name": "M01 Pro_F444", "auto_connect": True}})
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Microphone (High Definition Audio)",
                                                       "Casque (M01 Pro_F444 Hands-Free AG Audio)"])
    assert voice.lunettes_presentes() is True
    assert voice.lunettes_requises() is None, "le micro des lunettes suffit a prouver qu'elles sont la"


def test_le_nom_tronque_par_windows_est_reconnu(app, monkeypatch):
    """Windows coupe les noms MME a 31 caracteres : « Casque (M01 Pro_F444 Hands-Free »."""
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    app.state.ctx.settings.update({"glasses": {"address": "x", "name": "M01 Pro_F444", "auto_connect": True}})
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Casque (M01 Pro_F444 Hands-Free"])
    assert voice.lunettes_presentes() is True


def test_sans_lunettes_nulle_part_le_verrou_tient(app, monkeypatch):
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    app.state.ctx.settings.update({"glasses": {"address": "x", "name": "M01 Pro_F444", "auto_connect": True}})
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Microphone (High Definition Audio Device)"])
    assert voice.lunettes_presentes() is False
    assert voice.lunettes_requises() is not None


def test_le_verrou_ne_se_bloque_plus_pour_toujours(app, monkeypatch):
    """Sur scene, se taire definitivement est pire que reessayer : le chien de garde doit pouvoir
    relancer des que les lunettes reviennent."""
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    monkeypatch.setattr(voice, "mic_devices", lambda: [])
    app.state.ctx.settings.update({"glasses": {"address": "x", "name": "M01 Pro_F444", "auto_connect": True}})
    voice.stopped_by_user = False
    etat = voice.start()
    assert etat["state"] == "off" and "lunettes" in (etat["error"] or "").lower()
    assert voice.stopped_by_user is False, "le chien de garde doit pouvoir reessayer"


# --------------------------------------------------------------------------- le moteur figé au démarrage
# Bogue du 5 septembre 2026, et il rendait la voix TOTALEMENT inutilisable. Le moteur est choisi une
# seule fois, dans start(), appelé une seconde apres le lancement — avant que les 41 Mo du modele
# Vosk soient lus. model_ready() etait alors faux, IRIS se rabattait sur le nuage, et n'y revenait
# JAMAIS. Releve sur la machine de Miguel : 83 s de retard, 3414 blocs perdus, quatre par seconde en
# continu, et pas un seul « Dis-moi Iris » entendu de la matinee.
def test_le_moteur_repasse_en_local_des_que_le_modele_est_pret(app, monkeypatch):
    voice = app.state.ctx.voice
    voice.engine = "google"
    monkeypatch.setattr(voice, "model_ready", lambda: True)
    app.state.ctx.settings.update({"stt_engine": "auto"})

    voice._reconsiderer_le_moteur()
    assert voice.engine == "vosk", "le nuage capture 6 s puis attend le reseau : la file deborde"


def test_le_choix_explicite_de_lutilisateur_est_respecte(app, monkeypatch):
    """Quelqu'un qui a demande Google exprès ne doit pas se faire ramener en local sans le vouloir."""
    voice = app.state.ctx.voice
    voice.engine = "google"
    monkeypatch.setattr(voice, "model_ready", lambda: True)
    app.state.ctx.settings.update({"stt_engine": "google"})

    voice._reconsiderer_le_moteur()
    assert voice.engine == "google"


def test_sans_modele_on_ne_bascule_pas(app, monkeypatch):
    voice = app.state.ctx.voice
    voice.engine = "google"
    monkeypatch.setattr(voice, "model_ready", lambda: False)
    app.state.ctx.settings.update({"stt_engine": "auto"})

    voice._reconsiderer_le_moteur()
    assert voice.engine == "google"


def test_deja_en_local_ne_coute_rien(app, monkeypatch):
    """Le controle tourne a chaque tour de boucle : il doit sortir immediatement."""
    voice = app.state.ctx.voice
    voice.engine = "vosk"
    appels = []
    monkeypatch.setattr(voice, "model_ready", lambda: appels.append(1) or True)

    voice._reconsiderer_le_moteur()
    assert appels == [], "sortir avant meme d'interroger le modele"


def test_une_file_pleine_garde_le_son_le_plus_recent(app):
    """En jetant l'audio qui ARRIVE, IRIS gardait cent secondes de son perime et restait
    indefiniment en retard. Pour un mot d'activation, le son d'il y a une minute ne vaut rien."""
    import queue as _q

    voice = app.state.ctx.voice
    voice._audio = _q.Queue(maxsize=3)
    voice._native_rate = 16000
    for octet in (1, 2, 3):
        voice._audio.put_nowait(bytes([octet, 0]))

    voice._callback(memoryview(bytes([9, 0])), 1, None, None)

    restant = [voice._audio.get_nowait() for _ in range(voice._audio.qsize())]
    assert restant[-1] == bytes([9, 0]), "le bloc neuf doit etre entre"
    assert bytes([1, 0]) not in restant, "le plus vieux doit etre sorti"
    assert voice.dropped == 1
