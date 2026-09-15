"""Le mode interprète : chacun parle sa langue, chacun entend la sienne — et IRIS ne devine jamais.

Ce que ces tests protègent, dans l'ordre d'importance :
1. L'ATTRIBUTION. Une phrase du propriétaire traduite comme si l'autre l'avait dite (ou l'inverse)
   produit une traduction fluide que personne ne peut détecter. Dans le doute, IRIS le dit et ne
   traduit rien.
2. LA SORTIE. Ce que dit l'autre part en français dans les lunettes ; ce que dit le propriétaire part
   dans la langue de l'autre, sur la sortie réglée (ordinateur, lunettes, téléphone), avec une voix
   qui parle CETTE langue — et quand aucune n'existe, l'interprète le dit à l'ouverture.
3. LES VERROUS. Mode confidentiel, mode local, consentements : rien ne démarre et rien ne part.
4. LA LATENCE est mesurée par tour et publiée, jamais promise.

Aucun test n'ouvre de micro, ne joue de son, ne charge de modèle ni ne touche au réseau : les
reconnaissances, le modèle, la voix, l'écoute et le périphérique audio sont des doublures.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from iris.routes_interprete import REPLI_LUNETTES, VoixAutreLangue, classer_voix, langue_de_lcid, lire_lcid
from iris.traduction import (
    DOUTE_INTERVALLE,
    DecodeurContinu,
    Ecoute,
    RefusInterprete,
    ServiceInterprete,
    ServiceTraduction,
    attribuer,
    ecoute_depuis_resultats,
    est_phrase_interprete,
    juger_local,
)
from iris.voice import listener as ecoute_mod
from iris.voice import stt

FR_SUR = Ecoute("est-ce que vous pouvez m'aider à trouver mon hôtel", 0.97, 0.0, "fr")
# Sortie réelle du modèle français sur une phrase anglaise de synthèse, mesurée le 13 septembre 2026.
CHARABIA_LOCAL = Ecoute("je reconnais envie ou fin et du vosgien les données", 0.45, 0.8, "fr")
EN_EN_LIGNE = Ecoute("sure I can help you find your hotel what is the name", None, 0.0, "")
PAROLE = (6000).to_bytes(2, "little", signed=True) * ecoute_mod.BLOCK
SILENCE = b"\x00\x00" * ecoute_mod.BLOCK


# --------------------------------------------------------------------------- doublures
class Horloge:
    def __init__(self, depart: float = 1000.0):
        self.t = depart

    def __call__(self) -> float:
        return self.t

    def avancer(self, s: float) -> None:
        self.t += s


class FauxModele:
    """Traduit dans le bon sens, d'après la consigne. Peut faire avancer l'horloge (coût du réseau)."""

    def __init__(self, horloge: Horloge | None = None, cout: float = 0.0, apres: Any = None):
        self.appels: list[tuple[str, str]] = []
        self.horloge, self.cout, self.apres = horloge, cout, apres

    def __call__(self, systeme: str, message: str) -> str:
        self.appels.append((systeme, message))
        if self.horloge is not None:
            self.horloge.avancer(self.cout)
        if self.apres is not None:
            self.apres()
        if "vers le français" in systeme:
            return "TRADUCTION: Bien sûr, je peux vous aider à trouver votre hôtel."
        return "TRADUCTION: Can you help me find my hotel?"


class FauxHub:
    def __init__(self):
        self.evenements: list[dict] = []

    def publish(self, type_: str, **d: Any) -> dict:
        self.evenements.append({"type": type_, **d})
        return d

    def de_type(self, type_: str) -> list[dict]:
        return [e for e in self.evenements if e["type"] == type_]


class FausseVoix:
    def __init__(self, langues=("en",)):
        self.langues = set(langues)
        self.dites: list[tuple[str, str, str]] = []
        self.arrets = 0
        self.parle = False

    def disponible(self, langue: str) -> bool:
        return langue in self.langues

    def nom_voix(self, langue: str):
        return f"Voix de l'ordinateur en {langue}" if langue in self.langues else None

    def rafraichir(self):
        return []

    def parler(self, texte: str, langue: str, sortie: str) -> bool:
        if langue not in self.langues:
            return False
        self.dites.append((texte, langue, sortie))
        return True

    def arreter(self) -> None:
        self.arrets += 1


class FausseEcoute:
    def __init__(self, running: bool = True, demarre: bool = True, modele: bool = True):
        self.running, self.demarre, self.modele = running, demarre, modele
        self.error = None
        self.demarrages = 0

    def start(self):
        self.demarrages += 1
        if self.demarre:
            self.running = True
        else:
            self.error = "Connecte tes lunettes VELA pour utiliser IRIS."
        return {}

    def model_ready(self) -> bool:
        return self.modele


class ConsentRequired(Exception):  # même forme que iris.consent.ConsentRequired
    def __init__(self, data_type: str):
        super().__init__(data_type)
        self.data_type = data_type
        self.reason = "Texte de vos demandes"


def reglages(**kw) -> SimpleNamespace:
    base = dict(language="fr-CA", local_only=False, privacy_mode=False, interprete_langue="en",
                interprete_sortie_autre="pc")
    base.update(kw)
    return SimpleNamespace(user=SimpleNamespace(**base))


def construire(sortie="pc", voix=("en",), audio=True, ecoute=None, horloge=None, modele=None, **kw):
    horloge = horloge or Horloge()
    hub = FauxHub()
    r = reglages(interprete_sortie_autre=sortie, **kw)
    t = ServiceTraduction(modele or FauxModele(), settings=r, hub=hub, horloge=horloge)
    dits: list[str] = []
    service = ServiceInterprete(t, r, hub=hub, voix=FausseVoix(voix), ecoute=ecoute or FausseEcoute(),
                                audio_autorise=lambda: audio, parler_moi=dits.append,
                                horloge=horloge, murale=lambda: 1_700_000_000.0)
    return SimpleNamespace(service=service, trad=t, hub=hub, dits=dits, horloge=horloge, reglages=r)


def interdit():
    raise AssertionError("la voix du propriétaire, bien reconnue sur l'ordinateur, ne doit pas partir en ligne")


# =========================================================================== 1. qui a parlé ?
def test_une_phrase_francaise_bien_reconnue_est_la_mienne_sans_rien_envoyer():
    a = attribuer(FR_SUR, None, "fr", "en")
    assert a.qui == "moi" and a.langue == "fr" and a.texte == FR_SUR.texte


def test_le_charabia_du_modele_francais_sur_de_langlais_part_au_service_en_ligne_et_revient_autre():
    assert juger_local(CHARABIA_LOCAL, "fr") == "incertain"
    a = attribuer(CHARABIA_LOCAL, EN_EN_LIGNE, "fr", "en")
    assert a.qui == "autre" and a.langue == "en" and a.texte == EN_EN_LIGNE.texte


def test_une_confiance_haute_ne_suffit_pas_sur_une_boucle_de_repetition():
    """Mesuré : « hum hum hum hum hum hum » rendu à 0,91 de confiance sur une phrase anglaise."""
    assert juger_local(Ecoute("hum hum hum hum hum hum", 0.91, 0.0, "fr"), "fr") == "incertain"


def test_ma_phrase_mal_reconnue_localement_mais_francaise_en_ligne_reste_la_mienne():
    locale = Ecoute("je cherche la gare centrale", 0.66, 0.3, "fr")
    a = attribuer(locale, Ecoute("Je cherche la gare centrale, s'il vous plaît.", None, 0.0, ""), "fr", "en")
    assert a.qui == "moi" and "gare" in a.texte


def test_reconnaissance_en_ligne_en_panne_est_un_doute_dit_jamais_une_traduction():
    a = attribuer(CHARABIA_LOCAL, Ecoute(erreur="pas de réseau"), "fr", "en")
    assert a.qui == "doute" and a.a_dire and a.raison == "pas de réseau"
    assert attribuer(CHARABIA_LOCAL, None, "fr", "en").qui == "doute"


def test_un_bruit_que_personne_ne_reconnait_est_un_doute_silencieux():
    a = attribuer(None, Ecoute("", None, 0.0, ""), "fr", "en")
    assert a.qui == "doute" and a.a_dire == ""


@pytest.mark.parametrize("confiance, similaire, attendu", [
    (0.30, False, "autre"),   # le local s'est effondré : c'était l'autre
    (0.62, False, "doute"),   # ni l'un ni l'autre : on ne devine pas
    (0.92, True, "moi"),      # même phrase, bien reconnue localement
])
def test_une_phrase_courte_sans_mot_outil_est_departagee_par_le_local(confiance, similaire, attendu):
    locale = Ecoute("ok toronto" if similaire else "au trot tonneau", confiance, 0.0, "fr")
    assert attribuer(locale, Ecoute("OK Toronto", None, 0.0, ""), "fr", "en").qui == attendu


def test_un_service_qui_ne_cherchait_que_langlais_ne_prouve_rien_contre_un_local_confiant():
    locale = Ecoute("au trot tonneau", 0.8, 0.2, "fr")
    assert attribuer(locale, Ecoute("OK Toronto", None, 0.0, "en"), "fr", "en").qui == "doute"
    assert attribuer(Ecoute("euh", 0.3, 1.0, "fr"), Ecoute("OK Toronto", None, 0.0, "en"), "fr", "en").qui == "autre"


def test_un_mot_seul_nest_ni_traduit_ni_commente():
    a = attribuer(None, Ecoute("yes", None, 0.0, ""), "fr", "en")
    assert a.qui == "doute" and a.a_dire == ""


def test_les_resultats_vosk_donnent_texte_confiance_et_mots_incertains():
    resultats = [
        json.dumps({"result": [{"word": "bonjour", "conf": 1.0}, {"word": "madame", "conf": 0.4}], "text": "bonjour madame"}),
        json.dumps({"text": ""}),
        json.dumps({"result": [{"word": "merci", "conf": 0.7}], "text": "merci"}),
    ]
    e = ecoute_depuis_resultats(resultats, "fr")
    assert e.texte == "bonjour madame merci"
    assert e.confiance == pytest.approx(0.7)
    assert e.part_incertaine == pytest.approx(1 / 3)
    assert ecoute_depuis_resultats(["pas du json"], "fr").texte == ""


# =========================================================================== 2. la voix : ouvrir et fermer
@pytest.mark.parametrize("phrase, attendu", [
    ("mode interprète anglais", "demarrer"),
    ("interprète espagnol", "demarrer"),
    ("traduis en direct avec lui", "demarrer"),
    ("fais l'interprète", "demarrer"),
    ("fin de l'interprète", "arreter"),
    ("fait de l'interprète", "arreter"),  # ce que le petit modèle français rend de « fin de l'interprète »
    ("arrête l'interprète", "arreter"),
    ("c'est quoi un interprète", None),
    ("traduis ce qu'il dit", None),  # la traduction à sens unique garde ses phrases
    ("ouvre spotify", None),
])
def test_les_phrases_de_linterprete(phrase, attendu):
    assert est_phrase_interprete(phrase) == attendu


def test_linterception_ouvre_dans_la_langue_nommee_et_referme():
    m = construire(voix=("es",))
    phrase = m.service.interception("mode interprète espagnol")
    assert m.service.actif and m.trad.langue_entendue == "es"
    assert "espagnol" in phrase and "Iris, arrête" in phrase
    assert m.service.interception("ouvre mon navigateur") is None
    fin = m.service.interception("fin de l'interprète")
    assert not m.service.actif and fin.endswith("Je ne traduis plus.")


def test_linterception_dit_pourquoi_elle_ne_peut_pas_ouvrir():
    m = construire(audio=False)
    phrase = m.service.interception("mode interprète anglais")
    assert not m.service.actif and "Audio brut du micro" in phrase


# =========================================================================== 3. la sortie
def test_ce_que_dit_lautre_part_en_francais_dans_les_lunettes_et_la_latence_est_mesuree():
    horloge = Horloge()
    m = construire(horloge=horloge, modele=FauxModele(horloge, cout=1.5))
    m.service.demarrer("en", annoncer=False)
    fin_parole = horloge() - 0.7  # la parole s'est tue il y a 0,7 s (silence de fin de phrase)
    r = m.service.interpreter(CHARABIA_LOCAL, lambda: EN_EN_LIGNE, fin_parole=fin_parole)
    assert r["qui"] == "autre"
    assert m.dits == ["Bien sûr, je peux vous aider à trouver votre hôtel."]
    assert m.service.voix.dites == []
    tour = m.service.tours()[-1]
    assert tour["qui"] == "autre" and tour["langue_source"] == "en" and tour["langue_cible"] == "fr"
    assert tour["latence_ms"] == 2200 and tour["sortie"] == "voix_iris"
    assert m.hub.de_type("interprete.tour")[-1]["latence_ms"] == 2200
    assert m.service.etat()["latence_moyenne_ms"] == 2200


@pytest.mark.parametrize("sortie", ["pc", "lunettes"])
def test_ce_que_je_dis_part_dans_la_langue_de_lautre_sur_la_sortie_reglee(sortie):
    m = construire(sortie=sortie)
    m.service.demarrer("en", annoncer=False)
    r = m.service.interpreter(FR_SUR, interdit)
    assert r["qui"] == "moi"
    assert m.service.voix.dites == [("Can you help me find my hotel?", "en", sortie)]
    assert m.dits == [], "la traduction anglaise ne passe pas par la voix française d'IRIS"
    assert m.service.tours()[-1]["sortie"] == sortie


def test_sortie_telephone_le_telephone_lit_la_traduction():
    m = construire(sortie="telephone", voix=())
    m.service.demarrer("en", annoncer=False)
    m.service.interpreter(FR_SUR, interdit)
    a_lire = m.hub.de_type("interprete.a_lire")
    assert a_lire and a_lire[-1]["texte"] == "Can you help me find my hotel?" and a_lire[-1]["langue"] == "en"
    assert m.service.voix.dites == []
    assert m.service.tours()[-1]["sortie"] == "telephone"


def test_sans_voix_de_la_langue_linterprete_le_dit_a_louverture_et_naffiche_que_le_texte():
    m = construire(sortie="pc", voix=())
    etat = m.service.etat()
    assert etat["empechement"] and "Aucune voix capable de parler anglais" in etat["empechement"]
    assert etat["empechement_bloquant"] is False and etat["voix_autre"]["disponible"] is False
    ouvert = m.service.demarrer("en", annoncer=True)
    assert m.service.actif
    assert "Aucune voix en anglais" in ouvert["phrase"] and m.dits == [ouvert["phrase"]]
    m.service.interpreter(FR_SUR, interdit)
    assert m.service.tours()[-1]["sortie"] == "ecran"
    # Au téléphone, la voix du PC n'est pas en cause : aucun avertissement de voix.
    assert "Aucune voix" not in (construire(sortie="telephone", voix=()).service.etat()["empechement"] or "")


def test_dans_le_doute_iris_le_dit_une_fois_et_ne_traduit_rien():
    horloge = Horloge()
    modele = FauxModele()
    m = construire(horloge=horloge, modele=modele)
    m.service.demarrer("en", annoncer=False)
    panne = lambda: Ecoute(erreur="pas de réseau")
    assert m.service.interpreter(CHARABIA_LOCAL, panne)["dit"] is True
    assert m.service.interpreter(CHARABIA_LOCAL, panne)["dit"] is False  # pas deux fois de suite
    horloge.avancer(DOUTE_INTERVALLE + 0.1)
    assert m.service.interpreter(CHARABIA_LOCAL, panne)["dit"] is True
    assert modele.appels == [] and m.service.tours() == []
    assert len(m.dits) == 2 and m.hub.de_type("interprete.doute")
    assert m.service.etat()["dernier_doute"]["raison"] == "pas de réseau"


def test_une_traduction_qui_arrive_apres_la_fermeture_nest_ni_dite_ni_jouee():
    m = construire()
    m.trad._interroger = FauxModele(apres=lambda: m.service.arreter("demande"))
    m.service.demarrer("en", annoncer=False)
    assert m.service.interpreter(FR_SUR, interdit).get("abandon") is True
    assert m.service.voix.dites == [] and m.dits == []


# =========================================================================== 4. ouvrir, fermer, verrous
def test_demarrer_lance_lecoute_si_elle_dort_et_refuse_si_elle_ne_part_pas():
    ecoute = FausseEcoute(running=False)
    m = construire(ecoute=ecoute)
    m.service.demarrer("en", annoncer=False)
    assert ecoute.demarrages == 1 and m.service.actif

    muette = FausseEcoute(running=False, demarre=False)
    m2 = construire(ecoute=muette)
    with pytest.raises(RefusInterprete) as refus:
        m2.service.demarrer("en")
    assert refus.value.statut == 409 and "lunettes" in refus.value.message
    assert not m2.service.actif


def test_larret_est_propre_et_sur_a_appeler_deux_fois():
    m = construire()
    m.service.demarrer("en", annoncer=False)
    m.service.interpreter(FR_SUR, interdit)
    assert m.service.tours()
    etat = m.service.arreter()
    assert etat["actif"] is False and etat["tours"] == [] and etat["phrase"].endswith("Je ne traduis plus.")
    assert m.service.voix.arrets >= 1 and m.trad.fil() == []
    assert m.hub.de_type("interprete.etat")[-1]["actif"] is False
    assert m.service.arreter()["actif"] is False


def test_fermer_linterprete_ne_ferme_pas_une_traduction_simple():
    m = construire()
    m.trad.demarrer("en")
    m.service.arreter()
    assert m.trad.actif and not m.trad.bidirectionnel


def test_la_boucle_qui_referme_la_traduction_previent_linterprete():
    """« Iris, arrête » est entendu par l'écoute, qui ferme ServiceTraduction : l'interprète doit le savoir."""
    m = construire()
    m.service.demarrer("en", annoncer=False)
    m.trad.arreter("demande")
    assert not m.service.actif and m.service.voix.arrets == 1


def test_mode_confidentiel_rien_ne_demarre_et_linterprete_ouvert_se_referme():
    m = construire()
    m.service.demarrer("en", annoncer=False)
    m.reglages.user.privacy_mode = True
    m.service.appliquer_reglages()
    assert not m.service.actif
    with pytest.raises(RefusInterprete) as refus:
        m.service.demarrer("en")
    assert refus.value.statut == 409 and "confidentiel" in refus.value.message
    with pytest.raises(RefusInterprete):
        asyncio.run(m.service.traduire_texte("moi", "bonjour madame"))


def test_mode_local_refuse_et_explique():
    modele = FauxModele()
    m = construire(local_only=True, modele=modele)
    with pytest.raises(RefusInterprete) as refus:
        m.service.demarrer("en")
    assert refus.value.statut == 409 and "mode local" in refus.value.message.lower()
    assert m.service.etat()["empechement_bloquant"] is True
    with pytest.raises(RefusInterprete):
        asyncio.run(m.service.traduire_texte("autre", "where is the station"))
    assert modele.appels == []


def test_sans_consentement_du_texte_rien_ne_part_et_le_refus_est_un_403_structure():
    modele = FauxModele()
    m = construire(modele=modele)

    def refuse(message=None):
        raise ConsentRequired("transcript")

    m.trad.verifier_envoi = refuse
    with pytest.raises(RefusInterprete) as refus:
        m.service.demarrer("en")
    assert refus.value.statut == 403
    assert refus.value.detail["code"] == "consentement" and refus.value.detail["data_type"] == "transcript"
    # Même le chemin historique de la traduction simple ne peut plus envoyer sans cet accord.
    m.trad.demarrer("en")
    resultat = asyncio.run(m.trad.traduire_entendu("where is the train station please"))
    assert not resultat.ok and "Confidentialité" in resultat.a_dire and modele.appels == []


def test_sans_consentement_audio_la_voix_ne_demarre_pas_mais_le_texte_du_telephone_oui():
    m = construire(audio=False)
    with pytest.raises(RefusInterprete) as refus:
        m.service.demarrer("en")
    assert refus.value.statut == 403 and refus.value.detail["data_type"] == "audio_raw"
    assert asyncio.run(m.service.traduire_texte("moi", "pouvez-vous m'aider"))["traduction"]


def test_langue_invalide_ou_identique_a_la_mienne():
    m = construire()
    for langue in ("klingon", "fr"):
        with pytest.raises(RefusInterprete) as refus:
            m.service.demarrer(langue)
        assert refus.value.statut == 422
    with pytest.raises(RefusInterprete):
        m.service.demarrer("en", "haut-parleur")
    assert all(l["code"] != "fr" for l in m.service.langues())


# =========================================================================== 5. texte du téléphone
def test_le_texte_du_telephone_est_traduit_dans_les_deux_sens_et_rejoint_le_fil():
    horloge = Horloge()
    m = construire(horloge=horloge, modele=FauxModele(horloge, cout=0.8))
    moi = asyncio.run(m.service.traduire_texte("moi", "Pouvez-vous m'aider à trouver mon hôtel ?"))
    assert moi == {"ok": True, "traduction": "Can you help me find my hotel?", "langue_source": "fr",
                   "langue_cible": "en", "latence_ms": 800}
    autre = asyncio.run(m.service.traduire_texte("autre", "sure I can help you", langue="es"))
    assert autre["langue_source"] == "es" and autre["langue_cible"] == "fr"
    tours = m.service.tours()
    assert [t["origine"] for t in tours] == ["texte", "texte"] and tours[0]["sortie"] == "appelant"
    assert m.service.voix.dites == [] and m.dits == [], "la voix est jouée par l'appelant, pas par le PC"
    with pytest.raises(RefusInterprete) as refus:
        asyncio.run(m.service.traduire_texte("lui", "hello"))
    assert refus.value.statut == 422
    with pytest.raises(RefusInterprete):
        asyncio.run(m.service.traduire_texte("moi", "   "))


# =========================================================================== 6. décodage pendant la parole
class FauxReconnaisseur:
    def __init__(self, mots=("bonjour", "madame", "merci"), conf=0.95):
        self.mots, self.conf, self.blocs = list(mots), conf, 0

    def AcceptWaveform(self, data):  # noqa: N802 - signature Vosk
        self.blocs += 1
        return self.blocs == 2

    def Result(self):  # noqa: N802
        return json.dumps({"result": [{"word": self.mots[0], "conf": self.conf}]})

    def FinalResult(self):  # noqa: N802
        return json.dumps({"result": [{"word": m, "conf": self.conf} for m in self.mots[1:]]})


def test_le_decodeur_continu_rend_la_phrase_decodee_pendant_la_parole():
    fabriques: list[FauxReconnaisseur] = []

    def fabrique():
        fabriques.append(FauxReconnaisseur())
        return fabriques[-1]

    d = DecodeurContinu(fabrique, "fr")
    for _ in range(4):
        d.pousser(PAROLE)
    jeton = d.clore()
    ecoute = jeton.attendre(2.0)
    assert ecoute is not None and ecoute.texte == "bonjour madame merci" and ecoute.confiance == pytest.approx(0.95)
    assert fabriques[0].blocs == 4
    # Une toux : annulée, rien n'est rendu ; la phrase suivante repart d'un reconnaisseur neuf.
    d.pousser(PAROLE)
    d.annuler()
    d.pousser(PAROLE)
    d.pousser(PAROLE)
    assert d.clore().attendre(2.0).texte == "bonjour madame merci"
    assert fabriques[-1] is not fabriques[0] and fabriques[-1].blocs == 2
    d.fermer()


def test_un_reconnaisseur_qui_plante_ne_bloque_pas_lattente():
    def fabrique():
        raise RuntimeError("modèle illisible")

    d = DecodeurContinu(fabrique)
    d.pousser(PAROLE)
    debut = time.monotonic()
    assert d.clore().attendre(2.0) is None
    assert time.monotonic() - debut < 1.5
    d.fermer()


# =========================================================================== 7. la voix de l'autre langue
def test_classement_et_lecture_des_voix_de_windows():
    assert langue_de_lcid(lire_lcid("1009")) == "en" and langue_de_lcid(lire_lcid("C0A;A")) == "es"
    assert lire_lcid("n'importe quoi") is None
    voix = [{"id": "1", "nom": "Zira", "langue": "en", "region": "États-Unis", "recente": False},
            {"id": "2", "nom": "Linda", "langue": "en", "region": "Canada", "recente": True},
            {"id": "3", "nom": "Claude", "langue": "fr", "region": "Canada", "recente": True}]
    assert [v["id"] for v in classer_voix(voix, "en")] == ["2", "1"]
    v = VoixAutreLangue(reglages(), lister=lambda: voix, synthetiser=lambda *a: (b"", 0), jouer=lambda *a: "pc")
    assert v.disponible("en") and not v.disponible("es")
    assert v.nom_voix("fr") == "Voix de l'ordinateur en français (Canada)"
    assert "Claude" not in v.nom_voix("fr"), "le masque de marque vaut aussi pour le prénom d'une voix"
    v.fermer()


def test_la_voix_joue_en_file_signale_quelle_parle_et_sarrete_net():
    hub = FauxHub()
    commence, relache = threading.Event(), threading.Event()
    rendus: list[tuple[str, str]] = []
    joues: list[tuple[int, str, bool]] = []

    def synthetiser(voix, texte):
        rendus.append((voix["id"], texte))
        return PAROLE, 22050

    def jouer(pcm, taux, sortie, doit_arreter):
        commence.set()
        relache.wait(2.0)
        joues.append((taux, sortie, doit_arreter()))
        return sortie

    v = VoixAutreLangue(reglages(), hub, lister=lambda: [{"id": "linda", "nom": "Linda", "langue": "en",
                                                            "region": "Canada", "recente": True}],
                        synthetiser=synthetiser, jouer=jouer)
    assert v.parler("See you tomorrow.", "en", "lunettes") is True
    assert v.parler("And the day after.", "en", "lunettes") is True
    assert commence.wait(2.0) and v.parle
    v.arreter()  # coupe la phrase en cours ET oublie celle qui attend
    relache.set()
    fin = time.monotonic() + 2.0
    while v.parle and time.monotonic() < fin:
        time.sleep(0.01)
    assert not v.parle
    assert rendus == [("linda", "See you tomorrow.")]
    assert joues == [(22050, "lunettes", True)]
    assert v.parler("Hola", "es") is False
    v.fermer()


def test_sans_audio_autorise_la_voix_ne_touche_a_aucun_peripherique():
    v = VoixAutreLangue(reglages(), actif=False)
    assert v.voix() == [] and v.parler("hello", "en") is False and v.raison


class FauxSounddevice:
    def __init__(self, noms):
        self.noms = noms

    def query_hostapis(self):
        return [{"name": "MME"}]

    def query_devices(self, kind=None):
        if kind == "output":
            return {"default_samplerate": 48000}
        return [{"name": n, "max_output_channels": 1, "hostapi": 0, "default_samplerate": 16000} for n in self.noms]

    def check_output_settings(self, device=None, samplerate=0, channels=1, dtype="int16"):
        if device is not None and samplerate != 16000:
            raise ValueError("fréquence refusée")


def test_la_sortie_lunettes_suit_la_regle_des_autres_voix_et_se_replie_en_le_disant():
    hub = FauxHub()
    u = reglages(audio_output_device="Casque (M01 Pro_F444 Hands-Free", audio_input_device="",
                 glasses=SimpleNamespace(name="M01 Pro_F444"))
    v = VoixAutreLangue(u, hub, lister=lambda: [], synthetiser=lambda *a: (b"", 0), jouer=lambda *a: "pc")
    sd = FauxSounddevice(["Haut-parleurs (Realtek)", "Casque (M01 Pro_F444 Hands-Free AG Audio)"])
    assert v._peripherique(sd, "lunettes", 22050) == (1, 16000, "lunettes")
    assert hub.de_type("interprete.voix") == []
    assert v._peripherique(FauxSounddevice(["Haut-parleurs (Realtek)"]), "lunettes", 22050)[2] == "pc"
    assert hub.de_type("interprete.voix")[-1]["raison"] == REPLI_LUNETTES
    assert v._peripherique(sd, "pc", 22050) == (None, 22050, "pc")
    v.fermer()


# =========================================================================== 8. l'écoute (fil audio, doublures)
@pytest.fixture()
def voix_app(app, monkeypatch):
    """L'écoute réelle de l'application, avec une voix muette, sans lunettes exigées, et l'interprète
    branché sur un faux modèle et une fausse voix de l'autre langue."""
    ctx = app.state.ctx
    ctx.settings.update({"demo_sans_lunettes": True})
    # Le vérificateur choisit le moteur sur chaque message, comme demander_court : il faut qu'un moteur
    # (en ligne) soit prêt, et c'est le faux modèle qui répond à sa place.
    monkeypatch.setattr(ctx.chat.router, "available", lambda secrets: ["vela"])
    ctx.consent.set("audio_raw", True)
    ctx.consent.set("transcript", True)
    v = ctx.voice
    v.tts = SimpleNamespace(available=True, is_speaking=False, dites=[], wait_idle=lambda timeout=0: True,
                            stop=lambda: None)
    v.tts.speak = lambda texte, force=False: v.tts.dites.append(texte) or True
    v._stop.clear()
    v._ptt.clear()
    ctx.traduction._interroger = FauxModele()
    ctx.interprete.voix = FausseVoix(("en",))
    ctx.interprete.ecoute = FausseEcoute()
    return v


