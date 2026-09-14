/* IRIS — coquille de la page téléphone (servie par l'ordinateur à /m).
 *
 * Pourquoi une coquille : la page téléphone porte maintenant plusieurs fonctions (vision, sous-titres,
 * guidage, interprète…) écrites par des équipes différentes. Chacune s'enregistre auprès de
 * window.IRIS ; la coquille dessine sa tuile, ouvre son panneau et lui prête la voix, les événements
 * de l'ordinateur et les boîtes de dialogue. Un module absent ou en erreur ne retire que sa tuile.
 *
 * Contrat (interface K) :
 *   window.IRIS = { api, bus: {on(type, fn) -> off, emit}, voix: {parler, ecouter, arreter},
 *                   ui: {toast, ouvrirPanneau, confirmer}, enregistrer(module) }
 *   module = {id, titre, sous_titre, icone (SVG), ordre, ouvrir({corps, fermer})}
 * Compléments sans risque pour les modules qui les veulent : ouvrir reçoit aussi surFermeture(fn),
 * et peut renvoyer une fonction de nettoyage ; IRIS.ui.garderEcranAllume(raison, actif) ;
 * IRIS.image.reduire(fichier, coteMax) ; IRIS.etat() ; IRIS.reglages().
 *
 * Le téléphone de Miguel est un iPhone. Safari iOS d'abord : voix à amorcer depuis un vrai geste,
 * reconnaissance vocale capricieuse dont on ne dépend jamais, page suspendue dès qu'elle quitte
 * l'écran. Et une règle au-dessus des autres : la page dit ce qui marche vraiment, ici et maintenant.
 */
import { api, bus, memoire, retenir, oublier } from './api.js';

const VERSION_COQUILLE = '2026-09-13';

// ------------------------------------------------------------------ où sommes-nous ? (iPadOS se déguise en Mac, d'où le test tactile)
const UA = navigator.userAgent || '';
const IOS = /iPad|iPhone|iPod/.test(UA) || (UA.indexOf('Macintosh') !== -1 && 'ontouchend' in document);
const SAFARI_IOS = IOS && !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome/.test(UA);
const AUTONOME = window.navigator.standalone === true ||
  (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);

// ------------------------------------------------------------------ éléments et état
const $ = (id) => document.getElementById(id);
const racineApp = $('app');
const couchePanneaux = $('panneaux');
const zoneTuiles = $('tuiles');
const fil = $('fil');
const bouton = $('parler');
const libelleParler = $('parler-libelle');
const champ = $('texte');
const verrou = $('verrou');
const champMdp = $('mdp');
const erreur = $('erreur');
const brouillons = $('brouillons');

const modules = new Map();
let reglages = {};
let compte = { configure: false };
let phase = 'demarrage';          // « pret » une fois la session admise
let modeVerrou = null;            // attente | connexion | deverrouiller | adresse | injoignable | null
let conversation = memoire('iris_conv') || null;
let occupe = false;
let ecouteEnCours = false;
let voixPossible = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
let voixAmorcee = false;
let reconnaissance = null;        // { reco, finir } pendant une écoute
const pilePanneaux = [];
let compteurPanneaux = 0;
let dialogueOuvert = false;
let alerteOuverte = false;
let fileDialogues = Promise.resolve();
let bouclesLancees = false;
const connexion = { pc: null, ms: null, ws: false };

// ------------------------------------------------------------------ le contrat window.IRIS, AVANT tout le reste
// Les modules de fonctions sont chargés après ce fichier et s'enregistrent tout de suite : l'objet
// doit exister même si la suite de ce fichier rencontrait un problème.
const IRIS = window.IRIS || {};
window.IRIS = IRIS;
IRIS.api = api;
IRIS.bus = bus;
IRIS.voix = { parler, ecouter, arreter: arreterVoix };
IRIS.ui = { toast, ouvrirPanneau, confirmer, garderEcranAllume: eveil };
IRIS.image = { reduire: reduireImage };
IRIS.enregistrer = enregistrer;
IRIS.etat = () => ({ pc: connexion.pc, latence_ms: connexion.ms, evenements: api.evenementsOuverts(), verrouille: modeVerrou === 'deverrouiller', pret: phase === 'pret' });
IRIS.reglages = () => Object.assign({}, reglages);
IRIS.version = VERSION_COQUILLE;

// ------------------------------------------------------------------ petits outils
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

function svg(chemins) {
  return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + chemins + '</svg>';
}
const ICONES = {
  micro: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0"/><path d="M12 17v4M9 21h6"/>'),
  oeil: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>'),
  recherche: svg('<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>'),
  sousTitres: svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 11h4M13 11h4M7 15h7"/>'),
  reglages: svg('<path d="M4 7h10M18 7h2M4 12h3M11 12h9M4 17h12"/><circle cx="16" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="18" cy="17" r="2"/>'),
  retour: svg('<path d="m15 6-6 6 6 6"/>'),
  texto: svg('<path d="M4 5.5h16v10H9l-4 3.5v-3.5H4v-10Z"/>'),
  telephone: svg('<path d="M6.5 3.5h3l1.5 4-2 1.5a10 10 0 0 0 6 6l1.5-2 4 1.5v3a2 2 0 0 1-2 2A16 16 0 0 1 4.5 5.5a2 2 0 0 1 2-2Z"/>'),
  etoile: svg('<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8L3.5 9.7l5.9-.9L12 3.5Z"/>'),
};

function avecIcone(noeud, icone) {
  const span = el('span', { 'aria-hidden': 'true', class: 'icone' });
  span.innerHTML = icone;   // chaînes SVG écrites dans ce fichier ou par les modules : jamais du texte reçu
  noeud.prepend(span);
  return noeud;
}

/** « 3,4 s » : une durée mesurée, affichée en français. */
function secondes(ms) {
  const s = Math.max(0, Number(ms) || 0) / 1000;
  return s.toLocaleString('fr-CA', { maximumFractionDigits: s < 10 ? 1 : 0 }) + ' s';
}
function fois(taux) { return (Math.round((Number(taux) / 185) * 10) / 10).toLocaleString('fr-CA', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '×'; }
function heureDe(ts) {
  if (ts === null || ts === undefined || ts === '') return '';
  const n = Number(ts);
  const d = Number.isFinite(n) ? new Date(n < 1e12 ? n * 1000 : n) : new Date(ts);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' });
}
function dateLisible(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso || '') : d.toLocaleString('fr-CA', { dateStyle: 'medium', timeStyle: 'short' });
}
function lectureAuto() { return memoire('iris_lecture_auto') !== 'non'; }
function lire(texte) { if (lectureAuto() && texte) parler(texte); }

// ------------------------------------------------------------------ modules et tuiles
function enregistrer(module) {
  if (!module || typeof module !== 'object' || !module.id || typeof module.ouvrir !== 'function') return false;
  modules.set(String(module.id), module);
  planifierTuiles();
  return true;
}

let tuilesPlanifiees = false;
function planifierTuiles() {
  if (tuilesPlanifiees) return;
  tuilesPlanifiees = true;
  // Plusieurs modules arrivent coup sur coup : un seul dessin, après eux.
  Promise.resolve().then(() => { tuilesPlanifiees = false; dessinerTuiles(); });
}

function dessinerTuiles() {
  const actif = document.activeElement && document.activeElement.getAttribute ? document.activeElement.getAttribute('data-module') : null;
  const liste = Array.from(modules.values()).sort((a, b) =>
    ((Number(a.ordre) || 500) - (Number(b.ordre) || 500)) || String(a.titre || '').localeCompare(String(b.titre || ''), 'fr-CA'));
  zoneTuiles.textContent = '';
  for (const m of liste) {
    const tuile = el('button', { type: 'button', class: 'tuile', 'data-module': m.id });
    const icone = el('span', { class: 'tuile-icone', 'aria-hidden': 'true' });
    icone.innerHTML = typeof m.icone === 'string' && m.icone.trim().indexOf('<svg') === 0 ? m.icone : ICONES.etoile;
    tuile.append(icone, el('span', { class: 'tuile-titre' }, m.titre || m.id));
    if (m.sous_titre) tuile.append(el('span', { class: 'tuile-sous' }, m.sous_titre));
    tuile.addEventListener('click', () => ouvrirModule(m));
    zoneTuiles.append(tuile);
    if (actif && actif === String(m.id)) tuile.focus();
  }
}

function ouvrirModule(m) {
  amorcerSynthese();
  const panneau = ouvrirPanneau(m.titre || m.id);
  const montrerPanne = (err) => {
    panneau.corps.append(el('p', { class: 'resultat-erreur' },
      'Cette fonction a rencontré une erreur : ' + ((err && err.message) || String(err)) + ". Le reste d'IRIS continue de fonctionner."));
  };
  try {
    const retour = m.ouvrir({ corps: panneau.corps, fermer: panneau.fermer, surFermeture: panneau.surFermeture, api, bus, voix: IRIS.voix, ui: IRIS.ui });
    if (typeof retour === 'function') panneau.surFermeture(retour);
    else if (retour && typeof retour.then === 'function') {
      retour.then((nettoyage) => { if (typeof nettoyage === 'function') panneau.surFermeture(nettoyage); }).catch(montrerPanne);
    }
  } catch (err) {
    montrerPanne(err);
  }
}

// ------------------------------------------------------------------ panneaux, dialogue, messages
function majInert() {
  const verrouVisible = verrou.classList.contains('visible');
  const bloque = verrouVisible || pilePanneaux.length > 0 || dialogueOuvert || alerteOuverte;
  racineApp.toggleAttribute('inert', bloque);
  if (bloque) racineApp.setAttribute('aria-hidden', 'true'); else racineApp.removeAttribute('aria-hidden');
  pilePanneaux.forEach((p, i) => {
    const dessous = i < pilePanneaux.length - 1 || dialogueOuvert || alerteOuverte || verrouVisible;
    p.section.toggleAttribute('inert', dessous);
    if (dessous) p.section.setAttribute('aria-hidden', 'true'); else p.section.removeAttribute('aria-hidden');
  });
}

