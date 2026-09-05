"""Application FastAPI du serveur de licences VELA.

Points d'entrée :
    POST /paypal/webhook       — réception des événements PayPal (signature vérifiée)
    GET  /api/licence          — ce qu'IRIS interroge pour s'activer toute seule
    POST /api/licence/verifier — validation d'une clé
    GET  /sante                — état du service
    GET  /admin                — page d'administration (jeton obligatoire)
    POST /admin/emettre        — émission d'une clé à la main (jeton obligatoire)
"""
from __future__ import annotations

import hmac
import html
import json
import logging

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import __version__, cles
from .base import Base, normaliser
from .config import Config, charger
from .courriel import Facteur
from .limite import Limiteur, adresse_client
from .paypal import ClientPaypal, ErreurPaypal
from .service import Service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s : %(message)s",
)
log = logging.getLogger("licences.app")

# Journalisation : on n'écrit jamais de jeton, de signature ni de donnée de carte.
# PayPal ne transmet d'ailleurs aucun numéro de carte dans ses webhooks.


def creer_app(cfg: Config | None = None, base: Base | None = None,
              client_paypal: ClientPaypal | None = None, facteur: Facteur | None = None) -> FastAPI:
    cfg = cfg or charger()
    base = base or Base(cfg.base_donnees)
    service = Service(cfg, base, facteur)
    limiteur_general = Limiteur(cfg.limite_requetes, cfg.limite_fenetre)
    limiteur_licence = Limiteur(cfg.limite_licence_requetes, cfg.limite_fenetre)

    if client_paypal is None and cfg.paypal_configure:
        client_paypal = ClientPaypal(cfg.base_paypal, cfg.paypal_client_id, cfg.paypal_secret, cfg.paypal_webhook_id)

    app = FastAPI(title="Serveur de licences VELA", version=__version__, docs_url=None, redoc_url=None)
    app.state.cfg = cfg
    app.state.base = base
    app.state.service = service
    app.state.limiteur_general = limiteur_general
    app.state.limiteur_licence = limiteur_licence
    app.state.client_paypal = client_paypal

    # ================================================================== santé
    @app.get("/sante")
    def sante():
        """État du service. Ne révèle aucun secret, seulement ce qui est configuré ou non."""
        return {
            "etat": "ok",
            "version": __version__,
            "environnement": cfg.environnement,
            "paypal": {
                "configure": cfg.paypal_configure,
                "environnement": cfg.paypal_environnement,
                "verification_signature": not cfg.mode_dev_sans_verification,
            },
            "courriel": "smtp" if cfg.smtp_configure else "fichier",
            "administration": bool(cfg.jeton_admin),
            "abonnements_actifs": (base.un("SELECT COUNT(*) n FROM abonnements WHERE statut='actif'") or {"n": 0})["n"],
            "a_traiter_manuellement": len(base.manuels()),
        }

    # ================================================================== webhook PayPal
    @app.post("/paypal/webhook")
    async def webhook(requete: Request):
        corps_brut = await requete.body()
        try:
            evenement = json.loads(corps_brut.decode("utf-8"))
            if not isinstance(evenement, dict):
                raise ValueError("le corps n'est pas un objet JSON")
        except Exception as erreur:
            log.warning("Webhook illisible (%s) depuis %s.", erreur, adresse_client(requete))
            return JSONResponse({"erreur": "corps JSON invalide"}, status_code=400)

        type_evenement = evenement.get("event_type") or "(sans type)"

        # --- authentification de l'appel ------------------------------------
        if cfg.mode_dev_sans_verification and not cfg.production:
            log.warning("MODE DÉVELOPPEMENT : signature non vérifiée pour %s.", type_evenement)
        else:
            client = app.state.client_paypal
            if client is None:
                # Sans identifiants, impossible d'authentifier : on refuse plutôt que de croire l'appelant.
                log.error("Webhook %s refusé : PayPal n'est pas configuré (aucune vérification possible).",
                          type_evenement)
                return JSONResponse({"erreur": "vérification indisponible"}, status_code=400)
            try:
                valide = client.verifier_signature(dict(requete.headers), evenement)
            except ErreurPaypal as erreur:
                # Panne réseau ou API : ce n'est PAS une signature invalide. On répond 503 pour
                # que PayPal relance l'événement plus tard au lieu de l'abandonner.
                log.error("Vérification impossible pour %s : %s", type_evenement, erreur)
                return JSONResponse({"erreur": "vérification temporairement impossible"}, status_code=503)
            if not valide:
                log.warning("Signature invalide refusée : %s depuis %s (aucune écriture en base).",
                            type_evenement, adresse_client(requete))
                return JSONResponse({"erreur": "signature invalide"}, status_code=400)

        # --- traitement ------------------------------------------------------
        try:
            resultat = service.traiter(evenement)
        except Exception:
            log.exception("Erreur inattendue en traitant %s.", type_evenement)
            return JSONResponse({"erreur": "erreur interne"}, status_code=500)

        # La clé n'est jamais renvoyée à PayPal.
        public = {c: v for c, v in resultat.items() if c != "cle"}
        return JSONResponse({"recu": True, **public}, status_code=200)

    # ================================================================== licence (IRIS)
    @app.post("/api/licence")
    async def lire_licence_post(requete: Request):
        """Même chose, mais le courriel voyage dans le corps.

        C'est la forme à préférer : en GET, l'adresse du client se retrouve dans les journaux du
        serveur, dans ceux de tout intermédiaire, et dans les en-têtes de provenance. Le GET
        ci-dessous reste servi pour les versions d'IRIS déjà installées."""
        try:
            corps = await requete.json()
        except Exception:
            corps = {}
        return lire_licence(requete, str((corps or {}).get("email") or ""))

    @app.get("/api/licence")
    def lire_licence(requete: Request, email: str = ""):
        """Ce qu'IRIS appelle au démarrage pour s'activer toute seule.

        Anti-énumération : limite de débit stricte par IP, et réponse identique pour un courriel
        inconnu, un abonnement expiré ou un abonnement résilié.
        """
        ip = adresse_client(requete)
        if not limiteur_licence.autoriser(ip):
            log.warning("Limite de débit atteinte sur /api/licence pour %s.", ip)
            return JSONResponse(
                {"erreur": "trop de requêtes", "message": "Trop de requêtes. Réessayez dans une minute."},
                status_code=429, headers={"Retry-After": str(cfg.limite_fenetre)},
            )
        courriel = normaliser(email)
        if not courriel or "@" not in courriel:
            # Même forme de réponse qu'un courriel inconnu : rien à apprendre ici.
            return {"actif": False, "plan": "gratuit", "expire_le": None, "cle": None}
        return service.licence(courriel)

    @app.post("/api/licence/verifier")
    async def verifier_licence(requete: Request):
        """Valide une clé (JSON {"cle": "IRIS-..."} ou {"key": "..."})."""
        ip = adresse_client(requete)
        if not limiteur_general.autoriser(ip):
            return JSONResponse({"erreur": "trop de requêtes"}, status_code=429,
                                headers={"Retry-After": str(cfg.limite_fenetre)})
        try:
            donnees = json.loads((await requete.body()).decode("utf-8") or "{}")
        except Exception:
            return JSONResponse({"erreur": "corps JSON invalide"}, status_code=400)
        cle = (donnees.get("cle") or donnees.get("key") or "") if isinstance(donnees, dict) else ""
        return service.verifier(str(cle))

    # ================================================================== administration
    def jeton_valide(requete: Request, jeton_formulaire: str = "") -> bool:
        """Compare le jeton en temps constant. Sans IRIS_JETON_ADMIN, l'administration est fermée."""
        if not cfg.jeton_admin:
            return False
        fourni = (
            requete.headers.get("x-jeton-admin")
            or requete.query_params.get("jeton")
            or jeton_formulaire
            or ""
        )
        return hmac.compare_digest(fourni, cfg.jeton_admin)

    @app.get("/admin", response_class=HTMLResponse)
    def admin(requete: Request):
        if not cfg.jeton_admin:
            return PlainTextResponse("Administration désactivée : définissez IRIS_JETON_ADMIN.", status_code=404)
        if not jeton_valide(requete):
            log.warning("Accès administration refusé depuis %s.", adresse_client(requete))
            return PlainTextResponse("Jeton d'administration manquant ou invalide.", status_code=401)
        return HTMLResponse(_page_admin(base, requete.query_params.get("jeton", ""),
                                        requete.query_params.get("message", "")))

    @app.post("/admin/emettre")
    def admin_emettre(requete: Request, courriel: str = Form(""), plan: str = Form("pro"),
                      mois: int = Form(1), raison: str = Form("paiement hors PayPal"),
                      jeton: str = Form("")):
        """Émet une clé à la main : virement, comptant, geste commercial, clé perdue."""
        if not jeton_valide(requete, jeton):
            log.warning("Émission manuelle refusée depuis %s.", adresse_client(requete))
            return PlainTextResponse("Jeton d'administration manquant ou invalide.", status_code=401)
        try:
            resultat = service.emettre_manuellement(courriel, plan, max(1, int(mois)), raison or "manuel")
        except ValueError as erreur:
            return JSONResponse({"erreur": str(erreur)}, status_code=400)
        log.info("Clé émise à la main pour %s (%s, %s mois).", resultat["courriel"], plan, mois)
        return JSONResponse({"ok": True, **resultat})

    @app.post("/admin/resoudre")
    def admin_resoudre(requete: Request, identifiant: int = Form(0), jeton: str = Form("")):
        """Marque un dossier « à traiter manuellement » comme réglé."""
        if not jeton_valide(requete, jeton):
            return PlainTextResponse("Jeton d'administration manquant ou invalide.", status_code=401)
        base.executer("UPDATE manuel SET resolu=1 WHERE id=?", (int(identifiant),))
        return JSONResponse({"ok": True})

    return app