def test_linterception_est_branchee_en_priorite_30_et_la_traduction_simple_lui_laisse_ses_phrases(voix_app):
    assert (30, "interprete") in [(p, n) for p, n, _f in voix_app._interceptions]
    assert voix_app._est_demande_traduction("mode interprète anglais") is False
    assert voix_app._est_demande_traduction("fin de l'interprète") is False
    assert voix_app._est_demande_traduction("traduis ce qu'il dit") is True


def test_mode_interprete_anglais_a_la_voix_ouvre_sans_passer_par_le_modele(voix_app, monkeypatch):
    etats: list[str] = []
    monkeypatch.setattr(voix_app, "_set_state", lambda etat, **k: etats.append(etat))
    voix_app._process("mode interprète anglais")
    assert "processing" not in etats
    assert voix_app.traduction.bidirectionnel and voix_app.traduction.actif
    assert voix_app.tts.dites and "Interprète en anglais" in voix_app.tts.dites[0]
    assert voix_app._traduction_en_attente() is True  # _command_cycle enchaîne sur la boucle


def test_le_consentement_et_le_moteur_sont_choisis_a_chaque_envoi_sur_le_message_lui_meme():
    from iris.routes_interprete import fabriquer_verificateur

    selections: list[str] = []
    verifications: list[Any] = []
    u = SimpleNamespace(local_only=False, agents={"vela": SimpleNamespace(local=False)})
    routeur = SimpleNamespace(available=lambda secrets: ["vela"],
                              select=lambda texte, img, dispo, demande: selections.append(texte) or ("vela", ""))
    ctx = SimpleNamespace(settings=SimpleNamespace(user=u), chat=SimpleNamespace(router=routeur, secrets=None),
                          consent=SimpleNamespace(check=lambda t, agent=None: verifications.append((t, agent))))
    verifier = fabriquer_verificateur(ctx)
    assert verifier("À traduire :\n<<<hello>>>") == ("vela", False)
    assert verifier("À traduire :\n<<<open the file>>>") == ("vela", False)
    assert selections == ["À traduire :\n<<<hello>>>", "À traduire :\n<<<open the file>>>"], \
        "aucun cache : le moteur est choisi sur CHAQUE message, comme demander_court"
    assert verifications == [("transcript", "vela"), ("transcript", "vela")]
    # Vérification préalable (aucun message) : un moteur en ligne est disponible, l'accord est exigé sans agent.
    verifications.clear()
    assert verifier(None) == (None, False) and verifications == [("transcript", None)]


