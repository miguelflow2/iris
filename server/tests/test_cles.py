"""Les clés émises par le serveur doivent être acceptées par l'application IRIS, sans exception."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import plans_application

from licences import cles
from licences.config import SECRET_HISTORIQUE


def test_cle_du_serveur_identique_a_celle_de_lapplication():
    """Octet pour octet : le serveur et l'application doivent produire la même chaîne."""
    plans = plans_application()
    for plan in ("pro", "premium", "entreprise"):
        attendue = plans.make_key(plan, "2027-09-03", "client@exemple.com")
        obtenue = cles.faire_cle(plan, "2027-09-03", "client@exemple.com", SECRET_HISTORIQUE)
        assert obtenue == attendue, f"divergence de format pour le plan {plan}"


def test_cle_du_serveur_acceptee_par_verify_key_de_lapplication():
    """C'est le test qui compte : la clé livrée au client s'active vraiment dans IRIS."""
    plans = plans_application()
    cle, note = cles.emettre("pro", "2027-09-03", "client@exemple.com", SECRET_HISTORIQUE)
    assert note == ""
    resultat = plans.verify_key(cle)
    assert resultat is not None, "l'application a rejeté une clé émise par le serveur"
    assert resultat["plan"] == "pro"
    assert resultat["expires"] == "2027-09-03"
    assert resultat["expired"] is False


def test_cle_expiree_refusee_des_deux_cotes():
    plans = plans_application()
    hier = (date.today() - timedelta(days=1)).isoformat()
    cle = cles.faire_cle("pro", hier, "client@exemple.com", SECRET_HISTORIQUE)
    assert plans.verify_key(cle)["expired"] is True
    assert cles.verifier_cle(cle, SECRET_HISTORIQUE)["expiree"] is True


def test_signature_falsifiee_rejetee():
    cle = cles.faire_cle("entreprise", "2027-09-03", "client@exemple.com", SECRET_HISTORIQUE)
    charge = cle.rsplit("-", 1)[0]
    assert cles.verifier_cle(charge + "-0000000000000000abcd", SECRET_HISTORIQUE) is None
    # Un autre secret ne doit rien valider non plus.
    assert cles.verifier_cle(cle, b"un-autre-secret") is None


def test_cle_avec_tiret_dans_la_charge_utile_est_lisible():
    """La charge utile est du base64 url-safe : elle peut contenir un « - ».

    L'application découpait autrefois avec split("-", 2) et rejetait silencieusement ces clés.
    Le correctif (rsplit) est en place dans plans.py : le serveur peut donc émettre la clé
    normale, avec le courriel. Le repli reste en place pour les versions anciennes d'IRIS.
    """
    plans = plans_application()
    courriel_piege = "ZZZ~~~@exemple.com"  # produit un « - » dans la charge base64
    directe = cles.faire_cle("pro", "2027-09-03", courriel_piege, SECRET_HISTORIQUE)
    charge = directe[len("IRIS-") : directe.rindex("-")]
    assert "-" in charge, "le piège n'est plus reproductible : revoir ce test"
    assert plans.verify_key(directe) is not None, "l'application doit désormais lire cette clé"

    cle, _note = cles.emettre("pro", "2027-09-03", courriel_piege, SECRET_HISTORIQUE)
    assert plans.verify_key(cle) is not None, "la clé émise doit être lisible par l'application"


def test_plan_inconnu_refuse():
    with pytest.raises(ValueError):
        cles.faire_cle("platine", "2027-09-03", "client@exemple.com", SECRET_HISTORIQUE)


def test_prolongation_cumule_les_mois_payes_davance():
    aujourdhui = date(2026, 9, 3)
    # Abonnement encore valide : le mois payé s'ajoute à la fin en cours.
    assert cles.prolonger("2026-11-03", 1, aujourdhui) == "2026-12-03"
    # Abonnement déjà expiré : on repart d'aujourd'hui, pas du passé.
    assert cles.prolonger("2026-01-03", 1, aujourdhui) == "2026-10-03"
    # Aucun historique : un mois à partir d'aujourd'hui.
    assert cles.prolonger(None, 1, aujourdhui) == "2026-10-03"
    # Offre groupée : douze mois.
    assert cles.prolonger(None, 12, aujourdhui) == "2027-09-03"


def test_prolongation_gere_les_fins_de_mois():
    assert cles.prolonger(None, 1, date(2026, 1, 31)) == "2026-02-28"
    assert cles.prolonger(None, 1, date(2028, 1, 31)) == "2028-02-29"  # année bissextile
    assert cles.prolonger(None, 12, date(2026, 12, 31)) == "2027-12-31"
