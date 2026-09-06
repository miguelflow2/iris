"""Import des identifiants du navigateur dans le coffre d'IRIS.

Aucun de ces tests ne touche un vrai navigateur, un vrai mot de passe, ni DPAPI. Le dechiffrement
et le systeme sont injectes. Ce qu'ils gardent, c'est la seule chose qui compte vraiment : qu'un
mot de passe ne sorte JAMAIS en clair de ce module, par aucun chemin.
"""
from __future__ import annotations

import logging

from iris import identifiants_navigateur as idn


# Un faux dechiffreur AES-GCM : on n'a besoin ni de cle reelle, ni de cryptography, ni de Windows.
def _faux_aes(cle, nonce, corps):
    return corps  # dans les tests, le « chiffre » est deja le clair


def _valeur_v10(clair: bytes) -> bytes:
    # v10 + nonce (12) + corps. Notre faux AES rend le corps tel quel.
    return b"v10" + b"0" * 12 + clair


class FauxCoffre:
    def __init__(self):
        self.sites = {}

    def set_site(self, nom, utilisateur, mot_de_passe):
        self.sites[nom] = {"utilisateur": utilisateur, "mot_de_passe": mot_de_passe}


# --------------------------------------------------------------------------- le secret ne fuit pas
def test_le_repr_masque_le_mot_de_passe():
    """Un log ou un traceback qui afficherait un Identifiant ne doit jamais montrer le secret."""
    ident = idn.Identifiant(domaine="paypal.com", utilisateur="miguel", _secret="Soleil2026")
    assert "Soleil2026" not in repr(ident)
    assert "***" in repr(ident)


def test_en_dict_ne_contient_jamais_le_secret():
    ident = idn.Identifiant(domaine="netlify.com", utilisateur="miguel@exemple.com", _secret="motdepasse")
    d = ident.en_dict()
    assert "motdepasse" not in str(d)
    assert d == {"domaine": "netlify.com", "utilisateur": "miguel@exemple.com"}


def test_sites_pour_ne_rend_aucun_secret(monkeypatch):
    faux = [idn.Identifiant("omnivox.ca", "1234567", "MonNip"), idn.Identifiant("paypal.com", "miguel", "Secret")]
    monkeypatch.setattr(idn, "_tous", lambda **_: faux)
    resultats = idn.sites_pour("omnivox")
    assert resultats == [{"domaine": "omnivox.ca", "utilisateur": "1234567"}]
    assert "MonNip" not in str(resultats)


def test_le_message_dimport_ne_contient_aucun_secret(monkeypatch):
    faux = [idn.Identifiant("paypal.com", "miguel", "Soleil2026")]
    monkeypatch.setattr(idn, "_tous", lambda **_: faux)
    coffre = FauxCoffre()
    resultat = idn.importer_dans_le_coffre("paypal", coffre)
    assert "Soleil2026" not in str(resultat), "le secret ne doit jamais reparaitre dans le retour"
    assert resultat["importes"] == 1
    assert "paypal.com" in resultat["sites"]


# --------------------------------------------------------------------------- l'import fait le bon travail
def test_limport_depose_le_secret_dans_le_coffre(monkeypatch):
    """C'est la seule sortie legitime du secret : vers le coffre, directement."""
    faux = [idn.Identifiant("paypal.com", "miguel", "Soleil2026")]
    monkeypatch.setattr(idn, "_tous", lambda **_: faux)
    coffre = FauxCoffre()
    idn.importer_dans_le_coffre("paypal", coffre)
    assert coffre.sites["paypal.com"] == {"utilisateur": "miguel", "mot_de_passe": "Soleil2026"}


def test_seuls_les_sites_demandes_sont_importes(monkeypatch):
    faux = [
        idn.Identifiant("paypal.com", "miguel", "a"),
        idn.Identifiant("omnivox.ca", "1234", "b"),
        idn.Identifiant("netlify.com", "miguel", "c"),
    ]
    monkeypatch.setattr(idn, "_tous", lambda **_: faux)
    coffre = FauxCoffre()
    idn.importer_dans_le_coffre("netlify", coffre)
    assert set(coffre.sites) == {"netlify.com"}, "on n'importe pas tout le trousseau pour une seule demande"


def test_un_terme_vide_nimporte_rien(monkeypatch):
    monkeypatch.setattr(idn, "_tous", lambda **_: [idn.Identifiant("x.com", "u", "p")])
    coffre = FauxCoffre()
    assert idn.importer_dans_le_coffre("", coffre)["importes"] == 0
    assert coffre.sites == {}


def test_aucun_identifiant_ne_donne_un_message_clair(monkeypatch):
    monkeypatch.setattr(idn, "_tous", lambda **_: [])
    coffre = FauxCoffre()
    resultat = idn.importer_dans_le_coffre("banque-inconnue", coffre)
    assert resultat["importes"] == 0
    assert "banque-inconnue" in resultat["message"]


# --------------------------------------------------------------------------- le dechiffrement, structurellement
def test_le_format_v10_passe_par_laes(monkeypatch):
    clair = idn._dechiffrer_valeur(_valeur_v10(b"motdepasse"), cle_aes=b"0" * 32, aes_gcm=_faux_aes)
    assert clair == "motdepasse"


def test_lancien_format_passe_par_dpapi():
    clair = idn._dechiffrer_valeur(b"ancien-blob", cle_aes=None, dpapi=lambda b: b"secret-dpapi")
    assert clair == "secret-dpapi"


def test_une_valeur_vide_ne_casse_rien():
    assert idn._dechiffrer_valeur(b"", cle_aes=b"0" * 32, aes_gcm=_faux_aes) == ""


def test_un_dpapi_qui_echoue_ne_leve_pas():
    """Un mot de passe chiffre sous un AUTRE compte Windows doit etre saute, pas faire tout planter."""
    def refuse(_):
        raise OSError("autre compte")

    assert idn._dechiffrer_valeur(b"blob", cle_aes=None, dpapi=refuse) == ""


def test_le_v10_sans_cle_est_saute():
    assert idn._dechiffrer_valeur(_valeur_v10(b"x"), cle_aes=None, aes_gcm=_faux_aes) == ""


# --------------------------------------------------------------------------- aucune fuite dans les journaux
def test_rien_ne_secrit_dans_les_journaux(monkeypatch, caplog):
    faux = [idn.Identifiant("paypal.com", "miguel", "TopSecret123")]
    monkeypatch.setattr(idn, "_tous", lambda **_: faux)
    coffre = FauxCoffre()
    with caplog.at_level(logging.DEBUG, logger="iris.identifiants"):
        idn.importer_dans_le_coffre("paypal", coffre)
    assert "TopSecret123" not in caplog.text, "un secret dans un journal est un secret qui fuit"


# --------------------------------------------------------------------------- reellement branche
def test_les_outils_sont_offerts_au_modele():
    """Deux fois le 5 septembre 2026, un module teste est reste inutilisable faute d'etre branche.
    Ici on verifie que ce n'est pas le cas."""
    from types import SimpleNamespace

    from iris.tools import tool_specs

    noms = {s.name for s in tool_specs(SimpleNamespace(create_task=None))}
    assert {"retrouver_site", "importer_identifiants"} <= noms


def test_le_coffre_est_dans_le_contexte(app):
    """Sans le coffre dans le contexte, importer_identifiants leverait au lieu d'importer."""
    ctx = app.state.ctx
    assert ctx.chat.secrets is not None
