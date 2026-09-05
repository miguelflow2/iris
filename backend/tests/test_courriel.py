"""Envoi de courriels : c'est la seule action d'IRIS qu'on ne peut pas défaire.

Ces tests protègent une promesse faite au propriétaire : aucun message ne part sans un accord
explicite, donné juste avant l'envoi, pour ce message-là. Ils vérifient aussi qu'un échec est dit
au lieu d'être avalé, et qu'aucun identifiant ne fuit dans un message d'erreur.

Aucun test ne touche le réseau : la classe SMTP est injectée.
"""
from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from typing import Any

import pytest

from iris.courriel import (
    DUREE_ACCORD,
    MAX_DESTINATAIRES,
    AdresseInvalide,
    Autorisation,
    AutorisationInvalide,
    Brouillon,
    CourrielNonConfigure,
    EnvoiEchoue,
    ErreurCourriel,
    ModeLocalActif,
    Postier,
    ReglagesCourriel,
)
from iris.security.crypto import Crypto, load_master_key
from iris.security.secrets import SecretStore

ADRESSE = "iris.vela@gmail.com"
MOTDEPASSE_AFFICHE = "abcd efgh ijkl mnop"  # tel que Google le montre, en quatre groupes de quatre
MOTDEPASSE = "abcdefghijklmnop"


# --------------------------------------------------------------------------- doublures
class Journal:
    """Ce que le faux serveur a réellement reçu. Un journal vide = rien n'est parti."""

    def __init__(self) -> None:
        self.connexions: list[tuple[str, int, bool]] = []
        self.gestes: list[str] = []
        self.logins: list[tuple[str, str]] = []
        self.envois: list[Any] = []


class FauxSMTP:
    """Faux serveur SMTP : aucun octet ne quitte la machine pendant les tests."""

    def __init__(self, journal: Journal, echec_login: Exception | None = None, refuses: dict | None = None):
        self.journal = journal
        self.echec_login = echec_login
        self.refuses = refuses or {}

    def __enter__(self) -> "FauxSMTP":
        return self

    def __exit__(self, *_exc) -> bool:
        self.journal.gestes.append("quit")
        return False

    def starttls(self) -> None:
        self.journal.gestes.append("starttls")

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        self.journal.gestes.append("login")
        self.journal.logins.append((utilisateur, mot_de_passe))
        if self.echec_login:
            raise self.echec_login

    def send_message(self, message) -> dict:
        self.journal.gestes.append("send_message")
        self.journal.envois.append(message)
        return dict(self.refuses)


def fabrique(journal: Journal, echec_connexion: Exception | None = None, **pannes) -> Any:
    def ouvrir(hote: str, port: int, ssl: bool):
        journal.connexions.append((hote, port, ssl))
        if echec_connexion:
            raise echec_connexion
        return FauxSMTP(journal, **pannes)

    return ouvrir


@dataclass
class FauxUtilisateur:
    """Les seuls réglages que le postier lit. Reproduit ce que config.py exposera un jour."""

    local_only: bool = False
    courriel: Any = None


class FauxSettings:
    def __init__(self, **kwargs):
        self.user = FauxUtilisateur(**kwargs)


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def coffre(tmp_path) -> SecretStore:
    cle, _source = load_master_key(tmp_path, use_keyring=False)
    return SecretStore(Crypto(cle), tmp_path, use_keyring=False)


@pytest.fixture()
def journal() -> Journal:
    return Journal()


@pytest.fixture()
def postier(coffre, journal) -> Postier:
    p = Postier(FauxSettings(), coffre, fabrique_smtp=fabrique(journal))
    p.configurer(ADRESSE, MOTDEPASSE_AFFICHE)
    return p


def accorder(postier: Postier, brouillon: Brouillon, reponse: bool = True) -> Autorisation | None:
    """Passe par le seul chemin qui produit une autorisation : la confirmation de l'utilisateur."""

    async def confirmer(_titre: str, _detail: str) -> bool:
        return reponse

    return asyncio.run(postier.demander_accord(brouillon, confirmer))


