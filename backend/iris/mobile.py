"""Page mobile : parler à IRIS depuis le téléphone, pour agir sur l'ordinateur resté à la maison.

Pourquoi une page dédiée plutôt que l'interface de bureau : dans une voiture ou en marchant, on ne
navigue pas dans quatre colonnes. Il faut un bouton, une réponse, et rien d'autre.

Comment ça se tient ensemble : les lunettes se connectent en Bluetooth au TÉLÉPHONE (dix mètres),
le téléphone porte cette page, et la page parle à l'ordinateur de la maison par le réseau. C'est
le seul montage possible : les lunettes n'ont ni WiFi ni carte SIM.

La reconnaissance vocale est celle du navigateur (gratuite, pas de clé). La réponse est lue par la
synthèse du téléphone, donc entendue dans les lunettes puisqu'elles en sont la sortie audio.

Elle affiche aussi les textos et appels qu'IRIS a préparés (telephonie.py, voie « iphone ») : un
lien sms: ou tel: qui ouvre Messages ou le composeur déjà rempli, puis « C'est envoyé » ou
« Annuler ». Elle les obtient en sondant /api/telephonie/en_attente (routes_communications.py).
Jusqu'au 6 septembre 2026, IRIS annonçait « touche Envoyer » et rien n'apparaissait ici.

Le téléphone de Miguel est un iPhone. Cette page est donc écrite pour Safari iOS d'abord :
installation par « Sur l'écran d'accueil », synthèse vocale à amorcer depuis un vrai geste,
reconnaissance vocale capricieuse dont on ne dépend jamais, zone sûre et clavier respectés.

Identité VELA : la voile. Fond encre, texte crème, accent terracotta. La grand-voile est ici en
crème parce que le fond est sombre — en encre elle disparaîtrait purement et simplement.
"""
from __future__ import annotations

