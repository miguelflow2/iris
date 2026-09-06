"""Routes HTTP du courriel et de la téléphonie : ce que l'interface et le téléphone appellent.

POURQUOI CE FICHIER EXISTE — l'incident du 6 septembre 2026
-----------------------------------------------------------
Le journal d'exécution montrait IRIS annonçant « le texto est prêt sur ton téléphone : touche
Envoyer » pendant que RIEN n'apparaissait sur l'iPhone. `telephonie.py` faisait son travail :
il déposait le brouillon dans `Telephoniste._attente` et publiait « telephone.brouillon » sur le
hub. Mais aucune route ne permettait à la page /m de lire cette attente, et personne n'écoutait
l'événement. Le brouillon expirait au bout de quinze minutes, en silence. Un échec silencieux qui
ressemble à un succès : c'est la pire des deux issues, parce qu'on ne le cherche pas.

Même histoire pour le courriel : `Postier.configurer` existait, testé, et aucune interface ne
permettait d'y entrer le mot de passe d'application Gmail. IRIS savait écrire un courriel et
n'avait aucun moyen d'apprendre depuis quelle adresse.

Ce routeur ne fait que traduire des requêtes en appels de service. Il ne connaît ni SMTP, ni
Twilio, ni le coffre : `Postier` et `Telephoniste` s'en chargent, avec leurs propres tests.

PROTECTION
----------
Ce routeur ne porte PAS sa propre garde : il s'inclut dans `main.py` avec la même dépendance que
toutes les autres routes, celle qui accepte le jeton maître de l'application ou une session
ouverte avec le mot de passe (c'est par là que passe le téléphone) :

    app.include_router(creer_routeur(ctx), dependencies=auth)

`auth` est `[Depends(require_token)]`, exactement ce que /api/status exige. Aucune protection
n'est désactivée ici, et rien n'est ajouté non plus : une deuxième règle, différente, serait une
deuxième chose à casser. `tests/test_communications_api.py` vérifie que, inclus ainsi, chaque
route refuse un appel sans jeton.

SECRETS
-------
Aucune réponse de ce routeur ne contient un mot de passe ni un Auth Token, pas même une empreinte.
`SecretStore.mask` rend les quatre premiers et les quatre derniers caractères d'un secret : sur un
mot de passe d'application Google de seize lettres, c'est la moitié. On remplace donc ce champ
par des puces avant de répondre, quoi que le service ait mis dedans.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .courriel import ErreurCourriel
from .telephonie import ErreurTelephonie

log = logging.getLogger("iris.communications")

PUCES = "•" * 8
# Les champs qu'un état de service peut porter et qui décrivent un secret. Ils sortent d'ici
# sous forme de puces, jamais sous la forme que le service leur a donnée.
CHAMPS_SECRETS = ("secret", "mot_de_passe", "auth_token")

LIEN_MOTS_DE_PASSE_APPLICATION = "https://myaccount.google.com/apppasswords"


# --------------------------------------------------------------------------- corps des requêtes
class CompteCourriel(BaseModel):
    adresse: str = ""
    mot_de_passe_application: str = ""


class CompteTwilio(BaseModel):
    account_sid: str = ""
    auth_token: str = ""
    numero: str = ""


# --------------------------------------------------------------------------- outils
def sans_secrets(etat: dict) -> dict:
    """Copie de l'état dont les champs secrets sont réduits à des puces (ou vides s'ils l'étaient).

    Le service masque déjà ; on ne s'y fie pas. Trouvé en relisant `SecretStore.mask` : sur un
    Auth Token Twilio de 32 caractères, « f1e2…1100 » donne un quart du secret à qui lit la
    réponse, et la docstring de `Telephoniste.etat` promettait « jamais, même partiellement ».
    """
    propre = dict(etat or {})
    for champ in CHAMPS_SECRETS:
        if champ in propre:
            propre[champ] = PUCES if propre[champ] else ""
    return propre


def _tracer(ctx: Any, evenement: str, detail: str = "") -> None:
    """Inscrit un geste de configuration au registre, sans jamais y mettre un secret.

    Un registre qui tombe ne doit pas empêcher de configurer le courriel : on note et on continue.
    """
    registre = getattr(ctx, "consent", None)
    if registre is None:
        return
    try:
        registre.log(evenement, agent="communications", detail=detail)
    except Exception as exc:
        log.warning("Registre indisponible pour %s : %s", evenement, exc)


def _service(ctx: Any, nom: str, phrase: str) -> Any:
    """Le service demandé, ou une 503 en français s'il n'a pas été construit.

    Un AppContext sans postier n'existe pas aujourd'hui, mais un contexte de test peut en être
    dépourvu, et une AttributeError anonyme n'aide personne.
    """
    service = getattr(ctx, nom, None)
    if service is None:
        raise HTTPException(503, phrase)
    return service


# --------------------------------------------------------------------------- le routeur
def creer_routeur(ctx: Any) -> APIRouter:
    """Construit le routeur autour du contexte de l'application (`ctx.courriel`, `ctx.telephonie`).

    Il reçoit le contexte plutôt que les services un par un : `Postier` et `Telephoniste` peuvent
    être remplacés au démarrage (mode local, tests), et le routeur doit toujours parler au
    service en place, pas à celui qui existait quand il a été construit.
    """
    routeur = APIRouter(tags=["communications"])

    def postier() -> Any:
        return _service(ctx, "courriel", "Le service de courriel n'est pas disponible.")

    def telephoniste() -> Any:
        return _service(ctx, "telephonie", "Le service de téléphonie n'est pas disponible.")

    # ------------------------------------------------------------------ courriel
    @routeur.get("/api/courriel/etat")
    def courriel_etat() -> dict:
        """Ce que l'interface affiche : adresse, serveur, et si un compte est enregistré. Pas le secret."""
        etat = sans_secrets(postier().etat())
        etat["lien_mots_de_passe_application"] = LIEN_MOTS_DE_PASSE_APPLICATION
        return etat

    @routeur.post("/api/courriel/configurer")
    def courriel_configurer(body: CompteCourriel) -> dict:
        """Range l'adresse et le mot de passe d'application dans le coffre. Le secret n'en ressort pas."""
        try:
            etat = postier().configurer(body.adresse, body.mot_de_passe_application)
        except ErreurCourriel as exc:
            raise HTTPException(400, str(exc))
        _tracer(ctx, "courriel_configure", detail=str(etat.get("adresse") or ""))
        return sans_secrets(etat)

    @routeur.post("/api/courriel/tester")
    async def courriel_tester() -> dict:
        """Ouvre une connexion au serveur d'envoi et s'identifie, SANS envoyer le moindre message.

        Le SMTP bloque jusqu'à vingt secondes sur un port fermé : hors de la boucle, sinon la voix
        d'IRIS se fige le temps de l'attente.
        """
        try:
            resultat = await asyncio.to_thread(postier().tester_connexion)
        except ErreurCourriel as exc:
            raise HTTPException(400, str(exc))
        return sans_secrets(resultat)

    @routeur.delete("/api/courriel")
    def courriel_oublier() -> dict:
        """Efface le compte du coffre. IRIS ne pourra plus envoyer de courriel tant qu'on ne l'a pas redonné."""
        etat = postier().oublier()
        _tracer(ctx, "courriel_oublie")
        return sans_secrets(etat)

    # ------------------------------------------------------------------ téléphonie : état et compte
    @routeur.get("/api/telephonie/etat")
    def telephonie_etat() -> dict:
        return sans_secrets(telephoniste().etat())

    @routeur.post("/api/telephonie/configurer")
    def telephonie_configurer(body: CompteTwilio) -> dict:
        """Compte Twilio, optionnel et dormant : la voie active reste le brouillon sur le téléphone."""
        try:
            etat = telephoniste().configurer_twilio(body.account_sid, body.auth_token, body.numero)
        except ErreurTelephonie as exc:
            raise HTTPException(400, str(exc))
        _tracer(ctx, "telephonie_configuree", detail=str(etat.get("numero_expediteur") or ""))
        return sans_secrets(etat)

    @routeur.delete("/api/telephonie")
    def telephonie_oublier() -> dict:
        etat = telephoniste().oublier()
        _tracer(ctx, "telephonie_oubliee")
        return sans_secrets(etat)

    # ------------------------------------------------------------------ téléphonie : les brouillons
    @routeur.get("/api/telephonie/en_attente")
    def telephonie_en_attente() -> dict:
        """Les brouillons déposés pour le téléphone, du plus ancien au plus récent.

        C'est LA route qui manquait : c'est elle que la page /m sonde pour afficher « touche
        Envoyer » avec un vrai lien sms: ou tel:. Les périmés (quinze minutes) n'y figurent plus.
        """
        service = telephoniste()
        return {"brouillons": service.en_attente(), "voie": service.fournisseur}

    @routeur.post("/api/telephonie/{identifiant}/envoye")
    def telephonie_envoye(identifiant: str) -> dict:
        """Miguel a touché Envoyer sur son téléphone : le brouillon se ferme et le registre le note."""
        try:
            return telephoniste().marquer_envoye(identifiant)
        except ErreurTelephonie as exc:
            # « n'existe plus » : déjà traité, ou expiré. C'est une ressource absente, pas une faute.
            raise HTTPException(404, str(exc))

    @routeur.post("/api/telephonie/{identifiant}/annule")
    def telephonie_annule(identifiant: str) -> dict:
        try:
            return telephoniste().marquer_annule(identifiant)
        except ErreurTelephonie as exc:
            raise HTTPException(404, str(exc))

    return routeur