/** Panneau plein écran au-dessus de l'application. Rend {corps, fermer, surFermeture, element}. */
function ouvrirPanneau(titre) {
  const id = ++compteurPanneaux;
  const idTitre = 'panneau-titre-' + id;
  const retour = el('button', { type: 'button', class: 'btn-retour' }, 'Retour');
  avecIcone(retour, ICONES.retour);
  const entete = el('h2', { id: idTitre, tabindex: '-1' }, String(titre || ''));
  const corps = el('div', { class: 'panneau-corps' });
  const section = el('section', { class: 'panneau', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': idTitre },
    el('div', { class: 'panneau-entete' }, retour, entete), corps);
  const nettoyages = [];
  const precedent = document.activeElement;
  let ouvert = true;

  const entree = { id, section, fermer, fermerMaintenant };
  function fermerMaintenant() {
    if (!ouvert) return;
    ouvert = false;
    const i = pilePanneaux.indexOf(entree);
    if (i !== -1) pilePanneaux.splice(i, 1);
    for (const nettoyer of nettoyages.splice(0)) {
      try { nettoyer(); } catch (e) { /* un nettoyage raté ne doit pas bloquer la fermeture */ }
    }
    try { corps.dispatchEvent(new CustomEvent('iris:fermeture')); } catch (e) { /* vieux navigateur */ }
    section.remove();
    majInert();
    if (precedent && typeof precedent.focus === 'function' && document.contains(precedent)) {
      try { precedent.focus(); } catch (e) { /* l'élément a disparu */ }
    }
  }
  function fermer() {
    if (!ouvert) return;
    // Le panneau a posé une entrée d'historique (le bouton « retour » d'Android le ferme ainsi). On
    // ferme TOUT DE SUITE, puis on retire l'entrée en ignorant le popstate qu'elle provoque : un
    // module qui ferme puis rouvre aussitôt ne doit pas voir son nouveau panneau emporté.
    const avaitEntree = !!(history.state && history.state.irisPanneau === id);
    fermerMaintenant();
    if (avaitEntree) {
      popstateAIgnorer += 1;
      try { history.back(); } catch (e) { popstateAIgnorer -= 1; }
    }
  }
  retour.addEventListener('click', fermer);
  couchePanneaux.append(section);
  pilePanneaux.push(entree);
  try { history.pushState({ irisPanneau: id }, ''); } catch (e) { /* historique indisponible : Retour suffit */ }
  majInert();
  setTimeout(() => { try { entete.focus(); } catch (e) { /* rien */ } }, 30);
  return {
    corps,
    fermer,
    surFermeture: (fonction) => { if (typeof fonction === 'function') nettoyages.push(fonction); },
    element: section,
  };
}

let popstateAIgnorer = 0;
window.addEventListener('popstate', (e) => {
  if (popstateAIgnorer > 0) { popstateAIgnorer -= 1; return; }
  const cible = (e.state && e.state.irisPanneau) || 0;
  for (const p of pilePanneaux.slice().reverse()) {
    if (p.id > cible) p.fermerMaintenant();
  }
});

function toast(texte, genre) {
  const message = String(texte || '').trim();
  if (!message) return;
  const g = ['ok', 'erreur', 'alerte', 'info'].indexOf(genre) !== -1 ? genre : 'info';
  const urgent = g === 'erreur' || g === 'alerte';
  const t = el('div', { class: 'toast toast-' + g, 'aria-hidden': urgent ? 'true' : null }, message);
  t.addEventListener('click', () => t.remove());
  const zone = $('toasts');
  zone.append(t);
  while (zone.children.length > 3) zone.firstElementChild.remove();
  if (urgent) {
    // Une erreur est annoncée une seule fois, tout de suite, par la zone « assertive ».
    const annonce = $('annonce-urgente');
    annonce.textContent = '';
    setTimeout(() => { annonce.textContent = message; }, 60);
  }
  setTimeout(() => t.remove(), Math.min(12000, 4500 + message.length * 45));
}

/** Oui ou non, dans une vraie boîte accessible. Les demandes simultanées attendent leur tour. */
function confirmer(texte, options) {
  const tour = fileDialogues.then(() => afficherDialogue(texte, options || {}));
  fileDialogues = tour.catch(() => false);
  return tour;
}

function afficherDialogue(texte, o) {
  return new Promise((resoudre) => {
    const boite = $('dialogue');
    const oui = $('dialogue-oui');
    const non = $('dialogue-non');
    $('dialogue-texte').textContent = String(texte || '');
    oui.textContent = o.oui || 'Oui';
    non.textContent = o.non || 'Non';
    const precedent = document.activeElement;
    boite.hidden = false;
    dialogueOuvert = true;
    majInert();
    function finir(valeur) {
      document.removeEventListener('keydown', clavier, true);
      oui.onclick = null;
      non.onclick = null;
      boite.hidden = true;
      dialogueOuvert = false;
      majInert();
      if (precedent && typeof precedent.focus === 'function' && document.contains(precedent)) {
        try { precedent.focus(); } catch (e) { /* rien */ }
      }
      resoudre(valeur);
    }
    function clavier(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finir(false); } }
    oui.onclick = () => finir(true);
    non.onclick = () => finir(false);
    document.addEventListener('keydown', clavier, true);
    // Le focus va sur « Non » : une validation distraite ne doit rien autoriser.
    setTimeout(() => { try { non.focus(); } catch (e) { /* rien */ } }, 30);
  });
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || dialogueOuvert) return;
  if (alerteOuverte) { fermerAlerte(); return; }
  const haut = pilePanneaux[pilePanneaux.length - 1];
  if (haut) { e.preventDefault(); haut.fermer(); }
});

/** Événement venu de l'ordinateur pendant qu'on regarde ailleurs : dans le fil, et en message si un panneau le cache. */
function signaler(texte, genre) {
  bulle('info', texte);
  if (pilePanneaux.length) toast(texte, genre || 'info');
}

// ------------------------------------------------------------------ alerte sonore plein écran
let alertesRecues = 0;
function afficherAlerte(ev) {
  const libelle = String(ev.libelle || ev.genre || 'Son détecté');
  alertesRecues = alerteOuverte ? alertesRecues + 1 : 1;
  $('alerte-titre').textContent = (ev.test ? 'Essai : ' : '') + libelle;
  let detail = 'Détecté par IRIS sur votre ordinateur';
  const heure = heureDe(ev.ts);
  if (heure) detail += ' à ' + heure;
  if (typeof ev.confiance === 'number') detail += ', confiance estimée ' + Math.round(ev.confiance * 100) + ' %';
  detail += '.';
  if (alertesRecues > 1) detail += ' ' + alertesRecues + ' alertes reçues.';
  $('alerte-detail').textContent = detail;
  $('alerte-note').textContent = "Son capté par le micro de l'ordinateur, ou des lunettes qui lui sont reliées. " +
    "Ne remplace pas un avertisseur homologué.";
  $('alerte').hidden = false;
  alerteOuverte = true;
  majInert();
  // Pas de vibration sur iPhone : Safari ne la permet pas aux pages web. Ailleurs, on vibre.
  if (typeof navigator.vibrate === 'function') { try { navigator.vibrate([500, 200, 500, 200, 900]); } catch (e) { /* refusé */ } }
  lire((ev.test ? 'Essai. ' : 'Alerte. ') + libelle);
  setTimeout(() => { try { $('alerte-ok').focus(); } catch (e) { /* rien */ } }, 30);
}
function fermerAlerte() {
  $('alerte').hidden = true;
  alerteOuverte = false;
  alertesRecues = 0;
  if (typeof navigator.vibrate === 'function') { try { navigator.vibrate(0); } catch (e) { /* rien */ } }
  majInert();
}
$('alerte-ok').addEventListener('click', fermerAlerte);

// ------------------------------------------------------------------ écran allumé
// iOS suspend une page dès que l'écran s'éteint : plus d'alerte, plus de sous-titres. Le verrou
// d'écran est demandé par raison (sous-titres, réglage…) et rendu quand plus personne n'en veut.
const raisonsEveil = new Set();
let verrouEcran = null;
async function eveil(raison, actif) {
  if (actif) raisonsEveil.add(String(raison)); else raisonsEveil.delete(String(raison));
  if (raisonsEveil.size === 0) {
    if (verrouEcran) {
      const v = verrouEcran;
      verrouEcran = null;
      try { await v.release(); } catch (e) { /* déjà libéré */ }
    }
    return false;
  }
  if (verrouEcran) return true;
  if (!('wakeLock' in navigator) || document.hidden) return false;
  try {
    verrouEcran = await navigator.wakeLock.request('screen');
    verrouEcran.addEventListener('release', () => { verrouEcran = null; });
    return true;
  } catch (e) {
    verrouEcran = null;
    return false;
  }
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && raisonsEveil.size && !verrouEcran) eveil(Array.from(raisonsEveil)[0], true);
});

// ------------------------------------------------------------------ voix : synthèse
// Sur iOS elle reste muette tant qu'une première parole n'a pas été lancée depuis un vrai geste. On
// glisse donc une énonciation vide au premier appui, sinon la réponse d'IRIS ne serait jamais
// entendue dans les lunettes (sortie audio du téléphone).
function listeVoix() {
  try { return speechSynthesis.getVoices() || []; } catch (e) { return []; }
}
function choisirVoix(langue) {
  const voulue = String(langue || 'fr-CA').replace('_', '-').toLowerCase();
  const base = voulue.split('-')[0];
  const dispo = listeVoix();
  const langueDe = (v) => (v.lang || '').replace('_', '-').toLowerCase();
  if (base === 'fr') {
    return dispo.filter((v) => langueDe(v) === 'fr-ca')[0]
        || dispo.filter((v) => langueDe(v) === 'fr-fr')[0]
        || dispo.filter((v) => langueDe(v).indexOf('fr') === 0)[0] || null;
  }
  return dispo.filter((v) => langueDe(v) === voulue)[0]
      || dispo.filter((v) => langueDe(v).indexOf(base) === 0)[0] || null;
}
if ('speechSynthesis' in window) {
  listeVoix();   // sur iOS la liste arrive en retard : on la réclame tôt, et on la relit quand elle change
  try { speechSynthesis.addEventListener('voiceschanged', listeVoix); } catch (e) { /* vieux Safari */ }
}

function amorcerSynthese() {
  if (voixAmorcee || !('speechSynthesis' in window)) return;
  voixAmorcee = true;
  try {
    const vide = new SpeechSynthesisUtterance(' ');
    vide.volume = 0; vide.lang = 'fr-CA';
    speechSynthesis.speak(vide);
    listeVoix();
  } catch (e) { voixAmorcee = false; }
}
// Tout vrai geste compte, y compris dans les panneaux des modules.
document.addEventListener('click', () => amorcerSynthese(), true);