PAGE = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1B140E">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="IRIS">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icone-192.png">
<link rel="apple-touch-icon" href="/icone-192.png">
<title>IRIS</title>
<style>
  /* Palette VELA, extraite du logo. L'ancien teal a disparu : il n'avait rien à voir avec la voile. */
  :root { --encre:#1B140E; --creme:#F8F0E7; --terracotta:#B36B3B; --terracotta-clair:#D08A55;
          --bg:var(--encre); --surface:#251C14; --line:#3A2C20; --text:var(--creme); --text-2:#C4B5A6;
          --accent:var(--terracotta); --accent-sombre:#6E4223; --danger:#E0685A;
          /* Repli pour les iOS anciens qui ignorent dvh ; le JS affine ensuite en pixels réels. */
          --hauteur:100vh; }
  @supports (height: 100dvh) { :root { --hauteur:100dvh; } }

  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  [hidden] { display:none !important; }
  body { margin:0; background:var(--bg); color:var(--text);
         height:var(--hauteur); min-height:var(--hauteur); overflow:hidden;
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         display:flex; flex-direction:column;
         padding:env(safe-area-inset-top) calc(16px + env(safe-area-inset-right))
                 env(safe-area-inset-bottom) calc(16px + env(safe-area-inset-left)); }
  header { display:flex; align-items:center; gap:10px; padding:14px 0 10px; }
  .voile { flex:none; display:block; }
  .nom { font-weight:600; letter-spacing:.14em; font-size:13px; }
  .etat { margin-left:auto; font-size:12px; color:var(--text-2); display:flex; align-items:center; gap:6px; }
  .point { width:8px; height:8px; border-radius:50%; background:var(--text-2); }
  .point.ok { background:var(--terracotta-clair); }
  .point.err { background:var(--danger); }

  /* Bandeau d'installation iOS : discret, une seule fois dans une vie. */
  #banniere { display:flex; align-items:flex-start; gap:10px; margin:0 0 8px;
              background:var(--surface); border:1px solid var(--line);
              border-left:3px solid var(--terracotta); border-radius:12px; padding:11px 12px; }
  #banniere p { margin:0; font-size:13.5px; line-height:1.45; color:var(--text); }
  #banniere-ok { flex:none; align-self:center; border:1px solid var(--line); border-radius:10px;
                 background:transparent; color:var(--terracotta-clair); font-size:13px;
                 font-weight:600; padding:7px 11px; }

  #fil { flex:1; overflow-y:auto; -webkit-overflow-scrolling:touch;
         display:flex; flex-direction:column; gap:10px; padding:6px 0 16px; }
  .bulle { max-width:88%; padding:11px 14px; border-radius:16px; white-space:pre-wrap; word-wrap:break-word; }
  .moi { align-self:flex-end; background:var(--accent-sombre); color:var(--creme); border-bottom-right-radius:5px; }
  .elle { align-self:flex-start; background:var(--surface); border:1px solid var(--line); border-bottom-left-radius:5px; }
  .info { align-self:center; font-size:13px; color:var(--text-2); text-align:center; padding:0 12px; }

  footer { padding:10px 0 16px; display:flex; flex-direction:column; gap:10px; }
  #parler { width:100%; min-height:76px; border:none; border-radius:20px; background:var(--accent);
            color:var(--encre); font-size:19px; font-weight:600; display:flex; align-items:center;
            justify-content:center; gap:10px; transition:transform .1s, background .2s; }
  #parler:active { transform:scale(.98); }
  #parler.ecoute { background:var(--danger); color:var(--encre); animation:pulse 1.2s ease-in-out infinite; }
  #parler.occupe { background:var(--line); color:var(--text-2); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.72} }
  .ligne { display:flex; gap:8px; }
  /* 16 px au minimum sur les champs : en dessous, Safari iOS zoome tout seul à la mise au point. */
  #texte { flex:1; background:var(--surface); border:1px solid var(--line); border-radius:14px;
           padding:12px 14px; color:var(--text); font-size:16px; }
  #texte::placeholder { color:var(--text-2); }
  #envoyer { border:1px solid var(--line); border-radius:14px; padding:0 18px; background:var(--surface);
             color:var(--text); font-size:16px; }
  @media (prefers-reduced-motion: reduce) { *{animation:none!important; transition:none!important} }

  /* Brouillons de SMS et d'appel déposés par IRIS. Avant le 6 septembre 2026, ils n'apparaissaient
     nulle part : IRIS disait « touche Envoyer » et le téléphone restait vide. Ils vivent au-dessus
     du fil, jamais dedans : un texto à faire partir ne doit pas défiler hors de vue. */
  #brouillons { display:flex; flex-direction:column; gap:8px; margin:0 0 8px; max-height:45%; overflow-y:auto; }
  .brouillon { background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--terracotta);
               border-radius:12px; padding:11px 12px; display:flex; flex-direction:column; gap:8px; }
  .brouillon-titre { font-weight:600; font-size:14px; }
  .brouillon-texte { white-space:pre-wrap; word-wrap:break-word; font-size:15px; }
  .brouillon-note { font-size:12.5px; color:var(--text-2); }
  .brouillon-ouvrir { display:flex; align-items:center; justify-content:center; min-height:48px;
                      border-radius:14px; background:var(--accent); color:var(--encre); font-size:17px;
                      font-weight:600; text-decoration:none; }
  .brouillon-ouvrir:active { transform:scale(.98); }
  .brouillon .ligne button { flex:1; min-height:44px; border:1px solid var(--line); border-radius:12px;
                             background:transparent; color:var(--text); font-size:15px; }
  .brouillon .ligne button.fait { color:var(--terracotta-clair); font-weight:600; }

  /* Écran de connexion : l'adresse seule ne doit jamais suffire à commander l'ordinateur. */
  #verrou { position:fixed; inset:0; background:var(--bg); z-index:20; display:none;
            flex-direction:column; align-items:center; justify-content:center;
            padding:calc(28px + env(safe-area-inset-top)) 28px calc(28px + env(safe-area-inset-bottom)); gap:16px; }
  #verrou.visible { display:flex; }
  #verrou h1 { font-size:21px; margin:0; font-weight:600; letter-spacing:.1em; }
  #verrou p { margin:0; color:var(--text-2); font-size:14px; text-align:center; max-width:320px; }
  #verrou input { width:100%; max-width:320px; background:var(--surface); border:1px solid var(--line);
                  border-radius:14px; padding:15px; color:var(--text); font-size:17px; text-align:center; }
  #verrou button { width:100%; max-width:320px; border:none; border-radius:14px; padding:15px;
                   background:var(--accent); color:var(--encre); font-size:19px; font-weight:600; }
  #erreur { color:var(--danger); font-size:14px; min-height:20px; text-align:center; }
