/*
 * 모던 UI의 프로필 화면과 팔로워/팔로잉 목록.
 *
 * script.js 뒤에 로드된다. 서버의 팔로우 API(blueprints/follows.py)만 호출하고, 대화방 열기·알림창·확인창은
 * script.js의 전역 함수(showAlert, showConfirm, loadFriends 등)를 그대로 쓴다. 화면 문구는 DOM에 그려지면
 * i18n.js의 관찰자가 번역하므로 번역 키와 같은 글자로 그린다.
 */
(function () {
    "use strict";

    const $ = (selector) => document.querySelector(selector);
    const overlay = $("#modern-profile-overlay");
    const body = $("#modern-profile-body");
    const relationsOverlay = $("#modern-relations-overlay");
    if (!overlay || !body || !relationsOverlay) return;

    const relationsTitle = $("#modern-relations-title");
    const relationsSearch = $("#modern-relations-q");
    const relationsList = $("#modern-relations-list");

    let shownUserId = null;
    let relationsState = null; // { userId, kind, query, offset }

    const avatarHTML = (image) =>
        image
            ? `<img src="${escapeHTML(image)}" alt="">`
            : `<i class="fa-solid fa-circle-user"></i>`;

    /** fetch 결과를 { ok, data }로 정리한다. 서버 오류 문구는 data.error에 있다. */
    async function api(url, method = "GET", payload) {
        const options = { method };
        if (payload !== undefined) {
            options.headers = { "Content-Type": "application/json" };
            options.body = JSON.stringify(payload);
        }
        try {
            const response = await fetch(url, options);
            let data = {};
            try { data = await response.json(); } catch (error) { /* 본문이 없는 응답 */ }
            return { ok: response.ok && data.success !== false, data };
        } catch (error) {
            return { ok: false, data: { error: "네트워크 오류가 발생했습니다." } };
        }
    }

    // ------------------------------------------------------------------
    // 프로필 화면
    // ------------------------------------------------------------------
    async function openModernProfile(userId) {
        shownUserId = userId;
        overlay.style.display = "flex";
        body.innerHTML = `<p class="mp-loading">…</p>`;
        const { ok, data } = await api(`/api/users/${userId}/summary`);
        if (shownUserId !== userId) return; // 불러오는 사이 다른 프로필로 바뀌었다.
        if (!ok) {
            body.innerHTML = `<p class="mp-loading">${escapeHTML(data.error || "프로필을 불러오지 못했습니다.")}</p>`;
            return;
        }
        renderProfile(data);
    }

    function closeModernProfile() {
        shownUserId = null;
        overlay.style.display = "none";
        body.innerHTML = "";
    }

    function actionButtons(summary) {
        const relation = summary.relation;
        if (relation.status === "self") {
            return `<button type="button" class="mp-btn" data-act="edit">프로필 편집</button>`;
        }
        let followButton;
        if (relation.status === "following") {
            followButton = `<button type="button" class="mp-btn" data-act="unfollow">팔로잉 <i class="fa-solid fa-chevron-down"></i></button>`;
        } else if (relation.status === "requested") {
            followButton = `<button type="button" class="mp-btn" data-act="cancel">요청됨</button>`;
        } else {
            const label = relation.followsMe ? "맞팔로우" : "팔로우";
            followButton = `<button type="button" class="mp-btn mp-btn-primary" data-act="follow">${label}</button>`;
        }
        return `${followButton}<button type="button" class="mp-btn" data-act="message">메시지 보내기</button>`;
    }

    function renderProfile(summary) {
        const isSelf = summary.relation.status === "self";
        const canOpenLists = summary.canViewDetails;
        const bio = summary.bio ? `<p class="mp-bio">${escapeHTML(summary.bio)}</p>` : "";
        const privateNotice = summary.canViewDetails
            ? ""
            : `<p class="mp-private"><i class="fa-solid fa-lock"></i> <span>비공개 계정입니다</span><small>팔로우가 수락되면 소개글과 팔로워 목록을 볼 수 있어요.</small></p>`;
        const requestedMe = !isSelf && summary.relation.requestedMe
            ? `<p class="mp-note">이 사람이 팔로우를 요청했어요. 메시지함에서 수락할 수 있어요.</p>`
            : "";
        body.innerHTML = `
            <div class="mp-head">
                <div class="mp-avatar">${avatarHTML(summary.profileImage)}</div>
                <div class="mp-info">
                    <div class="mp-idrow">
                        <h2 id="modern-profile-id">${escapeHTML(summary.username)}</h2>
                        ${isSelf ? "" : `<button type="button" class="mp-more" data-act="more" aria-label="더 보기"><i class="fa-solid fa-ellipsis"></i></button>`}
                    </div>
                    <div class="mp-name">${escapeHTML(summary.displayName)}</div>
                    <div class="mp-counts">
                        <button type="button" data-rel="followers" ${canOpenLists ? "" : "disabled"}><b>${summary.followerCount}</b><span>팔로워</span></button>
                        <button type="button" data-rel="following" ${canOpenLists ? "" : "disabled"}><b>${summary.followingCount}</b><span>팔로잉</span></button>
                    </div>
                    ${bio}
                </div>
            </div>
            <div class="mp-actions">${actionButtons(summary)}</div>
            ${requestedMe}
            ${privateNotice}
            <div class="mp-menu" id="modern-profile-menu" hidden>
                <button type="button" data-act="report"><i class="fa-solid fa-flag"></i><span>신고하기</span></button>
                <button type="button" data-act="block"><i class="fa-solid fa-ban"></i><span>차단하기</span></button>
            </div>`;
        body.dataset.userId = summary.id;
        body.dataset.username = summary.displayName;
    }

    /** 대화방을 열어 채팅 화면으로 이동한다(script.js의 '채팅방 열기'와 같은 순서). */
    async function openConversation(conversationId) {
        await loadFriends();
        const conversation = friends.find((entry) => entry.id === conversationId);
        if (!conversation) {
            showAlert("채팅방을 불러오지 못했습니다. 다시 시도해주세요.");
            return;
        }
        currentConversationID = conversation.id;
        openMobileChat();
        updateChatHeader(conversation);
        updateBlockState();
        await fetch(`/api/conversations/${conversation.id}/read`, { method: "POST" });
        conversation.unreadCount = 0;
        readFriends();
        await readMessages();
        setTimeout(() => input.focus(), 10);
    }

    async function startMessage(userId) {
        const { ok, data } = await api(`/api/users/${userId}/message`, "POST");
        if (!ok) {
            showAlert(data.error || "대화를 시작하지 못했습니다.");
            return;
        }
        closeModernProfile();
        await openConversation(data.conversationId);
    }

    /** 팔로우 관계를 바꾸는 요청(팔로우 요청/언팔로우/요청 취소) 뒤에 화면을 새로 그린다. */
    async function changeFollow(userId, method) {
        const { ok, data } = await api(`/api/users/${userId}/follow`, method);
        if (!ok) {
            showAlert(data.error || "처리하지 못했습니다.");
            return false;
        }
        return true;
    }

    function confirmThen(message, run) {
        showConfirm(message, (accepted) => { if (accepted) run(); });
    }

    body.addEventListener("click", async (event) => {
        const relButton = event.target.closest("[data-rel]");
        if (relButton && !relButton.disabled) {
            openRelations(shownUserId, relButton.dataset.rel);
            return;
        }
        const button = event.target.closest("[data-act]");
        const menu = $("#modern-profile-menu");
        if (!button) {
            if (menu) menu.hidden = true;
            return;
        }
        const userId = shownUserId;
        const act = button.dataset.act;
        if (act === "edit") {
            closeModernProfile();
            openProfileEditor();
        } else if (act === "follow") {
            if (await changeFollow(userId, "POST")) openModernProfile(userId);
        } else if (act === "cancel") {
            if (await changeFollow(userId, "DELETE")) openModernProfile(userId);
        } else if (act === "unfollow") {
            confirmThen("팔로우를 취소하시겠습니까?", async () => {
                if (await changeFollow(userId, "DELETE")) openModernProfile(userId);
            });
        } else if (act === "message") {
            startMessage(userId);
        } else if (act === "more") {
            menu.hidden = !menu.hidden;
        } else if (act === "report" || act === "block") {
            // 기존 프로필 카드의 신고·차단 흐름(사유 선택, 확인창)을 그대로 쓴다.
            menu.hidden = true;
            profileCardTarget = { peerId: userId, name: body.dataset.username };
            closeModernProfile();
            $(act === "report" ? "#profile-card-report" : "#profile-card-block").click();
        }
    });
    $("#modern-profile-close").addEventListener("click", closeModernProfile);
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) closeModernProfile();
    });

    // ------------------------------------------------------------------
    // 팔로워/팔로잉 목록
    // ------------------------------------------------------------------
    function relationAction(user, isOwnList, kind) {
        const status = user.relation.status;
        if (status === "self") return "";
        if (isOwnList && kind === "followers") {
            return `<button type="button" class="mp-btn mp-btn-small" data-act="remove">삭제</button>`;
        }
        if (status === "following") return `<button type="button" class="mp-btn mp-btn-small" data-act="unfollow">팔로잉</button>`;
        if (status === "requested") return `<button type="button" class="mp-btn mp-btn-small" data-act="cancel">요청됨</button>`;
        return `<button type="button" class="mp-btn mp-btn-small mp-btn-primary" data-act="follow">${user.relation.followsMe ? "맞팔로우" : "팔로우"}</button>`;
    }

    function relationRow(user, state) {
        const row = document.createElement("div");
        row.className = "mr-row";
        row.dataset.userId = user.id;
        row.innerHTML = `
            <button type="button" class="mr-user" data-act="profile">
                <span class="mr-avatar">${avatarHTML(user.profileImage)}</span>
                <span class="mr-text"><b>${escapeHTML(user.username)}</b><small>${escapeHTML(user.displayName)}</small></span>
            </button>
            <div class="mr-action">${relationAction(user, state.userId === MY_USER_ID, state.kind)}</div>`;
        return row;
    }

    async function loadRelations(reset) {
        const state = relationsState;
        if (!state) return;
        if (reset) {
            state.offset = 0;
            relationsList.innerHTML = "";
        }
        const params = new URLSearchParams({ q: state.query, limit: "30", offset: String(state.offset) });
        const { ok, data } = await api(`/api/users/${state.userId}/${state.kind}?${params}`);
        if (relationsState !== state) return; // 검색어가 바뀌어 더 새로운 요청이 진행 중이다.
        relationsList.querySelector(".mr-more")?.remove();
        if (!ok) {
            relationsList.innerHTML = `<p class="mr-empty">${escapeHTML(data.error || "목록을 불러오지 못했습니다.")}</p>`;
            return;
        }
        data.users.forEach((user) => relationsList.appendChild(relationRow(user, state)));
        state.offset += data.users.length;
        if (!relationsList.children.length) {
            relationsList.innerHTML = `<p class="mr-empty">${state.query ? "검색 결과가 없어요" : "아직 없어요"}</p>`;
        } else if (data.hasMore) {
            const more = document.createElement("button");
            more.type = "button";
            more.className = "mr-more";
            more.textContent = "더 보기";
            more.addEventListener("click", () => loadRelations(false));
            relationsList.appendChild(more);
        }
    }

    function openRelations(userId, kind) {
        relationsState = { userId, kind, query: "", offset: 0 };
        relationsTitle.textContent = kind === "followers" ? "팔로워" : "팔로잉";
        relationsSearch.value = "";
        relationsOverlay.style.display = "flex";
        loadRelations(true);
    }

    function closeRelations() {
        relationsState = null;
        relationsOverlay.style.display = "none";
        relationsList.innerHTML = "";
    }

    let searchTimer = null;
    relationsSearch.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            if (!relationsState) return;
            relationsState = { ...relationsState, query: relationsSearch.value.trim() };
            loadRelations(true);
        }, 250);
    });

    relationsList.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-act]");
        const row = event.target.closest(".mr-row");
        if (!button || !row) return;
        const userId = Number(row.dataset.userId);
        const act = button.dataset.act;
        const refresh = async () => {
            await loadRelations(true);
            if (shownUserId !== null) openModernProfile(shownUserId);
        };
        if (act === "profile") {
            closeRelations();
            openModernProfile(userId);
        } else if (act === "follow") {
            if (await changeFollow(userId, "POST")) refresh();
        } else if (act === "cancel") {
            if (await changeFollow(userId, "DELETE")) refresh();
        } else if (act === "unfollow") {
            confirmThen("팔로우를 취소하시겠습니까?", async () => {
                if (await changeFollow(userId, "DELETE")) refresh();
            });
        } else if (act === "remove") {
            confirmThen("이 팔로워를 삭제하시겠습니까?", async () => {
                const { ok, data } = await api(`/api/users/${userId}/follower`, "DELETE");
                if (ok) refresh();
                else showAlert(data.error || "처리하지 못했습니다.");
            });
        }
    });
    $("#modern-relations-close").addEventListener("click", closeRelations);
    relationsOverlay.addEventListener("click", (event) => {
        if (event.target === relationsOverlay) closeRelations();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (relationsOverlay.style.display === "flex") closeRelations();
        else if (overlay.style.display === "flex") closeModernProfile();
    });

    // 상대가 팔로우 요청·수락·취소를 하면 열려 있는 화면의 숫자와 버튼을 새로 고친다.
    if (typeof socket !== "undefined") {
        socket.on("follow_updated", () => {
            if (overlay.style.display === "flex" && shownUserId !== null) openModernProfile(shownUserId);
            if (relationsState) loadRelations(true);
        });
    }

    window.openModernProfile = openModernProfile;
})();
