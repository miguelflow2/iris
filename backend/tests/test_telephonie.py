"""Appels et SMS : un texto parti ne se rattrape pas, et il se paie à chaque envoi.

Ces tests protègent trois promesses faites au propriétaire. Rien ne part sans un accord explicite,
donné juste avant, pour CE message-là. Un service non configuré le dit en français au lieu de
planter. Et une erreur d'IRIS ne peut ni composer un numéro à péage, ni vider un crédit en boucle.

Aucun test ne touche le réseau : le client HTTP est injecté, et la voie par défaut n'en a même pas
besoin — un client qui explose si on l'appelle sert de détecteur.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import pytest

from iris.security.crypto import Crypto, load_master_key
from iris.security.secrets import SecretStore
from iris.telephonie import (
    DUREE_ACCORD,
    DUREE_BROUILLON,
    MAX_CARACTERES,
    MAX_ENVOIS_PAR_HEURE,
    Autorisation,
    AutorisationInvalide,
    Brouillon,
    EnvoiEchoue,
    ErreurTelephonie,
    LimiteAtteinte,
    ModeLocalActif,
    NumeroInvalide,
    NumeroSurtaxe,
    Telephoniste,
    TelephonieNonConfiguree,
    normaliser_numero,
)

NUMERO = "+18195242804"
SID = "AC" + "0123456789abcdef" * 2  # 34 caractères, comme un vrai Account SID
TOKEN = "f1e2d3c4b5a697887766554433221100"
EXPEDITEUR = "+15145550100"


# --------------------------------------------------------------------------- doublures
class FausseReponse:
    def __init__(self, statut: int, corps: dict):
        self.status_code = statut
        self._corps = corps

    def json(self) -> dict:
        return self._corps


class FauxHTTP:
    """Faux opérateur : aucun octet ne quitte la machine pendant les tests."""

    def __init__(self, statut: int = 201, corps: dict | None = None, erreur: Exception | None = None):
        self.statut = statut
        self.corps = corps if corps is not None else {"sid": "SM0000000000000000000000000000000", "status": "queued"}
        self.erreur = erreur
        self.appels: list[dict] = []

    def __call__(self, url: str, donnees: dict, auth: tuple[str, str], delai: int) -> FausseReponse:
        self.appels.append({"url": url, "donnees": donnees, "auth": auth, "delai": delai})
        if self.erreur:
            raise self.erreur
        return FausseReponse(self.statut, self.corps)


def reseau_interdit(*_a, **_k):
    """Sert de détecteur : la voie iPhone ne doit jamais ouvrir la moindre connexion."""
    raise AssertionError("la voie iPhone a tenté un appel réseau")


class Horloge:
    """Horloge pilotée : vérifier une limite horaire ne doit pas prendre une heure."""

    def __init__(self, depart: float = 10_000.0):
        self.t = depart

    def __call__(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


class FauxRegistre:
    def __init__(self) -> None:
        self.entrees: list[tuple[str, str, str]] = []

    def log(self, event_type: str, data_type: str | None = None, agent: str | None = None, detail: str = "") -> None:
        self.entrees.append((event_type, agent or "", detail))

    @property
    def evenements(self) -> list[str]:
        return [e[0] for e in self.entrees]


class FauxHub:
    def __init__(self) -> None:
        self.publications: list[tuple[str, dict]] = []

    def publish(self, type_: str, **donnees: Any) -> None:
        self.publications.append((type_, donnees))


@dataclass
class FauxUtilisateur:
    """Les seuls réglages que le téléphoniste lit. Reproduit ce que config.py exposera."""

    local_only: bool = False
    telephonie: Any = None


@dataclass
class ReglagesBruts:
    fournisseur: str = "iphone"
    numero_par_defaut: str = ""
    indicatif_pays: str = "+1"


class FauxSettings:
    def __init__(self, **kwargs):
        self.user = FauxUtilisateur(**kwargs)


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def coffre(tmp_path) -> SecretStore:
    cle, _source = load_master_key(tmp_path, use_keyring=False)
    return SecretStore(Crypto(cle), tmp_path, use_keyring=False)


@pytest.fixture()
def horloge() -> Horloge:
    return Horloge()


@pytest.fixture()
def registre() -> FauxRegistre:
    return FauxRegistre()


@pytest.fixture()
def iris(coffre, horloge, registre) -> Telephoniste:
    """La voie par défaut : brouillon sur le téléphone, zéro réseau, zéro dollar."""
    return Telephoniste(FauxSettings(), coffre, client_http=reseau_interdit, registre=registre, horloge=horloge)


def twilio(coffre, horloge, http: FauxHTTP, **reglages) -> Telephoniste:
    settings = FauxSettings(telephonie=ReglagesBruts(fournisseur="twilio", **reglages))
    t = Telephoniste(settings, coffre, client_http=http, horloge=horloge)
    coffre.set_site("telephonie", SID, TOKEN)
    coffre.set_site("telephonie-numero", EXPEDITEUR, "")
    return t


def accorder(iris: Telephoniste, brouillon: Brouillon, reponse: bool = True) -> Autorisation | None:
    """Passe par le seul chemin qui produit une autorisation : la confirmation de l'utilisateur."""

    async def confirmer(_titre: str, _detail: str) -> bool:
        return reponse

    return asyncio.run(iris.demander_accord(brouillon, confirmer))


