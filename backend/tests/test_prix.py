"""Comparer les prix (interface H, chantier du 2026-09-13).

Tout est synthétique : faux résultats de recherche web (aucun réseau), fausse vision d'accessibilité.

Ce qui est protégé ici :
- un prix n'est gardé que s'il est vraisemblablement payé maintenant, en dollars canadiens : pas un
  rabais, un prix barré, des frais de livraison, un prix au kilo, un prix en dollars américains ;
- une offre par marchand, triée, les montants aberrants écartés ; un résultat hors sujet n'est pas une offre ;
- le produit n'est jamais deviné : un champ incertain reste vide, un produit non identifié est refusé ;
- rien ne part sans « Texte de vos demandes » ; mode local, mode confidentiel et recherche non configurée
  refusent AVANT toute photo ; l'avertissement est toujours là, et aucun nom de fournisseur n'apparaît.
"""
from __future__ import annotations

import json

import pytest

import iris.prix as prix
from iris import recherche_web

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "openrouter", "tavily", "brave")

RESULTATS_OSTER = [
    {"titre": "Réponse directe", "url": "", "extrait": "Le grille-pain Oster coûte environ 35 $."},
    {"titre": "Grille-pain Oster 2 tranches | Walmart Canada", "url": "https://www.walmart.ca/fr/ip/oster-2/123",
     "extrait": "Grille-pain Oster 2 tranches, fentes larges. 39,97 $ Livraison gratuite dès 35 $."},
    {"titre": "Oster 2-Slice Toaster - Best Buy", "url": "https://www.bestbuy.ca/en-ca/product/oster/456",
     "extrait": "Oster 2-Slice Toaster. Was $59.99 Save $10.00 Sale $49.99"},
    {"titre": "Grille-pain Oster - Canadian Tire", "url": "https://www.canadiantire.ca/fr/pdp/oster-789.html",
     "extrait": "Grille-pain à 2 tranches Oster, acier inoxydable. Prix régulier 54,99 $ Prix spécial 44,99 $"},
    {"titre": "Oster Toaster - Amazon.com", "url": "https://www.amazon.com/dp/B000",
     "extrait": "Oster 2-Slice Toaster $29.99 free shipping on orders over $35"},
    {"titre": "Pièce de rechange Oster ramasse-miettes", "url": "https://www.canadiantire.ca/fr/pdp/oster-tiroir.html",
     "extrait": "Tiroir ramasse-miettes pour grille-pain Oster : 4,99 $"},
    {"titre": "Bouilloire électrique Hamilton Beach", "url": "https://www.walmart.ca/fr/ip/bouilloire/999",
     "extrait": "Bouilloire 1,7 L : 24,97 $"},
    {"titre": "Grille-pain Oster - Walmart Canada (autre vendeur)", "url": "https://www.walmart.ca/fr/ip/oster-2/555",
     "extrait": "Grille-pain Oster 2 tranches vendu par un tiers : 42,50 $"},
]


@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-prix")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    application.state.ctx.settings.update({"voice_autostart": False})
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, _c = _application
    ctx = application.state.ctx
    vraie_fabrique = ctx.prix.fabrique_recherche
    yield application
    ctx.settings.update({"local_only": False, "privacy_mode": False})
    for type_donnee in ("transcript", "audio_raw", "image", "screen", "memory"):
        ctx.consent.set(type_donnee, False)
    ctx.prix.fabrique_recherche = vraie_fabrique


@pytest.fixture()
def client(app, _application):
    return _application[1]


class FausseRecherche:
    def __init__(self, pages: list[list[dict]], actif: bool = True, erreur: Exception | None = None):
        self.pages = list(pages)
        self.actif = actif
        self.erreur = erreur
        self.requetes: list[str] = []

    def fournisseur_actif(self):
        return ("tavily", "cle-de-test") if self.actif else None

    def rechercher(self, query, max_chars=4000, max_results=6):
        self.requetes.append(query)
        if self.erreur is not None:
            raise self.erreur
        resultats = self.pages.pop(0) if self.pages else []
        return recherche_web.ResultatRecherche(query=query, url="", text="", fournisseur="tavily", resultats=resultats)


class FausseVision:
    def __init__(self, texte: str):
        self.texte = texte
        self.appels: list[dict] = []

    async def decrire(self, mode, source="lunettes", image=None, question=None, parler=True, memoriser=True):
        self.appels.append({"mode": mode, "source": source, "image": image, "question": question,
                            "parler": parler, "memoriser": memoriser})
        return {"ok": True, "mode": mode, "source": source, "texte": self.texte, "chemin": None, "duree_ms": 8,
                "local": False}