# --------------------------------------------------------------------------- la garde d'envoi
def test_un_courriel_ne_part_jamais_sans_autorisation(postier: Postier, journal: Journal):
    """Si envoyer() acceptait autre chose qu'une Autorisation, un appelant distrait enverrait un message."""
    brouillon = postier.preparer("ami@exemple.com", "Bonjour", "Un mot rapide.")
    with pytest.raises(AutorisationInvalide):
        postier.envoyer(brouillon)  # type: ignore[arg-type]
    with pytest.raises(AutorisationInvalide):
        postier.envoyer(True)  # type: ignore[arg-type]
    assert journal.connexions == [] and journal.envois == [], "aucune connexion ne doit avoir été ouverte"


def test_une_autorisation_ne_se_fabrique_pas_a_la_main(postier: Postier):
    """Le sceau privé est ce qui distingue « confirmé » de « quelqu'un a mis True quelque part »."""
    brouillon = postier.preparer("ami@exemple.com", "Bonjour", "Un mot rapide.")
    with pytest.raises(AutorisationInvalide):
        Autorisation(brouillon, object())
    with pytest.raises(TypeError):
        Autorisation(brouillon)  # type: ignore[call-arg]


def test_un_refus_de_confirmation_nenvoie_rien(postier: Postier, journal: Journal):
    """Un non, un silence ou un délai dépassé donnent tous False : rien ne doit partir."""
    brouillon = postier.preparer("ami@exemple.com", "Bonjour", "Un mot rapide.")
    assert accorder(postier, brouillon, reponse=False) is None

    async def confirmer_non(_t, _d):
        return False

    resultat = asyncio.run(postier.envoyer_apres_accord("ami@exemple.com", "Bonjour", "Un mot.", confirmer_non))
    assert resultat["envoye"] is False and resultat["ok"] is False
    assert "rien envoyé" in resultat["message"]
    assert journal.envois == []


def test_la_confirmation_montre_le_message_entier(postier: Postier):
    """On ne confirme pas un résumé : le destinataire, l'objet et le corps doivent être sous les yeux."""
    vus: dict = {}

    async def confirmer(titre: str, detail: str) -> bool:
        vus["titre"], vus["detail"] = titre, detail
        return False

    asyncio.run(postier.demander_accord(postier.preparer("ami@exemple.com", "Rendez-vous", "Mardi 14 h."), confirmer))
    assert "ami@exemple.com" in vus["titre"]
    assert "Rendez-vous" in vus["detail"] and "Mardi 14 h." in vus["detail"]


def test_un_accord_ne_sert_quune_fois(postier: Postier, journal: Journal):
    """Un accord réutilisable ferait d'un simple « réessaie » un doublon chez le destinataire."""
    accord = accorder(postier, postier.preparer("ami@exemple.com", "Bonjour", "Un mot."))
    postier.envoyer(accord)
    with pytest.raises(AutorisationInvalide, match="déjà servi"):
        postier.envoyer(accord)
    assert len(journal.envois) == 1


def test_un_accord_perime_est_refuse(postier: Postier, journal: Journal):
    """Un oui d'il y a une heure ne dit rien de l'intention d'aujourd'hui."""
    accord = accorder(postier, postier.preparer("ami@exemple.com", "Bonjour", "Un mot."))
    accord._accorde_a -= DUREE_ACCORD + 1
    with pytest.raises(AutorisationInvalide, match="cinq minutes"):
        postier.envoyer(accord)
    assert journal.envois == []


def test_un_accord_ne_couvre_pas_un_message_modifie(postier: Postier, journal: Journal):
    """L'accord porte sur un texte précis : modifié après coup, il n'est plus celui qui a été relu."""
    brouillon = postier.preparer("ami@exemple.com", "Bonjour", "Un mot.")
    accord = accorder(postier, brouillon)
    object.__setattr__(brouillon, "corps", "Tout autre chose.")
    with pytest.raises(AutorisationInvalide, match="changé"):
        postier.envoyer(accord)
    assert journal.envois == []


# --------------------------------------------------------------------------- brouillon
def test_le_brouillon_ne_declenche_aucun_envoi(postier: Postier, journal: Journal):
    """IRIS doit pouvoir relire un message à voix haute sans qu'il parte pendant la lecture."""
    brouillon = postier.preparer("ami@exemple.com", "Rendez-vous", "On se voit mardi ?")
    assert journal.connexions == [] and journal.envois == []
    assert "Rendez-vous" in brouillon.apercu() and "On se voit mardi ?" in brouillon.apercu()
    assert brouillon.pour_la_voix().startswith("Courriel à ami@exemple.com")
    assert "Subject: Rendez-vous" in brouillon.eml()


