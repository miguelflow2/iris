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
    ids = [m["id"] for m in modeles["data"]]
    # Le client ne voit que des identifiants NEUTRES « vela-… », jamais le nom d'un fournisseur.
    assert ids and all(i.startswith("vela-") for i in ids), ids
    # Le modèle phare du forfait payant est bien exposé — sous son nom neutre, pas son vrai nom.
    assert relais.nom_neutre("anthropic/claude-sonnet-5") in ids


def test_v1_models_ne_montre_aucun_nom_de_fournisseur(client, relais):
    """Le client final ne doit lire aucun nom de fournisseur dans la liste de ses modèles :
    ni « anthropic », ni « openai », ni « google », ni le nom d'une famille de modèles."""
    abonne(relais, "ent@exemple.com", "entreprise")
    jeton = client.post("/api/appareil", json={"machine": "m", "email": "ent@exemple.com"}).json()["jeton"]
    corps = client.get("/v1/models", headers={"Authorization": "Bearer " + jeton}).text.lower()
    for marque in ("anthropic", "openai", "google", "openrouter", "claude", "gpt", "gemini",
                   "minimax", "nvidia", "nemotron", "gemma"):
        assert marque not in corps, "« {} » a fui dans /v1/models".format(marque)


def test_un_nom_neutre_se_retraduit_vers_le_vrai_modele(relais):
    """Si un client renvoie un nom neutre, le relais retrouve le vrai modèle, dans la limite du
    forfait : la façade cache le fournisseur sans empêcher le bon modèle de répondre."""
    assert relais.modele_autorise("vela-max", "entreprise") == "anthropic/claude-opus-5"
    assert relais.modele_autorise("vela-avance", "premium") == "anthropic/claude-sonnet-5"
    # Un plan gratuit qui renvoie le nom neutre d'un modèle payant reste au gratuit.
    assert relais.modele_autorise("vela-max", "gratuit").endswith(":free")


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
# Tous les forfaits promettent une voix ElevenLabs, Gratuit compris. Sans ce relais, l'abonné
# devrait fournir sa propre clé : il paierait une voix qu'il n'entendrait jamais.
@pytest.fixture()
def avec_voix(relais, monkeypatch):
    monkeypatch.setattr(relais, "CLES_VOIX", ["cle-voix-factice"])
    monkeypatch.setattr(relais, "CLE_VOIX", "cle-voix-factice")
    monkeypatch.setattr(relais, "_voix_cooldown", {})
    monkeypatch.setattr(relais, "_voix_i", 0)
    return relais


class _FluxAmont:
    """api.elevenlabs.io, en faux. Aucun test ne doit sortir sur le réseau ni dépenser un caractère."""

    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def aiter_bytes(self):
        yield b"\x00\x01\x02\x03"