# --------------------------------------------------------------------------- la serrure
def test_rien_ne_part_sans_autorisation(iris: Telephoniste):
    """Si executer() acceptait autre chose qu'une Autorisation, un appelant distrait ferait partir un texto."""
    brouillon = iris.preparer_sms("819 524-2804", "On se voit à 14 h ?")
    with pytest.raises(AutorisationInvalide):
        iris.executer(brouillon)  # type: ignore[arg-type]
    with pytest.raises(AutorisationInvalide):
        iris.executer(True)  # type: ignore[arg-type]
    assert iris.en_attente() == [], "aucun brouillon ne doit avoir été déposé"


def test_une_autorisation_ne_se_fabrique_pas_a_la_main(iris: Telephoniste):
    """Le sceau privé distingue « confirmé » de « quelqu'un a mis True quelque part »."""
    brouillon = iris.preparer_sms(NUMERO, "Un mot.")
    with pytest.raises(AutorisationInvalide):
        Autorisation(brouillon, object())
    with pytest.raises(TypeError):
        Autorisation(brouillon)  # type: ignore[call-arg]


def test_un_refus_de_confirmation_ne_fait_rien_partir(iris: Telephoniste, registre: FauxRegistre):
    """Un non, un silence ou un délai dépassé donnent tous False : rien ne doit partir."""
    assert accorder(iris, iris.preparer_sms(NUMERO, "Un mot."), reponse=False) is None

    async def confirmer_non(_t, _d):
        return False

    resultat = asyncio.run(iris.envoyer_sms_apres_accord(NUMERO, "Un mot.", confirmer_non))
    assert resultat["envoye"] is False and resultat["ok"] is False and resultat["en_attente"] is False
    assert "rien fait" in resultat["message"]
    assert iris.en_attente() == []
    assert registre.evenements == ["telephonie_refus", "telephonie_refus"], "un refus se consigne autant qu'un envoi"


def test_sans_moyen_de_confirmer_iris_ne_fait_rien(iris: Telephoniste):
    """Un appelant qui ne passe pas de fonction de confirmation ne doit pas obtenir un envoi muet."""
    brouillon = iris.preparer_sms(NUMERO, "Un mot.")
    with pytest.raises(AutorisationInvalide, match="ne fais rien"):
        asyncio.run(iris.demander_accord(brouillon, None))  # type: ignore[arg-type]
    with pytest.raises(AutorisationInvalide):
        asyncio.run(iris.envoyer_sms_apres_accord(NUMERO, "Un mot.", None))  # type: ignore[arg-type]
    assert iris.en_attente() == []