</style>
</head>
<body>
<div id="verrou">
  <!-- La voile VELA. Fond sombre : grand-voile crème, foc terracotta. Jamais l'encre ici. -->
  <svg class="voile" width="55" height="72" viewBox="0 0 120 158" aria-hidden="true">
    <path d="M 36.5 46.3 L 36.6 158 L 0 158 Z" fill="#B36B3B"/>
    <path d="M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z" fill="#F8F0E7"/>
  </svg>
  <h1 id="verrou-titre">IRIS</h1>
  <p id="verrou-texte">Entrez votre mot de passe pour commander votre ordinateur.</p>
  <input id="mdp" type="password" placeholder="mot de passe" autocomplete="current-password" inputmode="text">
  <button id="entrer">Se connecter</button>
  <div id="erreur"></div>
</div>

<header>
  <svg class="voile" width="21" height="28" viewBox="0 0 120 158" aria-hidden="true">
    <path d="M 36.5 46.3 L 36.6 158 L 0 158 Z" fill="#B36B3B"/>
    <path d="M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z" fill="#F8F0E7"/>
  </svg>
  <span class="nom">IRIS</span>
  <span class="etat"><span class="point" id="point"></span><span id="etat">connexion…</span></span>
</header>

<div id="banniere" hidden>
  <p id="banniere-texte"></p>
  <button id="banniere-ok">Compris</button>
</div>

<!-- Les textos et appels préparés par IRIS, à faire partir d'un geste. Rempli par sonderBrouillons(). -->
<div id="brouillons" hidden></div>

<div id="fil">
  <div class="info" id="accueil">
    Appuyez sur le bouton et parlez.<br>IRIS agit sur l'ordinateur resté à la maison.
  </div>
</div>

<footer>
  <button id="parler">🎙 Appuyez pour parler</button>
  <div class="ligne">
    <input id="texte" placeholder="ou écrivez ici…" autocomplete="off">
    <button id="envoyer">Envoyer</button>
  </div>
</footer>

<script>
const params = new URLSearchParams(location.search);
// Le jeton d'adresse sert au premier appairage ; ensuite c'est la session ouverte
// avec le mot de passe qui fait foi, pour qu'une adresse retrouvée ne suffise pas.
let JETON = memoire('iris_session') || params.get('token') || memoire('iris_token') || '';
if (params.get('token')) retenir('iris_token', params.get('token'));
const BASE = location.origin;
// Un objet neuf à chaque appel : le jeton change après la connexion, et surtout Safari refuse
// un mandataire comme en-têtes de `fetch` (TypeError sur le descripteur, à chaque requête).
function enTetes() { return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + JETON }; }

// Safari en navigation privée fait lever localStorage : on ne laisse jamais ça casser la page.
function memoire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
function retenir(cle, valeur) { try { localStorage.setItem(cle, valeur); } catch (e) { /* tant pis */ } }
function oublier(cle) { try { localStorage.removeItem(cle); } catch (e) { /* tant pis */ } }

// ---- où sommes-nous ? (iPadOS se déguise en Mac, d'où le test tactile)
const UA = navigator.userAgent || '';
const IOS = /iPad|iPhone|iPod/.test(UA) || (UA.indexOf('Macintosh') !== -1 && 'ontouchend' in document);
const SAFARI_IOS = IOS && !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome/.test(UA);
const AUTONOME = window.navigator.standalone === true ||
  (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);

const verrou = document.getElementById('verrou');
const champMdp = document.getElementById('mdp');
const erreur = document.getElementById('erreur');
let compte = { configure: false };

function verrouiller(afficher, titre, texte) {
  verrou.classList.toggle('visible', afficher);
  if (titre) document.getElementById('verrou-titre').textContent = titre;
  if (texte) document.getElementById('verrou-texte').textContent = texte;
  if (afficher) setTimeout(() => champMdp.focus(), 200);
}

