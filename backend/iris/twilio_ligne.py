"""La vraie ligne téléphonique d'IRIS chez Twilio : SMS et appels, sortants ET entrants.

Décision de Miguel, 7 septembre 2026 : donner à IRIS un vrai numéro, capable d'envoyer et de
recevoir des textos et des appels. Ce module est la plomberie de cette ligne. Il NE contient
aucune serrure de confirmation, aucune limite de débit, aucun contrôle de numéro : tout cela vit
déjà dans `telephonie.py`, et c'est `Telephoniste` qui appelle ce module APRÈS avoir obtenu
l'accord de l'utilisateur. Ici, on ne fait que parler HTTP à Twilio et écrire du TwiML.

CE QUI EST NOUVEAU PAR RAPPORT À LA VOIE « twilio » DORMANTE DE telephonie.py
-----------------------------------------------------------------------------
1. L'authentification. L'ancienne voie utilisait l'Account SID + l'Auth Token (le mot de passe
   maître du compte). Ici on utilise une CLÉ D'API : un couple (SID de clé « SK… », secret) que
   Twilio recommande, révocable sans toucher au compte, et qui ne donne pas tous les droits. En
   HTTP c'est la même authentification « Basic », mais l'utilisateur est le SID de la clé et le mot
   de passe est son secret ; l'URL, elle, porte toujours l'Account SID du compte.
2. Les identifiants viennent de l'ENVIRONNEMENT (fichier `backend/.env`, chargé par config.py),
   pas du coffre. C'est le même mécanisme que la clé ElevenLabs. Jamais en dur dans le code.
3. Les appels sortants sont possibles (l'ancienne voie les refusait). IRIS appelle depuis SON
   numéro loué et dit un message préparé, relu et approuvé — jamais un appel muet.
4. Les webhooks entrants existent : Twilio joint un serveur public quand un SMS ou un appel arrive.

LES QUATRE VALEURS À FOURNIR (Miguel), et pourquoi je ne peux pas les obtenir seule
-----------------------------------------------------------------------------------
- TWILIO_ACCOUNT_SID   : l'identifiant du compte, « AC… », en haut du tableau de bord Twilio.
- TWILIO_API_KEY_SID   : le SID de la clé d'API, « SK… ». (Fourni par Miguel le 7 septembre 2026 : il se met dans la configuration, jamais dans le code.)
- TWILIO_API_KEY_SECRET: le secret de cette clé, montré UNE SEULE FOIS à sa création. Irrécupérable
                         ensuite : si perdu, il faut créer une nouvelle clé.
- TWILIO_NUMBER        : le numéro loué, au format E.164 (« +1… »).
Créer une clé d'API et louer un numéro exigent une carte de crédit et une pièce d'identité : ce
sont des gestes que seul le titulaire du compte peut faire.

POUR RECEVOIR (entrants), DEUX VALEURS DE PLUS
----------------------------------------------
- TWILIO_AUTH_TOKEN    : l'Auth Token du compte. Twilio SIGNE chaque webhook avec lui (et non avec
                         le secret de la clé d'API : la signature ne connaît que l'Auth Token).
                         Sans lui, on ne peut PAS prouver qu'une requête vient vraiment de Twilio,
                         et le module refuse de traiter l'entrant plutôt que de faire confiance à
                         n'importe qui — c'est un serveur public.
- TWILIO_PUBLIC_BASE   : l'URL publique par laquelle Twilio nous joint, ex.
                         « https://iris.mondomaine.app ». Elle sert à recalculer la signature à
                         l'identique. Derrière un tunnel, l'hôte vu localement n'est pas celui que
                         Twilio a signé ; on ne devine pas, on le déclare.

PAS DE SDK TWILIO : appels HTTP directs avec `requests`, exactement comme telephonie.py. Le SDK
tirerait une dépendance de plus dans un exécutable déjà lourd pour deux points d'API et un HMAC de
vingt lignes. La signature entrante se calcule avec la bibliothèque standard (hmac, base64).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import quote
from xml.sax.saxutils import escape as _echapper_xml

log = logging.getLogger("iris.twilio_ligne")

# Le nom du fournisseur dans les réglages (config.UserSettings.telephonie.fournisseur).
FOURNISSEUR = "twilio_ligne"

# Noms des variables d'environnement. Une seule source de vérité pour le README et le .env.
ENV_ACCOUNT_SID = "TWILIO_ACCOUNT_SID"
ENV_API_KEY_SID = "TWILIO_API_KEY_SID"
ENV_API_KEY_SECRET = "TWILIO_API_KEY_SECRET"
ENV_NUMERO = "TWILIO_NUMBER"
ENV_AUTH_TOKEN = "TWILIO_AUTH_TOKEN"  # entrants seulement (validation de signature)
ENV_BASE_PUBLIQUE = "TWILIO_PUBLIC_BASE"  # entrants seulement (URL signée)
ENV_ACCUEIL_APPEL = "TWILIO_ACCUEIL_APPEL"  # message dit à qui appelle la ligne (facultatif)

URL_MESSAGES = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
URL_CALLS = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"

DELAI_HTTP = 20  # secondes ; au-delà, c'est une coupure réseau, pas un opérateur lent
LANGUE_VOIX = "fr-CA"

# Ce qu'IRIS dit par défaut quand elle appelle et qu'aucun message n'a été dicté.
MESSAGE_APPEL_DEFAUT = "Bonjour, c'est un appel passé pour vous par IRIS."
# Ce que la ligne répond à un appel entrant. Volontairement sobre : pas d'enregistrement de la voix
# de l'appelant par défaut (un répondeur stocke de l'audio chez un tiers ; on ne le fait pas sans
# décision explicite). Se personnalise par TWILIO_ACCUEIL_APPEL.
ACCUEIL_ENTRANT_DEFAUT = (
    "Bonjour, vous avez joint la ligne d'IRIS. Cette ligne ne prend pas les appels en direct. "
    "Envoyez plutôt un message texte, il sera lu. Merci et au revoir."
)

MODE_EMPLOI = (
    "Ma ligne Twilio n'est pas complète. Il me manque des informations que je ne peux pas obtenir "
    "seule (elles exigent le compte Twilio de Miguel) : le secret de la clé d'API (montré une seule "
    "fois à sa création), l'Account SID (AC…), et le numéro loué (+1…). Elles se rangent dans "
    "backend/.env sous TWILIO_API_KEY_SECRET, TWILIO_ACCOUNT_SID et TWILIO_NUMBER. En attendant, je "
    "peux préparer le message sur ton téléphone — c'est toi qui touches Envoyer."
)

# (url, données, (identifiant, secret), délai) -> réponse façon requests. Injecté dans les tests :
# aucun test de ce module ne touche le réseau.
ClientHTTP = Callable[[str, dict, tuple[str, str], int], Any]


# --------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class ConfigLigne:
    """Les identifiants de la ligne, lus dans l'environnement. Aucun secret n'est jamais journalisé.

    Gelée : une configuration se relit à chaque envoi (l'environnement peut changer au redémarrage),
    mais un objet donné ne se modifie pas sous les pieds de l'appelant.
    """

    account_sid: str = ""
    api_key_sid: str = ""
    api_key_secret: str = ""
    numero: str = ""
    auth_token: str = ""  # entrants seulement
    base_publique: str = ""  # entrants seulement
    accueil_appel: str = ""

    @classmethod
    def depuis_environnement(cls, environ: Mapping[str, str] | None = None) -> "ConfigLigne":
        env = environ if environ is not None else os.environ
        return cls(
            account_sid=(env.get(ENV_ACCOUNT_SID) or "").strip(),
            api_key_sid=(env.get(ENV_API_KEY_SID) or "").strip(),
            api_key_secret=(env.get(ENV_API_KEY_SECRET) or "").strip(),
            numero=(env.get(ENV_NUMERO) or "").strip(),
            auth_token=(env.get(ENV_AUTH_TOKEN) or "").strip(),
            base_publique=(env.get(ENV_BASE_PUBLIQUE) or "").strip().rstrip("/"),
            accueil_appel=(env.get(ENV_ACCUEIL_APPEL) or "").strip(),
        )

    @property
    def sortant_pret(self) -> bool:
        """Peut-on envoyer un SMS ou passer un appel ? Il faut l'Account SID, le numéro, et une
        authentification utilisable — soit (clé d'API + secret), soit l'Auth Token du compte."""
        return bool(self.account_sid and self.numero and self.auth()[1])

    @property
    def entrant_pret(self) -> bool:
        """Peut-on VÉRIFIER un webhook entrant ? Sans l'Auth Token, non — et on refuse alors."""
        return bool(self.auth_token)

    def manquant_sortant(self) -> list[str]:
        """Ce qui manque, nommé pour l'utilisateur, dans l'ordre où Twilio le présente."""
        pieces = [
            (self.account_sid, "l'Account SID (AC…, en haut du tableau de bord Twilio)"),
            # Une authentification suffit : le secret de la clé d'API, OU l'Auth Token du compte.
            (self.api_key_secret or self.auth_token, "le secret de la clé d'API (montré une seule fois à sa création) — ou, à défaut, l'Auth Token du compte"),
            (self.numero, "le numéro Twilio loué (au format +1 suivi de dix chiffres)"),
        ]
        return [phrase for valeur, phrase in pieces if not valeur]

    def auth(self) -> tuple[str, str]:
        """Le couple d'authentification HTTP Basic. Twilio accepte deux façons valides : (SID de la
        clé d'API, secret de la clé) si une clé d'API a été créée ; sinon on retombe sur
        (Account SID, Auth Token) — l'authentification « de base » du compte, celle du curl fourni."""
        if self.api_key_sid and self.api_key_secret:
            return (self.api_key_sid, self.api_key_secret)
        if self.account_sid and self.auth_token:
            return (self.account_sid, self.auth_token)
        return ("", "")

    @property
    def secrets_a_masquer(self) -> tuple[str, ...]:
        """Tout ce qui ne doit jamais paraître dans un journal ou un message d'erreur."""
        return tuple(s for s in (self.api_key_secret, self.auth_token) if s)

    def url_messages(self) -> str:
        return URL_MESSAGES.format(sid=quote(self.account_sid, safe=""))

    def url_calls(self) -> str:
        return URL_CALLS.format(sid=quote(self.account_sid, safe=""))

    def accueil(self) -> str:
        return self.accueil_appel or ACCUEIL_ENTRANT_DEFAUT


def client_http_par_defaut(url: str, donnees: dict, auth: tuple[str, str], delai: int) -> Any:
    """Client réel. Import local : `requests` n'a pas à être chargé si la ligne n'est pas utilisée."""
    import requests

    return requests.post(url, data=donnees, auth=auth, timeout=delai)


# --------------------------------------------------------------------------- TwiML
_ENTETE_XML = '<?xml version="1.0" encoding="UTF-8"?>'


def twiml_vide() -> str:
    """La réponse « je ne fais rien de plus » : accuse réception sans répondre à l'expéditeur.

    C'est volontaire pour un SMS entrant : IRIS n'envoie AUCUNE réponse automatique. Répondre
    automatiquement serait un envoi sans accord, exactement ce que toute la sécurité interdit.
    """
    return f"{_ENTETE_XML}<Response></Response>"


def twiml_dire(message: str, langue: str = LANGUE_VOIX) -> str:
    """TwiML d'un appel SORTANT : IRIS dit un message, puis raccroche."""
    return f'{_ENTETE_XML}<Response><Say language="{langue}">{_echapper_xml(message or MESSAGE_APPEL_DEFAUT)}</Say></Response>'


def twiml_accueil_entrant(message: str | None = None, langue: str = LANGUE_VOIX) -> str:
    """TwiML d'un appel ENTRANT : un accueil sobre, puis raccrochage. Pas d'enregistrement par défaut."""
    texte = message or ACCUEIL_ENTRANT_DEFAUT
    return f'{_ENTETE_XML}<Response><Say language="{langue}">{_echapper_xml(texte)}</Say><Hangup/></Response>'


# --------------------------------------------------------------------------- signature entrante
def valider_signature(auth_token: str, url: str, params: Mapping[str, str], signature: str) -> bool:
    """Vrai si `signature` (en-tête X-Twilio-Signature) prouve que la requête vient de Twilio.

    Algorithme de Twilio, formulaire encodé : on part de l'URL exacte que Twilio a appelée, on y
    concatène chaque paramètre POST — clé puis valeur, sans séparateur — dans l'ordre alphabétique
    des clés, puis HMAC-SHA1 avec l'Auth Token, encodé en base64. La comparaison est à temps
    constant : une comparaison naïve laisse fuir, octet par octet, où la signature diverge.

    Sans Auth Token ou sans en-tête, on renvoie faux : on ne « valide » jamais par défaut.
    """
    if not auth_token or not signature:
        return False
    base = url
    for cle in sorted(params):
        base += cle + str(params[cle])
    digest = hmac.new(auth_token.encode("utf-8"), base.encode("utf-8"), hashlib.sha1).digest()
    attendu = base64.b64encode(digest).decode("ascii")
    try:
        return hmac.compare_digest(attendu, signature)
    except Exception:
        return False


def sans_secret(texte: str, *secrets: str) -> str:
    """Efface les identifiants d'un texte destiné à un journal ou à l'écran (miroir de telephonie)."""
    propre = texte or ""
    for secret in secrets:
        secret = (secret or "").strip()
        if len(secret) < 8:  # un fragment trop court remplacerait des morceaux de phrase au hasard
            continue
        propre = propre.replace(secret, "•••")
    return propre