class FausseBase:
    """Juste ce que le vrai ConsentGate lit et écrit : les accords et le registre chaîné."""

    def __init__(self, accordes=()):
        self.accordes = set(accordes)
        self.registre: list[dict] = []

    def one(self, sql: str, params=()):
        if "FROM consents" in sql:
            return {"granted": 1} if params[0] in self.accordes else None
        if "FROM privacy_events" in sql:
            return {"hash": self.registre[-1]["hash"]} if self.registre else None
        return None

    def execute(self, sql: str, params=()):
        if "privacy_events" in sql:
            cles = ("created_at", "event_type", "data_type", "agent", "detail", "prev_hash", "hash")
            self.registre.append(dict(zip(cles, params)))


class ModeleRoute(FauxModele):
    """Comme ChatService.demander_court : le moteur est choisi par le VRAI routeur sur le message."""

    def __init__(self, ctx, reponse: Any = None):
        super().__init__()
        self.ctx, self.reponse, self.envois = ctx, reponse, []

    def __call__(self, systeme: str, message: str):
        routeur = self.ctx.chat.router
        agent, _r = routeur.select(message, False, routeur.available(None), "auto")
        self.envois.append(agent)
        if isinstance(self.reponse, Exception):
            raise self.reponse
        if self.reponse is not None:
            return self.reponse
        return super().__call__(systeme, message)


