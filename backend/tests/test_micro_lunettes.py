"""Le micro des lunettes VELA : choisir le bon périphérique, dire sa disparition, tenir la qualité téléphone.

AUCUN test n'ouvre de micro ni ne joue de son : les périphériques sont injectés. Les tables
reproduisent l'énumération relevée sur la machine de Miguel le 2026-09-04, lunettes « M01 Pro_F444 »
appairées et connectées (`sd.query_devices()`, aucun flux ouvert).
"""
from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from iris.voice.listener import (
    MICRO_MUET,
    MICRO_REOUVERTURES,
    MICRO_RETOUR,
    choisir_peripherique,
    frequence_native,
    nom_correspond,
    rafraichir_peripheriques,
)

MME, DSOUND, WASAPI, WDMKS = 0, 1, 2, 3
HOTES = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]


def _dev(nom: str, hote: int, entrees: int = 0, sorties: int = 0, taux: float = 44100.0) -> dict:
    return {"name": nom, "hostapi": hote, "max_input_channels": entrees,
            "max_output_channels": sorties, "default_samplerate": taux}


# Relevé du 2026-09-04. Les index d'origine sont en commentaire : ce qui compte ici est l'ORDRE,
# puisque c'est lui qui piégeait l'ancien code (il retenait le premier nom correspondant).
# Noter le nom tronqué à 31 caractères sous MME : « Casque (M01 Pro_F444 Hands-Free », sans
# « AG Audio ». C'est cette forme-là que l'interface enregistre dans les réglages.
PERIPHERIQUES = [
    _dev("Microphone (Realtek(R) Audio)", MME, entrees=2),                                  # micro du PC
    _dev("Casque (M01 Pro_F444 Hands-Free", MME, entrees=1),                                # 2  : LE bon micro
    _dev("Casque (M01 Pro_F444 Stereo)", MME, sorties=2),                                   # 4  : sortie A2DP
    _dev("Casque (M01 Pro_F444 Hands-Free", MME, sorties=1),                                # 5  : sortie, MÊME nom
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", WASAPI, sorties=1, taux=16000.0),     # 15
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", WASAPI, entrees=1, taux=16000.0),     # 17
    _dev("bthhfenum.sys (M01 Pro_F444)", WDMKS, sorties=1, taux=16000.0),                   # 25
    _dev("bthhfenum.sys (M01 Pro_F444)", WDMKS, entrees=1, taux=16000.0),                   # 26
    _dev("bthhfenum.sys (GT TWS)", WDMKS, entrees=1, taux=8000.0),                          # 22 : l'autre casque
]

SANS_LUNETTES = [_dev("Microphone (Realtek(R) Audio)", MME, entrees=2)]

# Même nom, même hôte, mais la SORTIE énumérée en premier : c'est exactement le piège que tendait
# le parcours d'index d'origine. Ordre construit, pas mesuré — il verrouille l'invariant.
SORTIE_EN_PREMIER = [
    _dev("Casque (GT TWS Hands-Free", MME, sorties=1),
    _dev("Casque (GT TWS Hands-Free", MME, entrees=1, taux=8000.0),
]

# Le nom exact est porté par WASAPI, le nom qui le contient par MME (l'hôte préféré) : seule la
# règle du nom exact peut départager, la préférence d'hôte tirerait dans l'autre sens.
NOM_EXACT_CONTRE_HOTE = [
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", MME, entrees=1),
    _dev("Casque (M01 Pro_F444 Hands-Free", WASAPI, entrees=1, taux=16000.0),
]


class _Sd:
    """Faux module sounddevice : énumération seule, aucun flux, aucun micro ouvert."""

    def __init__(self, devices: list[dict]):
        self._devices = devices

    def query_devices(self, *args, **kwargs):
        return self._devices

    def query_hostapis(self, *args, **kwargs):
        return HOTES