def test_le_brouillon_relu_est_exactement_celui_qui_part(postier: Postier, journal: Journal):
    """Signature comprise : ce qui est lu à voix haute doit être ce que le destinataire recevra."""
    postier.settings.user.courriel = ReglagesCourriel(signature="— Miguel, VELA")
    brouillon = postier.preparer("ami@exemple.com", "Bonjour", "Un mot.")
    assert "— Miguel, VELA" in brouillon.apercu()
    postier.envoyer(accorder(postier, brouillon))
    assert journal.envois[0].get_content().strip() == brouillon.corps.strip()


# --------------------------------------------------------------------------- adresses
@pytest.mark.parametrize("mauvaise", ["", "   ", "bonjour", "a@b", "@gmail.com", "a b@exemple.com", "ami@exemple"])
def test_une_adresse_invalide_est_refusee(postier: Postier, journal: Journal, mauvaise):
    """Une adresse acceptée à tort, c'est un message privé envoyé à un inconnu."""
    with pytest.raises(AdresseInvalide):
        postier.preparer(mauvaise, "Objet", "Corps")
    assert journal.envois == []


def test_un_saut_de_ligne_dans_le_sujet_ne_peut_pas_ajouter_den_tete(postier: Postier):
    """Un « \\nBcc: » dans l'objet enverrait une copie cachée à l'insu de l'utilisateur."""
    brouillon = postier.preparer("ami@exemple.com", "Bonjour\nBcc: espion@ailleurs.com", "Un mot.")
    assert "\n" not in brouillon.sujet
    assert "Bcc" not in brouillon.message().keys()


def test_les_destinataires_multiples_et_la_copie_sont_respectes(postier: Postier, journal: Journal):
    brouillon = postier.preparer(
        "un@exemple.com, deux@exemple.com", "Réunion", "À demain.", cc=["chef@exemple.com", "un@exemple.com"]
    )
    assert brouillon.destinataires == ("un@exemple.com", "deux@exemple.com")
    assert brouillon.cc == ("chef@exemple.com",), "un destinataire déjà en À ne doit pas être doublé en copie"
    postier.envoyer(accorder(postier, brouillon))
    envoye = journal.envois[0]
    assert envoye["To"] == "un@exemple.com, deux@exemple.com" and envoye["Cc"] == "chef@exemple.com"


def test_une_liste_de_diffusion_improvisee_est_refusee(postier: Postier):
    """Garde-fou : un modèle qui hallucine trente adresses ne doit pas faire d'envoi de masse."""
    trop = [f"personne{i}@exemple.com" for i in range(MAX_DESTINATAIRES + 1)]
    with pytest.raises(AdresseInvalide, match="maximum"):
        postier.preparer(trop, "Objet", "Corps")


@pytest.mark.parametrize("vide", ["", "   \n  "])
def test_un_message_vide_nest_pas_envoye(postier: Postier, vide):
    with pytest.raises(ErreurCourriel):
        postier.preparer("ami@exemple.com", "Objet", vide)
    with pytest.raises(ErreurCourriel):
        postier.preparer("ami@exemple.com", vide, "Corps")


# --------------------------------------------------------------------------- envoi réussi
def test_un_envoi_reussi_chiffre_puis_sidentifie_puis_envoie(postier: Postier, journal: Journal):
    """L'ordre compte : s'identifier avant STARTTLS enverrait le mot de passe en clair sur le réseau."""
    resultat = postier.envoyer(accorder(postier, postier.preparer("ami@exemple.com", "Bonjour", "Un mot.")))
    assert journal.connexions == [("smtp.gmail.com", 587, False)]
    assert journal.gestes == ["starttls", "login", "send_message", "quit"]
    assert resultat["ok"] is True and resultat["destinataires"] == ["ami@exemple.com"]
    assert "envoyé à ami@exemple.com" in resultat["message"]


def test_les_espaces_du_mot_de_passe_dapplication_sont_ignores(postier: Postier, journal: Journal):
    """Google affiche le mot de passe en quatre groupes ; collé avec ses espaces, il est refusé."""
    postier.envoyer(accorder(postier, postier.preparer("ami@exemple.com", "Bonjour", "Un mot.")))
    assert journal.logins == [(ADRESSE, MOTDEPASSE)]