# ---------------------------------------------------------------------- page d'administration
def _page_admin(base: Base, jeton: str, message: str = "") -> str:
    def e(valeur) -> str:
        return html.escape("" if valeur is None else str(valeur))

    abonnements = base.tous("SELECT * FROM abonnements ORDER BY maj_le DESC LIMIT 200")
    evenements = base.tous("SELECT * FROM evenements ORDER BY id DESC LIMIT 50")
    manuels = base.manuels()

    lignes_abo = "".join(
        f"<tr><td>{e(a['courriel'])}</td><td>{e(a['plan'])}</td><td>{e(a['expire_le'])}</td>"
        f"<td class='s-{e(a['statut'])}'>{e(a['statut'])}</td><td>{e(a['abonnement_paypal'] or '—')}</td>"
        f"<td class='cle'>{e(a['derniere_cle'] or '—')}</td><td>{e(a['maj_le'])}</td></tr>"
        for a in abonnements
    ) or "<tr><td colspan='7'>Aucun abonnement.</td></tr>"

    lignes_ev = "".join(
        f"<tr><td>{e(v['recu_le'])}</td><td>{e(v['type'])}</td><td>{e(v['courriel'] or '—')}</td>"
        f"<td>{e(v['montant'] if v['montant'] is not None else '—')} {e(v['devise'] or '')}</td>"
        f"<td>{e(v['resultat'])}</td><td>{e(v['detail'])}</td></tr>"
        for v in evenements
    ) or "<tr><td colspan='6'>Aucun événement.</td></tr>"

    lignes_manuel = "".join(
        f"<tr><td>#{e(m['id'])}</td><td>{e(m['courriel'] or '—')}</td>"
        f"<td>{e(m['montant'])} {e(m['devise'] or '')}</td><td>{e(m['raison'])}</td><td>{e(m['cree_le'])}</td></tr>"
        for m in manuels
    ) or "<tr><td colspan='5'>Rien à traiter.</td></tr>"

    alerte = f"<p class='alerte'>{e(message)}</p>" if message else ""
    options = "".join(f"<option value='{p}'>{cles.ETIQUETTES[p]}</option>" for p in cles.PLANS_PAYANTS)

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Licences VELA — administration</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<style>
 body {{ font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; background: #101418; color: #e6e9ee; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }} h2 {{ font-size: 15px; margin: 28px 0 8px; color: #9fb3c8; }}
 .sous {{ color: #7d8b9a; margin: 0 0 20px; }}
 table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px; }}
 th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #232a33; vertical-align: top; }}
 th {{ color: #9fb3c8; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
 .cle {{ font-family: ui-monospace, Consolas, monospace; font-size: 11px; word-break: break-all; max-width: 320px; }}
 .s-actif {{ color: #6ee7a8; }} .s-annule {{ color: #f0b775; }}
 .s-expire {{ color: #8b98a6; }} .s-paiement_echoue {{ color: #f08a8a; }}
 form {{ background: #161c23; padding: 16px; border-radius: 8px; display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }}
 label {{ display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #9fb3c8; }}
 input, select {{ background: #0d1116; color: #e6e9ee; border: 1px solid #2b3441; border-radius: 5px; padding: 7px 9px; font: inherit; }}
 button {{ background: #3b82f6; color: #fff; border: 0; border-radius: 5px; padding: 8px 16px; font: inherit; cursor: pointer; }}
 .alerte {{ background: #1d2a1f; border-left: 3px solid #6ee7a8; padding: 10px 14px; border-radius: 4px; }}
 #resultat {{ font-family: ui-monospace, Consolas, monospace; font-size: 12px; white-space: pre-wrap; word-break: break-all; margin-top: 10px; }}
</style></head><body>
<h1>Licences VELA</h1>
<p class="sous">{len(abonnements)} abonnement(s) · {len(manuels)} dossier(s) à traiter à la main</p>
{alerte}

<h2>Émettre une clé à la main</h2>
<form id="f" method="post" action="/admin/emettre">
  <input type="hidden" name="jeton" value="{e(jeton)}">
  <label>Courriel<input name="courriel" type="email" required placeholder="client@exemple.com" size="28"></label>
  <label>Plan<select name="plan">{options}</select></label>
  <label>Mois<input name="mois" type="number" value="1" min="1" max="36" style="width:70px"></label>
  <label>Raison<input name="raison" value="paiement hors PayPal" size="24"></label>
  <button type="submit">Émettre et envoyer</button>
</form>
<div id="resultat"></div>

<h2>Abonnements</h2>
<table><thead><tr><th>Courriel</th><th>Plan</th><th>Expire le</th><th>Statut</th><th>Abo PayPal</th><th>Dernière clé</th><th>Mise à jour</th></tr></thead>
<tbody>{lignes_abo}</tbody></table>

<h2>À traiter manuellement</h2>
<table><thead><tr><th>#</th><th>Courriel</th><th>Montant</th><th>Raison</th><th>Reçu le</th></tr></thead>
<tbody>{lignes_manuel}</tbody></table>

<h2>50 derniers événements</h2>
<table><thead><tr><th>Reçu le</th><th>Type</th><th>Courriel</th><th>Montant</th><th>Résultat</th><th>Détail</th></tr></thead>
<tbody>{lignes_ev}</tbody></table>

<script>
document.getElementById('f').addEventListener('submit', async (ev) => {{
  ev.preventDefault();
  const sortie = document.getElementById('resultat');
  sortie.textContent = 'Émission en cours…';
  const reponse = await fetch('/admin/emettre', {{ method: 'POST', body: new FormData(ev.target) }});
  const texte = await reponse.text();
  try {{
    const donnees = JSON.parse(texte);
    sortie.textContent = donnees.ok
      ? `Clé pour ${{donnees.courriel}} (${{donnees.plan}}, jusqu'au ${{donnees.expire_le}}) — envoi : ${{donnees.courriel_envoi}}\\n${{donnees.cle}}`
      : `Erreur : ${{donnees.erreur}}`;
  }} catch {{ sortie.textContent = texte; }}
}});
</script>
</body></html>"""