/** Débit du téléphone : tts_rate/185 (1× = 185), plafonné à 3 et jamais sous 0,5. */
function debitParDefaut() {
  const taux = Number(reglages.tts_rate) || 185;
  return Math.max(0.5, Math.min(3, taux / 185));
}

/** parler(texte, {langue, debit}) -> Promise<boolean> : true si la phrase a été dite jusqu'au bout. */
function parler(texte, options) {
  const o = options || {};
  return new Promise((resoudre) => {
    const phrase = String(texte || '').trim();
    if (!phrase || !('speechSynthesis' in window)) { resoudre(false); return; }
    let fini = false;
    let garde = null;
    const finir = (ok) => { if (fini) return; fini = true; if (garde) clearTimeout(garde); resoudre(ok); };
    try {
      const langue = o.langue || 'fr-CA';
      const enonce = new SpeechSynthesisUtterance(phrase);
      const voix = choisirVoix(langue);
      if (voix) enonce.voice = voix;
      enonce.lang = (voix && voix.lang) || langue;
      const debit = Math.max(0.5, Math.min(3, Number(o.debit) || debitParDefaut()));
      enonce.rate = debit;
      enonce.onend = () => finir(true);
      enonce.onerror = () => finir(false);
      // iOS perd parfois « onend » : un garde-fou proportionnel à la longueur rend la main.
      garde = setTimeout(() => finir(true), 6000 + (phrase.length * 90) / debit);
      const lancer = () => { try { speechSynthesis.speak(enonce); } catch (e) { finir(false); } };
      // Parler juste après cancel() fait perdre la phrase à Safari : on lui laisse un instant.
      if (speechSynthesis.speaking || speechSynthesis.pending) { speechSynthesis.cancel(); setTimeout(lancer, 80); }
      else lancer();
    } catch (e) { finir(false); }
  });
}

function arreterVoix() {
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch (e) { /* rien à couper */ } }
  arreterEcoute();
}

// ------------------------------------------------------------------ voix : reconnaissance
// Celle du navigateur : gratuite, sans clé, mais elle n'appartient pas à VELA. Selon le téléphone,
// la phrase peut être envoyée aux serveurs du fabricant pour être reconnue ; les réglages le disent.
// Sur Safari iOS elle est capricieuse : permission sur un vrai geste, session coupée seule, « onend »
// sans résultat. Règle : la promesse se termine dans tous les cas (résultat, erreur ou garde-fou de 12 s).
function erreurVoix(code, message) {
  const e = new Error(message);
  e.code = code;
  return e;
}

/** ecouter({langue, delai}) -> Promise<string>. Erreurs : code indisponible | refuse | rien | interrompu | reseau | erreur. */
function ecouter(options) {
  const o = options || {};
  return new Promise((resoudre, rejeter) => {
    const Reco = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Reco) {
      rejeter(erreurVoix('indisponible', "La reconnaissance vocale n'existe pas dans ce navigateur. Écrivez plutôt."));
      return;
    }
    arreterEcoute();
    let reco;
    try { reco = new Reco(); } catch (e) {
      rejeter(erreurVoix('indisponible', "La reconnaissance vocale ne démarre pas sur ce téléphone. Écrivez plutôt."));
      return;
    }
    reco.lang = o.langue || 'fr-CA';
    reco.interimResults = false; reco.maxAlternatives = 1; reco.continuous = false;
    let entendu = false;
    let fini = false;
    const garde = setTimeout(() => {
      try { reco.stop(); } catch (e) { /* déjà arrêtée */ }
      finir(null, erreurVoix('rien', "Je n'ai rien entendu. Réessayez, ou écrivez."));
    }, Number(o.delai) > 0 ? Number(o.delai) : 12000);
    function finir(texte, probleme) {
      if (fini) return;
      fini = true;
      clearTimeout(garde);
      if (reconnaissance && reconnaissance.reco === reco) reconnaissance = null;
      if (probleme) rejeter(probleme); else resoudre(texte);
    }
    reco.onresult = (e) => {
      entendu = true;
      const premier = (e.results && e.results[0] && e.results[0][0]) || null;
      const dit = ((premier && premier.transcript) || '').trim();
      if (dit) finir(dit);
      else finir(null, erreurVoix('rien', "Je n'ai rien saisi. Réessayez, ou écrivez."));
    };
    reco.onerror = (e) => {
      const code = (e && e.error) || '';
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        finir(null, erreurVoix('refuse', "Micro ou reconnaissance vocale refusés pour cette page. Autorisez-les dans les réglages du téléphone (Safari › Micro). En attendant, écrivez."));
      } else if (code === 'no-speech') {
        finir(null, erreurVoix('rien', "Je n'ai rien entendu. Réessayez."));
      } else if (code === 'aborted') {
        finir(null, erreurVoix('interrompu', 'Écoute arrêtée.'));
      } else if (code === 'network') {
        finir(null, erreurVoix('reseau', "La reconnaissance vocale du téléphone a besoin du réseau et ne l'a pas. Écrivez plutôt."));
      } else if (code === 'language-not-supported') {
        finir(null, erreurVoix('langue', "Ce téléphone ne reconnaît pas cette langue."));
      } else {
        finir(null, erreurVoix('erreur', 'La reconnaissance vocale ne répond pas. Écrivez plutôt.'));
      }
    };
    // Safari coupe la session tout seul, parfois sans résultat ni erreur : on reprend la main.
    reco.onend = () => { if (!entendu) finir(null, erreurVoix('rien', "Je n'ai rien entendu. Réessayez.")); };
    reconnaissance = { reco, finir };
    try {
      reco.start();
    } catch (e) {
      finir(null, erreurVoix('erreur', 'Le micro ne répond pas. Écrivez plutôt.'));
    }
  });
}

function arreterEcoute() {
  const r = reconnaissance;
  if (!r) return;
  reconnaissance = null;
  try { r.reco.abort(); } catch (e) { try { r.reco.stop(); } catch (e2) { /* déjà arrêtée */ } }
  r.finir(null, erreurVoix('interrompu', 'Écoute arrêtée.'));
}

// ------------------------------------------------------------------ bouton « parler » et saisie
const REPOS = 'Appuyez pour parler';
const ECRIRE = 'Voix indisponible — écrivez';
const ECOUTE = 'Parlez… (touchez pour arrêter)';
const TRAVAIL = 'IRIS travaille…';

function etiquette() { return voixPossible ? REPOS : ECRIRE; }
function majBouton() {
  bouton.classList.toggle('ecoute', ecouteEnCours);
  bouton.classList.toggle('occupe', occupe);
  libelleParler.textContent = occupe ? TRAVAIL : ecouteEnCours ? ECOUTE : etiquette();
}
function repos(message) {
  ecouteEnCours = false;
  bouton.classList.remove('ecoute');
  majBouton();
  if (message) bulle('info', message);
}
function basculerEnEcrit(raison) {
  voixPossible = false;                 // honnête : la voix ne marche pas, on le dit et on écrit
  repos(raison);
  try { champ.focus(); } catch (e) { /* le champ reste utilisable à la main */ }
}

avecIcone(bouton, ICONES.micro);
majBouton();

bouton.addEventListener('click', () => {
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch (e) { /* rien à couper */ } }
  amorcerSynthese();          // doit rester DANS le geste, sinon iOS ne parlera jamais
  if (occupe) return;
  if (!voixPossible) { champ.focus(); return; }
  if (ecouteEnCours) { arreterEcoute(); repos(); return; }
  ecouteEnCours = true;
  majBouton();
  ecouter({ langue: 'fr-CA' })
    .then((dit) => { repos(); envoyer(dit); })
    .catch((err) => {
      const code = err && err.code;
      if (code === 'refuse' || code === 'indisponible') basculerEnEcrit(err.message);
      else if (code === 'interrompu') repos();
      else repos((err && err.message) || "Je n'ai rien entendu. Réessayez.");
    });
});

$('envoyer').addEventListener('click', () => { amorcerSynthese(); envoyer(champ.value); champ.value = ''; });
champ.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); amorcerSynthese(); envoyer(champ.value); champ.value = ''; }
});

// ------------------------------------------------------------------ conversation
function defilerEnBas() { const p = $('principal'); if (p) p.scrollTop = p.scrollHeight; }
function bulle(classe, texte) {
  const accueil = $('accueil');
  if (accueil) accueil.remove();
  const d = el('div', { class: 'bulle ' + classe }, texte);
  fil.append(d);
  while (fil.children.length > 60) fil.firstElementChild.remove();
  defilerEnBas();
  return d;
}
function ajouterMeta(bulleEl, texte) {
  bulleEl.append(el('span', { class: 'bulle-meta' }, texte));
}

async function assurerConversation(titre) {
  if (conversation) {
    try {
      const d = await api.get('/api/conversations/' + encodeURIComponent(conversation), { delai: 20000 });
      // L'ordinateur ne renvoie que les 500 premiers messages d'une conversation : au-delà, une
      // réponse neuve deviendrait invisible au sondage. On en ouvre une neuve bien avant.
      if ((d.messages || []).length < 400) return { id: conversation, messages: d.messages || [] };
    } catch (err) {
      if (err.status !== 404) throw err;
    }
  }
  const c = await api.post('/api/conversations', { title: titre.slice(0, 40), agent: 'auto' }, { delai: 20000 });
  conversation = c.id;
  retenir('iris_conv', conversation);
  return { id: c.id, messages: [] };
}

