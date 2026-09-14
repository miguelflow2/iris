/* IRIS — vision partagée depuis la caméra du téléphone.
 *
 * Le scénario : dehors, une personne malvoyante veut qu'un proche voie ce qu'elle a devant elle. Les
 * lunettes n'envoient pas de vidéo ; le téléphone, lui, a une caméra. L'ordinateur crée la session sur
 * le relais VELA (il détient le jeton d'appareil) et rend à ce téléphone un jeton émetteur ; le
 * téléphone envoie ensuite ses images DIRECTEMENT au relais, sans passer par l'ordinateur : c'est
 * plus rapide, et l'ordinateur ne voit pas ces images. Le proche ouvre le lien /voir/<code>.
 *
 * Ce que le module mesure et dit, sans rien promettre : images JPEG d'environ 960 px, 1 à 5 par
 * seconde selon le réseau (la cadence baisse dès que le tampon d'envoi grossit, remonte quand il se
 * vide), cadence réellement reçue par le relais, nombre de personnes qui regardent, données envoyées
 * (sur un forfait mobile, ça compte). Rien n'est enregistré, ni ici, ni sur le relais.
 *
 * Règles de confiance : caméra ouverte AVANT de créer le lien (un refus de caméra ne laisse pas de lien
 * orphelin) ; tout s'arrête quand on ferme le panneau ; l'ordinateur garde le dernier mot (mode
 * confidentiel, consentement retiré, verrouillage : il ferme la session, et ce téléphone s'arrête).
 *
 * Lunettes d'abord : la vision partagée est une fonction des lunettes VELA. Un partage ne démarre (et ne
 * se prolonge) que si les lunettes sont détectées (lunettes.js). La caméra du téléphone ne sert qu'en
 * SECOURS, et l'écran le dit : la commande photo des lunettes n'est pas encore confirmée sur le vrai
 * matériel, et elles n'envoient de toute façon pas de vidéo. Un partage en cours n'est pas coupé net
 * si les lunettes disparaissent (le proche aide peut-être à ce moment précis) : on prévient, il va
 * jusqu'à son expiration, sans prolongation. Arrêter un partage reste toujours possible.
 */

const NIVEAUX = [
  // Du plus riche au plus léger. On démarre au deuxième : 960 px, 4 images par seconde.
  { cote: 960, qualite: 0.7, ips: 5 },
  { cote: 960, qualite: 0.6, ips: 4 },
  { cote: 800, qualite: 0.55, ips: 3 },
  { cote: 640, qualite: 0.5, ips: 2 },
  { cote: 480, qualite: 0.45, ips: 1 },
];
const NIVEAU_DEPART = 1;
const TAILLE_MAX = 290000;              // octets : sous la borne du relais (300 Ko)
const TAMPON_ENCOMBRE = 150000;         // octets en attente d'envoi : le réseau ne suit plus
const BAISSE_MIN_MS = 2000;
const HAUSSE_APRES_MS = 8000;
const PREAVIS_EXPIRATION_S = 120;
const DELAI_PRET_MS = 15000;
const RECONNEXIONS_MAX = 6;
const FERMETURES_DEFINITIVES = [4000, 4003, 4004, 4010];
const LIBELLES_SOURCES = { ecran: "l'écran de l'ordinateur", lunettes: 'la caméra des lunettes', telephone: 'un téléphone' };

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
const IRISv = () => window.IRIS || {};

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

function toast(texte, genre) { const ui = IRISv().ui; if (ui && typeof ui.toast === 'function') ui.toast(texte, genre); }
function lectureAuto() { try { return localStorage.getItem('iris_lecture_auto') !== 'non'; } catch (e) { return true; } }
function dire(texte) {
  const voix = IRISv().voix;
  if (!texte || !lectureAuto() || !voix || typeof voix.parler !== 'function') return;
  try { Promise.resolve(voix.parler(texte)).catch(() => false); } catch (e) { /* voix indisponible */ }
}
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
    if (voulu) { document.addEventListener('visibilitychange', auRetour); return verrou ? true : demander(); }
    document.removeEventListener('visibilitychange', auRetour);
    if (verrou) { try { await verrou.release(); } catch (e) { /* déjà libéré */ } verrou = null; }
    return false;
  };
}
const nombreFr = (n, d) => Number(n).toLocaleString('fr-CA', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 });
function mo(octets) { return nombreFr((Number(octets) || 0) / 1e6, 1) + ' Mo'; }
function codeLisible(code) { const c = String(code || ''); return c.length === 8 ? c.slice(0, 4) + ' ' + c.slice(4) : c; }
function codeEpele(code) { return String(code || '').split('').join(', '); }
function minutesSecondes(s) {
  const t = Math.max(0, Math.round(Number(s) || 0));
  return Math.floor(t / 60) + ' min ' + String(t % 60).padStart(2, '0') + ' s';
}

