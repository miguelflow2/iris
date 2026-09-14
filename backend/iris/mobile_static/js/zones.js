/* IRIS — zones sans mémoire, évaluées sur le téléphone.
 *
 * Dans un lieu choisi (clinique, bureau d'un client…), IRIS ne retient rien : ni souvenirs, ni journal,
 * ni cours, ni photos décrites, ni reçus. L'ordinateur connaît la liste des zones (cercles : centre et
 * rayon) ; c'est ce téléphone qui compare SA position à cette liste, et il n'envoie à l'ordinateur QUE
 * l'identifiant de la zone où il se trouve, ou « aucune » (POST /api/confiance/zone). La position
 * elle-même ne quitte pas le téléphone, sauf quand vous ajoutez explicitement une zone centrée ici.
 *
 * Même règle de prudence que l'ordinateur (zones.py) : une position imprécise compte comme « peut-être
 * dedans » jusqu'à un rayon de plus. On préfère suspendre la mémoire à tort que retenir à tort. Pour la
 * même raison, l'entrée est signalée tout de suite, la sortie seulement après deux positions de suite
 * hors de toute zone, et fermer le panneau ne signale rien : tant que la sortie n'est pas signalée,
 * la mémoire reste suspendue.
 *
 * Limite dite à l'écran : une page web ne surveille la position que tant qu'elle est ouverte à l'écran.
 */

const SORTIE_CONFIRMATIONS = 2;        // positions consécutives hors zone avant de signaler la sortie
const SORTIE_DELAI_MIN_MS = 8000;      // et au moins ce délai entre la première et la dernière
const RAYONS = [50, 100, 150, 250, 500, 1000];
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
const IRISv = () => window.IRIS || {};
function toast(texte, genre) { const ui = IRISv().ui; if (ui && typeof ui.toast === 'function') ui.toast(texte, genre); }
function confirmer(texte, options) {
  const ui = IRISv().ui;
  if (ui && typeof ui.confirmer === 'function') return ui.confirmer(texte, options);
  return Promise.resolve(window.confirm(texte));
}
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
const nombreFr = (n) => Number(n).toLocaleString('fr-CA', { maximumFractionDigits: 0 });
function distanceCourte(m) {
  const v = Math.max(0, Number(m) || 0);
  return v < 1000 ? nombreFr(Math.round(v)) + ' m' : (Math.round(v / 100) / 10).toLocaleString('fr-CA') + ' km';
}

const rad = (d) => (d * Math.PI) / 180;
/** Formule de haversine, la même que l'ordinateur (zones.distance_m). */
function distanceM(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2);
  const a = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(rad(lon2 - lon1) / 2) ** 2;
  return 2 * RAYON_TERRE_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** La zone qui contient la position (règle de zones.evaluer_position), ou null. */
function zoneContenant(position, zones) {
  let meilleure = null;
  for (const z of zones) {
    const lat = Number(z.lat), lon = Number(z.lon), rayon = Number(z.rayon_m);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(rayon)) continue;
    const d = distanceM(position.lat, position.lon, lat, lon);
    const precision = Math.max(0, Number(position.precision) || 0);
    if (d <= rayon + Math.min(precision, rayon)) {
      const marge = d - rayon;
      if (!meilleure || marge < meilleure.marge) meilleure = { zone: z, marge };
    }
  }
  return meilleure ? meilleure.zone : null;
}