def test_la_confirmation_montre_le_texte_entier_et_le_numero(iris: Telephoniste):
    """On ne confirme pas un résumé : le numéro et le texte complet doivent être sous les yeux."""
    vus: dict = {}

    async def confirmer(titre: str, detail: str) -> bool:
        vus["titre"], vus["detail"] = titre, detail
        return False

    asyncio.run(iris.demander_accord(iris.preparer_sms("8195242804", "Rendez-vous mardi 14 h."), confirmer))
    assert "819 524-2804" in vus["titre"]
    assert "Rendez-vous mardi 14 h." in vus["detail"] and NUMERO in vus["detail"]


def test_un_accord_ne_sert_quune_fois(iris: Telephoniste):
    """Un accord réutilisable ferait d'un simple « réessaie » un doublon chez le destinataire."""
    accord = accorder(iris, iris.preparer_sms(NUMERO, "Un mot."))
    iris.executer(accord)
    with pytest.raises(AutorisationInvalide, match="déjà servi"):
        iris.executer(accord)
    assert len(iris.en_attente()) == 1


def test_un_accord_perime_est_refuse(iris: Telephoniste):
    """Un oui d'il y a une heure ne dit rien de l'intention d'aujourd'hui."""
    accord = accorder(iris, iris.preparer_sms(NUMERO, "Un mot."))
    accord._accorde_a -= DUREE_ACCORD + 1
    with pytest.raises(AutorisationInvalide, match="cinq minutes"):
        iris.executer(accord)
    assert iris.en_attente() == []


def test_un_accord_ne_couvre_pas_un_texte_modifie(iris: Telephoniste):
    """L'accord porte sur un texte précis : modifié après coup, ce n'est plus celui qui a été relu."""
    brouillon = iris.preparer_sms(NUMERO, "Un mot.")
    accord = accorder(iris, brouillon)
    object.__setattr__(brouillon, "texte", "Tout autre chose.")
    with pytest.raises(AutorisationInvalide, match="changé"):
        iris.executer(accord)
    assert iris.en_attente() == []


# --------------------------------------------------------------------------- voie iPhone
def test_le_brouillon_est_depose_sans_jamais_toucher_au_reseau(iris: Telephoniste):
    """Toute la garantie tient là : c'est iOS qui envoie, sur un geste de Miguel, pas IRIS."""
    resultat = iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "J'arrive.")))
    assert resultat["ok"] is True
    assert resultat["envoye"] is False, "dire « envoyé » alors que rien n'est parti serait un mensonge"
    assert resultat["en_attente"] is True and "touche Envoyer" in resultat["message"]
    attente = iris.en_attente()
    assert len(attente) == 1 and attente[0]["texte"] == "J'arrive."


def test_le_separateur_du_corps_differe_entre_ios_et_android(iris: Telephoniste):
    """Piège connu : iOS attend « &body= », Android et la RFC attendent « ?body= ».

    Se tromper donne un SMS pré-rempli vide, sans la moindre erreur : la page /m doit pouvoir choisir.
    """
    brouillon = iris.preparer_sms(NUMERO, "Salut ça va ?")
    assert brouillon.lien_ios().startswith(f"sms:{NUMERO}&body=")
    assert brouillon.lien_android().startswith(f"sms:{NUMERO}?body=")
    assert " " not in brouillon.lien_ios() and "?" not in brouillon.lien_ios().split("&body=")[1]
    assert brouillon.lien_ios().endswith("Salut%20%C3%A7a%20va%20%3F")


def test_un_appel_ouvre_le_composeur_du_telephone(iris: Telephoniste):
    """« Un ordinateur ne passe pas d'appel » : IRIS compose sur la ligne de Miguel, il décroche."""
    brouillon = iris.preparer_appel("1 (819) 524-2804")
    assert brouillon.lien_ios() == brouillon.lien_android() == f"tel:{NUMERO}"
    resultat = iris.executer(accorder(iris, brouillon))
    assert resultat["envoye"] is False and "touche Appeler" in resultat["message"]


def test_le_brouillon_se_ferme_quil_soit_envoye_ou_annule(iris: Telephoniste, registre: FauxRegistre):
    """Le registre doit montrer les renoncements : une trace qui ne montre que les succès ne prouve rien."""
    envoye = iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "Un.")))
    annule = iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "Deux.")))
    iris.marquer_envoye(envoye["id"])
    iris.marquer_annule(annule["id"])
    assert iris.en_attente() == []
    assert registre.evenements == [
        "telephonie_brouillon", "telephonie_brouillon", "telephonie_envoye", "telephonie_annule"
    ]
    with pytest.raises(ErreurTelephonie, match="n'existe plus"):
        iris.marquer_envoye(envoye["id"])