class _ClientAmont:
    def __init__(self, **_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def stream(self, *_a, **_k):
        return _FluxAmont()


def test_la_voix_est_incluse_dans_tous_les_forfaits(client, avec_voix, monkeypatch):
    """Décision de Miguel, 5 septembre 2026 : la voix n'est plus un argument de vente entre paliers.

    Si ce test tombe, un utilisateur du plan Gratuit se voit refuser la voix qu'on lui promet à
    l'écran — et il n'a aucun moyen de savoir pourquoi."""
    monkeypatch.setattr(avec_voix.httpx, "AsyncClient", _ClientAmont)
    jeton = client.post("/api/appareil", json={"machine": "m", "email": ""}).json()["jeton"]
    r = client.post("/v1/voix/abcdef", json={"text": "bonjour"}, headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 200, "le plan Gratuit doit obtenir la voix comme les autres"
    compteurs = avec_voix._lire("quotas.json")
    assert compteurs["anonyme:m|caracteres"] == len("bonjour"), "les caractères servis doivent être comptés"


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


def test_la_voix_bascule_quand_une_cle_est_epuisee(client, relais, monkeypatch):
    """Deux comptes ElevenLabs : quand le premier répond « quota atteint » (429), le relais bascule
    sur le second sans que l'abonné entende un silence. C'est ce qui double la voix gratuite."""
    monkeypatch.setattr(relais, "CLES_VOIX", ["cleA", "cleB"])
    monkeypatch.setattr(relais, "_voix_cooldown", {})
    monkeypatch.setattr(relais, "_voix_i", 0)
    vues: list[str] = []
    reponses = {"cleA": 429, "cleB": 200}

    class _Flux:
        def __init__(self, code):
            self.status_code = code

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def aiter_bytes(self):
            yield b"\x00\x01"

    class _Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_a, **k):
            cle = k["headers"]["xi-api-key"]
            vues.append(cle)
            return _Flux(reponses[cle])

    monkeypatch.setattr(relais.httpx, "AsyncClient", _Client)
    jeton = client.post("/api/appareil", json={"machine": "m", "email": ""}).json()["jeton"]
    r = client.post("/v1/voix/abcdef", json={"text": "bonjour"}, headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 200
    assert r.content == b"\x00\x01", "les octets servis doivent venir de la 2e clé"
    assert vues == ["cleA", "cleB"], "le relais doit avoir tenté cleA (429) puis basculé sur cleB"


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
        # Le relais interroge en POST : un courriel dans une URL finirait dans tous les journaux
        # traverses. Le GET reste servi pour les serveurs plus anciens.
        def post(self, *_a, **_k): return FausseReponse()
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
        def post(self, *_a, **_k): raise OSError("réseau coupé")
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
    # La voix a sa propre monnaie : ElevenLabs facture au caractère, pas au jeton.
    assert corps["plafond_caracteres"] == relais.PLAFOND_CARACTERES_GLOBAL
    assert "caracteres" in corps


# --------------------------------------------------------------------------- l'argent de la voix
# Depuis que la voix est incluse dans tous les forfaits, plus rien ne borne la dépense côté
# abonnement. ElevenLabs facture au CARACTÈRE : un quota en nombre d'appels ne protège rien, « oui »
# et une tirade de mille caractères comptent chacune pour un.
def test_le_plafond_de_caracteres_arrete_un_abonne(relais):
    from fastapi import HTTPException

    relais.PLAFONDS_CARACTERES["gratuit"] = 100
    relais.consommer_voix("bavard@exemple.com", "gratuit", 120)
    with pytest.raises(HTTPException) as leve:
        relais.consommer_voix("bavard@exemple.com", "gratuit", 10)
    assert leve.value.status_code == 429
    assert "aractères" in leve.value.detail, "le refus doit nommer la vraie unité facturée"
    assert "Windows" in leve.value.detail, "un refus qui ne dit pas ce qui reste ressemble à une panne"


def test_le_plafond_global_de_voix_coupe_tout_le_monde(relais):
    """Le dernier rempart : celui qui empêche la facture ElevenLabs de monter pendant une nuit."""
    from fastapi import HTTPException

    relais.PLAFOND_CARACTERES_GLOBAL = 500
    relais.consommer_voix("quelquun@exemple.com", "entreprise", 600)
    with pytest.raises(HTTPException) as leve:
        relais.consommer_voix("quelquun.dautre@exemple.com", "entreprise", 10)
    assert leve.value.status_code == 503
    assert "Windows" in leve.value.detail


def test_les_deux_refus_de_voix_ne_disent_pas_la_meme_chose(relais):
    """« Vous avez beaucoup parlé ce mois-ci » et « le service entier est à sec » ne se corrigent
    pas de la même façon : le premier attend le mois prochain, le second attend Miguel."""
    from fastapi import HTTPException

    relais.PLAFONDS_CARACTERES["gratuit"] = 10
    relais.PLAFOND_CARACTERES_GLOBAL = 10 ** 9
    relais.consommer_voix("un@exemple.com", "gratuit", 50)
    with pytest.raises(HTTPException) as abonne_bloque:
        relais.consommer_voix("un@exemple.com", "gratuit", 5)

    relais.PLAFONDS_CARACTERES["gratuit"] = 10 ** 9
    relais.PLAFOND_CARACTERES_GLOBAL = 10
    with pytest.raises(HTTPException) as service_a_sec:
        relais.consommer_voix("deux@exemple.com", "gratuit", 5)

    assert abonne_bloque.value.status_code != service_a_sec.value.status_code
    assert abonne_bloque.value.detail != service_a_sec.value.detail


def test_une_replique_interminable_est_refusee(client, avec_voix):
    """IRIS tronque déjà ses phrases à 1 500 caractères. Un texte de dix mille n'est plus une
    assistante qui parle, c'est quelqu'un qui se sert du relais comme d'un service de synthèse."""
    abonne(avec_voix, "pro@exemple.com", "pro")
    jeton = client.post("/api/appareil", json={"machine": "m", "email": "pro@exemple.com"}).json()["jeton"]
    r = client.post("/v1/voix/abcdef", json={"text": "a" * 10_000}, headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 413
    assert avec_voix._lire("quotas.json").get("pro@exemple.com|caracteres") is None, "un texte refusé ne se compte pas"


def test_le_compteur_de_caracteres_repart_au_mois_suivant(relais, monkeypatch):
    relais.consommer_voix("mensuel@exemple.com", "gratuit", 900)
    monkeypatch.setattr(relais, "_mois", lambda: "2099-12")
    relais.consommer_voix("mensuel@exemple.com", "gratuit", 5)
    compteurs = relais._lire("quotas.json")
    assert compteurs["mensuel@exemple.com|caracteres"] == 5, "un nouveau mois efface l'ancien compte"


def test_les_plafonds_de_voix_se_reglent_sans_toucher_au_code(monkeypatch, tmp_path):
    """Personne ne peut deviner la consommation avant d'avoir des clients : Miguel doit pouvoir
    resserrer ou desserrer le filet depuis son fichier .env, sans redéployer un fichier Python."""
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_CARACTERES_GRATUIT", "1234")
    monkeypatch.setenv("VELA_CARACTERES_TOTAL", "99999")
    monkeypatch.setenv("VELA_CARACTERES_PAR_REQUETE", "77")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as recharge

    assert recharge.PLAFONDS_CARACTERES["gratuit"] == 1234
    assert recharge.PLAFOND_CARACTERES_GLOBAL == 99999
    assert recharge.CARACTERES_MAX_PAR_REQUETE == 77


# --------------------------------------------------------------------------- l'economie : Claude aux payants
def test_tout_forfait_payant_mene_avec_claude(relais):
    """Decision de Miguel du 6 septembre 2026 : chaque abonnement finance son propre cerveau. Le
    defaut d'un forfait payant DOIT etre un modele Claude — c'est ce que le client paie."""
    for plan in ("pro", "premium", "entreprise"):
        defaut = relais.modele_autorise("", plan)
        assert defaut.startswith("anthropic/claude-"), f"{plan} ne mene pas avec Claude : {defaut}"


def test_le_gratuit_mene_avec_un_modele_gratuit(relais):
    defaut = relais.modele_autorise("", "gratuit")
    assert defaut.endswith(":free"), f"le gratuit doit couter 0 a VELA : {defaut}"


def test_le_gratuit_natteint_jamais_claude_meme_en_le_demandant(relais):
    """La cle qui paie est celle de VELA : un curieux ne doit pas pouvoir se servir de Claude gratuitement."""
    for demande in ("anthropic/claude-opus-5", "anthropic/claude-sonnet-5"):
        assert not relais.modele_autorise(demande, "gratuit").startswith("anthropic/")


# --------------------------------------------------------------------------- Claude en direct chez Anthropic
def test_un_modele_claude_part_chez_anthropic_quand_la_cle_est_la(relais, monkeypatch):
    """Décision du 6 septembre 2026 : en test, Claude tourne via la clé Anthropic rechargée, en
    direct, pas par OpenRouter. On retire le préfixe « anthropic/ » qu'Anthropic n'attend pas."""
    monkeypatch.setattr(relais, "CLE_ANTHROPIC", "sk-ant-factice")
    base, entetes, effectif = relais.amont_pour("anthropic/claude-opus-5")
    assert base == relais.AMONT_ANTHROPIC
    assert effectif == "claude-opus-5", "le préfixe anthropic/ doit être retiré"
    assert entetes["Authorization"] == "Bearer sk-ant-factice"


def test_sans_cle_anthropic_claude_repasse_par_openrouter(relais, monkeypatch):
    monkeypatch.setattr(relais, "CLE_ANTHROPIC", "")
    base, _e, effectif = relais.amont_pour("anthropic/claude-opus-5")
    assert base == relais.AMONT
    assert effectif == "anthropic/claude-opus-5", "OpenRouter attend le préfixe, lui"


def test_les_modeles_gratuits_ne_partent_jamais_chez_anthropic(relais, monkeypatch):
    monkeypatch.setattr(relais, "CLE_ANTHROPIC", "sk-ant-factice")
    base, _e, _m = relais.amont_pour("minimax/minimax-m3:free")
    assert base == relais.AMONT, "un modèle gratuit reste chez OpenRouter"


def test_une_cle_anthropic_suffit_a_faire_repondre_le_relais(relais, monkeypatch):
    """Le relais ne doit plus exiger la clé OpenRouter : la clé Anthropic seule suffit à servir."""
    monkeypatch.setattr(relais, "CLE_AMONT", "")
    monkeypatch.setattr(relais, "CLE_ANTHROPIC", "sk-ant-factice")
    from fastapi.testclient import TestClient
    c = TestClient(relais.app)
    r = c.post("/api/appareil", json={"email": "x@y.com", "machine": "m"})
    assert r.status_code == 200, "avec une clé Anthropic seule, l'enregistrement doit marcher"


# --------------------------------------------------------------------------- /sante teste vraiment
# Avant, /sante renvoyait « ok: true » en dur : un disque plein ou une clé absente passaient pour
# « tout va bien » pendant que chaque appel IA échouait. Un service surveillé par un point de santé
# qui ne teste rien est un service qu'on croit vivant.
def test_sante_est_vrai_quand_cle_et_disque_repondent(client, relais):
    corps = client.get("/sante").json()
    assert corps["ok"] is True
    assert "detail" not in corps, "aucun détail quand tout va bien"
    # Les champs historiques restent, le format ne change pas.
    for champ in ("amont", "voix", "plafond_global", "consomme", "plafond_caracteres", "caracteres"):
        assert champ in corps


def test_sante_est_faux_sans_aucune_cle_ia(client, relais, monkeypatch):
    monkeypatch.setattr(relais, "CLE_AMONT", "")
    monkeypatch.setattr(relais, "CLE_ANTHROPIC", "")
    corps = client.get("/sante").json()
    assert corps["ok"] is False
    assert "detail" in corps and "cle" in corps["detail"].lower()


def test_sante_est_faux_si_le_disque_nest_pas_accessible(client, relais, tmp_path, monkeypatch):
    """Le vrai test qui manquait : un disque non inscriptible doit faire échouer /sante, pas mentir."""
    bloqueur = tmp_path / "fichier"
    bloqueur.write_text("x")  # un FICHIER là où /sante voudra un dossier : mkdir échouera
    monkeypatch.setattr(relais, "DONNEES", bloqueur / "sous")
    corps = client.get("/sante").json()
    assert corps["ok"] is False
    assert "detail" in corps and "disque" in corps["detail"].lower()


def test_sante_ne_divulgue_pas_la_cle_meme_en_echec(client, relais, monkeypatch, tmp_path):
    bloqueur = tmp_path / "f"
    bloqueur.write_text("x")
    monkeypatch.setattr(relais, "DONNEES", bloqueur / "sous")
    r = client.get("/sante")
    assert relais.CLE_AMONT not in r.text


def test_la_sonde_disque_isole_la_panne(relais, tmp_path, monkeypatch):
    """_test_disque renvoie (True, '') quand ça marche, (False, détail) quand ça ne marche pas."""
    monkeypatch.setattr(relais, "DONNEES", tmp_path)
    ok, detail = relais._test_disque()
    assert ok is True and detail == ""
    bloqueur = tmp_path / "f"
    bloqueur.write_text("x")
    monkeypatch.setattr(relais, "DONNEES", bloqueur / "sous")
    ok, detail = relais._test_disque()
    assert ok is False and detail


# --------------------------------------------------------------------------- l'amont qui déraille
# Une réponse non-JSON (HTML d'un 502, maintenance), un amont injoignable : rien de tout cela ne
# doit se transformer en 500 illisible côté IRIS ni faire sauter la comptabilisation des jetons.
def test_une_reponse_amont_non_json_ne_leve_jamais(relais):
    class R:
        status_code = 502
        text = "<html>Bad Gateway</html>"

        def json(self):
            raise ValueError("ce n'est pas du JSON")

    rendu = relais._json_amont(R())
    assert isinstance(rendu, dict) and "error" in rendu
    assert relais.jetons_de(rendu) == 0, "une erreur ne coûte aucun jeton, mais le compte ne saute pas"


def _faux_async_client(reponses):
    """Un httpx.AsyncClient factice pour le chemin non-flux : chaque .post() rend (ou lève) l'élément
    suivant de `reponses`. Aucun test ne doit sortir sur le réseau."""
    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **_k):
            item = reponses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    return C


def _jeton_anonyme(client):
    return client.post("/api/appareil", json={"machine": "m", "email": ""}).json()["jeton"]


def test_un_amont_non_json_devient_une_erreur_propre_pas_un_500(client, relais, monkeypatch):
    class Rep:
        status_code = 502
        text = "<html>502</html>"

        def json(self):
            raise ValueError("non-json")

    monkeypatch.setattr(relais.httpx, "AsyncClient", _faux_async_client([Rep()]))
    jeton = _jeton_anonyme(client)
    r = client.post("/v1/chat/completions",
                    json={"model": "x", "messages": [{"role": "user", "content": "salut"}], "stream": False},
                    headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 502, "le code amont est préservé, pas transformé en 500"
    assert "error" in r.json(), "un corps JSON propre malgré l'amont non-JSON"
    assert relais.CLE_AMONT not in r.text


def test_un_amont_injoignable_rend_502_pas_500(client, relais, monkeypatch):
    erreur = relais.httpx.ConnectError("connexion refusée")
    monkeypatch.setattr(relais.httpx, "AsyncClient", _faux_async_client([erreur]))
    jeton = _jeton_anonyme(client)
    r = client.post("/v1/chat/completions",
                    json={"model": "x", "messages": [{"role": "user", "content": "salut"}], "stream": False},
                    headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 502


def test_le_flux_amont_a_un_timeout_de_lecture_borne(relais):
    """Avant : timeout=None, donc un fournisseur muet figeait le flux à l'infini. Désormais borné."""
    t = relais._timeout_flux()
    assert t.read is not None and t.read > 0, "le flux amont ne doit plus pouvoir pendre à l'infini"
    assert t.connect is not None


def test_le_timeout_de_flux_se_regle_par_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "k")
    monkeypatch.setenv("VELA_TIMEOUT_FLUX_S", "42")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as recharge

    assert recharge.TIMEOUT_LECTURE_FLUX == 42
    assert recharge._timeout_flux().read == 42


# --------------------------------------------------------------------------- rotation des clés amont
# Une seule clé OpenRouter et une seule Anthropic ne laissaient aucune marge : un 429 ou une clé
# révoquée coupait tout le monde. On accepte maintenant PLUSIEURS clés (comme le pool ElevenLabs)
# et l'on bascule dès qu'une répond 401/402/429. Une seule clé : comportement d'avant.
def test_plusieurs_cles_openrouter_forment_un_pool(monkeypatch, tmp_path):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "k1, k2 ,k3")
    monkeypatch.setenv("VELA_ANTHROPIC_KEY", "a1 a2")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as recharge

    assert recharge.CLES_AMONT == ["k1", "k2", "k3"]
    assert recharge.CLE_AMONT == "k1", "la première reste la clé scalaire de compatibilité"
    assert recharge.CLES_ANTHROPIC == ["a1", "a2"]
    assert recharge.CLE_ANTHROPIC == "a1"


def test_une_seule_cle_reste_le_comportement_davant(relais):
    assert relais.CLES_AMONT == ["sk-or-factice"]
    assert relais.CLE_AMONT == "sk-or-factice"


def test_une_cle_penalisee_passe_en_dernier_puis_revient(relais):
    cooldown: dict = {}
    cles = ["k1", "k2"]
    assert relais._cles_a_essayer(cles, cooldown) == ["k1", "k2"]
    relais._amont_marquer_epuisee("k1", cooldown)
    assert relais._cles_a_essayer(cles, cooldown) == ["k2", "k1"], "la pénalisée passe en dernier recours"


def test_le_relais_bascule_de_cle_amont_sur_un_429(client, relais, monkeypatch):
    """Deux clés OpenRouter : la première répond 429, le relais bascule sur la seconde, sans échec."""
    monkeypatch.setattr(relais, "CLES_AMONT", ["kA", "kB"])
    monkeypatch.setattr(relais, "CLE_AMONT", "kA")
    monkeypatch.setattr(relais, "_amont_cooldown", {})
    vues: list = []
    codes = {"kA": 429, "kB": 200}

    class Rep:
        def __init__(self, code):
            self.status_code = code
            self.text = ""

        def json(self):
            return {"usage": {"total_tokens": 7}} if self.status_code == 200 else {"error": "quota"}

    class Cli:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **k):
            cle = k["headers"]["Authorization"].split()[-1]
            vues.append(cle)
            return Rep(codes[cle])

    monkeypatch.setattr(relais.httpx, "AsyncClient", Cli)
    jeton = _jeton_anonyme(client)
    r = client.post("/v1/chat/completions",
                    json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": False},
                    headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 200
    assert vues == ["kA", "kB"], "kA (429) puis bascule sur kB"


def test_le_flux_amont_bascule_de_cle_sur_un_429(client, relais, monkeypatch):
    monkeypatch.setattr(relais, "CLES_AMONT", ["kA", "kB"])
    monkeypatch.setattr(relais, "CLE_AMONT", "kA")
    monkeypatch.setattr(relais, "_amont_cooldown", {})
    vues: list = []
    codes = {"kA": 429, "kB": 200}

    class Flux:
        def __init__(self, code):
            self.status_code = code

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def aread(self):
            return b"refuse"

        async def aiter_bytes(self):
            yield b'data: {"usage":{"total_tokens":3}}\n\n'

    class Cli:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_a, **k):
            cle = k["headers"]["Authorization"].split()[-1]
            vues.append(cle)
            return Flux(codes[cle])

    monkeypatch.setattr(relais.httpx, "AsyncClient", Cli)
    jeton = _jeton_anonyme(client)
    r = client.post("/v1/chat/completions",
                    json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True},
                    headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 200
    assert vues == ["kA", "kB"], "kA (429) puis bascule sur kB, sans silence"
    assert b"total_tokens" in r.content


def test_une_seule_cle_ne_boucle_pas_sur_un_429(client, relais, monkeypatch):
    """Rétrocompatible : une seule clé fait UN appel, le 429 est rendu tel quel — pas de boucle."""
    monkeypatch.setattr(relais, "CLES_AMONT", ["seule"])
    monkeypatch.setattr(relais, "CLE_AMONT", "seule")
    monkeypatch.setattr(relais, "_amont_cooldown", {})
    appels: list = []

    class Rep:
        status_code = 429
        text = ""

        def json(self):
            return {"error": "quota"}

    class Cli:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **_k):
            appels.append(1)
            return Rep()

    monkeypatch.setattr(relais.httpx, "AsyncClient", Cli)
    jeton = _jeton_anonyme(client)
    r = client.post("/v1/chat/completions",
                    json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": False},
                    headers={"Authorization": "Bearer " + jeton})
    assert r.status_code == 429
    assert len(appels) == 1, "une seule clé : un seul appel amont"
