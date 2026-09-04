"""Rend la page mobile installable : manifeste, icônes, agent de service.

Sans ces trois pièces, Android ne propose qu'un simple raccourci. Avec elles, IRIS s'installe
comme une vraie application : icône dans le tiroir, plein écran, pas de barre de navigateur.
"""
import py_compile
from pathlib import Path

RACINE = Path(__file__).resolve().parent
faits = []


def patch(rel, paires):
    p = RACINE / rel
    s = original = p.read_text(encoding="utf-8")
    for old, new in paires:
        assert old in s, f"introuvable dans {rel} : {old[:80]!r}"
        s = s.replace(old, new, 1)
    if s != original:
        p.write_text(s, encoding="utf-8")
        py_compile.compile(str(p), doraise=True)
        faits.append(f"MODIFIE  {rel}")


# ------------------------------------------------------------------ manifeste et agent de service
patch(
    "iris/mobile.py",
    [
        ('''def urls_locales(port: int, token: str) -> list[dict]:''',
         '''MANIFESTE = {
    "name": "IRIS",
    "short_name": "IRIS",
    "description": "Commandez votre ordinateur à la voix, où que vous soyez.",
    "start_url": "/m",
    "scope": "/",
    "display": "standalone",   # plein écran, sans barre de navigateur
    "orientation": "portrait",
    "background_color": "#0b0d0c",
    "theme_color": "#0b0d0c",
    "lang": "fr-CA",
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

# Agent de service minimal. Android exige un gestionnaire `fetch` pour proposer l'installation.
# On ne met JAMAIS l'API en cache : les réponses d'IRIS sont des données vivantes, et une réponse
# périmée servie hors ligne serait pire que pas de réponse du tout.
AGENT_SERVICE = """
const CACHE = 'iris-coquille-v1';
const COQUILLE = ['/m', '/icone-192.png', '/icone-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(COQUILLE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((noms) => Promise.all(noms.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;  // jamais de cache sur les données
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok && COQUILLE.some((c) => url.pathname === c)) {
          const copie = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copie));
        }
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('/m')))
  );
});
"""


def urls_locales(port: int, token: str) -> list[dict]:'''),

        # lier le manifeste et enregistrer l'agent de service
        ('''<meta name="theme-color" content="#0b0d0c">
<title>IRIS</title>''',
         '''<meta name="theme-color" content="#0b0d0c">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="IRIS">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icone-192.png">
<link rel="apple-touch-icon" href="/icone-192.png">
<title>IRIS</title>'''),

        ("demarrer().then(verifier); setInterval(verifier, 20000);",
         """demarrer().then(verifier); setInterval(verifier, 20000);

// Agent de service : c'est lui qui permet à Android de proposer « Installer l'application ».
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* sans lui, la page marche quand même */ });
}"""),
    ],
)

# ------------------------------------------------------------------ routes
patch(
    "iris/main.py",
    [
        ("from .mobile import PAGE as PAGE_MOBILE, urls_locales",
         "from .mobile import AGENT_SERVICE, MANIFESTE, PAGE as PAGE_MOBILE, urls_locales"),
        ('''    class MotDePasse(BaseModel):''',
         '''    @app.get("/manifest.webmanifest")
    def manifeste():
        """Décrit l'application au téléphone : nom, icônes, plein écran."""
        return JSONResponse(MANIFESTE, media_type="application/manifest+json")

    @app.get("/sw.js")
    def agent_service():
        """Agent de service : Android l'exige pour proposer l'installation."""
        return Response(AGENT_SERVICE, media_type="application/javascript")

    @app.get("/icone-{taille}.png")
    def icone(taille: int):
        fichier = Path(__file__).parent / "assets" / f"icone-{taille}.png"
        if taille not in (192, 512) or not fichier.exists():
            raise HTTPException(404, "icône introuvable")
        return Response(fichier.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    class MotDePasse(BaseModel):'''),
    ],
)

print("\n".join(faits) or "rien")
