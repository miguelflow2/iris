/* IRIS — les lunettes VELA vues depuis la page téléphone : présence, connexion Bluetooth et attestation.
 *
 * Pourquoi ce module passe avant les autres : VELA vend des lunettes, et IRIS est la technologie
 * qu'elles contiennent. Toute fonction de cette page qui capte (caméra, micro) ou qui agit (guidage,
 * interprète, vision partagée, reçus, prix) exige des lunettes présentes : vues par l'ordinateur, ou
 * attestées par le téléphone qui leur est connecté. Ce module répond à la question pour tous les autres
 * (IRIS.lunettes.garde) et, là où le navigateur le permet, fournit la preuve : une connexion Bluetooth
 * basse énergie maintenue avec les lunettes, confirmée à l'ordinateur toutes les 60 secondes
 * (POST /api/lunettes/attestation, que l'ordinateur ne croit plus au-delà de 150 secondes).
 *
 * Sur iPhone, Safari n'a pas de Bluetooth web : la page ne peut rien attester, et elle le dit. Dehors,
 * sur iPhone, c'est l'app IRIS native qui se connecte aux lunettes ; ici, dans Safari, les fonctions
 * marchent seulement quand les lunettes sont reliées à l'ordinateur.
 *
 * Ce que la connexion ne fait PAS, et que le panneau dit : elle ne transporte ni le son (Bluetooth
 * audio du téléphone, géré par le système) ni les images (la commande photo des lunettes n'est pas
 * pilotée depuis le téléphone). Elle prouve seulement que les lunettes sont là. Une page fermée, ou
 * longtemps en arrière-plan, cesse de le prouver.
 *
 * Aucun geste caché ni aucune mention d'un accès propriétaire ici : quand l'ordinateur répond
 * « présentes » sans lunettes vues (source « demo » ou « desactive »), la page dit seulement que les
 * fonctions sont disponibles, sans affirmer que des lunettes sont connectées.
 *
 * Contrat : window.IRIS.lunettes = { disponible, connectees, nom, connecter(), deconnecter() },
 * plus, pour les modules voisins : presence({frais}), garde(ctx, options), on(fonction) -> off,
 * raisonIndisponible(), statut().
 */

const SERVICE_LUNETTES = 0xae00;           // service applicatif des lunettes-caméra (lunettes_camera.py)
const ATTESTATION_MS = 60000;              // l'ordinateur garde une attestation 150 s : on la refait chaque minute
const VALIDITE_ATTESTATION_MS = 150000;
const CACHE_PRESENCE_MS = 4000;            // plusieurs modules qui demandent en même temps : une seule requête
const GRACE_ABSENCE_MS = 12000;            // une absence passagère (micro qui change, réattestation) ne coupe rien
const SONDAGE_GARDE_MS = 30000;            // la présence vue par l'ordinateur ne publie pas toujours d'événement
const DELAI_GATT_MS = 20000;
const RECONNEXIONS_MS = [2000, 5000, 15000, 30000];
const URL_ACHAT_DEFAUT = 'https://velaglass.ca/lunettes.html';
const CLE_APPAREIL = 'iris_lunettes_appareil';   // identifiant Bluetooth opaque, propre à cette page

const UA = navigator.userAgent || '';
const IOS = /iPad|iPhone|iPod/.test(UA) || (UA.indexOf('Macintosh') !== -1 && 'ontouchend' in document);
const BLUETOOTH = !!(window.isSecureContext && navigator.bluetooth && typeof navigator.bluetooth.requestDevice === 'function');

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
const IRISv = () => window.IRIS || {};
const apiIRIS = () => IRISv().api || null;
function toast(texte, genre) { const ui = IRISv().ui; if (ui && typeof ui.toast === 'function') ui.toast(texte, genre); }
function lectureAuto() { return memoireLocale('iris_lecture_auto') !== 'non'; }
function dire(texte) {
  const voix = IRISv().voix;
  if (!texte || !lectureAuto() || !voix || typeof voix.parler !== 'function') return;
  try { Promise.resolve(voix.parler(texte)).catch(() => false); } catch (e) { /* voix indisponible */ }
}
function erreur(message, statut) {
  const e = new Error(message);
  e.status = typeof statut === 'number' ? statut : -1;
  return e;
}
function ilYA(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s';
}

// ------------------------------------------------------------------ état partagé par toute la page
const etat = {
  appareil: null,             // BluetoothDevice choisi sur ce téléphone
  connectees: false,          // lien GATT ouvert en ce moment
  connexionEnCours: false,
  connexionVoulue: false,     // l'utilisateur veut rester connecté : on retente après une coupure
  nom: null,                  // nom annoncé par les lunettes connectées ici
  batterie: null,
  erreur: '',                 // dernier problème de connexion, dit tel quel
  attestation: { derniere: 0, acceptee: false, erreur: '' },
  presence: null,             // dernière réponse de GET /api/lunettes/presence
  presenceA: 0,
  presenceEnVol: null,
  nomConnu: undefined,        // nom des lunettes associées, selon l'ordinateur (undefined : pas encore lu)
  essaiReconnexion: 0,
  minuterieReconnexion: null,
  minuterieAttestation: null,
};
const ecouteurs = new Set();
const ecoutesAppareil = new WeakSet();

function statut() {
  return {
    disponible: BLUETOOTH,
    connectees: etat.connectees,
    connexion_en_cours: etat.connexionEnCours,
    nom: etat.nom,
    batterie: etat.batterie,
    erreur: etat.erreur,
    attestation_acceptee: etat.attestation.acceptee,
    attestation_age_ms: etat.attestation.derniere ? Date.now() - etat.attestation.derniere : null,
    attestation_erreur: etat.attestation.erreur,
    presence: etat.presence,
  };
}