class _Flux:
    """Faux flux d'entrée : ne capte rien, ne joue rien ; il note seulement ce qu'on lui fait."""

    def __init__(self, **kw):
        self.kw = kw
        self.actif = False
        self.ferme = False

    def start(self):
        self.actif = True

    def stop(self):
        self.actif = False

    def close(self):
        self.ferme = True


class _SdComplet(_Sd):
    """Faux sounddevice complet : énumération, ouverture de flux (sans son) et ré-énumération.

    `a_venir` est la liste qui apparaît à la PROCHAINE ré-énumération, comme des lunettes qu'on
    rallume : PortAudio ne les voit qu'après avoir été fermé puis rouvert (`_terminate` /
    `_initialize`), jamais avant. C'est exactement ce que le vrai module fait, et ce qui a laissé
    IRIS sur le micro du portable."""

    def __init__(self, devices: list[dict], a_venir: list[dict] | None = None, defaut: int = 0):
        super().__init__(list(devices))
        self.a_venir = a_venir
        self.default = SimpleNamespace(device=[defaut, defaut])
        self.flux: list[_Flux] = []
        self.reenumerations = 0

    def query_devices(self, device=None, kind=None):
        if device is None:
            return self._devices
        return self._devices[device]

    def RawInputStream(self, **kw):
        flux = _Flux(**kw)
        self.flux.append(flux)
        return flux

    def _terminate(self):
        pass

    def _initialize(self):
        self.reenumerations += 1
        if self.a_venir is not None:
            self._devices, self.a_venir = list(self.a_venir), None


def _injecter(monkeypatch, sd) -> None:
    """Ce que `import sounddevice` rend dans le code testé : jamais le vrai module."""
    monkeypatch.setitem(sys.modules, "sounddevice", sd)


def _muet(voice) -> None:
    """Le micro ne dit plus rien depuis plus de MICRO_MUET secondes."""
    voice._last_block = time.time() - (MICRO_MUET + 1)


@pytest.fixture()
def evenements(app, monkeypatch):
    """Ce qu'IRIS publie vers l'interface, sans WebSocket : (type, données)."""
    recus: list[tuple[str, dict]] = []
    monkeypatch.setattr(app.state.ctx.hub, "publish", lambda type_, **data: recus.append((type_, data)) or {})
    return recus


def _alertes(evenements, type_: str = "voice.warning") -> list[str]:
    return [data.get("text", "") for nom, data in evenements if nom == type_]


# --------------------------------------------------------------- 1. trouver le bon périphérique
def test_le_micro_des_lunettes_est_choisi_parmi_ses_homonymes():
    """Six périphériques portent « M01 Pro_F444 ». Si le choix tombait ailleurs, IRIS ouvrirait la
    broche WDM-KS du noyau (souvent déjà prise) ou un point de sortie, et n'entendrait rien."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "M01 Pro_F444") == 1


def test_une_sortie_ne_peut_jamais_etre_prise_pour_un_micro():
    """« Casque (M01 Pro_F444 Stereo) » n'a aucun canal d'entrée : le retenir ferait échouer
    l'ouverture du flux et Miguel croirait ses lunettes en panne."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "M01 Pro_F444 Stereo") is None


def test_la_sortie_enumeree_avant_lentree_ne_gagne_pas():
    """Deux périphériques portent le même nom, la sortie d'abord. Sans le filtre par le sens, on
    ouvrirait un haut-parleur en croyant ouvrir un micro."""
    assert choisir_peripherique(SORTIE_EN_PREMIER, HOTES, "GT TWS") == 1


def test_le_nom_exact_lemporte_sur_le_nom_qui_le_contient():
    """L'interface enregistre le nom MME tronqué à 31 caractères, et ce nom est aussi CONTENU dans
    le nom complet annoncé par WASAPI. Sans cette règle, choisir un périphérique dans la liste
    n'aurait pas garanti d'ouvrir celui-là."""
    assert choisir_peripherique(NOM_EXACT_CONTRE_HOTE, HOTES, "Casque (M01 Pro_F444 Hands-Free") == 1


