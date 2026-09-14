/* IRIS — guidage à pied depuis le téléphone : « Où suis-je ? » et « Guide-moi ».
 *
 * Pourquoi ici et pas sur l'ordinateur : dehors, l'ordinateur est resté à la maison et ne sait rien de
 * la rue. La position du téléphone sert à trouver l'adresse et l'itinéraire auprès des services publics
 * d'OpenStreetMap, directement depuis cette page : elle n'est JAMAIS envoyée à IRIS ni à l'ordinateur.
 * D'où un accord explicite, retenu sur ce téléphone, avant la toute première requête.
 *
 * Règles d'usage d'OpenStreetMap respectées : une recherche d'adresse par seconde au plus (file
 * d'attente), aucune recherche pendant la frappe (seulement sur « Chercher »), attribution visible
 * « © contributeurs OpenStreetMap », et la page s'identifie par son origine (en-tête Referer).
 *
 * Ce que le guidage ne fait pas, et que l'écran dit : détecter un obstacle, des travaux ou l'état d'un
 * feu pour piétons ; marcher écran éteint ou page en arrière-plan (iOS suspend la page) ; être plus
 * précis que le GPS du téléphone. Les distances et durées sont des estimations, jamais des promesses.
 *
 * Lunettes d'abord : le guidage est une fonction des lunettes VELA. Le panneau vérifie leur présence
 * (lunettes.js) avant chaque recherche ou trajet et affiche l'invitation à les connecter sinon. Un
 * trajet déjà commencé n'est JAMAIS coupé net si les lunettes disparaissent en route : on prévient, et
 * le trajet continue jusqu'à l'arrivée ou l'arrêt. La sécurité d'une personne qui marche passe avant
 * la règle commerciale ; seul un NOUVEAU trajet exige de les reconnecter.
 *
 * Module du contrat window.IRIS (interface K) : il ne touche à rien d'autre que son panneau.
 */

const NOMINATIM = 'https://nominatim.openstreetmap.org';
const ITINERAIRE = 'https://routing.openstreetmap.de/routed-foot/route/v1/foot/';
const CLE_ACCORD = 'iris_guidage_accord';
const CLE_ANNONCES = 'iris_guidage_annonces';
const PAUSE_NOMINATIM_MS = 1100;      // « une requête par seconde au plus », avec une marge
const PAUSE_ITINERAIRE_MS = 1000;     // courtoisie envers un serveur bénévole
const DELAI_RESEAU_MS = 15000;
const DISTANCE_PREAVIS_M = 40;
const DISTANCE_MANOEUVRE_M = 10;
const ECART_MAX_M = 35;
const RECALCUL_MIN_MS = 20000;
const PRECISION_INUTILISABLE_M = 80;  // au-delà, une annonce « tournez » tomberait n'importe où
const ARRIVEE_M = 15;
const DISTANCE_MAX_KM = 100;
const RAYON_TERRE_M = 6371000;

