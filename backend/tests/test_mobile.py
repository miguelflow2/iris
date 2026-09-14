"""Accès mobile : la page téléphone, et surtout le fait qu'elle reste protégée.

IRIS exécute des commandes sur l'ordinateur. Ouvrir son interface au réseau est une décision qui
doit rester explicite, et le jeton doit être exigé partout, sans exception.

Depuis le 2026-09-13, la page téléphone est une coquille en plusieurs fichiers (mobile_static/ :
index.html, app.css, js/api.js, js/coeur.js, sw.js) sur laquelle les modules des fonctions viennent
s'enregistrer. Les garanties d'avant (Safari iOS, voix, connexion, voile VELA) sont vérifiées sur ce
que le téléphone charge VRAIMENT : la page et ses fichiers de coquille.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from iris import mobile
from iris.mobile import AGENT_SERVICE, DOSSIER_STATIQUE, EMPREINTE_COQUILLE, MANIFESTE, PAGE, urls_locales

# La voile VELA, source unique : renderer/src/components/Voile.tsx. Aucune approximation.
FOC = "M 36.5 46.3 L 36.6 158 L 0 158 Z"
GRAND_VOILE = "M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z"
CREME, ENCRE, TERRACOTTA = "#F8F0E7", "#1B140E", "#B36B3B"
FOND = "#1b1b1d"  # fond graphite des maquettes du 2026-09-12, commun au bureau et au téléphone

INDEX_HTML = (DOSSIER_STATIQUE / "index.html").read_text(encoding="utf-8")
API_JS = (DOSSIER_STATIQUE / "js" / "api.js").read_text(encoding="utf-8")
COEUR_JS = (DOSSIER_STATIQUE / "js" / "coeur.js").read_text(encoding="utf-8")
CSS = (DOSSIER_STATIQUE / "app.css").read_text(encoding="utf-8")
# Ce que le téléphone charge réellement pour la coquille (les fichiers sources, et la page composée).
COQUILLE = "\n".join((INDEX_HTML, CSS, API_JS, COEUR_JS))
FICHIERS_COQUILLE = {"page servie (/m)": PAGE, "index.html": INDEX_HTML, "app.css": CSS, "js/api.js": API_JS,
                     "js/coeur.js": COEUR_JS, "sw.js": AGENT_SERVICE}


def _script_en_ligne(page: str) -> str:
    trouve = re.search(r'<script type="module">(.*?)</script>', page, flags=re.S)
    assert trouve, "la page servie n'embarque pas la coquille"
    return trouve.group(1)


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
    for nom, contenu in FICHIERS_COQUILLE.items():
        for interdit in ("http://", "https://", "cdn", "@import"):
            assert interdit not in contenu, f"ressource externe détectée dans {nom} : {interdit}"


def test_la_page_contient_lessentiel():
    for attendu in ("SpeechRecognition", "speechSynthesis", "fr-CA", "Appuyez pour parler", "viewport"):
        assert attendu in COQUILLE, f"manque : {attendu}"


def test_la_page_gere_labsence_de_reconnaissance_vocale():
    """Sur un navigateur sans reconnaissance vocale, il doit rester possible d'écrire."""
    assert "Voix indisponible" in COQUILLE and "ou écrivez ici" in PAGE


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
        assert attendu in COQUILLE, f"manque : {attendu}"
    # IRIS verrouillée : la page affiche l'écran de déverrouillage au lieu de reboucler.
    assert "/api/confiance/deverrouiller" in COEUR_JS and "iris.verrouillee" in API_JS


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
    assert m == json.loads((DOSSIER_STATIQUE / "manifest.webmanifest").read_text(encoding="utf-8"))


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
    assert "url.pathname === '/ws'" in r.text, "le WebSocket non plus"
    assert "self.location.origin" in r.text, "les autres origines (cartographie, relais) ne sont pas interceptées"
    assert "e.request.method !== 'GET'" in r.text
    # La clé de cache est le chemin nu : « /m?token=… » ne doit jamais finir écrit dans le cache.
    assert "const cle = url.pathname" in r.text


def test_la_page_declare_le_manifeste():
    assert 'rel="manifest"' in PAGE and "serviceWorker" in COEUR_JS


