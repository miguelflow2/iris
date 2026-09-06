"""Import des identifiants du navigateur dans le coffre d'IRIS.

Aucun de ces tests ne touche un vrai navigateur, un vrai mot de passe, ni DPAPI. Le dechiffrement,
le systeme et les entrees sont injectes. Ce qu'ils gardent : (1) un mot de passe ne sort JAMAIS en
clair, (2) ce qui est montre a l'utilisateur est EXACTEMENT ce qui est importe, (3) un fichier
abime ne fait rien planter. Les deux derniers points ont ete trouves par une relecture adverse le
5 septembre 2026.
"""
from __future__ import annotations

import base64
import logging

import pytest

from iris import identifiants_navigateur as idn


def _faux_aes(cle, nonce, corps):
    return corps  # dans les tests, le « chiffre » est deja le clair


def _valeur_v10(clair: bytes) -> bytes:
    return b"v10" + b"0" * 12 + clair


class FauxCoffre:
    def __init__(self):
        self.sites = {}

    def set_site(self, nom, utilisateur, mot_de_passe):
        self.sites[nom] = {"utilisateur": utilisateur, "mot_de_passe": mot_de_passe}


# --------------------------------------------------------------------------- le secret ne fuit pas
def test_le_repr_masque_le_mot_de_passe():
    ident = idn.Identifiant(domaine="paypal.com", utilisateur="miguel", _secret="Soleil2026")
    assert "Soleil2026" not in repr(ident)
    assert "***" in repr(ident)


def test_en_dict_ne_contient_jamais_le_secret():
    ident = idn.Identifiant(domaine="netlify.com", utilisateur="miguel@exemple.com", _secret="motdepasse")
    assert "motdepasse" not in str(ident.en_dict())
    assert ident.en_dict() == {"domaine": "netlify.com", "utilisateur": "miguel@exemple.com"}


def test_le_message_dimport_ne_contient_aucun_secret(monkeypatch):
    monkeypatch.setattr(idn, "_identifiants", lambda *a, **k: [idn.Identifiant("paypal.com", "miguel", "Soleil2026")])
    resultat = idn.importer_dans_le_coffre("paypal", FauxCoffre())
    assert "Soleil2026" not in str(resultat)
    assert resultat["importes"] == 1 and "paypal.com" in resultat["sites"]


def test_rien_ne_secrit_dans_les_journaux(monkeypatch, caplog):
    class CoffreQuiRale:
        def set_site(self, *a):
            raise RuntimeError("le coffre a un souci")

    monkeypatch.setattr(idn, "_identifiants", lambda *a, **k: [idn.Identifiant("paypal.com", "miguel", "TopSecret123")])
    with caplog.at_level(logging.DEBUG, logger="iris.identifiants"):
        idn.importer_dans_le_coffre("paypal", CoffreQuiRale())
    assert "TopSecret123" not in caplog.text, "un secret dans un journal est un secret qui fuit"


# --------------------------------------------------------------------------- montre == importe (adversarial)
def test_la_confirmation_nomme_exactement_ce_qui_sera_importe(monkeypatch):
    """Defaut trouve le 5 septembre 2026 : la confirmation nommait 12 sites, l'import en ecrivait
    davantage. noms_correspondants et importer partent maintenant de la MEME correspondance."""
    entrees = [{"domaine": f"site{i}.com", "utilisateur": "miguel"} for i in range(20)]
    monkeypatch.setattr(idn, "_entrees", lambda motif=None: [e for e in entrees if idn._correspond(e["domaine"], motif)])
    # meme motif, meme filtrage : la liste montree contient tout ce qui matche, sans plafond cache.
    montres = idn.noms_correspondants("site1.com")
    assert montres == [{"domaine": "site1.com", "utilisateur": "miguel"}]


def test_paypal_nattrape_ni_sous_chaine_ni_utilisateur():
    """« paypal » ne doit ramener ni mypaypal-arnaque.com (sous-chaine) ni un compte dont seul
    l'utilisateur contient le mot."""
    assert idn._correspond("paypal.com", "paypal")
    assert idn._correspond("www.paypal.com".removeprefix("www."), "paypal")
    assert not idn._correspond("mypaypal-arnaque.com", "paypal"), "sous-chaine refusee"
    assert not idn._correspond("forum-obscur.net", "paypal"), "l'utilisateur ne compte pas ici"


