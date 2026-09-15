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
from fastapi import Request  # au niveau du module : les annotations sont des chaînes (from __future__)

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
# TOUS les scripts que le téléphone peut charger : la coquille ET les modules des fonctions (lunettes, guidage,
# zones, partage, achats, invité, interprète). Un test qui ne regarde que la coquille laisse passer un octet
# NUL, un nom de fournisseur ou une promesse absolue dans un module.
SCRIPTS = {f"js/{f.name}": f.read_text(encoding="utf-8") for f in sorted((DOSSIER_STATIQUE / "js").glob("*.js"))}
LUNETTES_JS = SCRIPTS["js/lunettes.js"]
GUIDAGE_JS = SCRIPTS["js/guidage.js"]


def _sans_commentaires(js: str) -> str:
    """Le texte d'un script sans ses commentaires : les formulations absolues comptent dans ce qui s'affiche,
    pas dans une explication pour le développeur (« arrêter reste toujours possible »)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|[ \t;{}(),])//[^\n]*", r"\1", js, flags=re.M)


def _corps_fonction(js: str, signature: str) -> str:
    """Le corps d'une fonction de premier niveau : de sa signature à la prochaine fonction de premier niveau."""
    debut = js.index(signature)
    suite = re.search(r"^(?:async )?function ", js[debut + len(signature):], flags=re.M)
    return js[debut:debut + len(signature) + (suite.start() if suite else len(js))]


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
# Ce qui CHARGE une ressource (script, style, image, module, police). Un lien de navigation (« Acheter les
# lunettes ») ou une connexion déclarée (OpenStreetMap, dans la politique de contenu) n'en est pas une.
RESSOURCES_EXTERNES = (
    r"""<script[^>]*\ssrc\s*=\s*["']?(?:https?:)?//""",
    r"""<link[^>]*\shref\s*=\s*["']?(?:https?:)?//""",
    r"""<img[^>]*\ssrc\s*=\s*["']?(?:https?:)?//""",
    r"@import",
    r"""url\(\s*["']?(?:https?:)?//""",
    r"""^\s*import\b[^;\n]*from\s*["'](?:https?:)?//""",
    r"""import\(\s*["'](?:https?:)?//""",
    r"""\bsrc\s*[:=]\s*["'](?:https?:)?//""",
    r"cdn\.",
)


def test_la_page_est_autonome():
    """Elle doit fonctionner dans une voiture, sur un réseau incertain : aucune ressource externe chargée."""
    for nom, contenu in {**FICHIERS_COQUILLE, **SCRIPTS}.items():
        for motif in RESSOURCES_EXTERNES:
            trouve = re.search(motif, contenu, flags=re.I | re.M)
            assert not trouve, f"ressource externe chargée dans {nom} : {trouve.group(0)!r}"
    # Le repli d'achat de la coquille est une adresse écrite en clair, plus une concaténation pour contourner ce test.
    assert "'https:' + '//" not in COEUR_JS


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
    from iris.routes_mobile import reponse_page

    app = FastAPI()
    app.include_router(creer_routeur(ctx))

    # /m comme main.py doit la servir (routes_mobile.reponse_page) : la politique ne compte que sur le document.
    @app.get("/m")
    def page(request: Request):
        return reponse_page(ctx, request, PAGE)

    return ctx, TestClient(app, base_url="https://bureau.tail1234.ts.net")