# --------------------------------------------------------------------------- identité VELA
def test_la_voile_remplace_lancien_anneau():
    """Le logo est une voile, reprise au tracé près de la source unique."""
    for page in (INDEX_HTML, PAGE):
        assert page.count(FOC) == 2, "le foc doit être là deux fois : entête et écran de connexion"
        assert page.count(GRAND_VOILE) == 2
        assert 'viewBox="0 0 120 158"' in page
    assert "A 36 36 0 1 0" not in COQUILLE + PAGE, "l'ancien anneau ne doit plus exister nulle part"


def test_le_logo_reste_visible_sur_le_fond_sombre():
    """Règle absolue : jamais la grand-voile encre sur fond sombre, elle y disparaîtrait.
    (Sur le HTML seul : les icônes des tuiles, dessinées par coeur.js, ne sont pas le logo.)"""
    for morceau in INDEX_HTML.split("<svg")[1:]:
        svg = morceau.split("</svg>")[0]
        grand = svg.split(GRAND_VOILE, 1)[1] if GRAND_VOILE in svg else ""
        assert CREME in grand.split("/>", 1)[0], "la grand-voile doit être crème sur ce fond sombre"
        foc = svg.split(FOC, 1)[1]
        assert TERRACOTTA in foc.split("/>", 1)[0], "le foc porte la couleur de la marque"


def test_lancien_teal_a_totalement_disparu():
    for teal in ("#17c793", "#0f6e56", "17C793", "0F6E56"):
        assert teal not in COQUILLE, f"couleur abandonnée encore présente : {teal}"


def test_la_voile_garde_ses_couleurs_et_le_fond_suit_les_maquettes():
    """Refonte du 2026-09-12 : fond graphite et boutons holographiques, comme le bureau. La voile,
    elle, garde la crème et la terracotta de VELA."""
    for couleur in (CREME, TERRACOTTA):
        assert couleur in PAGE, f"manque à la voile : {couleur}"
    assert f'<meta name="theme-color" content="{FOND}">' in PAGE
    assert MANIFESTE["theme_color"] == MANIFESTE["background_color"] == FOND
    assert f"--bg: {FOND};" in CSS and "--holo:" in CSS


# --------------------------------------------------------------------------- l'iPhone de Miguel
def test_liphone_est_reconnu():
    """iOS n'offre jamais « Installer l'application » : il faut le détecter pour l'expliquer."""
    assert "iPad|iPhone|iPod" in COEUR_JS
    assert "navigator.standalone" in COEUR_JS, "déjà posée sur l'écran d'accueil : ne rien proposer"


def test_le_bandeau_dinstallation_nomme_safari_et_ne_revient_pas():
    assert "Safari" in COEUR_JS, "sans Safari, le geste « Sur l'écran d'accueil » n'existe pas"
    assert "Sur l'écran d'accueil" in COEUR_JS
    assert "Partager" in COEUR_JS
    assert "iris_ios_installe" in COEUR_JS, "le bandeau fermé doit rester fermé"


def test_la_synthese_vocale_est_amorcee_par_un_geste():
    """Sans énonciation lancée depuis un vrai geste, iOS garde IRIS muette pour toujours."""
    assert "amorcerSynthese" in COEUR_JS
    assert COEUR_JS.count("amorcerSynthese()") >= 3, "le bouton, l'envoi écrit et la connexion"
    debut = COEUR_JS.index("function amorcerSynthese")
    corps = COEUR_JS[debut:debut + 420]
    assert "SpeechSynthesisUtterance" in corps and "volume = 0" in corps


def test_une_voix_francaise_est_choisie_si_le_telephone_en_a_une():
    assert "fr-ca" in COEUR_JS and "fr-fr" in COEUR_JS
    assert "voiceschanged" in COEUR_JS, "sur iOS la liste des voix arrive après le chargement"


def test_le_bouton_ne_reste_jamais_bloque_sur_parlez():
    """onend sans résultat, session coupée, micro muet : dans tous les cas on revient au repos."""
    assert "reco.onend" in COEUR_JS and "onerror" in COEUR_JS
    assert "setTimeout" in COEUR_JS and "12000" in COEUR_JS, "un garde-fou doit reprendre la main"
    for rappel in ("function repos", "clearTimeout(garde)", "classList.remove('ecoute')"):
        assert rappel in COEUR_JS, f"manque : {rappel}"


