/* ==========================================================================
   VELA — vérificateur du registre de transparence IRIS (fichier réel)
   --------------------------------------------------------------------------
   Module autonome, sans dépendance. Il télécharge un registre exporté par
   IRIS (Confidentialité > Exporter JSON, ou GET /api/privacy/export), recalcule
   chaque empreinte SHA-256 dans le navigateur (crypto.subtle), vérifie le
   chaînage, et affiche le résultat. Rien n'est envoyé nulle part.

   Calcul (identique à ConsentGate._digest, backend/iris/consent.py) :
     empreinte = SHA-256 hexadécimal de
       [précédente ou "", created_at, event_type, data_type ou "", agent ou "", detail ou ""].join("|")
   Une entrée est valide si son empreinte recalculée est égale à « hash » ET si
   « prev_hash » est égal à l'empreinte de l'entrée précédente ("" pour la première).
   Entrées sans empreinte (hash null, antérieures à la chaîne) : tolérées tant
   qu'aucune entrée avec empreinte ne les précède, la chaîne repart de "".
   Écart volontaire avec ConsentGate.verify (ajouté 2026-09-14) : une entrée sans
   empreinte qui SUIT une entrée qui en a une est comptée comme une rupture
   (sinon, effacer l'empreinte de la dernière ligne passait pour « intègre »).
   Si l'empreinte annoncée dans le fichier (verification.last_hash) diffère de
   la chaîne recalculée, l'écart est affiché.

   Balisage :
     <div class="demo" data-registre="assets/preuves/registre.json"
          data-empreinte-finale="<empreinte publiée, facultatif>"
          data-fichier-local            (facultatif : vérifier son propre fichier)
          data-t-integre="Chaîne intègre" ...>
     </div>
   Tous les textes se remplacent par des attributs data-t-* (français par défaut),
   voir TEXTES ci-dessous. Gabarits : {n} position, {id} identifiant, {k} nombre,
   {champ} {avant} {apres} {detail}.

   Ce que la vérification prouve : que le contenu du fichier est cohérent avec ses
   empreintes, et (si data-empreinte-finale est fourni) qu'il est identique à celui
   dont l'empreinte a été publiée. Elle ne prouve pas, à elle seule, QUI a produit
   le fichier : quiconque connaît la formule peut fabriquer une chaîne cohérente.
   ========================================================================== */
