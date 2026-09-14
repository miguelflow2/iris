/* =========================================================================
   VELA — site public. Aucun réseau, aucune dépendance : le site fonctionne
   ouvert directement depuis le disque.
   1. Menu de navigation sur téléphone.
   2. Démonstration du registre chaîné : SHA-256 calculé ici, dans la page.
      (SubtleCrypto n'existe pas sur file://, d'où cette implémentation.)
   ========================================================================= */
(function () {
  'use strict';

  /* --------------------------------------------------------- menu mobile */
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  /* ------------------------------------------------ barre d'achat collante
     Accueil et fiche produit : une barre discrète (prix + rassurance +
     « Précommander ») apparaît une fois le premier écran dépassé, jamais
     avant. On l'affiche par une classe (pas l'attribut hidden) pour garder la
     transition ; « mouvement réduit » la neutralise via la CSS. */
  var achat = document.querySelector('[data-sticky-buy]');
  if (achat) {
    achat.hidden = false;
    var seuil = function () { return Math.max(320, window.innerHeight * 0.6); };
    var majAchat = function () {
      if (window.pageYOffset > seuil()) achat.classList.add('show');
      else achat.classList.remove('show');
    };
    window.addEventListener('scroll', majAchat, { passive: true });
    window.addEventListener('resize', majAchat, { passive: true });
    majAchat();
  }

  /* ------------------------------------------------- formulaire de contact
     Site statique, aucun service tiers : à la soumission on construit un lien
     mailto: pré-rempli et on ouvre le logiciel de courriel du visiteur. */
  var COURRIEL = 'contact@velaglass.ca';
  var form = document.getElementById('form-contact');
  if (form) {
    var reponse = document.getElementById('reponse');

    var montrerErreur = function (champ, actif) {
      var msg = document.getElementById('err-' + champ.id);
      if (msg) msg.hidden = !actif;
      champ.classList.toggle('invalide', actif);
      champ.setAttribute('aria-invalid', actif ? 'true' : 'false');
    };

    // Volontairement permissif : refuser une adresse valide serait pire que l'inverse.
    var courrielValide = function (v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v); };

    // Repli de copie pour les navigateurs sans navigator.clipboard (contexte non
    // sécurisé, page ouverte depuis le disque en file://, navigateurs anciens) :
    // une zone de texte cachée, sélectionnée, puis execCommand('copy'). Renvoie
    // true si la copie a réussi.
    var copieDeSecours = function (texte) {
      try {
        var zone = document.createElement('textarea');
        zone.value = texte;
        zone.setAttribute('readonly', '');
        zone.style.position = 'fixed';
        zone.style.top = '-9999px';
        document.body.appendChild(zone);
        zone.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(zone);
        return ok;
      } catch (e) {
        return false;
      }
    };

    // Copie l'adresse dans le presse-papiers. On privilégie l'API moderne, et on
    // retombe sur le repli si elle est absente ou refusée. Le rappel reçoit true
    // en cas de succès, false sinon, pour ajuster le message de confirmation.
    var copierCourriel = function (texte, rappel) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texte).then(
          function () { rappel(true); },
          function () { rappel(copieDeSecours(texte)); }
        );
        return;
      }
      rappel(copieDeSecours(texte));
    };

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var nom = document.getElementById('nom');
      var courriel = document.getElementById('courriel');
      var sujet = document.getElementById('sujet');
      var message = document.getElementById('message');

      var manquants = [];
      var check = function (champ, ok) { montrerErreur(champ, !ok); if (!ok) manquants.push(champ); };
      check(nom, nom.value.trim().length > 0);
      check(courriel, courrielValide(courriel.value.trim()));
      check(message, message.value.trim().length > 0);

      if (manquants.length) {
        reponse.hidden = false;
        reponse.className = 'form-reponse erreur';
        reponse.textContent = 'Il manque quelque chose : complétez les champs signalés, puis réessayez.';
        manquants[0].focus();
        return;
      }

      // CRLF partout, y compris dans le texte saisi : c'est ce que tous les logiciels de
      // courriel interprètent correctement en sauts de ligne.
      var corps = [
        'Nom : ' + nom.value.trim(),
        'Courriel : ' + courriel.value.trim(),
        'Sujet : ' + sujet.value,
        '',
        message.value.trim().replace(/\r\n|\r|\n/g, '\r\n'),
        '',
        '— Envoyé depuis le formulaire du site VELA'
      ].join('\r\n');

      var lien = 'mailto:' + COURRIEL
        + '?subject=' + encodeURIComponent('VELA — ' + sujet.value)
        + '&body=' + encodeURIComponent(corps);

      // Beaucoup de visiteurs n'ont pas de logiciel de courriel branché sur leur
      // navigateur (Gmail dans un onglet, par exemple) : pour eux, le lien mailto
      // ne fait rien. On affiche donc TOUJOURS l'adresse en clair et un bouton
      // pour la copier, en plus de la tentative d'ouverture — personne ne reste
      // devant un bouton qui semble mort.
      // (#reponse est un <p> : on n'y met que des éléments en ligne, jamais de bloc.)
      reponse.hidden = false;
      reponse.className = 'form-reponse succes';
      reponse.textContent = '';
      reponse.appendChild(document.createTextNode(
        'Nous tentons d’ouvrir votre logiciel de courriel avec le message déjà rédigé. '
        + 'Si rien ne s’ouvre — c’est fréquent depuis un navigateur — écrivez-nous directement à '));
      var direct = document.createElement('a');
      direct.href = 'mailto:' + COURRIEL;
      direct.textContent = COURRIEL;
      reponse.appendChild(direct);
      reponse.appendChild(document.createTextNode('. '));

      reponse.appendChild(document.createElement('br'));

      // Le message de copie vit à côté du bouton ; il reste vide tant qu'on n'a
      // rien copié. #reponse étant déjà une zone aria-live, son contenu ajouté
      // est annoncé sans avoir à en refaire une ici.
      var copie = document.createElement('span');
      copie.className = 'small muted';

      var boutonCopier = document.createElement('button');
      boutonCopier.type = 'button';
      boutonCopier.className = 'btn sm';
      boutonCopier.textContent = 'Copier l’adresse';
      boutonCopier.addEventListener('click', function () {
        copierCourriel(COURRIEL, function (ok) {
          copie.textContent = ok
            ? ' Adresse copiée.'
            : ' Copie impossible : sélectionnez l’adresse ci-dessus, puis Ctrl+C.';
        });
      });
      reponse.appendChild(boutonCopier);
      reponse.appendChild(document.createTextNode(' '));

      var secours = document.createElement('a');
      secours.href = lien;
      secours.id = 'lien-secours';
      secours.textContent = 'Rouvrir le message pré-rédigé';
      reponse.appendChild(secours);
      reponse.appendChild(copie);

      window.location.href = lien;
    });

    // On efface le signalement dès que la personne corrige son champ.
    ['nom', 'courriel', 'message'].forEach(function (id) {
      var champ = document.getElementById(id);
      if (champ) champ.addEventListener('input', function () { montrerErreur(champ, false); });
    });
  }

  /* ------------------------------------ sujet pré-choisi (?objet=…)
     Ajouté le 2026-09-13 : un lien comme contact.html?objet=Premier%20testeur
     pré-sélectionne le sujet correspondant dans la liste « Sujet », s'il
     existe. Rien d'autre n'est lu dans l'adresse, et rien n'y est écrit. */
  var champSujet = document.getElementById('sujet');
  if (champSujet && window.location && window.location.search) {
    try {
      var objet = new URLSearchParams(window.location.search).get('objet');
      if (objet) {
        for (var io = 0; io < champSujet.options.length; io++) {
          if (champSujet.options[io].text === objet || champSujet.options[io].value === objet) {
            champSujet.selectedIndex = io;
            break;
          }
        }
      }
    } catch (e) { /* navigateur sans URLSearchParams : le sujet reste au choix par défaut */ }
  }

  /* --------------------------------------------------- suivi de commande
     Page suivi.html. Deux comportements, selon qu'un serveur de suivi existe :

       ADRESSE_SUIVI vide (aujourd'hui) — aucun appel réseau. Le formulaire
         redit à la personne ce qu'elle a saisi et l'oriente vers le courriel.
         Il n'affiche AUCUN état, AUCUNE date : on ne sait rien, on le dit.

       ADRESSE_SUIVI renseignée — un POST JSON, et la fiche est remplie avec ce
         que le serveur renvoie, sans jamais rien compléter ni calculer. Un
         champ absent s'écrit « inconnue » ; il ne se devine pas.

     Trois choses à ne pas casser en modifiant ce bloc :
       1. POST, jamais GET. Le numéro de commande et le courriel ne doivent
          apparaître ni dans l'adresse de la page, ni dans un journal de serveur.
       2. Rien n'est écrit dans location ni dans history : cette page reste
          partageable sans fuite.
       3. Tout l'affichage passe par textContent. Le serveur est une source
          externe : son texte ne devient jamais du HTML.

     Le jour où l'adresse est renseignée, ajouter son origine à connect-src dans
     _headers, sinon la politique de sécurité du contenu bloquera l'appel.
     Architecture complète : docs/SUIVI-COMMANDES.md. */
  var ADRESSE_SUIVI = '';
  var DELAI_SUIVI = 12000;

  var ETIQUETTES_ETAT = {
    paiement_recu: 'Paiement reçu',
    commandee_fournisseur: 'Commande passée au fournisseur',
    expediee: 'Expédiée',
    en_transit: 'En transit',
    livree: 'Livrée',
    annulee: 'Annulée',
    probleme: 'Problème — un humain s’en occupe'
  };

  var suivi = document.getElementById('form-suivi');
  if (suivi) {
    var sortieSuivi = document.getElementById('reponse-suivi');
    var avisSuivi = document.querySelector('[data-suivi-avis]');
    // L'avertissement « pas encore branché » disparaît de lui-même le jour où
    // le service existe : un seul endroit à modifier, pas deux textes à accorder.
    if (ADRESSE_SUIVI && avisSuivi) avisSuivi.hidden = true;

    var erreurChamp = function (champ, actif, idMsg) {
      var msg = document.getElementById(idMsg);
      if (msg) msg.hidden = !actif;
      champ.classList.toggle('invalide', actif);
      champ.setAttribute('aria-invalid', actif ? 'true' : 'false');
    };

    var vider = function () { while (sortieSuivi.firstChild) sortieSuivi.removeChild(sortieSuivi.firstChild); };

    var ligne = function (dl, terme, valeur, inconnu, mono) {
      var dt = document.createElement('dt');
      dt.textContent = terme;
      var dd = document.createElement('dd');
      dd.textContent = valeur;
      if (inconnu) dd.className = 'inconnu';
      else if (mono) dd.className = 'num';
      dl.appendChild(dt);
      dl.appendChild(dd);
    };

    var paragraphe = function (texte, classe) {
      var p = document.createElement('p');
      p.style.margin = '0';
      if (classe) p.className = classe;
      p.textContent = texte;
      return p;
    };

    // Lien de secours : le courriel, avec le numéro déjà dans le corps du message.
    // Ce lien n'est PAS suivi automatiquement — la personne clique si elle veut.
    // Rien n'entre donc dans l'historique du navigateur sans son geste.
    var lienSecours = function (numero) {
      var corps = [
        'Numéro de commande : ' + numero,
        '',
        'Bonjour, où en est ma commande ?',
        '',
        '— Envoyé depuis la page de suivi du site VELA'
      ].join('\r\n');
      var a = document.createElement('a');
      a.href = 'mailto:' + COURRIEL
        + '?subject=' + encodeURIComponent('VELA — suivi de commande')
        + '&body=' + encodeURIComponent(corps);
      a.textContent = 'Nous écrire à propos de cette commande';
      return a;
    };

    var afficher = function (classe, noeuds) {
      vider();
      sortieSuivi.hidden = false;
      sortieSuivi.className = 'form-reponse' + (classe ? ' ' + classe : '');
      noeuds.forEach(function (n) { sortieSuivi.appendChild(n); });
    };

    // Une fiche de commande, remplie uniquement avec ce que le serveur a dit.
    var afficherFiche = function (d, numero) {
      var bloc = document.createElement('div');
      bloc.className = 'suivi-fiche';
      var dl = document.createElement('dl');

      var etat = String(d.etat || '');
      ligne(dl, 'État', ETIQUETTES_ETAT[etat] || 'État inconnu', !ETIQUETTES_ETAT[etat]);
      ligne(dl, 'Numéro de commande', String(d.numero || numero));

      // Les dates : uniquement celles d'un fait qui a eu lieu. Aucune n'est
      // calculée à partir d'une autre, et aucune moyenne n'est appliquée.
      var dates = d.dates || {};
      ligne(dl, 'Paiement reçu le', dates.paiement_recu || 'inconnue', !dates.paiement_recu);
      ligne(dl, 'Passée au fournisseur le', dates.commandee_fournisseur || 'inconnue', !dates.commandee_fournisseur);
      ligne(dl, 'Expédiée le', dates.expediee || 'inconnue', !dates.expediee);
      ligne(dl, 'Livrée le', dates.livree || 'inconnue', !dates.livree);

      ligne(dl, 'Transporteur', d.transporteur || 'inconnu', !d.transporteur);
      ligne(dl, 'Numéro de suivi', d.suivi_numero || 'aucun pour l’instant', !d.suivi_numero, true);
      // Cette ligne ne vient QUE du transporteur. Le serveur envoie null tant
      // qu'aucun transporteur ne l'a annoncée ; on n'estime jamais nous-mêmes.
      ligne(dl, 'Livraison estimée', d.livraison_estimee || 'inconnue', !d.livraison_estimee);

      bloc.appendChild(dl);
      // suivi_url vient du transporteur. On ne la fabrique jamais nous-mêmes, et
      // on ne relaie que ce que le serveur a explicitement envoyé. Le schéma est
      // vérifié ici : une réponse malveillante ne doit pas pouvoir poser un lien
      // « javascript: » dans la page.
      if (d.suivi_url && /^https?:\/\//i.test(String(d.suivi_url))) {
        var lienT = document.createElement('a');
        lienT.href = String(d.suivi_url);
        lienT.target = '_blank';
        lienT.rel = 'noopener noreferrer';
        lienT.textContent = 'Suivre le colis chez le transporteur';
        bloc.appendChild(lienT);
      }
      if (d.message) bloc.appendChild(paragraphe(String(d.message), 'small'));
      bloc.appendChild(paragraphe(
        'Ce que cette page ne dit pas, nous ne le savons pas non plus. '
        + 'Nous vous écrivons dès qu’un état change.', 'small muted'));
      bloc.appendChild(lienSecours(String(d.numero || numero)));
      afficher('', [bloc]);
    };

    suivi.addEventListener('submit', function (e) {
      e.preventDefault();
      var numeroChamp = document.getElementById('numero');
      var courrielChamp = document.getElementById('courriel-suivi');
      var numero = numeroChamp.value.trim();
      var adresse = courrielChamp.value.trim();

      var okNumero = numero.length > 0;
      var okCourriel = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(adresse);
      erreurChamp(numeroChamp, !okNumero, 'err-numero');
      erreurChamp(courrielChamp, !okCourriel, 'err-courriel-suivi');
      if (!okNumero || !okCourriel) {
        afficher('erreur', [paragraphe(
          'Il faut les deux : le numéro de commande et le courriel du paiement. '
          + 'Le numéro seul ne donne accès à rien.')]);
        (okNumero ? courrielChamp : numeroChamp).focus();
        return;
      }

      // ---- aucun service de suivi : on le dit, on n'invente rien -------------
      if (!ADRESSE_SUIVI) {
        var rappel = document.createElement('p');
        rappel.style.margin = '0';
        rappel.appendChild(document.createTextNode('Vous avez saisi le numéro '));
        var b = document.createElement('b');
        b.className = 'mono';
        b.textContent = numero;
        rappel.appendChild(b);
        rappel.appendChild(document.createTextNode('.'));
        afficher('', [
          paragraphe('Nous ne pouvons pas encore vous répondre automatiquement : le suivi en ligne '
            + 'n’est pas branché, et nous préférons vous le dire plutôt que d’afficher une '
            + 'progression qui ne voudrait rien dire.'),
          rappel,
          paragraphe('Écrivez-nous avec ce numéro et nous vous répondons nous-mêmes, avec ce que '
            + 'nous savons vraiment ce jour-là.', 'small'),
          lienSecours(numero)
        ]);
        return;
      }

      // ---- un service existe : POST, et rien que ce qu'il répond ------------
      afficher('', [paragraphe('Recherche en cours…')]);
      var stop = null;
      var options = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ numero: numero, courriel: adresse })
      };
      if (typeof AbortController === 'function') {
        stop = new AbortController();
        options.signal = stop.signal;
        setTimeout(function () { stop.abort(); }, DELAI_SUIVI);
      }

      fetch(ADRESSE_SUIVI, options)
        .then(function (r) {
          if (r.status === 429) {
            afficher('erreur', [paragraphe('Trop de tentatives depuis cet appareil. '
              + 'Attendez une minute, puis réessayez.')]);
            return null;
          }
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (d) {
          if (!d) return;
          // Réponse volontairement identique pour « numéro inconnu » et
          // « le couple ne correspond pas » : rien à apprendre en tâtonnant.
          if (!d.trouvee) {
            afficher('erreur', [
              paragraphe('Aucune commande ne correspond à ce numéro et à ce courriel. '
                + 'Vérifiez que l’adresse est bien celle utilisée pour payer — c’est souvent celle '
                + 'indiquée au paiement Stripe, qui n’est pas toujours celle qu’on utilise tous les jours.'),
              lienSecours(numero)
            ]);
            return;
          }
          afficherFiche(d, numero);
        })
        .catch(function () {
          afficher('erreur', [
            paragraphe('Le service de suivi ne répond pas en ce moment. Votre commande, elle, n’a '
              + 'pas bougé : c’est cette page qui n’arrive pas à la lire.'),
            lienSecours(numero)
          ]);
        });
    });

    ['numero', 'courriel-suivi'].forEach(function (id) {
      var champ = document.getElementById(id);
      if (champ) champ.addEventListener('input', function () {
        erreurChamp(champ, false, 'err-' + id);
      });
    });
  }

  /* ------------------------------------------------------------ SHA-256 */
  var K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]);

  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

  function sha256(text) {
    var bytes = new TextEncoder().encode(text);
    var len = bytes.length;
    var blocks = Math.ceil((len + 9) / 64);
    var total = blocks * 64;
    var buf = new Uint8Array(total);
    buf.set(bytes);
    buf[len] = 0x80;
    var view = new DataView(buf.buffer);
    var bits = len * 8;
    view.setUint32(total - 8, Math.floor(bits / 4294967296));
    view.setUint32(total - 4, bits >>> 0);

    var H = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    ]);
    var w = new Uint32Array(64);

    for (var i = 0; i < blocks; i++) {
      var off = i * 64;
      for (var t = 0; t < 16; t++) w[t] = view.getUint32(off + t * 4);
      for (t = 16; t < 64; t++) {
        var x = w[t - 15], y = w[t - 2];
        var s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
        var s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (t = 0; t < 64; t++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[t] + w[t]) >>> 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var out = '';
    for (i = 0; i < 8; i++) out += ('00000000' + H[i].toString(16)).slice(-8);
    return out;
  }

  /* ------------------------------------- démonstration du registre chaîné */
  var demo = document.querySelector('[data-chain-demo]');
  if (!demo) return;

  var GENESIS = '0000000000000000000000000000000000000000000000000000000000000000';
  var base = [
    { time: '08 h 12 min 04 s', what: 'Consentement accordé', detail: 'Texte de vos demandes' },
    { time: '08 h 12 min 39 s', what: 'Envoi à un agent externe', detail: 'transcription → service IA de VELA' },
    { time: '09 h 03 min 15 s', what: 'Capture d’écran locale', detail: 'écran principal, restée sur l’appareil' },
    { time: '09 h 03 min 21 s', what: 'Commande exécutée', detail: 'ouverture de l’application « Code »' },
    { time: '11 h 47 min 58 s', what: 'Mode 100 % local activé', detail: 'plus aucun envoi externe' }
  ];
  var entries = base.map(function (e) { return { time: e.time, what: e.what, detail: e.detail }; });
  var tampered = -1;   // index de la ligne réécrite après coup
  var checked = false; // l'utilisateur a-t-il lancé une vérification ?

  var list = demo.querySelector('[data-entries]');
  var status = demo.querySelector('[data-status]');
  var state = document.querySelector('[data-state]'); // bandeau de résultat, hors du bloc de démonstration
  var btnVerify = demo.querySelector('[data-verify]');
  var btnTamper = demo.querySelector('[data-tamper]');
  var btnReset = demo.querySelector('[data-reset]');

  // Chaîne telle qu'elle a été écrite : chaque empreinte scelle la précédente.
  function chain(items) {
    var prev = GENESIS;
    return items.map(function (e) {
      var hash = sha256(prev + '|' + e.time + '|' + e.what + '|' + e.detail);
      var row = { entry: e, prev: prev, hash: hash };
      prev = hash;
      return row;
    });
  }
  var sealed = chain(entries); // empreintes enregistrées au moment des faits

  // Recalcul honnête à partir du contenu actuel : c'est ce que fait « Vérifier ».
  function verify() {
    var prev = GENESIS;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var expected = sha256(prev + '|' + e.time + '|' + e.what + '|' + e.detail);
      if (expected !== sealed[i].hash) return { ok: false, at: i };
      prev = sealed[i].hash;
    }
    return { ok: true, at: -1 };
  }

  function render() {
    var result = verify();
    list.innerHTML = '';
    entries.forEach(function (e, i) {
      var broken = checked && !result.ok && i >= result.at;
      var row = document.createElement('div');
      row.className = 'entry' + (broken ? ' broken' : '');
      var idx = document.createElement('div');
      idx.className = 'idx';
      idx.textContent = '#' + (i + 1);
      var body = document.createElement('div');
      body.className = 'body';

      var line = document.createElement('div');
      line.className = 'line';
      var what = document.createElement('span');
      what.className = 'what';
      what.textContent = e.what;
      var when = document.createElement('span');
      when.className = 'when';
      when.textContent = e.time;
      line.appendChild(what);
      line.appendChild(when);
      if (i === tampered) {
        var flag = document.createElement('span');
        flag.className = 'pill err';
        flag.textContent = 'ligne réécrite';
        line.appendChild(flag);
      }

      var detail = document.createElement('div');
      detail.className = 'small muted';
      detail.textContent = e.detail;

      var hash = document.createElement('div');
      hash.className = 'hash';
      hash.appendChild(document.createTextNode('empreinte : '));
      var strong = document.createElement('b');
      strong.textContent = sealed[i].hash;
      hash.appendChild(strong);

      body.appendChild(line);
      body.appendChild(detail);
      body.appendChild(hash);
      row.appendChild(idx);
      row.appendChild(body);
      list.appendChild(row);
    });

    if (!checked) {
      status.className = 'demo-status';
      status.textContent = 'Chaîne SHA-256 — non vérifiée pour l’instant.';
      if (state) state.textContent = 'Chaîne SHA-256 — non vérifiée pour l’instant';
    } else if (result.ok) {
      status.className = 'demo-status ok';
      status.textContent = 'Registre intact : ' + entries.length + ' entrées vérifiées, empreinte finale '
        + sealed[entries.length - 1].hash.slice(0, 16) + '…';
      if (state) state.textContent = 'Intact — ' + entries.length + ' entrées vérifiées';
    } else {
      status.className = 'demo-status bad';
      status.textContent = 'Altération détectée à l’entrée n° ' + (result.at + 1)
        + ' : le contenu ne correspond plus à son empreinte, et toutes les suivantes s’en trouvent invalidées.';
      if (state) state.textContent = 'Altération détectée à l’entrée n° ' + (result.at + 1);
    }
    if (btnReset) btnReset.hidden = tampered < 0;
  }

  btnVerify.addEventListener('click', function () { checked = true; render(); });

  btnTamper.addEventListener('click', function () {
    tampered = 1;
    entries[1] = {
      time: base[1].time,
      what: 'Aucun envoi externe',
      detail: 'ligne maquillée après coup pour cacher l’envoi'
    };
    checked = false;
    status.className = 'demo-status';
    status.textContent = 'L’entrée n° 2 vient d’être réécrite. Lancez « Vérifier la chaîne » pour voir ce qui se passe.';
    if (state) state.textContent = 'Chaîne SHA-256 — non vérifiée pour l’instant';
    render();
    status.textContent = 'L’entrée n° 2 vient d’être réécrite. Lancez « Vérifier la chaîne » pour voir ce qui se passe.';
  });

  btnReset.addEventListener('click', function () {
    entries = base.map(function (e) { return { time: e.time, what: e.what, detail: e.detail }; });
    tampered = -1;
    checked = false;
    render();
  });

  render();
})();
