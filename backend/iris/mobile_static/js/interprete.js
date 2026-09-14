/* IRIS — interprète bidirectionnel sur le téléphone, pour une conversation dehors.
 *
 * Deux grands boutons : « Je parle » (reconnaissance en français) et « L'autre parle » (reconnaissance
 * dans la langue de l'autre personne). La phrase reconnue par le téléphone part à votre ordinateur
 * (POST /api/interprete/texte), qui la fait traduire, puis ce téléphone lit la traduction dans la
 * langue de celui qui écoute et l'affiche en très grand, retournable pour la montrer en face.
 *
 * Règle ferme : dehors, ce module n'appelle JAMAIS /api/interprete/demarrer. Cette route ouvre le micro
 * de l'ordinateur resté à la maison, qui écouterait une pièce vide (ou quelqu'un d'autre). Seule la
 * route /texte est utilisée : « langue » y désigne toujours la langue de L'AUTRE personne.
 *
 * Honnêteté envers l'interlocuteur : il n'a rien accepté. Sa voix est reconnue par le service du
 * téléphone (souvent en ligne) et le texte est traduit en ligne ; l'écran invite à le prévenir, et la
 * saisie écrite reste possible. Les délais affichés sont mesurés, jamais promis.
 *
 * Lunettes d'abord : l'interprète est une fonction des lunettes VELA. Les deux boutons et la saisie
 * écrite ne s'ouvrent que si les lunettes sont détectées (lunettes.js). Pour ne pas ajouter un
 * aller-retour réseau à chaque tour (ni perdre le geste qu'exige la reconnaissance vocale sur iPhone),
 * un tour se fie à la présence déjà confirmée par la garde, qui la revérifie toutes les 30 secondes ;
 * l'ordinateur a de toute façon le dernier mot (réponse 428).
 */

// Variante régionale utilisée pour la reconnaissance et la voix du téléphone. Le français est celui
// du Canada ; pour les autres langues, la variante la plus probable d'un interlocuteur au Canada.
const LOCALES = { fr: 'fr-CA', en: 'en-CA', es: 'es-MX', pt: 'pt-BR', it: 'it-IT', de: 'de-DE' };
const NOMS = { fr: 'français', en: 'anglais', es: 'espagnol', pt: 'portugais', it: 'italien', de: 'allemand' };
const CLE_LANGUE = 'iris_interprete_langue';
const CLE_LECTURE = 'iris_interprete_lecture';

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
function secondes(ms) {
  const s = Math.max(0, Number(ms) || 0) / 1000;
  return s.toLocaleString('fr-CA', { maximumFractionDigits: s < 10 ? 1 : 0 }) + ' s';
}
const nomLangue = (code) => NOMS[code] || code;
const locale = (code) => LOCALES[code] || code;
/** « l'anglais », « le portugais » : pour une phrase affichée, jamais un code de langue nu. */
function avecArticle(code) {
  const nom = nomLangue(code);
  return (/^[aeiouy]/.test(nom) ? "l'" : 'le ') + nom;
}

