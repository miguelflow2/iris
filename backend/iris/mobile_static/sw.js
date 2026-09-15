/* IRIS — agent de service de la page téléphone (servi à /sw.js par l'ordinateur).
 *
 * Deux rôles, pas un de plus :
 * - permettre à Android de proposer « Installer l'application » (il exige un gestionnaire fetch) ;
 * - servir la COQUILLE hors ligne (page, styles, scripts, icônes), pour que la page s'ouvre et dise
 *   honnêtement « l'ordinateur ne répond pas » au lieu d'une page d'erreur du navigateur.
 *
 * On ne met JAMAIS l'API (/api/) ni le WebSocket (/ws) en cache : les réponses d'IRIS sont des
 * données vivantes, et une réponse périmée servie hors ligne serait pire que pas de réponse du tout.
 * Les autres origines (cartographie, relais) ne sont pas interceptées non plus.
 */
const CACHE = 'iris-coquille-v4';   // changer de nom purge l'ancienne coquille à l'activation
const COQUILLE = [
  '/m', '/m/app.css', '/m/js/api.js', '/m/js/coeur.js',
  '/manifest.webmanifest', '/icone-192.png', '/icone-512.png',
];
// Modules des fonctions : mis en cache s'ils existent. Un module absent ne doit pas faire échouer
// l'installation de l'agent (d'où un ajout un par un, et non addAll).
const MODULES = [
  '/m/js/lunettes.js', '/m/js/guidage.js', '/m/js/zones.js', '/m/js/partage.js',
  '/m/js/achats.js', '/m/js/invite.js', '/m/js/interprete.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.all(COQUILLE.concat(MODULES).map((chemin) =>
        fetch(chemin, { cache: 'no-store' })
          .then((r) => (r.ok ? cache.put(chemin, r) : null))
          .catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((noms) => Promise.all(noms.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

function estCoquille(url) {
  return url.pathname === '/m' || url.pathname.startsWith('/m/')
    || url.pathname === '/manifest.webmanifest' || url.pathname.startsWith('/icone-');
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;                        // jamais d'écriture en cache
  if (url.origin !== self.location.origin) return;               // cartographie, relais : réseau direct
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws') return;  // jamais de cache sur les données
  if (!estCoquille(url)) return;

  // La clé de cache est le chemin nu : « /m?token=… » ne doit jamais être écrit dans le cache.
  const cle = url.pathname;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok) {
          const copie = r.clone();
          caches.open(CACHE).then((c) => c.put(cle, copie)).catch(() => { /* cache plein : tant pis */ });
        }
        return r;
      })
      .catch(() => caches.match(cle).then((r) => r || (e.request.mode === 'navigate' ? caches.match('/m') : undefined))
        .then((r) => r || new Response('Hors ligne', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } })))
  );
});
