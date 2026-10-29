/*
 * 모던 UI의 메시지함: 팔로우 요청, 메시지 요청, 보낸 요청.
 *
 * modern-profile.js 뒤에 로드된다. 서버의 팔로우·메시지 요청 API(blueprints/follows.py)만 호출하고,
 * 요청 수는 왼쪽 메뉴와 목록 머리의 배지(.modern-badge)에 표시한다.
 */
(function () {
    "use strict";

    const $ = (selector) => document.querySelector(selector);
    const overlay = $("#modern-inbox-overlay");
    const ui = window.ModernUi;
    if (!overlay || !ui) return;

    const { api, avatarHTML } = ui;
    const lists = {
        follow: $("#modern-inbox-follow"),
        message: $("#modern-inbox-message"),
        sent: $("#modern-inbox-sent"),
    };
    const tabButtons = overlay.querySelectorAll("[data-inbox-tab]");
    const badges = document.querySelectorAll(".modern-badge");
    let activeTab = "follow";

    // ------------------------------------------------------------------
    // 배지: 받은 팔로우 요청 + 메시지 요청 수
    // ------------------------------------------------------------------
    async function refreshBadge() {
        const { ok, data } = await api("/api/inbox-counts");
        if (!ok) return;
        const total = data.followRequests + data.messageRequests;
        badges.forEach((badge) => {
            badge.hidden = total === 0;
            badge.textContent = total > 99 ? "99+" : String(total);
        });
    }

    // ------------------------------------------------------------------
    // 목록 그리기
    // ------------------------------------------------------------------
    function userBlock(user, subtitle) {
        return `
            <div class="mr-user">
                <span class="mr-avatar">${avatarHTML(user.profileImage)}</span>
                <span class="mr-text"><b>${escapeHTML(user.username)}</b><small>${escapeHTML(subtitle)}</small></span>
            </div>`;
    }

    function row(html, attributes) {
        const element = document.createElement("div");
        element.className = "mr-row";
        Object.entries(attributes).forEach(([key, value]) => { element.dataset[key] = value; });
        element.innerHTML = html;
        return element;
    }

    function empty(message) {
        return `<p class="mr-empty">${message}</p>`;
    }

    function sectionTitle(text) {
        const title = document.createElement("h4");
        title.className = "mi-section";
        title.textContent = text;
        return title;
    }

    const answerButtons = `
        <div class="mr-action mi-answer">
            <button type="button" class="mp-btn mp-btn-small mp-btn-primary" data-act="accept">수락</button>
            <button type="button" class="mp-btn mp-btn-small" data-act="decline">거절</button>
        </div>`;

    async function load() {
        const [follow, message] = await Promise.all([
            api("/api/follow-requests"),
            api("/api/message-requests"),
        ]);
        const incoming = follow.ok ? follow.data.incoming : [];
        const outgoing = follow.ok ? follow.data.outgoing : [];
        const pending = message.ok ? message.data.pending : [];
        const declined = message.ok ? message.data.declined : [];

        // 팔로우 요청
        lists.follow.innerHTML = incoming.length ? "" : empty("받은 팔로우 요청이 없어요");
        incoming.forEach((item) => {
            lists.follow.appendChild(
                row(userBlock(item.user, item.user.displayName) + answerButtons, { requestId: item.id, userId: item.user.id })
            );
        });

        // 메시지 요청(수락 대기) + 내가 거절한 요청
        lists.message.innerHTML = pending.length || declined.length ? "" : empty("메시지 요청이 없어요");
        pending.forEach((item) => {
            lists.message.appendChild(
                row(userBlock(item.user, item.preview || "메시지") + answerButtons, { conversationId: item.conversationId, userId: item.user.id })
            );
        });
        if (declined.length) {
            lists.message.appendChild(sectionTitle("거절한 요청"));
            declined.forEach((item) => {
                lists.message.appendChild(
                    row(
                        userBlock(item.user, item.preview || "메시지") +
                            `<div class="mr-action"><button type="button" class="mp-btn mp-btn-small" data-act="accept">수락</button></div>`,
                        { conversationId: item.conversationId, userId: item.user.id }
                    )
                );
            });
        }

        // 보낸 팔로우 요청
        lists.sent.innerHTML = outgoing.length ? "" : empty("보낸 요청이 없어요");
        outgoing.forEach((item) => {
            lists.sent.appendChild(
                row(
                    userBlock(item.user, item.user.displayName) +
                        `<div class="mr-action"><button type="button" class="mp-btn mp-btn-small" data-act="withdraw">취소</button></div>`,
                    { requestId: item.id, userId: item.user.id }
                )
            );
        });

        $("#modern-inbox-count-follow").textContent = incoming.length;
        $("#modern-inbox-count-message").textContent = pending.length;
        $("#modern-inbox-count-sent").textContent = outgoing.length;
        refreshBadge();
    }

    function showTab(name) {
        activeTab = name;
        tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.inboxTab === name));
        Object.entries(lists).forEach(([key, element]) => { element.hidden = key !== name; });
    }

    async function open(tab) {
        overlay.style.display = "flex";
        showTab(tab || activeTab);
        await load();
    }

    function close() {
        overlay.style.display = "none";
    }

    // ------------------------------------------------------------------
    // 버튼 동작
    // ------------------------------------------------------------------
    async function handleClick(event) {
        const button = event.target.closest("[data-act]");
        const item = event.target.closest(".mr-row");
        if (!button || !item) return;
        const act = button.dataset.act;
        const accept = act === "accept";
        let result = null;

        if (item.dataset.requestId && (act === "accept" || act === "decline")) {
            result = await api(`/api/follow-requests/${item.dataset.requestId}/respond`, "POST", { accept });
        } else if (item.dataset.conversationId && (act === "accept" || act === "decline")) {
            result = await api(`/api/message-requests/${item.dataset.conversationId}/respond`, "POST", { accept });
        } else if (act === "withdraw") {
            result = await api(`/api/users/${item.dataset.userId}/follow`, "DELETE");
        }
        if (!result) return;
        if (!result.ok) {
            showAlert(result.data.error || "처리하지 못했습니다.");
            return;
        }
        await load();
        // 메시지 요청을 수락하면 대화방이 내 목록에 나타난다.
        if (accept && item.dataset.conversationId) await loadFriends();
    }

    Object.values(lists).forEach((element) => element.addEventListener("click", handleClick));
    tabButtons.forEach((button) => button.addEventListener("click", () => showTab(button.dataset.inboxTab)));
    $("#modern-inbox-close").addEventListener("click", close);
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) close();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && overlay.style.display === "flex") close();
    });

    // 새 요청이 오거나 상대가 응답하면 열려 있는 목록과 배지를 새로 고친다.
    if (typeof socket !== "undefined") {
        ["follow_updated", "message_request_updated"].forEach((name) => {
            socket.on(name, () => {
                if (overlay.style.display === "flex") load();
                else refreshBadge();
            });
        });
    }

    // 모바일 하단 탭바의 메시지함 버튼(모던에서만 보인다).
    const mobileInboxButton = $("#mobile-inbox-nav-btn");
    if (mobileInboxButton) mobileInboxButton.addEventListener("click", () => open());

    window.openModernInbox = open;
    window.refreshModernInboxBadge = refreshBadge;
    refreshBadge();
})();