/** Attend la réponse d'IRIS : par les événements en direct, et par sondage (la liaison peut être coupée). */
function attendreReponse(convId, connus, bulleEnCours, debut) {
  let fini = false;
  let resoudre = null;
  let sondage = null;
  let garde = null;
  let premier = null;
  let flux = '';
  const promesse = new Promise((r) => { resoudre = r; });
  const desabonnements = [];
  function terminer(resultat) {
    if (fini) return;
    fini = true;
    desabonnements.forEach((f) => f());
    clearTimeout(sondage);
    clearTimeout(garde);
    resoudre(Object.assign({ premier }, resultat));
  }
  desabonnements.push(bus.on('chat.delta', (ev) => {
    if (ev.conversation_id !== convId || fini) return;
    if (premier === null) premier = performance.now() - debut;
    flux += ev.text || '';
    bulleEnCours.classList.remove('attente');
    bulleEnCours.textContent = flux;
    defilerEnBas();
  }));
  desabonnements.push(bus.on('chat.done', (ev) => {
    const m = ev.message || {};
    if (ev.conversation_id === convId && m.role === 'assistant' && !connus.has(m.id)) {
      terminer({ texte: m.text || (m.meta && m.meta.error) || '' });
    }
  }));
  desabonnements.push(bus.on('chat.error', (ev) => {
    if (ev.conversation_id === convId) terminer({ erreur: ev.message || "IRIS n'a pas pu répondre." });
  }));
  desabonnements.push(bus.on('chat.confirm', (ev) => { if (ev.conversation_id === convId) demanderAccord(ev); }));
  async function sonder() {
    if (fini) return;
    try {
      const d = await api.get('/api/conversations/' + encodeURIComponent(convId), { delai: 20000 });
      const nouveau = (d.messages || []).filter((m) => m.role === 'assistant' && !connus.has(m.id)).pop();
      if (nouveau && (nouveau.text || (nouveau.meta || {}).error)) {
        terminer({ texte: nouveau.text || nouveau.meta.error });
        return;
      }
    } catch (e) { /* le prochain tour réessaiera */ }
    if (!fini) sondage = setTimeout(sonder, api.evenementsOuverts() ? 6000 : 1500);
  }
  sondage = setTimeout(sonder, 1500);
  garde = setTimeout(() => terminer({ expire: true }), 180000);
  return { promesse, annuler: () => terminer({ annule: true }) };
}

async function demanderAccord(ev) {
  const titre = ev.title || 'IRIS demande votre accord.';
  const detail = typeof ev.detail === 'string' ? ev.detail : (ev.detail ? JSON.stringify(ev.detail) : '');
  lire('IRIS demande votre accord : ' + titre);
  const accord = await confirmer(titre + (detail ? '\n\n' + detail : ''), { oui: 'Autoriser', non: 'Refuser' });
  try {
    await api.post('/api/chat/confirm', { confirm_id: ev.confirm_id, approved: accord });
    if (!accord) toast('Action refusée : IRIS ne la fera pas.', 'info');
  } catch (err) {
    toast(err.message, 'erreur');
  }
}

async function envoyer(texte) {
  texte = (texte || '').trim();
  if (!texte || occupe) return;
  amorcerSynthese();
  occupe = true;
  majBouton();
  bulle('moi', texte);
  const reponse = bulle('elle attente', 'IRIS réfléchit…');
  reponse.setAttribute('aria-busy', 'true');
  const debut = performance.now();
  let attente = null;
  try {
    const conv = await assurerConversation(texte);
    const connus = new Set((conv.messages || []).map((m) => m.id));
    attente = attendreReponse(conv.id, connus, reponse, debut);   // à l'écoute AVANT l'envoi
    await api.post('/api/conversations/' + encodeURIComponent(conv.id) + '/messages',
      { text: texte, agent: 'auto', images: [] }, { delai: 20000 });
    const r = await attente.promesse;
    reponse.classList.remove('attente');
    reponse.removeAttribute('aria-busy');
    if (r.expire) {
      reponse.className = 'bulle info';
      reponse.textContent = "IRIS n'a pas répondu en 3 minutes. L'ordinateur a peut-être perdu sa connexion : réessayez.";
      return;
    }
    if (r.erreur) { reponse.textContent = r.erreur; lire(r.erreur); return; }
    reponse.textContent = r.texte || '(réponse vide)';
    ajouterMeta(reponse, 'Réponse en ' + secondes(performance.now() - debut) +
      (r.premier !== null ? ' (premiers mots après ' + secondes(r.premier) + ')' : '') + ', mesuré sur ce téléphone.');
    defilerEnBas();
    lire(r.texte);
  } catch (err) {
    if (attente) attente.annuler();
    reponse.removeAttribute('aria-busy');
    reponse.className = 'bulle info';
    reponse.textContent = err.status === 0 ? "Message non envoyé : l'ordinateur ne répond pas." : err.message;
  } finally {
    occupe = false;
    majBouton();
    // IRIS vient peut-être de déposer un texto : on l'affiche tout de suite, sans attendre le
    // sondage. Sans annonce : sa réponse vient d'être lue, elle dit déjà où le trouver.
    sonderBrouillons(false);
  }
}

// ------------------------------------------------------------------ brouillons de SMS et d'appel (telephonie.py, voie « iphone »)
// IRIS ne peut pas envoyer un texto depuis un programme : Apple ne le permet à personne. Elle le
// prépare, et c'est ce téléphone qui l'ouvre dans Messages, déjà rempli, pour un geste du pouce.
// Sondage plutôt qu'événements : une page mise en veille par iOS perd sa liaison, un sondage
// reprend là où il en était.
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
  const nouveaux = liste.filter((b) => brouillonsVus.split(',').indexOf(String(b.id)) === -1);
  brouillonsVus = cle;
  brouillons.textContent = '';
  brouillons.hidden = liste.length === 0;
  liste.forEach((b) => {
    const sms = b.genre === 'sms';
    const titre = el('p', { class: 'brouillon-titre' }, (sms ? 'Texto pour ' : 'Appel vers ') + (b.numero_lisible || b.numero));
    avecIcone(titre, sms ? ICONES.texto : ICONES.telephone);
    const carte = el('div', { class: 'brouillon' }, titre);
    if (sms) carte.append(el('p', { class: 'brouillon-texte' }, b.texte || ''));
    carte.append(el('p', { class: 'brouillon-note' }, sms
      ? "Messages s'ouvre déjà rempli : c'est vous qui touchez Envoyer. Rien ne part sans ce geste."
      : "Le composeur s'ouvre avec ce numéro : c'est vous qui lancez l'appel."));
    const lien = lienSur(b);
    if (lien) carte.append(el('a', { class: 'brouillon-ouvrir', href: lien }, sms ? 'Ouvrir dans Messages' : 'Appeler'));
    const fait = el('button', { type: 'button', class: 'bouton-sombre' }, sms ? "C'est envoyé" : "C'est appelé");
    fait.addEventListener('click', () => fermerBrouillon(b.id, 'envoye'));
    const annuler = el('button', { type: 'button', class: 'bouton-contour' }, 'Annuler');
    annuler.addEventListener('click', () => fermerBrouillon(b.id, 'annule'));
    carte.append(el('div', { class: 'ligne' }, fait, annuler));
    brouillons.append(carte);
  });
  ajusterHauteur();
  // Un brouillon dicté à la maison, devant l'ordinateur, arrive ici sans qu'on l'ait demandé
  // depuis cette page : on le dit, sinon il attendrait en silence ses quinze minutes.
  if (annoncer && nouveaux.length && !occupe) {
    const b = nouveaux[nouveaux.length - 1];
    const phrase = (b.genre === 'sms' ? 'Un texto pour ' : 'Un appel vers ') + (b.numero_lisible || b.numero) + ' est prêt, en haut de l’écran.';
    signaler(phrase);
    lire(phrase);
  }
}

async function sonderBrouillons(annoncer) {
  if (phase !== 'pret' || !api.jeton() || verrou.classList.contains('visible')) return;
  try {
    const d = await api.get('/api/telephonie/en_attente', { delai: 15000 });
    dessinerBrouillons((d && d.brouillons) || [], annoncer !== false);
  } catch (e) { /* 401 : l'écran de connexion s'en charge ; 404 : ordinateur pas à jour ; sinon le prochain sondage réessaiera */ }
}

async function fermerBrouillon(id, etat) {
  try {
    const d = await api.post('/api/telephonie/' + encodeURIComponent(id) + '/' + etat);
    if (d && d.message) bulle('info', d.message);
  } catch (err) {
    bulle('info', err.message);
  }
  brouillonsVus = '';       // forcer le redessin : la liste vient de changer côté ordinateur
  sonderBrouillons(false);
}

// Au retour de Messages ou de Téléphone, la page se réveille : elle vérifie tout de suite ce qui
// reste à faire partir, et l'état de la liaison, plutôt que d'attendre le prochain tour.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { sonderBrouillons(false); verifier(); }
});

// ------------------------------------------------------------------ connexion, verrouillage, état
function marquer(genre, texte) {
  $('point').className = 'point ' + (genre || '');
  $('etat').textContent = texte;
}

function messageHorsLigne(expire) {
  return (expire ? "L'ordinateur répond trop lentement. " : "L'ordinateur ne répond pas. ") +
    "IRIS vit sur votre ordinateur : il est peut-être éteint ou en veille, sans Internet, IRIS n'y est pas ouverte, " +
    "ou l'application de réseau privé est désactivée sur ce téléphone. Tant qu'il ne répond pas, rien de ce que vous demandez ici ne peut aboutir.";
}

function marquerConnecte() {
  connexion.pc = true;
  $('hors-ligne').hidden = true;
  marquer('ok', 'Connectée au PC' + (connexion.ms !== null ? ' · ' + connexion.ms + ' ms' : ''));
  // Déverrouillée ailleurs (sur l'ordinateur) : l'ordinateur répond de nouveau, l'écran s'efface.
  if (modeVerrou === 'deverrouiller') afficherVerrou(null);
  majLiaison();
  ajusterHauteur();
}

function marquerHorsLigne(sansReseau, expire) {
  connexion.pc = false;
  marquer('err', 'Hors ligne');
  $('hors-ligne-texte').textContent = sansReseau
    ? "Ce téléphone n'a pas de réseau. IRIS vit sur votre ordinateur : sans réseau, cette page ne peut rien lui demander."
    : messageHorsLigne(expire);
  $('hors-ligne').hidden = false;
  majLiaison();
  ajusterHauteur();
}

let minuterieLiaison = null;
function majLiaison() {
  const bandeau = $('liaison');
  clearTimeout(minuterieLiaison);
  if (connexion.pc !== true || api.evenementsOuverts() || phase !== 'pret') {
    if (!bandeau.hidden) { bandeau.hidden = true; ajusterHauteur(); }
    return;
  }
  // Quelques secondes de grâce : une reconnexion ordinaire ne mérite pas un bandeau.
  minuterieLiaison = setTimeout(() => {
    if (connexion.pc === true && !api.evenementsOuverts()) {
      bandeau.textContent = "Liaison en direct coupée : les alertes sonores, les sous-titres et les messages n'arrivent pas ici pour l'instant. " +
        'Les demandes marchent encore ; nouvel essai automatique.';
      bandeau.hidden = false;
      ajusterHauteur();
    }
  }, 8000);
}