def contexte_routage(accordes=()):
    """Moteur par défaut LOCAL, moteur en ligne disponible, vrai routeur, vrai ConsentGate."""
    from iris.consent import ConsentGate
    from iris.router import AgentRouter

    u = SimpleNamespace(local_only=False, routing_mode="auto", default_agent="custom",
                        agents={"custom": SimpleNamespace(local=True, active=True),
                                "claude": SimpleNamespace(local=False, active=True)})
    settings = SimpleNamespace(user=u)
    routeur = AgentRouter(settings)
    routeur.available = lambda secrets: ["custom", "claude"]
    base = FausseBase(accordes)
    ctx = SimpleNamespace(settings=settings, chat=SimpleNamespace(router=routeur, secrets=None),
                          consent=ConsentGate(base, settings, None))
    return ctx, base


def test_une_phrase_routee_vers_un_moteur_en_ligne_ne_part_jamais_sans_accord():
    """Constat du 2026-09-14 : le vérificateur choisissait le moteur sur le mot « traduction » (IA locale,
    donc aucun accord exigé) alors que l'envoi réel le choisit sur le message (mot-clé ordinateur ->
    moteur en ligne)."""
    from iris.routes_interprete import fabriquer_verificateur

    ctx, base = contexte_routage()
    modele = ModeleRoute(ctx)
    t = ServiceTraduction(modele, settings=reglages(), registre=ctx.consent)
    t.verifier_envoi = fabriquer_verificateur(ctx)
    refuse = asyncio.run(t.traduire_texte("can you open the file on my computer", "en", "fr"))
    assert not refuse.ok and "Confidentialité" in refuse.raison
    assert modele.envois == [], "le faux moteur ne doit JAMAIS être appelé"
    assert [e for e in base.registre if e["event_type"] == "external_send"] == []
    # Une phrase sans mot-clé reste sur l'IA locale : elle passe, et rien n'est inscrit comme envoi externe.
    local = asyncio.run(t.traduire_texte("where is the train station please", "en", "fr"))
    assert local.ok and modele.envois == ["custom"] and base.registre == []
    # Le chemin de l'interprète (téléphone) : la vérification préalable exige l'accord, rien ne part.
    service = ServiceInterprete(t, reglages(), hub=FauxHub(), voix=FausseVoix(), ecoute=FausseEcoute())
    with pytest.raises(RefusInterprete) as refus:
        asyncio.run(service.traduire_texte("autre", "can you open the file on my computer"))
    assert refus.value.statut == 403 and modele.envois == ["custom"]


