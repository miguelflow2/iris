/* IRIS — achats depuis le téléphone : garder un reçu, comparer un prix.
 *
 * Reçu : la photo est réduite ici, envoyée à votre ordinateur (POST /api/recus/analyser), où le texte est
 * lu hors ligne ; le moteur VELA ne reçoit l'image que si « Images jointes » est autorisé. Les montants
 * sont contrôlés (addition, taux de TPS/TVQ/TVH), jamais inventés : un champ illisible reste vide, et
 * c'est vous qui le corrigez ici (PATCH /api/recus/{id}). Données et image sont gardées chiffrées sur
 * l'ordinateur ; en mode invité ou en zone sans mémoire, le reçu est lu mais pas enregistré.
 *
 * Prix : le produit est identifié sur la photo (ou tapé), puis cherché en ligne au Canada
 * (POST /api/achats/comparer). Les prix viennent d'extraits de recherche : ils peuvent dater et
 * différer du magasin, et l'écran le dit toujours (champ « avertissement » de l'ordinateur).
 *
 * Lunettes d'abord : analyser un reçu et comparer un prix sont des fonctions des lunettes VELA. Elles
 * ne s'ouvrent que si les lunettes sont détectées (lunettes.js). La photo est prise avec la caméra du
 * téléphone EN SECOURS, et l'écran le dit : la commande photo des lunettes n'est pas encore confirmée
 * sur le vrai matériel. En revanche, consulter, corriger et supprimer ses reçus reste TOUJOURS
 * possible sans les lunettes (« Mes reçus enregistrés ») : ce sont vos données (Loi 25).
 *
 * Tout ce que l'ordinateur renvoie comme vérité (note, avertissement, confiance, contrôle, limite) est
 * affiché tel quel, sans l'arrondir en promesse.
 */

const CATEGORIES = [
  'Alimentation', 'Restaurant', 'Transport', 'Essence', 'Fournitures de bureau', 'Logiciels et abonnements',
  'Matériel', 'Télécommunications', 'Formation', 'Santé', 'Loisirs', 'Autre',
];
const MONTANTS = [['sous_total', 'Sous-total'], ['tps', 'TPS'], ['tvq', 'TVQ'], ['tvh', 'TVH'], ['total', 'Total']];
const LIMITE_RECUS = "Vérifiez chaque montant avant de l'utiliser : un reçu pâli, froissé ou manuscrit peut être mal lu. " +
  "La catégorie est une suggestion, et ce n'est pas un avis comptable ou fiscal. La durée de conservation réglée dans " +
  "Confidentialité s'applique aussi aux reçus : exportez-les depuis l'ordinateur si vous devez les garder plus longtemps.";