async function demarrer() {
  try {
    compte = await fetch(BASE + '/api/compte').then(r => r.json());
  } catch (e) { compte = { configure: false }; }

  if (!compte.configure) {
    // Aucun mot de passe posé : on fonctionne avec le jeton d'adresse, et on le dit.
    if (!JETON) return verrouiller(true, 'Adresse incomplète',
      "Ouvrez l'adresse complète affichée dans IRIS, Paramètres puis Téléphone.");
    return verrouiller(false);
  }
  // Un mot de passe existe : la session est obligatoire.
  const session = memoire('iris_session');
  if (session) {
    JETON = session;
    const ok = await fetch(BASE + '/api/status', { headers: enTetes() }).then(r => r.ok).catch(() => false);
    if (ok) return verrouiller(false);
    oublier('iris_session');
  }
  verrouiller(true, 'IRIS', 'Entrez votre mot de passe pour commander votre ordinateur.');
}

async function connexion() {
  amorcerSynthese();   // vrai geste : c'est le seul moment où iOS accepte de délier la voix
  const mdp = champMdp.value;
  if (!mdp) return;
  erreur.textContent = ''; const b = document.getElementById('entrer');
  b.disabled = true; b.textContent = 'Connexion…';
  try {
    const r = await fetch(BASE + '/api/compte/connexion', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mot_de_passe: mdp }) });
    if (!r.ok) { erreur.textContent = r.status === 401 ? 'Mot de passe incorrect.' : 'Erreur ' + r.status; return; }
    const d = await r.json();
    JETON = d.session; retenir('iris_session', d.session);
    champMdp.value = ''; verrouiller(false); verifier(); sonderBrouillons(false);
  } catch (e) {
    erreur.textContent = 'Ordinateur injoignable.';
  } finally { b.disabled = false; b.textContent = 'Se connecter'; }
}
document.getElementById('entrer').addEventListener('click', connexion);
champMdp.addEventListener('keydown', (e) => { if (e.key === 'Enter') connexion(); });

const fil = document.getElementById('fil');
const bouton = document.getElementById('parler');
const champ = document.getElementById('texte');
const point = document.getElementById('point');
const etat = document.getElementById('etat');
let conversation = memoire('iris_conv') || null;
let occupe = false;

function marquer(ok, texte) { point.className = 'point ' + (ok === null ? '' : ok ? 'ok' : 'err'); etat.textContent = texte; }
function bulle(classe, texte) {
  const acc = document.getElementById('accueil'); if (acc) acc.remove();
  const d = document.createElement('div');
  d.className = 'bulle ' + classe; d.textContent = texte;
  fil.appendChild(d); fil.scrollTop = fil.scrollHeight; return d;
}

// ---- synthèse vocale : sur iOS elle reste muette tant qu'une première parole n'a pas été
// lancée depuis un vrai geste. On glisse donc une énonciation vide au premier appui, sinon
// la réponse d'IRIS ne serait jamais entendue dans les lunettes.
let VOIX = null;
let voixAmorcee = false;

function choisirVoix() {
  try {
    const dispo = speechSynthesis.getVoices() || [];
    const langue = (v) => (v.lang || '').replace('_', '-').toLowerCase();
    VOIX = dispo.filter((v) => langue(v) === 'fr-ca')[0]
        || dispo.filter((v) => langue(v) === 'fr-fr')[0]
        || dispo.filter((v) => langue(v).indexOf('fr') === 0)[0] || null;
  } catch (e) { VOIX = null; }
}
if ('speechSynthesis' in window) {
  choisirVoix();   // sur iOS la liste arrive en retard : on réessaie quand elle change
  try { speechSynthesis.addEventListener('voiceschanged', choisirVoix); } catch (e) { /* vieux Safari */ }
}

function amorcerSynthese() {
  if (voixAmorcee || !('speechSynthesis' in window)) return;
  voixAmorcee = true;
  try {
    const vide = new SpeechSynthesisUtterance(' ');
    vide.volume = 0; vide.lang = 'fr-CA';
    speechSynthesis.speak(vide);
    choisirVoix();
  } catch (e) { voixAmorcee = false; }
}