def test_chaque_envoi_est_inscrit_au_registre_avant_de_partir_meme_quand_il_echoue(monkeypatch):
    from iris import traduction as traduction_mod
    from iris.routes_interprete import fabriquer_verificateur

    ctx, base = contexte_routage(accordes=("transcript",))
    phrase = "can you open the file on my computer"
    for reponse in (RuntimeError("panne du connecteur"), "TRADUCTION: ?", "TRADUCTION: can you open the file"):
        base.registre.clear()
        modele = ModeleRoute(ctx, reponse=reponse)
        t = ServiceTraduction(modele, settings=reglages(), registre=ctx.consent)
        t.verifier_envoi = fabriquer_verificateur(ctx)
        resultat = asyncio.run(t.traduire_texte(phrase, "en", "fr"))
        assert not resultat.ok and modele.envois == ["claude"]
        (envoi,) = base.registre
        assert envoi["event_type"] == "external_send" and envoi["data_type"] == "transcript"
        assert envoi["agent"] == "claude", "le moteur réellement joint, pas une constante"
        assert "caractères" in envoi["detail"] and "open" not in envoi["detail"] and "file" not in envoi["detail"]
        assert "panne" not in t.erreur, "le détail technique reste au journal"

    # Délai dépassé : le texte est parti, l'inscription aussi.
    monkeypatch.setattr(traduction_mod, "DELAI_MODELE", 0.05)
    base.registre.clear()

    async def lent(systeme, message):
        await asyncio.sleep(1.0)
        return "TRADUCTION: trop tard"

    t = ServiceTraduction(lent, settings=reglages(), registre=ctx.consent)
    t.verifier_envoi = fabriquer_verificateur(ctx)
    assert not asyncio.run(t.traduire_texte(phrase, "en", "fr")).ok
    assert [e["event_type"] for e in base.registre] == ["external_send"]
    # Succès : UNE inscription, pas deux.
    base.registre.clear()
    t = ServiceTraduction(ModeleRoute(ctx), settings=reglages(), registre=ctx.consent)
    t.verifier_envoi = fabriquer_verificateur(ctx)
    assert asyncio.run(t.traduire_texte(phrase, "en", "fr")).ok
    assert len(base.registre) == 1


