"""Webhooks ENTRANTS de la ligne Twilio d'IRIS : recevoir un SMS, recevoir un appel.

Twilio joint un serveur PUBLIC quand un message ou un appel arrive sur le numéro loué. Ces routes
sont ce serveur, côté backend d'IRIS.

DEUX DIFFÉRENCES CAPITALES AVEC routes_communications.py
--------------------------------------------------------
1. Elles NE portent PAS la garde `require_token`. Twilio n'a pas de jeton de session à présenter :
   c'est un tiers qui appelle de l'extérieur. On les inclut donc SANS `dependencies=auth`, et à la
   place chaque route exige une SIGNATURE Twilio valide. C'est le seul modèle qui tient : une route
   protégée par jeton refuserait tous les appels de Twilio, une route sans aucune protection
   accepterait ceux de n'importe qui.
2. Elles échouent FERMÉ. Pas d'Auth Token pour vérifier la signature = 503, pas 200. On ne traite
   jamais une requête qu'on ne peut pas prouver. C'est le même choix que le serveur de licences,
   qui refuse de démarrer sans de quoi vérifier les webhooks PayPal.

IL FAUT UNE URL PUBLIQUE
------------------------
localhost:8765 n'est pas joignable depuis Twilio. Il faut exposer ces routes derrière une URL
publique — le tunnel Cloudflare existant (`scripts/deployer-serveur.ps1` / `installer-tunnel.ps1`),
ou tout autre reverse-proxy. Cette URL doit être déclarée à Twilio (console du numéro → « A message
comes in » / « A call comes in ») ET donnée à IRIS via TWILIO_PUBLIC_BASE, pour recalculer la
signature à l'identique. Ces routes ne montent PAS le tunnel elles-mêmes et ne touchent PAS
serveur/relais.py : elles se contentent d'exister et d'attendre d'être jointes.

CE QU'ELLES NE FONT PAS
-----------------------
Aucune réponse automatique à un SMS entrant. Répondre tout seul serait un envoi sans accord —
exactement ce que toute la sécurité d'IRIS interdit. La ligne accuse réception (TwiML vide) et
prévient le bureau ; c'est IRIS, avec Miguel, qui décidera de répondre, en repassant par la
confirmation. L'appel entrant reçoit un accueil sobre et raccroche, sans enregistrer la voix de
l'appelant par défaut.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request, Response

from . import twilio_ligne

log = logging.getLogger("iris.twilio_webhooks")

TYPE_XML = "application/xml"


def _config(ctx: Any) -> twilio_ligne.ConfigLigne:
    """La MÊME configuration que celle qu'utilise le Telephoniste pour envoyer : une seule source.

    On la lit à travers le service quand il existe (les tests peuvent y injecter une config hors
    environnement), sinon directement dans l'environnement."""
    tele = getattr(ctx, "telephonie", None)
    lecteur = getattr(tele, "_config_ligne", None)
    if callable(lecteur):
        try:
            return lecteur()
        except Exception as exc:  # pragma: no cover - le service ne devrait pas lever ici
            log.warning("Config de ligne illisible via le service : %s", exc)
    return twilio_ligne.ConfigLigne.depuis_environnement()


def _tracer(ctx: Any, evenement: str, detail: str = "") -> None:
    """Inscrit au registre de transparence sans jamais y mettre le CONTENU d'un message."""
    registre = getattr(ctx, "consent", None)
    if registre is None:
        return
    try:
        registre.log(evenement, agent="telephonie", detail=detail)
    except Exception as exc:
        log.warning("Registre indisponible pour %s : %s", evenement, exc)


def _publier(ctx: Any, type_: str, **donnees: Any) -> None:
    hub = getattr(ctx, "hub", None)
    if hub is None:
        return
    try:
        hub.publish(type_, **donnees)
    except Exception as exc:
        log.warning("Publication %s impossible : %s", type_, exc)


def _url_signee(request: Request, config: twilio_ligne.ConfigLigne) -> str:
    """L'URL EXACTE que Twilio a signée. Derrière un tunnel, ce n'est pas request.url : l'hôte vu
    localement diffère de l'hôte public. On préfère donc TWILIO_PUBLIC_BASE ; à défaut, on
    reconstruit depuis les en-têtes que le proxy pose (X-Forwarded-*)."""
    chemin = request.url.path
    requete = f"?{request.url.query}" if request.url.query else ""
    if config.base_publique:
        return f"{config.base_publique}{chemin}{requete}"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    hote = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{hote}{chemin}{requete}"