def test_un_brouillon_oublie_expire(iris: Telephoniste, horloge: Horloge):
    """Un texto d'il y a une heure qui ressurgit sur le téléphone partirait hors de son contexte."""
    iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "À tout de suite.")))
    horloge.avancer(DUREE_BROUILLON - 1)
    assert len(iris.en_attente()) == 1
    horloge.avancer(2)
    assert iris.en_attente() == []


def test_le_texte_du_sms_ne_va_pas_dans_le_registre(iris: Telephoniste, registre: FauxRegistre):
    """Le registre s'exporte en CSV et se lit à l'écran : le contenu d'un texto n'a rien à y traîner."""
    iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "Mon code de porte est 4712.")))
    detail = registre.entrees[0][2]
    assert NUMERO in detail and "4712" not in detail and "code de porte" not in detail


def test_le_hub_previent_le_bureau_et_le_telephone(coffre, horloge):
    """Sans événement, la page /m ne voit le brouillon qu'au prochain sondage — trop tard en voiture."""
    hub = FauxHub()
    t = Telephoniste(FauxSettings(), coffre, client_http=reseau_interdit, hub=hub, horloge=horloge)
    resultat = t.executer(accorder(t, t.preparer_sms(NUMERO, "Un mot.")))
    assert hub.publications[0][0] == "telephone.brouillon"
    assert hub.publications[0][1]["brouillon"]["id"] == resultat["id"]


# --------------------------------------------------------------------------- numéros
@pytest.mark.parametrize(
    "dicte,attendu",
    [
        ("819 524-2804", NUMERO),
        ("(819) 524 2804", NUMERO),
        ("1-819-524-2804", NUMERO),
        ("+1 819 524 2804", NUMERO),
        ("8195242804", NUMERO),
        ("011 33 6 12 34 56 78", "+33612345678"),
        ("00 33 6 12 34 56 78", "+33612345678"),
    ],
)
def test_un_numero_dicte_sort_toujours_au_format_e164(dicte, attendu):
    """Un numéro arrive sous dix formes ; une seule doit en sortir, sinon le texto part chez un inconnu."""
    assert normaliser_numero(dicte) == attendu


@pytest.mark.parametrize(
    "mauvais",
    ["", "   ", "bonjour", "1-800-FLEURS", "819 524-2804 poste 12", "5551234", "0195242804", "1115242804",
     "8190242804", "+1234567890123456789"],
)
def test_un_numero_invalide_est_refuse(iris: Telephoniste, mauvais):
    """Un numéro accepté à tort, c'est un message privé chez quelqu'un qui n'a rien demandé."""
    with pytest.raises(NumeroInvalide):
        iris.preparer_sms(mauvais, "Un mot.")
    assert iris.en_attente() == []


@pytest.mark.parametrize("urgence", ["911", "112", "988"])
def test_iris_ne_compose_jamais_un_numero_durgence(iris: Telephoniste, urgence):
    """Une fausse alerte déclenchée par une hallucination, c'est un secours qui manque ailleurs."""
    with pytest.raises(NumeroInvalide) as capture:
        iris.preparer_appel(urgence)
    assert "compose-le toi-même" in str(capture.value)


@pytest.mark.parametrize(
    "peage,indice",
    [("1-900-555-1212", "à la minute"), ("819-976-1234", "central"), ("+8701234567", "satellite"), ("12345", "code court")],
)
def test_un_numero_surtaxe_est_refuse(iris: Telephoniste, peage, indice):
    """Une minute de 900 ou de satellite se facture en dollars, pas en cents."""
    with pytest.raises(NumeroSurtaxe) as capture:
        iris.preparer_sms(peage, "Un mot.")
    assert indice in str(capture.value)