def test_le_micro_refuse_bascule_en_saisie_ecrite():
    assert "basculerEnEcrit" in COEUR_JS
    assert "not-allowed" in COEUR_JS and "service-not-allowed" in COEUR_JS
    assert "Voix indisponible" in COEUR_JS and "champ.focus()" in COEUR_JS


def test_la_zone_sure_et_le_clavier_sont_respectes():
    for regle in ("env(safe-area-inset-top)", "env(safe-area-inset-bottom)",
                  "env(safe-area-inset-left)", "env(safe-area-inset-right)"):
        assert regle in CSS, f"encoche ou barre du bas ignorée : {regle}"
    assert "visualViewport" in COEUR_JS, "sinon le clavier iOS recouvre le champ de saisie"
    assert "font-size:16px" in CSS, "sous 16 px, Safari zoome tout seul à la mise au point"


def test_la_hauteur_a_un_repli_pour_les_ios_anciens():
    """100dvh manque avant iOS 15.4 : sans repli, la page serait coupée."""
    assert "--hauteur:100vh" in CSS
    assert "@supports (height: 100dvh)" in CSS


def test_le_stockage_local_ne_fait_jamais_planter_la_page():
    """Safari en navigation privée fait lever localStorage : la page doit survivre."""
    assert "function memoire" in API_JS and "function retenir" in API_JS
    assert "localStorage.getItem" in API_JS[API_JS.index("function memoire"):API_JS.index("function memoire") + 200]
    assert "localStorage" not in COEUR_JS, "la coquille passe par memoire/retenir/oublier"


# --------------------------------------------------------------------------- Safari iOS
def test_aucun_mandataire_comme_en_tetes():
    """Safari lève une TypeError à chaque requête si les en-têtes de fetch sont un Proxy.
    Bug réel : la page plantait en boucle sur iPhone (« un problème s'est produit à plusieurs fois »)."""
    assert "new Proxy" not in COQUILLE, "un mandataire en en-têtes casse Safari"
    assert "headers: EN_TETES" not in COQUILLE
    assert "headers: enTetes()" in API_JS, "chaque requête construit ses en-têtes"
    assert "fetch(" not in COEUR_JS, "toutes les requêtes de la coquille passent par api.js"


def test_le_jeton_est_relu_a_chaque_requete():
    """Après la connexion, le jeton change : des en-têtes figées enverraient l'ancien."""
    assert "function enTetes()" in API_JS
    assert "'Bearer ' + JETON" in API_JS


# --------------------------------------------------------------------------- le jeton d'adresse
# Defaut trouve par une relecture adverse le 2026-09-05. IRIS ecrit elle-meme son jeton maitre dans
# l'adresse qu'elle donne au telephone (« /m?token=... »). Le serveur acceptait ce jeton de
# n'importe ou : quiconque avait vu l'adresse — un historique, une capture d'ecran, un message
# qu'on s'envoie a soi-meme — commandait l'ordinateur SANS le mot de passe. Et la documentation
# affirmait le contraire a l'endroit exact ou le lecteur cherche a se rassurer.
def test_le_jeton_dadresse_ne_vaut_plus_depuis_lexterieur(client, client_sans_jeton):
    client.post("/api/compte", json={"nouveau": "motdepasse-solide"})

    # Depuis un tunnel ou un mandataire : ces en-tetes trahissent un intermediaire.
    for entete in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "Forwarded"):
        r = client_sans_jeton.get("/api/status?token=test-token", headers={entete: "203.0.113.7"})
        assert r.status_code == 401, "le jeton d'adresse a suffi malgre " + entete
        assert "mot de passe" in r.json()["detail"].lower(), "le refus doit dire quoi faire"


def test_le_meme_jeton_marche_toujours_depuis_cet_ordinateur(client):
    """L'application elle-meme s'en sert : la casser reviendrait a rendre IRIS inutilisable."""
    client.post("/api/compte", json={"nouveau": "motdepasse-solide"})
    assert client.get("/api/status").status_code == 200


def test_sans_mot_de_passe_le_jeton_dadresse_reste_le_seul_secret(client_sans_jeton):
    """Tant que personne n'a pose de mot de passe, ce jeton est tout ce qu'on a : le refuser
    fermerait l'acces telephone a quelqu'un qui n'a encore rien configure."""
    r = client_sans_jeton.get("/api/status?token=test-token", headers={"X-Forwarded-For": "203.0.113.7"})
    assert r.status_code == 200


