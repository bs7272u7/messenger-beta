// 브라우저가 닫혀 있어도 푸시 알림을 표시하는 서비스 워커입니다.
// 실제 알림 내용은 서버가 VAPID를 통해 보낸 데이터만 사용합니다.
self.addEventListener("push", function (event) {
    const data = event.data ? event.data.json() : {};
    event.waitUntil(self.registration.showNotification(data.title || "Cloud Chatting", {
        body: data.body || "새 메시지가 도착했습니다.",
        icon: "/static/favicon-180x180.png",
        badge: "/static/favicon-16x16.png",
        data: { url: data.url || "/" },
    }));
});

// 사용자가 알림을 누르면 새 메시지가 온 위치로 다시 연결합니다.
self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data.url || "/"));
});