function notifier() {
  const s = statut();
  for (const fonction of Array.from(ecouteurs)) {
    try { fonction(s); } catch (e) { /* un écouteur qui plante ne prive pas les autres */ }
  }
  const bus = IRISv().bus;
  if (bus && typeof bus.emit === 'function') {
    try { bus.emit('iris.lunettes', s); } catch (e) { /* bus indisponible */ }
  }
}

function raisonIndisponible() {
  if (BLUETOOTH) return '';
  if (IOS) {
    return "Sur iPhone, Safari ne donne pas accès au Bluetooth. Dehors, sur iPhone, utilisez l'app IRIS : c'est elle qui se connecte à vos lunettes. " +
      'Ici, les fonctions marchent quand vos lunettes sont connectées à votre ordinateur.';
  }
  if (!window.isSecureContext) {
    return "La connexion Bluetooth n'est permise qu'à une page sécurisée (adresse en https). Ouvrez IRIS par l'adresse de votre réseau privé, " +
      'ou connectez vos lunettes à votre ordinateur.';
  }
  return "Ce navigateur ne permet pas la connexion Bluetooth depuis une page web. Sur Android, ouvrez cette page dans Chrome, " +
    'ou connectez vos lunettes à votre ordinateur.';
}

// ------------------------------------------------------------------ présence selon l'ordinateur
function retenirPresence(d) {
  if (!d || typeof d !== 'object' || typeof d.presentes !== 'boolean') return;
  const copie = Object.assign({}, d);
  delete copie.type;
  const avant = etat.presence ? etat.presence.presentes : null;
  const avantSource = etat.presence ? etat.presence.source : null;
  etat.presence = copie;
  etat.presenceA = Date.now();
  if (typeof copie.nom === 'string' && copie.nom.trim()) etat.nomConnu = copie.nom.trim();
  else if (etat.nomConnu === undefined) etat.nomConnu = null;
  if (avant !== copie.presentes || avantSource !== copie.source) notifier();
}

/** GET /api/lunettes/presence, partagé entre modules. {frais: true} ignore le cache de 4 s. */
function presence(options) {
  const o = options || {};
  const api = apiIRIS();
  if (!api) return Promise.reject(erreur("La liaison avec votre ordinateur n'est pas prête.", 0));
  if (!o.frais && etat.presence && Date.now() - etat.presenceA < CACHE_PRESENCE_MS) return Promise.resolve(etat.presence);
  if (etat.presenceEnVol) return etat.presenceEnVol;
  const delai = Number(o.delai) > 0 ? Number(o.delai) : 10000;
  const enVol = api.get('/api/lunettes/presence', { delai }).then((d) => {
    retenirPresence(d);
    return etat.presence || d;
  });
  etat.presenceEnVol = enVol;
  const liberer = () => { if (etat.presenceEnVol === enVol) etat.presenceEnVol = null; };
  enVol.then(liberer, liberer);
  return enVol;
}

function presenceRecente() {
  return !!(etat.presence && etat.presence.presentes && Date.now() - etat.presenceA < VALIDITE_ATTESTATION_MS);
}
/** Preuve tenue par ce téléphone lui-même : lunettes connectées ici ET acceptées récemment par l'ordinateur. */
function preuveLocale() {
  return etat.connectees && etat.attestation.acceptee && Date.now() - etat.attestation.derniere < VALIDITE_ATTESTATION_MS;
}

// ------------------------------------------------------------------ Bluetooth (Android, Chrome)
function messageBluetooth(e, etape) {
  const nom = (e && e.name) || '';
  if (nom === 'NotFoundError') {
    return etape === 'choix'
      ? "Aucune paire choisie. Si vos lunettes n'apparaissent pas dans la liste : allumez-les, rapprochez-les du téléphone, puis réessayez."
      : 'Les lunettes ne sont plus à portée : rapprochez-les du téléphone, puis réessayez.';
  }
  if (nom === 'SecurityError') return 'Le navigateur demande un geste : touchez de nouveau « Connecter mes lunettes ».';
  if (nom === 'NotAllowedError') {
    return 'Bluetooth refusé pour cette page. Autorisez « Appareils à proximité » (ou la localisation, sur certains Android) pour Chrome, puis réessayez.';
  }
  if (nom === 'NetworkError') return 'Les lunettes ne répondent pas : rapprochez-les du téléphone, vérifiez qu’elles sont allumées, puis réessayez.';
  if (nom === 'NotSupportedError') return "Ce téléphone ne permet pas cette connexion Bluetooth depuis une page web.";
  return (e && e.message) || 'La connexion Bluetooth a échoué.';
}

function filtresPour(nom) {
  const filtres = [];
  const propre = String(nom || '').trim();
  if (propre) {
    filtres.push({ name: propre });
    // Le nom annoncé en basse énergie diffère parfois du nom audio (suffixe) : on accepte aussi le
    // premier mot, comme le fait l'ordinateur (lunettes_presence.attester). L'ordinateur revérifie.
    const tete = propre.split(/\s+/)[0];
    if (tete.length >= 3 && tete !== propre) filtres.push({ namePrefix: tete });
  }
  filtres.push({ services: [SERVICE_LUNETTES] });
  return filtres;
}

function avecDelai(promesse, ms, message) {
  let minuterie = null;
  const garde = new Promise((_, rejeter) => { minuterie = setTimeout(() => rejeter(erreur(message)), ms); });
  return Promise.race([promesse, garde]).finally(() => clearTimeout(minuterie));
}

async function lireBatterie(appareil) {
  try {
    if (!appareil || !appareil.gatt || !appareil.gatt.connected) return etat.batterie;
    const service = await avecDelai(appareil.gatt.getPrimaryService('battery_service'), 3000, 'batterie');
    const caracteristique = await service.getCharacteristic('battery_level');
    const valeur = await avecDelai(caracteristique.readValue(), 3000, 'batterie');
    const n = valeur.getUint8(0);
    return n >= 0 && n <= 100 ? n : null;
  } catch (e) {
    return null;   // beaucoup de lunettes n'exposent pas le niveau de batterie : on n'invente rien
  }
}