def brancher_recherche(app, *pages, **options) -> FausseRecherche:
    faux = FausseRecherche(list(pages), **options)
    app.state.ctx.prix.fabrique_recherche = lambda: faux
    return faux


def accorder(client, *types):
    for t in types:
        assert client.put(f"/api/consent/{t}", json={"granted": True}).status_code == 200


def sans_fournisseur(reponse: dict) -> bool:
    texte = json.dumps(reponse, ensure_ascii=False).lower()
    return not any(nom in texte for nom in NOMS_INTERDITS)


# --------------------------------------------------------------------------- lecture des prix
@pytest.mark.parametrize("texte, url, attendu", [
    ("Grille-pain Oster – 39,99 $ en magasin", "https://www.walmart.ca/x", [39.99]),
    ("Prix régulier 59,99 $ Prix spécial 44,99 $", "https://www.bestbuy.ca/fr-ca/x", [44.99]),
    ("Was $59.99 Save $10.00 Sale $49.99", "https://www.bestbuy.ca/en-ca/x", [49.99]),
    ("CA$ 1,299.99 portable", "https://exemple.com/x", [1299.99]),
    ("1 299,99 $ ordinateur", "https://www.bureauengros.com/x", [1299.99]),
    ("0,45 $/100 g pain tranché 3,49 $", "https://www.iga.net/x", [3.49]),
    ("Livraison 5,99 $ — prix 24,99 $", "https://www.canadiantire.ca/x", [24.99]),
    ("US$24.99 importé", "https://boutique.ca/x", []),
    ("$29.99 free shipping", "https://www.amazon.com/x", []),
    ("Forfait 45 $/mois", "https://www.fizz.ca/x", []),
    ("15 $ de rabais sur 99,99 $", "https://www.sail.ca/x", [99.99]),
    ("12,99 $ CAD", "https://example.org/x", [12.99]),
    ("IKEA lampe 19,99 $", "https://www.ikea.com/fr/fr/p/x", []),
    ("IKEA lampe 19,99 $", "https://www.ikea.com/ca/fr/p/x", [19.99]),
])
def test_seuls_les_prix_payes_maintenant_en_dollars_canadiens_sont_lus(texte, url, attendu):
    assert [p[0] for p in prix.prix_dans(texte, url)] == attendu


def test_le_produit_nest_jamais_devine():
    p = prix.lire_produit("NOM : Grille-pain 2 tranches\nMARQUE : Oster\nFORMAT : inconnu\n"
                          "CODE-BARRES : 0 34264 45612 3\nPRIX AFFICHÉ : 49,99 $")
    assert p == {"nom": "Grille-pain 2 tranches", "marque": "Oster", "format": None, "code_barres": "034264456123",
                 "prix_vu": 49.99}
    p = prix.lire_produit("NOM : Café moulu, MARQUE : Van Houtte, FORMAT : 340 g, CODE-BARRES : 1234, PRIX AFFICHÉ : non visible")
    assert p["nom"] == "Café moulu" and p["format"] == "340 g"
    assert p["code_barres"] is None, "un code-barres incomplet n'est pas un code-barres"
    assert p["prix_vu"] is None
    assert prix.lire_produit("Je ne suis pas sûre de ce que c'est, l'image est floue.")["nom"] is None


def test_offres_pertinentes_dedupliquees_triees_et_aberrations_ecartees():
    produit = {"nom": "Grille-pain 2 tranches", "marque": "Oster", "format": None, "code_barres": None, "prix_vu": None}
    offres = prix.extraire_offres(RESULTATS_OSTER, produit)
    marchands = [o["marchand"] for o in offres]
    assert "Réponse directe" not in [o["titre"] for o in offres], "une réponse sans source n'est jamais une offre"
    assert all("amazon.com" not in o["url"] for o in offres), "un $ nu hors Canada n'est pas un prix canadien"
    assert all("bouilloire" not in o["url"] for o in offres), "un résultat hors sujet n'est pas une offre"
    assert marchands.count("Walmart") == 2 and marchands.count("Best Buy") == 1, \
        "une fiche en anglais qui nomme la marque reste pertinente"
    assert 4.99 in [o["prix"] for o in offres], "le tiroir ramasse-miettes parle bien d'Oster"
    gardees, ecartees = prix.trier_offres(offres)
    assert [(o["marchand"], o["prix"]) for o in gardees] == [("Walmart", 39.97), ("Canadian Tire", 44.99),
                                                             ("Best Buy", 49.99)], \
        "l'accessoire à 4,99 $ ne remplace pas le grille-pain du même marchand"
    assert ecartees == 2, "l'accessoire est écarté et la seconde offre Walmart (plus chère) dédoublonnée"
    deux = [o for o in offres if o["prix"] in (39.97, 4.99)]
    assert [o["prix"] for o in prix.trier_offres(deux)[0]] == [4.99, 39.97], "à deux offres, rien n'est deviné"
    assert [o["prix"] for o in prix.trier_offres(deux, prix_vu=42.0)[0]] == [39.97], "le prix vu sert de référence"
    assert all(o["devise"] == "CAD" and o["extrait"] for o in gardees)


