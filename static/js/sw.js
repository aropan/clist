self.addEventListener('push', function (event) {
    const eventInfo = event.data.text();
    const data = JSON.parse(eventInfo);

    event.waitUntil(
        self.registration.showNotification(
            data.head || 'CLIST',
            {
                body: data.body || 'Bla, bla-bla',
                icon: data.icon || null,
                data: {'url': data.url || self.location.origin},
            },
        )
    );
});

self.addEventListener('notificationclick', function(event) {
    event.waitUntil(
        event.preventDefault(),
        event.notification.close(),
        self.clients.openWindow(event.notification.data.url)
    );
});