def test_aucun_micro_demande_veut_dire_micro_par_defaut():
    """Réglage vide = « laisse Windows décider ». Retourner un index ici imposerait un micro que
    personne n'a choisi."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "") is None
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "   ") is None


def test_le_nom_complet_retrouve_le_nom_que_mme_a_tronque():
    """Réglage pris dans une liste WASAPI (nom complet), périphérique annoncé par MME (31 caractères) :
    l'inverse du cas précédent. Sans cette règle, changer d'hôte au moment du choix rendait le
    micro introuvable."""
    tronque_seulement = [_dev("Casque (M01 Pro_F444 Hands-Free", MME, entrees=1)]
    assert choisir_peripherique(tronque_seulement, HOTES, "Casque (M01 Pro_F444 Hands-Free AG Audio)") == 0
    assert frequence_native(tronque_seulement, "Casque (M01 Pro_F444 Hands-Free AG Audio)") == 44100.0


def test_la_casse_et_les_espaces_ne_comptent_pas():
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "  casque (m01 PRO_f444 hands-free ") == 1
    assert nom_correspond("Casque  (M01 Pro_F444 Hands-Free", "casque (m01 pro_f444 hands-free")


def test_un_debut_de_nom_trop_court_ne_passe_pas_pour_une_troncature():
    """« Casque ( » est un préfixe de tous les casques : seul un nom de 31 caractères, la longueur
    à laquelle MME coupe, a le droit d'être pris pour une version tronquée."""
    assert not nom_correspond("Casque (", "Casque (M01 Pro_F444 Hands-Free AG Audio)")
    assert choisir_peripherique([_dev("Casque (", MME, entrees=1)], HOTES, "Casque (M01 Pro_F444 Hands-Free AG Audio)") is None


def test_sans_micro_choisi_celui_des_lunettes_appairees_est_prefere(app, evenements):
    """Réglage vide mais lunettes appairées : IRIS est ce qu'il y a dans les lunettes. Ouvrir le micro
    du portable pendant que Miguel parle dans ses lunettes n'est pas « laisser Windows décider »,
    c'est écouter le mauvais endroit."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "", "glasses": {"name": "M01 Pro_F444", "address": "x", "auto_connect": True}})
    assert voice._input_device(_Sd(PERIPHERIQUES)) == 1
    assert _alertes(evenements) == []


def test_les_lunettes_non_choisies_et_absentes_ne_declenchent_aucune_alerte(app, evenements):
    """Personne ne les a demandées : leur absence ne se signale pas, on prend le micro par défaut."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "", "glasses": {"name": "M01 Pro_F444", "address": "x", "auto_connect": True}})
    assert voice._input_device(_Sd(SANS_LUNETTES)) is None
    assert _alertes(evenements) == []


def test_le_micro_est_retrouve_a_partir_du_nom_enregistre_dans_les_reglages(app):
    """Bout en bout depuis le réglage réel : c'est la chaîne qui décide si « Dis-moi Iris » est
    entendu dans les lunettes ou dans le micro du portable."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    assert voice._input_device(_Sd(PERIPHERIQUES)) == 1


# --------------------------------------------------------------- 2. dire la disparition du micro
def test_le_micro_disparu_est_dit_a_lutilisateur(app, evenements):
    """Se rabattre en silence sur le micro du PC était le pire des comportements : IRIS écoutait
    l'ordinateur pendant que Miguel parlait dans ses lunettes, sans une erreur nulle part."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    assert voice._input_device(_Sd(SANS_LUNETTES)) is None
    textes = _alertes(evenements)
    assert len(textes) == 1
    assert "M01 Pro_F444" in textes[0] and "lunettes" in textes[0].lower()


def test_le_meme_avertissement_nest_jamais_repete(app, evenements):
    """Le chien de garde relance l'écoute toutes les 20 s tant qu'elle ne tourne pas : sans ce
    filtre, un micro absent ferait surgir la même fenêtre trois fois par minute, et un
    avertissement qu'on apprend à ignorer ne vaut pas mieux que le silence qu'on corrige."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    for _ in range(3):
        voice._input_device(_Sd(SANS_LUNETTES))
    assert len(_alertes(evenements)) == 1


def test_un_micro_qui_remarche_rouvre_le_droit_de_prevenir(app, evenements):
    """Sinon une panne qui revient des heures plus tard serait filtrée comme un doublon et Miguel
    ne saurait jamais que ses lunettes ont décroché."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    voice._input_device(_Sd(SANS_LUNETTES))
    voice._alertes_dites.clear()  # ce que fait `_run` dès que le flux s'ouvre pour de bon
    voice._input_device(_Sd(SANS_LUNETTES))
    assert len(_alertes(evenements)) == 2


def test_le_micro_devenu_muet_sans_flux_a_rouvrir_arrete_lecoute_et_dit_quoi_faire(app, evenements):
    """Des lunettes qui s'éteignent ne lèvent aucune exception : PortAudio garde le flux « actif »
    et cesse d'appeler le callback. Sans ce garde-fou, IRIS resterait en écoute devant un micro
    mort, sans un mot, et « Dis-moi Iris » ne réveillerait plus rien.

    Ici aucun flux n'a jamais été ouvert (rien à rouvrir) : c'est le seul cas où le premier
    silence arrête l'écoute d'un coup. Avec un flux, voir la section 4 : on rouvre d'abord."""
    voice = app.state.ctx.voice
    voice.device_name = "Casque (M01 Pro_F444 Hands-Free"
    _muet(voice)
    voice._stop.clear()
    assert voice._read(timeout=0.01) is None
    assert voice._stop.is_set(), "l'écoute doit se dénouer, pas continuer dans le vide"
    # Arbitrage du 5 septembre 2026, contre la version precedente de ce test. On ne pose PAS
    # `stopped_by_user` : ce drapeau empeche le chien de garde de jamais reessayer, et IRIS se
    # tairait definitivement parce que des lunettes ont manque d'air une fois. Le 8 septembre,
    # devant les dragons, une assistante qui reessaie toutes les vingt secondes vaut infiniment
    # mieux qu'une assistante muette pour de bon. Ce que le drapeau evitait — l'alerte repetee —
    # est traite ailleurs : `_alerter` ne redit rien deux fois.
    assert not voice.stopped_by_user, "se taire pour toujours est pire que reessayer"
    textes = _alertes(evenements)
    assert len(textes) == 1
    assert "M01 Pro_F444" in textes[0] and "rallumez" in textes[0].lower()
    assert voice.error and "M01 Pro_F444" in voice.error


def test_un_micro_qui_repond_encore_ne_declenche_aucune_alerte(app, evenements):
    """Une file momentanément vide n'est pas une panne : couper l'écoute au moindre blanc rendrait
    IRIS inutilisable, et c'est le cas le plus fréquent puisqu'on lit plus vite qu'on n'enregistre."""
    voice = app.state.ctx.voice
    voice._last_block = time.time()
    voice._stop.clear()
    assert voice._read(timeout=0.01) is None
    assert not voice._stop.is_set()
    assert _alertes(evenements) == []


def test_avant_le_premier_bloc_rien_nest_signale(app, evenements):
    """Au démarrage, `_last_block` vaut 0 : sans ce garde-fou, l'écoute s'arrêterait avant même
    d'avoir commencé, en accusant les lunettes."""
    voice = app.state.ctx.voice
    voice._last_block = 0.0
    voice._stop.clear()
    assert voice._micro_perdu() is False
    assert _alertes(evenements) == []


def test_le_compromis_mono_des_lunettes_est_annonce_une_seule_fois(app, evenements):
    """Le Bluetooth ne porte qu'un lien audio : micro ouvert, la stéréo des lunettes se tait. Le
    taire ferait croire à une panne de son ; le répéter à chaque écoute serait du harcèlement."""
    voice = app.state.ctx.voice
    voice._mono_annonce = False
    voice._prevenir_mono()
    voice._prevenir_mono()
    textes = _alertes(evenements, "voice.info")
    assert len(textes) == 1 and "mono" in textes[0].lower()


# --------------------------------------------------------------- 3. la qualité téléphone
def test_la_frequence_annoncee_par_mme_ne_fait_pas_foi():
    """MME annonce 44100 Hz pour un lien réellement à 16000 Hz. Si on le croyait, la détection de
    bande étroite serait morte et les lunettes passeraient pour un micro large bande."""
    assert frequence_native(PERIPHERIQUES, "M01 Pro_F444") == 16000.0
    assert frequence_native(PERIPHERIQUES, "GT TWS") == 8000.0
    assert frequence_native(PERIPHERIQUES, "Realtek") == 44100.0
    assert frequence_native(PERIPHERIQUES, "casque introuvable") == 0.0


def test_un_casque_sans_hands_free_dans_son_nom_reste_reconnu(app, monkeypatch):
    """Le nom anglais reste le test principal, mais un casque nommé autrement doit encore être
    reconnu comme bande étroite, sinon IRIS le traiterait comme un micro large bande."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "GT TWS"})
    monkeypatch.setitem(sys.modules, "sounddevice", _Sd(PERIPHERIQUES))
    assert voice._narrowband_input() is True


def test_le_micro_du_pc_nest_pas_pris_pour_un_micro_telephone(app, monkeypatch):
    """Croire le micro interne en bande étroite ferait choisir les mauvais compromis de traitement
    pour le seul micro qui capte vraiment large."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Realtek"})
    monkeypatch.setitem(sys.modules, "sounddevice", _Sd(PERIPHERIQUES))
    assert voice._narrowband_input() is False