def test_le_port_465_nutilise_pas_starttls(coffre, journal: Journal):
    """Sur 465 le canal est déjà chiffré : y ajouter STARTTLS fait échouer la connexion."""
    reglages = FauxSettings(courriel=ReglagesCourriel(smtp_hote="smtp.gmail.com", smtp_port=465))
    p = Postier(reglages, coffre, fabrique_smtp=fabrique(journal))
    p.configurer(ADRESSE, MOTDEPASSE)
    p.envoyer(accorder(p, p.preparer("ami@exemple.com", "Bonjour", "Un mot.")))
    assert journal.connexions == [("smtp.gmail.com", 465, True)]
    assert "starttls" not in journal.gestes


def test_la_connexion_se_teste_sans_envoyer_de_message(postier: Postier, journal: Journal):
    """Vérifier un mot de passe d'application ne doit déranger personne dans sa boîte de réception."""
    assert postier.tester_connexion()["ok"] is True
    assert "login" in journal.gestes and journal.envois == []


def test_un_destinataire_refuse_par_le_serveur_est_dit(coffre, journal: Journal):
    """Dire « c'est envoyé » alors qu'une adresse a été rejetée est un mensonge par omission."""
    ouvrir = fabrique(journal, refuses={"faux@exemple.com": (550, b"5.1.1 No such user")})
    p = Postier(FauxSettings(), coffre, fabrique_smtp=ouvrir)
    p.configurer(ADRESSE, MOTDEPASSE)
    resultat = p.envoyer(accorder(p, p.preparer("bon@exemple.com, faux@exemple.com", "Objet", "Corps")))
    assert resultat["ok"] is False and resultat["envoye"] is True
    assert resultat["destinataires"] == ["bon@exemple.com"]
    assert "faux@exemple.com" in resultat["message"] and "n'ont rien reçu" in resultat["message"]


# --------------------------------------------------------------------------- échecs SMTP
def _echec(coffre, journal, erreur, *, au_login=True) -> Postier:
    pannes = {"echec_login": erreur} if au_login else {}
    ouvrir = fabrique(journal, echec_connexion=None if au_login else erreur, **pannes)
    p = Postier(FauxSettings(), coffre, fabrique_smtp=ouvrir)
    p.configurer(ADRESSE, MOTDEPASSE_AFFICHE)
    return p


def test_le_mot_de_passe_napparait_jamais_dans_le_message_derreur(coffre, journal: Journal):
    """Un message d'erreur finit recopié dans un rapport de bogue, ou lu à voix haute."""
    reponse = f"5.7.8 Username and Password not accepted (mdp={MOTDEPASSE})".encode()
    p = _echec(coffre, journal, smtplib.SMTPAuthenticationError(535, reponse))
    with pytest.raises(EnvoiEchoue) as capture:
        p.envoyer(accorder(p, p.preparer("ami@exemple.com", "Objet", "Corps")))
    texte = str(capture.value)
    assert MOTDEPASSE not in texte and MOTDEPASSE_AFFICHE not in texte
    assert "•••" in texte, "le secret doit être remplacé, pas simplement absent par chance"


