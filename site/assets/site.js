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

  /* ------------------------------------------------- formulaire de contact
     Site statique, aucun service tiers : à la soumission on construit un lien
     mailto: pré-rempli et on ouvre le logiciel de courriel du visiteur. */
  var COURRIEL = 'miguelfreddy65@gmail.com';
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

      // Le message de confirmation porte aussi le lien : si le navigateur bloque l'ouverture du
      // logiciel de courriel, la personne a de quoi continuer au lieu de rester devant rien.
      reponse.hidden = false;
      reponse.className = 'form-reponse succes';
      reponse.textContent = '';
      reponse.appendChild(document.createTextNode(
        'Votre logiciel de courriel vient de s’ouvrir avec le message déjà rédigé : il ne reste qu’à '
        + 'l’envoyer. Rien ne s’est ouvert ? '));
      var secours = document.createElement('a');
      secours.href = lien;
      secours.id = 'lien-secours';
      secours.textContent = 'Rouvrir le message';
      reponse.appendChild(secours);
      reponse.appendChild(document.createTextNode(', ou écrivez directement à '));
      var direct = document.createElement('a');
      direct.href = 'mailto:' + COURRIEL;
      direct.textContent = COURRIEL;
      reponse.appendChild(direct);
      reponse.appendChild(document.createTextNode('.'));

      window.location.href = lien;
    });

    // On efface le signalement dès que la personne corrige son champ.
    ['nom', 'courriel', 'message'].forEach(function (id) {
      var champ = document.getElementById(id);
      if (champ) champ.addEventListener('input', function () { montrerErreur(champ, false); });
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
    { time: '08 h 12 min 39 s', what: 'Envoi à un agent externe', detail: 'transcription → OpenRouter' },
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