def _sinus(taux: int, secondes: float, hz: float = 440.0) -> bytes:
    import numpy as np

    t = np.arange(int(taux * secondes)) / taux
    return (np.sin(2 * np.pi * hz * t) * 8000).astype(np.int16).tobytes()


def _passages_a_zero(pcm: bytes) -> int:
    import numpy as np

    return int(np.count_nonzero(np.diff(np.signbit(np.frombuffer(pcm, dtype=np.int16).astype(np.int32)))))


def test_les_lunettes_a_16_khz_ne_sont_pas_reechantillonnees(app):
    """Le lien mains libres de ces lunettes fournit 16 kHz, exactement ce que Vosk attend
    (`stt.SAMPLE_RATE`). Un rééchantillonnage inutile ne pourrait qu'abîmer le signal."""
    voice = app.state.ctx.voice
    voice._native_rate = 16000
    pcm = _sinus(16000, 0.25)
    assert voice._resample(pcm) is pcm  # le même objet : rien n'a été touché


def test_le_bloc_de_44100_de_mme_redescend_a_exactement_4000_echantillons(app):
    """MME livre des blocs de 11025 échantillons pour un lien réellement à 16 kHz. S'ils ne
    redescendaient pas à exactement 4000, un résidu s'accumulerait de bloc en bloc et la parole
    dériverait peu à peu — c'est ce rapport entier qui rend l'interpolation linéaire acceptable."""
    voice = app.state.ctx.voice
    voice._native_rate = 44100
    bloc = _sinus(44100, 11025 / 44100)
    assert len(bloc) // 2 == 11025
    sortie = voice._resample(bloc)
    assert len(sortie) // 2 == 4000
    assert abs(_passages_a_zero(sortie) - _passages_a_zero(bloc)) <= 2, "la hauteur du son a changé"


