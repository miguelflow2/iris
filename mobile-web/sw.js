/* =========================================================================
   IRIS — agent de service (VELA)
   Rôle volontairement minimal : mettre en cache la COQUILLE locale (le HTML, le style,
   le script, les icônes) pour que l'app s'ouvre même sans réseau, et permettre à Android
   de proposer l'installation.

   Ce qu'il ne fait JAMAIS :
   - il n'intercepte ni ne met en cache le widget vocal (elevenlabs.io) ni aucun appel réseau
     distant : la voix d'Iris a besoin du direct, une version périmée serait pire que rien ;
   - il ne touche à rien d'autre que l'origine de l'app.
   ========================================================================= */
const CACHE = "iris-coquille-v1";
const COQUILLE = [
  "./",
  "./index.html",
  "./assets/app.css",
  "./assets/app.js",
  "./manifest.webmanifest",
  "./icone-192.png",
  "./icone-512.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(COQUILLE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((noms) => Promise.all(noms.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;

  // On ne s'occupe que des GET de notre propre origine. Le widget vocal, les échanges avec
  // l'agent et tout le reste passent directement au réseau, sans jamais être mis en cache.
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Réseau d'abord (pour toujours servir la dernière version de la coquille), cache en repli
  // quand le téléphone est hors ligne. En dernier recours, on rend la page d'accueil.
  e.respondWith(
    fetch(req)
      .then((r) => {
        if (r && r.ok) {
          const copie = r.clone();
          caches.open(CACHE).then((c) => c.put(req, copie));
        }
        return r;
      })
      .catch(() =>
        caches.match(req).then((r) => r || caches.match("./index.html") || caches.match("./"))
      )
  );
});
