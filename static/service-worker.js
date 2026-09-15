/* Local AI Agent - Service Worker (PWA)
   Кэширует оболочку приложения, чтобы оно открывалось как нативное.
   API-запросы (/chat, /apps, /settings, ...) НЕ кэшируются — всегда свежие. */

const CACHE_NAME = 'local-ai-agent-v1';
const SHELL = [
  '/',
  '/static/css/style.css',
  '/static/css/themes.css',
  '/static/js/app.js',
  '/static/js/auth.js',
  '/static/favicon.svg',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API и динамика — только сеть
  const isApi = ['/chat', '/history', '/settings', '/apps', '/login',
                 '/logout', '/guest', '/register', '/clear_history',
                 '/network', '/voice', '/health']
    .some((p) => url.pathname.startsWith(p));

  if (isApi || event.request.method !== 'GET') {
    return; // пропускаем без перехвата
  }

  // Оболочка — сеть, при офлайне — кэш
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200 && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
