"""Appels et SMS depuis IRIS.

Un SMS parti ne se rattrape pas, exactement comme un courriel — et en plus il coûte de l'argent à
chaque envoi. Ce module est écrit autour de ces deux phrases.

LES DEUX VOIES, ET POURQUOI LA PREMIÈRE EST LA BONNE
----------------------------------------------------
Voie « iphone » (celle qui est active) : IRIS rédige le message sur l'ordinateur, dépose un
BROUILLON, et le téléphone l'ouvre dans l'application Messages ou Téléphone, déjà rempli. C'est
Miguel qui touche Envoyer. Conséquences, toutes bonnes :
  - l'appel et le SMS partent de SA ligne, avec SON numéro : le correspondant le reconnaît et peut
    rappeler. C'est précisément ce qu'un numéro loué chez un tiers ne sait pas faire ;
  - ça ne coûte rien de plus que son forfait ;
  - et surtout la promesse « IRIS n'envoie rien en votre nom sans votre accord » cesse d'être une
    propriété de notre code pour devenir une propriété d'iOS, qui n'expose aucune API permettant à
    un programme d'envoyer un SMS en arrière-plan. Aucune quantité de code défensif n'atteint ce
    niveau de garantie : même un bogue d'IRIS ne peut pas faire partir un message.

Voie « twilio » (écrite, mais DORMANTE) : envoi réel par l'API REST d'un opérateur Internet. Elle
existe ici pour une seule raison — le jour où VELA devra prévenir un client (« votre licence est
active »), ce besoin-là ne passe pas par le téléphone de Miguel. Elle n'est pas configurée, elle le
dit en français au lieu de planter, et elle exige un compte payant que Miguel doit ouvrir lui-même.
Tant qu'elle dort, ce module ne fait AUCUN appel réseau.

CE QUI EST IMPOSSIBLE, pour que personne ne le recherche
--------------------------------------------------------
Faire envoyer un SMS par un iPhone depuis un programme : il n'existe pas d'API publique. Piloter le
relais SMS d'Apple depuis Windows : le Mac et l'iPad en sont capables, un PC n'entre jamais dans ce
cercle. Automatiser Phone Link : pas d'API, et de toute façon Windows 11 exigé pour l'iPhone —
cette machine est en Windows 10. Envoyer un SMS depuis le vrai numéro de Miguel via un service
Internet : l'expéditeur est toujours le numéro loué. Ce n'est pas une question de difficulté.

LA SERRURE DE CONFIRMATION
--------------------------
Même dispositif que `courriel.py`, volontairement identique : `executer()` n'accepte pas un
brouillon, il accepte une `Autorisation`, et une `Autorisation` ne se fabrique qu'avec un sceau
privé au module que seule `demander_accord()` détient — après qu'un humain a répondu oui. Écrire un
envoi non confirmé ne demande donc pas de la discipline, cela demande de modifier ce fichier.
Elle est liée à l'empreinte du message, ne sert qu'une fois, et expire.

Oui, cette confirmation fait doublon avec le geste du pouce sur l'iPhone. Elle ne fait pas doublon
avec ce qui compte : elle garantit que le texte relu à voix haute est EXACTEMENT celui qui sera
déposé sur le téléphone. Le pouce d'iOS, lui, ne vérifie rien du contenu.

DEUX GARDES QUE L'ARGENT JUSTIFIE
---------------------------------
Une limite de dix envois par heure : un modèle qui boucle sur un outil ne vide ni un forfait ni un
crédit prépayé. Et un refus net des numéros surtaxés (900, 976, satellite) et des numéros
d'urgence : une fausse alerte au 911 déclenchée par une hallucination a des conséquences réelles,
et une minute de 900 se facture en dollars.

TROU CONNU, à boucher avant d'activer quoi que ce soit depuis le téléphone
--------------------------------------------------------------------------
`mobile.py` n'écoute pas l'événement « chat.confirm » : une confirmation demandée par IRIS est
aujourd'hui INVISIBLE depuis la page /m. Un tour lancé depuis le téléphone tournerait 180 secondes
puis renverrait « refusé » sans que rien ne s'affiche. Tant que ce n'est pas corrigé, les outils de
téléphonie ne doivent pas être proposés depuis /m — ce qui est doublement dommage, puisque c'est en
voiture qu'on veut dicter un texto.

Les identifiants ne transitent ni par settings.json, ni par une variable d'environnement, ni par un
journal : ils vivent dans `security/secrets.py`.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote

log = logging.getLogger("iris.telephonie")

# Clé du coffre : username = Account SID, password = Auth Token. Même forme que les comptes web.
NOM_COFFRE = "telephonie"
# Le numéro d'expédition loué n'est pas un secret, mais c'est une donnée personnelle, et
# settings.json est lisible par n'importe quel programme de la machine. Il dort donc à côté des
# identifiants plutôt que dans les réglages.
NOM_COFFRE_NUMERO = "telephonie-numero"

DELAI_HTTP = 20  # secondes ; au-delà c'est une coupure réseau, pas un opérateur lent
DUREE_ACCORD = 300.0  # un oui vaut cinq minutes : le temps de se raviser sans tout redicter
DUREE_BROUILLON = 900.0  # un brouillon oublié qui ressurgit une heure plus tard ferait envoyer un message hors contexte
MAX_ENVOIS_PAR_HEURE = 10
FENETRE_DEBIT = 3600.0
# 1600 caractères = dix segments de 160, tous facturés. Au-delà, c'est un courriel, pas un texto.
MAX_CARACTERES = 1600
TAILLE_SEGMENT = 160

URL_TWILIO = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

FOURNISSEURS_CONNUS = ("iphone", "twilio", "aucun")
FOURNISSEUR_DEFAUT = "iphone"

_CONTROLE = re.compile(r"[\r\n\x00]")
_LETTRES = re.compile(r"[A-Za-z]")
_HORS_NUMERO = re.compile(r"[^\d+]")

# Un numéro d'urgence ne se compose pas depuis un programme. Ce n'est pas une question de coût.
NUMEROS_URGENCE = {"911", "112", "999", "988", "933"}
# Codes de service à trois chiffres (N11). Le 411 est facturé, les autres ne mènent nulle part
# depuis un composeur automatique.
CODES_SERVICE = {"211", "311", "411", "511", "611", "711", "811"}
# Indicatifs nord-américains facturés à l'appelant, parfois plusieurs dollars la minute.
NPA_SURTAXES = {
    "900": "les numéros 900 sont facturés à la minute à celui qui appelle",
    "976": "les numéros 976 sont des services payants à la minute",
    "700": "les numéros 700 sont des services d'opérateur au tarif imposé par l'opérateur",
    "500": "les numéros 500 sont des services de réacheminement facturés au tarif fort",
}
# Le 976 a d'abord été un central surtaxé À L'INTÉRIEUR de chaque indicatif (819-976-XXXX). Un
# numéro qui passe le contrôle de l'indicatif peut donc encore être surtaxé par son central.
NXX_SURTAXE = "976"
# Satellite et numéros internationaux à coût partagé : plusieurs dollars la minute, et ce sont les
# destinations favorites de la fraude au rappel.
PREFIXES_SURTAXES_INTERNATIONAUX = (
    "+870", "+871", "+872", "+873", "+874", "+875", "+876", "+877", "+878",  # Inmarsat / maritime
    "+881", "+882", "+883",  # réseaux mobiles et de réseau global
    "+808",  # coût partagé international
    "+979",  # tarif majoré international
)

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (titre, détail) -> approuvé ? — signature de ToolContext.confirm
# (url, données, (identifiant, secret), délai) -> réponse façon requests. Injecté dans les tests :
# aucun test de ce module ne touche le réseau.
ClientHTTP = Callable[[str, dict, tuple[str, str], int], Any]

MODE_EMPLOI_TWILIO = (
    "Pour que je puisse envoyer un SMS moi-même, il faut un compte chez un opérateur Internet "
    "(Twilio), et je ne peux pas l'ouvrir à ta place : cela demande une carte de crédit et une "
    "pièce d'identité. Il faut créer le compte sur twilio.com, y déclarer une adresse canadienne "
    "réelle (les casiers postaux sont refusés, la validation prend jusqu'à deux jours ouvrables), "
    "louer un numéro local (environ 1,15 $ US par mois), puis me donner l'Account SID, l'Auth "
    "Token et le numéro loué. Compte environ 1,7 ¢ par SMS. "
    "En attendant, je prépare le message sur ton téléphone et c'est toi qui touches Envoyer — "
    "ça ne coûte rien et ton correspondant voit ton vrai numéro."
)

EXPLICATION_IPHONE = (
    "Je ne peux pas envoyer un SMS ni composer un appel toute seule depuis cet ordinateur : "
    "Apple n'ouvre à aucun programme le droit d'envoyer un message à ta place. Ce que je fais, "
    "c'est préparer le message sur ton téléphone — tu n'as plus qu'à toucher Envoyer."
)


# --------------------------------------------------------------------------- erreurs
class ErreurTelephonie(Exception):
    """Toute erreur de ce module porte une phrase française, destinée à être lue à l'utilisateur."""


