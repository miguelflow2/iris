/* IRIS — mode invité, en un geste depuis le téléphone.
 *
 * Pour prêter IRIS (ou ses lunettes) sans qu'elle retienne quoi que ce soit de la session : la mémoire
 * est suspendue sur l'ordinateur, et à la fin les conversations de la session sont effacées. Une
 * minuterie ramène IRIS à la normale après la durée choisie (réglage mode_invite_minutes, 5 à 720).
 *
 * Un seul très grand bouton, parce qu'on active ce mode au moment où quelqu'un tend la main vers les
 * lunettes. Le temps restant est calculé à partir de l'échéance que donne l'ordinateur ; ce que le mode
 * ne fait PAS (cacher les souvenirs existants, effacer rappels et tâches) est affiché tel que
 * l'ordinateur le dit (champ « limite »).
 */

const DUREES = [30, 60, 120, 240];

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
/** « 15 h 20 » : l'heure d'une échéance ISO, à l'heure de ce téléphone. */
function heure(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.getHours() + ' h ' + String(d.getMinutes()).padStart(2, '0');
}
function dureeLisible(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 60) return m + (m > 1 ? ' minutes' : ' minute');
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h + ' h' + (r ? ' ' + String(r).padStart(2, '0') : '');
}

// ------------------------------------------------------------------ le panneau
function ouvrir(ctx) {
  const corps = ctx.corps;
  const IRIS = IRISv();
  const api = IRIS.api;
  const bus = IRIS.bus;

  let etat = null;          // dernière réponse de l'ordinateur
  let echeance = 0;         // ms, selon l'échéance ISO de l'ordinateur
  let occupe = false;
  let ferme = false;
  let minuterie = null;
  let dureeChoisie = null;  // null : la durée réglée sur l'ordinateur

  const statut = el('div', { class: 'resultat', role: 'status', 'aria-live': 'polite' });
  const statutTitre = el('p', { class: 'resultat-texte' }, 'Vérification…');
  statutTitre.style.fontSize = '1.6rem';
  statutTitre.style.fontWeight = '700';
  const statutDetail = el('p', { class: 'note' });
  statut.append(statutTitre, statutDetail);

  const grandBouton = el('button', { type: 'button', class: 'holo', disabled: true }, 'Mode invité');
  grandBouton.style.minHeight = '38vh';
  grandBouton.style.fontSize = '2rem';
  grandBouton.style.borderRadius = '28px';

  const groupeDuree = el('fieldset', { class: 'segmente' }, el('legend', {}, 'Durée avant le retour automatique à la normale'));
  const limite = el('p', { class: 'note-faible' });
  const resultatFin = el('p', { class: 'note', 'aria-live': 'polite' });

  corps.append(
    el('p', { class: 'note' }, "Pour prêter IRIS ou ses lunettes : pendant le mode invité, IRIS ne retient rien de la session, et ses conversations sont effacées à la fin."),
    statut, grandBouton, resultatFin, el('div', { class: 'carte' }, groupeDuree), el('div', { class: 'carte' }, el('h3', {}, 'Ce que le mode ne fait pas'), limite),
    el('p', { class: 'note-faible' }, "À la voix, sur l'ordinateur ou les lunettes : « Iris, mode invité ». « Iris, fin du mode invité » n'est acceptée à la voix qu'avec le verrou vocal actif (pas encore offert) : sinon, terminez le mode ici ou il se termine tout seul à l'heure prévue."));

  if (!api) {
    statutTitre.textContent = 'La liaison avec votre ordinateur n’est pas prête : fermez puis rouvrez ce panneau.';
    return () => {};
  }

  function dessinerDurees(defaut) {
    groupeDuree.querySelectorAll('label').forEach((l) => l.remove());
    const options = [[null, 'Réglage de l’ordinateur (' + dureeLisible(defaut) + ')']].concat(DUREES.map((m) => [m, dureeLisible(m)]));
    options.forEach(([valeur, libelle], i) => {
      const id = 'invite-duree-' + i;
      const radio = el('input', { type: 'radio', name: 'invite-duree', id, value: valeur === null ? '' : String(valeur) });
      radio.checked = valeur === dureeChoisie;
      radio.addEventListener('change', () => { if (radio.checked) dureeChoisie = valeur; });
      groupeDuree.append(el('label', { for: id }, radio, el('span', { class: 'rangee-titre' }, libelle)));
    });
  }

  function dessiner() {
    const actif = !!(etat && etat.actif);
    grandBouton.disabled = occupe || !etat;
    grandBouton.textContent = actif ? 'Terminer le mode invité' : 'Activer le mode invité';
    grandBouton.classList.toggle('rouge', actif);
    groupeDuree.parentElement.hidden = actif;
    if (!etat) return;
    if (etat.limite) limite.textContent = etat.limite;
    if (actif) {
      const restantMin = echeance ? Math.max(0, Math.ceil((echeance - Date.now()) / 60000)) : Number(etat.minutes_restantes) || 0;
      statutTitre.textContent = 'Mode invité actif';
      statutDetail.textContent = 'IRIS ne retient rien jusqu’à ' + heure(etat.jusqua) + ' (encore ' + dureeLisible(restantMin) + '), puis revient seule à la normale.' +
        (etat.depuis ? ' Actif depuis ' + heure(etat.depuis) + '.' : '');
    } else {
      statutTitre.textContent = 'Mode invité désactivé';
      statutDetail.textContent = 'IRIS retient normalement.';
    }
  }

  function appliquer(d) {
    if (!d || typeof d !== 'object') return;
    etat = d;
    const t = d.jusqua ? new Date(d.jusqua).getTime() : NaN;
    echeance = Number.isFinite(t) ? t : 0;
    dessiner();
  }

  async function charger() {
    try {
      appliquer(await api.get('/api/confiance/invite'));
    } catch (err) {
      statutTitre.textContent = err && err.status === 404
        ? "Le mode invité n'est pas disponible sur votre ordinateur : mettez IRIS à jour."
        : (err && err.message) || String(err);
      grandBouton.disabled = true;
    }
  }

  grandBouton.addEventListener('click', async () => {
    if (occupe || !etat) return;
    const activer = !etat.actif;
    if (!activer) {
      const ok = await confirmer('Terminer le mode invité ? Les conversations de la session seront effacées et IRIS retiendra de nouveau.',
        { oui: 'Terminer', non: 'Continuer' });
      if (!ok) return;
    }
    occupe = true;
    resultatFin.textContent = '';
    dessiner();
    try {
      if (activer) {
        const d = await api.post('/api/confiance/invite/activer', { minutes: dureeChoisie });
        if (ferme) return;
        appliquer(d);
        const phrase = 'Mode invité activé jusqu’à ' + heure(d.jusqua) + ' : IRIS ne retient rien de cette session.';
        toast(phrase, 'ok');
        dire(phrase);
      } else {
        const d = await api.post('/api/confiance/invite/desactiver', {}, { delai: 60000 });
        if (ferme) return;
        appliquer(d);
        const e = d.effacees || {};
        let phrase;
        if (e.erreurs) {
          phrase = "Mode invité terminé, mais une partie de la session n'a pas pu être effacée : vérifiez l'historique des conversations sur l'ordinateur.";
          toast(phrase, 'alerte');
        } else {
          phrase = 'Mode invité terminé : ' + (Number(e.conversations) || 0) + ' conversation(s) et ' + (Number(e.messages) || 0) +
            ' message(s) de la session effacés. IRIS retient de nouveau.';
          toast('Mode invité terminé.', 'ok');
        }
        resultatFin.textContent = phrase;
        dire(phrase);
      }
    } catch (err) {
      toast((err && err.message) || String(err), 'erreur');
      await charger();
    } finally {
      occupe = false;
      dessiner();
    }
  });

  const desabonnements = [];
  if (bus && typeof bus.on === 'function') {
    // Activé ou terminé ailleurs (voix, ordinateur, minuterie) : on relit l'état complet.
    desabonnements.push(bus.on('invite.etat', () => { if (!occupe) charger(); }));
  }
  minuterie = setInterval(() => {
    if (!etat || !etat.actif) return;
    if (echeance && Date.now() > echeance + 15000) charger();   // la minuterie de l'ordinateur a dû finir
    else dessiner();
  }, 15000);

  api.get('/api/settings').then((s) => {
    if (!ferme) dessinerDurees(Number(s && s.mode_invite_minutes) || 120);
  }).catch(() => { if (!ferme) dessinerDurees(120); });
  charger();

  return brancherNettoyage(ctx, () => {
    ferme = true;
    clearInterval(minuterie);
    desabonnements.forEach((f) => { try { f(); } catch (e) { /* déjà retiré */ } });
  });
}

// ------------------------------------------------------------------ enregistrement
const ICONE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
  '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 6.5h5M16 10h5M18.5 13.5v5"/></svg>';

const MODULE = {
  id: 'invite',
  titre: 'Mode invité',
  sous_titre: 'Prêter IRIS sans rien retenir',
  icone: ICONE,
  ordre: 65,
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