(function (racine) {
  'use strict';

  var TEXTES = {
    chargement: 'Chargement du registre…',
    calcul: 'Recalcul des empreintes SHA-256 dans votre navigateur…',
    integre: 'Chaîne intègre : {k} entrées recalculées, chaque empreinte correspond à son contenu et à l’entrée précédente.',
    alteree: 'Chaîne rompue à l’entrée n° {n} (identifiant {id}) : {detail}.',
    raisonEmpreinte: 'son contenu ne correspond plus à son empreinte',
    raisonChainage: 'elle ne pointe plus vers l’empreinte de l’entrée précédente',
    raisonSansEmpreinte: 'elle n’a pas d’empreinte, alors qu’une entrée précédente en a une',
    annonceKo: 'L’empreinte annoncée dans le fichier ne correspond pas à la chaîne recalculée.',
    ancreOk: 'Empreinte finale identique à celle publiée sur cette page.',
    ancreKo: 'La chaîne est cohérente, mais son empreinte finale diffère de celle publiée sur cette page : ce n’est pas le fichier publié.',
    sansAncre: 'Sans empreinte de référence, cela prouve la cohérence du fichier, pas qu’il n’a jamais été réécrit en entier : comparez son empreinte finale à celle qu’IRIS affiche dans Confidentialité (Vérifier maintenant), juste avant l’export.',
    sansEmpreinte: '{k} entrée(s) antérieure(s) à la chaîne, sans empreinte (tolérées, comme dans IRIS).',
    vide: 'Registre vide : aucune entrée à vérifier.',
    entrees: 'Entrées',
    premiere: 'Première empreinte',
    derniere: 'Dernière empreinte',
    horodatage: 'Horodatage (UTC)',
    heureLocale: 'À l’heure de votre appareil',
    voirEntrees: 'Voir les {k} entrées',
    empreinte: 'empreinte : ',
    alterer: 'Altérer une entrée pour voir',
    retablir: 'Rétablir le fichier publié',
    copie: 'Copie en mémoire : à l’entrée n° {n}, le champ « {champ} » passe de « {avant} » à « {apres} ». Le fichier publié n’est pas modifié.',
    marqueAlteree: 'modifiée en mémoire',
    telecharger: 'Télécharger le fichier (.json)',
    fichierLocal: 'Vérifier votre propre registre exporté (le fichier reste dans votre navigateur)',
    fichierLocalNom: 'Fichier vérifié : {detail}',
    erreurChargement: 'Impossible de charger le registre ({detail}).',
    erreurFormat: 'Ce fichier n’a pas la forme d’un registre IRIS (liste « events » absente ou illisible).',
    erreurCrypto: 'Ce navigateur ne fournit pas le calcul SHA-256 sur cette page (crypto.subtle exige une connexion https).'
  };

  /* ------------------------------------------------------------ calcul pur */

  function hex(tampon) {
    var octets = new Uint8Array(tampon);
    var s = '';
    for (var i = 0; i < octets.length; i++) s += ('0' + octets[i].toString(16)).slice(-2);
    return s;
  }

  function subtle() {
    var c = (typeof crypto !== 'undefined' && crypto) || (racine && racine.crypto);
    return c && c.subtle ? c.subtle : null;
  }

  function sha256Hex(texte) {
    var s = subtle();
    if (!s) return Promise.reject(new Error('crypto.subtle indisponible'));
    return s.digest('SHA-256', new TextEncoder().encode(texte)).then(hex);
  }

  function texteOuVide(v) {
    return v === null || v === undefined ? '' : String(v);
  }

  /* Chaîne hachée d'une entrée — miroir exact de ConsentGate._digest. */
  function chargeUtile(precedente, ev) {
    return [
      precedente || '',
      texteOuVide(ev.created_at),
      texteOuVide(ev.event_type),
      texteOuVide(ev.data_type),
      texteOuVide(ev.agent),
      texteOuVide(ev.detail)
    ].join('|');
  }

  /* Vérifie un registre déjà analysé (objet JSON).
     Résultat : { etat: 'integre' | 'alteree' | 'ancre' | 'format' | 'vide',
                  nombre, sansEmpreinte, premiere, derniere, index, id, raison,
                  annoncee, conformeAnnonce, conformeAncre } */
  async function verifierRegistre(doc, options) {
    options = options || {};
    var evenements = doc && Array.isArray(doc.events) ? doc.events : null;
    if (!evenements) return { etat: 'format', nombre: 0 };

    var res = {
      etat: 'integre',
      nombre: evenements.length,
      sansEmpreinte: 0,
      premiere: null,
      derniere: null,
      index: -1,
      id: null,
      raison: null,
      annoncee: doc.verification && doc.verification.last_hash ? doc.verification.last_hash : null,
      conformeAnnonce: null,
      conformeAncre: null
    };
    if (!evenements.length) { res.etat = 'vide'; return res; }

    var precedente = '';
    for (var i = 0; i < evenements.length; i++) {
      var ev = evenements[i] || {};
      if (ev.hash === null || ev.hash === undefined) {
        if (res.premiere !== null) {
          // Une entrée sans empreinte après le début de la chaîne n'est pas « antérieure » :
          // c'est une empreinte effacée (ou une ligne ajoutée hors chaîne).
          res.etat = 'alteree';
          res.index = i;
          res.id = ev.id === undefined ? null : ev.id;
          res.raison = 'sansEmpreinte';
          return res;
        }
        res.sansEmpreinte++;
        precedente = '';
        continue;
      }
      var attendue = await sha256Hex(chargeUtile(precedente, ev));
      var bonChainage = texteOuVide(ev.prev_hash) === precedente;
      if (attendue !== ev.hash || !bonChainage) {
        res.etat = 'alteree';
        res.index = i;
        res.id = ev.id === undefined ? null : ev.id;
        // Lien rompu (entrée retirée, insérée ou déplacée) avant contenu retouché.
        res.raison = bonChainage ? 'empreinte' : 'chainage';
        return res;
      }
      if (res.premiere === null) res.premiere = ev.hash;
      precedente = ev.hash;
    }
    res.derniere = precedente || null;
    if (res.annoncee) res.conformeAnnonce = res.annoncee === res.derniere;
    if (options.empreinteAttendue) {
      res.conformeAncre = options.empreinteAttendue.toLowerCase() === texteOuVide(res.derniere).toLowerCase();
      if (!res.conformeAncre) res.etat = 'ancre';
    }
    return res;
  }

  /* Copie modifiée d'un registre, pour la démonstration de détection.
     Préférence : faire passer un retrait de consentement (« …_revoked ») pour un
     accord (« …_granted ») — la falsification qu'on voudrait cacher. Sinon, on
     retouche le champ « detail » de l'entrée du milieu. */
  function alterer(doc) {
    var copie = JSON.parse(JSON.stringify(doc));
    var evs = copie.events || [];
    var avecEmpreinte = [];
    for (var i = 0; i < evs.length; i++) if (evs[i] && evs[i].hash) avecEmpreinte.push(i);
    if (!avecEmpreinte.length) return null;

    for (var j = 0; j < avecEmpreinte.length; j++) {
      var e = evs[avecEmpreinte[j]];
      if (typeof e.event_type === 'string' && /_revoked$/.test(e.event_type)) {
        var avant = e.event_type;
        e.event_type = avant.replace(/_revoked$/, '_granted');
        return { copie: copie, index: avecEmpreinte[j], champ: 'event_type', avant: avant, apres: e.event_type };
      }
    }
    var k = avecEmpreinte[Math.floor(avecEmpreinte.length / 2)];
    var avantDetail = texteOuVide(evs[k].detail);
    evs[k].detail = avantDetail + ' [modifié]';
    return { copie: copie, index: k, champ: 'detail', avant: avantDetail, apres: evs[k].detail };
  }

  function abreger(empreinte) {
    if (!empreinte) return '—';
    // 16 premiers caractères, comme l'écran Confidentialité d'IRIS, puis les 8 derniers.
    return empreinte.length > 24 ? empreinte.slice(0, 16) + '…' + empreinte.slice(-8) : empreinte;
  }

  function gabarit(modele, valeurs) {
    return String(modele).replace(/\{(\w+)\}/g, function (m, cle) {
      return Object.prototype.hasOwnProperty.call(valeurs, cle) ? String(valeurs[cle]) : m;
    });
  }

  var api = {
    chargeUtile: chargeUtile,
    sha256Hex: sha256Hex,
    verifierRegistre: verifierRegistre,
    alterer: alterer,
    abreger: abreger,
    TEXTES: TEXTES
  };

  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (racine) racine.VelaRegistre = api;
  if (typeof document === 'undefined') return;

  /* ------------------------------------------------------------ affichage */

  function el(balise, classe, texte) {
    var n = document.createElement(balise);
    if (classe) n.className = classe;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }

  function textes(conteneur) {
    var t = {};
    Object.keys(TEXTES).forEach(function (cle) {
      // data-t-raison-empreinte -> dataset.tRaisonEmpreinte
      var nom = 't' + cle.charAt(0).toUpperCase() + cle.slice(1);
      t[cle] = conteneur.dataset[nom] || TEXTES[cle];
    });
    return t;
  }

  function heureLocale(iso, langue) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    try {
      return d.toLocaleString(langue || undefined, { dateStyle: 'long', timeStyle: 'short' });
    } catch (e) {
      return d.toLocaleString();
    }
  }

  function monter(conteneur) {
    var t = textes(conteneur);
    var url = conteneur.getAttribute('data-registre');
    var ancrePubliee = conteneur.getAttribute('data-empreinte-finale') || null;
    var langue = document.documentElement.lang || 'fr';

    var original = null;     // registre tel que téléchargé
    var alteration = null;   // { copie, index, champ, avant, apres } quand la démo est active
    var ancre = ancrePubliee;
    var tour = 0;            // ignore les vérifications dépassées

    conteneur.textContent = '';
    var tete = el('div', 'demo-head');
    var titre = el('span', 'grow small muted', url ? url.split('/').pop() : '');
    var lien = el('a', 'btn sm', t.telecharger);
    if (url) { lien.href = url; lien.setAttribute('download', ''); } else { lien.hidden = true; }
    var bouton = el('button', 'btn primary sm', t.alterer);
    bouton.type = 'button';
    bouton.disabled = true;
    tete.appendChild(titre);
    tete.appendChild(lien);
    tete.appendChild(bouton);

    var corps = el('div', 'demo-body');
    var etat = el('p', 'demo-status', t.chargement);
    etat.setAttribute('role', 'status');
    etat.setAttribute('aria-live', 'polite');

    conteneur.appendChild(tete);
    conteneur.appendChild(corps);
    conteneur.appendChild(etat);

    if (conteneur.hasAttribute('data-fichier-local')) {
      var etiquette = el('label', 'small muted');
      etiquette.style.display = 'block';
      etiquette.style.marginTop = '14px';
      etiquette.appendChild(document.createTextNode(t.fichierLocal + ' '));
      var champ = el('input');
      champ.type = 'file';
      champ.accept = 'application/json,.json';
      etiquette.appendChild(champ);
      conteneur.appendChild(etiquette);
      champ.addEventListener('change', function () {
        var f = champ.files && champ.files[0];
        if (!f) return;
        f.text().then(function (brut) {
          alteration = null;
          ancre = null; // l'empreinte publiée ne concerne que le fichier publié
          titre.textContent = gabarit(t.fichierLocalNom, { detail: f.name });
          lien.hidden = true;
          analyser(brut);
        });
      });
    }

    function ligneFait(libelle, valeur, mono) {
      var p = el('p', 'small');
      p.style.margin = '0';
      p.appendChild(el('span', 'muted', libelle + ' : '));
      p.appendChild(el('b', mono ? 'mono' : '', valeur));
      return p;
    }

    function dessiner(doc, res) {
      corps.textContent = '';
      var evs = doc.events || [];
      corps.appendChild(ligneFait(t.entrees, String(evs.length)));
      corps.appendChild(ligneFait(t.premiere, abreger(res.premiere), true));
      corps.appendChild(ligneFait(t.derniere, abreger(res.derniere), true));
      var dates = evs.map(function (e) { return e && e.created_at; }).filter(Boolean);
      if (dates.length) {
        var debut = dates[0];
        var fin = dates[dates.length - 1];
        corps.appendChild(ligneFait(t.horodatage, debut === fin ? debut : debut + ' → ' + fin, true));
        var ld = heureLocale(debut, langue);
        var lf = heureLocale(fin, langue);
        if (ld) corps.appendChild(ligneFait(t.heureLocale, ld === lf ? ld : ld + ' → ' + lf));
      }
      if (res.sansEmpreinte) {
        corps.appendChild(el('p', 'small muted', gabarit(t.sansEmpreinte, { k: res.sansEmpreinte })));
      }

      var plis = el('details', 'plus');
      plis.style.marginTop = '8px';
      if (res.etat === 'alteree') plis.open = true;
      plis.appendChild(el('summary', '', gabarit(t.voirEntrees, { k: evs.length })));
      var liste = el('div', 'plus-body demo-body');
      evs.forEach(function (e, i) {
        e = e || {};
        // Seule l'entrée où la vérification échoue est marquée : la vérification s'arrête là,
        // les suivantes ne sont plus garanties mais n'ont pas été modifiées pour autant.
        var casse = res.etat === 'alteree' && i === res.index;
        var rangee = el('div', 'entry' + (casse ? ' broken' : ''));
        rangee.appendChild(el('div', 'idx', '#' + (i + 1)));
        var b = el('div', 'body');
        var ligne = el('div', 'line');
        ligne.appendChild(el('span', 'what mono', texteOuVide(e.event_type)));
        ligne.appendChild(el('span', 'when', texteOuVide(e.created_at)));
        if (alteration && alteration.index === i) ligne.appendChild(el('span', 'pill err', t.marqueAlteree));
        b.appendChild(ligne);
        var infos = [e.data_type, e.agent, e.detail].map(texteOuVide).filter(function (x) { return x; });
        if (infos.length) b.appendChild(el('div', 'small muted', infos.join(' · ')));
        var h = el('div', 'hash');
        h.appendChild(document.createTextNode(t.empreinte));
        h.appendChild(el('b', '', texteOuVide(e.hash) || '—'));
        b.appendChild(h);
        rangee.appendChild(b);
        liste.appendChild(rangee);
      });
      plis.appendChild(liste);
      corps.appendChild(plis);
    }

    function afficherEtat(res) {
      var lignes = [];
      var classe = 'demo-status';
      if (res.etat === 'integre') {
        classe += ' ok';
        lignes.push(gabarit(t.integre, { k: res.nombre }));
        lignes.push(res.conformeAncre === true ? t.ancreOk : t.sansAncre);
        if (res.conformeAnnonce === false) lignes.push(t.annonceKo);
      } else if (res.etat === 'ancre') {
        classe += ' bad';
        lignes.push(t.ancreKo);
        if (res.conformeAnnonce === false) lignes.push(t.annonceKo);
      } else if (res.etat === 'alteree') {
        classe += ' bad';
        lignes.push(gabarit(t.alteree, {
          n: res.index + 1,
          id: res.id === null ? '—' : res.id,
          detail: res.raison === 'empreinte' ? t.raisonEmpreinte
            : (res.raison === 'sansEmpreinte' ? t.raisonSansEmpreinte : t.raisonChainage)
        }));
      } else if (res.etat === 'vide') {
        lignes.push(t.vide);
      } else {
        classe += ' bad';
        lignes.push(t.erreurFormat);
      }
      if (alteration) {
        lignes.push(gabarit(t.copie, {
          n: alteration.index + 1, champ: alteration.champ, avant: alteration.avant, apres: alteration.apres
        }));
      }
      etat.className = classe;
      etat.textContent = lignes.join(' ');
    }

    function verifier(doc) {
      var monTour = ++tour;
      etat.className = 'demo-status';
      etat.textContent = t.calcul;
      bouton.disabled = true;
      return verifierRegistre(doc, { empreinteAttendue: ancre })
        .then(function (res) {
          if (monTour !== tour) return;
          dessiner(doc, res);
          afficherEtat(res);
          bouton.disabled = !original || res.etat === 'format' || res.etat === 'vide';
          bouton.textContent = alteration ? t.retablir : t.alterer;
        })
        .catch(function () {
          if (monTour !== tour) return;
          etat.className = 'demo-status bad';
          etat.textContent = t.erreurCrypto;
        });
    }

    function analyser(brut) {
      var doc;
      try { doc = JSON.parse(brut); } catch (e) { doc = null; }
      original = doc && Array.isArray(doc.events) ? doc : null;
      if (!original) {
        corps.textContent = '';
        etat.className = 'demo-status bad';
        etat.textContent = t.erreurFormat;
        bouton.disabled = true;
        return;
      }
      verifier(original);
    }

    bouton.addEventListener('click', function () {
      if (!original) return;
      if (alteration) {
        alteration = null;
        verifier(original);
      } else {
        alteration = alterer(original);
        verifier(alteration ? alteration.copie : original);
      }
    });

    if (!subtle()) {
      etat.className = 'demo-status bad';
      etat.textContent = t.erreurCrypto;
      return;
    }
    if (!url) return;
    fetch(url, { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      })
      .then(analyser)
      .catch(function (err) {
        etat.className = 'demo-status bad';
        etat.textContent = gabarit(t.erreurChargement, { detail: err && err.message ? err.message : String(err) });
      });
  }

  function demarrer() {
    var cibles = document.querySelectorAll('[data-registre]');
    for (var i = 0; i < cibles.length; i++) monter(cibles[i]);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : null));
