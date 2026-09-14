/* IRIS — liaison entre la page téléphone et l'ordinateur : session, requêtes, événements en direct.
 *
 * Module ES sans dépendance. Il ne dessine rien : coeur.js et les modules de fonctions s'en servent
 * par window.IRIS.api et window.IRIS.bus (on peut aussi l'importer : import { api } from './api.js').
 *
 * UNE SEULE liaison par page, quel que soit le nombre de copies de ce fichier évaluées : la page /m
 * embarque ce code en ligne (mobile.py), et un module qui importe /m/js/api.js en évalue une seconde
 * copie. Deux liaisons, ce seraient deux jetons, deux WebSocket et deux bus qui s'ignorent. La
 * première copie dépose donc la liaison sur window.__IRIS_LIAISON__ et les suivantes la reprennent.
 *
 * Règles apprises à nos dépens, à ne pas défaire :
 * - Safari lève une TypeError à chaque requête si les en-têtes de fetch sont un mandataire (Proxy) :
 *   chaque requête construit un objet neuf (enTetes()) ;
 * - le jeton change après la connexion : il est relu à chaque requête, jamais figé ;
 * - Safari en navigation privée fait lever localStorage : on n'y touche que par memoire/retenir/oublier ;
 * - un WebSocket refusé (verrouillage, session révoquée) ne doit pas être rouvert en rafale : les
 *   essais s'espacent jusqu'à 30 secondes.
 */

