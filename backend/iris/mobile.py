"""Page mobile : parler à IRIS depuis le téléphone, pour agir sur l'ordinateur resté à la maison.

Pourquoi une page dédiée plutôt que l'interface de bureau : dans une voiture ou en marchant, on ne
navigue pas dans quatre colonnes. Il faut un bouton, une réponse, et rien d'autre.

Comment ça se tient ensemble : les lunettes se connectent en Bluetooth au TÉLÉPHONE (dix mètres),
le téléphone porte cette page, et la page parle à l'ordinateur de la maison par le réseau. C'est
le seul montage possible : les lunettes n'ont ni WiFi ni carte SIM.

La reconnaissance vocale est celle du navigateur (gratuite, pas de clé). La réponse est lue par la
synthèse du téléphone, donc entendue dans les lunettes puisqu'elles en sont la sortie audio.
"""
from __future__ import annotations

PAGE = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0d0c">
<title>IRIS</title>
<style>
  :root { --bg:#0b0d0c; --surface:#14181a; --line:#232a2c; --text:#e8efec; --text-2:#94a3a0;
          --accent:#17c793; --accent-dark:#0f6e56; --danger:#ef5f5f; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; background:var(--bg); color:var(--text); min-height:100dvh;
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         display:flex; flex-direction:column; padding:env(safe-area-inset-top) 16px env(safe-area-inset-bottom); }
  header { display:flex; align-items:center; gap:10px; padding:14px 0 10px; }
  .ring { width:26px; height:26px; flex:none; }
  .nom { font-weight:600; letter-spacing:.14em; font-size:13px; }
  .etat { margin-left:auto; font-size:12px; color:var(--text-2); display:flex; align-items:center; gap:6px; }
  .point { width:8px; height:8px; border-radius:50%; background:var(--text-2); }
  .point.ok { background:var(--accent); }
  .point.err { background:var(--danger); }

  #fil { flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:10px; padding:6px 0 16px; }
  .bulle { max-width:88%; padding:11px 14px; border-radius:16px; white-space:pre-wrap; word-wrap:break-word; }
  .moi { align-self:flex-end; background:var(--accent-dark); border-bottom-right-radius:5px; }
  .elle { align-self:flex-start; background:var(--surface); border:1px solid var(--line); border-bottom-left-radius:5px; }
  .info { align-self:center; font-size:13px; color:var(--text-2); text-align:center; padding:0 12px; }

  footer { padding:10px 0 16px; display:flex; flex-direction:column; gap:10px; }
  #parler { width:100%; min-height:76px; border:none; border-radius:20px; background:var(--accent);
            color:#04120d; font-size:19px; font-weight:600; display:flex; align-items:center;
            justify-content:center; gap:10px; transition:transform .1s, background .2s; }
  #parler:active { transform:scale(.98); }
  #parler.ecoute { background:var(--danger); color:#fff; animation:pulse 1.2s ease-in-out infinite; }
  #parler.occupe { background:var(--line); color:var(--text-2); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.72} }
  .ligne { display:flex; gap:8px; }
  #texte { flex:1; background:var(--surface); border:1px solid var(--line); border-radius:14px;
           padding:12px 14px; color:var(--text); font-size:16px; }
  #envoyer { border:none; border-radius:14px; padding:0 18px; background:var(--surface);
             border:1px solid var(--line); color:var(--text); font-size:15px; }
  @media (prefers-reduced-motion: reduce) { *{animation:none!important; transition:none!important} }
</style>
</head>
<body>
<header>
  <svg class="ring" viewBox="0 0 120 120" aria-hidden="true">
    <path d="M 72 24 A 36 36 0 1 0 84 62" fill="none" stroke="#17c793" stroke-width="11" stroke-linecap="round"/>
  </svg>
  <span class="nom">IRIS</span>
  <span class="etat"><span class="point" id="point"></span><span id="etat">connexion…</span></span>
</header>

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
const JETON = params.get('token') || localStorage.getItem('iris_token') || '';
if (JETON) localStorage.setItem('iris_token', JETON);
const BASE = location.origin;
const EN_TETES = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + JETON };