const RECUS_AFFICHES = 30;

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
function secondes(ms) {
  const s = Math.max(0, Number(ms) || 0) / 1000;
  return s.toLocaleString('fr-CA', { maximumFractionDigits: s < 10 ? 1 : 0 }) + ' s';
}
function argent(valeur, devise) {
  if (valeur === null || valeur === undefined || !Number.isFinite(Number(valeur))) return 'non lu';
  const code = /^[A-Z]{3}$/.test(String(devise || '')) ? devise : 'CAD';
  try { return Number(valeur).toLocaleString('fr-CA', { style: 'currency', currency: code }); } catch (e) {
    return Number(valeur).toLocaleString('fr-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + code;
  }
}
/** « 13 sept. 2026 » pour une date d'achat AAAA-MM-JJ, lue comme un jour local (pas minuit UTC). */
function jourLisible(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return String(iso || '');
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' });
}
function saisieMontant(valeur) {
  if (valeur === null || valeur === undefined) return '';
  return Number(valeur).toLocaleString('fr-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false });
}
/** « 12,34 », « 12.34 $ » -> 12.34 ; vide -> null ; illisible -> NaN. */
function lireMontant(texte) {
  const propre = String(texte || '').replace(/[\s$]/g, '').replace(',', '.');
  if (!propre) return null;
  return /^-?\d+(\.\d{1,2})?$/.test(propre) ? Math.round(Number(propre) * 100) / 100 : NaN;
}
function messageErreur(err) { return (err && err.message) || String(err); }

/** Réduit une photo avant l'envoi : la coquille le fait (IRIS.image.reduire) ; repli local sinon. */
function reduire(fichier, coteMax) {
  const outil = IRISv().image;
  if (outil && typeof outil.reduire === 'function') return outil.reduire(fichier, coteMax);
  return new Promise((resoudre, rejeter) => {
    let url = '';
    try { url = URL.createObjectURL(fichier); } catch (e) { rejeter(new Error('Photo illisible sur ce téléphone.')); return; }
    const image = new Image();
    image.onload = () => {
      try {
        const echelle = Math.min(1, coteMax / Math.max(image.naturalWidth, image.naturalHeight));
        const toile = document.createElement('canvas');
        toile.width = Math.max(1, Math.round(image.naturalWidth * echelle));
        toile.height = Math.max(1, Math.round(image.naturalHeight * echelle));
        toile.getContext('2d').drawImage(image, 0, 0, toile.width, toile.height);
        const donnees = toile.toDataURL('image/jpeg', 0.85);
        URL.revokeObjectURL(url);
        if (donnees.indexOf('data:image/jpeg') !== 0) throw new Error("Ce téléphone n'a pas pu convertir la photo en JPEG.");
        resoudre({ media_type: 'image/jpeg', data: donnees.slice(donnees.indexOf(',') + 1) });
      } catch (e) { URL.revokeObjectURL(url); rejeter(e); }
    };
    image.onerror = () => { URL.revokeObjectURL(url); rejeter(new Error('Photo illisible sur ce téléphone (format non pris en charge).')); };
    image.src = url;
  });
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const IRIS = IRISv();
  const api = IRIS.api;
  const bus = IRIS.bus;
  let occupe = false;
  let ferme = false;
  let apercuUrl = '';       // photo du reçu qui vient d'être pris
  let urlDetail = '';       // image d'un reçu ouvert depuis la liste
  let listeChargee = false;
  const chronos = new Set();

  corps.append(el('p', { class: 'note' },
    "Photographiez un reçu pour le garder sur votre ordinateur, ou un produit pour voir son prix ailleurs au Canada. " +
    "Les photos sont réduites sur ce téléphone, puis envoyées à votre ordinateur."));

  // Champ photo propre à ce panneau : visuellement caché plutôt que display:none (certains iOS refusent
  // d'ouvrir l'appareil photo depuis un champ retiré de la mise en page). Hors de la zone cachée par la garde.
  const entreePhoto = el('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'invisible', tabindex: '-1', 'aria-hidden': 'true' });
  corps.append(entreePhoto);
  function prendrePhoto() {
    return new Promise((resoudre) => {
      entreePhoto.value = '';
      entreePhoto.onchange = () => {
        entreePhoto.onchange = null;
        resoudre((entreePhoto.files && entreePhoto.files[0]) || null);
      };
      try { entreePhoto.click(); } catch (e) { toast("L'appareil photo ne s'ouvre pas depuis cette page.", 'erreur'); resoudre(null); }
    });
  }

  // ---- lunettes : les captures restent cachées tant qu'elles ne sont pas détectées
  const zoneGarde = el('div');
  const zoneFonction = el('div');
  zoneFonction.hidden = true;
  corps.append(zoneGarde, zoneFonction);
  let gardeActive = null;
  const gardePrete = gardeLunettes(ctx, {
    fonction: 'achats',
    libelle: "l'analyse des reçus et la comparaison de prix",
    zone: zoneGarde,
    contenu: zoneFonction,
    noteSecours: 'La caméra des lunettes arrive ; en attendant, la photo est prise avec ce téléphone.',
    enCours: () => occupe,
  }).then((g) => { gardeActive = g; if (ferme) g.fermer(); return g; });
  async function lunettesOk() {
    const g = await gardePrete;
    return g.verifier({ depuisAction: true, cacheMs: 20000 });
  }
  /**
   * Avant d'ouvrir l'appareil photo : iOS n'ouvre le sélecteur que dans le geste lui-même, sans attente
   * réseau. On se fie donc à la présence déjà confirmée par la garde ; sinon on vérifie, sans photo.
   */
  function lunettesConfirmees() {
    if (gardeActive && gardeActive.presentes() === true) return true;
    lunettesOk().then((ok) => { if (ok && !ferme) toast('Lunettes VELA détectées : touchez de nouveau le bouton.', 'info'); }).catch(() => null);
    return false;
  }

  const boutonRecu = el('button', { type: 'button', class: 'holo' }, 'Photographier un reçu');
  const resultatRecu = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  zoneFonction.append(el('h3', { class: 'etiquette' }, 'Reçus'), boutonRecu,
    el('p', { class: 'note-faible' }, 'Posez le reçu à plat, bien éclairé, et cadrez-le en entier.'), resultatRecu);

  const champProduit = el('input', { id: 'achats-produit', class: 'champ', type: 'text', autocomplete: 'off', maxlength: '200', enterkeyhint: 'search', placeholder: 'Ex. : cafetière à piston 1 litre' });
  const photoProduit = el('button', { type: 'button', class: 'holo' }, 'Photographier le produit');
  const chercherNom = el('button', { type: 'button', class: 'bouton-sombre' }, 'Chercher ce nom');
  const resultatPrix = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  zoneFonction.append(el('h3', { class: 'etiquette' }, 'Comparer un prix'),
    el('div', { class: 'carte' },
      el('label', { for: 'achats-produit', class: 'etiquette' }, 'Nom du produit (ou précision pour la photo)'),
      champProduit, chercherNom,
      el('p', { class: 'note-faible' }, "Le nom du produit est envoyé au service de recherche web d'IRIS depuis votre ordinateur, avec votre accord « Texte de vos demandes ». La photo passe par la description d'image, avec l'accord « Images jointes ».")),
    photoProduit, resultatPrix);

  // ---- mes reçus : toujours accessibles, lunettes ou non
  const resumeRecus = el('p', { class: 'note', role: 'status' });
  const listeRecus = el('div', { class: 'liste-boutons' });
  const actualiser = el('button', { type: 'button', class: 'bouton-sombre' }, 'Actualiser la liste');
  const detailRecu = el('div', { class: 'resultat', 'aria-live': 'polite', hidden: true });
  const limiteListe = el('p', { class: 'note-faible' });
  const carteRecus = el('details', { class: 'carte' }, el('summary', {}, 'Mes reçus enregistrés'),
    el('p', { class: 'note-faible' }, 'Consulter, corriger et supprimer vos reçus marche aussi sans les lunettes.'),
    resumeRecus, listeRecus, actualiser, detailRecu, limiteListe);
  corps.append(carteRecus);

  if (!api) {
    [boutonRecu, photoProduit, chercherNom, actualiser].forEach((b) => { b.disabled = true; });
    corps.append(el('p', { class: 'resultat-erreur' }, 'La liaison avec votre ordinateur n’est pas prête : fermez puis rouvrez ce panneau.'));
    return brancherNettoyage(ctx, () => { ferme = true; gardePrete.then((g) => g.fermer()).catch(() => null); });
  }

  function occuper(actif) {
    occupe = actif;
    [boutonRecu, photoProduit, chercherNom].forEach((b) => { b.disabled = actif; });
  }
  function chrono(statut, prefixe, debut) {
    const id = setInterval(() => { statut.textContent = prefixe + ' ' + Math.round((performance.now() - debut) / 1000) + ' s'; }, 1000);
    chronos.add(id);
    return () => { clearInterval(id); chronos.delete(id); };
  }

  // ================================================================ reçu
  boutonRecu.addEventListener('click', async () => {
    if (occupe) return;
    if (!lunettesConfirmees()) return;
    const fichier = await prendrePhoto();
    if (!fichier || ferme) return;
    if (!(await lunettesOk())) return;       // elles ont pu partir pendant la photo
    occuper(true);
    const debut = performance.now();
    resultatRecu.hidden = false;
    resultatRecu.textContent = '';
    const statut = el('p', { class: 'note' }, 'Préparation de la photo…');
    resultatRecu.append(el('h3', {}, 'Reçu'), statut);
    let arreterChrono = () => {};
    try {
      if (apercuUrl) { URL.revokeObjectURL(apercuUrl); apercuUrl = ''; }
      try { apercuUrl = URL.createObjectURL(fichier); } catch (e) { apercuUrl = ''; }
      const image = await reduire(fichier, 1600);
      statut.textContent = 'Envoi à votre ordinateur et lecture…';
      arreterChrono = chrono(statut, 'Envoi à votre ordinateur et lecture…', debut);
      const recu = await api.post('/api/recus/analyser', { source: 'image', image: { media_type: image.media_type, data: image.data } }, { delai: 120000 });
      arreterChrono();
      if (ferme) return;
      afficherRecu(resultatRecu, recu, performance.now() - debut, apercuUrl, 'Photo du reçu prise avec ce téléphone');
      dire(phraseRecu(recu));
      if (listeChargee && recu && recu.enregistre) chargerRecus();
    } catch (err) {
      arreterChrono();
      if (ferme) return;
      if (gardeActive && gardeActive.refus(err)) { resultatRecu.hidden = true; return; }
      resultatRecu.textContent = '';
      resultatRecu.append(el('h3', {}, 'Reçu'), el('p', { class: 'resultat-erreur' }, messageErreur(err)));
      if (err && err.code === 'consentement') resultatRecu.append(el('p', { class: 'note' }, "Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité."));
      dire(messageErreur(err));
    } finally {
      occuper(false);
    }
  });

  function phraseRecu(r) {
    const commercant = r.commercant || 'commerçant non lu';
    const confiance = Math.round((Number(r.confiance) || 0) * 100);
    const debut = r.enregistre ? 'Reçu enregistré' : 'Reçu lu, mais pas enregistré';
    return debut + ' : ' + commercant + ', total ' + argent(r.total, r.devise) + ', confiance ' + confiance + ' %. Vérifiez les montants avant de vous en servir.';
  }

  function lignesControle(r) {
    const c = r.controle || {};
    const lignes = [];
    if (c.somme_ok === true) lignes.push('Sous-total et taxes donnent bien le total.');
    else if (c.somme_ok === false) lignes.push("Sous-total et taxes ne donnent pas le total : un montant est probablement mal lu.");
    else lignes.push('Addition non vérifiable : un montant manque.');
    if (c.taux_ok === true) lignes.push('Taxes conformes aux taux connus (TPS 5 %, TVQ 9,975 %, TVH 13 à 15 %).');
    else if (c.taux_ok === false) lignes.push('Taxes différentes des taux connus : à vérifier.');
    else lignes.push('Taux de taxes non vérifiable (montants manquants, ou panier en partie non taxé).');
    if (c.date_ambigue) lignes.push('Date ambiguë, lue jour/mois : vérifiez-la.');
    if (Array.isArray(c.completes_localement) && c.completes_localement.length) {
      lignes.push('Complété par la lecture faite sur l’ordinateur : ' + c.completes_localement.join(', ') + '.');
    }
    if (Array.isArray(c.champs_rejetes) && c.champs_rejetes.length) {
      lignes.push('Valeurs rejetées parce qu’illisibles ou incohérentes : ' + c.champs_rejetes.join(', ') + '.');
    }
    return lignes;
  }

  /** Dessine un reçu dans `cible`, avec le formulaire de correction s'il est enregistré. */
  function afficherRecu(cible, r, totalMs, urlImage, altImage) {
    cible.textContent = '';
    cible.hidden = false;
    const enregistre = !!(r && r.enregistre && r.id);
    const titre = el('h3', { tabindex: '-1' }, enregistre ? (r.corrige ? 'Reçu enregistré (corrigé)' : 'Reçu enregistré') : 'Reçu lu, pas enregistré');
    cible.append(titre);
    if (urlImage) {
      const img = el('img', { src: urlImage, alt: altImage || 'Photo du reçu' });
      img.style.maxHeight = '30vh';
      img.style.objectFit = 'contain';
      img.style.borderRadius = '12px';
      cible.append(img);
    }
    cible.append(el('p', { class: 'resultat-texte' },
      (r.commercant || 'Commerçant non lu') + ' — total ' + argent(r.total, r.devise)));
    cible.append(el('p', { class: 'note' },
      'Confiance de la lecture : ' + Math.round((Number(r.confiance) || 0) * 100) + ' %. Ce chiffre ne dépasse jamais 95 % : vérifiez chaque montant.'));
    cible.append(el('ul', { class: 'liste-limites' }, lignesControle(r).map((t) => el('li', {}, t))));
    if (r.note) cible.append(el('p', { class: 'note' }, r.note));
    const origine = r.local ? 'Lu sur votre ordinateur, sans envoi externe.' : 'Image lue par le moteur VELA ; addition et taux contrôlés sur votre ordinateur.';
    const delais = typeof r.duree_ms === 'number'
      ? ' Analyse : ' + secondes(r.duree_ms) + (totalMs ? ' ; total mesuré depuis ce téléphone : ' + secondes(totalMs) : '') + '.'
      : '';
    cible.append(el('p', { class: 'note-faible' }, origine + delais));

    const champs = {};
    const formulaire = el('div', { class: 'carte' }, el('h3', {}, enregistre ? 'Vérifier et corriger' : 'Ce qui a été lu'));
    function rangee(id, libelle, champ) {
      formulaire.append(el('label', { for: id, class: 'etiquette' }, libelle), champ);
    }
    const idBase = 'recu-' + Math.random().toString(36).slice(2, 8) + '-';
    champs.commercant = el('input', { id: idBase + 'commercant', class: 'champ', type: 'text', maxlength: '120', autocomplete: 'off', placeholder: 'non lu' });
    champs.commercant.value = r.commercant || '';
    rangee(idBase + 'commercant', 'Commerçant', champs.commercant);
    champs.date = el('input', { id: idBase + 'date', class: 'champ', type: 'date' });
    champs.date.value = r.date || '';
    rangee(idBase + 'date', 'Date d’achat', champs.date);
    champs.categorie = el('select', { id: idBase + 'categorie', class: 'champ' });
    CATEGORIES.forEach((c) => {
      const option = el('option', { value: c }, c);
      if ((r.categorie || 'Autre') === c) option.selected = true;
      champs.categorie.append(option);
    });
    rangee(idBase + 'categorie', 'Catégorie (suggestion)', champs.categorie);
    for (const [cle, libelle] of MONTANTS) {
      champs[cle] = el('input', { id: idBase + cle, class: 'champ', type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'non lu' });
      champs[cle].value = saisieMontant(r[cle]);
      rangee(idBase + cle, libelle, champs[cle]);
    }
    champs.devise = el('input', { id: idBase + 'devise', class: 'champ', type: 'text', maxlength: '3', autocomplete: 'off', autocapitalize: 'characters' });
    champs.devise.value = r.devise || 'CAD';
    rangee(idBase + 'devise', 'Devise', champs.devise);
    champs.moyen_paiement = el('input', { id: idBase + 'moyen', class: 'champ', type: 'text', maxlength: '40', autocomplete: 'off', placeholder: 'non lu' });
    champs.moyen_paiement.value = r.moyen_paiement || '';
    rangee(idBase + 'moyen', 'Moyen de paiement', champs.moyen_paiement);

    if (!enregistre) {
      Object.values(champs).forEach((c) => { c.disabled = true; });
      formulaire.append(el('p', { class: 'note' }, "Ce reçu n'a pas été enregistré sur l'ordinateur : il ne peut pas être corrigé ici. Notez les montants si vous en avez besoin."));
    } else {
      const erreurFormulaire = el('p', { class: 'resultat-erreur', role: 'alert' });
      const enregistrer = el('button', { type: 'button', class: 'holo' }, 'Enregistrer les corrections');
      const supprimer = el('button', { type: 'button', class: 'bouton-contour' }, 'Supprimer ce reçu');
      formulaire.append(erreurFormulaire, enregistrer, supprimer);

      enregistrer.addEventListener('click', async () => {
        erreurFormulaire.textContent = '';
        const patch = {};
        const texte = (champ, original) => {
          const v = champs[champ].value.trim();
          if (v !== String(original || '')) patch[champ] = v || null;
        };
        texte('commercant', r.commercant);
        texte('moyen_paiement', r.moyen_paiement);
        if ((champs.date.value || '') !== (r.date || '')) patch.date = champs.date.value || null;
        if (champs.categorie.value !== (r.categorie || 'Autre')) patch.categorie = champs.categorie.value;
        const devise = champs.devise.value.trim().toUpperCase();
        if (devise !== (r.devise || 'CAD')) {
          if (!/^[A-Z]{3}$/.test(devise)) { erreurFormulaire.textContent = 'Devise : trois lettres (CAD, USD…).'; champs.devise.focus(); return; }
          patch.devise = devise;
        }
        for (const [cle, libelle] of MONTANTS) {
          const saisi = lireMontant(champs[cle].value);
          if (Number.isNaN(saisi)) { erreurFormulaire.textContent = libelle + ' : montant illisible (ex. 12,34).'; champs[cle].focus(); return; }
          const original = r[cle] === null || r[cle] === undefined ? null : Number(r[cle]);
          const change = saisi === null ? original !== null : original === null || Math.abs(saisi - original) >= 0.005;
          if (change) patch[cle] = saisi;
        }
        if (!Object.keys(patch).length) { toast('Aucune correction à enregistrer.', 'info'); return; }
        enregistrer.disabled = true;
        try {
          const corrige = await api.patch('/api/recus/' + encodeURIComponent(r.id), patch);
          if (ferme) return;
          afficherRecu(cible, corrige, null, urlImage, altImage);
          toast('Corrections enregistrées sur votre ordinateur.', 'ok');
          if (listeChargee) chargerRecus();
        } catch (err) {
          erreurFormulaire.textContent = messageErreur(err);
          enregistrer.disabled = false;
        }
      });

      supprimer.addEventListener('click', async () => {
        const ok = await confirmer('Supprimer ce reçu et sa photo de votre ordinateur ? Cette action ne peut pas être annulée.', { oui: 'Supprimer', non: 'Garder' });
        if (!ok) return;
        try {
          await api.delete('/api/recus/' + encodeURIComponent(r.id));
          if (ferme) return;
          cible.textContent = '';
          cible.append(el('p', { class: 'note' }, 'Reçu supprimé de votre ordinateur.'));
          toast('Reçu supprimé.', 'ok');
          if (listeChargee) chargerRecus();
        } catch (err) {
          toast(messageErreur(err), 'erreur');
        }
      });
    }
    cible.append(formulaire);

    const lignes = Array.isArray(r.lignes) ? r.lignes : [];
    if (lignes.length) {
      const liste = el('ul', { class: 'souvenirs' });
      lignes.slice(0, 60).forEach((l) => liste.append(el('li', {}, String(l.libelle || '') + ' — ' + argent(l.montant, r.devise))));
      cible.append(el('details', {}, el('summary', {}, 'Articles lus (' + lignes.length + ')'), liste));
    }
    cible.append(el('p', { class: 'note-faible' }, LIMITE_RECUS));
    return titre;
  }

  // ================================================================ mes reçus (sans lunettes)
  let generationListe = 0;
  async function chargerRecus() {
    listeChargee = true;
    const ma = ++generationListe;
    actualiser.disabled = true;
    resumeRecus.textContent = 'Chargement de vos reçus…';
    try {
      const d = await api.get('/api/recus');
      if (ferme || ma !== generationListe) return;
      const recus = Array.isArray(d && d.recus) ? d.recus : [];
      const t = (d && d.totaux) || {};
      listeRecus.textContent = '';
      if (!recus.length) {
        resumeRecus.textContent = 'Aucun reçu enregistré sur votre ordinateur.';
      } else {
        let resume = recus.length + (recus.length > 1 ? ' reçus enregistrés' : ' reçu enregistré') + ' sur votre ordinateur';
        if (t.nombre && typeof t.total === 'number' && t.devise) resume += ' ; total lu en ' + t.devise + ' : ' + argent(t.total, t.devise);
        if (t.sans_total) resume += ' (' + t.sans_total + ' sans total lu)';
        if (t.autres_devises && Object.keys(t.autres_devises).length) resume += ' ; autres devises comptées à part, jamais converties';
        resumeRecus.textContent = resume + '.';
      }
      recus.slice(0, RECUS_AFFICHES).forEach((r) => {
        const b = el('button', { type: 'button', class: 'choix' },
          el('span', { class: 'choix-titre' }, (r.commercant || 'Commerçant non lu') + ' — ' + argent(r.total, r.devise)),
          el('span', { class: 'choix-sous' }, [r.date ? jourLisible(r.date) : 'date non lue', r.categorie || 'Autre', r.corrige ? 'corrigé' : ''].filter(Boolean).join(' · ')));
        b.addEventListener('click', () => ouvrirRecu(r));
        listeRecus.append(b);
      });
      if (recus.length > RECUS_AFFICHES) {
        listeRecus.append(el('p', { class: 'note-faible' }, 'Les ' + RECUS_AFFICHES + ' plus récents sont affichés ici ; la liste complète et l’export sont dans IRIS sur l’ordinateur.'));
      }
      limiteListe.textContent = (d && d.limite) || LIMITE_RECUS;
    } catch (err) {
      if (ferme || ma !== generationListe) return;
      resumeRecus.textContent = err && err.status === 404
        ? "Les reçus ne sont pas disponibles sur votre ordinateur : mettez IRIS à jour."
        : messageErreur(err);
    } finally {
      if (!ferme && ma === generationListe) actualiser.disabled = false;
    }
  }

  async function ouvrirRecu(r) {
    detailRecu.hidden = false;
    detailRecu.textContent = '';
    detailRecu.append(el('p', { class: 'note' }, 'Ouverture du reçu…'));
    let url = '';
    if (r.image_nom) {
      try { url = URL.createObjectURL(await api.blob('/api/recus/' + encodeURIComponent(r.id) + '/image')); } catch (e) { url = ''; }
    }
    if (ferme) { if (url) URL.revokeObjectURL(url); return; }
    if (urlDetail) URL.revokeObjectURL(urlDetail);
    urlDetail = url;
    const titre = afficherRecu(detailRecu, r, null, url, 'Photo du reçu gardée sur votre ordinateur');
    if (r.image_nom && !url) detailRecu.insertBefore(el('p', { class: 'note-faible' }, 'Photo du reçu indisponible pour l’instant.'), titre.nextSibling);
    setTimeout(() => { try { titre.focus(); } catch (e) { /* rien */ } }, 30);
  }

  carteRecus.addEventListener('toggle', () => { if (carteRecus.open && !listeChargee) chargerRecus(); });
  actualiser.addEventListener('click', () => chargerRecus());

  // ================================================================ prix
  chercherNom.addEventListener('click', () => lancerComparaison(null));
  champProduit.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lancerComparaison(null); } });
  photoProduit.addEventListener('click', async () => {
    if (occupe) return;
    if (!lunettesConfirmees()) return;
    const fichier = await prendrePhoto();
    if (fichier && !ferme) lancerComparaison(fichier);
  });

  async function lancerComparaison(fichier) {
    if (occupe) return;
    const requete = champProduit.value.trim() || null;
    if (!fichier && !requete) { toast('Tapez le nom du produit, ou photographiez-le.', 'info'); champProduit.focus(); return; }
    if (!(await lunettesOk())) return;
    if (ferme || occupe) return;
    occuper(true);
    const debut = performance.now();
    resultatPrix.hidden = false;
    resultatPrix.textContent = '';
    const statut = el('p', { class: 'note' }, fichier ? 'Préparation de la photo…' : 'Recherche des prix…');
    resultatPrix.append(el('h3', {}, 'Comparaison de prix'), statut);
    let arreterChrono = () => {};
    try {
      let corpsRequete;
      if (fichier) {
        const image = await reduire(fichier, 1280);
        corpsRequete = { source: 'image', image: { media_type: image.media_type, data: image.data }, requete, parler: false };
        arreterChrono = chrono(statut, 'Identification du produit et recherche des prix…', debut);
      } else {
        corpsRequete = { source: 'texte', image: null, requete, parler: false };
        arreterChrono = chrono(statut, 'Recherche des prix…', debut);
      }
      const r = await api.post('/api/achats/comparer', corpsRequete, { delai: 120000 });
      arreterChrono();
      if (ferme) return;
      afficherPrix(r, performance.now() - debut);
      dire([r.resume, r.avertissement].filter(Boolean).join(' '));
    } catch (err) {
      arreterChrono();
      if (ferme) return;
      if (gardeActive && gardeActive.refus(err)) { resultatPrix.hidden = true; return; }
      resultatPrix.textContent = '';
      resultatPrix.append(el('h3', {}, 'Comparaison de prix'), el('p', { class: 'resultat-erreur' }, messageErreur(err)));
      const detail = err && err.detail && typeof err.detail === 'object' ? err.detail : null;
      if (detail && detail.description) resultatPrix.append(el('p', { class: 'note' }, 'Ce qui a été vu sur la photo : ' + detail.description));
      if (err && err.code === 'consentement') resultatPrix.append(el('p', { class: 'note' }, "Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité."));
      dire(messageErreur(err));
    } finally {
      occuper(false);
    }
  }

  function afficherPrix(r, totalMs) {
    resultatPrix.textContent = '';
    const p = (r && r.produit) || {};
    resultatPrix.append(el('h3', {}, p.nom || 'Produit'));
    const details = [];
    if (p.marque) details.push('marque : ' + p.marque);
    if (p.format) details.push('format : ' + p.format);
    if (p.code_barres) details.push('code-barres lu : ' + p.code_barres);
    if (p.prix_vu) details.push('prix vu sur place : ' + p.prix_vu);
    if (details.length) resultatPrix.append(el('p', { class: 'note' }, details.join(' · ')));
    if (r.avertissement) {
      const a = el('p', { class: 'note' }, r.avertissement);
      a.style.fontWeight = '600';
      resultatPrix.append(a);
    }
    if (r.resume) resultatPrix.append(el('p', { class: 'resultat-texte' }, r.resume));
    const offres = (Array.isArray(r.offres) ? r.offres : []).slice().sort((a, b) => (Number(a.prix) || 0) - (Number(b.prix) || 0));
    if (offres.length) {
      const liste = el('div', { class: 'liste-boutons' });
      offres.forEach((o) => {
        const carte = el('div', { class: 'carte' },
          el('p', { class: 'choix-titre' }, (o.marchand || 'Marchand') + ' — ' + argent(o.prix, o.devise)),
          o.extrait ? el('p', { class: 'choix-sous' }, 'Extrait : « ' + o.extrait + ' »') : null);
        if (/^https:\/\//.test(String(o.url || ''))) {
          carte.append(el('a', { href: o.url, target: '_blank', rel: 'noopener noreferrer' }, 'Ouvrir la page de ' + (o.marchand || 'ce marchand')));
        }
        liste.append(carte);
      });
      resultatPrix.append(liste);
    } else {
      resultatPrix.append(el('p', { class: 'note' }, 'Aucun prix en dollars canadiens n’a été trouvé dans les résultats de recherche.'));
    }
    const pied = [];
    if (typeof r.ecartees === 'number' && r.ecartees > 0) pied.push(r.ecartees + ' montant(s) écarté(s) : rabais, prix barrés, frais, autres devises ou valeurs aberrantes');
    if (typeof r.duree_ms === 'number') pied.push('recherche : ' + secondes(r.duree_ms));
    if (totalMs) pied.push('total mesuré depuis ce téléphone : ' + secondes(totalMs));
    if (pied.length) resultatPrix.append(el('p', { class: 'note-faible' }, pied.join(' ; ') + '.'));
  }

  // Un reçu ajouté ailleurs (voix, ordinateur) : la liste ouverte se met à jour.
  const desabonnements = [];
  if (bus && typeof bus.on === 'function') {
    desabonnements.push(bus.on('recu.nouveau', () => { if (listeChargee && !ferme) chargerRecus(); }));
  }

  return brancherNettoyage(ctx, () => {
    ferme = true;
    gardePrete.then((g) => g.fermer()).catch(() => null);
    desabonnements.forEach((f) => { try { f(); } catch (e) { /* déjà retiré */ } });
    chronos.forEach((id) => clearInterval(id));
    chronos.clear();
    entreePhoto.onchange = null;
    if (apercuUrl) { try { URL.revokeObjectURL(apercuUrl); } catch (e) { /* déjà libérée */ } apercuUrl = ''; }
    if (urlDetail) { try { URL.revokeObjectURL(urlDetail); } catch (e) { /* déjà libérée */ } urlDetail = ''; }
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<path d="M6 3.5h12v17l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3v-17Z"/><path d="M9 8h6M9 11.5h6M9 15h3.5"/></svg>';

const MODULE = {
  id: 'achats',
  titre: 'Reçus et prix',
  sous_titre: 'Garder un reçu, comparer un prix',
  icone: ICONE,
  ordre: 70,
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