async function verifier() {
  if (phase !== 'pret' || !api.jeton()) return;
  if (navigator.onLine === false) { marquerHorsLigne(true); return; }
  const debut = performance.now();
  try {
    await api.get('/api/status', { delai: 15000 });
    connexion.ms = Math.round(performance.now() - debut);
    marquerConnecte();
  } catch (err) {
    if (err.status === 0) marquerHorsLigne(false, err.expire);
    else if (err.status !== 401) marquer('attente', 'erreur ' + err.status);
    // 401 : les événements iris.verrouillee / iris.session_refusee affichent le bon écran.
  }
}

function afficherVerrou(mode, titre, texte) {
  modeVerrou = mode || null;
  const visible = !!mode;
  verrou.classList.toggle('visible', visible);
  if (titre) $('verrou-titre').textContent = titre;
  if (texte) $('verrou-texte').textContent = texte;
  const formulaire = mode === 'connexion' || mode === 'deverrouiller';
  $('verrou-formulaire').hidden = !formulaire;
  $('verrou-reessayer').hidden = !(mode === 'injoignable');
  $('entrer').textContent = mode === 'deverrouiller' ? 'Déverrouiller' : 'Se connecter';
  erreur.textContent = '';
  majInert();
  if (visible && formulaire) setTimeout(() => { try { champMdp.focus(); } catch (e) { /* rien */ } }, 200);
}

async function validerVerrou() {
  amorcerSynthese();   // vrai geste : c'est le seul moment où iOS accepte de délier la voix
  const mdp = champMdp.value;
  if (!mdp) { erreur.textContent = 'Entrez votre mot de passe.'; return; }
  const deverrouillage = modeVerrou === 'deverrouiller';
  const b = $('entrer');
  erreur.textContent = '';
  b.disabled = true;
  b.textContent = deverrouillage ? 'Déverrouillage…' : 'Connexion…';
  try {
    if (deverrouillage) {
      await api.post('/api/confiance/deverrouiller', { mot_de_passe: mdp }, { delai: 20000 });
      toast('IRIS est déverrouillée.', 'ok');
    } else {
      await api.connexion(mdp);   // POST /api/compte/connexion, puis session retenue (iris_session)
    }
    champMdp.value = '';
    afficherVerrou(null);
    entrer();
  } catch (err) {
    if (deverrouillage && err.status === 401 && !/verrouill/i.test(err.message)) {
      api.fermerSession();
      afficherVerrou('connexion', 'IRIS', 'Session expirée. Entrez votre mot de passe.');
      return;
    }
    erreur.textContent = err.status === 0
      ? "Ordinateur injoignable. Vérifiez qu'il est allumé et que ce téléphone a du réseau."
      : err.message;
  } finally {
    b.disabled = false;
    b.textContent = modeVerrou === 'deverrouiller' ? 'Déverrouiller' : 'Se connecter';
  }
}
$('verrou-formulaire').addEventListener('submit', (e) => { e.preventDefault(); validerVerrou(); });
// Entrée dans le champ : certains claviers virtuels ne déclenchent pas l'envoi implicite du formulaire.
champMdp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); validerVerrou(); } });
$('verrou-reessayer').addEventListener('click', () => { demarrer(); });
$('hors-ligne-reessayer').addEventListener('click', () => { verifier(); api.connecterEvenements(); });

async function demarrer() {
  afficherVerrou('attente', 'IRIS', 'Connexion à votre ordinateur…');
  try {
    compte = await api.compte();
  } catch (e) {
    compte = null;
  }
  if (compte === null) {
    // Ordinateur injoignable dès l'ouverture. Avec une session déjà connue, la page s'ouvre quand
    // même et dit « hors ligne » ; sans session, rien à montrer : on explique.
    if (api.jeton()) { afficherVerrou(null); entrer(); return; }
    afficherVerrou('injoignable', 'Ordinateur injoignable', messageHorsLigne(false));
    return;
  }
  if (compte.configure) {
    // Un mot de passe existe : le jeton d'adresse ne vaut plus rien depuis ce téléphone. On le retire
    // de l'adresse et de la mémoire, pour qu'il ne finisse ni dans l'historique ni dans une capture.
    if (api.jetonDansAdresse()) {
      try { history.replaceState(history.state, '', location.pathname); } catch (e) { /* adresse inchangée */ }
    }
    api.oublierJetonAdresse();
    if (!memoire('iris_session')) {
      afficherVerrou('connexion', 'IRIS', 'Entrez votre mot de passe pour commander votre ordinateur.');
      return;
    }
    try {
      await api.get('/api/status', { delai: 15000 });
    } catch (err) {
      if (err.status === 401 && /verrouill/i.test(err.message)) {
        phase = 'pret';
        afficherVerrou('deverrouiller', 'IRIS est verrouillée', err.message);
        return;
      }
      if (err.status === 401) {
        api.fermerSession();
        afficherVerrou('connexion', 'IRIS', 'Session expirée. Entrez votre mot de passe.');
        return;
      }
      // Injoignable ou erreur passagère : la page s'ouvre et le dit.
    }
    afficherVerrou(null);
    entrer();
    return;
  }
  // Aucun mot de passe posé : le jeton d'adresse est le seul secret, et la page le dit dans l'aide.
  if (!api.jeton()) {
    afficherVerrou('adresse', 'Adresse incomplète', "Ouvrez l'adresse complète affichée dans IRIS sur l'ordinateur : Profil › Compte et sécurité.");
    return;
  }
  afficherVerrou(null);
  entrer();
}

function entrer() {
  phase = 'pret';
  api.connecterEvenements();
  verifier();
  chargerReglages();
  majMemoire();
  sonderBrouillons(false);
  if (memoire('iris_eveil') === 'oui') eveil('reglage', true);
  if (!bouclesLancees) {
    bouclesLancees = true;
    setInterval(verifier, 20000);
    // Cinq secondes : le temps qu'IRIS mette à dire « c'est prêt sur ton téléphone » — plus long, on
    // regarderait un écran vide en l'écoutant ; plus court, ce serait du bruit sur le réseau.
    setInterval(sonderBrouillons, 5000);
  }
}

bus.on('iris.verrouillee', (ev) => {
  if (phase !== 'pret' || modeVerrou === 'deverrouiller') return;
  marquer('err', 'verrouillée');
  afficherVerrou('deverrouiller', 'IRIS est verrouillée', ev.raison);
});
// ------------------------------------------------------------------ lunettes requises (428)
// Toute route qui capte ou agit répond 428 {code: "lunettes_requises"} sans lunettes. Les modules qui ont
// leur garde (IRIS.lunettes.garde) affichent l'invitation dans leur zone ; pour les autres (vision, chat,
// sous-titres de la coquille), c'est ce panneau, jamais une erreur technique.
let panneauLunettes = null;
bus.on('iris.lunettes_requises', (ev) => {
  if (phase !== 'pret') return;
  // Après la gestion d'erreur du module appelant (microtâches), pour savoir s'il l'a déjà affichée.
  setTimeout(() => {
    if ((ev.erreur && ev.erreur.geree) || panneauLunettes) return;
    afficherLunettesRequises(ev);
  }, 0);
});

function afficherLunettesRequises(ev) {
  const p = ouvrirPanneau('Lunettes VELA');
  panneauLunettes = p;
  p.surFermeture(() => { panneauLunettes = null; });
  // L'adresse d'achat vient du service (detail.acheter_url) ; seule une adresse https est suivie. La page
  // n'écrit aucune adresse absolue en dur (test_la_page_est_autonome) : le repli est composé.
  let acheter = 'https:' + '//velaglass.ca/lunettes.html';
  try { if (new URL(String(ev.acheter_url || '')).protocol === 'https:') acheter = String(ev.acheter_url); } catch (e) { /* repli */ }
  const lunettes = window.IRIS && window.IRIS.lunettes;
  p.corps.append(el('h3', {}, 'Cette fonction marche avec les lunettes VELA'));
  p.corps.append(el('p', { class: 'note', role: 'status' },
    'Connectez vos lunettes VELA à ce téléphone ou à votre ordinateur pour utiliser cette fonction.'));
  if (!(lunettes && lunettes.disponible)) {
    p.corps.append(el('p', { class: 'note-faible' }, (lunettes && lunettes.ios) || !('bluetooth' in navigator)
      ? "Dehors, sur iPhone, utilisez l'app IRIS : Safari ne peut pas se connecter aux lunettes. Ici, ces fonctions marchent quand les lunettes sont connectées à votre ordinateur."
      : "Ce navigateur ne peut pas se connecter aux lunettes. Sur Android, ouvrez cette page dans Chrome, ou connectez les lunettes à votre ordinateur."));
  }
  const actions = el('div', { class: 'ligne' });
  if (lunettes && lunettes.disponible && typeof lunettes.connecter === 'function') {
    const connecter = el('button', { type: 'button', class: 'bouton-sombre' }, 'Connecter mes lunettes');
    connecter.addEventListener('click', async () => {
      connecter.disabled = true;
      try {
        await lunettes.connecter();
        p.fermer();
        toast('Lunettes connectées. Réessayez la fonction.', 'info');
      } catch (err) {
        connecter.disabled = false;
        toast((err && err.message) || 'Connexion aux lunettes impossible.', 'erreur');
      }
    });
    actions.append(connecter);
  }
  actions.append(el('a', { class: 'bouton-contour', href: acheter, target: '_blank', rel: 'noopener noreferrer' }, 'Acheter les lunettes'));
  p.corps.append(actions);
  lire('Cette fonction marche avec les lunettes VELA.');
}

bus.on('iris.session_refusee', async (ev) => {
  if (phase !== 'pret' || modeVerrou === 'connexion' || modeVerrou === 'adresse') return;
  marquer('err', 'accès refusé');
  try { compte = await api.compte(); } catch (e) { /* on garde ce qu'on savait */ }
  if (compte && compte.configure) {
    api.fermerSession();
    afficherVerrou('connexion', 'IRIS', 'Session expirée ou révoquée. Entrez votre mot de passe.');
  } else {
    afficherVerrou('adresse', 'Accès refusé', ((ev.raison || '') + " Ouvrez l'adresse complète affichée dans IRIS sur l'ordinateur : Profil › Compte et sécurité.").trim());
  }
});
bus.on('iris.connexion', (ev) => {
  if (phase !== 'pret') return;
  if (ev.pc === false) marquerHorsLigne(navigator.onLine === false);
  else if (ev.pc === true && connexion.pc === false) verifier();
});
bus.on('iris.ws', (ev) => {
  connexion.ws = !!ev.ouvert;
  majLiaison();
  if (ev.refuse) verifier();          // verrouillage ou session : /api/status dira lequel
  if (ev.ouvert) majMemoire();
});
bus.on('hello', () => { if (phase === 'pret') marquerConnecte(); });
bus.on('verrou.etat', (ev) => {
  if (ev.verrouille) {
    afficherVerrou('deverrouiller', 'IRIS est verrouillée', ev.raison === 'distance'
      ? 'IRIS a été verrouillée à distance. Entrez le mot de passe du propriétaire pour la déverrouiller.'
      : 'Entrez le mot de passe du propriétaire pour la déverrouiller.');
  } else if (modeVerrou === 'deverrouiller') {
    afficherVerrou(null);
  }
});
window.addEventListener('online', () => verifier());
window.addEventListener('offline', () => { if (phase === 'pret') marquerHorsLigne(true); });