const fil = document.getElementById('fil');
const bouton = document.getElementById('parler');
const champ = document.getElementById('texte');
const point = document.getElementById('point');
const etat = document.getElementById('etat');
let conversation = localStorage.getItem('iris_conv') || null;
let occupe = false;

function marquer(ok, texte) { point.className = 'point ' + (ok === null ? '' : ok ? 'ok' : 'err'); etat.textContent = texte; }
function bulle(classe, texte) {
  const acc = document.getElementById('accueil'); if (acc) acc.remove();
  const d = document.createElement('div');
  d.className = 'bulle ' + classe; d.textContent = texte;
  fil.appendChild(d); fil.scrollTop = fil.scrollHeight; return d;
}
function dire(texte) {
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(texte);
    u.lang = 'fr-CA'; u.rate = 1.05;
    speechSynthesis.speak(u);          // sortie audio du téléphone = les lunettes
  } catch (e) { /* la lecture n'est pas indispensable */ }
}

async function verifier() {
  try {
    const r = await fetch(BASE + '/api/status', { headers: EN_TETES });
    if (r.status === 401) return marquer(false, 'jeton refusé');
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
      const c = await fetch(BASE + '/api/conversations', { method:'POST', headers: EN_TETES,
        body: JSON.stringify({ title: texte.slice(0, 40), agent: 'auto' }) }).then(r => r.json());
      conversation = c.id; localStorage.setItem('iris_conv', conversation);
    }
    await fetch(BASE + '/api/conversations/' + conversation + '/messages', { method:'POST', headers: EN_TETES,
      body: JSON.stringify({ text: texte, agent: 'auto', images: [] }) });

    const debut = Date.now(); let reponse = null;
    while (Date.now() - debut < 120000) {
      await new Promise(r => setTimeout(r, 1200));
      const d = await fetch(BASE + '/api/conversations/' + conversation, { headers: EN_TETES }).then(r => r.json());
      const dernier = (d.messages || []).filter(m => m.role === 'assistant').pop();
      if (dernier && (dernier.text || (dernier.meta || {}).error)) { reponse = dernier.text || dernier.meta.error; break; }
    }
    if (reponse) { bulle('elle', reponse); dire(reponse); }
    else bulle('info', "IRIS n'a pas répondu à temps.");
  } catch (e) {
    bulle('info', 'Ordinateur injoignable : ' + e.message);
    marquer(false, 'injoignable');
  } finally {
    occupe = false; bouton.classList.remove('occupe'); bouton.textContent = '🎙 Appuyez pour parler';
  }
}

// ---- reconnaissance vocale du navigateur : gratuite, aucune clé
const Reco = window.SpeechRecognition || window.webkitSpeechRecognition;
let reco = null;
if (Reco) {
  reco = new Reco(); reco.lang = 'fr-CA'; reco.interimResults = false; reco.maxAlternatives = 1;
  reco.onresult = (e) => envoyer(e.results[0][0].transcript);
  reco.onerror = (e) => { bouton.classList.remove('ecoute');
    bouton.textContent = '🎙 Appuyez pour parler';
    if (e.error === 'not-allowed') bulle('info', "Micro refusé. Autorisez-le dans le navigateur."); };
  reco.onend = () => { bouton.classList.remove('ecoute');
    if (!occupe) bouton.textContent = '🎙 Appuyez pour parler'; };
} else {
  bouton.textContent = '🎙 Voix indisponible — écrivez';
}

bouton.addEventListener('click', () => {
  if (occupe) return;
  if (!reco) { champ.focus(); return; }
  try {
    speechSynthesis.cancel();
    reco.start();
    bouton.classList.add('ecoute'); bouton.textContent = '● Parlez…';
  } catch (e) { reco.stop(); }
});
document.getElementById('envoyer').addEventListener('click', () => { envoyer(champ.value); champ.value = ''; });
champ.addEventListener('keydown', (e) => { if (e.key === 'Enter') { envoyer(champ.value); champ.value = ''; } });

verifier(); setInterval(verifier, 20000);
</script>
</body>
</html>"""


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
