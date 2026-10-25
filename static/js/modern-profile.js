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
    const page = $("#modern-profile-page");
    const body = $("#modern-profile-body");
    const relationsOverlay = $("#modern-relations-overlay");
    if (!page || !body || !relationsOverlay || !$("#modern-search-overlay")) return;

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
    const rail = $("#modern-rail");

    /** 왼쪽 메뉴의 '지금 보는 곳' 표시. 채팅 아이콘은 보고 있을 때 안쪽이 채워진 모양(solid)으로 바뀐다. */
    function setRailActive(name) {
        if (!rail) return;
        rail.querySelectorAll('[data-rail="chats"], [data-rail="profile"]').forEach((button) => {
            const active = button.dataset.rail === name;
            button.classList.toggle("active", active);
            if (active) button.setAttribute("aria-current", "page");
            else button.removeAttribute("aria-current");
        });
        const chatIcon = rail.querySelector('[data-rail="chats"] i');
        if (chatIcon) {
            chatIcon.classList.toggle("fa-solid", name === "chats");
            chatIcon.classList.toggle("fa-regular", name !== "chats");
        }
    }

    /** 주소 표시줄을 /u/<아이디> 또는 /chat으로 바꾼다(새로 불러오지 않는다). replace가 true면 기록을 쌓지 않는다. */
    function setAddress(path, replace) {
        if (location.pathname === path) return;
        try { history[replace ? "replaceState" : "pushState"]({}, "", path); } catch (error) { /* 주소 변경이 막힌 환경 */ }
    }

    /** 프로필 페이지를 연다. fromAddress가 true면 주소창/뒤로가기에서 온 것이라 주소를 다시 바꾸지 않는다. */
    async function showProfilePage(load, fromAddress) {
        document.body.classList.add("modern-profile-page");
        setRailActive("profile");
        body.innerHTML = `<p class="mp-loading">…</p>`;
        window.scrollTo(0, 0);
        const { ok, data } = await load();
        if (!document.body.classList.contains("modern-profile-page")) return; // 불러오는 사이 채팅으로 돌아갔다.
        if (!ok) {
            shownUserId = null;
            body.innerHTML = `<p class="mp-loading">${escapeHTML(data.error || "프로필을 불러오지 못했습니다.")}</p>`;
            return;
        }
        shownUserId = data.id;
        renderProfile(data);
        if (!fromAddress) setAddress(`/u/${encodeURIComponent(data.username)}`, false);
    }

    function openModernProfile(userId, fromAddress) {
        shownUserId = userId;
        return showProfilePage(() => api(`/api/users/${userId}/summary`), fromAddress);
    }

    function openModernProfileByUsername(username, fromAddress) {
        return showProfilePage(() => api(`/api/profiles/${encodeURIComponent(username)}`), fromAddress);
    }

    /** 프로필 페이지를 닫고 채팅 화면으로 돌아간다. 열려 있지 않으면 아무것도 하지 않는다. */
    function closeModernProfile(fromAddress) {
        if (!document.body.classList.contains("modern-profile-page")) return;
        shownUserId = null;
        document.body.classList.remove("modern-profile-page");
        body.innerHTML = "";
        setRailActive("chats");
        if (!fromAddress) setAddress("/chat", false);
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
            $(act === "report" ? "#profile-card-report" : "#profile-card-block").click();
        }
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

    /**
     * 사용자 행(팔로워·팔로잉·검색 결과 공통)의 버튼 동작. 처리 후에는 refresh로 목록과 열려 있는 프로필을 새로 그린다.
     */
    async function handleRowClick(event, refresh, closeList) {
        const button = event.target.closest("[data-act]");
        const row = event.target.closest(".mr-row");
        if (!button || !row) return;
        const userId = Number(row.dataset.userId);
        const act = button.dataset.act;
        if (act === "profile") {
            closeList();
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
    }

    relationsList.addEventListener("click", (event) =>
        handleRowClick(
            event,
            async () => {
                await loadRelations(true);
                if (shownUserId !== null) openModernProfile(shownUserId, true);
            },
            closeRelations
        )
    );
    $("#modern-relations-close").addEventListener("click", closeRelations);
    relationsOverlay.addEventListener("click", (event) => {
        if (event.target === relationsOverlay) closeRelations();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (relationsOverlay.style.display === "flex") closeRelations();
        else if (searchOverlay.style.display === "flex") closeModernSearch();
    });

    // ------------------------------------------------------------------
    // 사용자 검색(왼쪽 메뉴의 '검색')
    // ------------------------------------------------------------------
    const searchOverlay = $("#modern-search-overlay");
    const searchInput = $("#modern-search-q");
    const searchList = $("#modern-search-list");
    let searchSeq = 0;

    async function runUserSearch() {
        const query = searchInput.value.trim();
        const seq = ++searchSeq;
        if (query.length < 2) {
            searchList.innerHTML = `<p class="mr-empty">아이디나 이름을 2글자 이상 입력해주세요.</p>`;
            return;
        }
        const { ok, data } = await api(`/api/users/find?${new URLSearchParams({ q: query })}`);
        if (seq !== searchSeq) return; // 더 새로운 검색이 진행 중이다.
        searchList.innerHTML = "";
        if (!ok) {
            searchList.innerHTML = `<p class="mr-empty">${escapeHTML(data.error || "검색하지 못했습니다.")}</p>`;
            return;
        }
        if (!data.users.length) {
            searchList.innerHTML = `<p class="mr-empty">검색 결과가 없어요</p>`;
            return;
        }
        data.users.forEach((user) => searchList.appendChild(relationRow(user, { userId: null, kind: "search" })));
    }

    function openModernSearch() {
        searchOverlay.style.display = "flex";
        searchInput.value = "";
        searchSeq++;
        searchList.innerHTML = `<p class="mr-empty">아이디나 이름을 2글자 이상 입력해주세요.</p>`;
        setTimeout(() => searchInput.focus(), 30);
    }

    function closeModernSearch() {
        searchOverlay.style.display = "none";
        searchList.innerHTML = "";
    }

    let userSearchTimer = null;
    searchInput.addEventListener("input", () => {
        clearTimeout(userSearchTimer);
        userSearchTimer = setTimeout(runUserSearch, 300);
    });
    searchList.addEventListener("click", (event) => handleRowClick(event, runUserSearch, closeModernSearch));
    $("#modern-search-close").addEventListener("click", closeModernSearch);
    searchOverlay.addEventListener("click", (event) => {
        if (event.target === searchOverlay) closeModernSearch();
    });

    // 상대가 팔로우 요청·수락·취소를 하면 열려 있는 화면의 숫자와 버튼을 새로 고친다.
    if (typeof socket !== "undefined") {
        socket.on("follow_updated", () => {
            if (document.body.classList.contains("modern-profile-page") && shownUserId !== null) openModernProfile(shownUserId, true);
            if (relationsState) loadRelations(true);
        });
    }

    // 1:1 대화에서 받은 메시지 옆의 상대 사진을 누르면 그 사람의 프로필을 연다.
    document.addEventListener("click", (event) => {
        const avatar = event.target.closest(".msg-avatar");
        if (!avatar || !document.body.classList.contains("ui-modern")) return;
        const room = getCurrentFriend();
        if (room && !room.isGroup && room.peerId) openModernProfile(room.peerId);
    });

    // 뒤로가기/앞으로가기: 주소가 /u/<아이디>면 그 프로필 페이지를, 아니면 채팅 화면을 보여 준다.
    window.addEventListener("popstate", () => {
        if (!document.body.classList.contains("ui-modern")) return;
        const match = location.pathname.match(/^\/u\/([^/]+)/);
        if (match) openModernProfileByUsername(decodeURIComponent(match[1]), true);
        else closeModernProfile(true);
    });

    window.openModernProfile = openModernProfile;
    window.closeModernProfile = () => closeModernProfile(false);
    window.openModernSearch = openModernSearch;
    // 메시지함(modern-inbox.js)이 같은 요청 함수와 대화방 열기를 쓴다.
    window.ModernUi = { api, avatarHTML, openConversation, confirmThen };

    // /u/<아이디> 주소로 바로 들어온 경우: 모던이면 프로필 페이지를, 클래식이면 채팅 화면으로 주소를 고친다.
    if (typeof INITIAL_PROFILE_USERNAME === "string" && INITIAL_PROFILE_USERNAME) {
        if (document.body.classList.contains("ui-modern")) openModernProfileByUsername(INITIAL_PROFILE_USERNAME, true);
        else setAddress("/chat", true);
    }
})();
