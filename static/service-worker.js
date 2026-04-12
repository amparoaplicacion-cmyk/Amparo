const CACHE_NAME = 'amparo-v1';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/img/amparo_logo.png'
];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sin conexión — AMPARO</title>
  <style>
    body { font-family: sans-serif; display: flex; align-items: center;
           justify-content: center; min-height: 100vh; margin: 0;
           background: #f5f5f5; color: #333; text-align: center; }
    .card { background: #fff; padding: 2rem; border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,.1); max-width: 320px; }
    h1 { font-size: 1.4rem; margin-bottom: .5rem; }
    p  { color: #666; font-size: .9rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Sin conexión</h1>
    <p>No se puede conectar a AMPARO. Verificá tu conexión a internet e intentá de nuevo.</p>
  </div>
</body>
</html>`;

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      })
      .catch(() =>
        caches.match(event.request).then(cached =>
          cached || new Response(OFFLINE_HTML, {
            headers: { 'Content-Type': 'text/html; charset=utf-8' }
          })
        )
      )
  );
});
