"""Verrouillage à distance, côté relais : la page publique /verrou et la transmission de la commande au PC.

Le scénario : l'ordinateur est perdu ou volé. Depuis n'importe quel navigateur, le propriétaire ouvre
/verrou, donne son courriel VELA, son CODE DE SECOURS (choisi sur l'ordinateur) et l'action :
verrouiller, ou effacer les données d'IRIS. Le relais transmet {action, code} à l'ordinateur connecté
pour ce courriel, par le canal sortant que celui-ci tient déjà ouvert (/appareil/ws, voir relais.py).

Ce que le relais fait, et ne fait pas :
- il ne VÉRIFIE pas le code : il ne connaît ni le code ni son empreinte. C'est l'ordinateur qui compare
  le code à son empreinte locale (scrypt) ; le relais ne peut donc ni deviner ni rejouer quoi que ce soit
  hors de ce transit ;
- il ne journalise ni le code ni le corps des requêtes, et ne les écrit jamais sur le disque ;
- il attend la réponse de l'ordinateur 15 secondes. Sans réponse, il dit que la commande est partie
  mais qu'il ne peut pas confirmer son exécution ;
- si l'ordinateur est hors ligne, la commande attend sa reconnexion EN MÉMOIRE (72 h au plus, 3 par
  courriel). Si le relais redémarre (mise à jour, mise en veille du serveur), elle est perdue : la page
  le dit, et l'utilisateur doit recommencer ;
- limitation : 5 tentatives par 15 minutes, par courriel ET par adresse IP. Revers assumé : quelqu'un
  qui connaît le courriel peut bloquer la page pour ce courriel pendant 15 minutes.

Réponse de l'ordinateur : il la renvoie sous le type « resultat » avec le req_id reçu. Le routage
existant de relais.py (`_req_en_cours`) la remet à un destinataire factice (`_Attente`) qui débloque la
requête HTTP en cours. Ce module ne touche à aucun code de relais.py.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("vela.verrou_distant")

MAX_TENTATIVES = 5
FENETRE_S = 900.0  # 15 minutes
DELAI_REPONSE_S = 15.0
ATTENTE_MAX_S = 72 * 3600.0
ATTENTES_PAR_COURRIEL = 3
SUIVI_GARDE_S = 24 * 3600.0
INTERVALLE_LIVRAISON_S = 2.0
CODE_MIN = 6
CODE_MAX = 64
ACTIONS = ("verrouiller", "effacer")
_COURRIEL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")

MESSAGE_EN_ATTENTE = (
    "Votre ordinateur n'est pas connecté pour le moment. La commande attend sa reconnexion, en mémoire "
    "seulement, pendant 72 heures au plus : si le relais redémarre (mise à jour, mise en veille du serveur), "
    "elle est perdue et il faudra recommencer. Gardez cette page ouverte pour voir le résultat."
)
MESSAGE_SANS_REPONSE = (
    "La commande a été transmise à votre ordinateur, mais il n'a pas répondu dans les 15 secondes : "
    "impossible de confirmer qu'elle a été exécutée."
)
STATUTS_PC = {"code_refuse": 403, "trop_de_tentatives": 429, "desactive": 409, "sans_code": 409,
              "sans_mot_de_passe": 409, "indisponible": 409, "action_inconnue": 422, "erreur": 502}


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
    """Ce qu'on rend au navigateur : jamais le code, jamais d'identifiant interne."""
    return {cle: reponse[cle] for cle in ("ok", "etat", "message", "verrouille") if cle in reponse}


def creer_routeur_verrou(relais: Any) -> APIRouter:
    routeur = APIRouter()
    tentatives: dict[str, list[float]] = {}
    attentes: dict[str, list[dict]] = {}  # courriel -> commandes en attente (code compris, mémoire seulement)
    suivis: dict[str, dict] = {}  # identifiant de suivi -> {etat, message, maj}
    livraison: dict[str, asyncio.Task | None] = {"tache": None}

    # ------------------------------------------------------------------ limitation
    def _limiter(cles: list[str]) -> float:
        """Enregistre une tentative pour chaque clé ; renvoie le délai d'attente (0 = permis)."""
        maintenant = time.time()
        if len(tentatives) > 5000:  # ménage : les clés sans tentative récente disparaissent
            for cle in [c for c, t in tentatives.items() if not t or t[-1] < maintenant - FENETRE_S]:
                tentatives.pop(cle, None)
        attente = 0.0
        for cle in cles:
            recentes = [t for t in tentatives.get(cle, []) if t > maintenant - FENETRE_S]
            if len(recentes) >= MAX_TENTATIVES:
                attente = max(attente, recentes[0] + FENETRE_S - maintenant)
            tentatives[cle] = recentes
        if attente > 0:
            return attente
        for cle in cles:
            tentatives[cle].append(maintenant)
        return 0.0

    # ------------------------------------------------------------------ envoi à l'ordinateur
    async def _envoyer(pc: dict, courriel: str, action: str, code: str) -> dict | None:
        """Transmet la commande et attend la réponse. None = transmise sans réponse ; lève si l'envoi échoue."""
        req_id = "verrou-" + secrets.token_hex(12)
        attente = _Attente()
        relais._req_en_cours[req_id] = {"tel": attente, "courriel": courriel}
        try:
            await pc["ws"].send_json({"type": "verrou", "req_id": req_id, "action": action, "code": code})
            try:
                reponse = await asyncio.wait_for(attente.futur, timeout=DELAI_REPONSE_S)
            except asyncio.TimeoutError:
                return None
            return reponse if isinstance(reponse, dict) else None
        finally:
            relais._req_en_cours.pop(req_id, None)

    def _suivre(suivi: str, etat: str, message: str) -> None:
        suivis[suivi] = {"etat": etat, "message": message, "maj": time.time()}

    async def _livrer() -> None:
        """Livre les commandes en attente dès que l'ordinateur concerné se reconnecte."""
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
                pc = relais._pc_par_courriel.get(courriel)
                if not vivantes or pc is None:
                    if not vivantes:
                        attentes.pop(courriel, None)
                    continue
                a_livrer = attentes.pop(courriel)
                for commande in a_livrer:
                    code = commande.pop("code", "")  # le code quitte la mémoire du relais à la livraison
                    try:
                        reponse = await _envoyer(pc, courriel, commande["action"], code)
                    except Exception:
                        attentes.setdefault(courriel, []).append({**commande, "code": code})
                        break  # l'ordinateur vient de se déconnecter : on réessaiera
                    if reponse is None:
                        _suivre(commande["suivi"], "sans_reponse", MESSAGE_SANS_REPONSE)
                    else:
                        publique = _publique(reponse)
                        _suivre(commande["suivi"], str(publique.get("etat") or "inconnu"),
                                str(publique.get("message") or ""))
            for suivi in [s for s, v in suivis.items() if v["maj"] < time.time() - SUIVI_GARDE_S]:
                suivis.pop(suivi, None)
            if attentes:
                await asyncio.sleep(INTERVALLE_LIVRAISON_S)

    def _assurer_livraison() -> None:
        tache = livraison["tache"]
        if tache is None or tache.done():
            livraison["tache"] = asyncio.get_running_loop().create_task(_livrer())

    # ------------------------------------------------------------------ routes
    @routeur.get("/verrou", response_class=HTMLResponse)
    def page_verrou():
        return HTMLResponse(PAGE, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                           "Referrer-Policy": "no-referrer"})

    @routeur.post("/api/verrou")
    async def verrou(request: Request):
        # Corps lu à la main : une erreur de validation automatique renverrait les valeurs reçues, code compris.
        try:
            corps = await request.json()
        except Exception:
            corps = None
        if not isinstance(corps, dict):
            corps = {}
        courriel = relais.normaliser(str(corps.get("courriel") or ""))
        code = str(corps.get("code") or "").strip()
        action = str(corps.get("action") or "")
        cles = [f"ip:{_adresse_ip(request)}"] + ([f"courriel:{courriel}"] if courriel else [])
        delai = _limiter(cles)
        if delai > 0:
            minutes = max(1, int(-(-delai // 60)))
            return JSONResponse(
                {"ok": False, "etat": "trop_de_tentatives",
                 "message": f"Trop de tentatives. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}."},
                status_code=429, headers={"Retry-After": str(int(delai) + 1)})
        if not _COURRIEL.match(courriel):
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Courriel invalide."}, status_code=422)
        if not CODE_MIN <= len(code) <= CODE_MAX:
            return JSONResponse({"ok": False, "etat": "invalide",
                                 "message": f"Le code de secours fait de {CODE_MIN} à {CODE_MAX} caractères."},
                                status_code=422)
        if action not in ACTIONS:
            return JSONResponse({"ok": False, "etat": "invalide", "message": "Action inconnue."}, status_code=422)

        pc = relais._pc_par_courriel.get(courriel)
        if pc is not None:
            try:
                reponse = await _envoyer(pc, courriel, action, code)
            except Exception:
                pc = None  # canal rompu à l'instant : la commande passe en attente
            else:
                if reponse is None:
                    return JSONResponse({"ok": False, "etat": "sans_reponse", "message": MESSAGE_SANS_REPONSE},
                                        status_code=504)
                publique = _publique(reponse)
                statut = 200 if publique.get("ok") else STATUTS_PC.get(str(publique.get("etat")), 409)
                return JSONResponse(publique, status_code=statut)

        suivi = secrets.token_urlsafe(18)
        file = attentes.setdefault(courriel, [])
        file.append({"suivi": suivi, "action": action, "code": code, "cree": time.time()})
        while len(file) > ATTENTES_PAR_COURRIEL:
            remplacee = file.pop(0)
            _suivre(remplacee["suivi"], "remplacee", "Remplacée par une commande plus récente.")
        _suivre(suivi, "en_attente", MESSAGE_EN_ATTENTE)
        _assurer_livraison()
        return JSONResponse({"ok": False, "etat": "en_attente", "suivi": suivi, "message": MESSAGE_EN_ATTENTE},
                            status_code=202)

    @routeur.get("/api/verrou/suivi/{suivi}")
    def verrou_suivi(suivi: str):
        etat = suivis.get(suivi)
        if etat is None:
            return JSONResponse(
                {"etat": "inconnu", "message": "Suivi introuvable : le relais a peut-être redémarré, la commande "
                                               "est alors perdue. Recommencez."}, status_code=404)
        return {"etat": etat["etat"], "message": etat["message"]}

    _ETATS[id(relais)] = {"tentatives": tentatives, "attentes": attentes, "suivis": suivis}
    return routeur


# État en mémoire de chaque routeur créé, pour les tests seulement (jamais servi par HTTP).
_ETATS: dict[int, dict] = {}


def etat_memoire(relais: Any) -> dict:
    return _ETATS[id(relais)]


PAGE = """<!doctype html>
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
choisi sur l'ordinateur.</p>

<form id="formulaire" class="carte" novalidate>
  <label for="courriel">Courriel de votre compte VELA</label>
  <input id="courriel" name="courriel" type="email" autocomplete="email" required>

  <label for="code">Code de secours</label>
  <input id="code" name="code" type="password" autocomplete="off" minlength="6" maxlength="64" required aria-describedby="aide-code">
  <p id="aide-code" class="aide">Le code choisi dans IRIS, sur l'ordinateur, à l'écran « Verrouillage à distance ». Ce n'est pas votre mot de passe.</p>

  <fieldset>
    <legend>Action</legend>
    <div class="choix">
      <input id="action-verrouiller" type="radio" name="action" value="verrouiller" checked>
      <div><label for="action-verrouiller">Verrouiller</label>
      <p>IRIS cesse d'écouter, coupe les lunettes et refuse l'accès à ses fonctions, sur l'ordinateur comme depuis le téléphone, jusqu'à ce qu'on entre le mot de passe du propriétaire.</p></div>
    </div>
    <div class="choix">
      <input id="action-effacer" type="radio" name="action" value="effacer">
      <div><label for="action-effacer">Effacer les données d'IRIS et verrouiller</label>
      <p>Irréversible. Voir la liste plus bas.</p></div>
    </div>
  </fieldset>

  <div id="confirmation" class="choix">
    <input id="je-comprends" type="checkbox">
    <label for="je-comprends">Je comprends que l'effacement est définitif.</label>
  </div>

  <button id="envoyer" type="submit">Envoyer la commande</button>
  <p id="statut" role="status" aria-live="polite"></p>
</form>

<section class="carte" aria-labelledby="titre-conditions">
  <h2 id="titre-conditions">Ce qu'il faut savoir</h2>
  <ul>
    <li>Le verrouillage à distance doit avoir été activé sur l'ordinateur, avec un code de secours et un mot de passe.</li>
    <li>L'ordinateur doit être allumé et connecté à Internet. Sinon, la commande attend sa reconnexion en mémoire seulement : si le relais redémarre, elle est perdue et il faut recommencer.</li>
    <li>Le relais ne vérifie pas votre code et ne l'écrit nulle part : il le transmet à l'ordinateur, qui le compare à son empreinte. Une commande en attente le garde en mémoire jusqu'à sa livraison.</li>
    <li>5 tentatives au plus par 15 minutes, par courriel et par adresse.</li>
    <li>Ce verrou ne remplace pas le chiffrement du disque (BitLocker) contre le vol.</li>
  </ul>
  <h2>Ce que l'effacement supprime</h2>
  <p>Sur l'ordinateur : mémoire, rappels, journal d'écoute, cours, reçus, conversations, tâches, veilles,
  photos et enregistrements, empreinte vocale, zones sans mémoire, sessions des téléphones, clés et
  identifiants enregistrés, profil du navigateur piloté ; les lunettes sont oubliées. Le compte et le
  mot de passe restent, pour pouvoir déverrouiller. Les fichiers déjà exportés hors d'IRIS ne sont pas effacés.</p>
</section>
</main>
<script>
(function () {
  var form = document.getElementById('formulaire');
  var statut = document.getElementById('statut');
  var bouton = document.getElementById('envoyer');
  var confirmation = document.getElementById('confirmation');
  var jeComprends = document.getElementById('je-comprends');
  var minuterie = null;

  function action() {
    var coche = form.querySelector('input[name=action]:checked');
    return coche ? coche.value : 'verrouiller';
  }
  function dire(texte, genre) {
    statut.textContent = texte;
    statut.className = genre || '';
  }
  Array.prototype.forEach.call(form.querySelectorAll('input[name=action]'), function (r) {
    r.addEventListener('change', function () {
      confirmation.style.display = action() === 'effacer' ? 'flex' : 'none';
    });
  });

  function suivre(suivi, restant) {
    if (restant <= 0) { dire('Toujours en attente de l\\'ordinateur. Vous pouvez fermer cette page : la commande reste en attente tant que le relais ne redémarre pas.', ''); return; }
    minuterie = setTimeout(function () {
      fetch('api/verrou/suivi/' + encodeURIComponent(suivi), { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.etat === 'en_attente') { suivre(suivi, restant - 1); return; }
          var bon = j.etat === 'verrouille' || j.etat === 'efface' || j.etat === 'efface_partiel';
          dire(j.message || 'Résultat inconnu.', bon ? 'ok' : 'erreur');
        })
        .catch(function () { suivre(suivi, restant - 1); });
    }, 5000);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (minuterie) { clearTimeout(minuterie); minuterie = null; }
    var courriel = document.getElementById('courriel').value.trim();
    var code = document.getElementById('code').value.trim();
    if (!courriel || courriel.indexOf('@') < 1) { dire('Entrez le courriel de votre compte.', 'erreur'); return; }
    if (code.length < 6) { dire('Le code de secours fait au moins 6 caractères.', 'erreur'); return; }
    if (action() === 'effacer' && !jeComprends.checked) { dire('Cochez la case de confirmation pour effacer.', 'erreur'); jeComprends.focus(); return; }
    bouton.disabled = true;
    dire('Envoi en cours… (jusqu\\'à 15 secondes)', '');
    fetch('api/verrou', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
      body: JSON.stringify({ courriel: courriel, code: code, action: action() })
    })
      .then(function (r) { return r.json().then(function (j) { return { statut: r.status, j: j }; }); })
      .then(function (res) {
        document.getElementById('code').value = '';
        var j = res.j || {};
        if (res.statut === 202 && j.suivi) { dire(j.message, ''); suivre(j.suivi, 120); return; }
        dire(j.message || 'Réponse inattendue du relais.', j.ok ? 'ok' : 'erreur');
      })
      .catch(function () { dire('Le relais est injoignable. Vérifiez votre connexion et réessayez.', 'erreur'); })
      .then(function () { bouton.disabled = false; });
  });
})();
</script>
</body>
</html>
"""
