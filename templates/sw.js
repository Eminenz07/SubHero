// Service Worker with Web Push Notification Support for SubHero PWA
const CACHE_NAME = 'subhero-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request));
});

// =============================================================
// WEB PUSH NOTIFICATIONS
// =============================================================
self.addEventListener('push', (event) => {
    if (!event.data) return;

    let data = {};
    try {
        data = event.data.json();
    } catch (e) {
        data = {
            title: 'SubHero Notification',
            body: event.data.text()
        };
    }

    const title = data.title || 'SubHero Notification';
    const options = {
        body: data.body || '',
        icon: data.icon || '/static/images/icon-192.png',
        badge: '/static/images/icon-192.png',
        vibrate: [100, 50, 100],
        data: {
            url: data.url || '/dashboard/'
        },
        actions: [
            { action: 'open', title: 'View Details' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const targetUrl = event.notification.data && event.notification.data.url ? event.notification.data.url : '/dashboard/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (let client of clientList) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