def test_le_domaine_complet_et_letiquette_matchent():
    assert idn._correspond("app.netlify.com", "netlify"), "etiquette de domaine"
    assert idn._correspond("app.netlify.com", "app.netlify.com"), "domaine complet"
    assert idn._correspond("cegeptr.omnivox.ca", "omnivox")


# --------------------------------------------------------------------------- l'import fait le bon travail
def test_limport_depose_le_secret_dans_le_coffre(monkeypatch):
    monkeypatch.setattr(idn, "_identifiants", lambda *a, **k: [idn.Identifiant("paypal.com", "miguel", "Soleil2026")])
    coffre = FauxCoffre()
    idn.importer_dans_le_coffre("paypal", coffre)
    assert coffre.sites["paypal.com"] == {"utilisateur": "miguel", "mot_de_passe": "Soleil2026"}


def test_un_terme_vide_nimporte_rien(monkeypatch):
    monkeypatch.setattr(idn, "_identifiants", lambda *a, **k: [idn.Identifiant("x.com", "u", "p")])
    coffre = FauxCoffre()
    assert idn.importer_dans_le_coffre("", coffre)["importes"] == 0
    assert coffre.sites == {}


def test_aucun_identifiant_donne_un_message_clair(monkeypatch):
    monkeypatch.setattr(idn, "_identifiants", lambda *a, **k: [])
    resultat = idn.importer_dans_le_coffre("banque-inconnue", FauxCoffre())
    assert resultat["importes"] == 0 and "banque-inconnue" in resultat["message"]


# --------------------------------------------------------------------------- le dechiffrement
def test_le_format_v10_passe_par_laes():
    assert idn._dechiffrer_valeur(_valeur_v10(b"motdepasse"), cle_aes=b"0" * 32, aes_gcm=_faux_aes) == "motdepasse"


def test_lancien_format_passe_par_dpapi():
    assert idn._dechiffrer_valeur(b"blob", cle_aes=None, dpapi=lambda b: b"secret-dpapi") == "secret-dpapi"


def test_un_dpapi_qui_echoue_ne_leve_pas():
    def refuse(_):
        raise OSError("autre compte")

    assert idn._dechiffrer_valeur(b"blob", cle_aes=None, dpapi=refuse) == ""


def test_le_v10_sans_cle_est_saute():
    assert idn._dechiffrer_valeur(_valeur_v10(b"x"), cle_aes=None, aes_gcm=_faux_aes) == ""


# --------------------------------------------------------------------------- robustesse (adversarial)
def test_un_local_state_base64_invalide_ne_plante_pas(tmp_path):
    """Defaut trouve le 5 septembre 2026 : un encrypted_key base64 invalide levait binascii.Error
    (une ValueError, pas une OSError) qui traversait tout et cassait l'import de TOUS les sites."""
    user_data = tmp_path
    (user_data / "Local State").write_text(
        '{"os_crypt": {"encrypted_key": "ceci n est pas du base64 !!!"}}', encoding="utf-8")
    assert idn._cle_aes(user_data) is None, "un fichier abime doit etre saute, pas faire lever"


def test_un_local_state_sans_cle_est_saute(tmp_path):
    (tmp_path / "Local State").write_text('{"autre": 1}', encoding="utf-8")
    assert idn._cle_aes(tmp_path) is None


def test_un_local_state_json_casse_est_saute(tmp_path):
    (tmp_path / "Local State").write_text("pas du json", encoding="utf-8")
    assert idn._cle_aes(tmp_path) is None


def test_un_encrypted_key_sans_etiquette_dpapi_est_saute(tmp_path):
    faux = base64.b64encode(b"pas-DPAPI-devant").decode()
    (tmp_path / "Local State").write_text(f'{{"os_crypt": {{"encrypted_key": "{faux}"}}}}', encoding="utf-8")
    assert idn._cle_aes(tmp_path) is None


# --------------------------------------------------------------------------- reellement branche
def test_les_outils_sont_offerts_au_modele():
    from types import SimpleNamespace

    from iris.tools import tool_specs

    noms = {s.name for s in tool_specs(SimpleNamespace(create_task=None))}
    assert {"retrouver_site", "importer_identifiants"} <= noms


def test_le_coffre_est_dans_le_contexte(app):
    assert app.state.ctx.chat.secrets is not None