function attestationRecente() {
  return etat.attestation.acceptee && Date.now() - etat.attestation.derniere < VALIDITE_ATTESTATION_MS;
}

/** Confirme à l'ordinateur que les lunettes sont connectées ici. Lève une erreur 403 si ce ne sont pas les bonnes. */
async function attester() {
  const api = apiIRIS();
  const appareil = etat.appareil;
  if (!api || !appareil || !etat.connectees) return false;
  if (appareil.gatt && !appareil.gatt.connected) { surDeconnexion(); return false; }
  etat.batterie = await lireBatterie(appareil);
  const corps = {
    nom: appareil.name || etat.nom || 'Lunettes sans nom annoncé',
    identifiant: appareil.id || '',
    batterie: etat.batterie,
    source: IOS ? 'iphone' : 'android',
  };
  try {
    const d = await api.post('/api/lunettes/attestation', corps, { delai: 15000 });
    etat.attestation = { derniere: Date.now(), acceptee: true, erreur: '' };
    retenirPresence(d);
    notifier();
    return true;
  } catch (err) {
    const statutHttp = err && typeof err.status === 'number' ? err.status : -1;
    if (statutHttp === 403 || statutHttp === 422) {
      // L'ordinateur refuse ces lunettes : on coupe, sans retenter et sans retirer l'attestation d'un autre.
      const message = (err && err.message) || 'Ces lunettes ne sont pas celles associées à votre IRIS.';
      etat.attestation = { derniere: 0, acceptee: false, erreur: message };
      etat.connexionVoulue = false;
      oublierLocal(CLE_APPAREIL);
      arreterAttestations();
      try { if (appareil.gatt && appareil.gatt.connected) appareil.gatt.disconnect(); } catch (e) { /* déjà coupé */ }
      etat.connectees = false;
      etat.erreur = message;
      notifier();
      throw erreur(message, statutHttp);
    }
    etat.attestation.erreur = statutHttp === 0
      ? "L'ordinateur ne répond pas : la présence des lunettes ne lui est pas confirmée pour l'instant. Nouvel essai dans une minute."
      : statutHttp === 404
        ? "Votre ordinateur ne connaît pas l'attestation des lunettes : mettez IRIS à jour sur l'ordinateur."
        : ((err && err.message) || "L'ordinateur a refusé la confirmation.");
    notifier();
    return false;
  }
}

function demarrerAttestations() {
  arreterAttestations();
  etat.minuterieAttestation = setInterval(() => {
    if (!etat.connectees) { arreterAttestations(); return; }
    attester().catch(() => { /* refus déjà dit dans l'état */ });
  }, ATTESTATION_MS);
}
function arreterAttestations() {
  clearInterval(etat.minuterieAttestation);
  etat.minuterieAttestation = null;
}

/** Retire l'attestation de CE téléphone, seulement si elle est encore la sienne et encore valable. */
function retirerAttestation() {
  if (!attestationRecente()) return Promise.resolve(false);
  etat.attestation = { derniere: 0, acceptee: false, erreur: '' };
  const api = apiIRIS();
  if (!api) return Promise.resolve(false);
  return api.delete('/api/lunettes/attestation', { delai: 10000 })
    .then((d) => { retenirPresence(d); return true; })
    .catch(() => false);   // injoignable : l'ordinateur l'oubliera seul après 150 s
}

function surDeconnexion() {
  if (!etat.connectees && !etat.connexionEnCours) return;
  etat.connectees = false;
  arreterAttestations();
  retirerAttestation();
  notifier();
  if (etat.connexionVoulue && etat.appareil) planifierReconnexion();
}

function planifierReconnexion() {
  clearTimeout(etat.minuterieReconnexion);
  const i = etat.essaiReconnexion;
  if (i >= RECONNEXIONS_MS.length) {
    etat.connexionVoulue = false;
    etat.erreur = 'Lunettes perdues : plusieurs essais de reconnexion ont échoué. Rapprochez-les du téléphone, puis touchez « Connecter mes lunettes ».';
    notifier();
    return;
  }
  etat.minuterieReconnexion = setTimeout(async () => {
    etat.essaiReconnexion += 1;
    if (!etat.connexionVoulue || !etat.appareil || etat.connectees || etat.connexionEnCours) return;
    try {
      await ouvrirLien(etat.appareil);
    } catch (e) {
      if (etat.connexionVoulue && !etat.connectees) planifierReconnexion();
    }
  }, RECONNEXIONS_MS[i]);
}

/** Ouvre le lien GATT avec un appareil déjà choisi, puis atteste. */
async function ouvrirLien(appareil) {
  if (etat.appareil && etat.appareil !== appareil && etat.appareil.gatt && etat.appareil.gatt.connected) {
    try { etat.appareil.gatt.disconnect(); } catch (e) { /* déjà coupé */ }
  }
  etat.appareil = appareil;
  etat.nom = appareil.name || null;
  if (!ecoutesAppareil.has(appareil)) {
    appareil.addEventListener('gattserverdisconnected', () => { if (etat.appareil === appareil) surDeconnexion(); });
    ecoutesAppareil.add(appareil);
  }
  etat.connexionVoulue = true;
  etat.connexionEnCours = true;
  etat.erreur = '';
  notifier();
  try {
    await avecDelai(appareil.gatt.connect(), DELAI_GATT_MS,
      'Les lunettes ne répondent pas : rapprochez-les du téléphone, vérifiez qu’elles sont allumées, puis réessayez.');
    etat.connectees = !!(appareil.gatt && appareil.gatt.connected);
    if (!etat.connectees) throw erreur('Les lunettes ont refusé la connexion.');
  } catch (e) {
    etat.connectees = false;
    etat.connexionEnCours = false;
    try { if (appareil.gatt && appareil.gatt.connected) appareil.gatt.disconnect(); } catch (e2) { /* déjà coupé */ }
    etat.erreur = messageBluetooth(e, 'connexion');
    notifier();
    throw erreur(etat.erreur);
  }
  etat.connexionEnCours = false;
  etat.essaiReconnexion = 0;
  retenirLocal(CLE_APPAREIL, appareil.id || '');
  notifier();
  await attester();          // tout de suite : l'ordinateur doit le savoir avant le premier geste
  demarrerAttestations();
  return statut();
}

