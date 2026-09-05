"""Le relais tient la clé IA de VELA. Ces tests portent sur ce qui coûterait cher s'il cédait.

Trois choses doivent tenir : un plan Gratuit ne doit jamais atteindre un modèle payant, un jeton
forgé ne doit rien ouvrir, et une clé d'abonnement émise ici doit être acceptée par IRIS — sinon
le client paie et n'obtient rien.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def client(relais):
    from fastapi.testclient import TestClient

    return TestClient(relais.app)


def abonne(relais, courriel: str, plan: str, expires: str = "2099-01-01") -> None:
    (Path(relais.DONNEES)).mkdir(parents=True, exist_ok=True)
    (Path(relais.DONNEES) / "abonnes.json").write_text(
        json.dumps({courriel: {"plan": plan, "expires": expires}}), encoding="utf-8"
    )


# --------------------------------------------------------------------------- l'argent
def test_un_plan_gratuit_natteint_jamais_un_modele_payant(relais):
    for demande in ("anthropic/claude-opus-5", "openai/gpt-5-mini", "n'importe quoi"):
        choisi = relais.modele_autorise(demande, "gratuit")
        assert choisi.endswith(":free"), f"{demande} a donné {choisi}"


def test_chaque_plan_recoit_ce_quil_a_paye(relais):
    assert relais.modele_autorise("anthropic/claude-sonnet-5", "premium") == "anthropic/claude-sonnet-5"
    assert relais.modele_autorise("anthropic/claude-opus-5", "entreprise") == "anthropic/claude-opus-5"
    # Opus est réservé au dernier palier : un abonné Premium qui le demande obtient son propre modèle.
    assert relais.modele_autorise("anthropic/claude-opus-5", "premium") != "anthropic/claude-opus-5"


def test_un_abonnement_expire_retombe_au_gratuit(relais):
    abonne(relais, "ancien@exemple.com", "entreprise", expires="2020-01-01")
    etat = relais.abonnement("ancien@exemple.com")
    assert etat["plan"] == "gratuit" and etat.get("expire") is True


def test_le_quota_du_plan_est_applique(relais):
    from fastapi import HTTPException

    relais.QUOTAS["gratuit"] = 2
    relais.consommer("qui@exemple.com", "gratuit")
    relais.consommer("qui@exemple.com", "gratuit")
    with pytest.raises(HTTPException) as leve:
        relais.consommer("qui@exemple.com", "gratuit")
    assert leve.value.status_code == 429


# --------------------------------------------------------------------------- les jetons
def test_un_jeton_forge_est_refuse(relais):
    vrai = relais.emettre_jeton("client@exemple.com", "machine-1")
    assert relais.lire_jeton(vrai)["courriel"] == "client@exemple.com"
    corps, signature = vrai.rsplit(".", 1)
    assert relais.lire_jeton(corps + ".XXXX") is None, "signature modifiée"
    assert relais.lire_jeton("") is None
    assert relais.lire_jeton("n'importe.quoi.du.tout") is None


def test_un_jeton_perime_ne_vaut_plus_rien(relais, monkeypatch):
    monkeypatch.setattr(relais, "DUREE_JETON", -10)
    assert relais.lire_jeton(relais.emettre_jeton("client@exemple.com", "m")) is None


def test_changer_de_courriel_ne_donne_pas_le_plan_dun_autre(relais):
    """Le courriel est dans le corps signé : le modifier casse la signature."""
    jeton = relais.emettre_jeton("gratuit@exemple.com", "m")
    tete, reste = jeton.split(".", 1)
    autre = relais._b64(b"entreprise@exemple.com")
    assert relais.lire_jeton(autre + "." + reste) is None


def test_lia_est_fermee_sans_jeton(client):
    assert client.get("/v1/models").status_code == 401
    assert client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "salut"}]}).status_code == 401


def test_un_appareil_obtient_son_acces_et_voit_ses_modeles(client, relais):
    abonne(relais, "premium@exemple.com", "premium")
    reponse = client.post("/api/appareil", json={"machine": "abc", "email": "premium@exemple.com"}).json()
    assert reponse["plan"] == "premium"
    modeles = client.get("/v1/models", headers={"Authorization": "Bearer " + reponse["jeton"]}).json()
    assert "anthropic/claude-sonnet-5" in [m["id"] for m in modeles["data"]]


# --------------------------------------------------------------------------- l'abonnement
def test_une_cle_emise_ici_est_acceptee_par_iris(relais):
    """Le test qui compte vraiment : sinon le client paie, reçoit une clé, et IRIS la refuse."""
    from iris.plans import verify_key

    abonne(relais, "acheteur@exemple.com", "pro", expires="2099-06-30")
    cle = relais.cle_licence("pro", "2099-06-30", "acheteur@exemple.com")
    info = verify_key(cle)
    assert info is not None, "IRIS rejette la clé émise par le relais"
    assert info["plan"] == "pro" and info["expires"] == "2099-06-30" and not info["expired"]


def test_aucun_abonnement_pour_un_inconnu(client):
    assert client.get("/api/licence", params={"email": "personne@exemple.com"}).status_code == 404


def test_la_licence_dun_abonne_est_servie(client, relais):
    abonne(relais, "abonne@exemple.com", "entreprise", expires="2099-01-01")
    corps = client.get("/api/licence", params={"email": "Abonne@Exemple.com"}).json()
    assert corps["plan"] == "entreprise" and corps["key"].startswith("IRIS-")


def test_le_relais_ne_divulgue_jamais_sa_cle(client, relais):
    """Une clé d'API dans une réponse, et n'importe quel client peut vider le compte."""
    corps = json.dumps(client.get("/sante").json()) + json.dumps(
        client.post("/api/appareil", json={"machine": "m", "email": ""}).json()
    )
    assert relais.CLE_AMONT not in corps


# --------------------------------------------------------------------------- la voix incluse
# Les forfaits payants promettent une voix ElevenLabs. Sans ce relais, l'abonné devrait fournir sa
# propre clé : il paierait une voix qu'il n'entendrait jamais.
@pytest.fixture()
def avec_voix(relais, monkeypatch):
    monkeypatch.setattr(relais, "CLE_VOIX", "cle-voix-factice")
    return relais


def test_le_plan_gratuit_garde_la_voix_de_windows(client, avec_voix):
    jeton = client.post("/api/appareil", json={"machine": "m", "email": ""}).json()["jeton"]
    r = client.post("/v1/voix/abcdef", json={"text": "bonjour"}, headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 403
    assert "Windows" in r.json()["detail"], "le refus doit dire ce dont on dispose, pas seulement ce qu'on refuse"


def test_la_voix_est_fermee_sans_jeton(client, avec_voix):
    assert client.post("/v1/voix/abcdef", json={"text": "bonjour"}).status_code == 401


def test_un_identifiant_de_voix_fabrique_est_refuse(client, avec_voix):
    """Sans ce contrôle, l'identifiant partirait tel quel dans l'URL appelée en amont."""
    abonne(avec_voix, "pro@exemple.com", "pro")
    jeton = client.post("/api/appareil", json={"machine": "m", "email": "pro@exemple.com"}).json()["jeton"]
    entetes = {"Authorization": "Bearer " + jeton}
    for mauvais in ("../../compte", "abc/def", "a" * 60):
        r = client.post("/v1/voix/" + mauvais, json={"text": "bonjour"}, headers=entetes)
        assert r.status_code in (400, 404), mauvais


def test_la_cle_de_voix_ne_fuit_jamais(client, avec_voix):
    abonne(avec_voix, "pro@exemple.com", "pro")
    jeton = client.post("/api/appareil", json={"machine": "m", "email": "pro@exemple.com"}).json()["jeton"]
    r = client.post("/v1/voix/abcdef", json={"text": ""}, headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 400 and avec_voix.CLE_VOIX not in r.text


# --------------------------------------------------------------------------- une seule vérité
# Le serveur de licences (dossier server/) reçoit les paiements et décide qui est abonné. Le
# relais ne doit pas tenir une seconde liste : deux vérités finissent par diverger, et c'est
# toujours le client qui paie la différence.
def test_le_plan_vient_du_serveur_de_licences(relais, monkeypatch):
    monkeypatch.setenv("VELA_LICENCES_URL", "https://licences.exemple.test")
    abonne(relais, "double@exemple.com", "gratuit")  # le fichier local dit « gratuit »…

    class FausseReponse:
        status_code = 200

        @staticmethod
        def json():
            return {"plan": "entreprise", "expires": "2099-01-01"}

    class FauxClient:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, *_a, **_k): return FausseReponse()

    monkeypatch.setattr(relais.httpx, "Client", FauxClient)
    relais._CACHE.clear()
    assert relais.abonnement("double@exemple.com")["plan"] == "entreprise", "le serveur prime sur le fichier"


def test_un_serveur_injoignable_ne_coupe_pas_le_service(relais, monkeypatch):
    """Une panne du serveur de licences ne doit pas rendre IRIS muette pour tout le monde."""
    monkeypatch.setenv("VELA_LICENCES_URL", "https://licences.exemple.test")
    abonne(relais, "replis@exemple.com", "premium")

    class FauxClient:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, *_a, **_k): raise OSError("réseau coupé")

    monkeypatch.setattr(relais.httpx, "Client", FauxClient)
    relais._CACHE.clear()
    assert relais.abonnement("replis@exemple.com")["plan"] == "premium"


# --------------------------------------------------------------------------- l'argent réellement dépensé
# La clé qui paie est celle de Miguel, personnellement. Un quota en NOMBRE DE REQUÊTES ne le protège
# pas : une question courte et une demande avec capture d'écran, mémoire et long historique comptent
# toutes les deux pour un, alors que la seconde peut coûter cent fois la première.
def test_le_plafond_de_jetons_arrete_un_abonne(relais):
    from fastapi import HTTPException

    relais.PLAFONDS_JETONS["gratuit"] = 1000
    relais.enregistrer_jetons("gourmand@exemple.com", 1200)
    with pytest.raises(HTTPException) as leve:
        relais.consommer("gourmand@exemple.com", "gratuit")
    assert leve.value.status_code == 429
    assert "onsommation" in leve.value.detail, "le message doit se distinguer du quota de requêtes"


def test_les_deux_refus_ne_disent_pas_la_meme_chose(relais):
    """Dire « quota atteint » à quelqu'un qui en est à sa dixième requête lui ferait croire à une panne."""
    from fastapi import HTTPException

    relais.QUOTAS["gratuit"] = 1
    relais.PLAFONDS_JETONS["gratuit"] = 10 ** 9
    relais.consommer("compteur@exemple.com", "gratuit")
    with pytest.raises(HTTPException) as leve:
        relais.consommer("compteur@exemple.com", "gratuit")
    assert "requêtes" in leve.value.detail