def test_un_casque_a_8_khz_est_remonte_a_16_khz(app):
    """Le « GT TWS » appairé sur cette machine ne fournit que 8 kHz. Sans cette montée, Vosk
    recevrait un signal deux fois trop lent et n'entendrait plus jamais le mot d'activation."""
    voice = app.state.ctx.voice
    voice._native_rate = 8000
    bloc = _sinus(8000, 0.25)
    sortie = voice._resample(bloc)
    assert len(sortie) == 2 * len(bloc)
    assert abs(_passages_a_zero(sortie) - _passages_a_zero(bloc)) <= 2, "la hauteur du son a changé"


def test_le_mot_dactivation_reste_hors_ligne_avec_le_micro_des_lunettes(app, monkeypatch):
    """Basculer TOUT le cycle vers Google parce que le micro est en qualité téléphone envoyait le
    salon en continu par segments de 6 s et rendait la réponse en moins de 5 s impossible — alors
    que c'est justement en bande étroite que la grammaire restreinte est la plus sûre."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update(
        {"audio_input_device": "Casque (M01 Pro_F444 Hands-Free", "stt_engine": "auto", "local_only": False}
    )
    monkeypatch.setattr(voice, "model_ready", lambda: True)
    monkeypatch.setattr(voice.consent, "is_granted", lambda *a, **k: True)
    assert voice._choose_engine() == "vosk"


# --------------------------------------------------------------- 4. rouvrir plutôt que mourir
# Journal du 5 septembre 2026 : « micro muet depuis 5 s, l'écoute s'arrête ». La boucle est morte,
# le chien de garde l'a relancée vingt secondes plus tard — sur le micro du portable, parce que la
# liste des périphériques de PortAudio n'avait pas bougé depuis le lancement d'IRIS — et elle y est
# restée toute la journée pendant que Miguel parlait dans ses lunettes.
LUNETTES = "Casque (M01 Pro_F444 Hands-Free"
BLOC = b"\x00\x00"


def _ouvrir_sur(app, monkeypatch, sd, demande: str = LUNETTES):
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": demande})
    _injecter(monkeypatch, sd)
    voice._stop.clear()
    voice._ouvrir_flux(sd)
    return voice


def test_la_liste_des_micros_est_refaite_avant_chaque_ouverture(app, monkeypatch):
    """Les lunettes ont été allumées APRÈS IRIS : PortAudio ne les montre qu'une fois fermé puis
    rouvert. C'est ce que le chien de garde doit obtenir à chaque relance, sinon il repart sur le
    micro du portable en croyant les lunettes absentes."""
    sd = _SdComplet(SANS_LUNETTES, a_venir=PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    assert sd.reenumerations == 1
    assert sd.flux[-1].kw["device"] == 1, "le micro des lunettes, pas celui du portable"
    assert sd.flux[-1].actif
    assert voice._micro_de_repli is False
    assert voice.device_name == LUNETTES
    voice._fermer_flux()
    assert sd.flux[-1].ferme


def test_les_lunettes_vraiment_absentes_donnent_un_micro_de_repli_et_le_disent(app, monkeypatch, evenements):
    sd = _SdComplet(SANS_LUNETTES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    assert sd.flux[-1].kw["device"] is None
    assert voice._micro_de_repli is True
    assert voice.status()["device_fallback"] is True
    textes = _alertes(evenements)
    assert len(textes) == 1 and "lunettes" in textes[0].lower() and "toute seule" in textes[0]
    voice._fermer_flux()


def test_le_micro_muet_est_rouvert_avant_darreter_lecoute(app, monkeypatch, evenements):
    """Premier silence : on rouvre le MÊME micro. Le lien mains libres Bluetooth décroche et
    raccroche seul plus souvent qu'il ne meurt."""
    sd = _SdComplet(PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    _muet(voice)
    assert voice._read(timeout=0.01) is None
    assert not voice._stop.is_set(), "rouvrir, pas mourir"
    assert voice._reouvertures == 1
    assert len(sd.flux) == 2 and sd.flux[0].ferme and sd.flux[1].actif
    assert sd.flux[1].kw["device"] == 1, "le même micro d'abord"
    assert voice.error is None
    assert _alertes(evenements) == [], "rien à dire tant que les lunettes répondent de nouveau"
    voice._fermer_flux()


def test_muet_une_seconde_fois_on_passe_au_micro_de_lordinateur(app, monkeypatch, evenements):
    sd = _SdComplet(PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    for _ in range(2):
        _muet(voice)
        voice._read(timeout=0.01)
    assert not voice._stop.is_set()
    assert voice._reouvertures == 2
    assert sd.flux[-1].kw["device"] is None, "le micro par défaut, puisque le même micro reste muet"
    assert voice._micro_de_repli is True
    textes = _alertes(evenements)
    assert len(textes) == 1 and "ordinateur" in textes[0] and "M01 Pro_F444" in textes[0]
    voice._fermer_flux()


def test_muet_une_troisieme_fois_lecoute_sarrete_et_le_chien_de_garde_reprendra(app, monkeypatch, evenements):
    sd = _SdComplet(PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    for _ in range(MICRO_REOUVERTURES + 1):
        _muet(voice)
        voice._read(timeout=0.01)
    assert voice._stop.is_set(), "après échec répété seulement"
    assert voice.error and "rallumez" in voice.error.lower()
    assert not voice.stopped_by_user, "le chien de garde doit pouvoir réessayer"
    voice._fermer_flux()


def test_un_bloc_recu_efface_les_tentatives_passees(app, monkeypatch):
    """Sinon deux silences à une heure d'écart compteraient comme une panne continue."""
    sd = _SdComplet(PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    voice._reouvertures = 1
    voice._audio.put_nowait(BLOC)
    assert voice._read(timeout=0.01) == BLOC
    assert voice._reouvertures == 0
    voice._fermer_flux()


def test_si_aucun_micro_ne_souvre_plus_on_arrete_sans_attendre(app, monkeypatch):
    """Les deux essais échouent à l'ouverture même : inutile d'attendre cinq secondes de plus
    devant une file vide entre les deux."""
    sd = _SdComplet(PERIPHERIQUES)
    voice = _ouvrir_sur(app, monkeypatch, sd)

    def _refuse(**kw):
        raise RuntimeError("Error opening RawInputStream")

    sd.RawInputStream = _refuse
    _muet(voice)
    voice._read(timeout=0.01)
    assert voice._stop.is_set()
    assert voice._reouvertures == MICRO_REOUVERTURES
    assert voice._stream is None


def test_sur_le_micro_de_repli_les_lunettes_revenues_sont_reprises(app, monkeypatch, evenements):
    """LE cas du 5 septembre. L'écoute tourne sur le portable ; les lunettes reviennent ; sans
    personne pour relancer, IRIS doit repasser dessus toute seule."""
    sd = _SdComplet(SANS_LUNETTES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    assert voice._micro_de_repli is True
    sd.a_venir = PERIPHERIQUES  # les lunettes sont rallumées
    voice.state = "wake"
    voice._derniere_recherche = time.time() - MICRO_RETOUR - 1
    voice._audio.put_nowait(BLOC)
    voice._read(timeout=0.01)
    assert voice._micro_de_repli is False
    assert sd.flux[-1].kw["device"] == 1 and sd.flux[-1].actif
    assert voice.device_name == LUNETTES
    infos = _alertes(evenements, "voice.info")
    assert any("retour" in t for t in infos), "le retour se dit, sinon on croit IRIS encore sur le portable"
    voice._fermer_flux()


def test_la_reprise_attend_la_fin_dune_commande(app, monkeypatch):
    """Fermer le micro au milieu d'une commande en couperait un morceau : on attend d'être
    revenu à l'attente du mot d'activation."""
    sd = _SdComplet(SANS_LUNETTES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    sd.a_venir = PERIPHERIQUES
    voice.state = "command"
    voice._derniere_recherche = time.time() - MICRO_RETOUR - 1
    voice._audio.put_nowait(BLOC)
    voice._read(timeout=0.01)
    assert voice._micro_de_repli is True and len(sd.flux) == 1
    voice._fermer_flux()


def test_la_reprise_ne_regarde_pas_plus_dune_fois_par_demi_minute(app, monkeypatch):
    """Chaque coup d'œil ferme et rouvre le micro : quatre fois par seconde, ce serait l'écoute
    elle-même qu'on abîmerait."""
    sd = _SdComplet(SANS_LUNETTES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    sd.a_venir = PERIPHERIQUES
    voice.state = "wake"
    voice._derniere_recherche = time.time()
    voice._audio.put_nowait(BLOC)
    voice._read(timeout=0.01)
    assert voice._micro_de_repli is True and len(sd.flux) == 1
    voice._fermer_flux()


def test_les_lunettes_toujours_absentes_ne_font_pas_repeter_lalerte(app, monkeypatch, evenements):
    sd = _SdComplet(SANS_LUNETTES)
    voice = _ouvrir_sur(app, monkeypatch, sd)
    voice.state = "wake"
    for _ in range(3):
        voice._derniere_recherche = time.time() - MICRO_RETOUR - 1
        voice._audio.put_nowait(BLOC)
        voice._read(timeout=0.01)
    assert voice._micro_de_repli is True
    assert len(_alertes(evenements)) == 1
    voice._fermer_flux()


# --------------------------------------------------------------- 5. la liste des périphériques
def test_mic_devices_ne_reenumere_pas_pendant_que_le_micro_est_ouvert(app, monkeypatch):
    """Fermer PortAudio ferme d'autorité tout flux ouvert, le nôtre compris : la ré-énumération
    n'a lieu que micro fermé, et pas plus d'une fois toutes les dix secondes."""
    voice = app.state.ctx.voice
    sd = _SdComplet(PERIPHERIQUES)
    _injecter(monkeypatch, sd)
    voice._stream = object()
    voice._dernier_rafraichissement = 0.0
    assert LUNETTES in voice.mic_devices()
    assert sd.reenumerations == 0
    voice._stream = None
    voice.mic_devices()
    assert sd.reenumerations == 1
    voice.mic_devices()
    assert sd.reenumerations == 1, "pas deux fois en dix secondes"


def test_la_reenumeration_attend_quiris_ait_fini_de_parler(app, monkeypatch):
    """ElevenLabs parle par un flux PortAudio : le fermer couperait IRIS au milieu d'une phrase."""
    voice = app.state.ctx.voice
    sd = _SdComplet(PERIPHERIQUES)
    monkeypatch.setattr(type(voice.tts), "is_speaking", property(lambda self: True))
    monkeypatch.setattr(voice.tts, "wait_idle", lambda timeout=0.0: False)
    voice._dernier_rafraichissement = 0.0
    assert voice._rafraichir_si_possible(sd) is False
    assert voice._rafraichir_peripheriques(sd) is False
    assert sd.reenumerations == 0


def test_un_module_sans_reenumeration_est_laisse_tel_quel():
    assert rafraichir_peripheriques(_Sd(PERIPHERIQUES)) is False


def test_le_compromis_mono_est_juge_sur_le_micro_ouvert_pas_sur_celui_voulu(app, monkeypatch):
    """Sur le micro de repli (celui du portable), annoncer « le son des lunettes passe en mono »
    serait faux, et on cesserait vite de croire ces messages."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": LUNETTES})
    _injecter(monkeypatch, _Sd(PERIPHERIQUES))
    voice._stream = object()
    voice.device_name = "Microphone (Realtek(R) Audio)"
    assert voice._narrowband_input() is False
    voice.device_name = LUNETTES
    assert voice._narrowband_input() is True
    voice._stream = None