// ------------------------------------------------------------------ réglages et mémoire suspendue
async function chargerReglages() {
  try { appliquerReglages(await api.get('/api/settings')); } catch (e) { /* l'état de la liaison le dit déjà */ }
}
function appliquerReglages(s) {
  if (!s || typeof s !== 'object') return;
  reglages = s;
  document.documentElement.classList.toggle('grand-texte', !!s.interface_grand_texte);
}
async function changerReglage(patch) {
  const s = await api.patch('/api/settings', patch);
  appliquerReglages(s);
  return s;
}
bus.on('settings.updated', (ev) => appliquerReglages(ev.settings));

function libelleSuspension(raison) {
  const r = String(raison || '');
  if (r === 'invite') return 'mode invité';
  if (r.indexOf('zone:') === 0) return 'zone sans mémoire « ' + r.slice(5) + ' »';
  return r;
}
function afficherMemoire(raison) {
  const b = $('bandeau-memoire');
  b.hidden = !raison;
  if (raison) {
    b.textContent = 'Mémoire suspendue (' + libelleSuspension(raison) + ") : IRIS n'écrit rien, ni souvenirs, ni journal, ni cours, ni descriptions de photos.";
  }
  ajusterHauteur();
}
let minuterieMemoire = null;
function majMemoire() {
  clearTimeout(minuterieMemoire);
  minuterieMemoire = setTimeout(async () => {
    try {
      const e = await api.get('/api/ecoute/etat');
      if (e && 'memoire_suspendue' in e) afficherMemoire(e.memoire_suspendue);
    } catch (err) { /* ordinateur ancien ou injoignable : rien d'affirmé */ }
  }, 150);
}
bus.on('ecoute.etat', (ev) => { if ('memoire_suspendue' in ev) afficherMemoire(ev.memoire_suspendue); });
bus.on('invite.etat', majMemoire);
bus.on('zone.etat', majMemoire);

// ------------------------------------------------------------------ événements annoncés
bus.on('alerte.sonore', afficherAlerte);
bus.on('rappel.contexte', (ev) => {
  const phrase = 'Rappel pour ' + (ev.personne || 'cette personne') + ' : ' + (ev.texte || '');
  signaler(phrase);
  lire(phrase);
});
bus.on('partage.message', (ev) => {
  if (!ev.texte) return;
  const phrase = 'Message de votre proche : ' + ev.texte;
  signaler(phrase);
  lire(phrase);
});

// ------------------------------------------------------------------ image du téléphone
/** Réduit une photo à coteMax pixels sur son plus grand côté, en JPEG, AVANT tout envoi. */
function reduireImage(fichier, coteMax) {
  const limite = Number(coteMax) > 0 ? Number(coteMax) : 1280;
  return new Promise((resoudre, rejeter) => {
    let url = '';
    try { url = URL.createObjectURL(fichier); } catch (e) { rejeter(new Error('Photo illisible sur ce téléphone.')); return; }
    const image = new Image();
    image.onload = () => {
      try {
        const largeur = image.naturalWidth;
        const hauteur = image.naturalHeight;
        if (!largeur || !hauteur) throw new Error('Photo illisible sur ce téléphone.');
        const echelle = Math.min(1, limite / Math.max(largeur, hauteur));
        const toile = document.createElement('canvas');
        toile.width = Math.max(1, Math.round(largeur * echelle));
        toile.height = Math.max(1, Math.round(hauteur * echelle));
        toile.getContext('2d').drawImage(image, 0, 0, toile.width, toile.height);
        const donnees = toile.toDataURL('image/jpeg', 0.85);
        URL.revokeObjectURL(url);
        const virgule = donnees.indexOf(',');
        if (virgule === -1 || donnees.indexOf('data:image/jpeg') !== 0) throw new Error("Ce téléphone n'a pas pu convertir la photo en JPEG.");
        resoudre({ media_type: 'image/jpeg', data: donnees.slice(virgule + 1), largeur: toile.width, hauteur: toile.height });
      } catch (e) {
        URL.revokeObjectURL(url);
        rejeter(e);
      }
    };
    image.onerror = () => { URL.revokeObjectURL(url); rejeter(new Error("Photo illisible sur ce téléphone (format non pris en charge).")); };
    image.src = url;
  });
}

// ------------------------------------------------------------------ fonction : vision
// Les sept modes qui ont un sens avec une photo du téléphone. « ecran » décrit l'écran de
// l'ordinateur resté à la maison : il reste dans l'application de bureau.
const MODES_PHOTO = ['scene', 'lecture', 'billets', 'objet', 'couleur', 'personnes', 'affichage'];

function ouvrirVision(ctx) {
  const corps = ctx.corps;
  corps.append(el('p', { class: 'note' },
    "Choisissez ce que vous voulez savoir, puis prenez la photo avec ce téléphone. Elle est réduite ici, envoyée à votre ordinateur, puis décrite. " +
    "C'est la description d'une photo, pas une surveillance en direct : elle ne signale pas un obstacle qui apparaît ensuite."));

  const question = el('input', { id: 'vision-question', class: 'champ', type: 'text', autocomplete: 'off', placeholder: 'Ex. : est-ce du lait ?' });
  const retenirCase = el('input', { type: 'checkbox', id: 'vision-retenir' });
  retenirCase.checked = true;
  corps.append(el('div', { class: 'carte' },
    el('label', { for: 'vision-question', class: 'etiquette' }, 'Question précise (facultatif)'),
    question,
    el('label', { class: 'case', for: 'vision-retenir' }, retenirCase, el('span', {}, 'Retenir la description sur l’ordinateur, pour « Où ai-je posé ? »')),
    el('p', { class: 'note-faible' }, "La photo elle-même n'est pas gardée par IRIS.")));

  const liste = el('div', { class: 'liste-boutons', role: 'group', 'aria-labelledby': 'vision-modes-titre' },
    el('p', { class: 'note-faible' }, 'Chargement des modes…'));
  const resultat = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  corps.append(el('h3', { id: 'vision-modes-titre', class: 'etiquette' }, 'Que voulez-vous savoir ?'), liste, resultat);

  let enCours = false;
  const boutons = [];

  api.get('/api/accessibilite/modes').then((d) => {
    const parId = new Map(((d && d.modes) || []).map((m) => [m.id, m]));
    const retenus = MODES_PHOTO.map((id) => parId.get(id)).filter(Boolean);
    liste.textContent = '';
    if (!retenus.length) {
      liste.append(el('p', { class: 'resultat-erreur' }, "Aucun mode de description n'est disponible sur votre ordinateur."));
      return;
    }
    for (const m of retenus) {
      const b = el('button', { type: 'button', class: 'choix' },
        el('span', { class: 'choix-titre' }, m.nom),
        el('span', { class: 'choix-sous' }, [m.description, m.limite].filter(Boolean).join(' ')));
      b.addEventListener('click', () => prendrePhoto(m));
      boutons.push(b);
      liste.append(b);
    }
  }).catch((err) => {
    liste.textContent = '';
    liste.append(el('p', { class: 'resultat-erreur' }, err.status === 404
      ? "La description de photos n'est pas disponible sur votre ordinateur : mettez IRIS à jour."
      : err.message));
  });

  function prendrePhoto(m) {
    if (enCours) return;
    const entree = $('photo');
    entree.value = '';
    entree.onchange = () => {
      const fichier = entree.files && entree.files[0];
      entree.onchange = null;
      if (fichier) analyser(m, fichier);
    };
    try { entree.click(); } catch (e) { toast("L'appareil photo ne s'ouvre pas depuis cette page.", 'erreur'); }
  }

  async function analyser(m, fichier) {
    enCours = true;
    boutons.forEach((b) => { b.disabled = true; });
    const debut = performance.now();
    const statut = el('p', { class: 'note' }, 'Préparation de la photo…');
    resultat.hidden = false;
    resultat.textContent = '';
    resultat.append(el('h3', {}, m.nom), statut);
    let chrono = null;
    try {
      const image = await reduireImage(fichier, 1280);
      statut.textContent = 'Envoi à votre ordinateur et analyse…';
      chrono = setInterval(() => {
        statut.textContent = 'Envoi à votre ordinateur et analyse… ' + Math.round((performance.now() - debut) / 1000) + ' s';
      }, 1000);
      const r = await api.post('/api/accessibilite/decrire', {
        mode: m.id, source: 'image', image: { media_type: image.media_type, data: image.data },
        question: question.value.trim() || null,
        parler: false,          // l'ordinateur est à la maison : c'est ce téléphone qui lit la réponse
        memoriser: retenirCase.checked,
      }, { delai: 120000 });
      clearInterval(chrono);
      const total = performance.now() - debut;
      resultat.textContent = '';
      resultat.append(el('h3', {}, m.nom), el('p', { class: 'resultat-texte' }, r.texte || ''));
      if (r.note) resultat.append(el('p', { class: 'note' }, r.note));
      resultat.append(el('p', { class: 'note-faible' },
        (r.local ? 'Traité sur votre ordinateur, sans envoi externe. ' : 'Photo analysée par le moteur VELA. ') +
        'Analyse : ' + secondes(r.duree_ms) + ' ; total mesuré depuis ce téléphone : ' + secondes(total) + '.'));
      lire(r.texte);
    } catch (err) {
      clearInterval(chrono);
      resultat.textContent = '';
      resultat.append(el('h3', {}, m.nom), el('p', { class: 'resultat-erreur' }, (err && err.message) || String(err)));
      if (err && err.code === 'consentement') {
        resultat.append(el('p', { class: 'note' }, "Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité."));
      }
      lire(err && err.message);
    } finally {
      enCours = false;
      boutons.forEach((b) => { b.disabled = false; });
    }
  }
}

