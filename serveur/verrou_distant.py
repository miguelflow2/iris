"""Verrouillage à distance, côté relais : la page publique /verrou et la transmission de la commande au PC.

Le scénario : l'ordinateur est perdu ou volé. Depuis n'importe quel navigateur, le propriétaire ouvre
/verrou, donne son courriel VELA, son CODE DE SECOURS (choisi sur l'ordinateur) et l'action : verrouiller,
ou effacer les données d'IRIS. La commande part vers l'ordinateur LIÉ à ce courriel, par le canal sortant
que celui-ci tient déjà ouvert (/appareil/ws, voir relais.py).

Protocole (constat bloquant du 2026-09-14 : le code transitait en clair, et n'importe quelle machine qui se
disait « l'ordinateur de ce courriel » le recevait) :
1. seul un ordinateur LIÉ au courriel (clé confirmée par un lien envoyé à cette adresse, puis défi-réponse à
   chaque connexion : relais.liaison_confirmee, relais._defi_ordinateur) reçoit des messages « verrou » ;
2. le code ne quitte JAMAIS le navigateur. POST /api/verrou/defi rend le sel publié par l'ordinateur lié et un
   nonce à usage unique tiré ici ; la page calcule cle = PBKDF2-SHA256(code, sel) puis
   preuve = HMAC-SHA256(cle, « vela-verrou|v1|action|nonce ») et n'envoie que la preuve. L'ordinateur la
   vérifie avec la clé qu'il garde, refuse un nonce déjà vu ou trop vieux : rien n'est rejouable, et le relais
   n'apprend pas le code ;
3. l'ordinateur ne répond « verrouillé » qu'avec confirmation = HMAC-SHA256(cle, « vela-verrou-resultat|v1|
   etat|nonce|defi_page ») ; la page n'affiche le succès que si cette confirmation se vérifie avec sa propre clé
   (ni le relais ni une autre machine ne peuvent la fabriquer sans le code).

Ce que le relais fait, et ne fait pas :
- il ne connaît ni le code ni la clé qui en dérive ; il voit passer des preuves. Limite dite telle quelle : une
  preuve permet, à qui la détient (le relais lui-même, par exemple), de tester des codes hors ligne ; un code
  long rend cette recherche impraticable ;
- réponses uniformes : un courriel inconnu, sans ordinateur lié ou dont l'ordinateur est hors ligne reçoit un
  sel (factice si besoin) et la même réponse « transmise » (202) ; seul le résultat, s'il arrive, diffère ;
- la commande attend l'ordinateur EN MÉMOIRE (72 h au plus). Si le relais redémarre, elle est perdue : la page
  le dit ;
- finition B du 2026-09-14 : la file d'un courriel comptait 3 commandes, sans éviction, et répondait 429
  « file_pleine » au-delà. Trois preuves bidon (le courriel se lit sur le portable volé) empêchaient le
  propriétaire de mettre en file l'effacement de son ordinateur hors ligne, jusqu'à 72 h ; et la différence
  202/429 disait en quelques secondes si l'ordinateur lié était en ligne (en ligne, la file se vide). Désormais
  la file est comptée PAR ADRESSE IP : une commande par adresse (une nouvelle venue de la même adresse remplace
  la précédente — le propriétaire qui corrige son code), ATTENTES_PAR_COURRIEL adresses au plus ; quand la file
  est pleine, la commande la plus ancienne venue d'une AUTRE adresse cède sa place. La réponse est TOUJOURS
  202 avec un suivi, gardée ou non : le suivi se lit « en attente » puis « non confirmée », exactement comme
  une commande refusée. Limite dite : un tiers qui enverrait sans relâche des preuves depuis de nombreuses
  adresses finirait par faire céder la commande du propriétaire, qui devrait la renvoyer ;
- les commandes de la file partent comme un LOT (« differee », « lot », « reste ») : l'ordinateur ne compte pas
  comme échecs les preuves erronées d'un lot qui contient la bonne ;
- limitation : 5 commandes par 15 minutes, par courriel ET par adresse IP (20 défis). Revers assumé, écrit
  sur la page : quelqu'un qui connaît le courriel peut bloquer la page pour ce courriel pendant 15 minutes, et
  recommencer tant qu'il insiste (l'ordinateur compte de même 5 codes erronés par 15 minutes), sans jamais
  pouvoir agir sans le code. Choix : protéger le code contre les essais en ligne plutôt que garantir l'accès à
  la page ;
- contre-vérification du 2026-09-14 : le suivi ne révèle plus l'état de l'ordinateur. Un refus rendu en
  quelques secondes (« code refusé ») disait à quiconque envoie une preuve bidon que l'ordinateur lié est en
  ligne. Désormais tout ce qui n'est pas un succès reste « en attente » pendant DELAI_UNIFORME_S, puis devient
  « non confirmée » avec le même message, que l'ordinateur ait refusé, n'ait pas répondu ou soit hors ligne ;
  seul un succès (verrouillé, effacé), que seul l'ordinateur lié produit avec le bon code, est dit tel quel.

Réponse de l'ordinateur : il la renvoie sous le type « resultat » avec le req_id reçu. Le routage de relais.py
(`_req_en_cours`) la remet à un destinataire factice (`_Attente`) ; relais.py n'accepte cette réponse que de
l'ordinateur lié (entrée marquée « verrou »).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("vela.verrou_distant")

MAX_TENTATIVES = 5
DEFIS_MAX = 20
FENETRE_S = 900.0  # 15 minutes
DELAI_REPONSE_S = 15.0
DUREE_DEFI_S = 600.0
NONCES_MAX = 10_000
ATTENTE_MAX_S = 72 * 3600.0
ATTENTES_PAR_COURRIEL = 20  # adresses IP distinctes dont une commande attend le même ordinateur (une par adresse)
ATTENTES_TOTAL_MAX = 5_000
SUIVI_GARDE_S = 24 * 3600.0
INTERVALLE_LIVRAISON_S = 2.0
DELAI_UNIFORME_S = 45.0  # avant, tout résultat autre qu'un succès se lit « en attente »
ETATS_SUCCES = ("verrouille", "efface", "efface_partiel")
ITERATIONS_DEFAUT = 240_000  # celles de l'ordinateur (backend/iris/verrou.py) : un sel factice ne se distingue pas
ACTIONS = ("verrouiller", "effacer")
_COURRIEL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")

MESSAGE_TRANSMISE = (
    "Commande transmise au relais. Si votre ordinateur est allumé, connecté et lié à votre compte, sa réponse "
    "arrive en quelques secondes. Sinon, la commande attend sa reconnexion, en mémoire seulement, pendant "
    "72 heures au plus : si le relais redémarre (mise à jour, mise en veille du serveur), elle est perdue et il "
    "faudra recommencer. Gardez cette page ouverte pour voir le résultat confirmé."
)
MESSAGE_SANS_REPONSE = (
    "La commande a été transmise à votre ordinateur, mais il n'a pas répondu dans les 15 secondes : "
    "impossible de confirmer qu'elle a été exécutée."
)
MESSAGE_NON_CONFIRMEE = (
    "Aucune réponse confirmée par votre ordinateur pour l'instant : impossible de confirmer que la commande a été "
    "exécutée. Causes possibles : l'ordinateur est éteint ou hors ligne (la commande attend alors sa reconnexion, "
    "tant que le relais ne redémarre pas), le code de secours est erroné, le verrouillage à distance est désactivé "
    "ou son code est à redéfinir sur l'ordinateur, ou trop de codes erronés ont été essayés récemment. Par "
    "sécurité, la page ne dit pas laquelle : quelqu'un qui connaît votre courriel ne doit pas apprendre si votre "
    "ordinateur est en ligne. Gardez la page ouverte : un succès confirmé s'affichera s'il arrive."
)
MESSAGE_DEFI_EXPIRE = "La préparation de la commande a expiré ou a déjà servi : recommencez."
ENTETES_PAGE = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # La page manipule un code capable d'effacer les données : rien d'externe ne se charge, rien ne part
    # ailleurs que vers le relais lui-même, et un envoi natif du formulaire (code dans l'adresse) est bloqué.
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex",
}


class _Attente:
    """Destinataire factice inscrit dans relais._req_en_cours : reçoit la réponse de l'ordinateur."""

    def __init__(self) -> None:
        self.boucle = asyncio.get_running_loop()
        self.futur: asyncio.Future = self.boucle.create_future()

    def _poser(self, message: Any) -> None:
        if not self.futur.done():
            self.futur.set_result(message)

    async def send_json(self, message: Any) -> None:
        try:
            courante = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            courante = None
        if courante is self.boucle:
            self._poser(message)
        else:  # le WebSocket de l'ordinateur peut vivre dans une autre boucle (serveur de test)
            self.boucle.call_soon_threadsafe(self._poser, message)