function dire(texte) {
  if (!('speechSynthesis' in window)) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(texte);
    if (!VOIX) choisirVoix();
    if (VOIX) u.voice = VOIX;
    u.lang = (VOIX && VOIX.lang) || 'fr-CA';
    u.rate = 1.05;
    speechSynthesis.speak(u);          // sortie audio du téléphone = les lunettes
  } catch (e) { /* la lecture n'est pas indispensable */ }
}

async function verifier() {
  try {
    const r = await fetch(BASE + '/api/status', { headers: enTetes() });
    if (r.status === 401) {
      marquer(false, 'session expirée');
      if (compte.configure) { oublier('iris_session'); verrouiller(true, 'IRIS', 'Session expirée. Entrez votre mot de passe.'); }
      return;
    }
    if (!r.ok) return marquer(false, 'erreur ' + r.status);
    const s = await r.json();
    marquer(true, 'connectée · ' + (s.platform || ''));
  } catch (e) { marquer(false, 'ordinateur injoignable'); }
}

async function envoyer(texte) {
  texte = (texte || '').trim();
  if (!texte || occupe) return;
  occupe = true; bouton.classList.add('occupe'); bouton.textContent = '… IRIS travaille';
  bulle('moi', texte);
  try {
    if (!conversation) {
      const c = await fetch(BASE + '/api/conversations', { method:'POST', headers: enTetes(),
        body: JSON.stringify({ title: texte.slice(0, 40), agent: 'auto' }) }).then(r => r.json());
      conversation = c.id; retenir('iris_conv', conversation);
    }
    await fetch(BASE + '/api/conversations/' + conversation + '/messages', { method:'POST', headers: enTetes(),
      body: JSON.stringify({ text: texte, agent: 'auto', images: [] }) });

    const debut = Date.now(); let reponse = null;
    while (Date.now() - debut < 120000) {
      await new Promise(r => setTimeout(r, 1200));
      const d = await fetch(BASE + '/api/conversations/' + conversation, { headers: enTetes() }).then(r => r.json());
      const dernier = (d.messages || []).filter(m => m.role === 'assistant').pop();
      if (dernier && (dernier.text || (dernier.meta || {}).error)) { reponse = dernier.text || dernier.meta.error; break; }
    }
    if (reponse) { bulle('elle', reponse); dire(reponse); }
    else bulle('info', "IRIS n'a pas répondu à temps.");
  } catch (e) {
    bulle('info', 'Ordinateur injoignable : ' + e.message);
    marquer(false, 'injoignable');
  } finally {
    occupe = false; bouton.classList.remove('occupe'); bouton.textContent = etiquette();
    // IRIS vient peut-être de déposer un texto : on l'affiche tout de suite, sans attendre le
    // sondage. Sans annonce : sa réponse vient d'être lue, elle dit déjà « touche Envoyer ».
    sonderBrouillons(false);
  }
}

// ---- les brouillons de SMS et d'appel (telephonie.py, voie « iphone »).
// IRIS ne peut pas envoyer un texto depuis un programme : Apple ne le permet à personne. Elle le
// prépare, et c'est ce téléphone qui l'ouvre dans Messages, déjà rempli, pour un geste du pouce.
// La page SONDE l'ordinateur plutôt que d'écouter ses événements : la session ouverte avec le mot
// de passe ne donne pas accès au WebSocket, et une page mise en veille par iOS perd de toute
// façon sa connexion — un sondage, lui, reprend là où il en était.
const brouillons = document.getElementById('brouillons');
let brouillonsVus = '';   // identifiants affichés : on ne redessine pas sous le doigt sans raison

function lienSur(b) {
  // iOS attend « sms:…&body= », Android « sms:…?body= ». Voir Brouillon.lien_ios / lien_android.
  const lien = IOS ? b.lien_ios : b.lien_android;
  // Seuls sms: et tel: ont leur place ici ; tout autre schéma n'ouvrirait rien d'utile.
  return (lien && (lien.indexOf('sms:') === 0 || lien.indexOf('tel:') === 0)) ? lien : '';
}

