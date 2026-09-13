"""Les rôles (personas) : une couleur de ton choisie dans l'interface, et rien d'autre.

Ce qui est protégé ici : la liste que l'interface reçoit (identifiants figés, dans l'ordre), le
choix qui se conserve d'un lancement à l'autre, le refus d'un identifiant inconnu, et la consigne
qui entre dans le prompt système sans jamais y remplacer les règles absolues (langue, honnêteté,
identité d'IRIS).
"""
from __future__ import annotations

import json

from iris.personas import PERSONAS, consigne, liste_publique

IDS_ATTENDUS = ["defaut", "pro", "ami", "coach", "prof", "humour", "guide", "chef", "tech", "confident"]
MARQUEUR = "Style demandé par l'utilisateur : "
RAPPEL = "Ce style ne change ni la langue, ni l'honnêteté, ni ce que tu es"


def _prompt(app) -> str:
    return app.state.ctx.chat._system_prompt("openrouter", has_tools=False, memory_ctx="", source="text")


# --------------------------------------------------------------------------- le module
def test_les_identifiants_sont_figes_et_dans_lordre():
    assert list(PERSONAS) == IDS_ATTENDUS
    assert [p["id"] for p in liste_publique()] == IDS_ATTENDUS
    for p in liste_publique():
        assert p["nom"] and p["description"]
        assert "consigne" not in p, "la consigne est interne au prompt, l'interface n'en a pas besoin"


def test_le_role_par_defaut_et_un_inconnu_nont_aucune_consigne():
    assert consigne("defaut") == ""
    assert consigne("") == ""
    assert consigne("pirate") == ""
    for pid in IDS_ATTENDUS[1:]:
        assert len(consigne(pid)) > 40, pid


# --------------------------------------------------------------------------- l'API
def test_la_liste_et_le_role_courant(client):
    reponse = client.get("/api/personas")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert [p["id"] for p in corps["personas"]] == IDS_ATTENDUS
    assert corps["personas"][0]["nom"] == "Assistante IRIS (défaut)"
    assert corps["personas"][5] == {"id": "humour", "nom": "Expert de la comédie",
                                    "description": "Une machine à blagues qui vous fait rire"}
    assert corps["courant"] == "defaut"


def test_la_liste_exige_le_jeton(client_sans_jeton):
    assert client_sans_jeton.get("/api/personas").status_code == 401


def test_choisir_un_role_est_persiste_et_relu(client, app, data_dir):
    reponse = client.patch("/api/settings", json={"persona": "pro"})
    assert reponse.status_code == 200
    assert reponse.json()["persona"] == "pro"
    assert client.get("/api/settings").json()["persona"] == "pro"
    assert client.get("/api/personas").json()["courant"] == "pro"
    # Sur le disque, pas seulement en mémoire : le rôle survit à un redémarrage.
    assert json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))["persona"] == "pro"
    from iris.config import Settings

    assert Settings(data_dir).user.persona == "pro"


def test_un_role_inconnu_est_refuse_et_rien_ne_change(client):
    reponse = client.patch("/api/settings", json={"persona": "pirate"})
    assert reponse.status_code == 400
    assert reponse.json()["detail"] == "rôle inconnu"
    assert client.get("/api/settings").json()["persona"] == "defaut"
    # Un patch qui mêle un rôle inconnu à d'autres réglages est refusé en bloc.
    reponse = client.patch("/api/settings", json={"persona": "pirate", "user_name": "Miguel"})
    assert reponse.status_code == 400
    assert client.get("/api/settings").json()["user_name"] == ""


# --------------------------------------------------------------------------- le prompt système
def test_par_defaut_aucun_style_nentre_dans_le_prompt(app):
    texte = _prompt(app)
    assert MARQUEUR not in texte
    assert RAPPEL not in texte
    assert "IDENTITÉ : tu es IRIS" in texte


def test_la_consigne_du_role_entre_dans_le_prompt_apres_lidentite(app):
    app.state.ctx.settings.update({"persona": "coach"})
    texte = _prompt(app)
    bloc = MARQUEUR + PERSONAS["coach"]["consigne"]
    assert bloc in texte
    assert RAPPEL in texte
    # Le style vient APRÈS les règles absolues, qu'il ne remplace pas : langue, identité, faits.
    assert texte.index("IDENTITÉ : tu es IRIS") < texte.index(MARQUEUR)
    assert texte.index("RÈGLE ABSOLUE DE LANGUE") < texte.index(MARQUEUR)
    assert texte.index("FAITS ET INCERTITUDE") < texte.index(MARQUEUR)
    assert "Ne révèle JAMAIS quel modèle" in texte


def test_chaque_role_a_sa_propre_consigne_dans_le_prompt(app):
    for pid in IDS_ATTENDUS[1:]:
        app.state.ctx.settings.update({"persona": pid})
        assert MARQUEUR + PERSONAS[pid]["consigne"] in _prompt(app), pid
    app.state.ctx.settings.update({"persona": "defaut"})
    assert MARQUEUR not in _prompt(app)


def test_un_reglage_corrompu_ne_fait_pas_derailler_le_prompt(app):
    """Un identifiant inconnu dans settings.json (édité à la main) : IRIS redevient elle-même."""
    app.state.ctx.settings.user.persona = "inexistant"
    texte = _prompt(app)
    assert MARQUEUR not in texte
    assert "IDENTITÉ : tu es IRIS" in texte