def test_la_session_du_telephone_traverse_le_tunnel(client, client_sans_jeton):
    """C'est la voie normale : mot de passe, puis session. Elle doit marcher de l'exterieur."""
    client.post("/api/compte", json={"nouveau": "motdepasse-solide"})
    session = client_sans_jeton.post("/api/compte/connexion", json={"mot_de_passe": "motdepasse-solide"}).json()["session"]
    r = client_sans_jeton.get("/api/status", headers={"Authorization": "Bearer " + session, "X-Forwarded-For": "203.0.113.7"})
    assert r.status_code == 200


def test_pas_de_jeton_maitre_dans_la_page_quand_un_mot_de_passe_existe(client, client_sans_jeton):
    """La page et ses fichiers ne portent aucun secret ; et une fois le mot de passe posé, la coquille
    retire elle-même « ?token=… » de l'adresse et de la mémoire du téléphone."""
    client.post("/api/compte", json={"nouveau": "motdepasse-solide"})
    for chemin in ("/m?token=test-token", "/m/js/coeur.js", "/m/js/api.js", "/m/app.css", "/sw.js"):
        r = client_sans_jeton.get(chemin, headers={"X-Forwarded-For": "203.0.113.7"})
        assert r.status_code == 200, chemin
        assert "test-token" not in r.text, f"jeton maître présent dans {chemin}"
    debut = COEUR_JS.index("if (compte.configure) {")
    bloc = COEUR_JS[debut:debut + 700]
    assert "history.replaceState" in bloc and "api.oublierJetonAdresse()" in bloc
    assert "oublier('iris_token')" in API_JS


# --------------------------------------------------------------------------- fichiers de la coquille (routes_mobile)
def test_les_fichiers_de_la_coquille_sont_servis_avec_le_bon_type(client_sans_jeton):
    """Publics comme /m, branchés par main.py, types MIME exacts (nosniff les exige)."""
    attendus = {
        "/m/app.css": ("text/css", DOSSIER_STATIQUE / "app.css"),
        "/m/js/api.js": ("text/javascript", DOSSIER_STATIQUE / "js" / "api.js"),
        "/m/js/coeur.js": ("text/javascript", DOSSIER_STATIQUE / "js" / "coeur.js"),
    }
    for chemin, (type_mime, fichier) in attendus.items():
        r = client_sans_jeton.get(chemin)
        assert r.status_code == 200, chemin
        assert r.headers["content-type"].startswith(type_mime), chemin
        assert r.content == fichier.read_bytes()
        assert r.headers["x-content-type-options"] == "nosniff"
    # Un module absent répond 404 (la page le tolère) ; un nom douteux ne touche jamais le disque.
    for chemin in ("/m/js/absent.js", "/m/js/..%2Fcoeur.js", "/m/js/API.JS", "/m/js/coeur.css",
                   "/m/icones/rien.png", "/m/icones/..%2F..%2Fmain.py"):
        assert client_sans_jeton.get(chemin).status_code == 404, chemin


