/* IRIS — agent de service de l'ANCIENNE page téléphone (mobile-web), remplacée le 2026-09-14.
   Un téléphone qui avait installé l'ancienne page garde son agent de service : cette version le
   remplace, vide tous les caches (dont l'ancienne coquille avec le widget vocal tiers), puis se
   désinscrit. Elle n'intercepte aucune requête. */
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((noms) => Promise.all(noms.map((n) => caches.delete(n))))
      .then(() => self.registration.unregister())
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((fenetres) => fenetres.forEach((f) => f.navigate(f.url)))
      .catch(() => null)
  );
});