def test_le_plafond_global_coupe_tout_le_monde(relais):
    """Le dernier rempart : celui qui empêche un compte OpenRouter d'être vidé pendant une nuit."""
    from fastapi import HTTPException

    relais.PLAFOND_GLOBAL = 500
    relais.enregistrer_jetons("quelquun@exemple.com", 600)
    with pytest.raises(HTTPException) as leve:
        relais.consommer("quelquun.dautre@exemple.com", "entreprise")
    assert leve.value.status_code == 503


def test_les_jetons_sannoncent_dans_le_flux(relais):
    """OpenRouter met la consommation dans le dernier bloc, parce que le client demande include_usage."""
    saut = chr(10)
    dernier = 'data: {"choices":[],"usage":{"total_tokens":4321}}' + saut + saut
    assert relais.jetons_du_flux(dernier.encode()) == 4321
    milieu = 'data: {"choices":[{"delta":{"content":"bon"}}]}' + saut + saut
    assert relais.jetons_du_flux(milieu.encode()) == 0, 'un bloc ordinaire ne compte rien'
    assert relais.jetons_du_flux(('data: pas du json' + saut).encode()) == 0
    assert relais.jetons_du_flux(('data: [DONE]' + saut).encode()) == 0
    assert relais.jetons_du_flux(b'') == 0


def test_une_reponse_sans_consommation_ne_casse_rien(relais):
    """Tous les modèles ne renvoient pas d'usage : l'absence ne doit jamais lever."""
    assert relais.jetons_de(None) == 0
    assert relais.jetons_de({}) == 0
    assert relais.jetons_de({"usage": None}) == 0
    assert relais.jetons_de({"usage": {"total_tokens": "abc"}}) == 0
    assert relais.jetons_de({"usage": {"total_tokens": 12}}) == 12


def test_le_compteur_repart_au_mois_suivant(relais, monkeypatch):
    relais.enregistrer_jetons("mensuel@exemple.com", 900)
    monkeypatch.setattr(relais, "_mois", lambda: "2099-12")
    relais.enregistrer_jetons("mensuel@exemple.com", 5)
    compteurs = relais._lire("quotas.json")
    assert compteurs["mensuel@exemple.com|jetons"] == 5, "un nouveau mois efface l'ancien compte"


def test_letat_de_sante_dit_ce_qui_protege(client, relais):
    """Miguel doit pouvoir vérifier d'un coup d'oeil que le rempart est bien en place."""
    corps = client.get("/sante").json()
    assert corps["plafond_global"] == relais.PLAFOND_GLOBAL
    assert "consomme" in corps