function dessinerBrouillons(liste, annoncer) {
  const cle = liste.map((b) => b.id).join(',');
  if (cle === brouillonsVus) return;
  const nouveaux = liste.filter((b) => brouillonsVus.indexOf(b.id) === -1);
  brouillonsVus = cle;
  brouillons.textContent = '';
  brouillons.hidden = liste.length === 0;
  liste.forEach((b) => {
    const sms = b.genre === 'sms';
    const carte = document.createElement('div'); carte.className = 'brouillon';
    const titre = document.createElement('div'); titre.className = 'brouillon-titre';
    titre.textContent = (sms ? '💬 Texto pour ' : '📞 Appel vers ') + (b.numero_lisible || b.numero);
    carte.appendChild(titre);
    if (sms) {
      const texte = document.createElement('div'); texte.className = 'brouillon-texte';
      texte.textContent = b.texte || ''; carte.appendChild(texte);
    }
    const note = document.createElement('div'); note.className = 'brouillon-note';
    note.textContent = sms
      ? "Messages s'ouvre déjà rempli : c'est vous qui touchez Envoyer. Rien ne part sans ce geste."
      : "Le composeur s'ouvre avec ce numéro : c'est vous qui lancez l'appel.";
    carte.appendChild(note);
    const lien = lienSur(b);
    if (lien) {
      const ouvrir = document.createElement('a'); ouvrir.className = 'brouillon-ouvrir';
      ouvrir.href = lien; ouvrir.textContent = sms ? 'Ouvrir dans Messages' : 'Appeler';
      carte.appendChild(ouvrir);
    }
    const ligne = document.createElement('div'); ligne.className = 'ligne';
    const fait = document.createElement('button'); fait.className = 'fait';
    fait.textContent = sms ? "C'est envoyé" : "C'est appelé";
    fait.addEventListener('click', () => fermerBrouillon(b.id, 'envoye'));
    const annuler = document.createElement('button'); annuler.textContent = 'Annuler';
    annuler.addEventListener('click', () => fermerBrouillon(b.id, 'annule'));
    ligne.appendChild(fait); ligne.appendChild(annuler); carte.appendChild(ligne);
    brouillons.appendChild(carte);
  });
  ajusterHauteur();
  // Un brouillon dicté à la maison, devant l'ordinateur, arrive ici sans qu'on l'ait demandé
  // depuis cette page : on le dit, sinon il attendrait en silence ses quinze minutes.
  if (annoncer && nouveaux.length && !occupe) {
    const b = nouveaux[nouveaux.length - 1];
    const phrase = (b.genre === 'sms' ? 'Un texto pour ' : 'Un appel vers ') + (b.numero_lisible || b.numero) + ' est prêt, en haut de l’écran.';
    bulle('info', phrase); dire(phrase);
  }
}

async function sonderBrouillons(annoncer) {
  if (!JETON || verrou.classList.contains('visible')) return;
  try {
    const r = await fetch(BASE + '/api/telephonie/en_attente', { headers: enTetes() });
    if (!r.ok) return;   // 401 : verifier() s'occupe déjà de la session ; 404 : ordinateur pas à jour
    const d = await r.json();
    dessinerBrouillons(d.brouillons || [], annoncer !== false);
  } catch (e) { /* le prochain sondage réessaiera */ }
}

async function fermerBrouillon(id, etat) {
  try {
    const r = await fetch(BASE + '/api/telephonie/' + encodeURIComponent(id) + '/' + etat, { method: 'POST', headers: enTetes() });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) bulle('info', d.detail || ('Erreur ' + r.status));
    else if (d.message) bulle('info', d.message);
  } catch (e) {
    bulle('info', 'Ordinateur injoignable : ' + e.message);
  }
  brouillonsVus = '';       // forcer le redessin : la liste vient de changer côté ordinateur
  sonderBrouillons(false);
}

// Au retour de Messages ou de Téléphone, la page se réveille : elle vérifie tout de suite ce qui
// reste à faire partir plutôt que d'attendre le prochain tour de sondage.
document.addEventListener('visibilitychange', () => { if (!document.hidden) sonderBrouillons(false); });