// ------------------------------------------------------------------ petits outils (aucune dépendance)
function el(balise, attributs, ...enfants) {
  const noeud = document.createElement(balise);
  for (const [cle, valeur] of Object.entries(attributs || {})) {
    if (valeur === null || valeur === undefined || valeur === false) continue;
    if (cle === 'class') noeud.className = valeur;
    else noeud.setAttribute(cle, valeur === true ? '' : String(valeur));
  }
  for (const enfant of enfants.flat()) {
    if (enfant === null || enfant === undefined || enfant === false) continue;
    noeud.append(enfant instanceof Node ? enfant : document.createTextNode(String(enfant)));
  }
  return noeud;
}
function memoireLocale(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
function retenirLocal(cle, valeur) { try { localStorage.setItem(cle, valeur); } catch (e) { /* navigation privée */ } }
function oublierLocal(cle) { try { localStorage.removeItem(cle); } catch (e) { /* navigation privée */ } }
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const IRISv = () => window.IRIS || {};

function toast(texte, genre) {
  const ui = IRISv().ui;
  if (ui && typeof ui.toast === 'function') ui.toast(texte, genre);
}
function confirmer(texte, options) {
  const ui = IRISv().ui;
  if (ui && typeof ui.confirmer === 'function') return ui.confirmer(texte, options);
  return Promise.resolve(window.confirm(texte));
}
function dire(texte, options) {
  const voix = IRISv().voix;
  if (!texte || !voix || typeof voix.parler !== 'function') return Promise.resolve(false);
  try { return Promise.resolve(voix.parler(texte, options)).catch(() => false); } catch (e) { return Promise.resolve(false); }
}

// ------------------------------------------------------------------ lunettes d'abord
// lunettes.js est chargé dès l'évaluation de ce module : si la page ne l'a pas déjà fait, il l'est ici
// (même adresse, donc une seule copie). Sans lui, rien ne peut être vérifié : la fonction reste fermée.
const chargementLunettes = import('./lunettes.js').catch(() => null);
async function gardeLunettes(ctx, options) {
  await chargementLunettes;
  const outil = window.IRIS && window.IRIS.lunettes;
  if (outil && typeof outil.garde === 'function') {
    try { return outil.garde(ctx, options); } catch (e) { /* repli ci-dessous : fonction fermée */ }
  }
  if (options.contenu) options.contenu.hidden = true;
  (options.zone || ctx.corps).append(el('p', { class: 'resultat-erreur', role: 'alert' },
    "La vérification des lunettes VELA n'a pas pu se charger sur cette page : rechargez-la. Cette fonction reste fermée d'ici là."));
  return { verifier: () => Promise.resolve(false), refus: () => false, presentes: () => false, etat: () => null, fermer() {} };
}

/** Nettoyage appelé une seule fois, quel que soit le chemin de fermeture (coquille, événement, retour). */
function brancherNettoyage(ctx, fonction) {
  let fait = false;
  const nettoyer = () => {
    if (fait) return;
    fait = true;
    try { fonction(); } catch (e) { /* un nettoyage raté ne doit pas bloquer la fermeture */ }
  };
  if (ctx && typeof ctx.surFermeture === 'function') ctx.surFermeture(nettoyer);
  if (ctx && ctx.corps) ctx.corps.addEventListener('iris:fermeture', nettoyer, { once: true });
  return nettoyer;
}

/** Écran allumé : la coquille gère le verrou par raison ; sinon, verrou direct avec reprise au retour. */
function fabriquerEveil(raison) {
  let verrou = null;
  let voulu = false;
  async function demander() {
    if (!('wakeLock' in navigator) || document.hidden) return false;
    try {
      verrou = await navigator.wakeLock.request('screen');
      verrou.addEventListener('release', () => { verrou = null; });
      return true;
    } catch (e) { verrou = null; return false; }
  }
  const auRetour = () => { if (voulu && !document.hidden && !verrou) demander(); };
  return async function activer(actif) {
    const ui = IRISv().ui;
    if (ui && typeof ui.garderEcranAllume === 'function') {
      try { return !!(await ui.garderEcranAllume(raison, actif)); } catch (e) { return false; }
    }
    voulu = !!actif;
    if (voulu) {
      document.addEventListener('visibilitychange', auRetour);
      return verrou ? true : demander();
    }
    document.removeEventListener('visibilitychange', auRetour);
    if (verrou) { try { await verrou.release(); } catch (e) { /* déjà libéré */ } verrou = null; }
    return false;
  };
}

// ------------------------------------------------------------------ nombres dits à voix haute
function nombreFr(n, decimales) {
  return Number(n).toLocaleString('fr-CA', { maximumFractionDigits: decimales || 0, minimumFractionDigits: 0 });
}
/** « 40 mètres », « 1,2 kilomètre », « 3,5 kilomètres ». */
function distanceParlee(metres) {
  const m = Math.max(0, Number(metres) || 0);
  if (m < 1000) {
    const arrondi = m < 100 ? Math.max(5, Math.round(m / 5) * 5) : Math.round(m / 10) * 10;
    return nombreFr(arrondi) + ' mètres';
  }
  const km = Math.round(m / 100) / 10;
  return nombreFr(km, 1) + (km < 2 ? ' kilomètre' : ' kilomètres');
}
function distanceCourte(metres) {
  const m = Math.max(0, Number(metres) || 0);
  return m < 1000 ? nombreFr(Math.round(m / 5) * 5) + ' m' : nombreFr(Math.round(m / 100) / 10, 1) + ' km';
}
function dureeParlee(secondes) {
  const minutes = Math.max(1, Math.round((Number(secondes) || 0) / 60));
  if (minutes < 60) return minutes + (minutes > 1 ? ' minutes' : ' minute');
  const h = Math.floor(minutes / 60);
  const reste = minutes % 60;
  return h + (h > 1 ? ' heures' : ' heure') + (reste ? ' ' + reste : '');
}
const initialeMinuscule = (t) => (t ? t.charAt(0).toLowerCase() + t.slice(1) : '');

// ------------------------------------------------------------------ géométrie (sans bibliothèque)
const rad = (d) => (d * Math.PI) / 180;
function haversine(a, b) {
  const dp = rad(b.lat - a.lat);
  const dl = rad(b.lon - a.lon);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dl / 2) ** 2;
  return 2 * RAYON_TERRE_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Distance d'un point à une ligne [[lat, lon], …] et longueur de ligne restante depuis le point projeté.
 * Projection plane locale centrée sur le point : l'erreur est négligeable à l'échelle d'une étape à pied.
 */
function projeter(p, ligne) {
  if (!ligne || !ligne.length) return { distance: Infinity, restant: 0 };
  const k = Math.cos(rad(p.lat));
  const pts = ligne.map((q) => [rad(q[1] - p.lon) * k * RAYON_TERRE_M, rad(q[0] - p.lat) * RAYON_TERRE_M]);
  if (pts.length === 1) return { distance: Math.hypot(pts[0][0], pts[0][1]), restant: 0 };
  let meilleur = { distance: Infinity, i: 0, t: 0 };
  for (let i = 0; i < pts.length - 1; i++) {
    const ax = pts[i][0], ay = pts[i][1];
    const dx = pts[i + 1][0] - ax, dy = pts[i + 1][1] - ay;
    const l2 = dx * dx + dy * dy;
    const t = l2 ? Math.min(1, Math.max(0, -(ax * dx + ay * dy) / l2)) : 0;
    const d = Math.hypot(ax + t * dx, ay + t * dy);
    if (d < meilleur.distance) meilleur = { distance: d, i, t };
  }
  const longueur = (i) => Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
  let restant = longueur(meilleur.i) * (1 - meilleur.t);
  for (let j = meilleur.i + 1; j < pts.length - 1; j++) restant += longueur(j);
  return { distance: meilleur.distance, restant };
}

// ------------------------------------------------------------------ position du téléphone
function geolocalisationPossible() { return !!(window.isSecureContext && navigator.geolocation); }
function raisonSansGeolocalisation() {
  if (!window.isSecureContext) {
    return "La position n'est accessible qu'à une page sécurisée (adresse en https). Ouvrez IRIS par l'adresse de votre réseau privé, pas par une adresse locale en http.";
  }
  return "Ce navigateur ne donne pas accès à la position.";
}
function messageGeolocalisation(e) {
  if (e && e.code === 1) {
    return "Position refusée pour cette page. Sur iPhone : Réglages › Confidentialité et sécurité › Service de localisation › Sites web Safari, puis réessayez.";
  }
  if (e && e.code === 3) return "Position non obtenue à temps : allez à découvert, loin des grands immeubles, puis réessayez.";
  return "Position indisponible pour l'instant (signal GPS absent ou service de localisation coupé).";
}
function versPoint(p) {
  return { lat: p.coords.latitude, lon: p.coords.longitude, precision: Math.round(Number(p.coords.accuracy) || 0), t: Date.now() };
}
function positionActuelle() {
  return new Promise((resoudre, rejeter) => {
    if (!geolocalisationPossible()) { rejeter(new Error(raisonSansGeolocalisation())); return; }
    try {
      navigator.geolocation.getCurrentPosition((p) => resoudre(versPoint(p)), (e) => rejeter(new Error(messageGeolocalisation(e))),
        { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    } catch (e) { rejeter(new Error(messageGeolocalisation(null))); }
  });
}

// ------------------------------------------------------------------ OpenStreetMap
function erreurAnnulee() { const e = new Error('Demande annulée.'); e.annule = true; return e; }

/** GET JSON vers OpenStreetMap. Rend {statut, donnees} ; lève une Error au message affichable. */
async function lireJson(url, signal) {
  if (signal && signal.aborted) throw erreurAnnulee();
  const controle = new AbortController();
  const minuterie = setTimeout(() => controle.abort(), DELAI_RESEAU_MS);
  const annuler = () => controle.abort();
  if (signal) signal.addEventListener('abort', annuler, { once: true });
  try {
    let reponse;
    try {
      reponse = await fetch(url, {
        headers: { Accept: 'application/json' }, credentials: 'omit', cache: 'no-store',
        referrerPolicy: 'strict-origin-when-cross-origin', signal: controle.signal,
      });
    } catch (e) {
      if (signal && signal.aborted) throw erreurAnnulee();
      throw new Error(controle.signal.aborted
        ? "OpenStreetMap n'a pas répondu dans les 15 secondes."
        : "OpenStreetMap est injoignable : vérifiez les données mobiles ou le Wi-Fi de ce téléphone.");
    }
    if (reponse.status === 429) throw new Error('OpenStreetMap limite le nombre de demandes : réessayez dans une minute.');
    let donnees = null;
    try { donnees = await reponse.json(); } catch (e) { donnees = null; }
    if (signal && signal.aborted) throw erreurAnnulee();
    if (!reponse.ok && !(donnees && typeof donnees === 'object')) {
      throw new Error("OpenStreetMap a refusé la demande (" + reponse.status + ').');
    }
    return { statut: reponse.status, donnees };
  } finally {
    clearTimeout(minuterie);
    if (signal) signal.removeEventListener('abort', annuler);
  }
}

// Une file unique pour toute la page : deux panneaux ou deux gestes rapides ne doublent pas le débit.
let fileNominatim = Promise.resolve();
let derniereNominatim = 0;
function demanderNominatim(chemin, signal) {
  const tour = fileNominatim.then(async () => {
    const attente = derniereNominatim + PAUSE_NOMINATIM_MS - Date.now();
    if (attente > 0) await pause(attente);
    if (signal && signal.aborted) throw erreurAnnulee();
    derniereNominatim = Date.now();
    const r = await lireJson(NOMINATIM + chemin, signal);
    if (r.statut >= 400) throw new Error("OpenStreetMap a refusé la demande (" + r.statut + ').');
    return r.donnees;
  });
  fileNominatim = tour.catch(() => null);
  return tour;
}
let derniereItineraire = 0;

const fixe = (n) => Number(n).toFixed(6);

/** Adresse lisible d'une réponse de recherche inverse. */
function adresseLisible(d) {
  const a = (d && d.address) || {};
  const rue = a.road || a.pedestrian || a.footway || a.path || a.cycleway || a.square || a.place || '';
  const ville = a.city || a.town || a.village || a.municipality || a.hamlet || '';
  const quartier = a.neighbourhood || a.suburb || a.city_district || a.quarter || '';
  const lieu = d && d.name && d.name !== rue ? d.name : '';
  const morceaux = [];
  if (lieu) morceaux.push(lieu);
  if (rue) morceaux.push((a.house_number ? a.house_number + ', ' : '') + rue);
  if (quartier && quartier !== ville) morceaux.push(quartier);
  if (ville) morceaux.push(ville);
  if (morceaux.length) return morceaux.join(', ');
  return String((d && d.display_name) || '').split(',').slice(0, 4).join(',').trim();
}

function nomCourt(r) {
  const parties = String(r.display_name || '').split(',').map((s) => s.trim()).filter(Boolean);
  return r.name || parties[0] || 'Lieu sans nom';
}

// ------------------------------------------------------------------ instructions en français
const DIRECTIONS = {
  'uturn': 'faites demi-tour',
  'sharp right': 'tournez franchement à droite',
  'right': 'tournez à droite',
  'slight right': 'prenez légèrement à droite',
  'straight': 'continuez tout droit',
  'slight left': 'prenez légèrement à gauche',
  'left': 'tournez à gauche',
  'sharp left': 'tournez franchement à gauche',
};
const CARDINAUX = ['le nord', 'le nord-est', "l'est", 'le sud-est', 'le sud', 'le sud-ouest', "l'ouest", 'le nord-ouest'];
const ORDINAUX = ['', 'première', 'deuxième', 'troisième', 'quatrième', 'cinquième', 'sixième', 'septième', 'huitième', 'neuvième', 'dixième'];

const majuscule = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : '');
function nomVoie(step) { return String((step && (step.name || step.ref)) || '').trim(); }
function surVoie(nom) { return nom ? ' sur ' + nom : ''; }
function cote(modificateur) {
  if (/left/.test(modificateur || '')) return ', sur votre gauche';
  if (/right/.test(modificateur || '')) return ', sur votre droite';
  return '';
}

/** Une manœuvre de l'itinéraire -> une phrase française courte, sans ponctuation finale. */
function instruction(step) {
  const m = (step && step.maneuver) || {};
  const nom = nomVoie(step);
  const direction = DIRECTIONS[m.modifier] || '';
  switch (m.type) {
    case 'depart': {
      const cap = Number(m.bearing_after);
      const vers = Number.isFinite(cap) ? ' vers ' + CARDINAUX[Math.round(((cap % 360) + 360) % 360 / 45) % 8] : '';
      return 'Partez' + vers + surVoie(nom);
    }
    case 'arrive':
      return 'Vous arrivez à destination' + cote(m.modifier);
    case 'roundabout':
    case 'rotary': {
      const n = Number(m.exit);
      if (n > 0) return 'Au rond-point, prenez la ' + (ORDINAUX[n] || n + 'e') + ' sortie' + surVoie(nom);
      return 'Engagez-vous dans le rond-point' + surVoie(nom);
    }
    case 'roundabout turn':
      return 'Au rond-point, ' + (direction || 'continuez') + surVoie(nom);
    case 'exit roundabout':
    case 'exit rotary':
      return 'Sortez du rond-point' + surVoie(nom);
    case 'new name':
      return 'Continuez tout droit' + surVoie(nom);
    case 'continue':
      return majuscule(direction && m.modifier !== 'straight' ? direction : 'continuez tout droit') + surVoie(nom);
    case 'end of road':
      return 'Au bout de la voie, ' + (direction || 'tournez') + surVoie(nom);
    case 'fork':
      return "À l'embranchement, " + (/left/.test(m.modifier || '') ? 'gardez la gauche' : /right/.test(m.modifier || '') ? 'gardez la droite' : 'continuez tout droit') + surVoie(nom);
    case 'merge':
      return 'Rejoignez ' + (nom || 'la voie') + (direction && m.modifier !== 'straight' ? ' en tenant ' + (/left/.test(m.modifier) ? 'la gauche' : 'la droite') : '');
    default:
      return majuscule(direction || 'continuez') + surVoie(nom);
  }
}

/** Une simple continuation ne mérite pas de préavis à 40 m : on l'annonce seulement sur place. */
function meritePreavis(etape) {
  if (etape.type === 'new name') return false;
  if (etape.type === 'continue' && (!etape.modificateur || etape.modificateur === 'straight')) return false;
  return true;
}

function lireEtapes(route) {
  const brutes = (((route && route.legs) || [])[0] || {}).steps || [];
  return brutes.map((s) => {
    const m = s.maneuver || {};
    const coords = s.geometry && Array.isArray(s.geometry.coordinates) ? s.geometry.coordinates : [];
    return {
      type: m.type || '',
      modificateur: m.modifier || '',
      nom: nomVoie(s),
      distance: Number(s.distance) || 0,
      lieu: Array.isArray(m.location) ? { lat: Number(m.location[1]), lon: Number(m.location[0]) } : null,
      ligne: coords.map((c) => [Number(c[1]), Number(c[0])]),
      instruction: instruction(s),
      preavis: false,
      annoncee: false,
    };
  }).filter((e) => e.lieu && Number.isFinite(e.lieu.lat) && Number.isFinite(e.lieu.lon));
}

async function calculerItineraire(depart, arrivee, signal) {
  if (haversine(depart, arrivee) > DISTANCE_MAX_KM * 1000) {
    throw new Error('Destination à plus de ' + DISTANCE_MAX_KM + " km : le guidage à pied n'est pas fait pour ce trajet.");
  }
  const attente = derniereItineraire + PAUSE_ITINERAIRE_MS - Date.now();
  if (attente > 0) await pause(attente);
  derniereItineraire = Date.now();
  const url = ITINERAIRE + fixe(depart.lon) + ',' + fixe(depart.lat) + ';' + fixe(arrivee.lon) + ',' + fixe(arrivee.lat) +
    '?steps=true&overview=false&geometries=geojson';
  const r = await lireJson(url, signal);
  const d = r.donnees || {};
  if (d.code !== 'Ok' || !Array.isArray(d.routes) || !d.routes.length) {
    if (d.code === 'NoRoute') throw new Error("Aucun itinéraire à pied n'a été trouvé jusqu'à cette destination.");
    if (d.code === 'NoSegment') throw new Error("Votre position ou la destination est trop loin d'une rue ou d'un chemin connu d'OpenStreetMap.");
    throw new Error("Le service d'itinéraire d'OpenStreetMap n'a pas pu calculer le trajet (" + (d.code || r.statut) + ').');
  }
  const route = d.routes[0];
  const etapes = lireEtapes(route);
  if (!etapes.length) throw new Error("L'itinéraire reçu est vide : réessayez.");
  return { etapes, distance: Number(route.distance) || 0, duree: Number(route.duration) || 0 };
}

/** Première phrase d'une étape : la manœuvre, puis la longueur à parcourir. */
function phraseEtape(etape) {
  if (etape.type === 'arrive') return etape.instruction;
  return etape.instruction + (etape.distance >= 5 ? ', puis continuez pendant ' + distanceParlee(etape.distance) : '');
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const eveil = fabriquerEveil('guidage');
  const controleur = new AbortController();   // toutes les requêtes du panneau s'arrêtent à la fermeture
  let annoncesVocales = (memoireLocale(CLE_ANNONCES) || (memoireLocale('iris_lecture_auto') === 'non' ? 'non' : 'oui')) === 'oui';
  let nav = null;
  let generation = 0;

  corps.append(el('p', { class: 'note' },
    "Le guidage à pied utilise la position de ce téléphone et les données d'OpenStreetMap. Il donne l'adresse la plus proche " +
    "et annonce les virages à voix haute, dans vos lunettes quand elles sont la sortie audio du téléphone. " +
    "Votre position ne passe pas par votre ordinateur ; seule la présence des lunettes y est vérifiée."));

  // ---- lunettes : invitation à les connecter tant qu'elles manquent ; la fonction reste cachée d'ici là
  const zoneGarde = el('div');
  const zoneFonction = el('div');
  zoneFonction.hidden = true;
  corps.append(zoneGarde);
  let fermeGarde = false;
  const gardePrete = gardeLunettes(ctx, {
    fonction: 'guidage',
    libelle: 'le guidage à pied',
    zone: zoneGarde,
    contenu: zoneFonction,
    enCours: () => !!nav,
    avertissementEnCours: "Le trajet en cours continue jusqu'à l'arrivée ou jusqu'à ce que vous l'arrêtiez ; pour un nouveau trajet, reconnectez-les.",
    surAbsence: () => {
      if (nav) annoncer('Vos lunettes VELA ne sont plus détectées. Le trajet en cours continue ; pour un nouveau trajet, reconnectez-les.');
    },
  }).then((g) => { if (fermeGarde) g.fermer(); return g; });
  /** Présence des lunettes avant un geste ; l'invitation s'affiche d'elle-même si elles manquent. */
  async function lunettesOk() {
    const g = await gardePrete;
    return g.verifier({ depuisAction: true, cacheMs: 20000 });
  }

  // ---- accord (hors de la garde : retirer son accord reste possible sans les lunettes)
  const carteAccord = el('div', { class: 'carte' });
  corps.append(carteAccord, zoneFonction);
  const TEXTE_ACCORD = "Le guidage envoie la position de ce téléphone, et la destination que vous cherchez, aux services publics " +
    "d'OpenStreetMap sur Internet, pour trouver l'adresse et l'itinéraire. Votre position n'est pas envoyée à IRIS ni à votre ordinateur. " +
    "OpenStreetMap peut garder l'adresse Internet du téléphone dans ses journaux techniques, selon sa propre politique.";
  function accordDonne() { return String(memoireLocale(CLE_ACCORD) || '').indexOf('oui') === 0; }
  function dessinerAccord() {
    carteAccord.textContent = '';
    if (accordDonne()) {
      const retirer = el('button', { type: 'button', class: 'bouton-contour' }, 'Retirer mon accord');
      retirer.addEventListener('click', () => {
        oublierLocal(CLE_ACCORD);
        arreterGuidage(null);
        dessinerAccord();
        const t = "Accord retiré : le guidage est arrêté et plus aucune position n'est envoyée à OpenStreetMap depuis ce téléphone.";
        toast(t, 'ok');
        dire(t);
      });
      carteAccord.append(el('h3', {}, 'Votre accord'),
        el('p', { class: 'note-faible' }, 'Accordé sur ce téléphone. ' + TEXTE_ACCORD), retirer);
    } else {
      carteAccord.append(el('h3', {}, 'Avant la première utilisation'), el('p', { class: 'note' }, TEXTE_ACCORD),
        el('p', { class: 'note-faible' }, "L'accord vous sera demandé au premier geste, et vous pourrez le retirer ici."));
    }
  }
  async function assurerAccord() {
    if (accordDonne()) return true;
    const ok = await confirmer(TEXTE_ACCORD + '\n\nAcceptez-vous ?', { oui: "J'accepte", non: 'Refuser' });
    if (!ok) {
      toast("Sans votre accord, le guidage n'envoie rien et ne peut pas fonctionner.", 'info');
      return false;
    }
    retenirLocal(CLE_ACCORD, 'oui ' + new Date().toISOString());
    dessinerAccord();
    return true;
  }
  dessinerAccord();

  if (!geolocalisationPossible()) {
    zoneFonction.append(el('p', { class: 'resultat-erreur', role: 'alert' }, raisonSansGeolocalisation()));
  }

  // ---- où suis-je ?
  const boutonOu = el('button', { type: 'button', class: 'holo' }, 'Où suis-je ?');
  const resultatOu = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  zoneFonction.append(boutonOu, resultatOu);

  boutonOu.addEventListener('click', async () => {
    if (!(await lunettesOk())) return;
    if (!(await assurerAccord())) return;
    boutonOu.disabled = true;
    resultatOu.hidden = false;
    resultatOu.textContent = '';
    const statut = el('p', { class: 'note' }, 'Recherche de votre position…');
    resultatOu.append(statut);
    try {
      const p = await positionActuelle();
      statut.textContent = 'Position obtenue, à ' + distanceCourte(p.precision) + ' près. Recherche de l’adresse…';
      const d = await demanderNominatim('/reverse?format=jsonv2&lat=' + fixe(p.lat) + '&lon=' + fixe(p.lon) + '&accept-language=fr', controleur.signal);
      resultatOu.textContent = '';
      if (!d || d.error) {
        const t = "OpenStreetMap ne connaît pas d'adresse à cet endroit. Précision de la position : environ " + distanceParlee(p.precision) + '.';
        resultatOu.append(el('p', { class: 'resultat-texte' }, t));
        dire(t);
        return;
      }
      const adresse = adresseLisible(d);
      let phrase = 'Adresse la plus proche : ' + adresse + '. Précision de la position : environ ' + distanceParlee(p.precision) + '.';
      if (p.precision > 50) phrase += " Position peu précise : l'adresse peut être celle d'un bâtiment voisin.";
      resultatOu.append(el('p', { class: 'resultat-texte' }, phrase),
        el('p', { class: 'note-faible' }, "C'est l'adresse connue la plus proche du point GPS, pas forcément la porte devant vous. © contributeurs OpenStreetMap."));
      dire(phrase);
    } catch (err) {
      if (err && err.annule) return;
      resultatOu.textContent = '';
      resultatOu.append(el('p', { class: 'resultat-erreur' }, (err && err.message) || String(err)));
      dire(err && err.message);
    } finally {
      boutonOu.disabled = false;
    }
  });

  // ---- guide-moi
  const champ = el('input', { id: 'guidage-destination', class: 'champ', type: 'text', autocomplete: 'off', enterkeyhint: 'search', placeholder: 'Ex. : pharmacie rue Principale, Laval' });
  const dicter = el('button', { type: 'button', class: 'bouton-sombre' }, 'Dicter');
  const chercher = el('button', { type: 'button', class: 'holo' }, 'Chercher la destination');
  const resultats = el('div', { class: 'liste-boutons', 'aria-live': 'polite' });
  zoneFonction.append(el('div', { class: 'carte' },
    el('h3', {}, 'Guide-moi'),
    el('label', { for: 'guidage-destination', class: 'etiquette' }, 'Destination (adresse ou lieu, au Canada)'),
    el('div', { class: 'ligne' }, champ, dicter),
    el('p', { class: 'note-faible' }, 'La recherche part seulement quand vous touchez « Chercher » : rien n’est envoyé pendant que vous écrivez.')),
  chercher, resultats);

  dicter.addEventListener('click', async () => {
    const voix = IRISv().voix;
    if (!voix || typeof voix.ecouter !== 'function') { toast('La dictée n’est pas disponible sur cette page : écrivez la destination.', 'info'); champ.focus(); return; }
    dicter.disabled = true;
    dicter.textContent = 'Parlez…';
    try {
      champ.value = await voix.ecouter({ langue: 'fr-CA' });
      lancerRecherche();
    } catch (err) {
      if (!err || err.code !== 'interrompu') toast((err && err.message) || 'Dictée impossible.', 'erreur');
    } finally {
      dicter.disabled = false;
      dicter.textContent = 'Dicter';
    }
  });
  chercher.addEventListener('click', lancerRecherche);
  champ.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lancerRecherche(); } });

  let rechercheEnCours = false;
  async function lancerRecherche() {
    const q = champ.value.trim();
    if (!q) { toast('Dites ou écrivez une destination.', 'info'); champ.focus(); return; }
    if (rechercheEnCours) return;
    if (!(await lunettesOk())) return;
    if (!(await assurerAccord())) return;
    rechercheEnCours = true;
    chercher.disabled = true;
    resultats.textContent = '';
    resultats.append(el('p', { class: 'note' }, 'Recherche de « ' + q + ' »…'));
    // La position sert seulement à afficher la distance des résultats ; elle n'est pas envoyée pour la recherche.
    const position = positionActuelle().catch(() => null);
    try {
      const liste = await demanderNominatim('/search?format=jsonv2&q=' + encodeURIComponent(q) + '&limit=3&countrycodes=ca&accept-language=fr', controleur.signal);
      const p = await position;
      resultats.textContent = '';
      const lieux = (Array.isArray(liste) ? liste : []).map((r) => ({
        nom: nomCourt(r), detail: String(r.display_name || ''), lat: Number(r.lat), lon: Number(r.lon),
      })).filter((l) => Number.isFinite(l.lat) && Number.isFinite(l.lon));
      if (!lieux.length) {
        const t = 'Aucun lieu trouvé au Canada pour « ' + q + ' ». Ajoutez la ville ou le numéro civique.';
        resultats.append(el('p', { class: 'resultat-erreur' }, t));
        dire(t);
        return;
      }
      resultats.append(el('h3', { class: 'etiquette' }, lieux.length > 1 ? lieux.length + ' lieux trouvés : touchez le bon' : '1 lieu trouvé : touchez-le pour partir'));
      const annonce = [];
      lieux.forEach((l, i) => {
        const loin = p ? haversine(p, l) : null;
        const sous = l.detail + (loin !== null ? ' — à ' + distanceCourte(loin) + ' à vol d’oiseau' : '');
        const b = el('button', { type: 'button', class: 'choix' }, el('span', { class: 'choix-titre' }, l.nom), el('span', { class: 'choix-sous' }, sous));
        b.addEventListener('click', () => demarrerGuidage(l));
        resultats.append(b);
        annonce.push((i + 1) + ' : ' + l.nom + (loin !== null ? ', à ' + distanceParlee(loin) : ''));
      });
      resultats.append(el('p', { class: 'note-faible' }, '© contributeurs OpenStreetMap'));
      dire((lieux.length > 1 ? lieux.length + ' lieux trouvés. ' : 'Un lieu trouvé. ') + annonce.join('. ') + '.');
    } catch (err) {
      if (err && err.annule) return;
      resultats.textContent = '';
      resultats.append(el('p', { class: 'resultat-erreur' }, (err && err.message) || String(err)));
      dire(err && err.message);
    } finally {
      rechercheEnCours = false;
      chercher.disabled = false;
    }
  }

  // ---- navigation
  const sectionNav = el('div', { class: 'resultat', hidden: true });
  const titreNav = el('h3', {});
  const consigne = el('p', { class: 'resultat-texte' });
  consigne.style.fontSize = '1.75rem';
  consigne.style.fontWeight = '700';
  const detailNav = el('p', { class: 'note' });
  const annonceEcrite = el('p', { class: 'invisible', role: 'status', 'aria-live': 'assertive' });
  const noteEcran = el('p', { class: 'note-faible', hidden: true });
  const repeter = el('button', { type: 'button', class: 'bouton-sombre' }, 'Répéter');
  const arreter = el('button', { type: 'button', class: 'holo rouge' }, 'Arrêter le guidage');
  const listeEtapes = el('ol', { class: 'liste-limites' });
  const detailsEtapes = el('details', {}, el('summary', {}, 'Toutes les étapes'), listeEtapes);
  sectionNav.append(titreNav, consigne, detailNav, noteEcran, el('div', { class: 'ligne' }, repeter), arreter, detailsEtapes);
  zoneFonction.append(sectionNav, annonceEcrite);

  const annonces = el('input', { type: 'checkbox', role: 'switch', id: 'guidage-annonces', class: 'interrupteur' });
  annonces.checked = annoncesVocales;
  annonces.addEventListener('change', () => { annoncesVocales = annonces.checked; retenirLocal(CLE_ANNONCES, annoncesVocales ? 'oui' : 'non'); });
  zoneFonction.append(el('div', { class: 'carte' }, el('div', { class: 'rangee-reglage' },
    el('label', { for: 'guidage-annonces', class: 'rangee-libelle' },
      el('span', { class: 'rangee-titre' }, 'Annonces vocales'),
      el('span', { class: 'rangee-sous' }, 'Avec la voix de ce téléphone. Désactivées, les annonces passent par VoiceOver.')),
    annonces)));

  function annoncer(texte) {
    if (!texte) return;
    if (nav) nav.derniereAnnonce = texte;
    if (annoncesVocales) dire(texte);
    else {
      annonceEcrite.textContent = '';
      setTimeout(() => { annonceEcrite.textContent = texte; }, 60);
    }
  }

  function majAffichage(reste) {
    if (!nav) return;
    const prochaine = nav.etapes[nav.index + 1];
    const p = nav.derniere;
    if (prochaine && typeof reste === 'number' && Number.isFinite(reste)) {
      consigne.textContent = 'Dans ' + distanceCourte(reste) + ' : ' + initialeMinuscule(prochaine.instruction);
    } else if (prochaine) {
      consigne.textContent = 'Prochaine étape : ' + initialeMinuscule(prochaine.instruction);
    }
    const morceaux = ['Étape ' + Math.min(nav.index + 1, nav.etapes.length) + ' sur ' + nav.etapes.length];
    if (p) {
      morceaux.push('destination à ' + distanceCourte(haversine(p, nav.destination)) + ' à vol d’oiseau');
      morceaux.push('position à ' + distanceCourte(p.precision) + ' près');
    }
    if (nav.horsItineraire) morceaux.push('hors de l’itinéraire');
    detailNav.textContent = morceaux.join(' · ') + '.';
  }

  function dessinerEtapes() {
    listeEtapes.textContent = '';
    if (!nav) return;
    nav.etapes.forEach((e) => listeEtapes.append(el('li', {}, phraseEtape(e) + '.')));
  }

  function arreterGuidage(message) {
    generation += 1;
    if (nav && nav.surveillance !== null) {
      try { navigator.geolocation.clearWatch(nav.surveillance); } catch (e) { /* déjà arrêtée */ }
    }
    const etait = !!nav;
    nav = null;
    eveil(false);
    if (etait) {
      sectionNav.hidden = true;
      if (message) { toast(message, 'info'); dire(message); }
    }
  }
  arreter.addEventListener('click', () => arreterGuidage('Guidage arrêté.'));
  repeter.addEventListener('click', () => {
    if (!nav) return;
    const prochaine = nav.etapes[nav.index + 1];
    const p = nav.derniere;
    let t = prochaine ? consigne.textContent + '.' : (nav.derniereAnnonce || '');
    if (p) t += ' Position à environ ' + distanceParlee(p.precision) + ' près.';
    dire(t);
  });

  function arriver(etape) {
    const nom = nav ? nav.destination.nom : '';
    const phrase = 'Vous êtes arrivé près de ' + nom + (etape ? cote(etape.modificateur) : '') +
      ". Le point d'arrivée est approximatif, à quelques mètres près : cherchez l'entrée autour de vous.";
    titreNav.textContent = 'Arrivée';
    consigne.textContent = phrase;
    const sortie = nav;
    generation += 1;
    if (sortie && sortie.surveillance !== null) {
      try { navigator.geolocation.clearWatch(sortie.surveillance); } catch (e) { /* déjà arrêtée */ }
    }
    nav = null;
    eveil(false);
    detailNav.textContent = 'Guidage terminé.';
    annonceEcrite.textContent = '';
    if (annoncesVocales) dire(phrase); else setTimeout(() => { annonceEcrite.textContent = phrase; }, 60);
  }

  async function recalculer(p) {
    const courant = nav;
    if (!courant) return;
    courant.horsItineraire = true;
    if (courant.enRecalcul || Date.now() - courant.dernierRecalcul < RECALCUL_MIN_MS) {
      if (!courant.horsDit) { courant.horsDit = true; annoncer('Vous êtes hors de l’itinéraire.'); }
      return;
    }
    courant.enRecalcul = true;
    courant.dernierRecalcul = Date.now();
    courant.horsDit = true;
    const ma = generation;
    annoncer('Vous vous éloignez de l’itinéraire. Nouveau calcul.');
    try {
      const route = await calculerItineraire(p, courant.destination, controleur.signal);
      if (ma !== generation || nav !== courant) return;
      Object.assign(courant, { etapes: route.etapes, index: 0, ecarts: 0, resteMin: null, averti: false, horsItineraire: false, horsDit: false });
      courant.etapes[0].annoncee = true;
      dessinerEtapes();
      annoncer('Nouvel itinéraire : ' + distanceParlee(route.distance) + '. ' + phraseEtape(courant.etapes[0]) + '.');
      majAffichage();
    } catch (err) {
      if (err && err.annule) return;
      if (ma === generation && nav === courant) annoncer('Nouveau calcul impossible : ' + ((err && err.message) || 'erreur') + ' Nouvel essai dans 20 secondes.');
    } finally {
      courant.enRecalcul = false;
      courant.horsDit = false;
    }
  }

  function surPosition(p) {
    const n0 = nav;
    if (!n0) return;
    n0.derniere = p;
    if (p.precision > PRECISION_INUTILISABLE_M) {
      if (Date.now() - n0.avertiPrecision > 30000) {
        n0.avertiPrecision = Date.now();
        annoncer('Position imprécise, à ' + distanceParlee(p.precision) + ' près : annonces en pause jusqu’à un meilleur signal.');
      }
      majAffichage();
      return;
    }
    const etapes = n0.etapes;
    const derniere = etapes[etapes.length - 1];
    if ((derniere && derniere.type === 'arrive' && haversine(p, derniere.lieu) <= ARRIVEE_M) ||
        haversine(p, n0.destination) <= ARRIVEE_M + Math.min(p.precision, 15)) {
      arriver(derniere && derniere.type === 'arrive' ? derniere : null);
      return;
    }
    // La partie de l'itinéraire la plus proche, de l'étape précédente à trois étapes plus loin.
    let proche = null;
    for (let k = Math.max(0, n0.index - 1); k <= Math.min(etapes.length - 1, n0.index + 3); k++) {
      const pr = projeter(p, etapes[k].ligne);
      if (!proche || pr.distance < proche.distance) proche = { k, distance: pr.distance, restant: pr.restant };
    }
    if (!proche) return;
    if (proche.distance > ECART_MAX_M) {
      // Deux positions de suite hors du couloir : un seul point GPS aberrant ne relance rien.
      n0.ecarts += 1;
      if (n0.ecarts >= 2) recalculer(p);
      majAffichage();
      return;
    }
    n0.ecarts = 0;
    n0.horsItineraire = false;
    if (proche.k > n0.index && proche.distance <= 20) {
      // Une manœuvre a été passée sans annonce (GPS en retard, virage coupé) : on donne la suite, sans la rejouer.
      for (let j = 0; j <= proche.k; j++) { etapes[j].annoncee = true; etapes[j].preavis = true; }
      n0.index = proche.k;
      n0.resteMin = null;
      n0.averti = false;
      annoncer(phraseEtape(etapes[n0.index]) + '.');
    }
    const courante = etapes[n0.index];
    const prochaine = etapes[n0.index + 1];
    if (!prochaine) { majAffichage(); return; }
    const pr = proche.k === n0.index ? proche : projeter(p, courante.ligne);
    const direct = haversine(p, prochaine.lieu);
    const reste = Number.isFinite(pr.restant) && pr.distance <= ECART_MAX_M ? pr.restant : direct;

    // Sens de marche : la distance au prochain point grandit franchement -> demi-tour.
    if (n0.resteMin === null || reste < n0.resteMin) n0.resteMin = reste;
    else if (!n0.averti && p.precision <= 25 && reste > n0.resteMin + 25) {
      n0.averti = true;
      annoncer('Vous vous éloignez du prochain point de l’itinéraire : faites demi-tour.');
    }

    if (!prochaine.preavis && !prochaine.annoncee && meritePreavis(prochaine) && courante.distance > 60 &&
        reste <= DISTANCE_PREAVIS_M + 5 && reste > 18) {
      prochaine.preavis = true;
      annoncer('Dans ' + distanceParlee(Math.round(reste / 10) * 10) + ', ' + initialeMinuscule(prochaine.instruction) + '.');
    }
    if (!prochaine.annoncee && (reste <= DISTANCE_MANOEUVRE_M + 2 || direct <= DISTANCE_MANOEUVRE_M)) {
      prochaine.annoncee = true;
      prochaine.preavis = true;
      if (prochaine.type === 'arrive') { arriver(prochaine); return; }
      n0.index += 1;
      n0.resteMin = null;
      n0.averti = false;
      const suite = etapes[n0.index + 1];
      let phrase = prochaine.instruction;
      if (suite && suite.type !== 'arrive' && prochaine.distance < 25) {
        suite.preavis = true;
        phrase += ', puis tout de suite, ' + initialeMinuscule(suite.instruction);
      } else if (prochaine.distance >= 5) {
        phrase += ', puis continuez pendant ' + distanceParlee(prochaine.distance);
      }
      annoncer(phrase + '.');
      majAffichage(prochaine.distance);
      return;
    }
    majAffichage(reste);
  }

  async function demarrerGuidage(lieu) {
    if (!(await lunettesOk())) return;
    if (!(await assurerAccord())) return;
    arreterGuidage(null);
    const ma = generation;
    sectionNav.hidden = false;
    titreNav.textContent = 'Vers ' + lieu.nom;
    consigne.textContent = 'Recherche de votre position…';
    detailNav.textContent = '';
    listeEtapes.textContent = '';
    try {
      const p = await positionActuelle();
      if (ma !== generation) return;
      consigne.textContent = 'Calcul de l’itinéraire à pied…';
      const route = await calculerItineraire(p, lieu, controleur.signal);
      if (ma !== generation) return;
      nav = {
        destination: lieu, etapes: route.etapes, index: 0, surveillance: null, derniere: p, ecarts: 0,
        // dernierRecalcul à 0 : un écart dès les premiers pas se recalcule tout de suite ; ensuite, 20 s au moins.
        resteMin: null, averti: false, enRecalcul: false, dernierRecalcul: 0, horsDit: false,
        horsItineraire: false, avertiPrecision: 0, derniereAnnonce: '',
      };
      nav.etapes[0].annoncee = true;
      dessinerEtapes();
      annoncer('Itinéraire à pied vers ' + lieu.nom + ' : ' + distanceParlee(route.distance) + ', environ ' + dureeParlee(route.duree) +
        '. ' + phraseEtape(nav.etapes[0]) + '.');
      majAffichage();
      const courant = nav;
      courant.surveillance = navigator.geolocation.watchPosition(
        (pos) => { if (nav === courant) surPosition(versPoint(pos)); },
        (e) => {
          if (nav !== courant) return;
          if (e && e.code === 1) arreterGuidage(messageGeolocalisation(e));
          else detailNav.textContent = 'Pas de nouvelle position pour l’instant : ' + messageGeolocalisation(e);
        },
        { enableHighAccuracy: true, maximumAge: 1000, timeout: 30000 });
      const allume = await eveil(true);
      noteEcran.hidden = allume;
      noteEcran.textContent = allume ? '' : "Ce téléphone refuse de garder l'écran allumé depuis cette page : réglez le verrouillage automatique sur « Jamais » pendant le trajet, sinon le guidage s'interrompt.";
    } catch (err) {
      if (err && err.annule) return;
      if (ma !== generation) return;
      consigne.textContent = '';
      detailNav.textContent = (err && err.message) || String(err);
      titreNav.textContent = 'Guidage impossible';
      dire(err && err.message);
    }
  }

  // Page ramenée à l'écran : la position a pu manquer pendant la suspension ; on redit où l'on en est.
  const auRetour = () => {
    if (document.hidden || !nav) return;
    const prochaine = nav.etapes[nav.index + 1];
    annoncer('Guidage repris. ' + (prochaine ? 'Prochaine étape : ' + initialeMinuscule(prochaine.instruction) + '.' : ''));
  };
  document.addEventListener('visibilitychange', auRetour);

  // ---- limites et attribution
  const limites = el('details', { class: 'carte' }, el('summary', {}, 'Limites du guidage'));
  limites.append(el('ul', { class: 'liste-limites' },
    el('li', {}, "La position du téléphone est précise à quelques mètres au mieux, et à plusieurs dizaines de mètres entre de grands immeubles : une annonce peut arriver trop tôt ou trop tard."),
    el('li', {}, "L'écran doit rester allumé et cette page ouverte : sur iPhone, une page en arrière-plan ou un écran verrouillé ne reçoit plus la position, et le guidage s'interrompt."),
    el('li', {}, "Le guidage ne détecte ni les obstacles, ni les travaux, ni l'état des feux pour piétons. Il ne remplace ni la canne, ni le chien-guide, ni votre prudence pour traverser."),
    el('li', {}, "Les itinéraires viennent des données d'OpenStreetMap, rédigées par des bénévoles : un trottoir, un passage ou une entrée peut manquer ou être faux."),
    el('li', {}, 'Internet est requis sur ce téléphone. Durées estimées pour un pas moyen.'),
    el('li', {}, "Pour chercher une adresse ou commencer un trajet, vos lunettes VELA doivent être détectées : par votre ordinateur, ou connectées à ce téléphone (Android). Si l'ordinateur ne répond pas et que leur dernière confirmation date de plus de deux minutes et demie, un nouveau trajet ne peut pas commencer. Un trajet commencé n'est pas interrompu si elles disparaissent."),
    el('li', {}, 'Fermer ce panneau arrête le guidage.')));
  const attribution = el('p', { class: 'note-faible' }, 'Données cartographiques : ',
    el('a', { href: 'https://www.openstreetmap.org/copyright', target: '_blank', rel: 'noopener noreferrer' }, '© contributeurs OpenStreetMap'),
    ' (licence ODbL).');
  corps.append(limites, attribution);

  return brancherNettoyage(ctx, () => {
    fermeGarde = true;
    gardePrete.then((g) => g.fermer()).catch(() => null);
    document.removeEventListener('visibilitychange', auRetour);
    try { controleur.abort(); } catch (e) { /* rien en cours */ }
    const etait = nav;
    generation += 1;
    if (etait && etait.surveillance !== null) {
      try { navigator.geolocation.clearWatch(etait.surveillance); } catch (e) { /* déjà arrêtée */ }
    }
    nav = null;
    eveil(false);
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<path d="M12 21s-6.5-6.2-6.5-11.5a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.4"/></svg>';

const MODULE = {
  id: 'guidage',
  titre: 'Guidage à pied',
  sous_titre: 'Où suis-je, guide-moi',
  icone: ICONE,
  ordre: 40,
  ouvrir,
};

/** La coquille crée window.IRIS avant les modules ; si elle arrive après, on l'attend sans planter. */
function quandIRISPret(rappel) {
  const pret = () => window.IRIS && typeof window.IRIS.enregistrer === 'function';
  if (pret()) { rappel(window.IRIS); return; }
  let fait = false;
  let minuterie = null;
  const essayer = () => {
    if (fait || !pret()) return;
    fait = true;
    window.removeEventListener('iris:pret', essayer);
    clearInterval(minuterie);
    rappel(window.IRIS);
  };
  window.addEventListener('iris:pret', essayer);
  minuterie = setInterval(essayer, 250);
  setTimeout(() => clearInterval(minuterie), 60000);
}
quandIRISPret((IRIS) => IRIS.enregistrer(MODULE));
