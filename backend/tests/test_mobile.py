"""Accès mobile : la page téléphone, et surtout le fait qu'elle reste protégée.

IRIS exécute des commandes sur l'ordinateur. Ouvrir son interface au réseau est une décision qui
doit rester explicite, et le jeton doit être exigé partout, sans exception.
"""
from __future__ import annotations

from iris.mobile import PAGE, urls_locales


# --------------------------------------------------------------------------- sécurité
def test_la_page_mobile_repond_avec_le_jeton(client):
    r = client.get("/m")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "IRIS" in r.text


def test_acces_reseau_desactive_par_defaut(client):
    """Par défaut, IRIS n'est joignable que depuis cet ordinateur."""
    r = client.get("/api/remote").json()
    assert r["enabled"] is False
    assert r["urls"] == [], "aucune adresse ne doit être publiée tant que l'accès est fermé"


def test_les_adresses_apparaissent_une_fois_autorise(client):
    client.patch("/api/settings", json={"remote_access": True})
    r = client.get("/api/remote").json()
    assert r["enabled"] is True
    for u in r["urls"]:
        assert u["url"].startswith("http://") and "/m?token=" in u["url"]
        assert not u["ip"].startswith("127."), "l'adresse locale ne sert à rien depuis le téléphone"


def test_la_consigne_deconseille_ouvrir_un_port(client):
    """Rediriger un port du routeur vers IRIS reviendrait à laisser la porte ouverte sur Internet."""
    note = client.get("/api/remote").json()["note"]
    assert "tunnel" in note.lower() and "port" in note.lower()


# --------------------------------------------------------------------------- la page elle-même
def test_la_page_est_autonome():
    """Elle doit fonctionner dans une voiture, sur un réseau incertain : aucune ressource externe."""
    for interdit in ("http://", "https://", "cdn", "@import"):
        assert interdit not in PAGE, f"ressource externe détectée : {interdit}"


def test_la_page_contient_lessentiel():
    for attendu in ("SpeechRecognition", "speechSynthesis", "fr-CA", "Appuyez pour parler", "viewport"):
        assert attendu in PAGE, f"manque : {attendu}"


def test_la_page_gere_labsence_de_reconnaissance_vocale():
    """Sur un navigateur sans reconnaissance vocale, il doit rester possible d'écrire."""
    assert "Voix indisponible" in PAGE and "ou écrivez ici" in PAGE


def test_urls_locales_ecarte_le_bouclage():
    for u in urls_locales(8123, "jeton"):
        assert not u["ip"].startswith("127.")
        assert u["url"] == f"http://{u['ip']}:8123/m?token=jeton"


# --------------------------------------------------------------------------- adresse stable
def test_le_port_reste_le_meme(tmp_path):
    """Sans port fixe, l'adresse mise en favori sur le téléphone serait morte au redémarrage."""
    from iris.__main__ import PORT_MOBILE, port_stable

    a = port_stable("127.0.0.1")
    b = port_stable("127.0.0.1")
    assert a == b == PORT_MOBILE or (a == b and a > PORT_MOBILE)


def test_le_jeton_survit_au_redemarrage(tmp_path):
    """Même raison : un jeton régénéré à chaque lancement casserait le favori."""
    from iris.__main__ import jeton_persistant

    premier = jeton_persistant(tmp_path)
    assert len(premier) >= 20
    assert jeton_persistant(tmp_path) == premier

    (tmp_path / "remote-token").unlink()  # supprimer le fichier révoque les appareils
    assert jeton_persistant(tmp_path) != premier


def test_les_reglages_bruts_ne_plantent_jamais(tmp_path):
    from iris.__main__ import reglages_bruts

    assert reglages_bruts(None) == {}
    assert reglages_bruts(tmp_path) == {}
    (tmp_path / "settings.json").write_text('{"remote_access": true}', encoding="utf-8")
    assert reglages_bruts(tmp_path)["remote_access"] is True
    (tmp_path / "settings.json").write_text("pas du json", encoding="utf-8")
    assert reglages_bruts(tmp_path) == {}