// ---- reconnaissance vocale du navigateur : gratuite, aucune clé.
// Sur Safari iOS elle existe depuis iOS 14.5 mais elle est capricieuse : la permission exige un
// vrai geste, la session se coupe seule, et `onend` arrive parfois sans le moindre résultat.
// Règle : le bouton ne reste JAMAIS bloqué sur « Parlez… », et on ne prétend jamais que la voix
// marche quand elle ne marche pas — on bascule alors franchement sur la saisie écrite.
const Reco = window.SpeechRecognition || window.webkitSpeechRecognition;
const REPOS = '🎙 Appuyez pour parler';
const ECRIRE = '⌨️ Voix indisponible — écrivez';
let reco = null;
let voixPossible = !!Reco;
let ecoute = false;
let aEntendu = false;
let garde = null;

function etiquette() { return voixPossible ? REPOS : ECRIRE; }

function repos(message) {
  ecoute = false;
  if (garde) { clearTimeout(garde); garde = null; }
  bouton.classList.remove('ecoute');
  if (!occupe) bouton.textContent = etiquette();
  if (message) bulle('info', message);
}

function basculerEnEcrit(raison) {
  voixPossible = false;                 // honnête : la voix ne marche pas, on le dit et on écrit
  repos(raison);
  try { champ.focus(); } catch (e) { /* le champ reste utilisable à la main */ }
}

if (Reco) {
  reco = new Reco();
  reco.lang = 'fr-CA'; reco.interimResults = false; reco.maxAlternatives = 1; reco.continuous = false;
  reco.onstart = () => { aEntendu = false; };
  reco.onresult = (e) => {
    aEntendu = true;
    const premier = (e.results && e.results[0] && e.results[0][0]) || null;
    const dit = (premier && premier.transcript) || '';
    repos();
    if (dit.trim()) envoyer(dit);
    else bulle('info', "Je n'ai rien saisi. Réessayez, ou écrivez ci-dessous.");
  };
  reco.onerror = (e) => {
    const code = (e && e.error) || '';
    if (code === 'not-allowed' || code === 'service-not-allowed') {
      basculerEnEcrit("Micro refusé. Réglages ▸ Safari ▸ Microphone pour l'autoriser. En attendant, écrivez ci-dessous.");
    } else if (code === 'no-speech') {
      repos("Je n'ai rien entendu. Réessayez.");
    } else if (code === 'aborted') {
      repos();
    } else {
      repos('La reconnaissance vocale ne répond pas. Écrivez ci-dessous.');
    }
  };
  // Safari coupe la session tout seul, parfois sans résultat ni erreur : on reprend la main.
  reco.onend = () => { if (ecoute && !aEntendu) repos("Je n'ai rien entendu. Réessayez."); else repos(); };
} else {
  bouton.textContent = ECRIRE;
}

bouton.addEventListener('click', () => {
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch (e) { /* rien à couper */ } }
  amorcerSynthese();          // doit rester DANS le geste, sinon iOS ne parlera jamais
  if (occupe) return;
  if (!voixPossible || !reco) { champ.focus(); return; }
  if (ecoute) { try { reco.stop(); } catch (e) { /* déjà arrêtée */ } return repos(); }
  try {
    reco.start();
    ecoute = true; aEntendu = false;
    bouton.classList.add('ecoute'); bouton.textContent = '● Parlez…';
    garde = setTimeout(() => {
      try { reco.stop(); } catch (e) { /* déjà arrêtée */ }
      repos("Je n'ai rien entendu. Réessayez, ou écrivez ci-dessous.");
    }, 12000);
  } catch (e) {
    try { reco.stop(); } catch (e2) { /* déjà arrêtée */ }
    repos('Le micro ne répond pas. Écrivez ci-dessous.');
  }
});
document.getElementById('envoyer').addEventListener('click', () => {
  amorcerSynthese(); envoyer(champ.value); champ.value = '';
});
champ.addEventListener('keydown', (e) => { if (e.key === 'Enter') { amorcerSynthese(); envoyer(champ.value); champ.value = ''; } });