def test_un_mot_de_passe_refuse_explique_quoi_faire(coffre, journal: Journal):
    """« Authentication failed » ne dit rien à Miguel ; la marche à suivre, si."""
    p = _echec(coffre, journal, smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted"))
    with pytest.raises(EnvoiEchoue) as capture:
        p.envoyer(accorder(p, p.preparer("ami@exemple.com", "Objet", "Corps")))
    texte = str(capture.value)
    assert "mot de passe d'application" in texte
    assert "deux étapes" in texte and "apppasswords" in texte
    assert "révoqué" in texte, "changer son mot de passe Google casse l'envoi : il faut le dire"


def test_un_port_bloque_explique_quoi_faire(coffre, journal: Journal):
    """Pare-feu, antivirus, réseau d'hôtel : la même erreur, trois causes, une seule phrase utile."""
    p = _echec(coffre, journal, ConnectionRefusedError("[WinError 10061]"), au_login=False)
    with pytest.raises(EnvoiEchoue) as capture:
        p.envoyer(accorder(p, p.preparer("ami@exemple.com", "Objet", "Corps")))
    texte = str(capture.value)
    assert "pare-feu" in texte and "465" in texte and "587" in texte
    assert "Rien n'a été envoyé" in texte


def test_un_quota_depasse_est_nomme(coffre, journal: Journal):
    p = _echec(coffre, journal, smtplib.SMTPDataError(550, b"5.4.5 Daily user sending quota exceeded"))
    with pytest.raises(EnvoiEchoue, match="quota"):
        p.envoyer(accorder(p, p.preparer("ami@exemple.com", "Objet", "Corps")))


def test_un_echec_ne_laisse_pas_croire_que_le_message_est_parti(coffre, journal: Journal):
    """Le contraire du Facteur du serveur de licences : ici, un échec doit remonter, jamais être avalé."""
    p = _echec(coffre, journal, smtplib.SMTPServerDisconnected("connexion perdue"))
    accord = accorder(p, p.preparer("ami@exemple.com", "Objet", "Corps"))
    with pytest.raises(EnvoiEchoue):
        p.envoyer(accord)
    assert journal.envois == []
    # L'accord est consommé même en cas d'échec : on ne sait pas si le serveur avait déjà accepté
    # le message, donc un nouvel envoi se redemande.
    with pytest.raises(AutorisationInvalide):
        p.envoyer(accord)


# --------------------------------------------------------------------------- configuration
def test_sans_compte_configure_iris_explique_la_marche_a_suivre(coffre, journal: Journal):
    p = Postier(FauxSettings(), coffre, fabrique_smtp=fabrique(journal))
    assert p.configure is False
    with pytest.raises(CourrielNonConfigure) as capture:
        p.preparer("ami@exemple.com", "Objet", "Corps")
    texte = str(capture.value)
    assert "apppasswords" in texte and "deux étapes" in texte
    assert journal.connexions == []


def test_le_mot_de_passe_nest_jamais_ecrit_dans_les_reglages(tmp_path, coffre, journal: Journal):
    """Le secret vit dans le coffre. settings.json est lisible par n'importe quel programme."""
    from iris.config import Settings

    reglages = Settings(tmp_path / "iris-data")
    p = Postier(reglages, coffre, fabrique_smtp=fabrique(journal))
    etat = p.configurer(ADRESSE, MOTDEPASSE_AFFICHE)
    brut = reglages.settings_path.read_text(encoding="utf-8")
    assert MOTDEPASSE not in brut and MOTDEPASSE_AFFICHE not in brut
    assert MOTDEPASSE not in str(etat) and etat["adresse"] == ADRESSE
    assert etat["secret"] and etat["secret"] != MOTDEPASSE, "l'interface n'affiche qu'une empreinte"
    assert p.etat()["smtp_hote"] == "smtp.gmail.com", "le serveur se déduit du domaine"


def test_un_mot_de_passe_de_compte_google_est_signale(postier: Postier):
    """Cause d'échec numéro un : coller le mot de passe du compte au lieu du mot de passe d'application."""
    etat = postier.configurer(ADRESSE, "monVraiMotDePasseGoogle")
    assert "16 lettres" in etat["avertissement"]


def test_oublier_le_compte_le_retire_du_coffre(postier: Postier, coffre):
    postier.oublier()
    assert postier.configure is False and coffre.get_site("courriel") is None


def test_le_mode_local_empeche_tout_envoi(coffre, journal: Journal):
    """« Rien ne quitte l'ordinateur » ne souffre pas d'exception, courriel compris."""
    p = Postier(FauxSettings(local_only=True), coffre, fabrique_smtp=fabrique(journal))
    p.secrets.set_site("courriel", ADRESSE, MOTDEPASSE)
    assert p.configure is False
    with pytest.raises(ModeLocalActif):
        p.preparer("ami@exemple.com", "Objet", "Corps")
    assert journal.connexions == []


# --------------------------------------------------------------------------- ce que l'etat revele
# Defaut trouve par une relecture adverse le 2026-09-05 : etat() renvoyait SecretStore.mask(), qui
# n'est pas une empreinte mais un EXTRAIT — quatre caracteres au debut, quatre a la fin. Sur un mot
# de passe court, choisi par la personne plutot que genere, c'est deja trop. Et la docstring
# promettait de ne jamais renvoyer le mot de passe.
def test_letat_ne_laisse_filtrer_aucun_caractere_du_secret(postier):
    import json

    postier.configurer("miguel@exemple.com", "SoleilDeMai2026")
    revele = json.dumps(postier.etat(), ensure_ascii=False)
    for morceau in ("Soleil", "2026", "SoleilDeMai", "Sole", "l2026"):
        assert morceau not in revele, "l'etat laisse filtrer : " + morceau
