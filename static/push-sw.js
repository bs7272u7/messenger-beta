/*
 * 웹 푸시 알림용 서비스 워커.
 *
 * 브라우저(탭)가 닫혀 있어도 서버가 보낸 푸시를 받아 알림을 띄운다.
 * 알림 내용은 서버가 VAPID 서명으로 보낸 데이터만 사용한다. 등록은 static/js/script.js의 registerPushSubscription()이 한다.
 */

// 서버에서 푸시가 도착했을 때: title/body/url을 읽어 알림을 표시한다. 값이 없으면 기본 문구를 쓴다.
self.addEventListener("push", function (event) {
    const data = event.data ? event.data.json() : {};
    // waitUntil: 알림이 실제로 표시될 때까지 서비스 워커가 종료되지 않게 붙잡아 둔다.
    event.waitUntil(self.registration.showNotification(data.title || "Cloud Chatting", {
        body: data.body || "새 메시지가 도착했습니다.",
        icon: "/static/favicon-180x180.png",
        badge: "/static/favicon-16x16.png",
        data: { url: data.url || "/" },
    }));
});

// 사용자가 알림을 누르면 알림을 닫고, 새 메시지가 온 대화방 주소(url)로 새 창을 연다.
self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data.url || "/"));
});