function cameraPossible() { return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia); }
function raisonSansCamera() {
  if (!window.isSecureContext) {
    return "La caméra n'est accessible qu'à une page sécurisée (adresse en https). Ouvrez IRIS par l'adresse de votre réseau privé.";
  }
  return "Ce navigateur ne donne pas accès à la caméra depuis une page web.";
}
function messageCamera(e) {
  const nom = (e && e.name) || '';
  if (nom === 'NotAllowedError' || nom === 'SecurityError') {
    return "Caméra refusée pour cette page. Sur iPhone : Réglages › Safari › Appareil photo, puis rouvrez ce panneau.";
  }
  if (nom === 'NotFoundError' || nom === 'OverconstrainedError') return "Aucune caméra utilisable n'a été trouvée sur ce téléphone.";
  if (nom === 'NotReadableError' || nom === 'AbortError') return "La caméra est occupée par une autre application : fermez-la, puis réessayez.";
  return "La caméra n'a pas pu démarrer sur ce téléphone.";
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const IRIS = IRISv();
  const api = IRIS.api;
  const bus = IRIS.bus;
  const eveil = fabriquerEveil('partage');

  let phase = 'repos';                 // repos | demarrage | actif
  let session = null;                  // {code, url, jeton, ws, expireFin}
  let flux = null;                     // MediaStream de la caméra
  let socket = null;
  let reconnexions = 0;
  let minuterieReconnexion = null;
  let minuterieEmission = null;
  let minuterieHorloge = null;
  let minuteriePing = null;
  let niveau = NIVEAU_DEPART;
  let derniereBaisse = 0;
  let calmeDepuis = Date.now();
  let captureEnCours = false;
  let imagesEnvoyees = 0;
  let octetsEnvoyes = 0;
  let debutEmission = 0;
  let spectateurs = 0;
  let fpsRelais = null;
  let preavisDit = false;
  let arretVoulu = false;
  let ferme = false;
  const messagesLus = new Map();       // texte -> instant où la coquille l'a reçu (elle le lit déjà)
  const toile = document.createElement('canvas');

  corps.append(
    el('p', { class: 'note' },
      "Un proche voit ce que vous avez devant vous, par un lien à lui envoyer. Les images partent directement de ce téléphone " +
      "vers le relais VELA ; votre ordinateur crée le lien et suit le partage, mais ne reçoit pas les images."),
    el('p', { class: 'note-faible' },
      "Ce n'est pas une vidéo en direct : quelques images par seconde, avec du retard. Ce partage ne remplace pas une aide sur place pour traverser une rue, un escalier ou un danger immédiat."));

  const apercu = el('video', { playsinline: true, muted: true, autoplay: true, 'aria-label': 'Aperçu de la caméra arrière, tel que votre proche le voit', hidden: true });
  apercu.muted = true;
  apercu.setAttribute('webkit-playsinline', '');
  apercu.style.width = '100%';
  apercu.style.borderRadius = '20px';
  apercu.style.background = '#000000';
  apercu.style.maxHeight = '45vh';
  apercu.style.objectFit = 'contain';

  const temoin = el('p', { class: 'badge', hidden: true }, 'Caméra en marche : les images partent vers le relais VELA');
  temoin.style.background = '#b3261e';
  const etat = el('div', { class: 'resultat', role: 'status', 'aria-live': 'polite' });
  const etatTitre = el('p', { class: 'resultat-texte' }, 'Vérification…');
  const etatDetail = el('p', { class: 'note' });
  etat.append(etatTitre, etatDetail);

  const demarrer = el('button', { type: 'button', class: 'holo' }, 'Démarrer le partage');
  const zoneCode = el('div', { class: 'carte', hidden: true });
  const codeGrand = el('p', {});
  codeGrand.style.fontSize = '2.4rem';
  codeGrand.style.fontWeight = '700';
  codeGrand.style.letterSpacing = '0.08em';
  codeGrand.style.textAlign = 'center';
  const lien = el('p', { class: 'note-faible' });
  lien.style.overflowWrap = 'anywhere';
  const partager = el('button', { type: 'button', class: 'holo blanc' }, 'Envoyer le lien');
  const direCode = el('button', { type: 'button', class: 'bouton-sombre' }, 'Dire le code');
  const prolonger = el('button', { type: 'button', class: 'bouton-sombre' }, 'Prolonger de 30 min');
  zoneCode.append(el('h3', {}, 'À donner à votre proche'), el('p', { class: 'etiquette' }, 'Code du partage'), codeGrand, lien, partager,
    el('div', { class: 'ligne' }, direCode, prolonger));

  const arreter = el('button', { type: 'button', class: 'holo rouge', hidden: true }, 'Arrêter le partage');
  const relancerCamera = el('button', { type: 'button', class: 'bouton-sombre', hidden: true }, 'Relancer la caméra');
  const messages = el('ul', { class: 'souvenirs' });
  const zoneMessages = el('div', { class: 'carte', hidden: true }, el('h3', {}, 'Messages de votre proche'), messages);
  const annonceMessages = el('p', { class: 'invisible', 'aria-live': 'assertive' });
  // Limites propres au téléphone, puis celles que l'ordinateur donne pour tout partage (partage.LIMITES).
  const limites = el('ul', { class: 'liste-limites' },
    el('li', {}, "L'écran doit rester allumé et cette page ouverte : sur iPhone, une page en arrière-plan n'envoie plus rien."),
    el('li', {}, "Le partage utilise les données mobiles de ce téléphone : la quantité réellement envoyée est affichée pendant le partage."),
    el('li', {}, "Un partage ne démarre et ne se prolonge qu'avec vos lunettes VELA détectées. S'il est en cours quand elles disparaissent, il continue jusqu'à son expiration (au plus 30 minutes après le démarrage ou la dernière prolongation), puis s'arrête."),
    el('li', {}, "Les images viennent de la caméra de ce téléphone, pas de celle des lunettes : leur commande photo n'est pas encore confirmée sur le vrai matériel."),
    el('li', {}, 'Fermer ce panneau arrête le partage.'));
  const limitesServeur = el('ul', { class: 'liste-limites' });
  const detailsLimites = el('details', { class: 'carte' }, el('summary', {}, 'Limites du partage'), limites, limitesServeur);
  function afficherLimitesServeur(liste) {
    if (!Array.isArray(liste) || !liste.length) return;
    limitesServeur.textContent = '';
    liste.forEach((t) => limitesServeur.append(el('li', {}, String(t))));
  }

  // Lunettes : invitation à les connecter tant qu'elles manquent ; la fonction reste cachée d'ici là.
  // L'avis d'un partage déjà lancé depuis l'ordinateur reste hors de la garde : l'arrêter est toujours permis.
  const zoneGarde = el('div');
  const zoneFonction = el('div');
  zoneFonction.hidden = true;
  const carteExistant = el('div', { class: 'carte', role: 'status', hidden: true });
  zoneFonction.append(temoin, apercu, etat, demarrer, zoneCode, arreter, relancerCamera, zoneMessages, annonceMessages);
  corps.append(zoneGarde, zoneFonction, carteExistant, detailsLimites);
  let gardeActive = null;
  let verificationLunettes = false;
  const gardePrete = gardeLunettes(ctx, {
    fonction: 'partage',
    libelle: 'la vision partagée',
    zone: zoneGarde,
    contenu: zoneFonction,
    noteSecours: 'La caméra des lunettes arrive ; en attendant, les images viennent de la caméra arrière de ce téléphone.',
    enCours: () => phase !== 'repos',
    avertissementEnCours: "Le partage en cours continue jusqu'à son expiration, sans prolongation possible ; vous pouvez l'arrêter à tout moment.",
    surAbsence: () => {
      if (phase !== 'actif') return;
      const t = "Vos lunettes VELA ne sont plus détectées. Le partage continue jusqu'à son expiration, sans prolongation possible.";
      toast(t, 'alerte');
      dire(t);
    },
  }).then((g) => { gardeActive = g; if (ferme) g.fermer(); return g; });
  async function lunettesOk() {
    const g = await gardePrete;
    return g.verifier({ depuisAction: true, cacheMs: 20000 });
  }

  if (!api) {
    etatTitre.textContent = 'La liaison avec votre ordinateur n’est pas prête : fermez puis rouvrez ce panneau.';
    demarrer.disabled = true;
    return brancherNettoyage(ctx, () => { ferme = true; gardePrete.then((g) => g.fermer()).catch(() => null); });
  }
  if (!cameraPossible()) {
    etatTitre.textContent = raisonSansCamera();
    demarrer.disabled = true;
  }

  // ---- affichage
  function dessiner() {
    const actif = phase === 'actif';
    demarrer.hidden = phase !== 'repos';
    arreter.hidden = phase === 'repos';
    zoneCode.hidden = !(actif && session);
    temoin.hidden = !flux;
    apercu.hidden = !flux;
    if (actif && session) {
      codeGrand.textContent = codeLisible(session.code);
      lien.textContent = session.url;
      const reste = Math.max(0, (session.expireFin - Date.now()) / 1000);
      const ouvert = socket && socket.readyState === 1;
      etatTitre.textContent = !ouvert
        ? 'Partage en pause : connexion au relais perdue, nouvel essai…'
        : spectateurs > 0
          ? 'Partage en cours : ' + spectateurs + (spectateurs > 1 ? ' personnes regardent.' : ' personne regarde.')
          : 'Partage en cours : personne ne regarde encore.';
      const n = NIVEAUX[niveau];
      const duree = debutEmission ? (Date.now() - debutEmission) / 60000 : 0;
      const morceaux = [
        fpsRelais !== null ? nombreFr(fpsRelais, 1) + ' image(s) par seconde reçue(s) par le relais (mesure)' : 'cadence en cours de mesure',
        'réglage actuel : ' + n.cote + ' px, ' + n.ips + ' par seconde au plus',
        imagesEnvoyees + ' images envoyées, ' + mo(octetsEnvoyes) + (duree >= 0.5 ? ' (≈ ' + mo(octetsEnvoyes / duree) + ' par minute)' : ''),
        'expire dans ' + minutesSecondes(reste),
      ];
      etatDetail.textContent = morceaux.join(' · ') + '.';
    } else if (phase === 'demarrage') {
      etatTitre.textContent = 'Démarrage du partage…';
    }
  }

  // ---- caméra
  async function ouvrirCamera() {
    const nouveau = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 15, max: 30 } },
    });
    fermerCamera();
    flux = nouveau;
    apercu.srcObject = flux;
    try { await apercu.play(); } catch (e) { /* muet et en ligne : la lecture reprend seule */ }
    flux.getVideoTracks().forEach((piste) => {
      piste.addEventListener('ended', () => {
        if (phase === 'actif' && !ferme) {
          relancerCamera.hidden = false;
          toast("La caméra s'est arrêtée (page mise en arrière-plan ?). Touchez « Relancer la caméra ».", 'alerte');
        }
      });
    });
    relancerCamera.hidden = true;
  }
  function fermerCamera() {
    if (flux) {
      flux.getTracks().forEach((piste) => { try { piste.stop(); } catch (e) { /* déjà arrêtée */ } });
    }
    flux = null;
    try { apercu.srcObject = null; } catch (e) { /* vieux navigateur */ }
  }
  function cameraVivante() {
    return !!(flux && flux.getVideoTracks().some((p) => p.readyState === 'live'));
  }
  relancerCamera.addEventListener('click', async () => {
    try { await ouvrirCamera(); toast('Caméra relancée.', 'ok'); dessiner(); } catch (e) { toast(messageCamera(e), 'erreur'); }
  });

  // ---- images
  function capturer(n) {
    return new Promise((resoudre) => {
      const largeur = apercu.videoWidth;
      const hauteur = apercu.videoHeight;
      if (!largeur || !hauteur || apercu.readyState < 2) { resoudre(null); return; }
      const echelle = Math.min(1, n.cote / Math.max(largeur, hauteur));
      toile.width = Math.max(1, Math.round(largeur * echelle));
      toile.height = Math.max(1, Math.round(hauteur * echelle));
      try {
        toile.getContext('2d').drawImage(apercu, 0, 0, toile.width, toile.height);
      } catch (e) { resoudre(null); return; }
      if (typeof toile.toBlob === 'function') {
        toile.toBlob((b) => resoudre(b), 'image/jpeg', n.qualite);
        return;
      }
      try {
        const donnees = toile.toDataURL('image/jpeg', n.qualite);
        const binaire = atob(donnees.slice(donnees.indexOf(',') + 1));
        const octets = new Uint8Array(binaire.length);
        for (let i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
        resoudre(new Blob([octets], { type: 'image/jpeg' }));
      } catch (e) { resoudre(null); }
    });
  }

  function baisser() {
    const maintenant = Date.now();
    calmeDepuis = maintenant;
    if (niveau < NIVEAUX.length - 1 && maintenant - derniereBaisse >= BAISSE_MIN_MS) {
      niveau += 1;
      derniereBaisse = maintenant;
    }
  }

  function planifier(ms) {
    clearTimeout(minuterieEmission);
    if (phase !== 'actif' || ferme) return;
    minuterieEmission = setTimeout(emettre, ms);
  }

  async function emettre() {
    if (phase !== 'actif' || ferme) return;
    const n = NIVEAUX[niveau];
    const periode = Math.round(1000 / n.ips);
    if (document.hidden || captureEnCours || !socket || socket.readyState !== 1 || !cameraVivante()) { planifier(Math.max(periode, 500)); return; }
    if (socket.bufferedAmount > TAMPON_ENCOMBRE) {
      baisser();                          // le réseau ne suit plus : on saute cette image et on allège
      planifier(periode);
      return;
    }
    if (socket.bufferedAmount === 0 && niveau > 0 && Date.now() - calmeDepuis >= HAUSSE_APRES_MS) {
      niveau -= 1;
      calmeDepuis = Date.now();
    }
    captureEnCours = true;
    const debut = performance.now();
    try {
      const image = await capturer(n);
      if (image && phase === 'actif' && socket && socket.readyState === 1) {
        if (image.size > TAILLE_MAX) {
          baisser();                        // scène très détaillée : on allège avant d'envoyer
        } else {
          const donnees = typeof image.arrayBuffer === 'function' ? await image.arrayBuffer() : image;
          socket.send(donnees);
          imagesEnvoyees += 1;
          octetsEnvoyes += image.size;
          if (!debutEmission) debutEmission = Date.now();
        }
      }
    } catch (e) {
      // Une image ratée n'arrête pas le partage : la suivante réessaie.
    } finally {
      captureEnCours = false;
    }
    planifier(Math.max(0, periode - (performance.now() - debut)));
  }

  // ---- relais
  function traiter(message) {
    if (!message || typeof message !== 'object') return;
    if (typeof message.expire_dans_s === 'number' && session) {
      const fin = Date.now() + Math.max(0, message.expire_dans_s) * 1000;
      if (fin > session.expireFin + 60000) preavisDit = false;   // prolongé : on pourra prévenir de nouveau
      session.expireFin = fin;
    }
    switch (message.type) {
      case 'pret':
        spectateurs = Number(message.spectateurs) || 0;
        break;
      case 'stats':
        spectateurs = Number(message.spectateurs) || 0;
        fpsRelais = Number(message.fps_reel) || 0;
        break;
      case 'spectateurs': {
        const nombre = Number(message.nombre) || 0;
        const arrivee = nombre > spectateurs;
        spectateurs = nombre;
        const reglages = typeof IRIS.reglages === 'function' ? IRIS.reglages() : {};
        if (arrivee && reglages.annonce_capture !== false) {
          // Savoir qu'on est regardé fait partie de la confiance : on le dit à chaque arrivée.
          const t = 'Une personne regarde maintenant votre partage.';
          toast(t, 'info');
          dire(t);
        }
        break;
      }
      case 'message':
        recevoirMessage(String(message.texte || ''), true);
        break;
      case 'refus':
        if (message.raison === 'taille' || message.raison === 'debit') baisser();
        break;
      case 'fin':
        terminer(message.message || 'Le partage est terminé.', false);
        return;
      default:
        break;
    }
    dessiner();
  }

  function recevoirMessage(texte, duRelais) {
    const propre = texte.trim();
    if (!propre) return;
    const deja = messagesLus.get(propre);
    if (duRelais) {
      messages.append(el('li', {}, el('time', {}, new Date().toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })), propre));
      while (messages.children.length > 20) messages.firstElementChild.remove();
      zoneMessages.hidden = false;
      if (deja && Date.now() - deja < 30000) return;    // la coquille l'a déjà lu (événement de l'ordinateur)
      // L'ordinateur relaie aussi ce message, et la coquille le lit : on lui laisse quatre secondes
      // pour éviter une double lecture ; sans liaison en direct avec l'ordinateur, on lit tout de suite.
      const lire = () => {
        const vu = messagesLus.get(propre);
        if (vu && Date.now() - vu < 30000) return;
        messagesLus.set(propre, Date.now());
        const phrase = 'Message de votre proche : ' + propre;
        if (lectureAuto()) dire(phrase);
        else { annonceMessages.textContent = ''; setTimeout(() => { annonceMessages.textContent = phrase; }, 60); }
      };
      const evenements = api && typeof api.evenementsOuverts === 'function' && api.evenementsOuverts();
      if (evenements) setTimeout(lire, 4000); else lire();
    }
  }

  function brancher(ws) {
    ws.onmessage = (m) => {
      if (typeof m.data !== 'string') return;
      let message = null;
      try { message = JSON.parse(m.data); } catch (e) { return; }
      traiter(message);
    };
    ws.onclose = (e) => {
      if (socket === ws) socket = null;
      if (phase !== 'actif' || arretVoulu || ferme) return;
      if (FERMETURES_DEFINITIVES.indexOf(e && e.code) !== -1) {
        terminer(e.code === 4000 ? 'Un autre appareil émet maintenant pour ce partage : ce téléphone a cessé d’envoyer ses images.'
          : 'Le relais VELA a fermé ce partage (expiré ou arrêté).', false);
        return;
      }
      dessiner();
      planifierReconnexion();
    };
    ws.onerror = () => { /* onclose suit */ };
  }

  function connecter() {
    return new Promise((resoudre, rejeter) => {
      let ws;
      try { ws = new WebSocket(session.ws); } catch (e) {
        rejeter(new Error("Ce téléphone refuse de joindre le relais VELA depuis cette page."));
        return;
      }
      ws.binaryType = 'arraybuffer';
      let pret = false;
      const garde = setTimeout(() => {
        if (pret) return;
        try { ws.close(); } catch (e) { /* déjà fermé */ }
        rejeter(new Error('Le relais VELA ne répond pas. Vérifiez les données mobiles de ce téléphone.'));
      }, DELAI_PRET_MS);
      ws.onopen = () => {
        // Le jeton part dans le premier message, jamais dans l'adresse : il n'apparaît dans aucun journal.
        try { ws.send(JSON.stringify({ type: 'hello', jeton: session.jeton, role: 'emetteur', source: 'telephone' })); } catch (e) { /* onclose suivra */ }
      };
      ws.onmessage = (m) => {
        if (pret || typeof m.data !== 'string') return;
        let message = null;
        try { message = JSON.parse(m.data); } catch (e) { return; }
        if (message && message.type === 'pret') {
          pret = true;
          clearTimeout(garde);
          socket = ws;
          brancher(ws);
          traiter(message);
          resoudre(ws);
        } else if (message && (message.type === 'refus' || message.type === 'fin')) {
          clearTimeout(garde);
          const err = new Error(message.message || 'Partage introuvable ou expiré.');
          err.definitif = true;
          rejeter(err);
        }
      };
      ws.onclose = (e) => {
        if (pret) return;
        clearTimeout(garde);
        const err = new Error('Connexion au relais VELA impossible.');
        err.definitif = FERMETURES_DEFINITIVES.indexOf(e && e.code) !== -1;
        rejeter(err);
      };
      ws.onerror = () => { /* onclose suit */ };
    });
  }

  function planifierReconnexion() {
    clearTimeout(minuterieReconnexion);
    if (phase !== 'actif' || ferme || arretVoulu) return;
    if (session && Date.now() >= session.expireFin) { terminer('Le partage a expiré : 30 minutes sont passées sans prolongation.', false); return; }
    if (reconnexions >= RECONNEXIONS_MAX) {
      terminer('Connexion au relais VELA perdue trop longtemps : le partage est arrêté. Démarrez-en un nouveau quand le réseau revient.', true);
      return;
    }
    const delai = Math.min(15000, 1000 * Math.pow(2, reconnexions));
    minuterieReconnexion = setTimeout(async () => {
      if (phase !== 'actif' || ferme) return;
      // Page en arrière-plan : on n'use pas les essais ; le retour à l'écran relance la connexion.
      if (document.hidden) return;
      reconnexions += 1;
      try {
        await connecter();
        reconnexions = 0;
        toast('Connexion au relais rétablie : le partage reprend.', 'ok');
        dessiner();
      } catch (err) {
        if (err && err.definitif) terminer(err.message, true);
        else planifierReconnexion();
      }
    }, delai);
  }

  // ---- démarrer, prolonger, arrêter
  demarrer.addEventListener('click', async () => {
    if (phase !== 'repos' || !cameraPossible() || verificationLunettes) return;
    verificationLunettes = true;
    demarrer.disabled = true;
    let lunettes = false;
    try { lunettes = await lunettesOk(); } finally {
      verificationLunettes = false;
      demarrer.disabled = !cameraPossible();
    }
    if (!lunettes || ferme || phase !== 'repos') return;
    phase = 'demarrage';
    arretVoulu = false;
    demarrer.disabled = true;
    dessiner();
    etatDetail.textContent = 'Ouverture de la caméra…';
    try {
      await ouvrirCamera();
    } catch (e) {
      phase = 'repos';
      demarrer.disabled = false;
      etatTitre.textContent = messageCamera(e);
      etatDetail.textContent = '';
      dessiner();
      dire(messageCamera(e));
      return;
    }
    if (ferme) { fermerCamera(); return; }
    dessiner();
    etatDetail.textContent = 'Création du lien par votre ordinateur…';
    let r;
    try {
      r = await api.post('/api/partage/demarrer', { source: 'telephone' }, { delai: 45000 });
    } catch (err) {
      fermerCamera();
      phase = 'repos';
      demarrer.disabled = false;
      if (gardeActive && gardeActive.refus(err)) {   // 428 : l'ordinateur ne voit pas les lunettes
        etatTitre.textContent = '';
        etatDetail.textContent = '';
        dessiner();
        return;
      }
      etatTitre.textContent = (err && err.message) || String(err);
      etatDetail.textContent = err && err.code === 'consentement' ? "Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité." : '';
      dessiner();
      dire(err && err.message);
      return;
    }
    if (!r || !r.jeton_emetteur || !r.ws_emetteur) {
      fermerCamera();
      phase = 'repos';
      demarrer.disabled = false;
      etatTitre.textContent = "Votre ordinateur n'a pas rendu d'accès émetteur pour ce téléphone : mettez IRIS à jour.";
      api.post('/api/partage/arreter').catch(() => null);
      dessiner();
      return;
    }
    session = {
      code: r.code, url: r.url_spectateur, jeton: r.jeton_emetteur, ws: r.ws_emetteur,
      expireFin: Date.now() + (Number(r.expire_dans_s) || 1800) * 1000,
    };
    afficherLimitesServeur(r.limites);
    if (ferme) { terminer(null, true); return; }
    etatDetail.textContent = 'Connexion au relais VELA…';
    try {
      await connecter();
    } catch (err) {
      const message = (err && err.message) || String(err);
      terminer(null, true);
      etatTitre.textContent = message;
      dire(message);
      return;
    }
    if (ferme) { terminer(null, true); return; }
    phase = 'actif';
    reconnexions = 0;
    niveau = NIVEAU_DEPART;
    imagesEnvoyees = 0;
    octetsEnvoyes = 0;
    debutEmission = 0;
    preavisDit = false;
    demarrer.disabled = false;
    const allume = await eveil(true);
    if (!allume) toast("Ce téléphone refuse de garder l'écran allumé depuis cette page : réglez le verrouillage automatique pour éviter une coupure.", 'alerte');
    minuterieHorloge = setInterval(horloge, 1000);
    minuteriePing = setInterval(() => {
      if (socket && socket.readyState === 1) { try { socket.send(JSON.stringify({ type: 'ping' })); } catch (e) { /* onclose suivra */ } }
    }, 20000);
    dessiner();
    const phrase = 'Partage démarré. Code : ' + codeEpele(session.code) + '. Envoyez le lien à votre proche.';
    dire(phrase);
    emettre();
    try { partager.focus(); } catch (e) { /* rien */ }
  });

  function horloge() {
    if (phase !== 'actif' || !session) return;
    const reste = (session.expireFin - Date.now()) / 1000;
    if (reste <= 0) { terminer('Le partage a expiré : 30 minutes sont passées sans prolongation.', true); return; }
    if (reste <= PREAVIS_EXPIRATION_S && !preavisDit) {
      preavisDit = true;
      const t = 'Le partage se termine dans deux minutes. Touchez « Prolonger » pour le garder.';
      toast(t, 'alerte');
      dire(t);
    }
    dessiner();
  }

  prolonger.addEventListener('click', async () => {
    if (phase !== 'actif') return;
    prolonger.disabled = true;
    try {
      if (!(await lunettesOk())) {
        toast('Prolongation impossible : vos lunettes VELA ne sont pas détectées.', 'alerte');
        return;
      }
      const e = await api.post('/api/partage/prolonger');
      if (e && typeof e.expire_dans_s === 'number' && session) session.expireFin = Date.now() + e.expire_dans_s * 1000;
      preavisDit = false;
      toast('Partage prolongé de 30 minutes.', 'ok');
    } catch (err) {
      if (gardeActive && gardeActive.refus(err, { garderContenu: true })) {
        toast('Prolongation impossible : vos lunettes VELA ne sont pas détectées.', 'alerte');
      } else if (err && err.status === 0 && socket && socket.readyState === 1) {
        // Ordinateur injoignable : le relais accepte aussi la prolongation de l'émetteur lui-même.
        try { socket.send(JSON.stringify({ type: 'renouveler' })); toast('Prolongation demandée directement au relais.', 'info'); } catch (e) { toast(err.message, 'erreur'); }
      } else {
        toast((err && err.message) || String(err), 'erreur');
      }
    } finally {
      prolonger.disabled = false;
      dessiner();
    }
  });

  partager.addEventListener('click', async () => {
    if (!session) return;
    const texte = 'Voici le lien pour voir ce que je vois, avec IRIS (code ' + codeLisible(session.code) + '). Il expire dans 30 minutes.';
    if (navigator.share) {
      try { await navigator.share({ title: 'Vision partagée', text: texte, url: session.url }); return; } catch (e) {
        if (e && e.name === 'AbortError') return;
      }
    }
    try {
      await navigator.clipboard.writeText(session.url);
      toast('Lien copié : collez-le dans un message à votre proche.', 'ok');
    } catch (e) {
      toast("Ce téléphone ne permet ni le partage ni la copie depuis cette page : dictez le code à votre proche, qui l'entre sur la page du relais.", 'info');
    }
  });
  direCode.addEventListener('click', () => {
    if (!session) return;
    const voix = IRIS.voix;
    const phrase = 'Code du partage : ' + codeEpele(session.code) + '.';
    if (voix && typeof voix.parler === 'function') voix.parler(phrase); else toast(phrase, 'info');
  });

  arreter.addEventListener('click', () => terminer('Partage arrêté.', true));

  /** Arrête tout. parUtilisateur : c'est ce téléphone qui met fin (on prévient le relais et l'ordinateur). */
  function terminer(message, parUtilisateur) {
    const avait = phase !== 'repos' || !!flux || !!session;
    arretVoulu = true;
    phase = 'repos';
    clearTimeout(minuterieEmission);
    clearTimeout(minuterieReconnexion);
    clearInterval(minuterieHorloge);
    clearInterval(minuteriePing);
    const ws = socket;
    socket = null;
    if (ws) {
      if (parUtilisateur && ws.readyState === 1) {
        try { ws.send(JSON.stringify({ type: 'fin' })); } catch (e) { /* le relais expirera la session */ }
      }
      // Un court délai : le message « fin » part avant la fermeture.
      setTimeout(() => { try { ws.close(1000); } catch (e) { /* déjà fermé */ } }, 300);
    }
    fermerCamera();
    if (avait && parUtilisateur) api.post('/api/partage/arreter').catch(() => null);
    session = null;
    spectateurs = 0;
    fpsRelais = null;
    eveil(false);
    if (ferme) return;
    demarrer.disabled = !cameraPossible();
    zoneCode.hidden = true;
    relancerCamera.hidden = true;
    dessiner();
    if (message) {
      etatTitre.textContent = message;
      etatDetail.textContent = imagesEnvoyees ? imagesEnvoyees + ' images envoyées, ' + mo(octetsEnvoyes) + '.' : '';
      dire(message);
    }
  }

  // ---- ordinateur : il garde le dernier mot, et il relaie les messages
  const desabonnements = [];
  if (bus && typeof bus.on === 'function') {
    desabonnements.push(bus.on('partage.message', (ev) => {
      if (ev && ev.texte) messagesLus.set(String(ev.texte).trim(), Date.now());
    }));
    desabonnements.push(bus.on('partage.etat', (ev) => {
      // Mode confidentiel, consentement retiré, verrouillage : l'ordinateur a fermé le partage.
      if (phase === 'actif' && ev && ev.actif === false) {
        terminer(ev.raison || "Votre ordinateur a arrêté le partage.", false);
      }
    }));
  }

  // Page ramenée à l'écran : caméra et connexion ont pu être coupées par iOS.
  const auRetour = async () => {
    if (document.hidden || phase !== 'actif' || ferme) return;
    if (!cameraVivante()) {
      try { await ouvrirCamera(); } catch (e) { relancerCamera.hidden = false; }
    }
    if (!socket) { reconnexions = 0; planifierReconnexion(); }
    dessiner();
  };
  document.addEventListener('visibilitychange', auRetour);

  // ---- état de départ : un partage tourne peut-être déjà
  api.get('/api/partage/etat').then((e) => {
    if (e) afficherLimitesServeur(e.limites);
    if (ferme || phase !== 'repos' || !e || !e.actif) {
      if (phase === 'repos' && cameraPossible()) {
        etatTitre.textContent = 'Aucun partage en cours.';
        if (e && e.raison) etatDetail.textContent = 'Dernier arrêt : ' + e.raison;
      }
      return;
    }
    const avis = el('p', { class: 'note' }, 'Un partage depuis ' + (LIBELLES_SOURCES[e.source] || 'une autre source') +
      ' est déjà en cours sur votre ordinateur. Ce panneau ne peut pas le reprendre : arrêtez-le pour en démarrer un depuis ce téléphone.');
    const stop = el('button', { type: 'button', class: 'bouton-contour' }, 'Arrêter ce partage');
    stop.addEventListener('click', async () => {
      stop.disabled = true;
      try {
        await api.post('/api/partage/arreter');
        avis.textContent = 'Partage arrêté.';
        stop.remove();
        if (phase === 'repos') etatTitre.textContent = 'Aucun partage en cours.';
      } catch (err) {
        toast((err && err.message) || String(err), 'erreur');
        stop.disabled = false;
      }
    });
    etatTitre.textContent = 'Un autre partage est en cours sur votre ordinateur.';
    carteExistant.textContent = '';
    carteExistant.append(avis, stop);
    carteExistant.hidden = false;
  }).catch((err) => {
    if (ferme) return;
    if (err && err.status === 404) {
      etatTitre.textContent = "La vision partagée n'est pas disponible sur votre ordinateur : mettez IRIS à jour.";
      demarrer.disabled = true;
    } else if (phase === 'repos') {
      etatTitre.textContent = (err && err.message) || String(err);
    }
  });

  return brancherNettoyage(ctx, () => {
    const actif = phase !== 'repos' || !!session;
    terminer(null, actif);
    ferme = true;
    gardePrete.then((g) => g.fermer()).catch(() => null);
    desabonnements.forEach((f) => { try { f(); } catch (e) { /* déjà retiré */ } });
    document.removeEventListener('visibilitychange', auRetour);
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<path d="M3.5 8.5a2 2 0 0 1 2-2h2l1.5-2h6l1.5 2h2a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V8.5Z"/><circle cx="12" cy="12.5" r="3.2"/></svg>';

const MODULE = {
  id: 'partage',
  titre: 'Vision partagée',
  sous_titre: 'Un proche voit ma caméra',
  icone: ICONE,
  ordre: 50,
  ouvrir,
};

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
