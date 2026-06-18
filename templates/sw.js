// Minimal Service Worker to satisfy PWA requirements
const CACHE_NAME = 'subhero-v1';

self.addEventListener('install', (event) => {
    // Force active state immediately
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    // Control all clients immediately
    event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
    // Always fetch from the network directly, no caching of pages
    // to prevent CSRF token issues and authentication desyncs.
    event.respondWith(fetch(event.request));
});
