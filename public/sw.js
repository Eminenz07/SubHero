// Service Worker for SubHero PWA
// Version: subhero-v5

const CACHE_NAME = 'subhero-v5';
const ASSETS_TO_CACHE = [
  '/',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/js/feather.min.js',
  '/static/fonts/bricolage-grotesque-latin-wght-normal.woff2',
  '/static/fonts/dm-sans-latin-wght-normal.woff2',
  '/static/fonts/dm-mono-latin-400-normal.woff2',
  '/static/fonts/dm-mono-latin-500-normal.woff2',
  '/manifest.json',
  '/static/favicon.ico',
  '/static/favicon.svg',
  '/static/favicon.png'
];

// Install event - cache assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        return cache.addAll(ASSETS_TO_CACHE);
      })
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Fetch event - serve cached assets or fetch from network
self.addEventListener('fetch', (event) => {
  // Skip cross-origin requests
  if (!event.request.url.startsWith(self.location.origin)) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        // Return cached response if found
        if (response) {
          return response;
        }

        // Clone the request to use in the fetch
        const fetchRequest = event.request.clone();

        // Fetch from network and cache the response
        return fetch(fetchRequest).then((response) => {
          // Check if we received a valid response
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }

          // Clone the response to cache it
          const responseToCache = response.clone();

          caches.open(CACHE_NAME)
            .then((cache) => {
              cache.put(event.request, responseToCache);
            });

          return response;
        }).catch(() => {
          // If fetch fails, fall back to the cached landing shell
          return caches.match('/');
        });
      })
  );
});

// Push notification handler
self.addEventListener('push', (event) => {
  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/favicon.png',
    badge: '/favicon.png',
    data: {
      url: data.action_url
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.notification.data.url) {
    event.waitUntil(
      clients.openWindow(event.notification.data.url)
    );
  }
});