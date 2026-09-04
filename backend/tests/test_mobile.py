"""Accès mobile : la page téléphone, et surtout le fait qu'elle reste protégée.

IRIS exécute des commandes sur l'ordinateur. Ouvrir son interface au réseau est une décision qui
doit rester explicite, et le jeton doit être exigé partout, sans exception.
"""
from __future__ import annotations

from iris.mobile import PAGE, urls_locales


# --------------------------------------------------------------------------- sécurité
def test_la_page_mobile_exige_le_jeton(client_sans_jeton):
    """Sans jeton, aucune page. C'est la garantie la plus importante du fichier."""
    assert client_sans_jeton.get("/m").status_code == 401


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