/** Le téléphone a-t-il une voix pour cette langue ? null : on ne sait pas (liste pas encore chargée). */
function voixPourLangue(code) {
  let liste = [];
  try { liste = (window.speechSynthesis && speechSynthesis.getVoices()) || []; } catch (e) { liste = []; }
  if (!liste.length) return null;
  return liste.some((v) => String(v.lang || '').replace('_', '-').toLowerCase().indexOf(code) === 0);
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const IRIS = IRISv();
  const api = IRIS.api;
  const bus = IRIS.bus;
  const voix = IRIS.voix;

  let langueMoi = 'fr';
  let langueAutre = memoireLocale(CLE_LANGUE) || '';
  let lecture = memoireLocale(CLE_LECTURE) !== 'non';
  let occupe = false;
  let ferme = false;
  let retourne = false;
  const tours = [];

  // ---- lunettes : invitation à les connecter tant qu'elles manquent ; l'interprète reste caché d'ici là
  const zoneGarde = el('div');
  const zoneFonction = el('div');
  zoneFonction.hidden = true;
  corps.append(zoneGarde, zoneFonction);
  let gardeActive = null;
  const gardePrete = gardeLunettes(ctx, {
    fonction: 'interprete',
    libelle: "l'interprète",
    zone: zoneGarde,
    contenu: zoneFonction,
    enCours: () => occupe,
    avertissementEnCours: 'Le tour en cours se termine ; pour le suivant, reconnectez-les.',
  }).then((g) => { gardeActive = g; if (ferme) g.fermer(); return g; });
  async function lunettesOk() {
    const g = await gardePrete;
    return g.verifier({ depuisAction: true, cacheMs: 20000 });
  }
  /** Sans attente réseau : la reconnaissance vocale doit démarrer dans le geste (iPhone). */
  function lunettesConfirmees() {
    const etatPresence = gardeActive && typeof gardeActive.etat === 'function' ? gardeActive.etat() : null;
    if (gardeActive && gardeActive.presentes() === true && etatPresence && etatPresence.presentes) return true;
    lunettesOk().then((ok) => { if (ok && !ferme) toast('Lunettes VELA détectées : touchez de nouveau le bouton.', 'info'); }).catch(() => null);
    return false;
  }

  // ---- en-tête : langue et avertissements
  const choixLangue = el('select', { id: 'interprete-langue', class: 'champ' }, el('option', { value: '' }, 'Chargement…'));
  const empechement = el('p', { class: 'resultat-erreur', role: 'alert', hidden: true });
  const voixAbsente = el('p', { class: 'note', hidden: true });
  zoneFonction.append(
    el('div', { class: 'carte' },
      el('label', { for: 'interprete-langue', class: 'etiquette' }, "Langue de l'autre personne"),
      choixLangue, empechement, voixAbsente),
    el('p', { class: 'note' },
      "Prévenez l'autre personne : sa voix est reconnue par le service vocal du téléphone, souvent en ligne, et le texte est traduit en ligne par le moteur VELA."));

  // ---- les deux grands boutons
  const jeParle = el('button', { type: 'button', class: 'holo' }, 'Je parle');
  const autreParle = el('button', { type: 'button', class: 'holo blanc' }, "L'autre parle");
  [jeParle, autreParle].forEach((b) => { b.style.minHeight = '6rem'; b.style.fontSize = '1.5rem'; });
  const statut = el('p', { class: 'note', role: 'status', 'aria-live': 'polite' }, 'Choisissez la langue, puis touchez le bouton de celui qui parle.');
  zoneFonction.append(el('div', { class: 'liste-boutons' }, jeParle, autreParle), statut);

  // ---- texte géant, à montrer
  const grand = el('div', { class: 'sous-titres' });
  grand.style.minHeight = '32vh';
  grand.style.justifyContent = 'center';
  grand.style.transition = 'transform 0.2s';
  const grandSurTitre = el('p', { class: 'st-vide' }, 'La traduction s’affichera ici, en grand.');
  const grandTexte = el('p', { class: 'st-ligne' });
  grandTexte.style.fontSize = '2.4rem';
  const annonce = el('p', { class: 'invisible', 'aria-live': 'assertive' });
  grand.append(grandSurTitre, grandTexte);
  const tourner = el('button', { type: 'button', class: 'bouton-sombre', 'aria-pressed': 'false' }, "Tourner vers l'autre personne");
  const repeter = el('button', { type: 'button', class: 'bouton-sombre', disabled: true }, 'Relire');
  zoneFonction.append(grand, annonce, el('div', { class: 'ligne' }, tourner, repeter));

  // ---- saisie écrite
  const champ = el('textarea', { id: 'interprete-texte', class: 'champ', rows: '2', maxlength: '2000', placeholder: 'Écrivez une phrase à traduire…' });
  const quiEcrit = el('select', { id: 'interprete-qui', class: 'champ' },
    el('option', { value: 'moi' }, 'Moi (du français vers sa langue)'),
    el('option', { value: 'autre' }, "L'autre personne (de sa langue vers le français)"));
  const traduireEcrit = el('button', { type: 'button', class: 'bouton-sombre' }, 'Traduire le texte');
  zoneFonction.append(el('details', { class: 'carte' },
    el('summary', {}, 'Écrire au lieu de parler'),
    el('label', { for: 'interprete-texte', class: 'etiquette' }, 'Phrase'), champ,
    el('label', { for: 'interprete-qui', class: 'etiquette' }, 'Qui écrit ?'), quiEcrit,
    traduireEcrit));

  // ---- lecture et historique
  const interrupteur = el('input', { type: 'checkbox', role: 'switch', id: 'interprete-lecture', class: 'interrupteur' });
  interrupteur.checked = lecture;
  interrupteur.addEventListener('change', () => { lecture = interrupteur.checked; retenirLocal(CLE_LECTURE, lecture ? 'oui' : 'non'); });
  const historique = el('ul', { class: 'souvenirs' });
  zoneFonction.append(
    el('div', { class: 'carte' }, el('div', { class: 'rangee-reglage' },
      el('label', { for: 'interprete-lecture', class: 'rangee-libelle' },
        el('span', { class: 'rangee-titre' }, 'Lire les traductions à voix haute'),
        el('span', { class: 'rangee-sous' }, "Avec les voix de ce téléphone. Désactivé, la traduction s'affiche et passe par VoiceOver.")),
      interrupteur)),
    el('details', { class: 'carte' }, el('summary', {}, 'Échanges de cette conversation'), historique,
      el('p', { class: 'note-faible' }, "Cette liste reste sur cette page et disparaît à la fermeture. L'ordinateur garde les derniers échanges en mémoire vive au plus dix minutes, sans les écrire sur le disque.")));

  const limites = el('details', { class: 'carte' }, el('summary', {}, "Limites de l'interprète"), el('ul', { class: 'liste-limites' },
    el('li', {}, "Chaque tour prend quelques secondes : reconnaissance sur le téléphone, envoi à votre ordinateur, traduction en ligne. Le délai réel est mesuré et affiché."),
    el('li', {}, "Une traduction automatique peut se tromper, surtout sur les noms, les chiffres et les phrases ambiguës. Pour la santé, le droit ou l'argent, faites confirmer par écrit ou par un interprète professionnel."),
    el('li', {}, "Sur iPhone, quand les lunettes sont connectées en audio, tout le son du téléphone part dans les lunettes : l'autre personne n'entend rien. Montrez-lui l'écran avec « Tourner vers l'autre personne »."),
    el('li', {}, "Le micro utilisé peut alors être celui des lunettes : la voix de l'autre personne, captée de plus loin, est moins bien reconnue."),
    el('li', {}, "Votre ordinateur doit être allumé et joignable : c'est lui qui fait traduire. Ce panneau n'ouvre jamais son micro."),
    el('li', {}, "L'interprète s'utilise avec vos lunettes VELA détectées, par votre ordinateur ou par ce téléphone (Android). Si elles disparaissent, le tour en cours se termine, puis les boutons laissent place à l'invitation à les reconnecter."),
    el('li', {}, "Si l'interprète de l'ordinateur est ouvert avec la sortie « téléphone », ses traductions pour l'autre personne sont lues ici tant que ce panneau reste ouvert.")));
  corps.append(limites);

  if (!api) {
    [jeParle, autreParle, traduireEcrit].forEach((b) => { b.disabled = true; });
    statut.textContent = 'La liaison avec votre ordinateur n’est pas prête : fermez puis rouvrez ce panneau.';
    return brancherNettoyage(ctx, () => { ferme = true; gardePrete.then((g) => g.fermer()).catch(() => null); });
  }

  function occuper(actif) {
    occupe = actif;
    jeParle.disabled = actif || !langueAutre;
    autreParle.disabled = actif || !langueAutre;
    traduireEcrit.disabled = actif || !langueAutre;
  }

  function majVoixAbsente() {
    if (!langueAutre) { voixAbsente.hidden = true; return; }
    const dispo = voixPourLangue(langueAutre);
    voixAbsente.hidden = dispo !== false;
    voixAbsente.textContent = 'Ce téléphone n’a pas de voix en ' + nomLangue(langueAutre) +
      " : les traductions pour l'autre personne seront affichées en grand, pas lues. Montrez-lui l'écran.";
  }
  try { if (window.speechSynthesis) speechSynthesis.addEventListener('voiceschanged', majVoixAbsente); } catch (e) { /* vieux Safari */ }

  // ---- état de l'ordinateur : langues disponibles et empêchements
  api.get('/api/interprete/etat').then((e) => {
    if (ferme || !e) return;
    langueMoi = e.langue_moi || 'fr';
    const langues = (Array.isArray(e.langues) ? e.langues : []).filter((l) => l && l.code && l.code !== langueMoi);
    choixLangue.textContent = '';
    if (!langues.length) {
      choixLangue.append(el('option', { value: '' }, 'Aucune langue disponible'));
      langueAutre = '';
      occuper(false);
      return;
    }
    const codes = langues.map((l) => l.code);
    if (codes.indexOf(langueAutre) === -1) langueAutre = codes.indexOf(e.langue_autre) !== -1 ? e.langue_autre : codes[0];
    langues.forEach((l) => {
      const option = el('option', { value: l.code }, l.nom || nomLangue(l.code));
      if (l.code === langueAutre) option.selected = true;
      choixLangue.append(option);
    });
    // L'état décrit l'interprète du MICRO de l'ordinateur. Pour ce panneau, seuls comptent les
    // empêchements bloquants qui touchent aussi la traduction de texte (confidentialité, mode local,
    // accord d'envoi du texte) ; celui qui réclame l'audio brut du micro de l'ordinateur ne concerne
    // pas le téléphone. La traduction elle-même donnera, de toute façon, le refus exact s'il y en a un.
    const message = e.empechement_bloquant && e.empechement ? String(e.empechement) : '';
    if (message && !/audio brut/i.test(message)) {
      empechement.textContent = 'Sur votre ordinateur : ' + message;
      empechement.hidden = false;
    }
    majVoixAbsente();
    occuper(false);
  }).catch((err) => {
    if (ferme) return;
    choixLangue.textContent = '';
    choixLangue.append(el('option', { value: '' }, 'Indisponible'));
    langueAutre = '';
    empechement.hidden = false;
    empechement.textContent = err && err.status === 404
      ? "L'interprète n'est pas disponible sur votre ordinateur : mettez IRIS à jour."
      : (err && err.message) || String(err);
    occuper(false);
  });
  occuper(false);

  choixLangue.addEventListener('change', () => {
    langueAutre = choixLangue.value;
    if (langueAutre) retenirLocal(CLE_LANGUE, langueAutre);
    majVoixAbsente();
    occuper(occupe);
  });

  // ---- affichage et voix
  let affiche = null;   // {texte, langue, pourAutre} : ce que « Relire » redit
  function afficherGrand(texte, langue, surTitre, pourAutre) {
    grandSurTitre.textContent = surTitre;
    grandTexte.textContent = texte;
    grandTexte.setAttribute('lang', locale(langue));   // VoiceOver prononce dans la bonne langue
    affiche = texte ? { texte, langue, pourAutre: !!pourAutre } : null;
    repeter.disabled = !texte;
  }

  function lire(texte, langue, pourAutre) {
    if (!texte) return;
    const peutLire = lecture && voix && typeof voix.parler === 'function' && !(pourAutre && voixPourLangue(langue) === false);
    if (peutLire) {
      // Pour l'autre personne, débit naturel : le débit accéléré du propriétaire la perdrait.
      try { Promise.resolve(voix.parler(texte, pourAutre ? { langue: locale(langue), debit: 1 } : { langue: locale(langue) })).catch(() => false); } catch (e) { /* voix indisponible */ }
    } else {
      annonce.setAttribute('lang', locale(langue));
      annonce.textContent = '';
      setTimeout(() => { annonce.textContent = texte; }, 60);
    }
  }

  function ajouterHistorique(t) {
    tours.push(t);
    const li = el('li', {},
      el('time', {}, (t.qui === 'moi' ? 'Moi' : "L'autre personne") + ' · ' + nomLangue(t.source) + ' → ' + nomLangue(t.cible) +
        (typeof t.latence === 'number' ? ' · traduit en ' + secondes(t.latence) : '') + (t.total ? ' · ' + secondes(t.total) + ' depuis ce téléphone' : '')),
      el('span', { lang: locale(t.source) }, t.original), el('br'),
      el('strong', { lang: locale(t.cible) }, t.traduction));
    historique.prepend(li);
    while (historique.children.length > 50) historique.lastElementChild.remove();
  }

  async function traduire(qui, texte) {
    const autre = langueAutre;
    const debut = performance.now();
    statut.textContent = 'Traduction…';
    const r = await api.post('/api/interprete/texte', { qui, texte, langue: autre }, { delai: 30000 });
    if (ferme) return;
    const total = performance.now() - debut;
    const source = r.langue_source || (qui === 'moi' ? langueMoi : autre);
    const cible = r.langue_cible || (qui === 'moi' ? autre : langueMoi);
    afficherGrand(r.traduction || '', cible, qui === 'moi' ? 'Pour l’autre personne (' + nomLangue(cible) + ') :' : 'Pour vous (' + nomLangue(cible) + ') :', qui === 'moi');
    ajouterHistorique({ qui, original: texte, traduction: r.traduction || '', source, cible, latence: r.latence_ms, total });
    statut.textContent = 'Traduit en ' + secondes(r.latence_ms) + ' (mesuré par l’ordinateur) ; ' + secondes(total) + ' aller-retour depuis ce téléphone.';
    lire(r.traduction, cible, qui === 'moi');
  }

  function messageErreur(err) {
    if (err && err.code === 'consentement') return err.message + " Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité.";
    return (err && err.message) || String(err);
  }

  async function tour(qui) {
    if (occupe || !langueAutre) return;
    if (!lunettesConfirmees()) return;
    if (!voix || typeof voix.ecouter !== 'function') {
      statut.textContent = "La reconnaissance vocale n'est pas disponible sur cette page : écrivez la phrase.";
      return;
    }
    const langueEcoute = qui === 'moi' ? langueMoi : langueAutre;
    occuper(true);
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) { /* rien à couper */ }
    statut.textContent = qui === 'moi' ? 'Parlez en ' + nomLangue(langueMoi) + '…' : "L'autre personne peut parler en " + nomLangue(langueAutre) + '…';
    let texte = '';
    try {
      texte = await voix.ecouter({ langue: locale(langueEcoute), delai: 15000 });
    } catch (err) {
      if (!ferme) {
        const code = err && err.code;
        if (code === 'interrompu') statut.textContent = 'Écoute arrêtée.';
        else if (code === 'langue') statut.textContent = 'La reconnaissance vocale de ce téléphone ne reconnaît pas ' + avecArticle(langueEcoute) + ' : écrivez la phrase, ou faites-la écrire.';
        else statut.textContent = (err && err.message) || "Je n'ai rien entendu.";
      }
      occuper(false);
      return;
    }
    if (ferme) return;
    try {
      await traduire(qui, texte);
    } catch (err) {
      if (!ferme) {
        if (gardeActive && gardeActive.refus(err)) {
          statut.textContent = 'Pas traduit : vos lunettes VELA ne sont pas détectées.';
        } else {
          statut.textContent = messageErreur(err);
          afficherGrand(texte, langueEcoute, 'Entendu, mais pas traduit :', false);
        }
      }
    } finally {
      occuper(false);
    }
  }

  jeParle.addEventListener('click', () => tour('moi'));
  autreParle.addEventListener('click', () => tour('autre'));
  traduireEcrit.addEventListener('click', async () => {
    const texte = champ.value.trim();
    if (!texte) { toast('Écrivez une phrase à traduire.', 'info'); champ.focus(); return; }
    if (occupe || !langueAutre) return;
    occuper(true);
    try {
      if (!(await lunettesOk())) return;
      await traduire(quiEcrit.value === 'autre' ? 'autre' : 'moi', texte);
      champ.value = '';
    } catch (err) {
      if (gardeActive && gardeActive.refus(err)) statut.textContent = 'Pas traduit : vos lunettes VELA ne sont pas détectées.';
      else statut.textContent = messageErreur(err);
    } finally {
      occuper(false);
    }
  });

  tourner.addEventListener('click', () => {
    retourne = !retourne;
    grand.style.transform = retourne ? 'rotate(180deg)' : 'none';
    tourner.setAttribute('aria-pressed', retourne ? 'true' : 'false');
    tourner.textContent = retourne ? 'Remettre à l’endroit' : "Tourner vers l'autre personne";
  });
  repeter.addEventListener('click', () => {
    if (affiche) lire(affiche.texte, affiche.langue, affiche.pourAutre);
  });

  // L'interprète de l'ordinateur (à la maison) peut confier la voix de l'autre langue au téléphone.
  const desabonnements = [];
  if (bus && typeof bus.on === 'function') {
    desabonnements.push(bus.on('interprete.a_lire', (ev) => {
      if (!ev || !ev.texte) return;
      const langue = String(ev.langue || langueAutre || 'en').split('-')[0];
      afficherGrand(String(ev.texte), langue, 'De l’interprète de l’ordinateur, pour l’autre personne (' + nomLangue(langue) + ') :', true);
      lire(String(ev.texte), langue, true);
    }));
  }

  return brancherNettoyage(ctx, () => {
    ferme = true;
    gardePrete.then((g) => g.fermer()).catch(() => null);
    desabonnements.forEach((f) => { try { f(); } catch (e) { /* déjà retiré */ } });
    try { if (window.speechSynthesis) speechSynthesis.removeEventListener('voiceschanged', majVoixAbsente); } catch (e) { /* vieux Safari */ }
    if (occupe && voix && typeof voix.arreter === 'function') {
      try { voix.arreter(); } catch (e) { /* rien à arrêter */ }
    }
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<path d="M3.5 5.5h9v7h-5l-3 2.5V12.5h-1v-7Z"/><path d="M12.5 9.5h8v7h-1V19l-3-2.5h-4v-7Z"/><path d="M6 8h4M15 12.5h3"/></svg>';

const MODULE = {
  id: 'interprete',
  titre: 'Interprète',
  sous_titre: 'Converser dans deux langues',
  icone: ICONE,
  ordre: 45,
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