def test_la_politique_de_contenu_autorise_seulement_le_necessaire(monkeypatch):
    monkeypatch.setenv("VELA_RELAIS_REPLIS", "https://repli.exemple.ca")
    _ctx, c = _mini_app(repli="https://autre-repli.exemple.ca")
    r = c.get("/m")
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
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
    document = c.get("/m")
    permissions = document.headers["permissions-policy"]
    for attendue in ("camera=(self)", "microphone=(self)", "geolocation=(self)", "screen-wake-lock=(self)", "payment=()"):
        assert attendue in permissions, attendue
    assert document.headers["referrer-policy"] == "same-origin", "le nom .ts.net ne part vers aucune autre origine"
    assert document.headers["cache-control"] == "no-cache"
    r = c.get("/m/app.css")
    age = re.search(r"max-age=(\d+)", r.headers["cache-control"])
    assert age and int(age.group(1)) <= 300, "une mise à jour d'IRIS doit atteindre le téléphone vite"
    # Revalidation bon marché : même contenu, 304 sans corps.
    r2 = c.get("/m/app.css", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    assert r2.headers["x-content-type-options"] == "nosniff"


def test_les_fichiers_ne_portent_plus_une_politique_sans_effet():
    """Un navigateur ignore la politique de contenu et les permissions d'un fichier JS ou CSS : les y poser
    faisait croire à une protection de la page qui n'existait pas (revue du 2026-09-14)."""
    _ctx, c = _mini_app()
    for chemin in ("/m/js/coeur.js", "/m/app.css"):
        r = c.get(chemin)
        assert r.status_code == 200
        assert "content-security-policy" not in r.headers and "permissions-policy" not in r.headers, chemin
        assert r.headers["x-content-type-options"] == "nosniff"


def test_les_reponses_pretes_pour_main_py():
    """L'agent de service et le manifeste : ce que main.py doit poser (nosniff partout, politique du worker)."""
    from iris.routes_mobile import entetes_securite, reponse_agent_service, reponse_manifeste

    sw = reponse_agent_service(AGENT_SERVICE)
    assert sw.headers["x-content-type-options"] == "nosniff" and "javascript" in sw.headers["content-type"]
    politique_sw = sw.headers["content-security-policy"]
    assert "connect-src 'self'" in politique_sw and "https:" not in politique_sw
    manifeste = reponse_manifeste(MANIFESTE)
    assert manifeste.headers["x-content-type-options"] == "nosniff"
    assert "manifest+json" in manifeste.headers["content-type"]
    # L'ancien nom reste utilisable, avec l'interdiction d'intégration dans un cadre.
    from starlette.requests import Request

    requete = Request({"type": "http", "method": "GET", "path": "/m", "headers": [(b"host", b"bureau.ts.net")]})
    assert entetes_securite(_mini_app()[0], requete)["X-Frame-Options"] == "DENY"


def test_la_page_m_porte_les_entetes(client_sans_jeton):
    """LE test qui compte : les en-têtes sur le document réellement servi par IRIS. main.py pose ceux de
    routes_mobile (reponse_page, reponse_agent_service, reponse_manifeste) sur /m, /sw.js et le manifeste ;
    strict depuis le 2026-09-14 (il était « échec attendu » tant que main.py ne les posait pas)."""
    r = client_sans_jeton.get("/m")
    assert r.status_code == 200
    assert "content-security-policy" in r.headers, "main.py sert /m sans en-têtes de sécurité"
    csp = r.headers["content-security-policy"]
    directives = {d.split(" ", 1)[0]: d for d in csp.split("; ")}
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"
    connexions = directives["connect-src"].split()[1:]
    for interdit in ("https:", "http:", "wss:", "ws:", "*"):
        assert interdit not in connexions, f"connect-src ouvert : {interdit}"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "camera=(self)" in r.headers["permissions-policy"]
    sw = client_sans_jeton.get("/sw.js")
    assert sw.headers.get("x-content-type-options") == "nosniff"
    assert "connect-src 'self'" in sw.headers.get("content-security-policy", "")
    assert client_sans_jeton.get("/manifest.webmanifest").headers.get("x-content-type-options") == "nosniff"


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
    # Plus de « https: » ouvert à toute origine : seulement cette origine et les deux services du guidage.
    connexions = re.search(r"connect-src ([^;]+);", politique).group(1).split()
    assert "https:" not in connexions and "http:" not in connexions and "*" not in connexions
    assert {"'self'", "https://nominatim.openstreetmap.org", "https://routing.openstreetmap.de"} <= set(connexions)
    assert "frame-src 'none'" in politique
    assert '<meta name="referrer" content="same-origin">' in PAGE
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
    ordre = ["api", "coeur", "lunettes", "guidage", "zones", "partage", "achats", "invite", "interprete"]
    positions = [INDEX_HTML.index(f'<script type="module" src="/m/js/{nom}.js"></script>') for nom in ordre]
    assert positions == sorted(positions), "api.js, coeur.js, lunettes.js (EN PREMIER des modules), puis les fonctions"
    # Tous les modules présents dans le dossier sont chargés par la page, et mis en cache par l'agent de service.
    for nom in SCRIPTS:
        assert f'src="/m/{nom}"' in INDEX_HTML, f"{nom} n'est pas chargé par la page"
        if nom not in ("js/api.js", "js/coeur.js"):
            assert f"'/m/{nom}'" in AGENT_SERVICE, f"{nom} absent de la coquille hors ligne"
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
    fichiers = sorted((DOSSIER_STATIQUE / "js").glob("*.js")) + [DOSSIER_STATIQUE / "sw.js"]
    assert len(fichiers) >= 10, "la coquille, les modules des fonctions et l'agent de service"
    for fichier in fichiers:
        assert b"\x00" not in fichier.read_bytes(), f"octet NUL dans {fichier.name}"
        sortie = subprocess.run(["node", "--check", str(fichier)], capture_output=True, text=True, timeout=30)
        assert sortie.returncode == 0, f"{fichier.name} : {sortie.stderr}"


# --------------------------------------------------------------------------- honnêteté, marque, accessibilité
def test_aucun_nom_de_fournisseur_ni_promesse_absolue():
    for nom, contenu in {**FICHIERS_COQUILLE, **SCRIPTS}.items():
        bas = contenu.lower()
        for fournisseur in ("claude", "anthropic", "openai", "gpt", "gemini", "elevenlabs", "vosk", "piper",
                            "google", "twilio", "openrouter", "mistral"):
            assert fournisseur not in bas, f"nom de fournisseur dans {nom} : {fournisseur}"
        # Les modules expliquent parfois une règle en commentaire (« arrêter reste toujours possible ») : seul
        # le texte qui peut s'afficher compte. La coquille, elle, est vérifiée en entier, comme avant.
        visible = _sans_commentaires(bas) if nom in SCRIPTS and nom not in ("js/api.js", "js/coeur.js") else bas
        for absolu in ("toujours", "instantané", "entièrement", "parfait", "garanti"):
            assert absolu not in visible, f"formulation absolue dans {nom} : {absolu}"
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
    # La composition réelle, avec le dossier absent : exactement ce que mobile.py calcule à l'import.
    page, empreinte = mobile.composer_page(mobile.lire_statique("index.html"), mobile.lire_statique("js/api.js"),
                                           mobile.lire_statique("js/coeur.js"), mobile.lire_statique("app.css"))
    assert (page, empreinte) == (mobile.PAGE_ABSENTE, None)
    # Dossier incomplet (gabarit seul) : la page en fichiers séparés, sans empreinte ni coquille en ligne.
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    page, empreinte = mobile.composer_page(mobile.lire_statique("index.html"), mobile.lire_statique("js/api.js"),
                                           mobile.lire_statique("js/coeur.js"), mobile.lire_statique("app.css"))
    assert page == INDEX_HTML and empreinte is None and '<script type="module" src="/m/js/coeur.js">' in page
    # Manifeste illisible : le manifeste par défaut, jamais une exception au démarrage.
    (tmp_path / "manifest.webmanifest").write_text("{pas du json", encoding="utf-8")
    assert mobile._manifeste() == mobile.MANIFESTE_DEFAUT


def test_lempaquetage_embarque_la_coquille():
    spec = (Path(__file__).resolve().parents[1] / "iris-backend.spec").read_text(encoding="utf-8")
    assert '("iris/mobile_static", "iris/mobile_static")' in spec


# --------------------------------------------------------------------------- lunettes d'abord dans la coquille (revue du 2026-09-14)
def test_les_fonctions_de_la_coquille_passent_par_la_garde_des_lunettes():
    """Sans lunettes, la vision n'ouvre pas l'appareil photo et n'envoie aucune photo pour se la faire refuser
    ensuite ; « Où ai-je posé ? » et les sous-titres affichent l'invitation au lieu d'appeler l'ordinateur ;
    un refus 428 est traité une seule fois (pas de message technique ET de panneau, pas de phrase lue deux fois)."""
    for signature in ("async function ouvrirVision(ctx)", "async function ouvrirOuEst(ctx)", "async function ouvrirSousTitres(ctx)"):
        corps = _corps_fonction(COEUR_JS, signature)
        assert "await gardeLunettes(ctx, {" in corps, f"garde absente : {signature}"
        assert "contenu" in corps and "hidden: true" in corps, f"contenu visible avant la vérification : {signature}"
        assert "garde.refus(err" in corps, f"refus 428 non traité : {signature}"
        assert "garde.fermer()" in corps, f"garde jamais fermée : {signature}"
    garde = _corps_fonction(COEUR_JS, "async function gardeLunettes(ctx, options)")
    assert "window.IRIS.lunettes" in garde and "outil.garde(ctx, options)" in garde
    assert "reste fermée" in garde, "sans lunettes.js, la fonction reste fermée"
    vision = _corps_fonction(COEUR_JS, "async function ouvrirVision(ctx)")
    photo = vision[vision.index("function prendrePhoto(m)"):]
    assert photo.index("garde.presentes() !== true") < photo.index("entree.click()"), "l'appareil photo s'ouvrirait sans lunettes"
    assert "La caméra des lunettes arrive ; en attendant, la photo est prise avec ce téléphone." in vision
    # Le repli d'achat ne passe plus par une concaténation, et l'adresse de l'ordinateur prime.
    assert "function adresseAchat(proposee)" in COEUR_JS and "URL_ACHAT_LUNETTES" in COEUR_JS


def test_les_sous_titres_ne_laissent_pas_le_micro_de_la_maison_ouvert():
    """Démarrer depuis le téléphone ouvre le micro d'une pièce de la maison : accord explicite d'abord, et arrêt
    par une requête qui survit à la suspension dès que la page quitte l'écran."""
    corps = _corps_fonction(COEUR_JS, "async function ouvrirSousTitres(ctx)")
    clic = corps[corps.index("bascule.addEventListener('click'"):]
    assert clic.index("confirmer(") < clic.index("/api/ecoute/sous-titres/demarrer"), "le micro s'ouvrirait sans accord"
    assert "Ouvrir le micro" in clic and "n'ont rien accepté" in clic
    assert "document.addEventListener('visibilitychange', surVisibilite)" in corps
    assert "window.addEventListener('pagehide', arreterDepuisIci)" in corps
    assert "{ keepalive: true" in corps and "document.removeEventListener('visibilitychange', surVisibilite)" in corps
    assert "keepalive: !!opts.keepalive" in API_JS, "api.js doit transmettre keepalive au navigateur"


def test_le_chat_montre_lapercu_et_ne_deguise_pas_un_refus_en_reponse():
    assert 'id="apercu-lunettes"' in INDEX_HTML
    envoi = _corps_fonction(COEUR_JS, "async function envoyer(texte)")
    refus = envoi[envoi.index("if (r.lunettes) {"):envoi.index("reponse.textContent = r.texte || '(réponse vide)';")]
    assert "afficherLunettesRequises(" in refus and "return;" in refus
    assert "mesuré sur ce téléphone" not in refus, "un refus n'a pas de délai de réponse mesuré"
    assert COEUR_JS.count("glasses_required") == 2, "par les événements ET par le sondage"
    assert "apercu_restant" in COEUR_JS and "majApercu();" in _corps_fonction(COEUR_JS, "function entrer()")


def test_la_carte_dehors_dit_la_regle_des_lunettes():
    reglages = _corps_fonction(COEUR_JS, "function ouvrirReglages(ctx)")
    for phrase in ("exigent vos lunettes VELA", "passera par l'app IRIS, qui n'est pas encore disponible",
                   "un aperçu de 10 messages", "Sans lunettes"):
        assert phrase in reglages, f"manque : {phrase}"
    assert "ils sont reliés à l'ordinateur par Bluetooth" not in reglages, "phrase contredite par lunettes.js"


def test_le_guidage_nenvoie_pas_le_nom_de_la_machine_a_openstreetmap():
    assert "referrerPolicy: 'no-referrer'" in GUIDAGE_JS
    assert "strict-origin-when-cross-origin" not in GUIDAGE_JS
    assert "'email=' + encodeURIComponent(CONTACT_APPLICATION)" in GUIDAGE_JS
    assert "il peut limiter ou refuser les demandes" in GUIDAGE_JS
    assert "© contributeurs OpenStreetMap" in GUIDAGE_JS, "mention ODbL obligatoire"


# --------------------------------------------------------------------------- comportement réel de lunettes.js (Node, faux Bluetooth)
SCRIPT_LUNETTES = r"""
globalThis.window = globalThis;
window.isSecureContext = true;
const stock = new Map();
globalThis.localStorage = { getItem: (k) => (stock.has(k) ? stock.get(k) : null), setItem: (k, v) => stock.set(k, String(v)), removeItem: (k) => stock.delete(k) };
globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
const ecouteursFenetre = [];
globalThis.addEventListener = (type, fn) => ecouteursFenetre.push([type, fn]);
const intervalles = [];
globalThis.setInterval = (fn, ms) => { intervalles.push({ fn, ms }); return intervalles.length; };
globalThis.clearInterval = () => {};
const fetchs = [];
globalThis.fetch = async (url, init) => { fetchs.push({ url, init }); return new Response('{}'); };

// Le geste de l'utilisateur : Chrome n'ouvre la liste que pendant une activation « transitoire ».
let activation = false;
const demandes = [];
function appareil(id, nom) {
  const ecouteurs = {};
  const gatt = { connected: false, connect() { gatt.connected = true; return Promise.resolve(gatt); },
                 disconnect() { gatt.connected = false; }, getPrimaryService() { return Promise.reject(new Error('pas de batterie')); } };
  return { id, name: nom, gatt, addEventListener(t, fn) { (ecouteurs[t] = ecouteurs[t] || []).push(fn); },
           declencher(t) { (ecouteurs[t] || []).forEach((fn) => fn()); } };
}
let prochain = null;
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
  userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36',
  bluetooth: {
    requestDevice(options) {
      demandes.push({ options, geste: activation });
      if (!activation) return Promise.reject(new DOMException('Must be handling a user gesture', 'SecurityError'));
      return Promise.resolve(prochain);
    },
    getAvailability: async () => true,
    getDevices: async () => [],
  },
} });

const appels = [];
let presence = { presentes: false, source: null, nom: 'VELA K900', apercu_restant: 7, apercu_total: 10, acheter_url: 'https://velaglass.ca/lunettes.html' };
let getBloque = false;
let refuser = false;
let nonAssocie = false;
const api = {
  base: 'https://iris.test',
  jeton: () => 'session-1',
  get: (chemin) => { appels.push(['GET', chemin]); return getBloque ? new Promise(() => {}) : Promise.resolve(presence); },
  post: async (chemin, corps) => {
    appels.push(['POST', chemin, corps]);
    if (refuser) { const e = new Error('Ces lunettes ne sont pas celles associées à votre IRIS.'); e.status = 403; throw e; }
    if (nonAssocie && chemin === '/api/lunettes/attestation') {
      const e = new Error("Ce téléphone n'est pas encore associé à tes lunettes sur cet IRIS."); e.status = 403; e.code = 'appareil_non_associe'; throw e;
    }
    return Object.assign({}, presence, { presentes: true, source: 'telephone' });
  },
  delete: async (chemin) => { appels.push(['DELETE', chemin]); return Object.assign({}, presence, { presentes: false, source: null }); },
};
const modules = [];
window.IRIS = { api, bus: { on: () => () => {}, emit() {} }, enregistrer: (m) => modules.push(m.id), etat: () => ({ pret: true }), ui: { toast() {} }, voix: { parler: async () => true } };
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const res = {};

await import(process.argv[2]);
const L = window.IRIS.lunettes;
await pause(20);                       // la présence lue dès que la session est prête : le nom est en cache
res.contrat = [typeof L.connecter, typeof L.deconnecter, typeof L.garde, L.disponible, modules.includes('lunettes')];

// 1. Connexion : la liste s'ouvre DANS le geste, filtrée sur le nom connu et le service des lunettes.
prochain = appareil('appareil-1', 'VELA K900');
activation = true; let p = L.connecter(); activation = false;
await p;
res.demande1 = demandes[0];
const postes = () => appels.filter((a) => a[0] === 'POST');
res.attestation = postes()[0];
res.intervalle60 = intervalles.filter((i) => i.ms === 60000).length;
intervalles.filter((i) => i.ms === 60000).pop().fn();   // une minute plus tard
await pause(10);
res.postsApresMinute = postes().length;

// 2. Coupure Bluetooth : l'attestation de CES lunettes est retirée, avec leur identifiant.
prochain.gatt.connected = false;
prochain.declencher('gattserverdisconnected');
await pause(10);
res.retrait = appels.filter((a) => a[0] === 'DELETE').map((a) => a[1]);
await L.deconnecter();

// 3. Page fermée : le retrait part par une requête qui survit à la fermeture, avec l'identifiant.
activation = true; p = L.connecter(); activation = false;
await p;
ecouteursFenetre.filter(([t]) => t === 'pagehide').forEach(([, fn]) => fn());
res.pagehide = fetchs.map((f) => [f.url, f.init.method, f.init.keepalive]);
await L.deconnecter();

// 4. Deuxième copie, ordinateur qui ne répond pas encore : aucune liste de n'importe quels appareils, on le dit.
getBloque = true;
await import(process.argv[3]);
const L2 = window.IRIS.lunettes;
res.deuxiemeCopie = L2 !== L;
prochain = appareil('appareil-2', 'VELA K900');
const demandesAvant = demandes.length;
activation = true; p = L2.connecter(); activation = false;
try { await p; res.sansNom = 'accepté'; } catch (e) { res.sansNom = e.message; }
res.demandesSansNom = demandes.length - demandesAvant;
getBloque = false;

// 5. Lunettes refusées par l'ordinateur (403) : on coupe, sans nouvel essai et sans retirer l'attestation d'un autre.
refuser = true;
const avant = { posts: postes().length, deletes: appels.filter((a) => a[0] === 'DELETE').length, intervalles: intervalles.length };
prochain = appareil('appareil-3', 'Autres lunettes');
activation = true; p = L.connecter(); activation = false;
try { await p; res.refus = 'accepté'; } catch (e) { res.refus = e.status; }
await pause(30);
res.apresRefus = {
  posts: postes().length - avant.posts,
  deletes: appels.filter((a) => a[0] === 'DELETE').length - avant.deletes,
  intervalles: intervalles.length - avant.intervalles,
  gatt: prochain.gatt.connected,
  connectees: L.connectees,
};

// 5 bis. Bonnes lunettes, téléphone pas encore associé (403 codé) : le lien reste ouvert, puis l'association avec le
// mot de passe du propriétaire reprend les attestations (constat du 2026-09-14).
refuser = false;
nonAssocie = true;
prochain = appareil('appareil-4', 'VELA K900');
const intervallesAvant = intervalles.length;
activation = true; p = L.connecter(); activation = false;
try { await p; res.nonAssocie = 'accepté'; } catch (e) { res.nonAssocie = e.status; }
res.apresNonAssocie = { connectees: L.connectees, gatt: prochain.gatt.connected, intervalles: intervalles.length - intervallesAvant };
nonAssocie = false;
res.association = await L.associer('mdp-proprio').then((s) => s.attestation_acceptee).catch((e) => e.message);
res.appelAssociation = appels.filter((a) => a[1] === '/api/lunettes/association').map((a) => a[2]);
await L.deconnecter();

// 6. Sans geste : l'erreur du navigateur est traduite, sans jargon.
refuser = false;
try { await L.connecter(); } catch (e) { res.sansGeste = e.message; }
process.stdout.write(JSON.stringify(res));
process.exit(0);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_lunettes_js_se_comporte_comme_promis(tmp_path):
    script = tmp_path / "essai_lunettes.mjs"
    script.write_text(SCRIPT_LUNETTES, encoding="utf-8")
    # Deux copies .mjs du VRAI fichier : sans import ni export, Node chargerait lunettes.js comme un module
    # CommonJS, mis en cache par nom de fichier (une adresse « ?copie=2 » rendrait la même copie).
    copies = []
    for n in (1, 2):
        copie = tmp_path / f"lunettes-{n}.mjs"
        copie.write_text(LUNETTES_JS, encoding="utf-8")
        copies.append(copie.as_uri())
    sortie = subprocess.run(["node", str(script), *copies],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert sortie.returncode == 0, sortie.stderr
    res = json.loads(sortie.stdout)
    assert res["contrat"] == ["function", "function", "function", True, True]
    assert res["demande1"]["geste"] is True, "requestDevice doit être appelé sans attente préalable"
    # Constat du 2026-09-14 : plus de filtre « service 0xae00 » seul, annoncé par bien d'autres objets Bluetooth.
    assert res["demande1"]["options"]["filters"] == [{"name": "VELA K900"}, {"namePrefix": "VELA"}]
    assert 0xAE00 in res["demande1"]["options"]["optionalServices"]
    _, chemin, corps = res["attestation"]
    assert chemin == "/api/lunettes/attestation"
    assert corps["source"] == "android" and corps["identifiant"] == "appareil-1" and corps["nom"] == "VELA K900"
    assert res["intervalle60"] == 1 and res["postsApresMinute"] == 2, "réattestation toutes les 60 s"
    assert res["retrait"] == ["/api/lunettes/attestation?identifiant=appareil-1"], "retrait de SES lunettes seulement"
    assert res["pagehide"] == [["https://iris.test/api/lunettes/attestation?identifiant=appareil-1", "DELETE", True]]
    assert res["deuxiemeCopie"] is True
    assert res["demandesSansNom"] == 0, "nom inconnu : aucune liste ouverte sur un simple service Bluetooth"
    assert "nom de vos lunettes" in res["sansNom"]
    assert res["refus"] == 403
    assert res["apresRefus"] == {"posts": 1, "deletes": 0, "intervalles": 0, "gatt": False, "connectees": False}
    assert "geste" in res["sansGeste"] and "SecurityError" not in res["sansGeste"]
    assert res["nonAssocie"] == 403
    assert res["apresNonAssocie"] == {"connectees": True, "gatt": True, "intervalles": 0}, "lien gardé, rien ne réatteste"
    assert res["association"] is True
    assert res["appelAssociation"] == [{"nom": "VELA K900", "identifiant": "appareil-4", "mot_de_passe": "mdp-proprio"}]


SCRIPT_CADRE = r"""
globalThis.window = globalThis;
window.self = window;
window.top = {};                          // la page est dans un cadre : top n'est pas elle-même
globalThis.location = { origin: 'https://iris.test', search: '', protocol: 'https:', host: 'iris.test', pathname: '/m' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const corps = { enfants: [], textContent: 'formulaire', append(n) { this.enfants.push(n); } };
globalThis.document = { hidden: false, body: corps, addEventListener() {}, createElement: () => ({ className: '', textContent: '' }) };
globalThis.addEventListener = () => {};
const res = {};
try { await import(process.argv[2]); res.importe = true; } catch (e) { res.erreur = e.message; }
res.iris = typeof window.IRIS;
res.corps = corps.enfants.map((n) => n.textContent);
process.stdout.write(JSON.stringify(res));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_la_coquille_refuse_de_demarrer_dans_un_cadre(tmp_path):
    """Détournement de clic : dans le cadre d'un autre site, rien ne démarre (ni formulaire, ni window.IRIS)."""
    script = tmp_path / "essai_cadre.mjs"
    script.write_text(SCRIPT_CADRE, encoding="utf-8")
    sortie = subprocess.run(["node", str(script), (DOSSIER_STATIQUE / "js" / "coeur.js").as_uri()],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert sortie.returncode == 0, sortie.stderr
    res = json.loads(sortie.stdout)
    assert "cadre" in res.get("erreur", ""), res
    assert res["iris"] == "undefined", "le contrat window.IRIS ne doit pas exister dans un cadre"
    assert res["corps"] and "ne s'ouvre pas à l'intérieur d'une autre page" in res["corps"][0]
    assert COEUR_JS.index("if (dansUnCadre)") < COEUR_JS.index("window.IRIS = IRIS;")


def test_lunettes_js_dit_ce_que_la_connexion_peut_couper():
    assert "peut couper leur liaison avec l'ordinateur" in LUNETTES_JS
    assert "function relieesAuPc()" in LUNETTES_JS and "if (relieesAuPc()) { suspendreReconnexion(); return; }" in LUNETTES_JS
    connecter = _corps_fonction(LUNETTES_JS, "async function connecter()")
    avant_liste = connecter[:connecter.index("navigator.bluetooth.requestDevice(")]
    assert "await" not in avant_liste, "aucune attente avant l'ouverture de la liste Bluetooth"



# --------------------------------------------------------------------------- guidage : services cartographiques
# Contre-vérification mobile du 2026-09-14 : la limite d'une requête par seconde des services publics
# d'OpenStreetMap vaut pour la SOMME des utilisateurs, et aucun code dans des téléphones indépendants ne peut la
# tenir ; le mandataire sur le relais est écarté (pas de position GPS sur les serveurs VELA). La page était
# câblée en dur sur ces services : une instance propre ou un fournisseur sous contrat exigeait de changer le
# code, la politique de contenu et la balise meta. Ils se branchent désormais par deux réglages de l'ordinateur.
def test_adresse_des_services_cartographiques_validee():
    from iris.config import UserSettings, adresse_service_cartographique as adresse

    assert adresse("https://carto.exemple.ca/") == "https://carto.exemple.ca"
    assert adresse("https://carto.exemple.ca/route/v1/foot", dossier=True) == "https://carto.exemple.ca/route/v1/foot/"
    assert adresse("http://127.0.0.1:8080/r") == "http://127.0.0.1:8080/r"
    for mauvaise in ("http://carto.exemple.ca", "https://u:p@carto.exemple.ca", "https://carto.exemple.ca/?cle=1",
                     "javascript:alert(1)", "https://carto.exemple.ca; script-src *", "https://x.ca:99999", "ftp://x.ca"):
        assert adresse(mauvaise) == "", mauvaise
    u = UserSettings(guidage_recherche="https://carto.exemple.ca/", guidage_itineraire="https://x.ca/route/v1/foot")
    assert (u.guidage_recherche, u.guidage_itineraire) == ("https://carto.exemple.ca", "https://x.ca/route/v1/foot/")
    assert UserSettings(guidage_recherche="http://exterieur.ca").guidage_recherche == ""
    assert (UserSettings().guidage_recherche, UserSettings().guidage_itineraire) == ("", "")


def test_la_politique_de_contenu_suit_les_services_du_guidage():
    from iris.routes_mobile import politique_contenu, services_guidage

    ctx, c = _mini_app()
    publics = services_guidage(ctx)
    assert publics["recherche_publique"] and publics["itineraire_public"]
    connexions = re.search(r"connect-src ([^;]+)", politique_contenu(ctx, "bureau.ts.net")).group(1).split()
    assert {"https://nominatim.openstreetmap.org", "https://routing.openstreetmap.de"} <= set(connexions)

    ctx.settings.user.guidage_recherche = "https://carto.vela-essai.ca"
    ctx.settings.user.guidage_itineraire = "https://itineraire.vela-essai.ca:8443/route/v1/foot/"
    connexions = re.search(r"connect-src ([^;]+)", politique_contenu(ctx, "bureau.ts.net")).group(1).split()
    assert "https://carto.vela-essai.ca" in connexions and "https://itineraire.vela-essai.ca:8443" in connexions
    assert "https://nominatim.openstreetmap.org" not in connexions, "la position ne peut plus partir vers le public"
    # La balise meta de /m s'applique EN PLUS de l'en-tête : elle doit nommer les mêmes services.
    r = c.get("/m")
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', r.text).group(1)
    assert "https://carto.vela-essai.ca https://itineraire.vela-essai.ca:8443" in meta
    assert "nominatim.openstreetmap.org" not in meta
    assert f"'{EMPREINTE_COQUILLE}'" in r.headers["content-security-policy"], "la coquille en ligne reste admise"
    # Une adresse écrite à la main dans settings.json est revalidée : rien d'injecté dans la politique.
    ctx.settings.user.guidage_recherche = "https://x.ca; script-src *"
    assert "script-src *" not in politique_contenu(ctx, "bureau.ts.net")
    assert services_guidage(ctx)["recherche_publique"] is True


SCRIPT_GUIDAGE = r"""
globalThis.window = globalThis;
window.isSecureContext = true;
class Node {
  constructor(balise) { this.balise = balise; this.enfants = []; this.ecouteurs = {}; this.attributs = {}; this.style = {}; this.dataset = {}; this.classList = { add() {}, remove() {}, toggle() {} }; this.hidden = false; this.disabled = false; this._texte = ''; this.value = ''; }
  append(...n) { for (const e of n) this.enfants.push(e); }
  appendChild(e) { this.enfants.push(e); return e; }
  setAttribute(k, v) { this.attributs[k] = v; }
  addEventListener(t, fn) { (this.ecouteurs[t] = this.ecouteurs[t] || []).push(fn); }
  removeEventListener() {}
  focus() {}
  scrollIntoView() {}
  get textContent() { return this._texte + this.enfants.map((e) => e.textContent).join(''); }
  set textContent(v) { this._texte = String(v); this.enfants = []; }
}
globalThis.Node = Node;
const stock = new Map();
globalThis.localStorage = { getItem: (k) => (stock.has(k) ? stock.get(k) : null), setItem: (k, v) => stock.set(k, String(v)), removeItem: (k) => stock.delete(k) };
globalThis.document = { hidden: false, createElement: (b) => new Node(b), createTextNode: (t) => { const n = new Node('#texte'); n._texte = String(t); return n; },
  addEventListener() {}, removeEventListener() {} };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
  userAgent: 'essai', geolocation: { getCurrentPosition: (ok) => ok({ coords: { latitude: 45.5, longitude: -73.56, accuracy: 8 } }),
  watchPosition: () => 1, clearWatch() {} } } });
const fetchs = [];
globalThis.fetch = async (url, init) => {
  fetchs.push({ url: String(url), referrer: init && init.referrerPolicy });
  return new Response(JSON.stringify({ display_name: 'Rue essai', address: { road: 'Rue Essai', city: 'Montréal' } }), { status: 200 });
};
let reglages = {};
const confirmations = [];
const modules = [];
window.IRIS = {
  enregistrer: (m) => modules.push(m),
  api: { get: async (chemin) => { if (chemin !== '/api/settings') throw new Error('inattendu ' + chemin); return reglages; } },
  ui: { toast() {}, confirmer: async (texte) => { confirmations.push(texte); return true; } },
  voix: { parler: async () => true },
  lunettes: { garde: (ctx, o) => { if (o.contenu) o.contenu.hidden = false; return { verifier: async () => true, refus: () => false, presentes: () => true, etat: () => null, fermer() {} }; } },
};
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));
function trouver(n, texte) {
  if (n.balise === 'button' && n.textContent === texte) return n;
  for (const e of n.enfants) { const t = trouver(e, texte); if (t) return t; }
  return null;
}
async function ouSuisJe() {
  const corps = new Node('div');
  modules[0].ouvrir({ corps, fermer() {} });
  await attendre(20);
  const bouton = trouver(corps, 'Où suis-je ?');
  const avant = fetchs.length;
  for (const fn of bouton.ecouteurs.click) await fn();
  for (let i = 0; i < 400 && fetchs.length === avant; i++) await attendre(10);
  await attendre(20);
  return { url: fetchs.slice(avant).map((f) => f.url), texte: corps.textContent };
}
await import(process.argv[2]);
const res = {};
reglages = { guidage_recherche: 'https://carto.vela-essai.ca', guidage_itineraire: 'https://itineraire.vela-essai.ca/route/v1/foot/' };
res.configure = await ouSuisJe();
res.confirmationsConfigure = confirmations.length;
res.retenu = JSON.parse(localStorage.getItem('iris_guidage_services'));
// Même services : l'accord déjà donné vaut, aucune nouvelle question.
res.memeServices = await ouSuisJe();
res.confirmationsMemeServices = confirmations.length;
// Retour aux services publics : l'accord ne portait pas sur eux, il est redemandé.
reglages = { guidage_recherche: '', guidage_itineraire: '' };
res.publics = await ouSuisJe();
res.confirmationsPublics = confirmations.length;
res.referrers = [...new Set(fetchs.map((f) => f.referrer))];
res.derniereConfirmation = confirmations[confirmations.length - 1];
process.stdout.write(JSON.stringify(res));
process.exit(0);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_le_guidage_utilise_les_services_configures_sur_lordinateur(tmp_path):
    script = tmp_path / "essai_guidage.mjs"
    script.write_text(SCRIPT_GUIDAGE, encoding="utf-8")
    copie = tmp_path / "guidage.mjs"
    copie.write_text(GUIDAGE_JS, encoding="utf-8")
    (tmp_path / "lunettes.js").write_text("export {};\n", encoding="utf-8")  # import('./lunettes.js') du module
    sortie = subprocess.run(["node", str(script), copie.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert sortie.returncode == 0, sortie.stderr
    res = json.loads(sortie.stdout)
    configure = res["configure"]["url"]
    assert len(configure) == 1 and configure[0].startswith("https://carto.vela-essai.ca/reverse?"), configure
    assert "email=" not in configure[0], "le contact de l'application n'est destiné qu'au service public"
    assert "openstreetmap" not in " ".join(configure)
    assert res["confirmationsConfigure"] == 1
    assert res["retenu"] == {"recherche": "https://carto.vela-essai.ca", "itineraire": "https://itineraire.vela-essai.ca/route/v1/foot/"}
    assert "service cartographique choisi dans les réglages de votre IRIS" in res["configure"]["texte"]
    assert "vela-essai" not in res["configure"]["texte"], "aucun nom d'hôte affiché au client"
    assert res["memeServices"]["url"][0].startswith("https://carto.vela-essai.ca/")
    assert res["confirmationsMemeServices"] == 1
    publics = res["publics"]["url"]
    assert len(publics) == 1 and publics[0].startswith("https://nominatim.openstreetmap.org/reverse?")
    assert "email=contact%40velaglass.ca" in publics[0]
    assert res["confirmationsPublics"] == 2, "changer de service redemande l'accord"
    assert "il peut limiter ou refuser les demandes" in res["derniereConfirmation"]
    assert res["referrers"] == ["no-referrer"]


# --------------------------------------------------------------------------- finition du 2026-09-14
def test_aucun_texte_ne_presente_lapp_iphone_comme_disponible():
    """L'app IRIS pour iPhone n'a jamais été compilée ni distribuée (docs/MODE-DEHORS.md §2.2) : aucun texte de la
    page téléphone ne dit de « l'utiliser » ni qu'elle « se connecte » ou « peut » faire quelque chose aujourd'hui."""
    for nom, js in SCRIPTS.items():
        texte = _sans_commentaires(js)
        for interdit in ("utilisez l'app IRIS", "c'est l'app IRIS qui se connecte", "c'est elle qui se connecte",
                         "L'application IRIS pour iPhone, elle, peut"):
            assert interdit not in texte, f"{nom} : « {interdit} » présente l'app iPhone comme disponible"
    assert "n'est pas encore disponible" in _sans_commentaires(LUNETTES_JS)
    assert "n'est pas encore disponible" in _corps_fonction(COEUR_JS, "function ouvrirReglages(ctx)")


def test_les_sous_titres_ferment_la_garde_si_le_panneau_est_ferme_pendant_son_chargement():
    """Le nettoyage du panneau tourne avant que gardeLunettes ne rende la garde : sans drapeau vérifié après l'await,
    la garde, son sondage et ses écouteurs restaient actifs derrière un panneau fermé."""
    corps = _corps_fonction(COEUR_JS, "async function ouvrirSousTitres(ctx)")
    nettoyage = corps[corps.index("surFermeture(() => {"):]
    assert "panneauFerme = true;" in nettoyage[:nettoyage.index("});")]
    apres = corps[corps.index("garde = await gardeLunettes(ctx, {"):]
    apres = apres[apres.index("});") + 3:]
    assert apres.index("if (panneauFerme) { garde.fermer(); return; }") < apres.index("garde.verifier()")


def test_la_documentation_ne_dit_plus_que_les_entetes_de_m_manquent():
    """main.py pose les en-têtes de /m (test_la_page_m_porte_les_entetes, strict) : la documentation et les
    commentaires ne doivent plus dire le contraire."""
    racine = Path(__file__).resolve().parents[2]
    guide = (racine / "docs" / "MODE-DEHORS.md").read_text(encoding="utf-8")
    assert "l'ordinateur ne les pose pas encore" not in guide and "échec attendu" not in guide
    assert "test_la_page_m_porte_les_entetes" in guide
    import iris.routes_mobile as routes_mobile

    assert "TANT QUE main.py ne les appelle pas" not in (routes_mobile.__doc__ or "")
    assert "que doit poser l'ordinateur" not in COEUR_JS and "que l'ordinateur doit poser" not in INDEX_HTML