def test_un_sms_vide_ou_interminable_est_refuse(iris: Telephoniste):
    """Chaque tranche de 160 caractères se facture : un pavé de 3000 signes coûte dix-neuf segments."""
    with pytest.raises(ErreurTelephonie, match="vide"):
        iris.preparer_sms(NUMERO, "   \n  ")
    with pytest.raises(ErreurTelephonie) as capture:
        iris.preparer_sms(NUMERO, "a" * (MAX_CARACTERES + 1))
    assert "segments" in str(capture.value)
    assert iris.preparer_sms(NUMERO, "a" * 200).segments == 2


# --------------------------------------------------------------------------- limite de débit
def test_la_limite_de_debit_tient_meme_avec_des_accords_en_main(iris: Telephoniste):
    """Un modèle qui boucle sur un outil appellerait cent fois. Chaque appel se paie."""
    accords = [accorder(iris, iris.preparer_sms(NUMERO, f"Message {i}")) for i in range(MAX_ENVOIS_PAR_HEURE + 1)]
    for accord in accords[:MAX_ENVOIS_PAR_HEURE]:
        iris.executer(accord)
    assert iris.compteur.restant == 0
    with pytest.raises(LimiteAtteinte) as capture:
        iris.executer(accords[-1])
    texte = str(capture.value)
    assert "dernière heure" in texte and "minutes" in texte
    assert "toi-même depuis ton téléphone" in texte, "un refus doit dire quoi faire à la place"


def test_la_limite_ne_brule_pas_laccord_deja_donne(iris: Telephoniste, horloge: Horloge):
    """Redemander une confirmation qu'on vient de donner passe pour une panne ; l'accord doit survivre."""
    accords = [accorder(iris, iris.preparer_sms(NUMERO, f"Message {i}")) for i in range(MAX_ENVOIS_PAR_HEURE + 1)]
    for accord in accords[:MAX_ENVOIS_PAR_HEURE]:
        iris.executer(accord)
    with pytest.raises(LimiteAtteinte):
        iris.executer(accords[-1])
    horloge.avancer(3601)
    assert iris.executer(accords[-1])["ok"] is True


def test_la_limite_se_dit_avant_de_faire_relire_le_message(iris: Telephoniste):
    """Faire relire un texto à voix haute pour le refuser après serait une perte de temps de plus."""
    for _ in range(MAX_ENVOIS_PAR_HEURE):
        iris.executer(accorder(iris, iris.preparer_sms(NUMERO, "Un mot.")))
    with pytest.raises(LimiteAtteinte):
        iris.preparer_sms(NUMERO, "Un mot de plus.")


# --------------------------------------------------------------------------- service non configuré
def test_sans_compte_le_service_dit_ce_qui_manque_en_francais(coffre, horloge):
    """« KeyError: username » ne dit rien à Miguel ; ce qu'il doit ouvrir lui-même, si."""
    t = Telephoniste(FauxSettings(telephonie=ReglagesBruts(fournisseur="twilio")), coffre,
                     client_http=reseau_interdit, horloge=horloge)
    assert t.configure is False
    with pytest.raises(TelephonieNonConfiguree) as capture:
        t.preparer_sms(NUMERO, "Un mot.")
    texte = str(capture.value)
    assert "twilio.com" in texte and "carte de crédit" in texte
    assert "adresse canadienne" in texte, "la validation d'adresse est ce qui bloque le plus longtemps"
    assert "je prépare le message sur ton téléphone" in texte, "un refus doit proposer ce qui marche"


def test_un_compte_sans_numero_dexpedition_le_dit(coffre, horloge):
    t = Telephoniste(FauxSettings(telephonie=ReglagesBruts(fournisseur="twilio")), coffre,
                     client_http=reseau_interdit, horloge=horloge)
    coffre.set_site("telephonie", SID, TOKEN)
    assert t.configure is False
    with pytest.raises(TelephonieNonConfiguree, match="numéro depuis lequel envoyer"):
        t.preparer_sms(NUMERO, "Un mot.")


def test_la_telephonie_desactivee_le_dit_sans_planter(coffre, horloge):
    t = Telephoniste(FauxSettings(telephonie=ReglagesBruts(fournisseur="aucun")), coffre, horloge=horloge)
    assert t.configure is False
    with pytest.raises(TelephonieNonConfiguree, match="désactivée"):
        t.preparer_sms(NUMERO, "Un mot.")