def test_le_refus_dun_appel_nest_pas_dit_par_un_autre_appel_simultane():
    """La boucle vocale et la route /texte partagent le même service : le refus est rendu, pas partagé."""

    async def modele(systeme, message):
        await asyncio.sleep(0.05)
        return ""  # le moteur ne rend rien : échec ordinaire, sans refus

    def verifier(message=None):
        if message is not None and "secret" in message:
            raise ConsentRequired("transcript")
        return ("vela", False)

    t = ServiceTraduction(modele, settings=reglages())
    t.verifier_envoi = verifier

    async def les_deux():
        return await asyncio.gather(t.traduire_texte("where is the station", "en", "fr"),
                                    t.traduire_texte("the secret code", "en", "fr"))

    echec, refus = asyncio.run(les_deux())
    assert not echec.ok and "Confidentialité" not in echec.raison
    assert not refus.ok and "Confidentialité" in refus.raison
    assert not hasattr(t, "_refus")


def test_le_guetteur_ferme_linterprete_sur_iris_fin(voix_app):
    for entendu, attendu in [
        ("iris fin de arrete", "demande"),   # rendu mesuré de « Iris, fin de l'interprète »
        ("iris stop dis arrete", "demande"),
        ("iris arrete", "demande"),
        ("fin stop", ""),                    # sans le nom, rien ne ferme (rendu mesuré sur de l'anglais)
        ("de stop", ""),
        ("iris", ""),
    ]:
        assert voix_app._sortie_traduction(entendu, []) == attendu, entendu