/** Choix des lunettes par l'utilisateur (liste du navigateur), connexion, attestation. À appeler depuis un geste. */
async function connecter() {
  if (!BLUETOOTH) throw erreur(raisonIndisponible());
  if (etat.connectees) return statut();
  if (etat.connexionEnCours) throw erreur('Connexion déjà en cours…');
  clearTimeout(etat.minuterieReconnexion);
  // Le navigateur n'ouvre sa liste d'appareils que peu après le geste : le nom connu de l'ordinateur
  // est normalement déjà en cache ; sinon, on le demande avec un délai court.
  let nom = etat.nomConnu;
  if (nom === undefined) {
    try { nom = ((await presence({ delai: 3000 })) || {}).nom || null; } catch (e) { nom = null; }
  }
  if (typeof navigator.bluetooth.getAvailability === 'function') {
    try {
      if (!(await navigator.bluetooth.getAvailability())) throw erreur('Le Bluetooth de ce téléphone est désactivé : activez-le, puis réessayez.');
    } catch (e) {
      if (e && e.status === -1) throw e;   // notre propre message ; une erreur du navigateur n'empêche pas d'essayer
    }
  }
  let appareil;
  try {
    appareil = await navigator.bluetooth.requestDevice({ filters: filtresPour(nom), optionalServices: [SERVICE_LUNETTES, 'battery_service'] });
  } catch (e) {
    const message = messageBluetooth(e, 'choix');
    if (!(e && e.name === 'NotFoundError')) { etat.erreur = message; notifier(); }
    throw erreur(message);
  }
  etat.essaiReconnexion = 0;
  try {
    return await ouvrirLien(appareil);
  } catch (e) {
    // Échec d'un geste de l'utilisateur : pas de reconnexion automatique derrière son dos.
    etat.connexionVoulue = false;
    throw e;
  }
}

/** Coupe le lien voulu par l'utilisateur et retire l'attestation de ce téléphone. */
async function deconnecter() {
  etat.connexionVoulue = false;
  clearTimeout(etat.minuterieReconnexion);
  arreterAttestations();
  oublierLocal(CLE_APPAREIL);
  const retrait = retirerAttestation();    // avant la coupure : l'événement de déconnexion n'aura plus rien à retirer
  const appareil = etat.appareil;
  etat.connectees = false;
  etat.erreur = '';
  try { if (appareil && appareil.gatt && appareil.gatt.connected) appareil.gatt.disconnect(); } catch (e) { /* déjà coupé */ }
  notifier();
  await retrait;
  return statut();
}

// Page fermée : le lien Bluetooth tombe avec elle. On le dit à l'ordinateur tout de suite, par une
// requête qui survit à la fermeture, plutôt que de le laisser croire deux minutes et demie de trop.
window.addEventListener('pagehide', () => {
  if (!attestationRecente()) return;
  const api = apiIRIS();
  etat.attestation = { derniere: 0, acceptee: false, erreur: '' };
  if (!api || typeof api.jeton !== 'function') return;
  try {
    fetch(api.base + '/api/lunettes/attestation', {
      method: 'DELETE', headers: { Authorization: 'Bearer ' + api.jeton() }, keepalive: true, cache: 'no-store',
    }).catch(() => null);
  } catch (e) { /* navigateur ancien : l'ordinateur oubliera seul */ }
});
// Retour à l'écran : les minuteries ont pu dormir ; on confirme tout de suite si le lien tient encore.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  if (etat.connectees && Date.now() - etat.attestation.derniere > 20000) attester().catch(() => null);
  else if (!etat.connectees && etat.connexionVoulue && etat.appareil && !etat.connexionEnCours) {
    etat.essaiReconnexion = 0;
    planifierReconnexion();
  }
});
window.addEventListener('pageshow', (e) => {
  if (e && e.persisted && etat.connexionVoulue && etat.appareil && !etat.connectees && !etat.connexionEnCours) {
    etat.essaiReconnexion = 0;
    planifierReconnexion();
  }
});