def test_un_fournisseur_inconnu_nomme_les_valeurs_acceptees(coffre, horloge):
    """Une faute de frappe dans settings.json ne doit pas se traduire par un silence."""
    t = Telephoniste(FauxSettings(telephonie=ReglagesBruts(fournisseur="pigeon")), coffre, horloge=horloge)
    with pytest.raises(TelephonieNonConfiguree) as capture:
        t.preparer_sms(NUMERO, "Un mot.")
    assert "iphone" in str(capture.value) and "twilio" in str(capture.value)


def test_sans_section_dans_les_reglages_la_voie_iphone_sapplique(coffre, horloge):
    """config.py n'a pas encore de section « telephonie » : l'absence doit valoir le choix le plus sûr."""
    t = Telephoniste(FauxSettings(), coffre, client_http=reseau_interdit, horloge=horloge)
    assert t.fournisseur == "iphone" and t.configure is True
    assert t.executer(accorder(t, t.preparer_sms(NUMERO, "Un mot.")))["envoye"] is False


def test_le_mode_local_interdit_lenvoi_par_un_tiers_mais_pas_le_brouillon(coffre, horloge):
    """Décision assumée : un brouillon ne quitte pas l'ordinateur vers un tiers, il va sur SON téléphone.

    Le texte d'un SMS remis à Twilio, lui, part chez un service américain : c'est exactement ce que
    « rien ne quitte cet ordinateur » interdit.
    """
    bloque = Telephoniste(FauxSettings(local_only=True, telephonie=ReglagesBruts(fournisseur="twilio")), coffre,
                          client_http=reseau_interdit, horloge=horloge)
    coffre.set_site("telephonie", SID, TOKEN)
    coffre.set_site("telephonie-numero", EXPEDITEUR, "")
    assert bloque.configure is False
    with pytest.raises(ModeLocalActif, match="mode local"):
        bloque.preparer_sms(NUMERO, "Un mot.")

    permis = Telephoniste(FauxSettings(local_only=True), coffre, client_http=reseau_interdit, horloge=horloge)
    assert permis.executer(accorder(permis, permis.preparer_sms(NUMERO, "Un mot.")))["en_attente"] is True


def test_un_appel_par_un_service_internet_est_refuse(coffre, horloge):
    """Le correspondant verrait un numéro inconnu et ne pourrait pas rappeler la vraie ligne."""
    t = twilio(coffre, horloge, FauxHTTP())
    with pytest.raises(TelephonieNonConfiguree, match="numéro inconnu"):
        t.preparer_appel(NUMERO)


# --------------------------------------------------------------------------- voie Twilio (dormante)
def test_un_envoi_reel_transmet_le_texte_approuve_et_rien_dautre(coffre, horloge):
    http = FauxHTTP()
    t = twilio(coffre, horloge, http)
    resultat = t.executer(accorder(t, t.preparer_sms("819 524-2804", "À demain.")))
    assert len(http.appels) == 1
    envoi = http.appels[0]
    assert envoi["donnees"] == {"To": NUMERO, "From": EXPEDITEUR, "Body": "À demain."}
    assert envoi["auth"] == (SID, TOKEN) and SID in envoi["url"]
    assert resultat["envoye"] is True and resultat["ok"] is True
    assert "819 524-2804" in resultat["message"]


def test_un_destinataire_desabonne_est_expose_clairement(coffre, horloge):
    """Répondre STOP bloque définitivement l'expéditeur, et c'est la loi : inutile de réessayer."""
    http = FauxHTTP(statut=400, corps={"code": 21610, "message": "Attempt to send to unsubscribed recipient"})
    t = twilio(coffre, horloge, http)
    with pytest.raises(EnvoiEchoue) as capture:
        t.executer(accorder(t, t.preparer_sms(NUMERO, "Un mot.")))
    assert "STOP" in str(capture.value) and "Rien n'est parti" in str(capture.value)


