/* Télécommande d'Iris — côté téléphone.
 *
 * Ouvre un WebSocket vers le relais VELA, s'authentifie avec un jeton d'appareil (obtenu du relais)
 * ET le code d'appairage affiché par l'ordinateur, puis envoie des commandes. Les demandes d'accord
 * (courriel, SMS, appel, action irréversible) remontent ici : l'utilisateur répond oui ou non.
 *
 * Aucun secret n'est codé en dur. Le courriel, l'adresse du relais et le code d'appairage sont
 * saisis par l'utilisateur et gardés dans ce navigateur (localStorage), rien d'autre.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var ws = null, jeton = null, connecte = false;
  var accordEnCours = null; // { req_id, confirm_id }

  var els = {
    relais: $("relais"), courriel: $("courriel"), pairing: $("pairing"),
    connecter: $("btn-connecter"), point: $("point"), etat: $("etat-texte"),
    carteCmd: $("carte-commande"), commande: $("commande"), envoyer: $("btn-envoyer"),
    carteAccord: $("carte-accord"), accordTitre: $("accord-titre"), accordDetail: $("accord-detail"),
    oui: $("btn-oui"), non: $("btn-non"), fil: $("fil"),
  };

  // --- mémoire locale (ce navigateur seulement) ---
  function charger() {
    try {
      els.relais.value = localStorage.getItem("tc.relais") || "";
      els.courriel.value = localStorage.getItem("tc.courriel") || "";
      els.pairing.value = localStorage.getItem("tc.pairing") || "";
    } catch (e) {}
  }
  function sauver() {
    try {
      localStorage.setItem("tc.relais", els.relais.value.trim());
      localStorage.setItem("tc.courriel", els.courriel.value.trim());
      localStorage.setItem("tc.pairing", els.pairing.value.trim());
    } catch (e) {}
  }

  // --- affichage ---
  function bulle(texte, classe) {
    var d = document.createElement("div");
    d.className = "bulle " + classe;
    d.textContent = texte;
    els.fil.appendChild(d);
    els.fil.scrollIntoView(false);
  }
  function etat(texte, on) {
    els.etat.textContent = texte;
    els.point.className = "point" + (on === true ? " on" : on === false ? " off" : "");
  }

  function baseWs(url) {
    url = (url || "").trim().replace(/\/+$/, "");
    if (url.indexOf("https://") === 0) return "wss://" + url.slice(8);
    if (url.indexOf("http://") === 0) return "ws://" + url.slice(7);
    return url;
  }
  function reqId() {
    try { return crypto.randomUUID(); } catch (e) { return "r" + Date.now() + Math.floor(Math.random() * 1e6); }
  }

  // --- connexion ---
  async function connecter() {
    var base = els.relais.value.trim().replace(/\/+$/, "");
    var email = els.courriel.value.trim();
    var code = els.pairing.value.trim();
    if (!base || !email || !code) { etat("Remplis l'adresse, le courriel et le code.", false); return; }
    sauver();
    els.connecter.disabled = true;
    etat("Obtention de l'accès…", null);
    try {
      var r = await fetch(base + "/api/appareil", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ machine: "telephone-web", email: email }),
      });
      if (!r.ok) throw new Error("relais " + r.status);
      jeton = (await r.json()).jeton;
      if (!jeton) throw new Error("aucun jeton");
    } catch (e) {
      etat("Relais injoignable. Vérifie l'adresse.", false);
      els.connecter.disabled = false;
      return;
    }
    try {
      ws = new WebSocket(baseWs(base) + "/telecommande/ws");
    } catch (e) {
      etat("Connexion impossible.", false); els.connecter.disabled = false; return;
    }
    ws.onopen = function () { ws.send(JSON.stringify({ type: "hello", jeton: jeton, pairing: code })); };
    ws.onmessage = function (ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      traiter(m);
    };
    ws.onclose = function () {
      connecte = false; els.envoyer.disabled = true; els.connecter.disabled = false;
      etat("Déconnecté.", false);
    };
    ws.onerror = function () { etat("Erreur de connexion.", false); };
  }

  function traiter(m) {
    if (m.type === "pret") {
      connecte = true;
      els.connecter.disabled = false;
      els.carteCmd.hidden = false;
      els.envoyer.disabled = false;
      if (m.ordinateur) { etat("Connecté — ton ordinateur est prêt.", true); }
      else { etat("Connecté, mais ton ordinateur n'est pas joignable (allumé ? télécommande activée ? bon code ?).", false); }
    } else if (m.type === "confirm") {
      accordEnCours = { req_id: m.req_id, confirm_id: m.confirm_id };
      els.accordTitre.textContent = m.title || "Confirmer ?";
      els.accordDetail.textContent = m.detail || "";
      els.carteAccord.hidden = false;
      els.carteAccord.scrollIntoView({ behavior: "smooth", block: "center" });
    } else if (m.type === "resultat") {
      if (m.erreur) { bulle(m.message || "Iris n'a pas pu exécuter la commande.", "sys"); }
      else { bulle(m.reponse || "(pas de réponse)", "iris"); }
      els.envoyer.disabled = !connecte;
    }
  }

  function repondreAccord(ok) {
    if (accordEnCours && ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "confirm_reponse", req_id: accordEnCours.req_id,
                               confirm_id: accordEnCours.confirm_id, approved: ok }));
      bulle(ok ? "✓ Tu as autorisé." : "✕ Tu as refusé.", "sys");
    }
    accordEnCours = null;
    els.carteAccord.hidden = true;
  }

  function envoyer() {
    var texte = els.commande.value.trim();
    if (!texte || !ws || ws.readyState !== 1) return;
    ws.send(JSON.stringify({ type: "commande", req_id: reqId(), texte: texte }));
    bulle(texte, "moi");
    els.commande.value = "";
    els.envoyer.disabled = true;
  }

  els.connecter.addEventListener("click", connecter);
  els.envoyer.addEventListener("click", envoyer);
  els.oui.addEventListener("click", function () { repondreAccord(true); });
  els.non.addEventListener("click", function () { repondreAccord(false); });
  charger();
})();