def test_en_mode_interprete_la_boucle_decode_pendant_la_parole_et_mesure_la_fin(voix_app):
    ctx_trad = voix_app.traduction
    ctx_trad.demarrer("en", bidirectionnel=True)
    decodeur = SimpleNamespace(poussees=0, annulations=0, clotures=0, fermee=False)
    decodeur.pousser = lambda bloc: setattr(decodeur, "poussees", decodeur.poussees + 1)
    decodeur.annuler = lambda: setattr(decodeur, "annulations", decodeur.annulations + 1)
    decodeur.clore = lambda: setattr(decodeur, "clotures", decodeur.clotures + 1) or "jeton"
    decodeur.fermer = lambda: setattr(decodeur, "fermee", True)
    taches: list[tuple] = []
    blocs = [SILENCE] * 4 + [PAROLE] * 4 + [SILENCE] * 3
    voix_app._read = lambda timeout=0.3: blocs.pop(0) if blocs else voix_app._stop.set()
    voix_app._drain = lambda: None
    voix_app._guetteur_de_sortie = lambda mots: None
    voix_app._decodeur_interprete = lambda: decodeur
    voix_app._traduire_segment = lambda *args: taches.append(args)
    avant = time.monotonic()
    voix_app._boucle_traduction()
    fin = time.monotonic() + 2.0
    while not taches and time.monotonic() < fin:
        time.sleep(0.01)
    assert len(taches) == 1
    pcm, jeton, fin_parole = taches[0]
    assert len(pcm) == 7 * len(PAROLE) and jeton == "jeton"
    assert decodeur.poussees == 7 and decodeur.clotures == 1 and decodeur.fermee
    assert avant - 1.0 <= fin_parole <= time.monotonic()
    voix_app._stop.clear()


def test_pendant_que_la_voix_de_lautre_langue_parle_rien_nest_accumule(voix_app):
    voix_app.traduction.demarrer("en", bidirectionnel=True)
    voix_app.traduction.interprete.voix.parle = True
    decodeur = SimpleNamespace(annulations=0, pousser=lambda b: pytest.fail("rien ne doit être décodé"),
                               clore=lambda: None, fermer=lambda: None)
    decodeur.annuler = lambda: setattr(decodeur, "annulations", decodeur.annulations + 1)
    taches: list = []
    blocs = [SILENCE] * 4 + [PAROLE] * 6 + [SILENCE] * 4
    voix_app._read = lambda timeout=0.3: blocs.pop(0) if blocs else voix_app._stop.set()
    voix_app._drain = lambda: None
    voix_app._guetteur_de_sortie = lambda mots: None
    voix_app._decodeur_interprete = lambda: decodeur
    voix_app._traduire_segment = lambda *a: taches.append(a)
    voix_app._boucle_traduction()
    time.sleep(0.05)
    assert taches == [] and decodeur.annulations > 0
    voix_app._stop.clear()


def test_une_phrase_du_proprietaire_va_de_bout_en_bout_vers_la_voix_anglaise(voix_app):
    """Fil de travail réel : jeton du décodeur -> interpréter -> traduire -> voix de l'autre langue."""
    voix_app.traduction.interprete.demarrer("en", "pc", annoncer=False)
    jeton = SimpleNamespace(attendre=lambda delai: FR_SUR, abandonner=lambda: None)
    voix_app._reconnaitre_bilingue = lambda pcm, langue: pytest.fail("ma phrase sûre ne part pas en ligne")
    voix_app._traduire_segment(PAROLE * 4, jeton, time.monotonic())
    assert voix_app.traduction.interprete.voix.dites == [("Can you help me find my hotel?", "en", "pc")]
    assert voix_app.tts.dites == []
    tour = voix_app.traduction.interprete.tours()[-1]
    assert tour["qui"] == "moi" and tour["latence_ms"] is not None and tour["latence_ms"] >= 0


def test_une_phrase_de_lautre_va_de_bout_en_bout_vers_les_lunettes(voix_app):
    voix_app.traduction.interprete.demarrer("en", "pc", annoncer=False)
    jeton = SimpleNamespace(attendre=lambda delai: CHARABIA_LOCAL, abandonner=lambda: None)
    voix_app._reconnaitre_bilingue = lambda pcm, langue: EN_EN_LIGNE
    voix_app._traduire_segment(PAROLE * 4, jeton, time.monotonic())
    assert voix_app.tts.dites == ["Bien sûr, je peux vous aider à trouver votre hôtel."]
    assert voix_app.traduction.interprete.voix.dites == []


def test_la_reconnaissance_en_ligne_ne_devine_pas_la_langue_et_trace_chaque_envoi(voix_app, monkeypatch):
    appels: list[tuple] = []
    traces: list[dict] = []
    monkeypatch.setattr(stt, "pool_elevenlabs", lambda: ["cle"])
    monkeypatch.setattr(stt, "scribe_recognize", lambda pcm, rate, langue, **k: appels.append(("principal", langue)) or " Hello there ")
    monkeypatch.setattr(stt, "google_recognize", lambda *a, **k: pytest.fail("pas de repli quand le principal répond"))
    monkeypatch.setattr(voix_app.consent, "log", lambda *a, **k: traces.append(k))
    e = voix_app._reconnaitre_bilingue(PAROLE, "es")
    assert e.texte == "Hello there" and e.langue == "" and appels == [("principal", "")]
    assert traces and traces[0]["data_type"] == "audio_raw" and "Hello" not in traces[0]["detail"]

    # Principal en panne : le repli exige une langue, c'est celle de l'autre, et l'Ecoute le dit.
    def panne(*a, **k):
        raise stt.ReconnaissanceImpossible(stt.RESEAU, "hors ligne")

    monkeypatch.setattr(stt, "scribe_recognize", panne)
    monkeypatch.setattr(stt, "google_recognize", lambda pcm, rate, locale: appels.append(("repli", locale)) or "hola")
    assert voix_app._reconnaitre_bilingue(PAROLE, "es").langue == "es" and appels[-1] == ("repli", "es-ES")


