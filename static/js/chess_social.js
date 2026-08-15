(function () {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const shell = document.querySelector(".chess-game-shell");
    if (!shell) return;
    const currentUserId = Number(shell.dataset.currentUserId || 0);

    async function api(url, options) {
        const response = await fetch(url, { ...options, headers: { "X-CSRF-Token": csrf, ...(options && options.headers) } });
        const contentType = response.headers.get("content-type") || "";
        const data = contentType.includes("application/json") ? await response.json() : {};
        if (!response.ok) throw new Error(data.error || "요청을 처리하지 못했습니다.");
        return data;
    }

    /* ======================================================
     * 친구 관리 패널 — 채팅 웹의 친구 목록(/api/conversations)과
     * 친구 요청 API를 그대로 재사용해 체스 페이지에서도 같은 방식으로 동작한다.
     * ====================================================== */
    const friendsModal = document.querySelector("#chess-friends-modal");
    const friendsBtn = document.querySelector("#chess-friends-btn");
    const friendList = document.querySelector("#chess-friend-list");
    const friendSearchInput = document.querySelector("#chess-friend-search-input");
    const friendSearchBtn = document.querySelector("#chess-friend-search-btn");
    const friendSearchResult = document.querySelector("#chess-friend-search-result");

    function escapeHTML(value) {
        return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
    }

    async function loadFriendList() {
        friendList.innerHTML = "불러오는 중…";
        try {
            const conversations = await api("/api/conversations");
            const friends = conversations.filter(item => !item.isGroup && item.peerId);
            if (!friends.length) { friendList.innerHTML = "아직 친구가 없습니다. 위에서 아이디로 친구를 찾아보세요."; return; }
            friendList.innerHTML = "";
            friends.forEach(friend => {
                const row = document.createElement("div");
                row.className = "chess-friend-row";
                const inviteIconHTML = friend.blockedByMe || friend.blockedMe ? "" :
                    `<button type="button" class="chess-friend-icon-btn chess-friend-invite" title="체스 초대" aria-label="${escapeHTML(friend.name)}님에게 체스 초대"><i class="fa-solid fa-chess-knight"></i></button>`;
                const blockIconHTML = friend.blockedByMe
                    ? `<button type="button" class="chess-friend-icon-btn chess-friend-unblock" title="차단 해제"><i class="fa-solid fa-lock-open"></i></button>`
                    : `<button type="button" class="chess-friend-icon-btn chess-friend-block" title="차단"><i class="fa-solid fa-ban"></i></button>`;
                row.innerHTML = `
                    <img src="${escapeHTML(friend.peerProfileImage || "/static/default_profile.png")}" alt="">
                    <span class="chess-friend-name">${escapeHTML(friend.name)}<small>@${escapeHTML(friend.peerUsername || "")}</small></span>
                    <span class="chess-friend-status ${friend.isOnline ? "online" : ""}">${friend.isOnline ? "온라인" : "오프라인"}</span>
                    <div class="chess-friend-actions">
                        ${inviteIconHTML}
                        ${blockIconHTML}
                        <button type="button" class="chess-friend-icon-btn chess-friend-delete" title="친구 삭제"><i class="fa-solid fa-trash"></i></button>
                    </div>`;
                const inviteBtn = row.querySelector(".chess-friend-invite");
                if (inviteBtn) inviteBtn.addEventListener("click", async () => {
                    inviteBtn.disabled = true;
                    try {
                        const result = await api(`/api/chess/quick-invite/${friend.peerId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ timeControl: "unlimited" }) });
                        location.href = `/chess/game/${result.game.id}`;
                    } catch (error) { inviteBtn.disabled = false; alert(error.message); }
                });
                row.querySelector(".chess-friend-delete").addEventListener("click", async () => {
                    if (!confirm(`"${friend.name}"님을 친구에서 삭제할까요?`)) return;
                    try { await api(`/api/conversations/${friend.id}/leave`, { method: "DELETE" }); loadFriendList(); } catch (error) { alert(error.message); }
                });
                const blockBtn = row.querySelector(".chess-friend-block");
                if (blockBtn) blockBtn.addEventListener("click", async () => {
                    if (!confirm(`"${friend.name}"님을 차단하시겠습니까? 차단하면 서로 메시지를 보낼 수 없어요.`)) return;
                    try { await api("/api/blocks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: friend.peerId }) }); loadFriendList(); } catch (error) { alert(error.message); }
                });
                const unblockBtn = row.querySelector(".chess-friend-unblock");
                if (unblockBtn) unblockBtn.addEventListener("click", async () => {
                    try { await api(`/api/blocks/${friend.peerId}`, { method: "DELETE" }); loadFriendList(); } catch (error) { alert(error.message); }
                });
                friendList.appendChild(row);
            });
        } catch (error) { friendList.innerHTML = escapeHTML(error.message); }
    }

    async function searchFriend() {
        const username = friendSearchInput.value.trim().toLowerCase();
        if (!username) return friendSearchInput.focus();
        friendSearchResult.innerHTML = "검색 중…";
        try {
            const data = await api(`/api/users/search?username=${encodeURIComponent(username)}`);
            const user = data.user;
            friendSearchResult.innerHTML = `
                <div class="chess-search-card">
                    <img src="${escapeHTML(user.profile_image || "/static/default_profile.png")}" alt="">
                    <span>${escapeHTML(user.display_name || user.username)}<small>@${escapeHTML(user.username)}</small></span>
                    ${user.is_friend ? '<span class="chess-search-state">친구</span>' : '<button type="button" class="chess-search-add">친구 추가</button>'}
                </div>`;
            const addBtn = friendSearchResult.querySelector(".chess-search-add");
            if (addBtn) addBtn.addEventListener("click", async () => {
                addBtn.disabled = true;
                try {
                    await api("/api/friend-requests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user.username }) });
                    addBtn.textContent = "요청 완료";
                } catch (error) { addBtn.disabled = false; alert(error.message); }
            });
        } catch (error) { friendSearchResult.innerHTML = escapeHTML(error.message); }
    }
    friendSearchBtn.addEventListener("click", searchFriend);
    friendSearchInput.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); searchFriend(); } });

    friendsBtn.addEventListener("click", () => { friendsModal.hidden = false; friendSearchResult.innerHTML = ""; friendSearchInput.value = ""; loadFriendList(); });
    document.querySelector("#close-chess-friends").addEventListener("click", () => { friendsModal.hidden = true; });
    friendsModal.addEventListener("click", event => { if (event.target === friendsModal) friendsModal.hidden = true; });

    /* ======================================================
     * 메시지함 — 채팅 웹의 메시지함과 동일하게 친구 요청 + 체스 초대를 모아 보여준다.
     * ====================================================== */
    const inboxModal = document.querySelector("#chess-inbox-modal");
    const inboxBtn = document.querySelector("#chess-inbox-btn");
    const inboxBadge = document.querySelector("#chess-inbox-badge");
    const incomingList = document.querySelector("#chess-inbox-incoming");
    const outgoingList = document.querySelector("#chess-inbox-outgoing");
    const incomingCount = document.querySelector("#chess-incoming-count");
    const outgoingCount = document.querySelector("#chess-outgoing-count");

    async function refreshInboxBadge() {
        try {
            const [requests, invites] = await Promise.all([api("/api/friend-requests"), api("/api/chess/invites")]);
            const total = (requests.incoming || []).length + (invites.invites || []).length;
            inboxBadge.hidden = total === 0;
            inboxBadge.textContent = total > 99 ? "99+" : total;
            return { requests, invites };
        } catch (error) { return null; }
    }

    async function loadInbox() {
        incomingList.innerHTML = "불러오는 중…";
        outgoingList.innerHTML = "불러오는 중…";
        const data = await refreshInboxBadge();
        if (!data) { incomingList.innerHTML = "메시지함을 불러오지 못했습니다."; return; }
        const incoming = data.requests.incoming || [];
        const outgoing = data.requests.outgoing || [];
        const chessInvites = data.invites.invites || [];
        incomingCount.textContent = incoming.length + chessInvites.length;
        outgoingCount.textContent = outgoing.length;

        incomingList.innerHTML = "";
        if (!incoming.length && !chessInvites.length) incomingList.innerHTML = '<div class="chess-inbox-empty">받은 요청이 없습니다.</div>';
        chessInvites.forEach(invite => {
            const item = document.createElement("div");
            item.className = "chess-request-item";
            item.innerHTML = `
                <img src="${escapeHTML(invite.profile_image || "/static/default_profile.png")}" alt="">
                <span><strong><i class="fa-solid fa-chess-knight"></i> ${escapeHTML(invite.display_name || invite.username)}</strong><small>체스 대국에 초대했습니다.</small></span>
                <button type="button" class="chess-accept-icon" title="수락"><i class="fa-solid fa-check"></i></button>
                <button type="button" class="chess-decline-icon" title="거절"><i class="fa-solid fa-xmark"></i></button>`;
            item.querySelector(".chess-accept-icon").addEventListener("click", async () => {
                try { const result = await api(`/api/chess/invites/${invite.id}/accept`, { method: "POST" }); location.href = `/chess/game/${result.game.id}`; } catch (error) { alert(error.message); }
            });
            item.querySelector(".chess-decline-icon").addEventListener("click", async () => {
                try { await api(`/api/chess/invites/${invite.id}/decline`, { method: "POST" }); loadInbox(); } catch (error) { alert(error.message); }
            });
            incomingList.appendChild(item);
        });
        incoming.forEach(req => {
            const item = document.createElement("div");
            item.className = "chess-request-item";
            item.innerHTML = `
                <img src="${escapeHTML(req.profile_image || "/static/default_profile.png")}" alt="">
                <span><strong>${escapeHTML(req.display_name || req.username)}</strong><small>친구 요청을 보냈습니다.</small></span>
                <button type="button" class="chess-accept-icon" title="수락"><i class="fa-solid fa-check"></i></button>
                <button type="button" class="chess-decline-icon" title="거절"><i class="fa-solid fa-xmark"></i></button>`;
            item.querySelector(".chess-accept-icon").addEventListener("click", async () => {
                try { await api(`/api/friend-requests/${req.id}/respond`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accept: true }) }); loadInbox(); } catch (error) { alert(error.message); }
            });
            item.querySelector(".chess-decline-icon").addEventListener("click", async () => {
                try { await api(`/api/friend-requests/${req.id}/respond`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accept: false }) }); loadInbox(); } catch (error) { alert(error.message); }
            });
            incomingList.appendChild(item);
        });

        outgoingList.innerHTML = "";
        if (!outgoing.length) outgoingList.innerHTML = '<div class="chess-inbox-empty">보낸 친구 요청이 없습니다.</div>';
        outgoing.forEach(req => {
            const item = document.createElement("div");
            item.className = "chess-request-item";
            item.innerHTML = `
                <img src="${escapeHTML(req.profile_image || "/static/default_profile.png")}" alt="">
                <span><strong>${escapeHTML(req.display_name || req.username)}</strong><small>친구 요청을 보냈습니다.</small></span>
                <button type="button" class="chess-cancel-request">요청 취소</button>`;
            item.querySelector(".chess-cancel-request").addEventListener("click", async () => {
                try { await api(`/api/friend-requests/${req.id}`, { method: "DELETE" }); loadInbox(); } catch (error) { alert(error.message); }
            });
            outgoingList.appendChild(item);
        });
    }

    document.querySelectorAll("[data-chess-inbox-tab]").forEach(tabBtn => tabBtn.addEventListener("click", () => {
        document.querySelectorAll("[data-chess-inbox-tab]").forEach(btn => btn.classList.remove("active"));
        tabBtn.classList.add("active");
        const tab = tabBtn.dataset.chessInboxTab;
        incomingList.hidden = tab !== "incoming";
        outgoingList.hidden = tab !== "outgoing";
    }));

    inboxBtn.addEventListener("click", () => { inboxModal.hidden = false; loadInbox(); });
    document.querySelector("#close-chess-inbox").addEventListener("click", () => { inboxModal.hidden = true; });
    inboxModal.addEventListener("click", event => { if (event.target === inboxModal) inboxModal.hidden = true; });

    refreshInboxBadge();
    if (window.io) {
        const socket = io();
        socket.on("friend_updated", () => { refreshInboxBadge(); if (!friendsModal.hidden) loadFriendList(); if (!inboxModal.hidden) loadInbox(); });
        socket.on("chess_invite", () => { refreshInboxBadge(); if (!inboxModal.hidden) loadInbox(); });
    }
}());