def test_resume_vocal_court_et_honnete():
    produit = {"nom": "Grille-pain", "marque": "Oster", "format": None, "code_barres": None, "prix_vu": 49.99}
    offres = [{"marchand": "Walmart", "prix": 39.97}, {"marchand": "Best Buy", "prix": 50.0}]
    assert prix.resume_vocal(produit, offres) == (
        "Oster Grille-pain : 2 prix trouvés en ligne. Le plus bas : 39,97 $ chez Walmart ; le plus haut : 50 $ chez "
        "Best Buy. Prix vu sur place : 49,99 $. Prix en ligne à vérifier : le magasin peut différer.")
    assert prix.resume_vocal({"nom": "Truc rare"}, []) == "Je n'ai trouvé aucun prix en ligne au Canada pour Truc rare."


@pytest.mark.parametrize("phrase, attendu", [
    ("compare les prix", ""), ("c'est combien ailleurs", ""), ("compare le prix de ça", ""),
    ("compare les prix de la cafetière Bodum", "cafetière Bodum"),
    ("trouve le meilleur prix pour des écouteurs Sony", "écouteurs Sony"),
    ("quelle heure est-il", None), ("le prix de l'essence a monté", None),
])
def test_demande_vocale(phrase, attendu):
    assert prix.demande_vocale(phrase) == attendu


# --------------------------------------------------------------------------- route : requête texte
def test_comparer_par_nom(client, app):
    accorder(client, "transcript")
    faux = brancher_recherche(app, RESULTATS_OSTER)
    r = client.post("/api/achats/comparer", json={"source": "image", "requete": "grille-pain Oster 2 tranches"})
    assert r.status_code == 200
    donnees = r.json()
    assert donnees["local"] is False and donnees["source"] == "texte"
    assert donnees["produit"] == {"nom": "grille-pain Oster 2 tranches", "marque": None, "format": None,
                                  "code_barres": None, "prix_vu": None}
    assert [o["prix"] for o in donnees["offres"]] == [39.97, 44.99, 49.99]
    assert set(donnees["offres"][0]) >= {"marchand", "prix", "devise", "url", "extrait"}
    assert donnees["avertissement"] == prix.AVERTISSEMENT and "stock en magasin" in donnees["avertissement"]
    assert donnees["resume"].startswith("grille-pain Oster 2 tranches : 3 prix trouvés en ligne. Le plus bas : 39,97 $")
    assert faux.requetes == ["grille-pain Oster 2 tranches prix Canada"]
    envoi = [e for e in app.state.ctx.consent.events(30) if e["event_type"] == "external_send"]
    assert envoi and envoi[0]["data_type"] == "transcript" and envoi[0]["agent"] == "recherche_web"
    assert sans_fournisseur(donnees)


def test_refus_avant_tout_envoi(client, app, monkeypatch):
    vision = FausseVision("NOM : Grille-pain")
    monkeypatch.setattr(app.state.ctx, "accessibilite", vision)
    faux = brancher_recherche(app, RESULTATS_OSTER)
    r = client.post("/api/achats/comparer", json={"requete": "grille-pain"})
    assert r.status_code == 403 and r.json()["detail"]["data_type"] == "transcript"
    r = client.post("/api/achats/comparer", json={"source": "lunettes"})
    assert r.status_code == 403
    assert faux.requetes == [] and vision.appels == [], "ni recherche, ni photo sans accord"

    accorder(client, "transcript")
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/achats/comparer", json={"source": "lunettes"})
    assert r.status_code == 409 and "100 % local" in r.json()["detail"]
    app.state.ctx.settings.update({"local_only": False, "privacy_mode": True})
    r = client.post("/api/achats/comparer", json={"source": "lunettes"})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    app.state.ctx.settings.update({"privacy_mode": False})
    brancher_recherche(app, RESULTATS_OSTER, actif=False)
    r = client.post("/api/achats/comparer", json={"source": "lunettes"})
    assert r.status_code == 409 and "pas configurée" in r.json()["detail"]
    assert vision.appels == [], "aucune photo prise pour rien"
    assert client.post("/api/achats/comparer", json={"source": "image"}).status_code == 409  # non configurée d'abord
    brancher_recherche(app, RESULTATS_OSTER)
    assert client.post("/api/achats/comparer", json={"source": "image"}).status_code == 422
    assert client.post("/api/achats/comparer", json={"source": "radio"}).status_code == 422