class TelephonieNonConfiguree(ErreurTelephonie):
    """Le service n'est pas prêt. Il doit le DIRE, pas planter sur une clé manquante."""


class NumeroInvalide(ErreurTelephonie):
    pass


class NumeroSurtaxe(NumeroInvalide):
    """Sous-classe volontaire : qui attrape NumeroInvalide attrape aussi les numéros à péage."""


class AutorisationInvalide(ErreurTelephonie):
    """Levée dès qu'on tente d'agir sans un accord valide, à jour et non encore utilisé."""


class LimiteAtteinte(ErreurTelephonie):
    pass


class EnvoiEchoue(ErreurTelephonie):
    """L'envoi n'a pas abouti. IRIS doit le dire, jamais prétendre le contraire."""


class ModeLocalActif(ErreurTelephonie):
    pass


# --------------------------------------------------------------------------- outils internes
def _sans_secret(texte: str, *secrets: str) -> str:
    """Efface les identifiants d'un texte destiné à un journal ou à l'écran.

    Un Auth Token n'a aucune raison d'apparaître dans une réponse d'API, mais un message d'erreur
    finit souvent recopié dans un rapport de bogue, ou lu à voix haute. On ne parie pas là-dessus.
    """
    propre = texte or ""
    for secret in secrets:
        secret = (secret or "").strip()
        if len(secret) < 8:  # un fragment trop court remplacerait des morceaux de phrase au hasard
            continue
        propre = propre.replace(secret, "•••")
    return propre


def _champ(source: Any, nom: str, defaut: Any) -> Any:
    """Lit un champ que la source soit un modèle pydantic, un dataclass ou un dict."""
    if source is None:
        return defaut
    valeur = source.get(nom, defaut) if isinstance(source, dict) else getattr(source, nom, defaut)
    return defaut if valeur in (None, "") else valeur


def _maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- numéros
def _refuser_court(chiffres: str) -> None:
    if chiffres in NUMEROS_URGENCE:
        raise NumeroInvalide(
            f"Je ne compose jamais le {chiffres}. Si c'est une urgence, compose-le toi-même, "
            "tout de suite — un secours envoyé par erreur est un secours qui manque ailleurs."
        )
    if chiffres in CODES_SERVICE:
        raise NumeroInvalide(
            f"Le {chiffres} est un code de service, pas un numéro de correspondant. "
            "Compose-le depuis ton téléphone si tu en as besoin."
        )
    raise NumeroSurtaxe(
        f"« {chiffres} » est un code court. Ces numéros à trois, quatre ou cinq chiffres sont "
        "presque tous facturés, souvent par abonnement. Je ne les compose pas."
    )


