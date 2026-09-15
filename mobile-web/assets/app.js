/* IRIS — ancienne page téléphone (mobile-web), remplacée le 2026-09-14.
   Plus aucun widget vocal ni appel à un service tiers : ce fichier ne sert plus qu'aux téléphones qui
   l'ont encore en cache. Il désinscrit l'ancien agent de service et vide ses caches, pour que la page
   d'information remplace pour de bon l'ancienne coquille. */
(function () {
  "use strict";
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations()
      .then(function (inscrits) { inscrits.forEach(function (i) { i.unregister(); }); })
      .catch(function () { /* facultatif */ });
  }
  if (window.caches && caches.keys) {
    caches.keys()
      .then(function (noms) { return Promise.all(noms.map(function (n) { return caches.delete(n); })); })
      .catch(function () { /* facultatif */ });
  }
})();