@pytest.mark.parametrize("erreur, statut, mot", [
    (recherche_web.RechercheReseau("Tavily injoignable (ConnectError)."), 502, "connexion"),
    (recherche_web.RechercheRefusee("Brave a refusé la clé d'API (HTTP 401)."), 502, "refusé"),
    (recherche_web.RechercheNonConfiguree("Aucune clé TAVILY_API_KEY"), 409, "pas configurée"),
])
def test_erreurs_de_recherche_sans_nom_de_fournisseur(client, app, erreur, statut, mot):
    accorder(client, "transcript")
    brancher_recherche(app, erreur=erreur)
    r = client.post("/api/achats/comparer", json={"requete": "grille-pain"})
    assert r.status_code == statut and mot in r.json()["detail"]
    assert sans_fournisseur(r.json())


def test_aucun_prix_trouve_est_dit_tel_quel(client, app):
    accorder(client, "transcript")
    brancher_recherche(app, [RESULTATS_OSTER[6]])
    donnees = client.post("/api/achats/comparer", json={"requete": "grille-pain Oster"}).json()
    assert donnees["offres"] == [] and donnees["resume"] == "Je n'ai trouvé aucun prix en ligne au Canada pour grille-pain Oster."
    assert donnees["avertissement"]


# --------------------------------------------------------------------------- route : photo
def test_comparer_par_photo_des_lunettes(client, app, monkeypatch):
    accorder(client, "transcript")
    vision = FausseVision("NOM : Grille-pain 2 tranches\nMARQUE : Oster\nFORMAT : inconnu\n"
                          "CODE-BARRES : 034264456123\nPRIX AFFICHÉ : 49,99 $")
    monkeypatch.setattr(app.state.ctx, "accessibilite", vision)
    faux = brancher_recherche(app, [RESULTATS_OSTER[1]], RESULTATS_OSTER[2:4])
    donnees = client.post("/api/achats/comparer", json={"source": "lunettes"}).json()
    appel = vision.appels[0]
    assert appel["mode"] == "objet" and appel["source"] == "lunettes" and appel["image"] is None
    assert appel["parler"] is False and appel["memoriser"] is False and "CODE-BARRES" in appel["question"]
    assert donnees["source"] == "lunettes" and donnees["produit"]["code_barres"] == "034264456123"
    assert faux.requetes == ["Oster Grille-pain 2 tranches prix Canada", "034264456123 prix"], \
        "une première recherche maigre est complétée par le code-barres"
    assert [o["prix"] for o in donnees["offres"]] == [39.97, 44.99, 49.99]
    assert "Prix vu sur place : 49,99 $." in donnees["resume"] and donnees["recherches"] == 2


def test_photo_du_telephone_et_produit_non_identifie(client, app, monkeypatch):
    accorder(client, "transcript")
    vision = FausseVision("Je ne suis pas sûre : l'image est floue.")
    monkeypatch.setattr(app.state.ctx, "accessibilite", vision)
    faux = brancher_recherche(app, RESULTATS_OSTER)
    image = {"media_type": "image/jpeg", "data": "QUJD"}
    r = client.post("/api/achats/comparer", json={"source": "image", "image": image})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "non_identifie"
    assert vision.appels[0]["source"] == "image" and vision.appels[0]["image"] == image
    assert faux.requetes == [], "rien n'est cherché pour un produit inconnu"


def test_sans_vision_on_propose_de_taper_le_nom(client, app, monkeypatch):
    accorder(client, "transcript")
    monkeypatch.setattr(app.state.ctx, "accessibilite", None)
    brancher_recherche(app, RESULTATS_OSTER)
    r = client.post("/api/achats/comparer", json={"source": "lunettes"})
    assert r.status_code == 409 and "tapez le nom" in r.json()["detail"]


def test_voix_compare_les_prix(client, app):
    accorder(client, "transcript")
    brancher_recherche(app, RESULTATS_OSTER)
    phrase = app.state.ctx.voice._intercepter("compare les prix du grille-pain Oster")
    assert phrase.startswith("grille-pain Oster : 3 prix trouvés en ligne.") and phrase.endswith("peut différer.")
    brancher_recherche(app, RESULTATS_OSTER, actif=False)
    assert app.state.ctx.voice._intercepter("compare les prix") == "La recherche web n'est pas configurée sur cet ordinateur."