def _adresse_ip(request: Request) -> str:
    """L'adresse du navigateur. Derrière le mandataire de l'hébergeur (et le tunnel), request.client est
    le mandataire, le même pour tout le monde : on prend la DERNIÈRE entrée de X-Forwarded-For, celle
    qu'ajoute le mandataire le plus proche (le client peut forger les premières, pas celle-là)."""
    transmis = request.headers.get("x-forwarded-for", "")
    if transmis.strip():
        return transmis.split(",")[-1].strip()[:64]
    return ((request.client.host if request.client else "") or "inconnue")[:64]


def _publique(reponse: dict) -> dict:
    """Ce qu'on rend au navigateur : jamais d'identifiant interne. La confirmation n'est utile qu'à la page."""
    return {cle: reponse[cle] for cle in ("ok", "etat", "message", "verrouille", "confirmation") if cle in reponse}


def _b64url_valide(valeur: Any, minimum: int, maximum: int) -> bool:
    return isinstance(valeur, str) and minimum <= len(valeur) <= maximum and bool(_B64URL.match(valeur))


def creer_routeur_verrou(relais: Any) -> APIRouter:
    routeur = APIRouter()
    tentatives: dict[str, list[float]] = {}
    nonces: dict[str, dict] = {}  # nonce -> {courriel, cree} : usage unique, 10 minutes
    attentes: dict[str, list[dict]] = {}  # courriel -> commandes en attente (preuves, jamais de code)
    suivis: dict[str, dict] = {}  # identifiant de suivi -> {etat, message, confirmation, maj}
    livraison: dict[str, asyncio.Task | None] = {"tache": None}

    # ------------------------------------------------------------------ limitation
    def _limiter(cles: list[str], maximum: int = MAX_TENTATIVES) -> float:
        """Enregistre une tentative pour chaque clé ; renvoie le délai d'attente (0 = permis)."""
        maintenant = time.time()
        if len(tentatives) > 5000:  # ménage : les clés sans tentative récente disparaissent
            for cle in [c for c, t in tentatives.items() if not t or t[-1] < maintenant - FENETRE_S]:
                tentatives.pop(cle, None)
        attente = 0.0
        for cle in cles:
            recentes = [t for t in tentatives.get(cle, []) if t > maintenant - FENETRE_S]
            if len(recentes) >= maximum:
                attente = max(attente, recentes[0] + FENETRE_S - maintenant)
            tentatives[cle] = recentes
        if attente > 0:
            return attente
        for cle in cles:
            tentatives[cle].append(maintenant)
        return 0.0

    def _trop(delai: float) -> JSONResponse:
        minutes = max(1, int(-(-delai // 60)))
        return JSONResponse(
            {"ok": False, "etat": "trop_de_tentatives",
             "message": f"Trop de tentatives. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}."},
            status_code=429, headers={"Retry-After": str(int(delai) + 1)})

    # ------------------------------------------------------------------ envoi à l'ordinateur
    def _pc_lie(courriel: str) -> dict | None:
        pc = relais._pc_par_courriel.get(courriel)
        return pc if pc is not None and pc.get("prouve") else None

    async def _envoyer(pc: dict, courriel: str, commande: dict, lot: dict) -> dict | None:
        """Transmet la commande (preuve, jamais de code) et attend la réponse. None = sans réponse ; lève si
        l'envoi échoue. `lot` ({lot, reste}) marque une commande livrée depuis la file."""
        req_id = "verrou-" + secrets.token_hex(12)
        attente = _Attente()
        relais._req_en_cours[req_id] = {"tel": attente, "courriel": courriel, "verrou": True}
        message = {"type": "verrou", "req_id": req_id, "action": commande["action"], "nonce": commande["nonce"],
                   "preuve": commande["preuve"], "defi_page": commande["defi_page"],
                   "differee": True, "lot": lot["lot"], "reste": lot["reste"]}
        try:
            await pc["ws"].send_json(message)
            try:
                reponse = await asyncio.wait_for(attente.futur, timeout=DELAI_REPONSE_S)
            except asyncio.TimeoutError:
                return None
            return reponse if isinstance(reponse, dict) else None
        finally:
            relais._req_en_cours.pop(req_id, None)

    def _suivre(suivi: str, etat: str, message: str, confirmation: str | None = None) -> None:
        cree = (suivis.get(suivi) or {}).get("cree") or time.time()
        suivis[suivi] = {"etat": etat, "message": message, "confirmation": confirmation, "maj": time.time(),
                         "cree": cree}

    async def _livrer() -> None:
        """Livre les commandes en attente dès que l'ordinateur LIÉ au courriel est connecté."""
        while attentes:
            maintenant = time.time()
            for courriel in list(attentes):
                vivantes = []
                for commande in attentes.get(courriel, []):
                    if commande["cree"] < maintenant - ATTENTE_MAX_S:
                        _suivre(commande["suivi"], "expiree",
                                "La commande a expiré : l'ordinateur ne s'est pas reconnecté en 72 heures.")
                    else:
                        vivantes.append(commande)
                attentes[courriel] = vivantes
                pc = _pc_lie(courriel)
                if not vivantes or pc is None:
                    if not vivantes:
                        attentes.pop(courriel, None)
                    continue
                a_livrer = attentes.pop(courriel)
                lot = secrets.token_hex(8)
                for i, commande in enumerate(a_livrer):
                    try:
                        reponse = await _envoyer(pc, courriel, commande, {"lot": lot, "reste": len(a_livrer) - i - 1})
                    except Exception:
                        # L'ordinateur vient de se déconnecter : la commande en cours ET toutes celles qui la
                        # suivaient retournent en tête de file, dans leur ordre. On réessaiera.
                        attentes[courriel] = a_livrer[i:] + attentes.get(courriel, [])
                        break
                    if reponse is None:
                        _suivre(commande["suivi"], "sans_reponse", MESSAGE_SANS_REPONSE)
                    else:
                        publique = _publique(reponse)
                        confirmation = publique.get("confirmation")
                        _suivre(commande["suivi"], str(publique.get("etat") or "inconnu"),
                                str(publique.get("message") or ""),
                                confirmation if isinstance(confirmation, str) else None)
            for suivi in [s for s, v in suivis.items() if v["maj"] < time.time() - SUIVI_GARDE_S]:
                suivis.pop(suivi, None)
            if attentes:
                await asyncio.sleep(INTERVALLE_LIVRAISON_S)

    def _assurer_livraison() -> None:
        tache = livraison["tache"]
        if tache is None or tache.done():
            livraison["tache"] = asyncio.get_running_loop().create_task(_livrer())

    async def _corps(request: Request) -> dict:
        # Corps lu à la main : une erreur de validation automatique renverrait les valeurs reçues.
        try:
            corps = await request.json()
        except Exception:
            corps = None
        return corps if isinstance(corps, dict) else {}

    # ------------------------------------------------------------------ routes
    @routeur.get("/verrou", response_class=HTMLResponse)
    def page_verrou():
        return HTMLResponse(PAGE, headers=ENTETES_PAGE)

    @routeur.post("/api/verrou/defi")
    async def verrou_defi(request: Request):
        """Sel du code de secours (publié par l'ordinateur lié) et nonce à usage unique. Même forme de réponse
        pour tout courriel valide : un courriel sans ordinateur lié reçoit un sel factice, stable."""
        corps = await _corps(request)
        courriel = relais.normaliser(str(corps.get("courriel") or ""))
        delai = _limiter([f"defi-ip:{_adresse_ip(request)}"] + ([f"defi-courriel:{courriel}"] if courriel else []),
                         DEFIS_MAX)
        if delai > 0:
            return _trop(delai)
        if not _COURRIEL.match(courriel):
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Courriel invalide."}, status_code=422)
        fiche = relais.liaison_confirmee(courriel)
        sel, iterations = (fiche.get("sel"), fiche.get("iterations")) if fiche else (None, None)
        if not sel or not iterations:
            factice = hmac.new(relais.SECRET_JETON, f"sel-factice|{courriel}".encode("utf-8"), hashlib.sha256).digest()
            sel, iterations = relais._b64(factice[:16]), ITERATIONS_DEFAUT
        maintenant = time.time()
        if len(nonces) >= NONCES_MAX:
            for vieux in sorted(nonces, key=lambda n: nonces[n]["cree"])[: len(nonces) - NONCES_MAX + 1]:
                nonces.pop(vieux, None)
        # L'horodatage fait partie du nonce (et donc de la preuve) : l'ordinateur refuse un nonce trop vieux.
        nonce = f"{int(maintenant)}.{secrets.token_urlsafe(24)}"
        nonces[nonce] = {"courriel": courriel, "cree": maintenant}
        return {"sel": sel, "iterations": int(iterations), "nonce": nonce, "expire_dans_s": int(DUREE_DEFI_S)}

    @routeur.post("/api/verrou")
    async def verrou(request: Request):
        corps = await _corps(request)
        courriel = relais.normaliser(str(corps.get("courriel") or ""))
        action = str(corps.get("action") or "")
        nonce = str(corps.get("nonce") or "")
        preuve = corps.get("preuve")
        defi_page = corps.get("defi_page")
        delai = _limiter([f"ip:{_adresse_ip(request)}"] + ([f"courriel:{courriel}"] if courriel else []))
        if delai > 0:
            return _trop(delai)
        if not _COURRIEL.match(courriel):
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Courriel invalide."}, status_code=422)
        if action not in ACTIONS:
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Action inconnue."}, status_code=422)
        if "code" in corps:
            # Ancienne page gardée en cache : elle enverrait le code lui-même. On refuse sans le relayer.
            return JSONResponse({"ok": False, "etat": "page_perimee",
                                 "message": "Cette page est périmée : rechargez-la, puis recommencez."}, status_code=422)
        if not _b64url_valide(preuve, 40, 64) or not _b64url_valide(defi_page, 16, 64):
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Commande mal formée : rechargez la page."},
                                status_code=422)
        emis = nonces.pop(nonce, None)
        if not emis or emis["courriel"] != courriel or emis["cree"] < time.time() - DUREE_DEFI_S:
            return JSONResponse({"ok": False, "etat": "defi_expire", "message": MESSAGE_DEFI_EXPIRE}, status_code=422)
        if sum(len(f) for f in attentes.values()) >= ATTENTES_TOTAL_MAX:
            log.warning("verrou : plafond de commandes en attente atteint")
            return JSONResponse({"ok": False, "etat": "sature",
                                 "message": "Le relais est momentanément saturé. Réessayez dans quelques minutes."},
                                status_code=503)
        suivi = secrets.token_urlsafe(18)
        adresse = hmac.new(relais.SECRET_JETON, f"verrou-ip|{courriel}|{_adresse_ip(request)}".encode("utf-8"),
                           hashlib.sha256).hexdigest()[:24]  # jamais l'adresse en clair, même en mémoire
        file = attentes.setdefault(courriel, [])
        # Une commande par adresse : la nouvelle remplace celle que la même adresse avait mise en file.
        file[:] = [c for c in file if c.get("adresse") != adresse]
        if len(file) >= ATTENTES_PAR_COURRIEL:
            # File pleine : la plus ancienne commande venue d'une AUTRE adresse cède sa place (toutes le sont, ici).
            file.pop(min(range(len(file)), key=lambda i: file[i]["cree"]))
        file.append({"suivi": suivi, "action": action, "nonce": nonce, "preuve": preuve, "defi_page": defi_page,
                     "cree": time.time(), "adresse": adresse})
        # Même réponse, même suivi, que la commande soit gardée, remplacée plus tard ou refusée par l'ordinateur :
        # une commande qui cède sa place n'est plus livrée, son suivi se lit « non confirmée » après le délai uniforme.
        _suivre(suivi, "en_attente", MESSAGE_TRANSMISE)
        _assurer_livraison()
        return JSONResponse({"ok": False, "etat": "en_attente", "suivi": suivi, "message": MESSAGE_TRANSMISE},
                            status_code=202)

    @routeur.get("/api/verrou/suivi/{suivi}")
    def verrou_suivi(suivi: str):
        etat = suivis.get(suivi)
        if etat is None:
            return JSONResponse(
                {"etat": "inconnu", "message": "Suivi introuvable : le relais a peut-être redémarré, la commande "
                                               "est alors perdue. Recommencez."}, status_code=404)
        if etat["etat"] in ETATS_SUCCES:
            reponse = {"etat": etat["etat"], "message": etat["message"]}
            if etat.get("confirmation"):
                reponse["confirmation"] = etat["confirmation"]
            return reponse
        # Tout le reste (refus, sans réponse, toujours en attente) se lit de la même façon.
        if time.time() - float(etat.get("cree") or 0) < DELAI_UNIFORME_S:
            return {"etat": "en_attente", "message": MESSAGE_TRANSMISE}
        return {"etat": "non_confirmee", "message": MESSAGE_NON_CONFIRMEE}

    _ETATS[id(relais)] = {"tentatives": tentatives, "attentes": attentes, "suivis": suivis, "nonces": nonces}
    return routeur


# État en mémoire de chaque routeur créé, pour les tests seulement (jamais servi par HTTP).
_ETATS: dict[int, dict] = {}


def etat_memoire(relais: Any) -> dict:
    return _ETATS[id(relais)]


# Chaîne brute : le script contient des expressions régulières et des échappements JavaScript.
PAGE = r"""<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Verrouiller IRIS à distance · VELA</title>
<style>
:root { --fond:#f6f7f9; --carte:#ffffff; --texte:#14161a; --doux:#4a505a; --ligne:#c9ced6; --accent:#1f4fd1;
  --danger:#b3261e; --ok:#1b6e3a; --focus:#ffb300; }
@media (prefers-color-scheme: dark) { :root { --fond:#0f1115; --carte:#181b21; --texte:#eef0f3; --doux:#b4bac4;
  --ligne:#3a404a; --accent:#8fb0ff; --danger:#ff8a80; --ok:#7ddc9c; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--fond); color:var(--texte); font:18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:40rem; margin:0 auto; padding:1.5rem 1rem 3rem; }
h1 { font-size:1.6rem; margin:.5rem 0 1rem; }
h2 { font-size:1.15rem; margin:1.5rem 0 .5rem; }
.carte { background:var(--carte); border:1px solid var(--ligne); border-radius:14px; padding:1.25rem; margin:1rem 0; }
label { display:block; font-weight:600; margin:1rem 0 .35rem; }
input[type=email], input[type=password] { width:100%; font-size:1.1rem; padding:.8rem; border-radius:10px;
  border:2px solid var(--ligne); background:var(--fond); color:var(--texte); }
fieldset { border:none; padding:0; margin:1rem 0 0; }
legend { font-weight:600; margin-bottom:.35rem; }
.choix { display:flex; gap:.6rem; align-items:flex-start; padding:.7rem; border:2px solid var(--ligne); border-radius:10px; margin:.5rem 0; }
.choix input { width:1.4rem; height:1.4rem; margin-top:.2rem; flex:none; }
.choix label { margin:0; font-weight:600; }
.choix p { margin:.2rem 0 0; font-weight:400; color:var(--doux); }
button { width:100%; min-height:3.2rem; font-size:1.15rem; font-weight:700; border:none; border-radius:12px;
  background:var(--accent); color:#fff; margin-top:1.25rem; cursor:pointer; }
button[disabled] { opacity:.6; cursor:wait; }
:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
.aide { color:var(--doux); font-size:.95rem; margin:.3rem 0 0; }
#confirmation { display:none; }
#statut { min-height:1.5rem; font-weight:600; }
#statut.ok { color:var(--ok); } #statut.erreur { color:var(--danger); }
ul { padding-left:1.2rem; } li { margin:.3rem 0; }
@media (prefers-color-scheme: dark) { button { color:#0f1115; } }
</style>
</head>
<body>
<main>
<h1>Verrouiller IRIS à distance</h1>
<p>Votre ordinateur est perdu ou volé ? Verrouillez IRIS, ou effacez ses données, avec le code de secours
choisi sur l’ordinateur.</p>

<form id="formulaire" class="carte" novalidate>
  <label for="courriel">Courriel de votre compte VELA</label>
  <input id="courriel" name="courriel" type="email" autocomplete="email" required>

  <label for="code">Code de secours</label>
  <input id="code" name="code" type="password" autocomplete="off" minlength="6" maxlength="64" required aria-describedby="aide-code">
  <p id="aide-code" class="aide">Le code choisi dans IRIS, sur l’ordinateur, à l’écran « Verrouillage à distance ». Ce n’est pas votre mot de passe. Il ne quitte pas ce navigateur.</p>

  <fieldset>
    <legend>Action</legend>
    <div class="choix">
      <input id="action-verrouiller" type="radio" name="action" value="verrouiller" checked>
      <div><label for="action-verrouiller">Verrouiller</label>
      <p>IRIS cesse d’écouter, coupe les lunettes et refuse l’accès à ses fonctions, sur l’ordinateur comme depuis le téléphone, jusqu’à ce qu’on entre le mot de passe du propriétaire.</p></div>
    </div>
    <div class="choix">
      <input id="action-effacer" type="radio" name="action" value="effacer">
      <div><label for="action-effacer">Effacer les données d’IRIS et verrouiller</label>
      <p>Irréversible. Voir la liste plus bas.</p></div>
    </div>
  </fieldset>

  <div id="confirmation" class="choix">
    <input id="je-comprends" type="checkbox">
    <label for="je-comprends">Je comprends que l’effacement est définitif.</label>
  </div>

  <button id="envoyer" type="submit">Envoyer la commande</button>
  <p id="statut" role="status" aria-live="polite"></p>
</form>

<section class="carte" aria-labelledby="titre-conditions">
  <h2 id="titre-conditions">Ce qu’il faut savoir</h2>
  <ul>
    <li>Le verrouillage à distance doit avoir été activé sur l’ordinateur, avec un code de secours et un mot de passe, et l’ordinateur doit avoir été lié à votre compte en confirmant le courriel reçu à ce moment-là.</li>
    <li>L’ordinateur doit être allumé et connecté à Internet. Sinon, la commande attend sa reconnexion en mémoire seulement : si le relais redémarre, elle est perdue et il faut recommencer.</li>
    <li>Votre code ne quitte pas ce navigateur : la page en tire une preuve à usage unique que seul votre ordinateur lié peut vérifier. Le relais voit passer cette preuve, pas le code ; quelqu’un qui la détient pourrait essayer de deviner le code hors ligne, ce qu’un code long rend impraticable. Changez quand même votre code après usage.</li>
    <li>Le succès n’est affiché que si la réponse est confirmée par votre ordinateur. Une réponse non confirmée est dite comme telle.</li>
    <li>5 tentatives au plus par 15 minutes, par courriel et par adresse. Limite : un tiers qui connaît votre courriel peut bloquer cette page 15 minutes pour ce courriel, et recommencer tant qu’il insiste ; l’ordinateur refuse de même les codes pendant 15 minutes après 5 codes erronés. Ce choix protège votre code contre les essais au hasard, au prix de l’accès à la page.</li>
    <li>Tant qu’aucun succès n’est confirmé, la page ne dit pas pourquoi (code erroné, ordinateur hors ligne, verrouillage désactivé) : un tiers ne doit pas apprendre si votre ordinateur est en ligne.</li>
    <li id="liaison-indisponible" hidden><strong>Sur ce relais, la liaison des ordinateurs par courriel n’est pas encore en service :</strong> un ordinateur qui n’a pas été lié avant ne recevra pas la commande.</li>
    <li>Une seule commande par connexion Internet attend un même ordinateur hors ligne : une nouvelle commande envoyée depuis la même connexion remplace la précédente. Au-delà de 20 connexions différentes, la commande la plus ancienne cède sa place. Limite : un tiers qui connaît votre courriel et enverrait sans relâche des commandes depuis de nombreuses connexions pourrait faire céder la vôtre ; renvoyez-la si l’ordinateur ne s’est toujours pas reconnecté. Il ne peut jamais agir sans votre code.</li>
    <li>Ce verrou ne remplace pas le chiffrement du disque (BitLocker) contre le vol.</li>
  </ul>
  <h2>Ce que l’effacement supprime</h2>
  <p>Sur l’ordinateur : mémoire, rappels, journal d’écoute, cours, reçus, conversations, tâches, veilles,
  routines, séances d’entraînement, historique d’activité, photos et enregistrements, empreinte vocale,
  zones sans mémoire, état du mode invité, copies de secours des réglages, sessions des téléphones, clés et
  identifiants enregistrés, profil du navigateur piloté, journal technique d’IRIS ; les lunettes sont oubliées.
  Le registre de confidentialité est remis à zéro : il repart de l’effacement. Le compte et le mot de passe
  restent, pour pouvoir déverrouiller. Les fichiers déjà exportés hors d’IRIS ne sont pas effacés, et un outil
  de récupération peut retrouver des traces sur un disque non chiffré.</p>
</section>
</main>
<script>
/* Preuve du code de secours, calculée dans ce navigateur (WebCrypto). Le code ne part jamais. */
var VerrouPreuve = (function () {
  var encodeur = new TextEncoder();
  function b64url(tampon) {
    var octets = new Uint8Array(tampon), binaire = '';
    for (var i = 0; i < octets.length; i++) binaire += String.fromCharCode(octets[i]);
    return btoa(binaire).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function deb64url(texte) {
    var propre = String(texte || '').replace(/-/g, '+').replace(/_/g, '/');
    while (propre.length % 4) propre += '=';
    var binaire = atob(propre), octets = new Uint8Array(binaire.length);
    for (var i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
    return octets;
  }
  function deriver(code, sel, iterations) {
    return crypto.subtle.importKey('raw', encodeur.encode(code), 'PBKDF2', false, ['deriveBits'])
      .then(function (base) {
        return crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: deb64url(sel), iterations: iterations }, base, 256);
      })
      .then(function (bits) {
        return crypto.subtle.importKey('raw', bits, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
      });
  }
  function signer(cle, texte) {
    return crypto.subtle.sign('HMAC', cle, encodeur.encode(texte)).then(b64url);
  }
  function verifier(cle, texte, preuve) {
    if (!cle || !preuve) return Promise.resolve(false);
    try {
      return crypto.subtle.verify('HMAC', cle, deb64url(preuve), encodeur.encode(texte)).catch(function () { return false; });
    } catch (e) {
      return Promise.resolve(false);
    }
  }
  function aleatoire(n) {
    var octets = new Uint8Array(n);
    crypto.getRandomValues(octets);
    return b64url(octets);
  }
  return { b64url: b64url, deb64url: deb64url, deriver: deriver, signer: signer, verifier: verifier, aleatoire: aleatoire };
})();
/* fin VerrouPreuve */

(function () {
  var form = document.getElementById('formulaire');
  var statut = document.getElementById('statut');
  var bouton = document.getElementById('envoyer');
  var confirmation = document.getElementById('confirmation');
  var jeComprends = document.getElementById('je-comprends');
  var minuterie = null;
  var REUSSITES = { verrouille: true, efface: true, efface_partiel: true };

  function action() {
    var coche = form.querySelector('input[name=action]:checked');
    return coche ? coche.value : 'verrouiller';
  }
  function dire(texte, genre) {
    statut.textContent = texte;
    statut.className = genre || '';
  }
  function refus(message) {
    return { francais: message };
  }
  // Sans serveur de courriel, aucun ordinateur ne peut être lié : la page le dit (état global du relais,
  // jamais celui d'un compte).
  fetch('sante', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (j) { if (j && j.liaison_possible === false) document.getElementById('liaison-indisponible').hidden = false; })
    .catch(function () { /* page utilisable quand même */ });
  Array.prototype.forEach.call(form.querySelectorAll('input[name=action]'), function (r) {
    r.addEventListener('change', function () {
      confirmation.style.display = action() === 'effacer' ? 'flex' : 'none';
    });
  });

  function poster(chemin, corps) {
    return fetch(chemin, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify(corps)
    }).then(function (r) { return r.json().then(function (j) { return { statut: r.status, j: j || {} }; }); });
  }

  function afficherResultat(j, envoi) {
    if (!REUSSITES[j.etat]) { dire(j.message || 'Résultat inconnu.', 'erreur'); return; }
    var texte = 'vela-verrou-resultat|v1|' + j.etat + '|' + envoi.nonce + '|' + envoi.defiPage;
    VerrouPreuve.verifier(envoi.cle, texte, j.confirmation).then(function (confirme) {
      if (confirme) dire((j.message || '') + ' Réponse confirmée par votre ordinateur.', 'ok');
      else dire('Réponse non confirmée : impossible de garantir que votre ordinateur a exécuté la commande.', 'erreur');
    });
  }

  function suivre(suivi, essai, envoi) {
    if (essai >= 240) {
      dire('Toujours en attente de l’ordinateur. La commande reste en attente tant que le relais ne redémarre pas ; rouvrez cette page plus tard pour renvoyer une commande.', '');
      return;
    }
    minuterie = setTimeout(function () {
      fetch('api/verrou/suivi/' + encodeURIComponent(suivi), { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.etat === 'en_attente') { suivre(suivi, essai + 1, envoi); return; }
          if (j.etat === 'non_confirmee') { dire(j.message || 'Aucune réponse confirmée.', ''); suivre(suivi, essai + 1, envoi); return; }
          afficherResultat(j, envoi);
        })
        .catch(function () { suivre(suivi, essai + 1, envoi); });
    }, essai < 15 ? 2000 : 5000);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (minuterie) { clearTimeout(minuterie); minuterie = null; }
    var courriel = document.getElementById('courriel').value.trim();
    var champ = document.getElementById('code');
    var code = champ.value.trim();
    var act = action();
    if (!courriel || courriel.indexOf('@') < 1) { dire('Entrez le courriel de votre compte.', 'erreur'); return; }
    if (code.length < 6) { dire('Le code de secours fait au moins 6 caractères.', 'erreur'); return; }
    if (act === 'effacer' && !jeComprends.checked) { dire('Cochez la case de confirmation pour effacer.', 'erreur'); jeComprends.focus(); return; }
    if (!window.crypto || !crypto.subtle || !window.TextEncoder) {
      dire('Ce navigateur ne peut pas calculer la preuve du code : ouvrez la page en HTTPS, dans un navigateur récent.', 'erreur');
      return;
    }
    bouton.disabled = true;
    var envoi = { cle: null, nonce: '', defiPage: VerrouPreuve.aleatoire(16) };
    dire('Préparation de la preuve du code…', '');
    poster('api/verrou/defi', { courriel: courriel })
      .then(function (res) {
        if (res.statut !== 200) throw refus(res.j.message || 'Le relais refuse la demande.');
        envoi.nonce = res.j.nonce;
        return VerrouPreuve.deriver(code, res.j.sel, res.j.iterations);
      })
      .then(function (cle) {
        code = '';
        champ.value = '';
        envoi.cle = cle;
        return VerrouPreuve.signer(cle, 'vela-verrou|v1|' + act + '|' + envoi.nonce);
      })
      .then(function (preuve) {
        dire('Envoi en cours…', '');
        return poster('api/verrou', { courriel: courriel, action: act, nonce: envoi.nonce, preuve: preuve, defi_page: envoi.defiPage });
      })
      .then(function (res) {
        if (res.statut === 202 && res.j.suivi) { dire(res.j.message, ''); suivre(res.j.suivi, 0, envoi); return; }
        dire(res.j.message || 'Réponse inattendue du relais.', 'erreur');
      })
      .catch(function (err) {
        dire(err && err.francais ? err.francais : 'Le relais est injoignable. Vérifiez votre connexion et réessayez.', 'erreur');
      })
      .then(function () { bouton.disabled = false; });
  });
})();
</script>
</body>
</html>
"""