def _refuser_surtaxe(numero: str) -> None:
    """Lève si le numéro coûte de l'argent à celui qui l'appelle ou l'écrit."""
    for prefixe in PREFIXES_SURTAXES_INTERNATIONAUX:
        if numero.startswith(prefixe):
            raise NumeroSurtaxe(
                f"« {numero} » est un numéro satellite ou à tarif majoré ({prefixe}) : la minute s'y "
                "facture en dollars, pas en cents. Je ne le compose pas. Si tu y tiens, fais-le toi-même."
            )
    if numero.startswith("+1") and len(numero) == 12:
        npa, nxx = numero[2:5], numero[5:8]
        raison = NPA_SURTAXES.get(npa)
        if raison:
            raise NumeroSurtaxe(
                f"« {numero} » est un numéro à péage : {raison}. Je ne le compose pas. "
                "Si c'est vraiment ce que tu veux, compose-le toi-même."
            )
        if nxx == NXX_SURTAXE:
            raise NumeroSurtaxe(
                f"« {numero} » passe par le central {NXX_SURTAXE}, historiquement réservé aux services "
                "payants à la minute. Je ne le compose pas."
            )


def _valider_nord_americain(chiffres: str) -> None:
    """Contrôle du plan de numérotation nord-américain, sur « 1 » + dix chiffres."""
    national = chiffres[1:]
    if len(national) != 10:
        raise NumeroInvalide(
            f"« +{chiffres} » n'est pas un numéro nord-américain valide : il en faut exactement dix "
            "chiffres après l'indicatif 1."
        )
    npa, nxx = national[:3], national[3:6]
    if npa[0] in "01":
        raise NumeroInvalide(f"« +{chiffres} » : aucun indicatif régional ne commence par {npa[0]}.")
    if npa[1:] == "11":
        raise NumeroInvalide(
            f"« +{chiffres} » : {npa} est un code de service (comme le 911 ou le 411), pas un indicatif régional."
        )
    if nxx[0] in "01":
        raise NumeroInvalide(f"« +{chiffres} » : aucun central ne commence par {nxx[0]}.")


def normaliser_numero(brut: str, indicatif_pays: str = "+1") -> str:
    """Renvoie le numéro au format E.164 (« +18195242804 ») ou lève.

    Un numéro dicté arrive sous toutes les formes : « 819-524-2804 », « (819) 524 2804 »,
    « 1 819 524 2804 ». Une seule sort d'ici. Un numéro mal normalisé, c'est un message chez un
    inconnu ou un appel qui ne passe pas.
    """
    brut = (brut or "").strip()
    if not brut:
        raise NumeroInvalide("Aucun numéro : je ne sais pas qui joindre.")
    if _CONTROLE.search(brut):
        raise NumeroInvalide("Numéro refusé : il contient un retour à la ligne.")
    if _LETTRES.search(brut):
        # « 1-800-FLEURS », ou un modèle qui glisse « poste 12 » dans le champ. Les deux se
        # corrigent à la main ; composé tel quel, l'un ne passe pas et l'autre appelle un inconnu.
        raise NumeroInvalide(
            f"« {brut} » contient des lettres. Donne-moi le numéro en chiffres, sans poste ni mot."
        )

    compact = _HORS_NUMERO.sub("", brut)
    plus = compact.startswith("+")
    chiffres = compact.lstrip("+")
    if not chiffres.isdigit():
        raise NumeroInvalide(f"« {brut} » n'est pas un numéro de téléphone.")

    if not plus:
        if len(chiffres) <= 6:
            _refuser_court(chiffres)
        if chiffres.startswith("011"):  # préfixe international composé depuis l'Amérique du Nord
            chiffres, plus = chiffres[3:], True
        elif chiffres.startswith("00"):  # préfixe international composé depuis l'Europe
            chiffres, plus = chiffres[2:], True

    if not plus:
        indicatif = (indicatif_pays or "+1").lstrip("+")
        if not indicatif.isdigit():
            indicatif = "1"
        if len(chiffres) == 10 and indicatif == "1":
            chiffres = indicatif + chiffres  # 819 524 2804 dicté sans son 1
        elif len(chiffres) == 11 and chiffres.startswith("1"):
            pass  # déjà 1 + indicatif régional
        elif indicatif != "1":
            chiffres = indicatif + chiffres.lstrip("0")
        else:
            raise NumeroInvalide(
                f"« {brut} » ne fait pas dix chiffres : je ne devine pas un numéro de téléphone. "
                "Donne-moi l'indicatif régional et les sept chiffres, ou le numéro complet avec son +."
            )

    if len(chiffres) < 8:
        raise NumeroInvalide(f"« {brut} » est trop court pour être un numéro joignable.")
    if len(chiffres) > 15:
        # E.164 : quinze chiffres, pas un de plus. Au-delà, c'est une saisie qui a dérapé.
        raise NumeroInvalide(f"« {brut} » fait plus de quinze chiffres : ce n'est pas un numéro.")

    numero = "+" + chiffres
    _refuser_surtaxe(numero)
    if chiffres.startswith("1"):
        _valider_nord_americain(chiffres)
    return numero


def numero_lisible(numero: str) -> str:
    """« +18195242804 » -> « 819 524-2804 », pour l'écrire à l'écran et le lire à voix haute."""
    if numero.startswith("+1") and len(numero) == 12:
        n = numero[2:]
        return f"{n[:3]} {n[3:6]}-{n[6:]}"
    return numero