function geolocalisationPossible() { return !!(window.isSecureContext && navigator.geolocation); }
function raisonSansGeolocalisation() {
  if (!window.isSecureContext) {
    return "La position n'est accessible qu'à une page sécurisée (adresse en https). Ouvrez IRIS par l'adresse de votre réseau privé.";
  }
  return "Ce navigateur ne donne pas accès à la position : la surveillance des zones est impossible ici.";
}
function messageGeolocalisation(e) {
  if (e && e.code === 1) return "Position refusée pour cette page. Sur iPhone : Réglages › Confidentialité et sécurité › Service de localisation › Sites web Safari.";
  if (e && e.code === 3) return "Position non obtenue à temps : nouvel essai automatique.";
  return "Position indisponible pour l'instant (signal GPS absent ou localisation coupée).";
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const IRIS = IRISv();
  const api = IRIS.api;
  const bus = IRIS.bus;

  let zones = [];
  let zoneActiveServeur = null;       // {id, nom} selon l'ordinateur, toutes sources confondues
  let signalee;                        // undefined : rien signalé depuis ce panneau ; null : « aucune » ; sinon l'id
  let echec;                           // zone dont l'envoi a échoué (undefined : aucun échec en suspens)
  let pendant;                         // changement survenu pendant un envoi (undefined : aucun)
  let envoiEnCours = false;
  let surveillance = null;
  let derniere = null;                 // dernière position (reste sur ce téléphone)
  let horsDepuis = null;               // {n, t} : positions consécutives hors zone
  let ferme = false;

  corps.append(
    el('p', { class: 'note' },
      "Dans une zone sans mémoire, IRIS ne retient rien : ni souvenirs, ni journal, ni cours, ni photos décrites, ni reçus. " +
      "Ce téléphone compare sa position à vos zones et n'envoie à votre ordinateur que le nom de code de la zone où il se trouve, ou « aucune »."),
    el('p', { class: 'note-faible' },
      "Sur iPhone, la surveillance ne marche que tant que cette page est ouverte à l'écran. L'application IRIS pour iPhone, elle, peut surveiller en arrière-plan."));

  const etat = el('div', { class: 'resultat', role: 'status', 'aria-live': 'polite' });
  const etatTitre = el('p', { class: 'resultat-texte' }, 'Chargement de vos zones…');
  const etatDetail = el('p', { class: 'note' });
  etat.append(etatTitre, etatDetail);
  const bascule = el('button', { type: 'button', class: 'holo' }, 'Surveiller ma position');
  const listeZones = el('div', { class: 'liste-boutons' });
  const limiteServeur = el('p', { class: 'note-faible' });
  corps.append(etat, bascule, el('h3', { class: 'etiquette' }, 'Vos zones'), listeZones, limiteServeur);

  if (!api) {
    etatTitre.textContent = 'La liaison avec votre ordinateur n’est pas prête : fermez puis rouvrez ce panneau.';
    bascule.disabled = true;
    return () => {};
  }

  // ---- ajouter une zone ici
  const champNom = el('input', { id: 'zone-nom', class: 'champ', type: 'text', autocomplete: 'off', maxlength: '60', placeholder: 'Ex. : Clinique' });
  const choixRayon = el('select', { id: 'zone-rayon', class: 'champ' });
  RAYONS.forEach((r) => {
    const option = el('option', { value: String(r) }, distanceCourte(r));
    if (r === 150) option.selected = true;
    choixRayon.append(option);
  });
  const ajouter = el('button', { type: 'button', class: 'bouton-sombre' }, 'Ajouter l’endroit où je suis');
  corps.append(el('details', { class: 'carte' },
    el('summary', {}, 'Ajouter une zone ici'),
    el('p', { class: 'note-faible' }, "Le centre de la zone (votre position actuelle) et son rayon sont enregistrés dans les réglages d'IRIS, sur votre ordinateur. C'est le seul cas où ce panneau envoie une position."),
    el('label', { for: 'zone-nom', class: 'etiquette' }, 'Nom de la zone'), champNom,
    el('label', { for: 'zone-rayon', class: 'etiquette' }, 'Rayon'), choixRayon,
    ajouter));

  const aucune = el('button', { type: 'button', class: 'bouton-contour' }, 'Signaler : je ne suis dans aucune zone');
  corps.append(el('div', { class: 'carte' },
    el('p', { class: 'note-faible' },
      "Fermer ce panneau arrête la surveillance sans rien signaler : si ce téléphone a signalé une zone, la mémoire reste suspendue " +
      "jusqu'à ce qu'il signale la sortie (rouvrez ce panneau hors de la zone) ou que vous utilisiez ce bouton."),
    aucune));

  // ---- affichage
  function libelleZone(id) {
    const z = zones.find((x) => x.id === id);
    return z ? z.nom : 'zone inconnue';
  }
  function dessinerEtat() {
    let titre;
    if (zoneActiveServeur) titre = 'Mémoire suspendue : zone « ' + zoneActiveServeur.nom + ' ».';
    else titre = 'Aucune zone active : IRIS retient normalement.';
    etatTitre.textContent = titre;
    const morceaux = [];
    if (!geolocalisationPossible()) morceaux.push(raisonSansGeolocalisation());
    else if (surveillance === null) morceaux.push('Surveillance arrêtée.');
    else if (!derniere) morceaux.push('Surveillance en marche : en attente de la position…');
    else {
      const ici = zoneContenant(derniere, zones);
      morceaux.push('Surveillance en marche. Selon ce téléphone : ' + (ici ? 'dans « ' + ici.nom + ' »' : 'hors de toute zone') +
        ' (position à ' + distanceCourte(derniere.precision) + ' près).');
      if (!ici && signalee && horsDepuis) morceaux.push('Sortie en cours de confirmation…');
    }
    if (signalee !== undefined) morceaux.push('Dernier signalement de ce téléphone : ' + (signalee ? '« ' + libelleZone(signalee) + ' »' : 'aucune zone') + '.');
    if (echec !== undefined) morceaux.push("Signalement pas encore reçu par l'ordinateur : nouvel essai à la prochaine position.");
    etatDetail.textContent = morceaux.join(' ');
    bascule.textContent = surveillance === null ? 'Surveiller ma position' : 'Arrêter la surveillance';
    bascule.disabled = surveillance === null && (!geolocalisationPossible() || !zones.length);
  }

  function dessinerZones() {
    listeZones.textContent = '';
    if (!zones.length) {
      listeZones.append(el('p', { class: 'note' }, "Aucune zone pour l'instant. Ajoutez-en une ci-dessous, ou dans IRIS sur l'ordinateur (Confiance › Zones sans mémoire)."));
      return;
    }
    for (const z of zones) {
      const morceaux = ['rayon ' + distanceCourte(z.rayon_m)];
      if (derniere) morceaux.push('à ' + distanceCourte(distanceM(derniere.lat, derniere.lon, Number(z.lat), Number(z.lon))) + ' du centre');
      if (zoneActiveServeur && zoneActiveServeur.id === z.id) morceaux.push('active');
      const supprimer = el('button', { type: 'button', class: 'bouton-contour petit', 'aria-label': 'Supprimer la zone ' + z.nom }, 'Supprimer');
      supprimer.addEventListener('click', () => supprimerZone(z));
      listeZones.append(el('div', { class: 'carte' },
        el('p', { class: 'choix-titre' }, z.nom),
        el('p', { class: 'choix-sous' }, morceaux.join(' · ')),
        supprimer));
    }
  }

  function appliquerEtat(d) {
    if (!d || typeof d !== 'object') return;
    if (Array.isArray(d.zones)) zones = d.zones.filter((z) => z && z.id && z.nom);
    if ('zone_active' in d) zoneActiveServeur = d.zone_active || null;
    if (d.limite) limiteServeur.textContent = d.limite;
    dessinerZones();
    dessinerEtat();
  }

  async function charger() {
    try {
      appliquerEtat(await api.get('/api/confiance/zones'));
      return true;
    } catch (err) {
      etatTitre.textContent = err && err.status === 404
        ? "Les zones sans mémoire ne sont pas disponibles sur votre ordinateur : mettez IRIS à jour."
        : (err && err.message) || String(err);
      bascule.disabled = true;
      return false;
    }
  }

  // ---- signalement : seulement au changement
  async function signaler(zoneId, manuel) {
    if (envoiEnCours) { pendant = zoneId; return; }   // parti après l'envoi en cours, s'il change encore quelque chose
    envoiEnCours = true;
    echec = undefined;
    try {
      const d = await api.post('/api/confiance/zone', { zone_id: zoneId, source: 'telephone' });
      const avant = signalee;
      signalee = zoneId;
      appliquerEtat(d);
      if (manuel || avant !== zoneId) {
        const phrase = zoneId ? 'Zone « ' + libelleZone(zoneId) + ' » : IRIS ne retient plus rien.' : (avant ? 'Sortie de zone signalée : IRIS retient de nouveau.' : '');
        if (phrase) { toast(phrase, 'info'); dire(phrase); }
      }
    } catch (err) {
      if (err && err.status === 404) {
        // La zone a été supprimée entre-temps (sur l'ordinateur) : on relit la liste et on réévalue.
        await charger();
        if (derniere && !ferme) evaluer(derniere);
      } else {
        // Réseau coupé ou ordinateur injoignable : nouvel essai à la prochaine position, jamais en rafale.
        echec = zoneId;
        if (manuel) toast((err && err.message) || String(err), 'erreur');
      }
      dessinerEtat();
    } finally {
      envoiEnCours = false;
    }
    if (pendant !== undefined && !ferme) {
      const suivant = pendant;
      pendant = undefined;
      if (suivant !== signalee) signaler(suivant, false);
    }
  }

  function evaluer(position) {
    const ici = zoneContenant(position, zones);
    const voulu = ici ? ici.id : null;
    if (echec !== undefined && echec === voulu) {
      signaler(voulu, false);
      return;
    }
    if (voulu) {
      horsDepuis = null;
      if (signalee !== voulu) signaler(voulu, false);   // entrée (ou changement de zone) : tout de suite
      return;
    }
    if (signalee === null) { horsDepuis = null; return; }
    // Sortie (ou premier état « hors zone ») : confirmée par deux positions espacées.
    const maintenant = Date.now();
    if (!horsDepuis) horsDepuis = { n: 1, t: maintenant };
    else horsDepuis.n += 1;
    if (horsDepuis.n >= SORTIE_CONFIRMATIONS && maintenant - horsDepuis.t >= SORTIE_DELAI_MIN_MS) {
      horsDepuis = null;
      signaler(null, false);
    }
  }

  // ---- surveillance
  function demarrerSurveillance() {
    if (surveillance !== null || !geolocalisationPossible()) return;
    try {
      surveillance = navigator.geolocation.watchPosition((pos) => {
        if (ferme) return;
        derniere = { lat: pos.coords.latitude, lon: pos.coords.longitude, precision: Math.round(Number(pos.coords.accuracy) || 0) };
        evaluer(derniere);
        dessinerZones();
        dessinerEtat();
      }, (e) => {
        if (ferme) return;
        if (e && e.code === 1) arreterSurveillance();
        etatDetail.textContent = messageGeolocalisation(e);
      }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 });
    } catch (e) {
      surveillance = null;
      etatDetail.textContent = messageGeolocalisation(null);
    }
    dessinerEtat();
  }
  function arreterSurveillance() {
    if (surveillance !== null) {
      try { navigator.geolocation.clearWatch(surveillance); } catch (e) { /* déjà arrêtée */ }
    }
    surveillance = null;
    horsDepuis = null;
    dessinerEtat();
  }
  bascule.addEventListener('click', () => {
    if (surveillance === null) demarrerSurveillance(); else arreterSurveillance();
  });

  aucune.addEventListener('click', async () => {
    const ok = await confirmer("Signaler que ce téléphone n'est dans aucune zone ? Si vous y êtes encore, IRIS recommencera à retenir ce que vous faites.",
      { oui: 'Signaler', non: 'Annuler' });
    if (!ok) return;
    horsDepuis = null;
    signaler(null, true);
  });

  ajouter.addEventListener('click', async () => {
    const nom = champNom.value.trim();
    if (!nom) { toast('Donnez un nom à la zone.', 'info'); champNom.focus(); return; }
    if (!geolocalisationPossible()) { toast(raisonSansGeolocalisation(), 'erreur'); return; }
    ajouter.disabled = true;
    ajouter.textContent = 'Recherche de votre position…';
    try {
      const pos = await new Promise((resoudre, rejeter) => navigator.geolocation.getCurrentPosition(resoudre, rejeter,
        { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }));
      const rayon = Number(choixRayon.value) || 150;
      const precision = Math.round(Number(pos.coords.accuracy) || 0);
      let texte = 'Ajouter la zone « ' + nom + ' », rayon ' + distanceCourte(rayon) + ', centrée sur votre position actuelle (précise à ' +
        distanceCourte(precision) + ' près) ? Le centre est enregistré sur votre ordinateur.';
      if (precision > rayon / 2) texte += ' Attention : la position est peu précise par rapport au rayon choisi.';
      const ok = await confirmer(texte, { oui: 'Ajouter', non: 'Annuler' });
      if (!ok) return;
      await api.post('/api/confiance/zones', { nom, lat: pos.coords.latitude, lon: pos.coords.longitude, rayon_m: rayon });
      champNom.value = '';
      toast('Zone « ' + nom + ' » ajoutée.', 'ok');
      await charger();
      derniere = { lat: pos.coords.latitude, lon: pos.coords.longitude, precision };
      evaluer(derniere);
      if (surveillance === null) demarrerSurveillance();
    } catch (err) {
      toast(err && typeof err.code === 'number' && !('status' in err) ? messageGeolocalisation(err) : ((err && err.message) || String(err)), 'erreur');
    } finally {
      ajouter.disabled = false;
      ajouter.textContent = 'Ajouter l’endroit où je suis';
    }
  });

  async function supprimerZone(z) {
    const ok = await confirmer('Supprimer la zone « ' + z.nom + " » ? IRIS retiendra de nouveau ce qui s'y passe.", { oui: 'Supprimer', non: 'Annuler' });
    if (!ok) return;
    try {
      appliquerEtat(await api.delete('/api/confiance/zones/' + encodeURIComponent(z.id)));
      if (signalee === z.id) signalee = null;   // l'ordinateur a levé ce signalement en supprimant la zone
      toast('Zone « ' + z.nom + ' » supprimée.', 'ok');
      if (derniere) evaluer(derniere);
    } catch (err) {
      toast((err && err.message) || String(err), 'erreur');
    }
  }

  // ---- événements de l'ordinateur
  const desabonnements = [];
  if (bus && typeof bus.on === 'function') {
    desabonnements.push(bus.on('zone.etat', () => { charger(); }));
    desabonnements.push(bus.on('settings.updated', (ev) => {
      const s = ev && ev.settings;
      if (s && Array.isArray(s.zones_sans_memoire)) {
        zones = s.zones_sans_memoire.filter((z) => z && z.id && z.nom);
        dessinerZones();
        dessinerEtat();
        if (derniere) evaluer(derniere);
      }
    }));
  }

  charger().then((ok) => {
    if (ok && zones.length && geolocalisationPossible() && !ferme) demarrerSurveillance();
  });

  return brancherNettoyage(ctx, () => {
    ferme = true;
    desabonnements.forEach((f) => { try { f(); } catch (e) { /* déjà retiré */ } });
    if (surveillance !== null) {
      try { navigator.geolocation.clearWatch(surveillance); } catch (e) { /* déjà arrêtée */ }
    }
    surveillance = null;
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<circle cx="12" cy="12" r="8.5" stroke-dasharray="3 2.5"/><path d="M12 8.5v3.5l2.2 1.6"/><path d="m4 4 16 16"/></svg>';

const MODULE = {
  id: 'zones',
  titre: 'Zones sans mémoire',
  sous_titre: 'IRIS ne retient rien dans ces lieux',
  icone: ICONE,
  ordre: 60,
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