def test_un_echec_ne_laisse_jamais_croire_que_le_message_est_parti(coffre, horloge):
    """IRIS doit pouvoir dire « je n'ai pas réussi », jamais « c'est fait » quand rien n'est parti."""
    http = FauxHTTP(erreur=OSError("[WinError 10060] hôte injoignable"))
    t = twilio(coffre, horloge, http)
    accord = accorder(t, t.preparer_sms(NUMERO, "Un mot."))
    with pytest.raises(EnvoiEchoue, match="pas parti"):
        t.executer(accord)
    # L'accord est consommé même en échec : on ne sait pas si l'opérateur avait déjà accepté le
    # message, donc un nouvel envoi se redemande.
    with pytest.raises(AutorisationInvalide):
        t.executer(accord)


# --------------------------------------------------------------------------- fuite d'identifiants
def test_le_jeton_napparait_ni_dans_lerreur_ni_dans_le_journal(coffre, horloge, caplog):
    """Un message d'erreur finit recopié dans un rapport de bogue, ou lu à voix haute."""
    caplog.set_level(logging.DEBUG, logger="iris.telephonie")
    http = FauxHTTP(erreur=RuntimeError(f"échec TLS pour Authorization: Basic {SID}:{TOKEN}"))
    t = twilio(coffre, horloge, http)
    with pytest.raises(EnvoiEchoue) as capture:
        t.executer(accorder(t, t.preparer_sms(NUMERO, "Un mot.")))
    texte = str(capture.value)
    assert TOKEN not in texte and SID not in texte
    assert "•••" in texte, "le secret doit être remplacé, pas absent par chance"
    assert TOKEN not in caplog.text and SID not in caplog.text


def test_la_reponse_de_loperateur_est_nettoyee_avant_detre_montree(coffre, horloge):
    http = FauxHTTP(statut=401, corps={"code": 20003, "message": f"Authenticate ({TOKEN})"})
    t = twilio(coffre, horloge, http)
    with pytest.raises(EnvoiEchoue) as capture:
        t.executer(accorder(t, t.preparer_sms(NUMERO, "Un mot.")))
    assert TOKEN not in str(capture.value)
    assert "redonner le nouveau" in str(capture.value)


def test_letat_affichable_ne_contient_jamais_les_identifiants(coffre, horloge):
    """L'état part vers le renderer et vers la page /m : il ne doit rien porter de réutilisable."""
    t = twilio(coffre, horloge, FauxHTTP())
    etat = t.etat()
    assert TOKEN not in str(etat) and SID not in str(etat)
    assert etat["secret"] and etat["identifiant"], "l'interface montre une empreinte, pas rien"
    assert etat["configure"] is True and etat["peut_envoyer_seule"] is True


def test_les_identifiants_ne_sont_jamais_ecrits_dans_les_reglages(tmp_path, coffre, horloge):
    """Les secrets vivent dans le coffre. settings.json est lisible par n'importe quel programme."""
    from iris.config import Settings

    reglages = Settings(tmp_path / "iris-data")
    t = Telephoniste(reglages, coffre, client_http=reseau_interdit, horloge=horloge)
    etat = t.configurer_twilio(SID, TOKEN, "514-555-0100")
    brut = reglages.settings_path.read_text(encoding="utf-8")
    assert TOKEN not in brut and SID not in brut
    assert TOKEN not in str(etat) and SID not in str(etat)
    assert etat["numero_expediteur"] == EXPEDITEUR, "le numéro loué est normalisé une fois pour toutes"
    t.oublier()
    assert coffre.get_site("telephonie") is None and coffre.get_site("telephonie-numero") is None


def test_un_identifiant_qui_nest_pas_un_account_sid_est_signale(iris: Telephoniste):
    """Cause d'échec numéro un : coller une clé d'API (SK…) au lieu de l'Account SID (AC…)."""
    with pytest.raises(TelephonieNonConfiguree, match="AC"):
        iris.configurer_twilio("SK" + "0" * 32, TOKEN, EXPEDITEUR)
    with pytest.raises(TelephonieNonConfiguree, match="tous les deux"):
        iris.configurer_twilio(SID, "", EXPEDITEUR)