# --------------------------------------------------------------------------- limite de débit
class Compteur:
    """Fenêtre glissante d'une heure sur les envois.

    Elle n'existe pas pour rationner Miguel : elle existe parce qu'un modèle qui boucle sur un
    outil peut appeler cent fois de suite, et que chaque appel se facture. Elle compte aussi les
    brouillons déposés sur le téléphone, qui ne coûtent rien mais qui, en rafale, noient l'écran
    de demandes de confirmation.
    """

    def __init__(self, maximum: int = MAX_ENVOIS_PAR_HEURE, fenetre: float = FENETRE_DEBIT,
                 horloge: Callable[[], float] = time.monotonic):
        self.maximum = max(1, int(maximum))
        self.fenetre = float(fenetre)
        self._horloge = horloge
        self._envois: list[float] = []

    def _purger(self) -> None:
        limite = self._horloge() - self.fenetre
        self._envois = [t for t in self._envois if t > limite]

    @property
    def restant(self) -> int:
        self._purger()
        return max(0, self.maximum - len(self._envois))

    def minutes_avant_creneau(self) -> int:
        self._purger()
        if not self._envois:
            return 0
        attente = self.fenetre - (self._horloge() - min(self._envois))
        return max(1, int(attente // 60) + (1 if attente % 60 else 0))

    def verifier(self) -> None:
        if self.restant > 0:
            return
        raise LimiteAtteinte(
            f"J'ai déjà fait partir {self.maximum} messages dans la dernière heure, et je m'arrête là. "
            "C'est ce qui empêche une erreur de ma part de vider ton forfait ou ton crédit. "
            f"Le prochain sera possible dans {self.minutes_avant_creneau()} minutes. "
            "Si c'est urgent, envoie-le toi-même depuis ton téléphone."
        )

    def enregistrer(self) -> None:
        self._purger()
        self._envois.append(self._horloge())


# --------------------------------------------------------------------------- brouillon
@dataclass(frozen=True)
class Brouillon:
    """Un SMS ou un appel prêt, mais NON parti. C'est ce qu'IRIS relit avant de demander l'accord.

    Gelé pour que ce qui a été approuvé soit exactement ce qui part : l'empreinte est calculée à la
    construction et revérifiée au moment d'agir.
    """

    genre: str  # "sms" | "appel"
    numero: str  # E.164
    texte: str = ""
    identifiant: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    empreinte: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "empreinte", self.calculer_empreinte())

    def calculer_empreinte(self) -> str:
        return hashlib.sha256("\x1f".join([self.genre, self.numero, self.texte]).encode("utf-8")).hexdigest()

    @property
    def segments(self) -> int:
        """Nombre de segments facturés. Un SMS de 200 caractères se paie deux fois."""
        if self.genre != "sms" or not self.texte:
            return 0
        return (len(self.texte) - 1) // TAILLE_SEGMENT + 1

    def titre(self) -> str:
        """Titre de la demande de confirmation : il contient à QUI, c'est ce qui se vérifie d'abord."""
        qui = numero_lisible(self.numero)
        return f"Préparer un SMS pour {qui}" if self.genre == "sms" else f"Appeler {qui}"

    def apercu(self) -> str:
        """Le message entier, tel qu'il partira. Rien d'abrégé : on ne confirme pas un résumé."""
        lignes = [f"À : {numero_lisible(self.numero)} ({self.numero})"]
        if self.genre == "sms":
            lignes += [f"Longueur : {len(self.texte)} caractères ({self.segments} segment(s) facturé(s))", "", self.texte]
        else:
            lignes.append("Le composeur de ton téléphone s'ouvrira avec ce numéro ; c'est toi qui lances l'appel.")
        return "\n".join(lignes)

    def pour_la_voix(self) -> str:
        qui = numero_lisible(self.numero)
        if self.genre == "appel":
            return f"Appel vers {qui}."
        return f"SMS à {qui}. Message : {self.texte}"

    # --- liens à ouvrir sur le téléphone ---
    # PIÈGE, il coûte une soirée sinon : le séparateur du corps du message n'est pas le même
    # partout. iOS attend historiquement « sms:+1819...&body=… » (esperluette), Android et la
    # RFC 5724 attendent « ?body= ». On écrit les deux et la page /m choisit selon l'agent
    # utilisateur, qu'elle sait déjà reconnaître (constante IOS de mobile.py).
    def lien_ios(self) -> str:
        if self.genre == "appel":
            return f"tel:{self.numero}"
        return f"sms:{self.numero}&body={quote(self.texte, safe='')}"

    def lien_android(self) -> str:
        if self.genre == "appel":
            return f"tel:{self.numero}"
        return f"sms:{self.numero}?body={quote(self.texte, safe='')}"

    def en_dict(self) -> dict:
        return {
            "id": self.identifiant,
            "genre": self.genre,
            "numero": self.numero,
            "numero_lisible": numero_lisible(self.numero),
            "texte": self.texte,
            "segments": self.segments,
            "titre": self.titre(),
            "lien_ios": self.lien_ios(),
            "lien_android": self.lien_android(),
        }


@dataclass
class EnAttente:
    """Un brouillon déposé sur le téléphone, en attente du pouce de Miguel."""

    brouillon: Brouillon
    depose_a: float
    depose_iso: str


# --------------------------------------------------------------------------- autorisation
_SCEAU = object()  # jeton privé au module : seule `Telephoniste.demander_accord` le détient


class Autorisation:
    """La preuve qu'un humain a dit oui à CE message-là, il y a moins de cinq minutes.

    Impossible à fabriquer depuis l'extérieur : le constructeur exige `_SCEAU`. C'est ce qui rend un
    envoi non confirmé structurellement impossible plutôt que simplement déconseillé.
    """

    __slots__ = ("brouillon", "empreinte", "_accorde_a", "_consomme")

    def __init__(self, brouillon: Brouillon, sceau: Any) -> None:
        if sceau is not _SCEAU:
            raise AutorisationInvalide(
                "Une autorisation ne se fabrique pas : elle s'obtient par "
                "Telephoniste.demander_accord(), qui attend la réponse de l'utilisateur."
            )
        self.brouillon = brouillon
        self.empreinte = brouillon.empreinte
        self._accorde_a = time.monotonic()
        self._consomme = False

    @property
    def perimee(self) -> bool:
        return (time.monotonic() - self._accorde_a) > DUREE_ACCORD

    @property
    def utilisable(self) -> bool:
        return not self._consomme and not self.perimee and self.empreinte == self.brouillon.calculer_empreinte()

    def consommer(self) -> Brouillon:
        """Rend le brouillon approuvé, une seule fois. Toute anomalie lève au lieu d'agir."""
        if self._consomme:
            raise AutorisationInvalide(
                "Cet accord a déjà servi. Pour recommencer, il faut le confirmer à nouveau."
            )
        if self.perimee:
            raise AutorisationInvalide(
                "L'accord a plus de cinq minutes. Je préfère te redemander avant d'agir."
            )
        if self.empreinte != self.brouillon.calculer_empreinte():
            raise AutorisationInvalide(
                "Le message a changé depuis que tu l'as approuvé. Je n'envoie pas un texte que tu n'as pas relu."
            )
        self._consomme = True
        return self.brouillon


# --------------------------------------------------------------------------- réglages
@dataclass
class ReglagesTelephonie:
    """Réglages non secrets. Ni le SID ni le token ne sont ici : ils ne touchent pas settings.json."""

    fournisseur: str = FOURNISSEUR_DEFAUT
    numero_par_defaut: str = ""
    indicatif_pays: str = "+1"


# --------------------------------------------------------------------------- service
class Telephoniste:
    """Le service. Quatre gestes : dire s'il est prêt, préparer, faire confirmer, agir.

    `client_http` existe pour les tests : aucun test de ce module ne touche le réseau. `horloge`
    aussi, pour vérifier la limite de débit sans attendre une heure.
    """

    def __init__(
        self,
        settings: Any,
        secrets: Any,
        client_http: ClientHTTP | None = None,
        registre: Any = None,  # ConsentGate : trace chaque envoi ET chaque refus
        hub: Any = None,  # EventHub : réveille le bureau et /m sans attendre le sondage
        horloge: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.secrets = secrets
        self._http = client_http
        self.registre = registre
        self.hub = hub
        self._horloge = horloge
        self.compteur = Compteur(horloge=horloge)
        self._attente: dict[str, EnAttente] = {}

    # ------------------------------------------------------------------ état
    @property
    def _user(self) -> Any:
        return getattr(self.settings, "user", None)

    @property
    def mode_local(self) -> bool:
        return bool(getattr(self._user, "local_only", False))

    def reglages(self) -> ReglagesTelephonie:
        brut = getattr(self._user, "telephonie", None)  # absent tant que config.py n'a pas la section
        fournisseur = str(_champ(brut, "fournisseur", FOURNISSEUR_DEFAUT)).strip().lower()
        return ReglagesTelephonie(
            fournisseur=fournisseur,
            numero_par_defaut=str(_champ(brut, "numero_par_defaut", "")).strip(),
            indicatif_pays=str(_champ(brut, "indicatif_pays", "+1")).strip(),
        )

    @property
    def fournisseur(self) -> str:
        return self.reglages().fournisseur

    def _identifiants(self) -> tuple[str, str]:
        """(Account SID, Auth Token) depuis le coffre, ou ('', '')."""
        try:
            creds = self.secrets.get_site(NOM_COFFRE) or {}
        except Exception as exc:  # coffre verrouillé, trousseau absent : pas une raison de planter
            log.warning("Coffre illisible pour le compte de téléphonie : %s", exc)
            return "", ""
        return (creds.get("username") or "").strip(), (creds.get("password") or "").strip()

    def _numero_expediteur(self) -> str:
        try:
            entree = self.secrets.get_site(NOM_COFFRE_NUMERO) or {}
        except Exception:
            entree = {}
        return (entree.get("username") or "").strip()

    @property
    def configure(self) -> bool:
        """Prêt à agir ? La voie iPhone l'est toujours : elle n'a rien à configurer."""
        fournisseur = self.fournisseur
        if fournisseur == "iphone":
            return True
        if fournisseur == "twilio":
            sid, token = self._identifiants()
            return bool(sid and token and self._numero_expediteur()) and not self.mode_local
        return False

    def pourquoi_pas_pret(self) -> str:
        """La phrase que la voix dit quand rien n'est possible. Vide si le service est prêt."""
        fournisseur = self.fournisseur
        if fournisseur == "aucun":
            return (
                "La téléphonie est désactivée dans les réglages : je ne prépare ni SMS ni appel. "
                "Remets « iphone » dans les réglages de téléphonie si tu veux que je m'en occupe."
            )
        if fournisseur not in FOURNISSEURS_CONNUS:
            return (
                f"Le fournisseur de téléphonie « {fournisseur} » ne me dit rien. "
                f"Les valeurs que je connais sont : {', '.join(FOURNISSEURS_CONNUS)}."
            )
        if fournisseur == "twilio":
            if self.mode_local:
                return (
                    "Le mode local est actif : le texte d'un SMS envoyé par Twilio quitterait cet "
                    "ordinateur vers un service américain, et c'est exactement ce que le mode local "
                    "interdit. Je peux en revanche le préparer sur ton téléphone."
                )
            sid, token = self._identifiants()
            if not (sid and token):
                return "Aucun compte d'envoi n'est enregistré. " + MODE_EMPLOI_TWILIO
            if not self._numero_expediteur():
                return (
                    "Le compte est enregistré, mais pas le numéro depuis lequel envoyer. "
                    "Donne-moi le numéro loué chez Twilio, au format +1 suivi de dix chiffres."
                )
        return ""

    def etat(self) -> dict:
        """État affichable. Ne renvoie jamais l'Auth Token, même partiellement côté serveur."""
        sid, token = self._identifiants()
        r = self.reglages()
        masque = getattr(self.secrets, "mask", lambda v: "••••" if v else "")
        return {
            "fournisseur": r.fournisseur,
            "configure": self.configure,
            "voie": "brouillon sur le téléphone" if r.fournisseur == "iphone" else r.fournisseur,
            "peut_envoyer_seule": r.fournisseur == "twilio" and self.configure,
            "identifiant": masque(sid) if sid else "",
            "secret": masque(token) if token else "",
            "numero_expediteur": self._numero_expediteur(),
            "numero_par_defaut": r.numero_par_defaut,
            "mode_local": self.mode_local,
            "envois_restants_cette_heure": self.compteur.restant,
            "en_attente": len(self.en_attente()),
            "explication": self.pourquoi_pas_pret() or (EXPLICATION_IPHONE if r.fournisseur == "iphone" else ""),
        }

    # ------------------------------------------------------------------ configuration
    def configurer_twilio(self, account_sid: str, auth_token: str, numero_expediteur: str) -> dict:
        """Range le compte d'envoi dans le coffre. Les identifiants ne ressortent jamais d'ici."""
        sid = (account_sid or "").strip()
        token = (auth_token or "").strip()
        if not sid or not token:
            raise TelephonieNonConfiguree("Account SID et Auth Token sont tous les deux nécessaires. " + MODE_EMPLOI_TWILIO)
        if not sid.startswith("AC") or len(sid) != 34:
            # Cause d'échec numéro un : coller le Message Service SID (MG…) ou une clé d'API (SK…)
            # à la place de l'Account SID. Le dire ici évite un « 20003 » incompréhensible plus tard.
            raise TelephonieNonConfiguree(
                "Un Account SID Twilio commence par « AC » et fait 34 caractères. Celui-ci n'y ressemble "
                "pas : c'est probablement une clé d'API (SK…) ou un identifiant de service (MG…)."
            )
        numero = normaliser_numero(numero_expediteur, self.reglages().indicatif_pays)
        self.secrets.set_site(NOM_COFFRE, sid, token)
        self.secrets.set_site(NOM_COFFRE_NUMERO, numero, "")
        log.info("Compte de téléphonie enregistré (les identifiants restent dans le coffre).")
        return self.etat()

    def oublier(self) -> dict:
        self.secrets.delete_site(NOM_COFFRE)
        self.secrets.delete_site(NOM_COFFRE_NUMERO)
        return self.etat()

    # ------------------------------------------------------------------ brouillon
    def _garde(self) -> None:
        """Tout ce qui doit être vrai avant même de rédiger. Lève une phrase française, sinon rien."""
        raison = self.pourquoi_pas_pret()
        if raison:
            raise TelephonieNonConfiguree(raison)
        if self.mode_local and self.fournisseur != "iphone":
            raise ModeLocalActif(
                "Le mode local est actif : rien ne quitte cet ordinateur, donc je n'envoie aucun message."
            )
        # Vérifiée AVANT la confirmation : mieux vaut dire « limite atteinte » tout de suite que de
        # faire relire un message à voix haute pour le refuser ensuite.
        self.compteur.verifier()

    def preparer_sms(self, destinataire: str, message: str) -> Brouillon:
        """Construit le SMS et n'envoie RIEN. Aucune connexion n'est ouverte ici."""
        self._garde()
        numero = normaliser_numero(destinataire, self.reglages().indicatif_pays)
        texte = (message or "").replace("\r\n", "\n").strip()
        if not texte:
            raise ErreurTelephonie("Le message est vide : je n'envoie pas un texto blanc.")
        if len(texte) > MAX_CARACTERES:
            segments = (len(texte) - 1) // TAILLE_SEGMENT + 1
            raise ErreurTelephonie(
                f"Ce message fait {len(texte)} caractères, soit {segments} segments facturés séparément. "
                f"Je m'arrête à {MAX_CARACTERES}. Raccourcis-le, ou envoie plutôt un courriel."
            )
        return Brouillon(genre="sms", numero=numero, texte=texte)

    def preparer_appel(self, numero: str) -> Brouillon:
        """Construit l'appel et ne compose RIEN."""
        self._garde()
        if self.fournisseur == "twilio":
            # Un appel parti d'un numéro loué s'affiche comme un inconnu chez le correspondant, qui
            # ne peut pas rappeler la vraie ligne — et IRIS n'aurait rien à dire une fois décroché.
            raise TelephonieNonConfiguree(
                "Je ne passe pas d'appel par un service Internet : ton correspondant verrait un numéro "
                "inconnu et ne pourrait pas te rappeler. Je prépare le numéro sur ton téléphone, "
                "et c'est ta ligne qui appelle."
            )
        return Brouillon(genre="appel", numero=normaliser_numero(numero, self.reglages().indicatif_pays))

    # ------------------------------------------------------------------ accord
    async def demander_accord(self, brouillon: Brouillon, confirmer: ConfirmFn) -> Autorisation | None:
        """Seule fabrique d'`Autorisation` du programme. Renvoie None si l'utilisateur n'a pas dit oui.

        `confirmer` est la fonction de ToolContext : elle publie la demande à l'écran et renvoie
        False si personne ne répond dans les 180 secondes. Un silence vaut donc un refus — c'est le
        bon sens de l'échec pour une action qu'on ne peut pas rattraper.
        """
        if confirmer is None:
            raise AutorisationInvalide("Aucun moyen de demander confirmation : je ne fais rien.")
        approuve = bool(await confirmer(brouillon.titre(), brouillon.apercu()))
        if not approuve:
            # Le registre consigne le refus autant que l'envoi : une trace qui ne montre que les
            # succès ne prouve rien.
            self._tracer("telephonie_refus", brouillon)
            log.info("Téléphonie : %s non confirmé.", brouillon.genre)
            return None
        return Autorisation(brouillon, _SCEAU)

    # ------------------------------------------------------------------ action
    def executer(self, autorisation: Autorisation) -> dict:
        """Agit sur le message approuvé. N'accepte QUE des `Autorisation` — jamais un brouillon nu."""
        if not isinstance(autorisation, Autorisation):
            raise AutorisationInvalide(
                "Je ne fais rien partir : ça n'a pas été confirmé. "
                "Demande-moi de te relire le message, puis confirme."
            )
        # Revérifiée ici, où c'est décisif : entre la préparation et l'accord, d'autres envois ont
        # pu passer. Vérifiée AVANT de consommer l'accord, pour qu'un refus de débit ne le brûle pas.
        self.compteur.verifier()
        brouillon = autorisation.consommer()
        # Enregistré avant d'agir, pas après : si un envoi Twilio se coupe en plein vol, on ne sait
        # pas s'il a été facturé. Compter une tentative de trop vaut mieux que d'en oublier dix.
        self.compteur.enregistrer()

        if self.fournisseur == "twilio":
            return self._envoyer_par_twilio(brouillon)
        return self._deposer_sur_le_telephone(brouillon)

    # --- voie 1 : le brouillon sur le téléphone ---
    def _deposer_sur_le_telephone(self, brouillon: Brouillon) -> dict:
        self._attente[brouillon.identifiant] = EnAttente(brouillon, self._horloge(), _maintenant_iso())
        self._tracer("telephonie_brouillon", brouillon)
        self._publier("telephone.brouillon", brouillon=brouillon.en_dict())
        quoi = "Le texto est prêt" if brouillon.genre == "sms" else "Le numéro est prêt"
        geste = "touche Envoyer" if brouillon.genre == "sms" else "touche Appeler"
        return {
            "ok": True,
            "envoye": False,  # capital : rien n'est parti, et IRIS ne doit pas dire le contraire
            "en_attente": True,
            "id": brouillon.identifiant,
            "numero": brouillon.numero,
            "genre": brouillon.genre,
            "lien_ios": brouillon.lien_ios(),
            "lien_android": brouillon.lien_android(),
            "message": f"{quoi} sur ton téléphone : {geste}.",
        }

    def en_attente(self) -> list[dict]:
        """Les brouillons que le téléphone doit afficher. Les périmés disparaissent d'eux-mêmes."""
        limite = self._horloge() - DUREE_BROUILLON
        for identifiant, entree in list(self._attente.items()):
            if entree.depose_a < limite:
                del self._attente[identifiant]
        return [
            {**e.brouillon.en_dict(), "depose_a": e.depose_iso}
            for e in sorted(self._attente.values(), key=lambda e: e.depose_a)
        ]

    def _retirer(self, identifiant: str) -> Brouillon:
        entree = self._attente.pop((identifiant or "").strip(), None)
        if entree is None:
            raise ErreurTelephonie(
                "Ce brouillon n'existe plus : il a déjà été traité, ou il a expiré au bout de quinze minutes."
            )
        return entree.brouillon

    def marquer_envoye(self, identifiant: str) -> dict:
        """Miguel a touché Envoyer sur son téléphone. On ferme et on inscrit au registre."""
        brouillon = self._retirer(identifiant)
        self._tracer("telephonie_envoye", brouillon)
        self._publier("telephone.brouillon_ferme", id=brouillon.identifiant, etat="envoye")
        return {"ok": True, "id": brouillon.identifiant, "message": "C'est noté, le message est parti de ton téléphone."}

    def marquer_annule(self, identifiant: str) -> dict:
        """Il a renoncé. On inscrit aussi : une trace qui ne montre que les succès ne prouve rien."""
        brouillon = self._retirer(identifiant)
        self._tracer("telephonie_annule", brouillon)
        self._publier("telephone.brouillon_ferme", id=brouillon.identifiant, etat="annule")
        return {"ok": True, "id": brouillon.identifiant, "message": "D'accord, je l'oublie."}

    # --- voie 2 : l'envoi réel, dormante ---
    def _envoyer_par_twilio(self, brouillon: Brouillon) -> dict:
        sid, token = self._identifiants()
        expediteur = self._numero_expediteur()
        if not (sid and token and expediteur):
            # Le compte a disparu du coffre entre l'accord et l'envoi (trousseau verrouillé,
            # session Windows changée). On le dit ; on ne prétend pas avoir envoyé.
            raise TelephonieNonConfiguree("Le compte d'envoi a disparu du coffre entre-temps. " + MODE_EMPLOI_TWILIO)
        if brouillon.genre != "sms":
            raise TelephonieNonConfiguree("Je ne passe pas d'appel par un service Internet.")

        envoyer = self._http or _client_http_par_defaut
        url = URL_TWILIO.format(sid=quote(sid, safe=""))
        donnees = {"To": brouillon.numero, "From": expediteur, "Body": brouillon.texte}
        try:
            reponse = envoyer(url, donnees, (sid, token), DELAI_HTTP)
        except Exception as erreur:
            log.error("Envoi SMS impossible : %s", _sans_secret(str(erreur), token, sid))
            # `from None` : la chaîne d'exceptions recopie l'en-tête Authorization dans les
            # journaux de certaines bibliothèques HTTP. Il n'a à être relu par personne.
            raise EnvoiEchoue(
                "Je n'ai pas réussi à joindre l'opérateur, et le message n'est pas parti. "
                f"À vérifier : la connexion internet, puis le pare-feu. Détail : "
                f"{_sans_secret(str(erreur), token, sid) or type(erreur).__name__}"
            ) from None

        statut = int(getattr(reponse, "status_code", 0) or 0)
        corps: dict = {}
        try:
            corps = reponse.json() or {}
        except Exception:
            corps = {}
        if not 200 <= statut < 300:
            raise EnvoiEchoue(self._expliquer_twilio(statut, corps, token, sid))

        self._tracer("telephonie_envoye", brouillon, tiers="twilio")
        log.info("SMS remis à l'opérateur (%s segment(s)).", brouillon.segments)
        return {
            "ok": True,
            "envoye": True,
            "en_attente": False,
            "id": brouillon.identifiant,
            "numero": brouillon.numero,
            "genre": "sms",
            "segments": brouillon.segments,
            "reference": str(corps.get("sid") or ""),
            "message": f"SMS envoyé à {numero_lisible(brouillon.numero)}.",
        }

    @staticmethod
    def _expliquer_twilio(statut: int, corps: dict, token: str, sid: str) -> str:
        """Transforme un code d'erreur en phrase qui dit quoi faire. Jamais d'identifiant dedans."""
        code = corps.get("code")
        detail = _sans_secret(str(corps.get("message") or ""), token, sid) or f"réponse HTTP {statut}"
        explications = {
            20003: "L'opérateur a refusé mes identifiants. Rien n'est parti. L'Auth Token a probablement été "
                   "régénéré depuis le tableau de bord : il faut me redonner le nouveau.",
            20429: "L'opérateur me demande de ralentir : trop de messages d'un coup. Rien n'est parti pour "
                   "celui-ci ; réessaie dans une minute.",
            21211: "Le numéro du destinataire a été refusé par l'opérateur. Rien n'est parti. Vérifie les chiffres.",
            21212: "Le numéro depuis lequel j'envoie a été refusé. Rien n'est parti : il faut vérifier le numéro "
                   "loué dans le tableau de bord.",
            21408: "L'envoi vers ce pays n'est pas activé sur le compte. Rien n'est parti. Cela s'active dans "
                   "les réglages de messagerie géographique du tableau de bord.",
            21606: "Le numéro d'envoi enregistré n'est pas un numéro capable d'envoyer des SMS. Rien n'est parti.",
            21610: "Ce destinataire a répondu STOP à un message précédent : l'opérateur bloque définitivement "
                   "les envois vers lui, et c'est la loi. Rien n'est parti. Écris-lui autrement.",
            21614: "Ce numéro n'est pas un mobile : il ne peut pas recevoir de SMS. Rien n'est parti.",
            30032: "Le numéro d'envoi n'est pas vérifié. Depuis le 31 janvier 2024, les opérateurs canadiens "
                   "bloquent tout numéro sans frais non vérifié. Rien n'est parti : la vérification se demande "
                   "dans le tableau de bord.",
        }
        if code in explications:
            return f"{explications[code]} (code {code})"
        if statut in (401, 403):
            return (
                "L'opérateur a refusé mes identifiants. Rien n'est parti. Il faut me redonner l'Account SID "
                f"et l'Auth Token. Réponse : {detail}"
            )
        if statut == 429:
            return f"L'opérateur me demande de ralentir. Rien n'est parti ; réessaie dans une minute. Réponse : {detail}"
        if statut >= 500:
            return f"L'opérateur est en panne de son côté. Rien n'est parti ; réessaie plus tard. Réponse : {detail}"
        return f"L'envoi a échoué et le message n'est pas parti. Réponse de l'opérateur : {detail}"

    # ------------------------------------------------------------------ chemins complets
    async def envoyer_sms_apres_accord(self, destinataire: str, message: str, confirmer: ConfirmFn) -> dict:
        """Le chemin qu'appelle l'outil `preparer_sms` : préparer, faire confirmer, agir.

        Aucun raccourci n'est possible : sans accord, il n'y a rien à passer à `executer()`.
        """
        brouillon = self.preparer_sms(destinataire, message)
        return await self._apres_accord(brouillon, confirmer)

    async def appeler_apres_accord(self, numero: str, confirmer: ConfirmFn) -> dict:
        brouillon = self.preparer_appel(numero)
        return await self._apres_accord(brouillon, confirmer)

    async def _apres_accord(self, brouillon: Brouillon, confirmer: ConfirmFn) -> dict:
        accord = await self.demander_accord(brouillon, confirmer)
        if accord is None:
            return {
                "ok": False,
                "envoye": False,
                "en_attente": False,
                "numero": brouillon.numero,
                "genre": brouillon.genre,
                "message": "Je n'ai rien fait : ça n'a pas été confirmé.",
            }
        # Twilio ouvre une connexion : hors de la boucle, sinon la voix se fige le temps de l'aller-retour.
        if self.fournisseur == "twilio":
            return await asyncio.to_thread(self.executer, accord)
        return self.executer(accord)

    # ------------------------------------------------------------------ traces
    def _tracer(self, evenement: str, brouillon: Brouillon, tiers: str = "") -> None:
        """Inscrit au registre infalsifiable. Le TEXTE du message n'y va pas.

        Le registre s'exporte en CSV et se lit à l'écran : le contenu d'un texto n'a rien à y
        traîner. Ce qu'il doit prouver, c'est qu'un message est parti, vers qui, et quand.
        """
        if self.registre is None:
            return
        detail = f"{brouillon.genre} vers {brouillon.numero}, {len(brouillon.texte)} caractères"
        if tiers:
            detail += f", remis à {tiers}"
        try:
            self.registre.log(evenement, agent="telephonie", detail=detail)
        except Exception as exc:  # une trace qui échoue ne doit pas empêcher IRIS de répondre
            log.warning("Registre indisponible pour %s : %s", evenement, exc)

    def _publier(self, type_: str, **donnees: Any) -> None:
        if self.hub is None:
            return
        try:
            self.hub.publish(type_, **donnees)
        except Exception as exc:
            log.warning("Publication %s impossible : %s", type_, exc)


def _client_http_par_defaut(url: str, donnees: dict, auth: tuple[str, str], delai: int) -> Any:
    """Client réel. Import local : `requests` n'a pas à être chargé tant que la voie iPhone est
    active — c'est-à-dire toujours, pour l'instant."""
    import requests

    return requests.post(url, data=donnees, auth=auth, timeout=delai)