def _mini_app(relais: str = "https://relais.exemple.ca", repli: str = ""):
    """Le routeur seul, sur un faux contexte : les en-têtes se vérifient sans démarrer IRIS."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from iris.routes_mobile import creer_routeur

    ctx = SimpleNamespace(settings=SimpleNamespace(user=SimpleNamespace(relay_server=relais), relay_base_override=repli))
    app = FastAPI()
    app.include_router(creer_routeur(ctx))
    return ctx, TestClient(app, base_url="https://bureau.tail1234.ts.net")


def test_la_politique_de_contenu_autorise_seulement_le_necessaire(monkeypatch):
    monkeypatch.setenv("VELA_RELAIS_REPLIS", "https://repli.exemple.ca")
    _ctx, c = _mini_app(repli="https://autre-repli.exemple.ca")
    r = c.get("/m/js/coeur.js")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    directives = {d.split(" ", 1)[0]: d for d in csp.split("; ")}
    assert directives["script-src"] == f"script-src 'self' '{EMPREINTE_COQUILLE}'", \
        "la coquille par son empreinte, aucun autre script en ligne, aucun eval, aucune autre origine"
    assert directives["default-src"] == "default-src 'self'"
    assert directives["object-src"] == "object-src 'none'" and directives["frame-ancestors"] == "frame-ancestors 'none'"
    connexions = directives["connect-src"].split()[1:]
    assert connexions[0] == "'self'"
    for attendue in ("wss://bureau.tail1234.ts.net", "https://nominatim.openstreetmap.org", "https://routing.openstreetmap.de",
                     "https://relais.exemple.ca", "wss://relais.exemple.ca", "https://repli.exemple.ca", "wss://repli.exemple.ca",
                     "https://autre-repli.exemple.ca"):
        assert attendue in connexions, f"manque : {attendue}"
    for interdit in ("*", "https:", "wss:", "http:", "'unsafe-eval'"):
        assert interdit not in connexions and interdit not in directives["script-src"], interdit
    assert "unsafe-eval" not in csp


def test_les_permissions_et_le_cache_court():
    _ctx, c = _mini_app()
    r = c.get("/m/app.css")
    permissions = r.headers["permissions-policy"]
    for attendue in ("camera=(self)", "microphone=(self)", "geolocation=(self)", "screen-wake-lock=(self)"):
        assert attendue in permissions, attendue
    age = re.search(r"max-age=(\d+)", r.headers["cache-control"])
    assert age and int(age.group(1)) <= 300, "une mise à jour d'IRIS doit atteindre le téléphone vite"
    # Revalidation bon marché : même contenu, 304 sans corps.
    r2 = c.get("/m/app.css", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    assert "content-security-policy" in r2.headers


def test_un_hote_forge_ninjecte_aucune_directive():
    from iris.routes_mobile import politique_contenu

    ctx, _c = _mini_app()
    for hote in ("evil.exemple; script-src *", "a b", "bureau.ts.net'", "x\r\nSet-Cookie: a=b"):
        csp = politique_contenu(ctx, hote)
        assert "script-src *" not in csp and "evil" not in csp and "Set-Cookie" not in csp and "'bureau" not in csp
    assert "wss://[::1]:8765" in politique_contenu(ctx, "[::1]:8765")


def test_un_relais_en_clair_distant_nest_jamais_autorise(monkeypatch):
    """Même règle que le cerveau (connectors.bases_relais) : http seulement en boucle locale."""
    monkeypatch.setenv("VELA_RELAIS_REPLIS", "http://relais-en-clair.exemple.ca")
    from iris.routes_mobile import politique_contenu

    ctx, _c = _mini_app(relais="http://relais-en-clair.exemple.ca")
    csp = politique_contenu(ctx, "bureau.ts.net")
    assert "relais-en-clair" not in csp
    ctx_local, _c = _mini_app(relais="http://127.0.0.1:8100")
    assert "ws://127.0.0.1:8100" in politique_contenu(ctx_local, "bureau.ts.net")


def test_la_page_porte_sa_politique_et_seule_la_coquille_est_en_ligne():
    """/m est servie par main.py sans en-têtes : la page apporte sa propre politique. Un seul script
    en ligne, la coquille, admis par son empreinte exacte ; aucun 'unsafe-inline' pour les scripts,
    aucun gestionnaire on…= dans le HTML, aucun eval."""
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', PAGE)
    assert meta, "politique de contenu absente de la page"
    politique = meta.group(1)
    assert f"script-src 'self' '{EMPREINTE_COQUILLE}';" in politique and "object-src 'none'" in politique
    assert "unsafe-eval" not in politique and "script-src 'self' 'unsafe-inline'" not in politique
    code = _script_en_ligne(PAGE)
    assert EMPREINTE_COQUILLE == "sha256-" + base64.b64encode(hashlib.sha256(code.encode("utf-8")).digest()).decode()
    scripts = re.findall(r"<script[^>]*>", PAGE)
    assert scripts.count('<script type="module">') == 1
    assert all(s == '<script type="module">' or 'src="/m/js/' in s for s in scripts)
    assert not re.search(r"\son[a-z]+=", INDEX_HTML), "gestionnaire d'événement en ligne interdit par la politique"
    for js in (API_JS, COEUR_JS):
        assert "eval(" not in js and "new Function" not in js


def test_la_page_servie_embarque_la_coquille_en_ligne():
    """Une requête au lieu de quatre sur le réseau cellulaire, et une page qui tient debout même si
    routes_mobile.py ne se branche pas. Le code en ligne est exactement celui des fichiers."""
    assert EMPREINTE_COQUILLE, "la composition de la page a échoué : repli sur les fichiers séparés"
    assert '<link rel="stylesheet" href="/m/app.css">' not in PAGE and "<style>" in PAGE
    assert CSS.strip() in PAGE
    code = _script_en_ligne(PAGE)
    assert "function creerLiaison()" in code and "window.IRIS = IRIS;" in code
    assert not re.search(r"^[ \t]*(import|export)[ \t{]", code, flags=re.M), "un script en ligne n'importe ni n'exporte"
    # Les brouillons de textos et d'appels sont bien dans la page que le téléphone reçoit.
    for attendu in ("/api/telephonie/en_attente", "lien_ios", "indexOf('sms:') === 0", "indexOf('tel:') === 0"):
        assert attendu in PAGE


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_le_script_en_ligne_est_un_module_valide(tmp_path):
    """Deux fichiers recollés : une variable déclarée deux fois serait une erreur de syntaxe, et la page
    entière resterait blanche. node --check le voit avant le téléphone."""
    fichier = tmp_path / "coquille-en-ligne.mjs"
    fichier.write_text(_script_en_ligne(PAGE), encoding="utf-8")
    sortie = subprocess.run(["node", "--check", str(fichier)], capture_output=True, text=True, timeout=30)
    assert sortie.returncode == 0, sortie.stderr


def test_la_composition_retombe_sur_les_fichiers_si_quelque_chose_cloche():
    from iris.mobile import PAGE_ABSENTE, composer_page

    assert composer_page(None, API_JS, COEUR_JS, CSS) == (PAGE_ABSENTE, None)
    sans_repere = INDEX_HTML.replace('<link rel="stylesheet" href="/m/app.css">', "")
    assert composer_page(sans_repere, API_JS, COEUR_JS, CSS) == (sans_repere, None)
    assert composer_page(INDEX_HTML, API_JS, COEUR_JS + "\nconst x = '</script>';", CSS) == (INDEX_HTML, None)
    assert composer_page(INDEX_HTML, API_JS.replace("export default liaison.api;", ""), COEUR_JS, CSS) == (INDEX_HTML, None)
    assert composer_page(INDEX_HTML, API_JS, COEUR_JS + "\nexport const fuite = 1;", CSS) == (INDEX_HTML, None)
    assert composer_page(INDEX_HTML, None, COEUR_JS, CSS) == (INDEX_HTML, None)


def test_les_modules_sont_charges_dans_lordre_du_contrat():
    ordre = ["api", "coeur", "guidage", "zones", "partage", "achats", "invite", "interprete"]
    positions = [INDEX_HTML.index(f'<script type="module" src="/m/js/{nom}.js"></script>') for nom in ordre]
    assert positions == sorted(positions), "api.js, coeur.js, puis les modules de fonctions"
    # Dans la page servie : la coquille en ligne d'abord, puis les modules, dans le même ordre.
    servie = [PAGE.index('<script type="module">')] + [
        PAGE.index(f'<script type="module" src="/m/js/{nom}.js"></script>') for nom in ordre[2:]]
    assert servie == sorted(servie)
    # Tolérance : la coquille n'importe aucun module de fonction, un module absent ne la casse pas.
    assert re.findall(r"^import .* from '([^']+)';", COEUR_JS, re.M) == ["./api.js"]


def test_le_contrat_window_iris_est_pose_avant_tout_le_reste():
    for attendu in ("window.IRIS = IRIS;", "IRIS.api = api;", "IRIS.bus = bus;",
                    "IRIS.voix = { parler, ecouter, arreter: arreterVoix };",
                    "IRIS.ui = { toast, ouvrirPanneau, confirmer", "IRIS.enregistrer = enregistrer;"):
        assert attendu in COEUR_JS, f"contrat incomplet : {attendu}"
    contrat = COEUR_JS.index("window.IRIS = IRIS;")
    assert contrat < COEUR_JS.index("enregistrer({ id: 'vision'") < COEUR_JS.index("\ndemarrer();")
    # Les tuiles des modules arrivés APRÈS la coquille sont dessinées aussi.
    assert "function planifierTuiles" in COEUR_JS and "modules.set(String(module.id), module)" in COEUR_JS


# --------------------------------------------------------------------------- comportement réel de api.js (Node, sans réseau)
SCRIPT_API = r"""
globalThis.window = globalThis;
globalThis.location = { origin: 'http://iris.test', search: '?token=jeton-adresse', protocol: 'http:', host: 'iris.test', pathname: '/m' };
const stock = new Map();
globalThis.localStorage = { getItem: (k) => (stock.has(k) ? stock.get(k) : null), setItem: (k, v) => stock.set(k, String(v)), removeItem: (k) => stock.delete(k) };
globalThis.document = { hidden: false, addEventListener() {} };
globalThis.addEventListener = () => {};
const vus = [];
const reponses = [];
globalThis.fetch = async (url, init) => {
  const r = reponses.shift();
  vus.push({ url, init });
  if (r === 'reseau') throw new TypeError('Failed to fetch');
  return new Response(JSON.stringify(r.corps), { status: r.statut, headers: { 'content-type': 'application/json' } });
};
const { api, bus } = await import(process.argv[2]);
const res = {};
reponses.push({ statut: 200, corps: { ok: true } });
await api.get('/api/status');
res.entete1 = vus[0].init.headers.Authorization;
api.ouvrirSession('session-1');
reponses.push({ statut: 200, corps: {} });
await api.get('/api/status');
res.entete2 = vus[1].init.headers.Authorization;
res.objetsNeufs = vus[0].init.headers !== vus[1].init.headers;
res.jetonAdresseOublie = !stock.has('iris_token') && stock.get('iris_session') === 'session-1';
const recus = [];
const off = bus.on('*', (e) => recus.push(e.type));
reponses.push({ statut: 401, corps: { detail: 'IRIS est verrouillée à distance. Déverrouillez-la avec le mot de passe du propriétaire.' } });
try { await api.get('/api/x'); } catch (e) { res.statutVerrou = e.status; }
reponses.push({ statut: 401, corps: { detail: 'jeton de session invalide' } });
try { await api.get('/api/x'); } catch (e) { res.statutSession = e.status; }
reponses.push({ statut: 403, corps: { detail: { code: 'consentement', data_type: 'image', label: 'Images', message: 'Autorisez « Images » dans Confidentialité.' } } });
try { await api.post('/api/accessibilite/decrire', {}); } catch (e) { res.consentement = [e.code, e.message, e.detail.data_type]; }
reponses.push({ statut: 422, corps: { detail: [{ loc: ['body'], msg: 'x' }] } });
try { await api.post('/api/y', {}); } catch (e) { res.validation = e.message; }
reponses.push('reseau');
try { await api.get('/api/status'); } catch (e) { res.reseau = [e.status, e.reseau]; }
off();
bus.on('essai', () => { throw new Error('boum'); });
let second = 0;
const off2 = bus.on('essai', (e) => { second = e.valeur + ':' + e.type; });
bus.emit('essai', { valeur: 5, type: 'autre' });
off2();
bus.emit('essai', { valeur: 9 });
res.second = second;
res.evenements = recus;
res.corpsPost = vus[4].init.body;
// Seconde copie du fichier (un module qui l'importe alors que la page l'embarque déjà) : même liaison.
const copie = await import(process.argv[2] + '?copie=2');
res.memeLiaison = copie.api === api && copie.bus === bus && copie.default === api;
process.stdout.write(JSON.stringify(res));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_api_js_se_comporte_comme_promis(tmp_path):
    script = tmp_path / "essai_api.mjs"
    script.write_text(SCRIPT_API, encoding="utf-8")
    sortie = subprocess.run(["node", str(script), (DOSSIER_STATIQUE / "js" / "api.js").as_uri()],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert sortie.returncode == 0, sortie.stderr
    res = json.loads(sortie.stdout)
    assert res["entete1"] == "Bearer jeton-adresse", "avant la connexion : le jeton d'adresse"
    assert res["entete2"] == "Bearer session-1", "après la connexion : la session, relue à chaque requête"
    assert res["objetsNeufs"] is True and res["jetonAdresseOublie"] is True
    assert res["statutVerrou"] == 401 and res["statutSession"] == 401
    assert res["evenements"] == ["iris.verrouillee", "iris.session_refusee", "iris.connexion"], \
        "verrouillage et session refusée se distinguent ; une coupure réseau se signale une fois"
    assert res["consentement"] == ["consentement", "Autorisez « Images » dans Confidentialité.", "image"]
    assert "invalides" in res["validation"]
    assert res["reseau"] == [0, True]
    assert res["second"] == "5:essai", "un écouteur qui plante ne prive pas les autres ; le type n'est pas écrasé"
    assert json.loads(res["corpsPost"]) == {}
    assert res["memeLiaison"] is True, "deux copies de api.js, ce seraient deux sessions et deux bus"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_la_syntaxe_des_scripts_est_valide():
    for fichier in (DOSSIER_STATIQUE / "js" / "api.js", DOSSIER_STATIQUE / "js" / "coeur.js", DOSSIER_STATIQUE / "sw.js"):
        sortie = subprocess.run(["node", "--check", str(fichier)], capture_output=True, text=True, timeout=30)
        assert sortie.returncode == 0, f"{fichier.name} : {sortie.stderr}"


# --------------------------------------------------------------------------- honnêteté, marque, accessibilité
def test_aucun_nom_de_fournisseur_ni_promesse_absolue():
    for nom, contenu in FICHIERS_COQUILLE.items():
        bas = contenu.lower()
        for fournisseur in ("claude", "anthropic", "openai", "gpt", "gemini", "elevenlabs", "vosk", "piper",
                            "google", "twilio", "openrouter", "mistral"):
            assert fournisseur not in bas, f"nom de fournisseur dans {nom} : {fournisseur}"
        for absolu in ("toujours", "instantané", "entièrement", "parfait", "garanti"):
            assert absolu not in bas, f"formulation absolue dans {nom} : {absolu}"
    assert "toujours" not in MANIFESTE["description"].lower() and "où que vous soyez" not in MANIFESTE["description"]


def test_les_limites_reelles_sont_dites_la_ou_on_les_voit():
    for phrase in (
        "pas une surveillance en direct",                  # vision : une photo, pas un flux
        "n'entend pas votre conversation",                 # sous-titres : micro de l'ordinateur
        "Ne remplace pas un avertisseur homologué",        # alertes
        "mesuré sur ce téléphone",                          # latence mesurée, jamais promise
        "serveurs de son fabricant",                        # dictée du navigateur
        "Pas de vibration sur iPhone",
        "iOS suspend une page web",
        "Mémoire suspendue",
        "L'ordinateur ne répond pas.",
    ):
        assert phrase in COEUR_JS, f"limite non dite : {phrase}"
    # La vision du téléphone ne fait pas parler l'ordinateur resté à la maison.
    assert "parler: false" in COEUR_JS


def test_accessibilite_de_base():
    assert '<html lang="fr-CA">' in PAGE
    assert 'id="fil" class="fil" role="log" aria-live="polite"' in INDEX_HTML, "les réponses sont annoncées"
    assert 'role="alertdialog"' in INDEX_HTML and 'aria-live="assertive"' in INDEX_HTML
    for champ in ("mdp", "texte"):
        assert f'<label for="{champ}"' in INDEX_HTML, f"champ sans libellé : {champ}"
    assert "--cible: 3.5rem" in CSS, "cibles tactiles de 56 px"
    assert "prefers-reduced-motion" in CSS and ":focus-visible" in CSS
    boutons = re.findall(r"<button[^>]*>", INDEX_HTML)
    assert boutons and all('type="' in b for b in boutons)


def test_la_page_de_repli_ne_fait_pas_semblant(monkeypatch, tmp_path):
    """Fichiers de la coquille absents (mauvais empaquetage) : IRIS démarre quand même, et la page dit
    le problème au lieu d'afficher un bouton qui ne mènerait nulle part."""
    monkeypatch.setattr(mobile, "DOSSIER_STATIQUE", tmp_path)
    assert mobile.lire_statique("index.html") is None
    assert mobile._manifeste() == mobile.MANIFESTE_DEFAUT
    assert "pas installée correctement" in mobile.PAGE_ABSENTE and "<script" not in mobile.PAGE_ABSENTE
    assert "/api/" in mobile.AGENT_SERVICE_DEFAUT


def test_lempaquetage_embarque_la_coquille():
    spec = (Path(__file__).resolve().parents[1] / "iris-backend.spec").read_text(encoding="utf-8")
    assert '("iris/mobile_static", "iris/mobile_static")' in spec