async def _params(request: Request) -> dict[str, str]:
    """Les paramètres POST tels que Twilio les envoie et les signe.

    Twilio poste en `application/x-www-form-urlencoded` : on lit le corps brut et on le décode avec
    la bibliothèque standard, plutôt que `request.form()` — qui exigerait la dépendance
    python-multipart pour deux ou trois champs. Les valeurs décodées sont exactement celles sur
    lesquelles porte la signature Twilio."""
    corps = (await request.body()).decode("utf-8", "replace")
    return dict(parse_qsl(corps, keep_blank_values=True))


def _exiger_signature(request: Request, params: dict[str, str], config: twilio_ligne.ConfigLigne) -> None:
    """Refuse tout ce qui n'est pas prouvé venir de Twilio. Échoue FERMÉ, jamais ouvert."""
    if not config.entrant_pret:
        raise HTTPException(
            503,
            "La ligne entrante n'est pas configurée : il manque TWILIO_AUTH_TOKEN, sans lequel je ne "
            "peux pas prouver qu'une requête vient bien de Twilio. Je refuse de traiter un webhook non "
            "vérifiable sur un serveur public.",
        )
    signature = request.headers.get("x-twilio-signature", "")
    url = _url_signee(request, config)
    if not twilio_ligne.valider_signature(config.auth_token, url, params, signature):
        # On ne dit pas POURQUOI la signature est invalide (URL ? clé ? rejeu ?) : à un tiers qui
        # sonde, chaque détail est une aide. Le journal, lui, garde de quoi diagnostiquer.
        log.warning("Webhook Twilio refusé : signature invalide pour %s", url)
        raise HTTPException(403, "Signature Twilio invalide : requête refusée.")


def creer_routeur_twilio(ctx: Any) -> APIRouter:
    """Le routeur des entrants. Inclus dans main.py SANS `dependencies=auth` : la signature protège."""
    routeur = APIRouter(tags=["twilio-entrant"])

    @routeur.post("/twilio/entrant/sms")
    async def sms_entrant(request: Request) -> Response:
        """Un SMS est arrivé sur la ligne d'IRIS. On accuse réception, on prévient, on NE répond PAS seul."""
        config = _config(ctx)
        params = await _params(request)
        _exiger_signature(request, params, config)
        de = params.get("From", "")
        vers = params.get("To", "")
        corps = params.get("Body", "")
        # Registre : l'expéditeur et la taille, jamais le contenu (il s'exporte en CSV et se lit à l'écran).
        _tracer(ctx, "telephonie_sms_recu", detail=f"de {de}, {len(corps)} caractères")
        # Hub : le contenu va au bureau/à /m, pour que Miguel LISE le message reçu. C'est le sien.
        _publier(ctx, "telephone.sms_entrant", de=de, vers=vers, corps=corps,
                 reference=params.get("MessageSid", ""))
        return Response(content=twilio_ligne.twiml_vide(), media_type=TYPE_XML)

    @routeur.post("/twilio/entrant/appel")
    async def appel_entrant(request: Request) -> Response:
        """Un appel arrive. Accueil sobre, puis raccrochage. La voix de l'appelant n'est pas enregistrée."""
        config = _config(ctx)
        params = await _params(request)
        _exiger_signature(request, params, config)
        de = params.get("From", "")
        _tracer(ctx, "telephonie_appel_recu", detail=f"de {de}")
        _publier(ctx, "telephone.appel_entrant", de=de, vers=params.get("To", ""),
                 reference=params.get("CallSid", ""))
        return Response(content=twilio_ligne.twiml_accueil_entrant(config.accueil()), media_type=TYPE_XML)

    @routeur.post("/twilio/statut")
    async def rappel_statut(request: Request) -> Response:
        """Rappel de statut d'un envoi/appel sortant (remis, échoué…). Signé comme le reste."""
        config = _config(ctx)
        params = await _params(request)
        _exiger_signature(request, params, config)
        reference = params.get("MessageSid") or params.get("CallSid") or ""
        statut = params.get("MessageStatus") or params.get("CallStatus") or ""
        _tracer(ctx, "telephonie_statut", detail=f"{reference}: {statut}")
        _publier(ctx, "telephone.statut", reference=reference, statut=statut)
        return Response(content=twilio_ligne.twiml_vide(), media_type=TYPE_XML)

    return routeur