/** Attend que la coquille ait fait admettre la session par l'ordinateur. Rend false après maxMs. */
async function attendreSession(maxMs) {
  const fin = Date.now() + maxMs;
  for (;;) {
    const e = typeof IRISv().etat === 'function' ? IRISv().etat() : null;
    // Coquille sans IRIS.etat (ancienne) : on ne peut pas savoir, on n'attend pas.
    if (!e || (e.pret && apiIRIS())) return !!apiIRIS();
    if (Date.now() >= fin) return false;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** Reprise après rechargement : seulement une paire déjà autorisée sur cette page, et si l'utilisateur ne l'a pas déconnectée. */
async function reprendreAuChargement() {
  if (!BLUETOOTH || typeof navigator.bluetooth.getDevices !== 'function') return;
  const id = memoireLocale(CLE_APPAREIL);
  if (!id) return;
  // La session doit être admise par l'ordinateur, sinon l'attestation déclencherait l'écran de connexion.
  if (!(await attendreSession(90000))) return;
  let appareils = [];
  try { appareils = await navigator.bluetooth.getDevices(); } catch (e) { return; }
  const appareil = (appareils || []).find((d) => d && d.id === id);
  if (!appareil || etat.connectees || etat.connexionEnCours) return;
  try { await ouvrirLien(appareil); } catch (e) {
    // Hors de portée au chargement : pas d'insistance ; le panneau propose « Connecter mes lunettes ».
    etat.connexionVoulue = false;
    etat.erreur = '';
    notifier();
  }
}

// ------------------------------------------------------------------ la garde des modules
/**
 * Garde « lunettes d'abord » d'un panneau de fonction.
 * options : {
 *   fonction: identifiant, libelle: complément « le guidage à pied », zone: élément à remplir (sinon ajouté en tête),
 *   contenu: élément de la fonction, caché tant que les lunettes ne sont pas confirmées,
 *   enCours: () => bool — une session en cours (trajet, partage) n'est pas coupée net,
 *   surAbsence(etat), surPresence(etat), noteSecours: phrase sur la caméra du téléphone en secours
 * }
 * Rend { verifier({depuisAction}) -> Promise<bool>, refus(err) -> bool, presentes() -> bool|null, fermer() }.
 */
function garde(ctx, options) {
  const o = options || {};
  const corps = ctx && ctx.corps;
  const zone = o.zone || el('div');
  if (!o.zone && corps) corps.prepend(zone);
  zone.setAttribute('data-garde-lunettes', o.fonction || '');
  const contenu = o.contenu || null;
  const libelle = o.libelle || 'cette fonction';   // complément : « le guidage à pied », « l'interprète »
  if (contenu) contenu.hidden = true;
  zone.textContent = '';
  zone.append(el('p', { class: 'note-faible', role: 'status' }, 'Vérification de vos lunettes VELA…'));

  let presentes = null;
  let affichage = '';        // present | absent | averti | injoignable
  let clePresent = '';       // ce qui est affiché en mode « présentes » : on ne redessine pas pour rien
  let ferme = false;
  let minuterieGrace = null;
  let minuterieSession = null;
  let sondage = null;

  function sourceLisible(d) {
    if (!d) return '';
    if (d.source === 'pc') return 'Lunettes VELA reliées à votre ordinateur.';
    if (d.source === 'telephone') {
      return etat.connectees && etat.attestation.acceptee ? 'Lunettes VELA connectées à ce téléphone.' : 'Lunettes VELA confirmées par votre téléphone.';
    }
    return '';
  }

  function montrerPresent(d) {
    const ligne = sourceLisible(d);
    if (affichage === 'present' && clePresent === ligne) { if (contenu) contenu.hidden = false; return; }
    affichage = 'present';
    clePresent = ligne;
    zone.textContent = '';
    if (ligne) zone.append(el('p', { class: 'note-faible' }, ligne));
    if (o.noteSecours) zone.append(el('p', { class: 'note' }, o.noteSecours));
    if (contenu) contenu.hidden = false;
  }

  function montrerAvertissement() {
    if (affichage === 'averti') return;
    affichage = 'averti';
    // Dès que la session se termine (trajet arrivé, partage arrêté), l'invitation remplace l'avertissement,
    // sans attendre le prochain sondage réseau (qui dort quand la page est en arrière-plan).
    clearInterval(minuterieSession);
    minuterieSession = setInterval(() => {
      if (ferme || affichage !== 'averti') { clearInterval(minuterieSession); return; }
      if (!sessionEnCours() && presentes === false) {
        clearInterval(minuterieSession);
        appliquer(etat.presence || { presentes: false }, false);
      }
    }, 1500);
    zone.textContent = '';
    zone.append(el('p', { class: 'resultat-erreur', role: 'alert' },
      'Vos lunettes VELA ne sont plus détectées. ' + (o.avertissementEnCours || 'La session en cours se termine normalement ; pour en commencer une autre, reconnectez-les.')));
    if (contenu) contenu.hidden = false;
  }

  function montrerAbsent(d, depuisAction) {
    const dejaAffiche = affichage === 'absent';
    affichage = 'absent';
    if (contenu) {
      // Le focus était peut-être sur un bouton qui disparaît : il ira sur le titre de l'invitation.
      contenu.hidden = true;
    }
    zone.textContent = '';
    const idTitre = 'garde-lunettes-' + Math.random().toString(36).slice(2, 8);
    const titre = el('h3', { id: idTitre, tabindex: '-1' }, 'Cette fonction marche avec les lunettes VELA');
    const carte = el('section', { class: 'carte', 'aria-labelledby': idTitre }, titre,
      el('p', { class: 'note' }, 'Pour utiliser ' + libelle + ', connectez vos lunettes VELA à ce téléphone ou à votre ordinateur.'));
    const probleme = el('p', { class: 'resultat-erreur', role: 'alert', hidden: true });
    if (etat.connectees && etat.attestation.erreur) {
      probleme.textContent = 'Vos lunettes sont connectées à ce téléphone, mais : ' + etat.attestation.erreur;
      probleme.hidden = false;
    }
    if (BLUETOOTH) {
      const connecterBouton = el('button', { type: 'button', class: 'holo' }, etat.connectees ? 'Confirmer mes lunettes' : 'Connecter mes lunettes');
      connecterBouton.addEventListener('click', async () => {
        connecterBouton.disabled = true;
        probleme.hidden = true;
        const libelleAvant = connecterBouton.textContent;
        connecterBouton.textContent = 'Connexion…';
        try {
          if (etat.connectees) await attester(); else await connecter();
          const ok = await verifier({ depuisAction: true });
          if (ok) { toast('Lunettes VELA connectées.', 'ok'); dire('Lunettes connectées.'); }
        } catch (e) {
          if (!ferme && document.contains(probleme)) {
            probleme.textContent = (e && e.message) || String(e);
            probleme.hidden = false;
          }
        } finally {
          if (document.contains(connecterBouton)) {
            connecterBouton.disabled = false;
            connecterBouton.textContent = libelleAvant;
          }
        }
      });
      carte.append(connecterBouton,
        el('p', { class: 'note-faible' }, 'Chrome affiche la liste des lunettes à proximité : choisissez les vôtres. Le son continue de passer par le Bluetooth audio du téléphone.'));
    } else {
      carte.append(el('p', { class: 'note' }, raisonIndisponible()));
    }
    const reverifier = el('button', { type: 'button', class: 'bouton-sombre' }, 'Vérifier de nouveau');
    reverifier.addEventListener('click', async () => {
      reverifier.disabled = true;
      try {
        const ok = await verifier({ depuisAction: true });
        if (!ok && document.contains(reverifier)) toast('Lunettes VELA toujours pas détectées.', 'info');
      } finally {
        if (document.contains(reverifier)) reverifier.disabled = false;
      }
    });
    const acheter = /^https:\/\//.test(String((d && d.acheter_url) || '')) ? d.acheter_url : URL_ACHAT_DEFAUT;
    const lien = el('a', { class: 'bouton-contour', href: acheter, target: '_blank', rel: 'noopener noreferrer' }, 'Acheter les lunettes');
    carte.append(probleme, el('div', { class: 'ligne' }, reverifier, lien));
    zone.append(carte);
    if (depuisAction && !dejaAffiche) {
      setTimeout(() => { try { titre.focus(); } catch (e) { /* rien */ } }, 30);
      dire("Cette fonction marche avec les lunettes VELA. Connectez vos lunettes pour l'utiliser.");
    }
  }

  function montrerInjoignable(err) {
    affichage = 'injoignable';
    if (contenu) contenu.hidden = true;
    zone.textContent = '';
    const message = err && err.status === 404
      ? "Votre ordinateur ne sait pas encore vérifier la présence des lunettes : mettez IRIS à jour sur l'ordinateur."
      : 'Impossible de vérifier vos lunettes VELA : ' + ((err && err.message) || "l'ordinateur ne répond pas.");
    const reessayer = el('button', { type: 'button', class: 'bouton-sombre' }, 'Réessayer');
    reessayer.addEventListener('click', () => { verifier({ depuisAction: true }); });
    zone.append(el('p', { class: 'resultat-erreur', role: 'alert' }, message), reessayer);
  }

  function sessionEnCours() {
    if (typeof o.enCours !== 'function') return false;
    try { return !!o.enCours(); } catch (e) { return false; }
  }

  /** ignorerSession : un refus de l'ordinateur (428) clôt l'action en cours, il n'y a plus rien à ménager. */
  function appliquer(d, depuisAction, ignorerSession) {
    if (ferme) return;
    const avant = presentes;
    presentes = !!(d && d.presentes);
    if (presentes) {
      clearTimeout(minuterieGrace);
      minuterieGrace = null;
      montrerPresent(d);
      if (avant === false && typeof o.surPresence === 'function') { try { o.surPresence(d); } catch (e) { /* module */ } }
      return;
    }
    if (!ignorerSession && sessionEnCours()) montrerAvertissement(); else montrerAbsent(d, depuisAction);
    // Prévenu seulement d'une PERTE : des lunettes absentes dès l'ouverture ne sont pas un événement.
    if (avant === true && typeof o.surAbsence === 'function') { try { o.surAbsence(d); } catch (e) { /* module */ } }
  }

  async function verifier(options2) {
    const v = options2 || {};
    // Présence confirmée il y a moins de cacheMs : pas d'aller-retour de plus avant un geste pressé
    // (« Où suis-je ? », « Je parle »). Le sondage de la garde et le 428 de l'ordinateur couvrent le reste.
    if (Number(v.cacheMs) > 0 && presentes === true && etat.presence && etat.presence.presentes &&
        Date.now() - etat.presenceA < Number(v.cacheMs)) {
      return true;
    }
    try {
      const d = await presence({ frais: true });
      if (!ferme) appliquer(d, !!v.depuisAction);
      return !!(d && d.presentes);
    } catch (err) {
      if (ferme) return false;
      // Ordinateur injoignable : les lunettes connectées à ce téléphone, ou une présence confirmée il y a
      // moins de 150 s (la durée qu'accorde l'ordinateur lui-même), valent encore.
      if (err && err.status === 0 && (preuveLocale() || presenceRecente())) {
        appliquer(Object.assign({}, etat.presence || {}, { presentes: true, source: preuveLocale() ? 'telephone' : (etat.presence || {}).source }), false);
        return true;
      }
      if (err && err.status === 401) {
        // Verrouillage ou session : la coquille affiche l'écran qui convient. Rien n'est permis d'ici là.
        affichage = 'injoignable';
        if (contenu) contenu.hidden = true;
        zone.textContent = '';
        zone.append(el('p', { class: 'resultat-erreur', role: 'alert' }, (err && err.message) || 'Accès refusé par votre ordinateur.'));
        presentes = null;
        return false;
      }
      montrerInjoignable(err);
      presentes = null;
      return false;
    }
  }

  /**
   * Une erreur 428 de l'ordinateur (lunettes requises) : invitation affichée, true. Toute autre erreur : false.
   * {garderContenu: true} : l'action refusée n'arrête pas une session en cours (prolonger un partage) ;
   * on prévient sans cacher le bouton d'arrêt.
   */
  function refus(err, options3) {
    if (!err || err.status !== 428) return false;
    const detail = err.detail && typeof err.detail === 'object' ? err.detail : {};
    if (detail.code && detail.code !== 'lunettes_requises') return false;
    const avant = presentes;
    retenirPresence(Object.assign({}, etat.presence || {}, { presentes: false, acheter_url: detail.acheter_url || (etat.presence || {}).acheter_url }));
    clearTimeout(minuterieGrace);        // l'ordinateur vient de trancher : pas de délai de grâce
    minuterieGrace = null;
    presentes = avant === null ? null : true;   // pour que la perte prévienne le module (surAbsence)
    appliquer(etat.presence, true, !(options3 && options3.garderContenu));
    return true;
  }

  function surChangement() {
    if (ferme || !etat.presence) return;
    const d = etat.presence;
    if (d.presentes) { appliquer(d, false); return; }
    if (presentes === null) { appliquer(d, false); return; }
    if (presentes === false) {
      // La session qui justifiait l'avertissement est finie : place à l'invitation.
      if (affichage === 'averti' && !sessionEnCours()) appliquer(d, false);
      return;
    }
    // Absence annoncée : confirmée après un délai de grâce, pour ne rien couper sur un changement passager.
    if (minuterieGrace) return;
    if (affichage === 'present') {
      // Ne plus affirmer « reliées » pendant la grâce : on dit qu'on revérifie.
      zone.textContent = '';
      zone.append(el('p', { class: 'note-faible', role: 'status' }, 'Vos lunettes VELA ne sont plus signalées : nouvelle vérification dans quelques secondes.'));
      clePresent = 'grace';   // forcera le redessin si elles reviennent
    }
    minuterieGrace = setTimeout(async () => {
      minuterieGrace = null;
      if (ferme) return;
      try {
        const frais = await presence({ frais: true });
        if (!ferme) appliquer(frais, false);
      } catch (e) {
        if (!ferme && !(preuveLocale() || presenceRecente())) appliquer({ presentes: false }, false);
      }
    }, GRACE_ABSENCE_MS);
  }
  const retirerEcouteur = on(() => {
    surChangement();
    // La ligne « connectées à ce téléphone / reliées à l'ordinateur » suit la connexion locale.
    if (!ferme && affichage === 'present' && etat.presence && etat.presence.presentes) montrerPresent(etat.presence);
  });

  function sonder() {
    if (ferme || document.hidden) return;
    presence({ frais: true }).then(() => surChangement()).catch((err) => {
      if (ferme || !err || err.status !== 0) return;
      if (presentes === true && !(preuveLocale() || presenceRecente())) surChangement();
    });
  }
  sondage = setInterval(sonder, SONDAGE_GARDE_MS);
  // Page ramenée à l'écran : le sondage dormait, la présence a pu changer entre-temps.
  const auRetour = () => { if (!document.hidden) sonder(); };
  document.addEventListener('visibilitychange', auRetour);

  verifier({ depuisAction: false });

  return {
    verifier,
    refus,
    presentes: () => presentes,
    etat: () => etat.presence,
    fermer() {
      ferme = true;
      clearTimeout(minuterieGrace);
      clearInterval(minuterieSession);
      clearInterval(sondage);
      document.removeEventListener('visibilitychange', auRetour);
      retirerEcouteur();
    },
  };
}

/** on(fonction) -> désabonnement : appelée à chaque changement de connexion ou de présence. */
function on(fonction) {
  if (typeof fonction !== 'function') return () => {};
  ecouteurs.add(fonction);
  return () => ecouteurs.delete(fonction);
}

// ------------------------------------------------------------------ le contrat
const LUNETTES = {
  get disponible() { return BLUETOOTH; },
  get connectees() { return etat.connectees; },
  get nom() { return etat.nom || (etat.presence && etat.presence.nom) || null; },
  ios: IOS,
  connecter,
  deconnecter,
  presence,
  garde,
  on,
  raisonIndisponible,
  statut,
};
window.IRIS = window.IRIS || {};
window.IRIS.lunettes = LUNETTES;

// ------------------------------------------------------------------ panneau « Mes lunettes »
function ouvrir(ctx) {
  const corps = ctx.corps;
  let ferme = false;

  corps.append(el('p', { class: 'note' },
    "Les fonctions d'IRIS sur ce téléphone (guidage, interprète, vision partagée, reçus et prix) s'utilisent avec vos lunettes VELA, " +
    'connectées à ce téléphone ou à votre ordinateur.'));

  const carteEtat = el('div', { class: 'resultat', role: 'status', 'aria-live': 'polite' });
  const etatTitre = el('p', { class: 'resultat-texte' }, 'Vérification…');
  const etatDetail = el('p', { class: 'note' });
  carteEtat.append(etatTitre, etatDetail);

  const carteTelephone = el('div', { class: 'carte' }, el('h3', {}, 'Sur ce téléphone'));
  const telephoneTexte = el('p', { class: 'note' });
  const telephoneErreur = el('p', { class: 'resultat-erreur', role: 'alert', hidden: true });
  const boutonConnecter = el('button', { type: 'button', class: 'holo' }, 'Connecter mes lunettes');
  const boutonDeconnecter = el('button', { type: 'button', class: 'bouton-contour', hidden: true }, 'Déconnecter de ce téléphone');
  carteTelephone.append(telephoneTexte, telephoneErreur);
  if (BLUETOOTH) carteTelephone.append(boutonConnecter, boutonDeconnecter);

  const lienAchat = el('a', { class: 'bouton-contour', href: URL_ACHAT_DEFAUT, target: '_blank', rel: 'noopener noreferrer', hidden: true }, 'Acheter les lunettes');
  const limites = el('details', { class: 'carte' }, el('summary', {}, 'Ce que fait cette connexion, et ce qu’elle ne fait pas'),
    el('ul', { class: 'liste-limites' },
      el('li', {}, "Elle sert à confirmer à votre ordinateur que vos lunettes sont là. Le nom et l'identifiant Bluetooth des lunettes lui sont envoyés, avec leur niveau de batterie quand elles le donnent ; rien d'autre."),
      el('li', {}, 'Le son ne passe pas par elle : il passe par le Bluetooth audio du téléphone, réglé dans les réglages du téléphone.'),
      el('li', {}, "La caméra des lunettes n'est pas pilotée depuis ce téléphone : quand une fonction a besoin d'une photo, elle est prise avec la caméra du téléphone."),
      el('li', {}, "Cette page doit rester ouverte : fermée, ou longtemps en arrière-plan, elle cesse de confirmer la présence, et l'ordinateur considère les lunettes absentes après environ deux minutes et demie."),
      el('li', {}, "Sur iPhone, Safari n'a pas de Bluetooth web : c'est l'app IRIS qui se connecte aux lunettes.")));

  corps.append(carteEtat, carteTelephone, lienAchat, limites);

  function dessiner() {
    if (ferme) return;
    const d = etat.presence;
    const s = statut();
    if (!d) {
      etatTitre.textContent = 'Vérification…';
      etatDetail.textContent = '';
    } else if (d.presentes) {
      if (d.source === 'pc') etatTitre.textContent = 'Vos lunettes sont reliées à votre ordinateur.';
      else if (d.source === 'telephone') etatTitre.textContent = s.connectees && s.attestation_acceptee ? 'Vos lunettes sont connectées à ce téléphone.' : 'Vos lunettes sont confirmées par votre téléphone.';
      else etatTitre.textContent = 'Les fonctions des lunettes sont disponibles.';
      etatDetail.textContent = d.nom && (d.source === 'pc' || d.source === 'telephone') ? 'Paire : ' + d.nom + '.' : '';
    } else {
      etatTitre.textContent = 'Vos lunettes VELA ne sont pas détectées.';
      etatDetail.textContent = 'Ni votre ordinateur ni un téléphone connecté ne les voit en ce moment.';
    }
    lienAchat.hidden = !(d && !d.presentes);
    if (d && /^https:\/\//.test(String(d.acheter_url || ''))) lienAchat.href = d.acheter_url;

    if (!BLUETOOTH) {
      telephoneTexte.textContent = raisonIndisponible();
      return;
    }
    const morceaux = [];
    if (s.connexion_en_cours) morceaux.push('Connexion Bluetooth en cours…');
    else if (s.connectees) {
      morceaux.push('Connectées à ce téléphone' + (s.nom ? ' : ' + s.nom : '') + '.');
      if (typeof s.batterie === 'number') morceaux.push('Batterie : ' + s.batterie + ' %.');
      if (s.attestation_acceptee && s.attestation_age_ms !== null) morceaux.push('Présence confirmée à votre ordinateur il y a ' + ilYA(s.attestation_age_ms) + '.');
    } else {
      morceaux.push('Pas de lunettes connectées à ce téléphone.');
    }
    telephoneTexte.textContent = morceaux.join(' ');
    const probleme = s.connectees ? s.attestation_erreur : s.erreur;
    telephoneErreur.textContent = probleme || '';
    telephoneErreur.hidden = !probleme;
    boutonConnecter.hidden = s.connectees;
    boutonConnecter.disabled = s.connexion_en_cours;
    boutonDeconnecter.hidden = !s.connectees;
  }

  boutonConnecter.addEventListener('click', async () => {
    boutonConnecter.disabled = true;
    telephoneErreur.hidden = true;
    try {
      await connecter();
      await presence({ frais: true }).catch(() => null);
      if (!ferme && etat.connectees) { toast('Lunettes VELA connectées à ce téléphone.', 'ok'); dire('Lunettes connectées.'); }
    } catch (e) {
      if (!ferme) {
        telephoneErreur.textContent = (e && e.message) || String(e);
        telephoneErreur.hidden = false;
      }
    } finally {
      if (!ferme) { boutonConnecter.disabled = false; dessiner(); }
    }
  });
  boutonDeconnecter.addEventListener('click', async () => {
    boutonDeconnecter.disabled = true;
    try {
      await deconnecter();
      await presence({ frais: true }).catch(() => null);
      if (!ferme) toast('Lunettes déconnectées de ce téléphone.', 'info');
    } finally {
      if (!ferme) { boutonDeconnecter.disabled = false; dessiner(); }
    }
  });

  const retirer = on(dessiner);
  const minuterie = setInterval(() => {
    if (document.hidden) return;
    presence({ frais: true }).catch(() => null).then(dessiner);
  }, 15000);
  const horloge = setInterval(dessiner, 5000);
  presence({ frais: true }).then(dessiner).catch((err) => {
    if (ferme) return;
    etatTitre.textContent = err && err.status === 404
      ? "Votre ordinateur ne sait pas encore vérifier la présence des lunettes : mettez IRIS à jour sur l'ordinateur."
      : 'Présence des lunettes inconnue : ' + ((err && err.message) || "l'ordinateur ne répond pas.");
    dessiner();
  });
  dessiner();

  const nettoyer = () => {
    if (ferme) return;
    ferme = true;
    retirer();
    clearInterval(minuterie);
    clearInterval(horloge);
  };
  if (typeof ctx.surFermeture === 'function') ctx.surFermeture(nettoyer);
  corps.addEventListener('iris:fermeture', nettoyer, { once: true });
  return nettoyer;
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<circle cx="6.5" cy="14" r="3.5"/><circle cx="17.5" cy="14" r="3.5"/><path d="M10 14c.7-.8 3.3-.8 4 0"/><path d="M3 14 4.5 7.5h2M21 14l-1.5-6.5h-2"/></svg>';

const MODULE = {
  id: 'lunettes',
  titre: 'Mes lunettes',
  sous_titre: 'Connexion et présence',
  icone: ICONE,
  ordre: 5,
  ouvrir,
};

function quandIRISPret(rappel) {
  const pret = () => window.IRIS && typeof window.IRIS.enregistrer === 'function' && window.IRIS.api;
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
quandIRISPret((IRIS) => {
  IRIS.lunettes = LUNETTES;   // la coquille a pu recréer l'objet : on s'y rattache
  IRIS.enregistrer(MODULE);
  if (IRIS.bus && typeof IRIS.bus.on === 'function') {
    IRIS.bus.on('lunettes.presence', retenirPresence);
    // Reconnecté à l'ordinateur : la présence a pu changer pendant la coupure.
    IRIS.bus.on('iris.ws', (ev) => { if (ev && ev.ouvert) presence({ frais: true }).catch(() => null); });
  }
  attendreSession(90000).then((ok) => { if (ok) presence({ frais: true }).catch(() => null); });
  reprendreAuChargement().catch(() => null);
});
