/*
 * 모던 UI 동작.
 *
 * script.js 뒤에 로드되며, 모던 UI의 새 요소(왼쪽 아이콘 줄, 목록 위쪽의 검색·제목, 헤더의 (i) 버튼, 정보 패널의 액션)만 맡는다.
 * 기능 자체는 새로 만들지 않는다. 새 버튼은 기존 버튼을 대신 눌러 주고(.click()), 기존 요소의 상태(메시지함 숫자,
 * 내 이름·사진)는 관찰해서 그대로 옮겨 보여 준다. 클래식 UI에서는 새 요소가 CSS로 숨겨져 있어 이 파일은 아무 일도 하지 않는다.
 */
(function () {
    "use strict";

    /** CSS 선택자로 요소 하나를 찾는다. */
    const $ = (selector) => document.querySelector(selector);

    const rail = $("#modern-rail");
    // 템플릿(index.html)에 아이콘 줄이 없는 페이지(예: 로그인 화면)에서는 아무것도 하지 않는다.
    if (!rail) return;

    // ---------------------------------------------------------------
    // 1) 아이콘 줄과 목록 위쪽 버튼: 기존 버튼을 대신 눌러 준다.
    // ---------------------------------------------------------------
    /** data-rail 값 → 대신 눌러 줄 기존 버튼의 선택자. 설정 메뉴('more')는 아래에서 따로 처리한다. */
    const RAIL_TARGETS = {
        group: "#open-new-group-btn",
        profile: "#edit-profile-btn"
    };

    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-rail]");
        if (!button) return;
        const action = button.dataset.rail;

        if (action === "more") return; // 아래 capture 리스너가 처리한다.
        if (action === "chats" && window.closeModernProfile) {
            // 프로필 페이지를 보고 있었다면 채팅 화면으로 돌아간다(채팅 아이콘이 다시 채워진다).
            window.closeModernProfile();
            return;
        }
        if (action === "profile" && window.openModernProfile) {
            window.openModernProfile(MY_USER_ID);
            return;
        }
        if (action === "search" && window.openModernSearch) {
            window.openModernSearch();
            return;
        }
        if (action === "inbox" && window.openModernInbox) {
            window.openModernInbox();
            return;
        }
        const target = RAIL_TARGETS[action] && $(RAIL_TARGETS[action]);
        if (target) target.click();
    });

    // '더 보기'는 누를 때마다 열고 닫는다. script.js의 문서 클릭 리스너가 '바깥 클릭'으로 먼저 메뉴를 닫아 버리면 다시 열려 버리므로,
    // 캡처 단계에서 먼저 처리하고 다른 리스너에는 전달하지 않는다.
    document.addEventListener("click", function (event) {
        const button = event.target.closest('[data-rail="more"]');
        if (!button) return;
        event.stopImmediatePropagation();
        if ($("#settings-menu").style.display === "block") closeSettingsMenu();
        else openSettingsFromRail(button);
    }, true);

    /**
     * '더 보기' 버튼 옆에 설정 메뉴를 연다. script.js의 openSettingsMenu는 메뉴를 버튼 오른쪽 '위쪽 정렬'로 놓는데,
     * 이 버튼은 화면 아래에 있어서 메뉴가 잘린다. 그래서 연 뒤에 메뉴의 아래쪽을 버튼 아래쪽에 맞춰 올려 준다.
     */
    function openSettingsFromRail(button) {
        const menu = $("#settings-menu");
        openSettingsMenu(button);
        if (isMobileViewport()) return;
        const rail = $("#modern-rail");
        // 아이콘 줄은 마우스를 올리면 펼쳐지므로, 펼쳐진 폭(244px) 기준으로 카드를 옆에 붙인다.
        const railRight = rail ? rail.getBoundingClientRect().left + Math.max(rail.offsetWidth, 244) : 244;
        menu.style.left = railRight + 8 + window.scrollX + "px";
        const rect = button.getBoundingClientRect();
        const top = Math.max(10, Math.min(rect.bottom - menu.offsetHeight, window.innerHeight - menu.offsetHeight - 10));
        menu.style.top = top + window.scrollY + "px";
    }

    // ---------------------------------------------------------------
    // 1-2) '더 보기'는 버튼을 눌러야 설정 카드가 열리고, 다시 누르거나 바깥을 누르거나 Esc를 누르면 닫힌다.
    // ---------------------------------------------------------------
    const moreButton = $('[data-rail="more"]');
    const settingsCard = $("#settings-menu");
    if (moreButton && settingsCard) {
        // 카드가 열려 있는 동안에는 아이콘 줄이 접히지 않게 해서, 카드가 줄 옆에 붙어 있게 한다(CSS의 modern-more-open).
        new MutationObserver(function () {
            rail.classList.toggle("modern-more-open", settingsCard.style.display === "block");
        }).observe(settingsCard, { attributes: true, attributeFilter: ["style"] });

        // 키보드: Esc로 닫고 버튼으로 포커스를 돌려준다.
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && settingsCard.style.display === "block" && document.body.classList.contains("ui-modern")) {
                closeSettingsMenu();
                moreButton.focus();
            }
        });
    }

    // ---------------------------------------------------------------
    // 2) 메시지함 숫자 배지는 modern-inbox.js가 서버의 요청 수(팔로우 요청 + 메시지 요청)로 채운다.
    // ---------------------------------------------------------------

    // ---------------------------------------------------------------
    // 3) 내 이름·사진 복사 (원본: #current-username, #side-nav-profile-pic)
    // ---------------------------------------------------------------
    const sourceName = $("#current-username");
    const modernName = $("#modern-list-username");
    const sourcePic = $("#side-nav-profile-pic");
    const railAvatar = rail.querySelector(".modern-rail-avatar");

    /** 프로필을 바꾸면 원본이 바뀌므로, 이름과 사진을 다시 복사한다. */
    function syncProfile() {
        if (sourceName && modernName) modernName.textContent = sourceName.textContent;
        if (sourcePic && railAvatar) railAvatar.innerHTML = sourcePic.innerHTML;
    }
    [sourceName, sourcePic].forEach(function (node) {
        if (node) new MutationObserver(syncProfile).observe(node, { childList: true, characterData: true, subtree: true, attributes: true });
    });
    syncProfile();

    // ---------------------------------------------------------------
    // 4) 대화 검색: 목록의 행을 이름·미리보기 글자로 걸러 낸다.
    // ---------------------------------------------------------------
    const searchInput = $("#modern-conv-search");
    const conversationList = $("#friend-list");

    /** 검색어가 들어 있지 않은 대화방 행을 숨긴다. 검색어가 비어 있으면 모두 보인다. */
    function filterConversations() {
        if (!searchInput || !conversationList) return;
        const query = searchInput.value.trim().toLowerCase();
        conversationList.querySelectorAll(".friend").forEach(function (row) {
            row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
        });
    }
    if (searchInput && conversationList) {
        searchInput.addEventListener("input", filterConversations);
        // 새 메시지·읽음 처리로 목록이 다시 그려지면 걸러 둔 상태도 다시 적용한다.
        new MutationObserver(filterConversations).observe(conversationList, { childList: true });
    }

    // ---------------------------------------------------------------
    // 5) 대화 정보 패널: 헤더의 (i) 버튼으로 열고 닫는다.
    // ---------------------------------------------------------------
    const infoToggle = $("#modern-info-toggle");
    if (infoToggle) {
        infoToggle.addEventListener("click", function () {
            const open = document.body.classList.toggle("modern-info-open");
            infoToggle.setAttribute("aria-pressed", String(open));
        });
    }

    // ---------------------------------------------------------------
    // 6) 정보 패널의 액션: 헤더에서 빠진 기능을 기존 버튼으로 연다.
    // ---------------------------------------------------------------
    /** data-info-action 값 → 대신 눌러 줄 기존 버튼의 선택자. */
    const INFO_TARGETS = {
        theme: "#chat-theme-btn",
        gallery: "#gallery-toggle-btn",
        search: "#search-toggle-btn",
        members: "#group-members-btn"
    };
    const infoActions = $("#modern-info-actions");
    if (infoActions) {
        infoActions.addEventListener("click", function (event) {
            const button = event.target.closest("[data-info-action]");
            const target = button && $(INFO_TARGETS[button.dataset.infoAction]);
            if (target) target.click();
        });
    }

    // 대화방을 고르기 전에는 액션을 숨기고, 그룹 채팅일 때만 '그룹 관리'를 보인다. 둘 다 script.js가 기존 요소에 쓴 표시 상태를 따른다.
    const conversationActions = $("#desktop-conversation-actions");
    const groupMembersButton = $("#group-members-btn");
    const membersAction = infoActions && infoActions.querySelector('[data-info-action="members"]');

    /** 기존 요소의 display 값을 읽어 정보 패널의 액션 표시를 맞춘다. */
    function syncInfoActions() {
        if (!infoActions) return;
        infoActions.hidden = !conversationActions || conversationActions.style.display === "none";
        if (membersAction && groupMembersButton) membersAction.hidden = groupMembersButton.style.display === "none";
    }
    [conversationActions, groupMembersButton].forEach(function (node) {
        if (node) new MutationObserver(syncInfoActions).observe(node, { attributes: true, attributeFilter: ["style"] });
    });
    syncInfoActions();
})();
