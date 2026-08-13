self.addEventListener("push", function (event) {
    const data = event.data ? event.data.json() : {};
    event.waitUntil(self.registration.showNotification(data.title || "Cloud Chatting", {
        body: data.body || "새 메시지가 도착했습니다.",
        icon: "/static/favicon-180x180.png",
        badge: "/static/favicon-16x16.png",
        data: { url: data.url || "/" },
    }));
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data.url || "/"));
});