function creerLiaison() {
  // ---------------------------------------------------------------- stockage local
  function memoire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function retenir(cle, valeur) { try { localStorage.setItem(cle, valeur); } catch (e) { /* navigation privée : tant pis */ } }
  function oublier(cle) { try { localStorage.removeItem(cle); } catch (e) { /* navigation privée : tant pis */ } }

  const BASE = location.origin;
  const params = new URLSearchParams(location.search);

  // Le jeton d'adresse (« /m?token=… ») sert au premier appairage tant qu'aucun mot de passe n'existe.
  // Dès qu'il en existe un, c'est la session ouverte avec le mot de passe qui fait foi : l'ordinateur
  // refuse le jeton d'adresse venu d'un autre appareil (main._raison_jeton).
  let JETON = memoire('iris_session') || params.get('token') || memoire('iris_token') || '';
  if (params.get('token')) retenir('iris_token', params.get('token'));

  // Un objet neuf à chaque appel : voir l'en-tête du fichier (Safari et les mandataires).
  function enTetes() { return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + JETON }; }

  // ---------------------------------------------------------------- bus d'événements
  // Les événements de l'ordinateur (WebSocket) et ceux de la page (« iris.* ») passent par le même bus.
  const ecouteurs = new Map();   // type -> Set de fonctions ; « * » = tous les événements
  let derniereErreurEcouteur = null;

  function diffuser(evenement) {
    if (!evenement || typeof evenement.type !== 'string') return;
    for (const cle of [evenement.type, '*']) {
      const liste = ecouteurs.get(cle);
      if (!liste) continue;
      for (const fonction of Array.from(liste)) {
        // Un écouteur qui plante ne doit priver ni les autres, ni la page, de la suite.
        try { fonction(evenement); } catch (e) { derniereErreurEcouteur = e; }
      }
    }
  }

  const bus = {
    /** on(type, fonction) -> désabonnement. on(fonction) ou on('*', fonction) : tous les événements. */
    on(type, fonction) {
      if (typeof type === 'function') { fonction = type; type = '*'; }
      if (typeof fonction !== 'function') return () => {};
      const cle = String(type || '*');
      if (!ecouteurs.has(cle)) ecouteurs.set(cle, new Set());
      ecouteurs.get(cle).add(fonction);
      return () => { const liste = ecouteurs.get(cle); if (liste) liste.delete(fonction); };
    },
    /** emit(type, données) ou emit({type, …}). Le type donné en premier l'emporte sur un champ « type ». */
    emit(type, donnees) {
      if (typeof type === 'string') diffuser(Object.assign({}, donnees || {}, { type }));
      else diffuser(type);
    },
  };

  // ---------------------------------------------------------------- état de la liaison
  let pcJoignable = null;   // null = pas encore vérifié
  function signalerConnexion(joignable) {
    if (pcJoignable === joignable) return;
    pcJoignable = joignable;
    diffuser({ type: 'iris.connexion', pc: joignable });
  }

  // ---------------------------------------------------------------- requêtes
  class ErreurApi extends Error {
    constructor(message, statut, detail) {
      super(message);
      this.name = 'ErreurApi';
      this.status = statut;       // même nom que l'ApiError du bureau
      this.statut = statut;
      this.detail = detail === undefined ? null : detail;
      this.code = (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.code) || null;
      this.reseau = false;
      this.expire = false;
    }
  }

  function messageDe(detail, statut) {
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof detail.message === 'string') return detail.message;
    if (Array.isArray(detail)) return "IRIS a refusé la demande : données incomplètes ou invalides.";
    return "L'ordinateur a répondu par une erreur (" + statut + ').';
  }

  async function requete(methode, chemin, corps, options) {
    const opts = options || {};
    const delai = Number(opts.delai) > 0 ? Number(opts.delai) : 30000;
    const controle = new AbortController();
    const minuterie = setTimeout(() => controle.abort(), delai);
    let reponse;
    try {
      reponse = await fetch(BASE + chemin, {
        method: methode,
        headers: enTetes(),
        body: corps === undefined ? undefined : JSON.stringify(corps),
        signal: controle.signal,
        cache: 'no-store',
      });
    } catch (e) {
      clearTimeout(minuterie);
      const expire = controle.signal.aborted;
      const erreur = new ErreurApi(expire
        ? "L'ordinateur n'a pas répondu dans les " + Math.round(delai / 1000) + ' secondes.'
        : "L'ordinateur ne répond pas.", 0, null);
      erreur.expire = expire;
      erreur.reseau = !expire;
      if (!expire) signalerConnexion(false);
      throw erreur;
    }
    clearTimeout(minuterie);
    signalerConnexion(true);   // une réponse HTTP, même une erreur, prouve que l'ordinateur est là

    const json = (reponse.headers.get('content-type') || '').indexOf('application/json') !== -1;
    let charge = null;
    try { charge = json ? await reponse.json() : await reponse.text(); } catch (e) { charge = null; }
    if (reponse.ok) return charge;

    const detail = charge && typeof charge === 'object' && !Array.isArray(charge) ? charge.detail : charge;
    const message = messageDe(detail, reponse.status);
    if (reponse.status === 401) {
      // Deux refus très différents : IRIS verrouillée (on déverrouille avec le mot de passe) ou
      // session refusée (on se reconnecte). Le détail le dit ; coeur.js affiche l'écran qui convient.
      if (/verrouill/i.test(message)) diffuser({ type: 'iris.verrouillee', raison: message });
      else diffuser({ type: 'iris.session_refusee', raison: message });
    }
    if (reponse.status === 428 && detail && typeof detail === 'object' && detail.code === 'lunettes_requises') {
      // Lunettes d'abord : coeur.js affiche l'invitation générale, sauf si le module l'a déjà fait dans sa
      // propre zone (IRIS.lunettes.garde().refus pose erreur.geree). L'erreur voyage avec l'événement.
      const erreur = new ErreurApi(message, reponse.status, detail);
      diffuser({ type: 'iris.lunettes_requises', erreur, fonction: detail.fonction || '', message: detail.message || message, acheter_url: detail.acheter_url || '' });
      throw erreur;
    }
    throw new ErreurApi(message, reponse.status, detail);
  }

  /** Binaire authentifié (image d'un reçu, fichier de l'album) : un <img src> nu ne porte pas le jeton. */
  async function blob(chemin) {
    let reponse;
    try {
      reponse = await fetch(BASE + chemin, { headers: { 'Authorization': 'Bearer ' + JETON }, cache: 'no-store' });
    } catch (e) {
      signalerConnexion(false);
      const erreur = new ErreurApi("L'ordinateur ne répond pas.", 0, null);
      erreur.reseau = true;
      throw erreur;
    }
    signalerConnexion(true);
    if (!reponse.ok) throw new ErreurApi('Fichier indisponible (' + reponse.status + ').', reponse.status, null);
    return reponse.blob();
  }

  // ---------------------------------------------------------------- WebSocket des événements
  // La session ouverte avec le mot de passe est acceptée par /ws (même règle que le HTTP) : le jeton
  // passe dans l'adresse, un navigateur ne sachant pas poser d'en-tête sur un WebSocket.
  let ws = null;
  let wsVoulu = false;
  let wsOuvert = false;
  let essais = 0;
  let minuterieReconnexion = null;
  let minuterieVeille = null;
  let dernierMessage = 0;
  const PING_MS = 25000;        // un tunnel coupe volontiers une liaison muette
  const SILENCE_MAX_MS = 70000; // plus rien depuis ce délai : la liaison est morte sans le dire

  function changerEtatWs(ouvert, extra) {
    if (wsOuvert === ouvert && !extra) return;
    wsOuvert = ouvert;
    diffuser(Object.assign({ type: 'iris.ws', ouvert }, extra || {}));
  }

  function planifierReconnexion() {
    if (!wsVoulu) return;
    clearTimeout(minuterieReconnexion);
    const delai = Math.min(30000, 1500 * Math.pow(2, Math.min(essais, 5)));
    essais += 1;
    minuterieReconnexion = setTimeout(connecterEvenements, delai);
  }

  function connecterEvenements() {
    wsVoulu = true;
    clearTimeout(minuterieReconnexion);
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    if (!JETON) return;
    const schema = location.protocol === 'https:' ? 'wss://' : 'ws://';
    let socket;
    try {
      socket = new WebSocket(schema + location.host + '/ws?token=' + encodeURIComponent(JETON));
    } catch (e) {
      planifierReconnexion();
      return;
    }
    ws = socket;
    socket.onopen = () => {
      essais = 0;
      dernierMessage = Date.now();
      changerEtatWs(true);
      clearInterval(minuterieVeille);
      minuterieVeille = setInterval(() => {
        if (ws !== socket) return;
        if (Date.now() - dernierMessage > SILENCE_MAX_MS) { try { socket.close(); } catch (e) { /* déjà fermé */ } return; }
        try { socket.send(JSON.stringify({ type: 'ping' })); } catch (e) { /* onclose suivra */ }
      }, PING_MS);
    };
    socket.onmessage = (message) => {
      dernierMessage = Date.now();
      let evenement = null;
      try { evenement = JSON.parse(message.data); } catch (e) { return; }
      diffuser(evenement);
    };
    socket.onerror = () => { /* onclose suit */ };
    socket.onclose = (e) => {
      if (ws === socket) ws = null;
      clearInterval(minuterieVeille);
      const refuse = !!(e && e.code === 4401);
      // 4401 : verrouillage ou session refusée. On le dit et on espace les essais (pas de rafale).
      if (refuse) essais = Math.max(essais, 4);
      changerEtatWs(false, refuse ? { refuse: true, raison: (e && e.reason) || '' } : null);
      planifierReconnexion();
    };
  }

  function fermerEvenements() {
    wsVoulu = false;
    clearTimeout(minuterieReconnexion);
    clearInterval(minuterieVeille);
    if (ws) { try { ws.close(); } catch (e) { /* déjà fermé */ } }
    ws = null;
    changerEtatWs(false);
  }

  // Page ramenée au premier plan (iOS coupe tout en arrière-plan) : on reprend sans attendre le délai.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && wsVoulu && !ws && essais < 4) connecterEvenements();
  });
  window.addEventListener('online', () => { if (wsVoulu && !ws) { essais = 0; connecterEvenements(); } });

  // ---------------------------------------------------------------- interface publique
  const api = {
    base: BASE,
    jeton: () => JETON,
    jetonDansAdresse: () => params.get('token') || '',
    pcJoignable: () => pcJoignable,
    evenementsOuverts: () => wsOuvert,

    /** État du compte, public : faut-il un mot de passe ? */
    async compte() {
      return requete('GET', '/api/compte', undefined, { delai: 12000 });
    },
    /** Échange le mot de passe contre une session (30 jours) et la retient sur ce téléphone. */
    async connexion(motDePasse) {
      let reponse;
      try {
        reponse = await fetch(BASE + '/api/compte/connexion', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mot_de_passe: motDePasse }), cache: 'no-store',
        });
      } catch (e) {
        signalerConnexion(false);
        const erreur = new ErreurApi("L'ordinateur ne répond pas.", 0, null);
        erreur.reseau = true;
        throw erreur;
      }
      signalerConnexion(true);
      const charge = await reponse.json().catch(() => ({}));
      if (!reponse.ok) {
        throw new ErreurApi(reponse.status === 401 ? 'Mot de passe incorrect.' : messageDe(charge.detail, reponse.status), reponse.status, charge.detail);
      }
      api.ouvrirSession(charge.session);
      return charge;
    },
    ouvrirSession(session) {
      JETON = session || '';
      retenir('iris_session', JETON);
      // Un mot de passe existe : le jeton d'adresse ne vaut plus rien depuis ce téléphone, on l'oublie.
      oublier('iris_token');
    },
    /** Oublie la session de CE téléphone (les autres appareils restent connectés). */
    fermerSession() {
      oublier('iris_session');
      JETON = memoire('iris_token') || '';
      fermerEvenements();
    },
    oublierJetonAdresse() {
      oublier('iris_token');
      if (!memoire('iris_session')) JETON = '';
    },

    request: requete,
    requete,
    get: (chemin, options) => requete('GET', chemin, undefined, options),
    post: (chemin, corps, options) => requete('POST', chemin, corps === undefined ? {} : corps, options),
    put: (chemin, corps, options) => requete('PUT', chemin, corps === undefined ? {} : corps, options),
    patch: (chemin, corps, options) => requete('PATCH', chemin, corps === undefined ? {} : corps, options),
    delete: (chemin, options) => requete('DELETE', chemin, undefined, options),
    blob,

    /** Même forme que le bureau : api.on(fonction) reçoit tout ; api.on(type, fonction) un seul type. */
    on: (type, fonction) => bus.on(type, fonction),
    /** Message vers l'ordinateur par le WebSocket ; false s'il n'est pas ouvert. */
    send(message) {
      if (ws && ws.readyState === 1) {
        try { ws.send(JSON.stringify(message)); return true; } catch (e) { return false; }
      }
      return false;
    },
    connecterEvenements,
    fermerEvenements,
    derniereErreurEcouteur: () => derniereErreurEcouteur,
  };

  return { api, bus, memoire, retenir, oublier, ErreurApi };
}

const liaison = window.__IRIS_LIAISON__ || (window.__IRIS_LIAISON__ = creerLiaison());
export const { api, bus, memoire, retenir, oublier, ErreurApi } = liaison;
export default liaison.api;