// ------------------------------------------------------------------ fonction : où ai-je posé ?
function ouvrirOuEst(ctx) {
  const corps = ctx.corps;
  corps.append(el('p', { class: 'note' },
    "IRIS cherche dans ce qu'elle a décrit ou dans ce que vous lui avez dit, avec la date. Elle ne peut pas savoir où se trouve " +
    "un objet qu'elle n'a jamais vu, et l'objet a pu être déplacé depuis."));
  const champQ = el('input', { id: 'ouest-question', class: 'champ', type: 'text', autocomplete: 'off', placeholder: 'Ex. : mes clés', enterkeyhint: 'search' });
  const dicter = el('button', { type: 'button', class: 'bouton-sombre' }, 'Dicter');
  const chercher = el('button', { type: 'button', class: 'holo' }, 'Chercher');
  const resultat = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  corps.append(el('div', { class: 'carte' },
    el('label', { for: 'ouest-question', class: 'etiquette' }, 'Quel objet cherchez-vous ?'),
    el('div', { class: 'ligne' }, champQ, dicter)), chercher, resultat);

  dicter.addEventListener('click', async () => {
    dicter.disabled = true;
    dicter.textContent = 'Parlez…';
    try {
      champQ.value = await ecouter({ langue: 'fr-CA' });
      lancer();
    } catch (err) {
      if (err.code !== 'interrompu') toast(err.message, 'erreur');
    } finally {
      dicter.disabled = false;
      dicter.textContent = 'Dicter';
    }
  });
  chercher.addEventListener('click', lancer);
  champQ.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lancer(); } });

  async function lancer() {
    const q = champQ.value.trim();
    if (!q) { toast("Dites ou écrivez l'objet à chercher.", 'info'); champQ.focus(); return; }
    chercher.disabled = true;
    resultat.hidden = false;
    resultat.textContent = '';
    resultat.append(el('p', { class: 'note' }, 'Recherche dans vos souvenirs…'));
    const debut = performance.now();
    try {
      const r = await api.post('/api/accessibilite/ou-est', { question: q }, { delai: 60000 });
      resultat.textContent = '';
      resultat.append(el('p', { class: 'resultat-texte' }, r.reponse || ''));
      const souvenirs = r.souvenirs || [];
      if (souvenirs.length) {
        const ul = el('ul', { class: 'souvenirs' });
        souvenirs.forEach((s) => ul.append(el('li', {}, el('time', {}, dateLisible(s.date)), s.texte)));
        resultat.append(el('h3', { class: 'etiquette' }, 'Souvenirs trouvés'), ul);
      }
      resultat.append(el('p', { class: 'note-faible' },
        (r.local ? 'Réponse formée sur votre ordinateur. ' : 'Réponse reformulée par le moteur VELA à partir de ces souvenirs. ') +
        'Délai mesuré : ' + secondes(performance.now() - debut) + '.'));
      lire(r.reponse);
    } catch (err) {
      resultat.textContent = '';
      resultat.append(el('p', { class: 'resultat-erreur' }, err.message));
    } finally {
      chercher.disabled = false;
    }
  }
}

// ------------------------------------------------------------------ fonction : sous-titres géants
function ouvrirSousTitres(ctx) {
  const { corps, surFermeture } = ctx;
  corps.append(
    el('p', { class: 'note' },
      "Les sous-titres affichent ce qu'entend le micro de votre ordinateur, ou celui des lunettes quand elles sont reliées à l'ordinateur. " +
      'La reconnaissance se fait sur l’ordinateur, sans Internet.'),
    el('p', { class: 'note' },
      "Dehors, l'ordinateur resté à la maison n'entend pas votre conversation : cette fonction sert près de lui. " +
      'Transcription approximative : noms propres, accents marqués, bruit et voix superposées sont mal reconnus ; pas de ponctuation, et IRIS n’indique pas qui parle.'));
  const etat = el('p', { class: 'note', role: 'status' }, "Vérification de l'écoute sur l'ordinateur…");
  const bascule = el('button', { type: 'button', class: 'holo' }, 'Démarrer les sous-titres');
  const moins = el('button', { type: 'button', class: 'bouton-sombre', 'aria-label': 'Réduire le texte' }, 'A−');
  const plus = el('button', { type: 'button', class: 'bouton-sombre', 'aria-label': 'Agrandir le texte' }, 'A+');
  const ecran = el('div', { class: 'sous-titres' });
  const vide = el('p', { class: 'st-vide' }, 'Les phrases entendues apparaîtront ici.');
  const lignes = el('div', { 'aria-live': 'polite' });
  const partiel = el('p', { class: 'st-partiel', 'aria-hidden': 'true' });
  ecran.append(vide, lignes, partiel);
  corps.append(etat, bascule, el('div', { class: 'ligne' }, moins, plus),
    el('p', { class: 'note-faible' }, 'Fermer ce panneau arrête les sous-titres démarrés d’ici.'), ecran);

  let taille = Number(memoire('iris_taille_st')) || 2.25;
  const appliquerTaille = () => { ecran.style.setProperty('--taille-st', taille + 'rem'); retenir('iris_taille_st', String(taille)); };
  appliquerTaille();
  moins.addEventListener('click', () => { taille = Math.max(1.25, taille - 0.25); appliquerTaille(); });
  plus.addEventListener('click', () => { taille = Math.min(4.5, taille + 0.25); appliquerTaille(); });

  let actif = false;
  let demarreIci = false;
  function ajouterLigne(texte) {
    if (!texte) return;
    vide.remove();
    lignes.append(el('p', { class: 'st-ligne' }, texte));
    while (lignes.children.length > 40) lignes.firstElementChild.remove();
    corps.scrollTop = corps.scrollHeight;
  }
  function majEtat(e) {
    if (!e || typeof e !== 'object') return;
    actif = !!e.sous_titres;
    bascule.textContent = actif ? 'Arrêter les sous-titres' : 'Démarrer les sous-titres';
    bascule.classList.toggle('rouge', actif);
    let t = actif ? "Sous-titres en marche sur l'ordinateur." : 'Sous-titres arrêtés.';
    if (e.modele_pret === false) t = "La reconnaissance hors ligne n'est pas installée sur l'ordinateur (réglages de la voix d'IRIS sur l'ordinateur).";
    if (e.raison) t += ' ' + e.raison;
    if (actif && !api.evenementsOuverts()) t += ' Liaison en direct coupée : le texte arrive toutes les deux secondes environ.';
    etat.textContent = t;
    eveil('sous-titres', actif);
  }
  const desabonnements = [
    bus.on('ecoute.sous_titre', (ev) => {
      if (ev.final) { ajouterLigne(ev.final); partiel.textContent = ''; }
      else if (typeof ev.partiel === 'string') partiel.textContent = ev.partiel;
    }),
    bus.on('ecoute.etat', (ev) => { if ('sous_titres' in ev) majEtat(ev); }),
  ];
  // Liaison en direct coupée : on relit la transcription de la session par sondage.
  const sondage = setInterval(async () => {
    if (!actif || api.evenementsOuverts()) return;
    try {
      const d = await api.get('/api/ecoute/transcription');
      const toutes = (d && d.lignes) || [];
      if (!toutes.length) return;
      lignes.textContent = '';
      vide.remove();
      toutes.slice(-40).forEach((l) => lignes.append(el('p', { class: 'st-ligne' }, l.texte)));
      corps.scrollTop = corps.scrollHeight;
    } catch (e) { /* prochain tour */ }
  }, 2000);

  bascule.addEventListener('click', async () => {
    bascule.disabled = true;
    try {
      if (actif) {
        const r = await api.post('/api/ecoute/sous-titres/arreter');
        demarreIci = false;
        majEtat(r && r.etat);
      } else {
        const e = await api.post('/api/ecoute/sous-titres/demarrer');
        demarreIci = true;
        majEtat(e);
      }
    } catch (err) {
      etat.textContent = err.message;
      toast(err.message, 'erreur');
    } finally {
      bascule.disabled = false;
    }
  });
  api.get('/api/ecoute/etat').then(majEtat).catch((err) => {
    etat.textContent = err.status === 404
      ? "Les sous-titres ne sont pas disponibles sur votre ordinateur : mettez IRIS à jour."
      : err.message;
    if (err.status === 404) bascule.disabled = true;
  });

  surFermeture(() => {
    desabonnements.forEach((f) => f());
    clearInterval(sondage);
    eveil('sous-titres', false);
    if (demarreIci && actif) api.post('/api/ecoute/sous-titres/arreter').catch(() => { /* l'ordinateur les arrêtera à la prochaine purge */ });
  });
}

// ------------------------------------------------------------------ fonction : réglages
function interrupteur(id, titre, sous, coche, surChangement) {
  const entree = el('input', { type: 'checkbox', role: 'switch', id, class: 'interrupteur' });
  entree.checked = !!coche;
  entree.addEventListener('change', () => surChangement(entree.checked, entree));
  return el('div', { class: 'rangee-reglage' },
    el('label', { for: id, class: 'rangee-libelle' },
      el('span', { class: 'rangee-titre' }, titre),
      sous ? el('span', { class: 'rangee-sous' }, sous) : null),
    entree);
}