# --------------------------------------------------------------------------- connexion par mot de passe
def test_la_page_est_publique_mais_lapi_ne_lest_pas(client_sans_jeton):
    """La page n'est qu'un formulaire : elle peut se charger. Les données, non."""
    assert client_sans_jeton.get("/m").status_code == 200
    assert client_sans_jeton.get("/api/status").status_code == 401
    assert client_sans_jeton.get("/api/memory").status_code == 401


def test_letat_du_compte_est_consultable_sans_jeton(client_sans_jeton):
    """Le téléphone doit savoir s'il faut se connecter, avant d'avoir quoi que ce soit."""
    r = client_sans_jeton.get("/api/compte").json()
    assert r["configure"] is False


def test_connexion_puis_acces_complet(client, client_sans_jeton):
    client.post("/api/compte", json={"nouveau": "motdepasse-solide", "nom": "Miguel"})

    refus = client_sans_jeton.post("/api/compte/connexion", json={"mot_de_passe": "mauvais"})
    assert refus.status_code == 401

    ok = client_sans_jeton.post("/api/compte/connexion", json={"mot_de_passe": "motdepasse-solide"})
    assert ok.status_code == 200
    session = ok.json()["session"]

    entetes = {"Authorization": f"Bearer {session}"}
    assert client_sans_jeton.get("/api/status", headers=entetes).status_code == 200
    assert client_sans_jeton.get("/api/memory", headers=entetes).status_code == 200


def test_la_deconnexion_coupe_les_appareils(client, client_sans_jeton):
    client.post("/api/compte", json={"nouveau": "motdepasse-solide"})
    session = client_sans_jeton.post("/api/compte/connexion", json={"mot_de_passe": "motdepasse-solide"}).json()["session"]
    entetes = {"Authorization": f"Bearer {session}"}
    assert client_sans_jeton.get("/api/status", headers=entetes).status_code == 200

    client.post("/api/compte/deconnexion")
    assert client_sans_jeton.get("/api/status", headers=entetes).status_code == 401


def test_un_mot_de_passe_faible_est_refuse(client):
    r = client.post("/api/compte", json={"nouveau": "court"})
    assert r.status_code == 400


def test_la_page_contient_lecran_de_connexion():
    for attendu in ("verrou", "mot de passe", "/api/compte/connexion", "iris_session"):
        assert attendu in PAGE, f"manque : {attendu}"


# --------------------------------------------------------------------------- installable sur le téléphone
def test_le_manifeste_permet_linstallation(client_sans_jeton):
    """Sans manifeste conforme, Android ne propose qu'un raccourci, pas une application."""
    r = client_sans_jeton.get("/manifest.webmanifest")
    assert r.status_code == 200
    m = r.json()
    assert m["display"] == "standalone", "sinon la barre du navigateur reste visible"
    assert m["start_url"] == "/m"
    tailles = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= tailles, "Android exige ces deux tailles"


def test_les_icones_sont_servies(client_sans_jeton):
    for taille in (192, 512):
        r = client_sans_jeton.get(f"/icone-{taille}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n", "ce n'est pas un vrai PNG"
    assert client_sans_jeton.get("/icone-999.png").status_code == 404


def test_lagent_de_service_ne_met_jamais_lapi_en_cache(client_sans_jeton):
    """Une réponse d'IRIS servie depuis un cache périmé serait pire que pas de réponse."""
    r = client_sans_jeton.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "/api/" in r.text and "return" in r.text, "l'API doit être explicitement écartée du cache"
    assert "addEventListener('fetch'" in r.text, "Android exige un gestionnaire fetch"


def test_la_page_declare_le_manifeste():
    assert 'rel="manifest"' in PAGE and "serviceWorker" in PAGE