def test_sans_consentement_ou_en_mode_local_aucune_voix_ne_part(voix_app, monkeypatch):
    monkeypatch.setattr(stt, "scribe_recognize", lambda *a, **k: pytest.fail("aucun envoi"))
    monkeypatch.setattr(stt, "google_recognize", lambda *a, **k: pytest.fail("aucun envoi"))
    voix_app.consent.set("audio_raw", False)
    assert voix_app._reconnaitre_bilingue(PAROLE, "en").erreur
    voix_app.consent.set("audio_raw", True)
    voix_app.settings.update({"local_only": True})
    assert voix_app._reconnaitre_bilingue(PAROLE, "en").erreur


# =========================================================================== 9. les routes
@pytest.fixture()
def routes(client, app, monkeypatch):
    ctx = app.state.ctx
    ctx.settings.update({"demo_sans_lunettes": True})
    ctx.consent.set("audio_raw", True)
    ctx.consent.set("transcript", True)
    monkeypatch.setattr(ctx.chat.router, "available", lambda secrets: ["vela"])
    ctx.traduction._interroger = FauxModele()
    ctx.interprete.voix = FausseVoix(("en",))
    v = ctx.voice
    v.demarrages = []
    v.ecoute_active = False

    def faux_start(one_shot: bool = False) -> dict:
        v.demarrages.append(one_shot)
        v.ecoute_active = True
        return {"running": True}

    monkeypatch.setattr(ecoute_mod.VoiceListener, "running",
                        property(lambda self: bool(getattr(self, "ecoute_active", False))))
    v.start = faux_start
    return ctx


def test_les_routes_exigent_le_jeton(client_sans_jeton):
    assert client_sans_jeton.get("/api/interprete/etat").status_code == 401
    assert client_sans_jeton.post("/api/interprete/demarrer", json={}).status_code == 401
    assert client_sans_jeton.post("/api/interprete/arreter").status_code == 401
    assert client_sans_jeton.post("/api/interprete/texte", json={"qui": "moi", "texte": "x"}).status_code == 401


def test_routes_etat_demarrer_texte_arreter(client, routes):
    etat = client.get("/api/interprete/etat").json()
    for cle in ("actif", "langue_moi", "langue_autre", "sortie_autre", "tours", "langues", "empechement"):
        assert cle in etat
    assert etat["actif"] is False and etat["langue_moi"] == "fr"
    assert {"code": "en", "nom": "anglais", "voix": True} in etat["langues"]

    ouvert = client.post("/api/interprete/demarrer", json={"langue_autre": "en", "sortie_autre": "telephone"}).json()
    assert ouvert["actif"] is True and ouvert["sortie_autre"] == "telephone" and routes.voice.demarrages == [False]
    assert routes.voice._traduction_en_attente() is True, "le fil audio entrera dans la boucle au bloc suivant"

    r = client.post("/api/interprete/texte", json={"qui": "moi", "texte": "Pouvez-vous m'aider ?"})
    assert r.status_code == 200 and r.json()["traduction"] == "Can you help me find my hotel?"
    assert set(r.json()) >= {"traduction", "langue_source", "langue_cible", "latence_ms"}
    assert client.get("/api/interprete/etat").json()["tours"][-1]["origine"] == "texte"
    assert client.post("/api/interprete/texte", json={"qui": "personne", "texte": "x"}).status_code == 422

    ferme = client.post("/api/interprete/arreter").json()
    assert ferme["actif"] is False and ferme["tours"] == []
    assert client.post("/api/interprete/arreter").status_code == 200


def test_routes_refus_confidentiel_local_et_consentement(client, routes):
    routes.consent.set("transcript", False)
    r = client.post("/api/interprete/demarrer", json={"langue_autre": "en"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consentement"
    assert routes.voice.demarrages == []
    routes.consent.set("transcript", True)

    client.patch("/api/settings", json={"local_only": True})
    r = client.post("/api/interprete/demarrer", json={"langue_autre": "en"})
    assert r.status_code == 409 and "mode local" in str(r.json()["detail"]).lower()
    client.patch("/api/settings", json={"local_only": False})

    client.patch("/api/settings", json={"privacy_mode": True})
    r = client.post("/api/interprete/demarrer", json={"langue_autre": "en"})
    assert r.status_code == 409 and "confidentiel" in str(r.json()["detail"])
    assert client.post("/api/interprete/texte", json={"qui": "moi", "texte": "bonjour madame"}).status_code == 409
    assert routes.voice.demarrages == [] and not routes.interprete.actif


def test_dehors_lunettes_attestees_par_le_telephone_le_micro_du_pc_ne_souvre_pas(client, routes, monkeypatch):
    """Erratum F : dehors, le téléphone n'appelle que /texte. Un client bogué ou ancien qui appellerait
    /demarrer ouvrirait le micro de l'ordinateur resté à la maison : le service le refuse lui-même."""
    routes.settings.update({"require_glasses": True, "demo_sans_lunettes": False,
                            "glasses": {"name": "M01 Pro_F444", "address": "", "auto_connect": False}})
    monkeypatch.setattr(routes.voice, "lunettes_presentes", lambda: False)
    att = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "iphone-1", "source": "iphone"})
    assert att.status_code == 200 and att.json()["source"] == "telephone"
    try:
        r = client.post("/api/interprete/demarrer", json={"langue_autre": "en", "sortie_autre": "telephone"})
        assert r.status_code == 409 and "traduction par texte" in r.json()["detail"]
        assert routes.voice.demarrages == [] and not routes.interprete.actif
        # Le chemin prévu pour le téléphone reste ouvert.
        texte = client.post("/api/interprete/texte", json={"qui": "moi", "texte": "Pouvez-vous m'aider ?"})
        assert texte.status_code == 200 and texte.json()["traduction"] == "Can you help me find my hotel?"
        # Les lunettes vues par l'ordinateur : l'interprète vocal redevient possible.
        monkeypatch.setattr(routes.voice, "lunettes_presentes", lambda: True)
        ouvert = client.post("/api/interprete/demarrer", json={"langue_autre": "en"})
        assert ouvert.status_code == 200 and routes.voice.demarrages == [False]
        client.post("/api/interprete/arreter")
    finally:
        client.delete("/api/lunettes/attestation")