function ouvrirReglages(ctx) {
  const corps = ctx.corps;

  // Voix
  const debit = el('input', { type: 'range', class: 'curseur', id: 'reglage-debit', min: '90', max: '555', step: '5' });
  debit.value = String(Number(reglages.tts_rate) || 185);
  const valeur = el('output', { class: 'valeur', for: 'reglage-debit' });
  const majDebit = () => {
    valeur.textContent = fois(debit.value);
    debit.setAttribute('aria-valuetext', fois(debit.value).replace('×', ' fois'));
  };
  majDebit();
  debit.addEventListener('input', majDebit);
  debit.addEventListener('change', async () => {
    try {
      await changerReglage({ tts_rate: Number(debit.value) });
      parler('Voici ma voix à ce débit.');
    } catch (err) { toast(err.message, 'erreur'); }
  });
  corps.append(el('div', { class: 'carte' },
    el('h3', {}, 'Voix d’IRIS'),
    el('label', { for: 'reglage-debit', class: 'etiquette' }, 'Débit de la voix'), valeur, debit,
    el('p', { class: 'note-faible' },
      "S'applique à la voix de l'ordinateur et à celle de ce téléphone, jusqu'à 3× selon ce que le téléphone permet. " +
      'La voix Windows avance par crans ; au-delà de 2×, la voix reste intelligible mais moins naturelle.')));

  // Longueur des réponses
  const groupe = el('fieldset', { class: 'segmente' }, el('legend', {}, 'Longueur des réponses'));
  [['concis', 'Concise', 'Environ une ou deux phrases.'],
   ['normal', 'Normale', 'Environ trois à cinq phrases.'],
   ['descriptif', 'Descriptive', 'Descriptions détaillées, plus longues à écouter.']].forEach(([v, libelle, sous]) => {
    const id = 'verbosite-' + v;
    const radio = el('input', { type: 'radio', name: 'verbosite', id, value: v });
    radio.checked = (reglages.verbosite || 'normal') === v;
    radio.addEventListener('change', () => {
      if (radio.checked) changerReglage({ verbosite: v }).catch((err) => toast(err.message, 'erreur'));
    });
    groupe.append(el('label', { for: id }, radio,
      el('span', { class: 'rangee-libelle' }, el('span', { class: 'rangee-titre' }, libelle), el('span', { class: 'rangee-sous' }, sous))));
  });
  corps.append(el('div', { class: 'carte' }, groupe));

  // Affichage et comportement de ce téléphone
  corps.append(el('div', { class: 'carte' },
    el('h3', {}, 'Affichage'),
    interrupteur('reglage-grand-texte', 'Grand texte', 'Agrandit le texte de cette page (réglage partagé avec IRIS sur l’ordinateur).',
      !!reglages.interface_grand_texte, (v, entree) => {
        changerReglage({ interface_grand_texte: v }).catch((err) => { entree.checked = !v; toast(err.message, 'erreur'); });
      }),
    interrupteur('reglage-lecture', 'Lire les réponses à voix haute', 'Avec la voix de ce téléphone. Désactivez-le si vous utilisez VoiceOver, pour ne pas entendre deux voix.',
      lectureAuto(), (v) => retenir('iris_lecture_auto', v ? 'oui' : 'non')),
    interrupteur('reglage-eveil', 'Garder l’écran allumé', "Tant qu'IRIS est ouverte à l'écran. Sur iPhone, une page en arrière-plan ou un écran verrouillé ne reçoit plus rien.",
      memoire('iris_eveil') === 'oui', async (v) => {
        retenir('iris_eveil', v ? 'oui' : 'non');
        const ok = await eveil('reglage', v);
        if (v && !ok) toast("Ce téléphone refuse de garder l'écran allumé depuis cette page. Réglez le verrouillage automatique dans les réglages du téléphone.", 'alerte');
      })));

  // Alertes sonores : réglées sur l'ordinateur, affichées ici
  const texteAlertes = el('p', { class: 'note' }, 'Vérification…');
  const carteAlertes = el('div', { class: 'carte' }, el('h3', {}, 'Alertes sonores'), texteAlertes);
  corps.append(carteAlertes);
  api.get('/api/alertes').then((a) => {
    let t = a.actives
      ? (a.en_marche ? "Actives sur l'ordinateur." : "Activées sur l'ordinateur, mais l'écoute ne tourne pas.")
      : "Désactivées. Elles se règlent sur l'ordinateur, dans Accessibilité › Alertes sonores.";
    if (a.raison) t += ' ' + a.raison;
    texteAlertes.textContent = t;
    carteAlertes.append(el('p', { class: 'note-faible' },
      "Quand l'ordinateur détecte un son, ce téléphone l'affiche en plein écran, s'il est ouvert à l'écran. Pas de vibration sur iPhone : Safari ne la permet pas aux pages web."));
    if (a.avertissement) carteAlertes.append(el('p', { class: 'note-faible' }, a.avertissement));
  }).catch((err) => {
    texteAlertes.textContent = err.status === 404 ? "Les alertes sonores ne sont pas disponibles sur votre ordinateur." : err.message;
  });

  // Ce qui marche dehors, et ce qui ne marche pas
  const limites = el('details', { class: 'carte' }, el('summary', {}, 'Ce qui marche dehors, et ce qui ne marche pas'));
  const liste = (titre, elements) => [el('p', { class: 'etiquette' }, titre), el('ul', { class: 'liste-limites' }, elements.map((t) => el('li', {}, t)))];
  limites.append(
    ...liste('Ce qui marche', [
      "Parler à IRIS ou lui écrire, et entendre sa réponse lue par ce téléphone (donc dans les lunettes, si elles sont la sortie audio du téléphone).",
      'Faire décrire une photo prise avec ce téléphone, et « Où ai-je posé ? ».',
      'Les textos et appels préparés par IRIS, envoyés par vous depuis ce téléphone.',
      "Les alertes sonores entendues à la maison par l'ordinateur, affichées ici tant que la page est ouverte.",
    ]),
    ...liste('Ce qu’il faut', [
      "L'ordinateur allumé, IRIS ouverte, Internet des deux côtés, et l'application de réseau privé active sur ce téléphone.",
      "L'écran de ce téléphone allumé et IRIS au premier plan : iOS suspend une page web dès qu'elle quitte l'écran.",
    ]),
    ...liste('Ce qui ne marche pas dehors', [
      "La caméra et les boutons des lunettes : ils sont reliés à l'ordinateur par Bluetooth, dont la portée est d'une dizaine de mètres.",
      "Les sous-titres de votre conversation : le micro qui écoute est celui de l'ordinateur.",
      'Les notifications, écran verrouillé ou page en arrière-plan, et la vibration sur iPhone.',
    ]),
    ...liste('Délais et confidentialité', [
      "Chaque demande fait l'aller-retour téléphone, ordinateur, parfois moteur VELA, puis téléphone : les délais affichés sont mesurés, jamais promis.",
      'La dictée utilise la reconnaissance vocale intégrée au téléphone : selon le téléphone, vos phrases peuvent être envoyées aux serveurs de son fabricant pour être reconnues.',
    ]));
  corps.append(limites);

  // Connexion
  const carteConnexion = el('div', { class: 'carte' }, el('h3', {}, 'Connexion'),
    el('p', { class: 'note' }, connexion.pc
      ? 'Connectée à votre ordinateur' + (connexion.ms !== null ? ' (dernier aller-retour : ' + connexion.ms + ' ms)' : '') + '.'
      : "L'ordinateur ne répond pas pour l'instant."));
  if (compte && compte.configure) {
    const deconnecter = el('button', { type: 'button', class: 'bouton-contour' }, 'Déconnecter ce téléphone');
    deconnecter.addEventListener('click', async () => {
      const ok = await confirmer('Déconnecter ce téléphone ? Il faudra entrer le mot de passe pour revenir. Les autres appareils restent connectés.',
        { oui: 'Déconnecter', non: 'Annuler' });
      if (!ok) return;
      api.fermerSession();
      oublier('iris_conv');
      location.reload();
    });
    carteConnexion.append(deconnecter);
  }
  carteConnexion.append(el('p', { class: 'note-faible' },
    'Fonctions chargées sur cette page : ' + (Array.from(modules.keys()).join(', ') || 'aucune') + '. Version de la page : ' + VERSION_COQUILLE + '.'));
  corps.append(carteConnexion);
}

// Les fonctions du cœur passent par le même contrat que les modules des autres équipes.
enregistrer({ id: 'vision', titre: 'Décrire une photo', sous_titre: 'Devant moi, lire, billets, objet…', icone: ICONES.oeil, ordre: 10, ouvrir: ouvrirVision });
enregistrer({ id: 'ou-est', titre: 'Où ai-je posé ?', sous_titre: 'Chercher dans vos souvenirs', icone: ICONES.recherche, ordre: 20, ouvrir: ouvrirOuEst });
enregistrer({ id: 'sous-titres', titre: 'Sous-titres géants', sous_titre: "Ce qu'entend l'ordinateur", icone: ICONES.sousTitres, ordre: 30, ouvrir: ouvrirSousTitres });
enregistrer({ id: 'reglages', titre: 'Réglages', sous_titre: 'Voix, texte, limites', icone: ICONES.reglages, ordre: 1000, ouvrir: ouvrirReglages });

// ------------------------------------------------------------------ hauteur réelle
// 100dvh manque aux iOS anciens, et le clavier iOS recouvrirait le champ. On suit la fenêtre
// visuelle : la zone centrale rétrécit, le bouton et le champ restent visibles.
function ajusterHauteur() {
  const vue = window.visualViewport;
  const h = vue ? vue.height : window.innerHeight;
  if (h) document.documentElement.style.setProperty('--hauteur', Math.round(h) + 'px');
}
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', ajusterHauteur);
  window.visualViewport.addEventListener('scroll', ajusterHauteur);
}
window.addEventListener('orientationchange', () => setTimeout(ajusterHauteur, 250));
ajusterHauteur();
champ.addEventListener('focus', () => setTimeout(() => { ajusterHauteur(); defilerEnBas(); }, 300));

// ------------------------------------------------------------------ installation sur iPhone
// iOS ne propose JAMAIS « Installer l'application ». Le seul chemin est Safari ▸ Partager ▸
// « Sur l'écran d'accueil ». Chrome et les autres navigateurs de l'iPhone ne savent pas le faire de
// façon fiable, d'où la mention explicite de Safari.
function proposerInstallation() {
  if (!IOS || AUTONOME) return;
  if (memoire('iris_ios_installe') === 'vu') return;
  $('banniere-texte').textContent = SAFARI_IOS
    ? "Gardez IRIS sous la main : touchez Partager, en bas de Safari, puis « Sur l'écran d'accueil »."
    : "Gardez IRIS sous la main : ouvrez cette adresse dans Safari — seul lui sait le faire sur iPhone — puis Partager, puis « Sur l'écran d'accueil ».";
  $('banniere').hidden = false;
  ajusterHauteur();
}
$('banniere-ok').addEventListener('click', () => {
  $('banniere').hidden = true;
  retenir('iris_ios_installe', 'vu');   // fermé une fois, fermé pour de bon
  ajusterHauteur();
});
proposerInstallation();

// ------------------------------------------------------------------ lancement
// Signal pour un module évalué avant la coquille qui attendrait son arrivée. Envoyé ici, à la fin :
// plus tôt, un enregistrement toucherait des variables pas encore initialisées.
try { window.dispatchEvent(new CustomEvent('iris:pret')); } catch (e) { /* navigateur ancien : les modules sondent */ }
demarrer();

// Agent de service : il permet à Android de proposer « Installer l'application », et sert la
// coquille hors ligne une fois la page posée sur l'écran d'accueil. Jamais les données.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* sans lui, la page marche quand même */ });
}