// ---- hauteur réelle : 100dvh manque aux iOS anciens, et le clavier iOS recouvrirait le champ.
// On suit la fenêtre visuelle : le fil de discussion rétrécit, le bouton et le champ restent visibles.
function ajusterHauteur() {
  const vue = window.visualViewport;
  const h = vue ? vue.height : window.innerHeight;
  if (h) document.documentElement.style.setProperty('--hauteur', Math.round(h) + 'px');
  fil.scrollTop = fil.scrollHeight;
}
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', ajusterHauteur);
  window.visualViewport.addEventListener('scroll', ajusterHauteur);
}
window.addEventListener('orientationchange', () => setTimeout(ajusterHauteur, 250));
ajusterHauteur();
champ.addEventListener('focus', () => setTimeout(ajusterHauteur, 300));

// ---- installation sur iPhone : iOS ne propose JAMAIS « Installer l'application ». Le seul
// chemin est Safari ▸ Partager ▸ « Sur l'écran d'accueil ». Chrome et les autres navigateurs de
// l'iPhone ne savent pas le faire de façon fiable, d'où la mention explicite de Safari.
function proposerInstallation() {
  if (!IOS || AUTONOME) return;
  if (memoire('iris_ios_installe') === 'vu') return;
  document.getElementById('banniere-texte').textContent = SAFARI_IOS
    ? "Gardez IRIS sous la main : touchez Partager, en bas de Safari, puis « Sur l'écran d'accueil »."
    : "Gardez IRIS sous la main : ouvrez cette adresse dans Safari — seul lui sait le faire sur iPhone — puis Partager, puis « Sur l'écran d'accueil ».";
  document.getElementById('banniere').hidden = false;
  ajusterHauteur();
}
document.getElementById('banniere-ok').addEventListener('click', () => {
  document.getElementById('banniere').hidden = true;
  retenir('iris_ios_installe', 'vu');   // fermé une fois, fermé pour de bon
  ajusterHauteur();
});
proposerInstallation();

demarrer().then(() => { verifier(); sonderBrouillons(false); });
setInterval(verifier, 20000);
// Cinq secondes : le temps qu'IRIS mette à dire « c'est prêt sur ton téléphone » — plus long, on
// regarderait un écran vide en l'écoutant ; plus court, ce serait du bruit sur un réseau WiFi.
setInterval(sonderBrouillons, 5000);

// Agent de service : il permet à Android de proposer « Installer l'application », et sur iOS il
// sert la coquille hors ligne une fois la page posée sur l'écran d'accueil.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* sans lui, la page marche quand même */ });
}
</script>
</body>
</html>"""


MANIFESTE = {
    "name": "IRIS",
    "short_name": "IRIS",
    "description": "Commandez votre ordinateur à la voix, où que vous soyez.",
    "start_url": "/m",
    "scope": "/",
    "display": "standalone",   # plein écran, sans barre de navigateur
    "orientation": "portrait",
    "background_color": "#1B140E",   # encre VELA
    "theme_color": "#1B140E",
    "lang": "fr-CA",
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

# Agent de service minimal. Android exige un gestionnaire `fetch` pour proposer l'installation.
# On ne met JAMAIS l'API en cache : les réponses d'IRIS sont des données vivantes, et une réponse
# périmée servie hors ligne serait pire que pas de réponse du tout.
AGENT_SERVICE = """
const CACHE = 'iris-coquille-v2';
const COQUILLE = ['/m', '/icone-192.png', '/icone-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(COQUILLE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((noms) => Promise.all(noms.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;  // jamais de cache sur les données
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok && COQUILLE.some((c) => url.pathname === c)) {
          const copie = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copie));
        }
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('/m')))
  );
});
"""


def urls_locales(port: int, token: str) -> list[dict]:
    """Adresses à ouvrir sur le téléphone, pour chaque carte réseau de la machine."""
    import socket

    adresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in adresses:
                continue
            adresses.append(ip)
    except Exception:
        pass
    return [{"ip": ip, "url": f"http://{ip}:{port}/m?token={token}"} for ip in adresses]
