        /* ======================================================
         * 세션 만료 처리: API가 401을 주면 로그인 페이지로 보낸다.
         * ====================================================== */
        const _originalFetch = window.fetch;
        window.fetch = async function (...args) {
            const response = await _originalFetch(...args);
            if (response.status === 401) {
                window.location.href = "/login";
            }
            return response;
        };

        /* ======================================================
         * 상태 변수
         * ====================================================== */
        let currentConversationID = null;
        let selectedMessage = null;
        let selectedIndex = -1;
        let editingIndex = null;
        let replyMessage = null;
        let searchQuery = "";
        let searchMatches = [];
        let currentMatchIndex = 0;

        /* ======================================================
         * 데이터 로드 (서버 → 메모리)
         * 친구/채팅 모두 서버(Flask)가 진짜 데이터를 갖고 있고,
         * chats/friends는 화면을 그리기 위한 로컬 캐시일 뿐이다.
         * ====================================================== */

        const chats = {};
        let friends = [];
        let messageRefreshPromise = null;
        let lastMessageRefreshAt = 0;
        let pendingProfileImageData = null;
        let pendingProfileImageRemoval = false;
        let savedProfileImageHTML = "";

        async function loadFriends() {
            const response  = await fetch("/api/conversations");
            friends = await response.json();
            readFriends();
        }
            

        /* ======================================================
         * 저장/시간/친구 조회 헬퍼
         * ====================================================== */

        function formatNowTime() {
            const now = new Date();
            let hour = now.getHours();
            const minute = String(now.getMinutes()).padStart(2, "0");
            const period = hour >= 12 ? "오후" : "오전";
            hour = hour % 12;
            if (hour === 0) hour = 12;
            return `${period} ${hour}:${minute}`;
        }

        function todayDate() {
            return new Date().toISOString().split("T")[0];
        }

        function getCurrentFriend() {
            return friends.find(function (friend) { return friend.id === currentConversationID; });
        }

        function updateChatHeader(friend) {
            if (!friend) {
                chatHeader.innerText = "";
                chatHeaderAvatar.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
                chatHeaderAvatar.onclick = null;
                chatHeaderMemberCount.style.display = "none";
                if (chatPanel) chatPanel.classList.add("no-conversation");
                return;
            }

            if (chatPanel) chatPanel.classList.remove("no-conversation");
            chatHeader.innerText = friend.name;

            if (friend.isGroup) {
                // 서버에서 전달받은 그룹 프로필 이미지 변수 (groupProfileImage 또는 profileImage)
                const groupImg = friend.groupProfileImage || friend.profileImage;

                chatHeaderAvatar.innerHTML = groupImg
                    ? `<img src="${groupImg}">`
                    : `<i class="fa-solid fa-users"></i>`;

                // 이미지 클릭 시 확대 모달 연결
                chatHeaderAvatar.onclick = groupImg
                    ? function () {
                        modalImage.src = groupImg;
                        imageModal.style.display = "flex";
                    }
                    : null;

                chatHeaderAvatar.style.display = "inline";
                chatHeaderMemberCount.innerText = friend.memberCount;
            } else {
                chatHeaderAvatar.innerHTML = friend.peerProfileImage
                ? `<img src="${friend.peerProfileImage}">`
                : `<i class="fa-solid fa-circle-user"></i>`;
                // 사진이 있을 때만 클릭 시 확대 (수정은 안 되고 보기만)
                chatHeaderAvatar.onclick = friend.peerProfileImage
                    ? function () {
                        modalImage.src = friend.peerProfileImage;
                        imageModal.style.display = "flex";
                      }
                    : null;
                chatHeaderMemberCount.style.display = "none";
            }
        }

        /* 현재 열려있는 대화방이 차단 상태(내가 차단했거나, 상대가 나를 차단)면
         * 입력창/전송/첨부 버튼을 잠그고 안내 배너를 띄운다. */
        function updateBlockState() {
            const friend = getCurrentFriend();
            const blocked = !!(friend && !friend.isGroup && (friend.blockedByMe || friend.blockedMe));

            blockBanner.style.display = blocked ? "flex" : "none";
            input.disabled = blocked;
            button.disabled = blocked;
            plusBtn.disabled = blocked;
            input.placeholder = blocked ? "차단된 사용자입니다" : "메시지를 입력하세요";
        }

        function updateFriendPreviewFromSever() {
            const friend = getCurrentFriend();
            const chatList = chats[currentConversationID] || [];
            if (friend) {
                friend.message = getPreviewText(chatList);
                friend.lastTime = getPreviewTime(chatList);
                readFriends();
            }
        }

        function getPreviewText(chatList) {
            if (!chatList || chatList.length === 0) return "";
            const last = chatList[chatList.length - 1];
            return last.image ? "__CAMERA__사진" : last.text;
        }

        function getPreviewTime(chatList) {
            if (!chatList || chatList.length === 0) return "";
            return chatList[chatList.length - 1].time;
        }

        function isMessageRead(chat) {
            return !chat.unreadCount || chat.unreadCount <= 0;
        }

        function escapeHTML(text) {
            if (text == null) return"";
            const div = document.createElement("div");
            div.textContent = text;
            return div.innerHTML;
        }

        function highlightText(text, query) {
            const safeText = escapeHTML(text);
            if (!query) return linkifyText(safeText);
            const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const regex = new RegExp("(" + escapedQuery + ")", "gi");
            return safeText.replace(regex, '<mark class="search-highlight">$1</mark>');
        }

        const linkPreviewCache = new Map();
        const urlPattern = /https?:\/\/[^\s<>"']+/gi;

        function getFirstUrl(text) {
            const match = (text || "").match(urlPattern);
            return match ? match[0].replace(/[.,!?;:)]*$/, "") : null;
        }

        function linkifyText(safeText) {
            return safeText.replace(urlPattern, function (url) {
                const cleanUrl = url.replace(/[.,!?;:)]*$/, "");
                const suffix = url.slice(cleanUrl.length);
                return `<a class="message-link" href="${cleanUrl}" target="_blank" rel="noopener noreferrer">${cleanUrl}</a>${suffix}`;
            });
        }

        function createLinkPreview(preview) {
            const card = document.createElement("a");
            card.className = "link-preview";
            card.href = preview.url;
            card.target = "_blank";
            card.rel = "noopener noreferrer";
            const imageHTML = preview.image ? `<img class="link-preview-image" src="${escapeHTML(preview.image)}" alt="" onerror="this.remove()">` : "";
            card.innerHTML = `${imageHTML}<div class="link-preview-content"><div class="link-preview-domain">${escapeHTML(preview.domain)}</div><div class="link-preview-title">${escapeHTML(preview.title)}</div>${preview.description ? `<div class="link-preview-description">${escapeHTML(preview.description)}</div>` : ""}</div>`;
            return card;
        }

        async function appendLinkPreview(messageEl, chat) {
            const url = getFirstUrl(chat.text);
            if (!url) return;
            let preview = linkPreviewCache.get(url);
            if (preview === undefined) {
                try {
                    const response = await fetch("/api/link-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url }) });
                    const result = await response.json();
                    preview = result.success ? result.preview : null;
                } catch (error) {
                    preview = null;
                }
                linkPreviewCache.set(url, preview);
            }
            if (!preview || (!messageEl.isConnected && !messageEl.parentNode)) return;
            const card = createLinkPreview(preview);
            const content = messageEl.querySelector(".msg-content-col") || messageEl;
            const bubbleRow = content.querySelector(".bubble-row");

            if (bubbleRow) {
                content.insertBefore(card, bubbleRow);
            } else {
                content.prepend(card);
            }

            if (chat.mine) {
                messageEl.style.flexDirection = "column";
                messageEl.style.alignItems = "flex-end";
            } else if (!messageEl.querySelector(".msg-content-col")) {
                messageEl.style.flexDirection = "column";
                messageEl.style.alignItems = "flex-start";
            }
        }

        function buildReplyQuoteHTML(reply) {
            if (reply.image) {
                return `<img src="${reply.image}" class="reply-quote-image">`;
            }
            return `<div class="reply-quote">${escapeHTML(reply.text)}</div>`;
        }

        /* # 기준 요소(rect) 옆에 메뉴를 띄우고, 화면 밖으로 나가지 않게 좌표를 보정한다. */
        function positionMenuNear(menuEl, rect, preferLeft) {
            const menuWidth = menuEl.offsetWidth;
            const menuHeight = menuEl.offsetHeight;
            const scrollX = window.scrollX;
            const scrollY = window.scrollY;

            let left = preferLeft
                ? rect.left + scrollX - menuWidth - 10
                : rect.right + scrollX + 10;
            let top = rect.top + scrollY;

            if (left < 10) left = rect.right + scrollX + 10;
            if (left + menuWidth > window.innerWidth) left = rect.left + scrollX - menuWidth - 10;
            if (left < 10) left = 10;

            if (top + menuHeight > window.innerHeight + scrollY) top = rect.bottom + scrollY - menuHeight;
            if (top < 10) top = 10;

            menuEl.style.left = left + "px";
            menuEl.style.top = top + "px";
        }

        /* ======================================================
         * DOM 요소 참조
         * ====================================================== */

        const input = document.querySelector("#message");
        const button = document.querySelector("#send-btn");
        const messages = document.querySelector("#messages");
        const friendList = document.querySelector("#friend-list");
        const messageMenu = document.querySelector("#message-menu");
        const copyMessage = document.querySelector("#copy-message");
        const deleteMessage = document.querySelector("#delete-message");
        const editMessage = document.querySelector("#edit-message");
        const replyButton = document.querySelector("#reply-message");
        const cancelReply = document.querySelector("#cancel-reply");
        const replyText = document.querySelector("#reply-text");
        const replyPreview = document.querySelector("#reply-preview");
        const plusBtn = document.querySelector("#plus-btn");
        const attachMenu = document.querySelector("#attach-menu");
        const imageBtn = document.querySelector("#image-btn");
        const imageInput = document.querySelector("#image-input");
        const imageModal = document.querySelector("#image-modal");
        const modalImage = document.querySelector("#modal-image");
        const closeImage = document.querySelector("#close-image");
        const downloadImage = document.querySelector("#download-image");
        const reactionPicker = document.querySelector("#reaction-picker");
        const searchToggleBtn = document.querySelector("#search-toggle-btn");
        const searchBar = document.querySelector("#search-bar");
        const searchInput = document.querySelector("#search-input");
        const searchCount = document.querySelector("#search-count");
        const searchPrev = document.querySelector("#search-prev");
        const searchNext = document.querySelector("#search-next");
        const searchClose = document.querySelector("#search-close");
        const editPreview = document.querySelector("#edit-preview");
        const editPreviewText = document.querySelector("#edit-preview-text");
        const cancelEdit = document.querySelector("#cancel-edit");
        const replyImage = document.querySelector("#reply-image");
        const pinMessageButton = document.querySelector("#pin-message");
        const pinLabel = document.querySelector("#pin-label");
        const friendPanelTab = document.querySelector("#friend-panel-tab");
        const friendPanel = document.querySelector("#friend-panel");
        const closeFriendPanel = document.querySelector("#close-friend-panel");
        const newFriendInput = document.querySelector("#new-friend-input");
        const addFriendConfirmBtn = document.querySelector("#add-friend-confirm-btn");
        const friendRequestList = document.querySelector("#friend-request-list");
        const friendPanelList = document.querySelector("#friend-panel-list");
        const openNewGroupBtn = document.querySelector("#open-new-group-btn");
        const newGroupOverlay = document.querySelector("#new-group-overlay");
        const newGroupNameInput = document.querySelector("#new-group-name-input");
        const newGroupMemberList = document.querySelector("#new-group-member-list");
        const newGroupCancelBtn = document.querySelector("#new-group-cancel-btn");
        const newGroupCreateBtn = document.querySelector("#new-group-create-btn");
        const sideNavSettings = document.querySelector(".side-nav-settings");
        const settingsMenu = document.querySelector("#settings-menu");
        const logoutBtn = document.querySelector("#logout-btn");
        const editProfileBtn = document.querySelector("#edit-profile-btn");
        const myProfileOverlay = document.querySelector("#my-profile-overlay");
        const accountSettingsItem = document.querySelector("#account-settings-item");
        const notificationSettingsItem = document.querySelector("#notification-settings-item");
        const updateNoticeBadge = document.querySelector("#update-notice-badge");
        const updateHistoryList = document.querySelector("#update-history-list");
        const notificationSettingsOverlay = document.querySelector("#notification-settings-overlay");
        const notificationSettingsCloseBtn = document.querySelector("#notification-settings-close-btn");
        const helpItem = document.querySelector("#help-item");
        const helpOverlay = document.querySelector("#help-overlay");
        const helpCloseBtn = document.querySelector("#help-close-btn");
        const supportInquiryForm = document.querySelector("#support-inquiry-form");
        const supportMessage = document.querySelector("#support-message");
        const supportAttachment = document.querySelector("#support-attachment");
        const supportAttachmentName = document.querySelector("#support-attachment-name");
        const supportInquiryResult = document.querySelector("#support-inquiry-result");
        const supportInquirySubmitBtn = document.querySelector("#support-inquiry-submit-btn");
        const accountSettingsOverlay = document.querySelector("#account-settings-overlay");
        const accountSettingsCloseBtn = document.querySelector("#account-settings-close-btn");
        const newUsernameInput = document.querySelector("#new-username-input");
        const usernameChangePassword = document.querySelector("#username-change-password");
        const saveUsernameBtn = document.querySelector("#save-username-btn");
        const currentPasswordInput = document.querySelector("#current-password-input");
        const newPasswordInput = document.querySelector("#new-password-input");
        const savePasswordBtn = document.querySelector("#save-password-btn");
        const myProfileCancelBtn = document.querySelector("#my-profile-cancel-btn");
        const myProfileSaveBtn = document.querySelector("#my-profile-save-btn");
        const galleryToggleBtn = document.querySelector("#gallery-toggle-btn");
        const galleryOverlay = document.querySelector("#gallery-overlay");
        const closeGallery = document.querySelector("#close-gallery");
        const galleryGrid = document.querySelector("#gallery-grid");
        const groupMembersBtn = document.querySelector("#group-members-btn");
        const groupMembersOverlay = document.querySelector("#group-members-overlay");
        const groupMembersList = document.querySelector("#group-members-list");
        const closeGroupMembersBtn = document.querySelector("#close-group-members-btn");
        const leaveGroupBtn = document.querySelector("#leave-group-btn");
        const groupNameText = document.querySelector("#group-name-text");
        const renameGroupBtn = document.querySelector("#rename-group-btn");
        const groupPhotoImg = document.querySelector("#group-photo-img");
        const changeGroupPhotoBtn = document.querySelector("#change-group-photo-btn");
        const groupPhotoInput = document.querySelector("#group-photo-input");
        const removeGroupPhotoBtn = document.querySelector("#remove-group-photo-btn");
        const openInviteMemberBtn = document.querySelector("#open-invite-member-btn");
        const inviteMemberOverlay = document.querySelector("#invite-member-overlay");
        const inviteMemberList = document.querySelector("#invite-member-list");
        const inviteMemberCancelBtn = document.querySelector("#invite-member-cancel-btn");
        const inviteMemberConfirmBtn = document.querySelector("#invite-member-confirm-btn");
        let currentGroupMembers = [];
        let currentGroupOwnerId = null;

        const chatPanel = document.querySelector(".chat");
        const chatHeader = document.querySelector(".chat-header h2");
        const chatHeaderAvatar = document.querySelector("#chat-header-avatar");
        const chatHeaderMemberCount = document.querySelector("#chat-header-member-count");
        const blockBanner = document.querySelector("#block-banner");

        const modalOverlay = document.querySelector("#modal-overlay");
        const modalMessage = document.querySelector("#modal-message");
        const modalCancelBtn = document.querySelector("#modal-cancel-btn");
        const modalConfirmBtn = document.querySelector("#modal-confirm-btn");

        const themeToggleItem = document.querySelector("#theme-toggle-item");
        const themeToggleIcon = document.querySelector("#theme-toggle-icon");
        const themeToggleLabel = document.querySelector("#theme-toggle-label");
        const deleteAccountPassword = document.querySelector("#delete-account-password");
        const deleteAccountBtn = document.querySelector("#delete-account-btn");
        const profileImageInput = document.querySelector("#profile-image-input");
        const changeProfilePicBtn = document.querySelector("#change-profile-pic-btn");
        const removeProfilePicBtn = document.querySelector("#remove-profile-pic-btn");
        const profileModalPic = document.querySelector("#profile-modal-pic");
        const sideNavProfilePic = document.querySelector("#side-nav-profile-pic");
        const videoBtn = document.querySelector("#video-btn");
        const videoInput = document.querySelector("#video-input");
        const newEmailInput = document.querySelector("#new-email-input");
        const sendEmailCodeBtn = document.querySelector("#send-email-code-btn");
        const emailCodeInput = document.querySelector("#email-code-input");
        const emailChangePassword = document.querySelector("#email-change-password");
        const saveEmailBtn = document.querySelector("#save-email-btn");
        const currentEmailText = document.querySelector("#current-email-text");
        const outgoingFriendRequestList = document.querySelector(
            "#outgoing-friend-request-list"
        );

        /* ======================================================
         * 다크모드
         * ====================================================== */

        const savedTheme = localStorage.getItem("theme");
        if (savedTheme === "dark") {
            document.body.classList.add("dark-mode");
            themeToggleIcon.className = "fa-solid fa-sun";
            themeToggleLabel.innerText = "라이트 모드";
        }

        themeToggleItem.addEventListener("click", function (event) {
            event.stopPropagation();
            settingsMenu.style.display = "none";
            document.body.classList.toggle("dark-mode");

            if (document.body.classList.contains("dark-mode")) {
                localStorage.setItem("theme", "dark");
                themeToggleIcon.className = "fa-solid fa-sun";
                themeToggleLabel.innerText = "라이트 모드";
            } else {
                localStorage.setItem("theme", "light");
                themeToggleIcon.className = "fa-solid fa-moon";
                themeToggleLabel.innerText = "다크 모드";
            }
        });

        /* ======================================================
         * 커스텀 확인/알림 모달
         * ====================================================== */

        function showConfirm(message, onConfirm) {
            modalMessage.innerText = message;
            modalCancelBtn.style.display = "inline-block";
            modalOverlay.style.display = "flex";

            function cleanup() {
                modalOverlay.style.display = "none";
                modalConfirmBtn.removeEventListener("click", onOk);
                modalCancelBtn.removeEventListener("click", onCancel);
            }
            function onOk() { cleanup(); onConfirm(true); }
            function onCancel() { cleanup(); onConfirm(false); }

            modalConfirmBtn.addEventListener("click", onOk);
            modalCancelBtn.addEventListener("click", onCancel);
        }

        function showAlert(message, onClose) {
            modalMessage.innerText = message;
            modalCancelBtn.style.display = "none";
            modalOverlay.style.display = "flex";

            function cleanup() {
                modalOverlay.style.display = "none";
                modalConfirmBtn.removeEventListener("click", onOk);
            }
            function onOk() { cleanup(); if (onClose) onClose(); }

            modalConfirmBtn.addEventListener("click", onOk);
        }

        function focusInputSafely() {
            setTimeout(function () { input.focus(); }, 50);
        }

        /* ======================================================
         * 검색
         * ====================================================== */

        function performSearch(query) {
            searchQuery = query;
            const chatList = chats[currentConversationID] || [];

            searchMatches = [];
            chatList.forEach(function (chat, index) {
                if (chat.text && query !== "" && chat.text.toLowerCase().includes(query.toLowerCase())) {
                    searchMatches.push(index);
                }
            });

            currentMatchIndex = 0;
            readMessages();
            updateSearchCount();
            scrollToMatch();
        }

        function updateSearchCount() {
            searchCount.innerText = searchMatches.length === 0
                ? "0/0"
                : (currentMatchIndex + 1) + "/" + searchMatches.length;
        }

        function scrollToMatch() {
            if (searchMatches.length === 0) return;
            const targetIndex = searchMatches[currentMatchIndex];
            const el = messages.querySelector('[data-msg-index="' + targetIndex + '"]');
            if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        }

        
        /* ======================================================
         * 메시지 전송 / 수정
         * ====================================================== */

        async function sendMessage() {
            const planeIcon = document.querySelector(".input-area button i.fa-paper-plane");
            if (planeIcon) {
                planeIcon.classList.remove("launch");
                void planeIcon.offsetWidth;      // 같은 애니메이션을 연속으로 눌러도 재생되게 강제 리플로우
                planeIcon.classList.add("launch");
            }

            const text = input.value.trim();
            if (text === "") return;

            if (editingIndex !== null) {
                await fetch(`/api/messages/${editingIndex}`, {
                    method: "PATCH",
                    headers: {"Content-Type": "application/json" },
                    body: JSON.stringify({ text:text })
                });

                await readMessages();
                updateFriendPreviewFromSever();

                editingIndex = null;
                input.value = "";
                replyMessage = null;
                replyPreview.style.display = "none";
                editPreview.style.display = "none";
                button.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
                return;
            }

            const time = formatNowTime();
            const today = todayDate();

            const response = await fetch(`/api/conversations/${currentConversationID}/messages`, {
                method: "POST",
                headers: { "Content-Type": "application/json"},
                body: JSON.stringify({
                    text: text,
                    time: time,
                    date: today,
                    mine: true,
                    reply: replyMessage,
                    read: false
                })
            });
            const result = await response.json();
            if (!result.success) {
                showAlert(result.error);
                return;
            }

            await readMessages();
            updateFriendPreviewFromSever();

            input.value = "";
            replyMessage = null;
            replyPreview.style.display = "none";

            setTimeout(function () { input.focus(); }, 10);
        }

        /* ======================================================
         * 메시지 렌더링
         * ====================================================== */
        
            
        async function readMessages() {
            if (messageRefreshPromise) return messageRefreshPromise;

            messageRefreshPromise = renderMessages();
            try {
                return await messageRefreshPromise;
            } finally {
                messageRefreshPromise = null;
                lastMessageRefreshAt = Date.now();
            }
        }

        async function renderMessages() {

            if (currentConversationID === null) {
                if (chatPanel) chatPanel.classList.add("no-conversation");
                messages.innerHTML = `
                    <div class="empty-chat">
                        <div class="empty-chat-icon"><i class="fa-solid fa-paper-plane"></i></div>
                        <div class="empty-chat-title">아직 열린 대화가 없어요</div>
                        <div class="empty-chat-subtitle">친구를 추가하고 대화를 시작해보세요!</div>
                        <button id="empty-chat-add-friend-btn" class="empty-chat-cta"><i class="fa-solid fa-user-plus"></i> 친구 추가하기</button>
                    </div>
                `;
                const emptyChatAddFriendBtn = document.querySelector("#empty-chat-add-friend-btn");
                if (emptyChatAddFriendBtn) {
                    emptyChatAddFriendBtn.addEventListener("click", function () {
                        friendPanel.classList.add("open");
                        loadFriendRequests();
                    });
                }
                return;
            }

            if (chatPanel) chatPanel.classList.remove("no-conversation");

            const response = await fetch(`/api/conversations/${currentConversationID}/messages`);
            const chatList = await response.json();
            chats[currentConversationID] = chatList;
            const pinnedBox = document.querySelector("#pinned-message");
            const currentConversationsInfo = getCurrentFriend();
            const isGroupChat = !!(currentConversationID && currentConversationsInfo.isGroup);
            groupMembersBtn.style.display = isGroupChat ? "inline-block" : "none";

            const renderTarget = document.createDocumentFragment();

            if (chatList.length === 0) {
                pinnedBox.style.display = "none";
                pinnedBox.innerHTML = "";
                pinnedBox.onclick = null;

                messages.innerHTML = `
                    <div class="empty-chat">
                        <i class="fa-regular fa-comments"></i>
                        <div>아직 대화가 없어요. 메시지를 보내보세요!</div>
                    </div>
                `;
                return;
            }

            const pinnedChat = chatList.find(function (chat) { return chat.pinned; }) || null;
            if (pinnedChat) {
                pinnedBox.style.display = "flex";
                pinnedBox.style.cursor = "pointer";

                const pinnedPreview = pinnedChat.image
                    ? `<img src="${pinnedChat.image}" style="width:32px; height:32px; border-radius:8px; object-fit:cover;"><span style="flex:1;">사진</span>`
                    : `<span style="flex:1;">${pinnedChat.text}</span>`;

                pinnedBox.innerHTML = `
                    <i class="fa-solid fa-thumbtack"></i>
                    ${pinnedPreview}
                    <i class="fa-solid fa-xmark"></i>
                `;
                pinnedBox.onclick = async function () {
                    await fetch(`/api/messages/${pinnedChat.id}/pin`, {
                        method: "POST"
                    });
                    await readMessages();
                };
            } else {
                pinnedBox.style.display = "none";
                pinnedBox.innerHTML = "";
                pinnedBox.onclick = null;
            }

            let lastDate = "";
            chatList.forEach(function (chat, index) {

                if (chat.date !== lastDate) {
                    const dateLine = document.createElement("div");
                    dateLine.className = "date-divider";
                    dateLine.innerText = chat.date;
                    renderTarget.appendChild(dateLine);
                    lastDate = chat.date;
                }

                const message = document.createElement("div");
                message.dataset.msgIndex = index;

                message.addEventListener("contextmenu", function (event) {
                    event.preventDefault();

                    selectedMessage = chat;
                    selectedIndex = chat.id;
                    pinLabel.innerText = chat.pinned ? "고정 해제" : "고정";

                    if (chat.image || chat.video) {
                        replyButton.style.display = "block";
                        editMessage.style.display = "none";
                        copyMessage.style.display = "none";
                        deleteMessage.style.display = chat.mine ? "block" : "none";
                    } else {
                        replyButton.style.display = "block";
                        copyMessage.style.display = "block";
                        editMessage.style.display = chat.mine ? "block" : "none";
                        deleteMessage.style.display = chat.mine ? "block" : "none";
                    }

                    messageMenu.style.display = "block";
                    messageMenu.style.pointerEvents = "auto";

                    let target = (chat.image || chat.video)
                        ? message.querySelector(".chat-image")
                        : message.querySelector(".bubble, .message-left");
                    if (!target) target = message;

                    positionMenuNear(messageMenu, target.getBoundingClientRect(), chat.mine);
                });

                message.addEventListener("dblclick", function (event) {
                    event.preventDefault();

                    selectedMessage = chat;
                    selectedIndex = chat.id;

                    const bubble = message.querySelector(".bubble, .message-left") || message;
                    reactionPicker.style.display = "flex";

                    const rect = bubble.getBoundingClientRect();
                    const pickerWidth = reactionPicker.offsetWidth;
                    let left = rect.left + window.scrollX + (rect.width / 2) - (pickerWidth / 2);
                    let top = rect.top + window.scrollY - 55;

                    if (left < 10) left = 10;
                    if (left + pickerWidth > window.innerWidth) left = window.innerWidth - pickerWidth - 10;

                    reactionPicker.style.left = left + "px";
                    reactionPicker.style.top = top + "px";
                });

                const reactionsHTML = (chat.reactions && chat.reactions.length > 0)
                    ? `<div class="reactions-row">${chat.reactions.map(function (e) { return `<span class="reactions-badge">${e}</span>`; }).join("")}</div>`
                    : "";

                const editedHTML = chat.edited ? `<div class="edited-label">수정 됨</div>` : "";
                const readStatusHTML = (chat.mine && !isMessageRead(chat)) ? `<span class="read-status">${chat.unreadCount}</span>` : "";

                if (chat.mine) {
                    message.className = "message-right";

                    if (chat.video) {
                        message.innerHTML = `
                            ${reactionsHTML}
                            <div class="time">${readStatusHTML}${chat.time}</div>
                            <div class="image-bubble">
                                <video src="${chat.video}" class="chat-image" controls style="max-width: 250px; border-radius: 12px; display: block;"></video>
                            </div>
                        `;
                    } else if (chat.image) {
                        message.innerHTML = `
                            ${reactionsHTML}
                            <div class="time">${readStatusHTML}${chat.time}</div>
                            <div class="image-bubble">
                                <img src="${chat.image}" class="chat-image" data-image="${chat.image}">
                            </div>
                        `;
                    } else if (chat.reply) {
                        message.style.flexDirection = "column";
                        message.style.alignItems = "flex-end";
                        message.innerHTML = `
                            ${buildReplyQuoteHTML(chat.reply)}
                            ${editedHTML}
                            <div class="bubble-row">
                                <div class="time">${readStatusHTML}${chat.time}</div>
                                <div class="bubble">${highlightText(chat.text, searchQuery)}</div>
                            </div>
                            ${reactionsHTML}
                        `;
                    } else {
                        if (chat.edited) {
                            message.style.flexDirection = "column";
                            message.style.alignItems = "flex-end";
                        }
                        message.innerHTML = `
                            ${editedHTML}
                            ${reactionsHTML}
                            <div class="bubble-row">
                                <div class="time">${readStatusHTML}${chat.time}</div>
                                <div class="bubble">${highlightText(chat.text, searchQuery)}</div>
                            </div>
                        `;
                    }

              } else {
                    message.className = isGroupChat ? "message-left-container group-message" : "message-left-container";

                    const avatarHTML = isGroupChat
                        ? (chat.senderProfileImage
                            ? `<img src="${chat.senderProfileImage}" class="msg-avatar">`
                            : `<div class="msg-avatar"><i class="fa-solid fa-circle-user"></i></div>`)
                        : "";
                    const senderNameHTML = isGroupChat
                        ? `<div class="msg-sender-name">${escapeHTML(chat.senderName || "")}</div>`
                        : "";

                    let innerContent;

                    if (chat.video) {
                        innerContent = `
                            <div class="image-bubble">
                                <video src="${chat.video}" class="chat-image" controls style="max-width: 250px; border-radius: 12px; display: block;"></video>
                            </div>
                            <div class="time">${chat.time}</div>
                            ${reactionsHTML}
                        `;
                    } else if (chat.image) {
                        innerContent = `
                            <div class="image-bubble">
                                <img src="${chat.image}" class="chat-image">
                            </div>
                            <div class="time">${chat.time}</div>
                            ${reactionsHTML}
                        `;
                    } else if (chat.reply) {
                        if (!isGroupChat) {
                            message.style.flexDirection = "column";
                            message.style.alignItems = "flex-start";
                        }
                        innerContent = `
                            ${buildReplyQuoteHTML(chat.reply)}
                            <div class="bubble-row">
                                <div class="message-left">${highlightText(chat.text, searchQuery)}</div>
                                <div class="time">${chat.time}</div>
                            </div>
                            ${reactionsHTML}
                        `;
                    } else {
                        innerContent = `
                            <div class="bubble-row">
                                <div class="message-left">${highlightText(chat.text, searchQuery)}</div>
                                <div class="time">${chat.time}</div>
                            </div>
                            ${reactionsHTML}
                        `;
                    }

                    message.innerHTML = isGroupChat
                        ? `${avatarHTML}<div class="msg-content-col">${senderNameHTML}${innerContent}</div>`
                        : innerContent;
                }

                if (chat.text && !chat.image && !chat.video) appendLinkPreview(message, chat);

                const swipeIcon = document.createElement("i");
                swipeIcon.className = "fa-solid fa-reply swipe-reply-icon";
                message.appendChild(swipeIcon);

                message.addEventListener("mousedown", function (event) { startSwipe(event, message, chat); });
                message.addEventListener("touchstart", function (event) { startSwipe(event, message, chat); }, { passive: true });

                const image = message.querySelector(".chat-image");
                if (image) {
                    image.addEventListener("click", function () {
                        modalImage.src = this.dataset.image;
                        imageModal.style.display = "flex";
                    });
                }

                renderTarget.appendChild(message);
            });

            messages.replaceChildren(renderTarget);
            messages.scrollTop = messages.scrollHeight;
        }

        /* ======================================================
         * 메시지 컨텍스트 메뉴 동작 (복사/답장/취소/삭제/수정/고정)
         * ====================================================== */

        copyMessage.addEventListener("click", function (event) {
            event.stopPropagation();
            if (selectedMessage == null) return;

            closeMessageMenu();
            navigator.clipboard.writeText(selectedMessage.text);

            setTimeout(function () {
                showAlert("메시지가 복사되었습니다.", function () { focusInputSafely(); });
            }, 10);
        });

        replyButton.addEventListener("click", function (event) {
            event.stopPropagation();
            replyMessage = selectedMessage;
            replyPreview.style.display = "block";

            if (selectedMessage.image) {
                replyText.style.display = "none";
                replyImage.style.display = "block";
                replyImage.src = selectedMessage.image;
            } else {
                replyImage.style.display = "none";
                replyText.style.display = "block";
                replyText.innerText = selectedMessage.text;
            }

            closeMessageMenu();
            input.focus();
        });

        cancelReply.addEventListener("click", function () {
            replyMessage = null;
            replyPreview.style.display = "none";
            replyImage.style.display = "none";
            replyImage.src = "";
            input.focus();
        });

        cancelEdit.addEventListener("click", function () {
            editingIndex = null;
            editPreview.style.display = "none";
            input.value = "";
            button.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
            input.focus();
        });

        deleteMessage.addEventListener("click", function (event) {
            event.stopPropagation();
            closeMessageMenu();

            setTimeout(function () {
                showConfirm("메시지를 삭제 하시겠습니까?", async function (confirmDelete) {
                    if (confirmDelete) {
                        await fetch(`/api/messages/${selectedIndex}`, {
                            method:"DELETE"
                        });
                        
                        await readMessages();
                        updateFriendPreviewFromSever();
                    }
                    focusInputSafely();     
                });
            }, 10);
        });

        editMessage.addEventListener("click", function (event) {
            event.stopPropagation();
            if (selectedMessage == null) return;

            input.value = selectedMessage.text;
            editingIndex = selectedIndex;

            editPreviewText.innerText = selectedMessage.text;
            editPreview.style.display = "block";
            replyPreview.style.display = "none";

            button.innerHTML = '<i class="fa-solid fa-check"></i>';
            closeMessageMenu();
            input.focus();
        });

        pinMessageButton.addEventListener("click", async function () {
            if (selectedIndex === -1) return;
            
            await fetch(`/api/messages/${selectedIndex}/pin`, {
                method: "POST"
        });

        await readMessages();
        messageMenu.style.display = "none";
    });

        /* ======================================================
         * 사진 첨부 / 전송
         * ====================================================== */

        imageBtn.addEventListener("click", function () {
            imageInput.click();
            attachMenu.style.display = "none";
        });

        imageInput.addEventListener("change", function () {
            const files = imageInput.files;
            if (!files || files.length === 0) return;
            for (const file of files) sendImage(file);
        });

        function sendImage(file) {
            const reader = new FileReader();

            reader.onload = async function () {
                const time = formatNowTime();
                const today = todayDate();

                const response = await fetch(`/api/conversations/${currentConversationID}/messages/image`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        image: reader.result,
                        time: time,
                        date: today
                    })
                });
                const result = await response.json();
                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                await readMessages();
                updateFriendPreviewFromSever();

                imageInput.value = "";
                replyMessage = null;
                replyPreview.style.display = "none";

                setTimeout(function () { input.focus(); }, 10);
            };
            
            reader.readAsDataURL(file);
        }

        plusBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            attachMenu.style.display = (attachMenu.style.display === "block") ? "none" : "block";
        });

        closeImage.addEventListener("click", function () { imageModal.style.display = "none"; });

        imageModal.addEventListener("click", function (e) {
            if (e.target === imageModal) imageModal.style.display = "none";
        });

        downloadImage.addEventListener("click", function () {
            const a = document.createElement("a");
            a.href = modalImage.src;
            a.download = "photo.png";
            a.click();
        });

        /* ======================================================
         * 친구 목록 렌더링
         * ====================================================== */

        function readFriends() {
            friendList.innerHTML = "";

            friends.forEach(function (friend) {
                const newFriend = document.createElement("div");
                newFriend.className = friend.id === currentConversationID ? "friend active" : "friend";

                newFriend.addEventListener("click", async function () {
                    currentConversationID = friend.id;
                    updateChatHeader(friend);
                    updateBlockState();

                    await fetch(`/api/conversations/${friend.id}/read`, { method: "POST" });
                    friend.unreadCount = 0;

                    readFriends();
                    await readMessages();
                    setTimeout(function () { input.focus(); }, 10);
                });

                    newFriend.addEventListener("contextmenu", function (event) {
                        event.preventDefault();

                        showConfirm("채팅방을 삭제 하시겠습니까?", async function (confirmDelete) {
                            if(!confirmDelete) return;

                            await fetch(`/api/conversations/${friend.id}/hide`, { method: "POST" });

                            if (currentConversationID === friend.id) {
                                currentConversationID = null;
                                updateChatHeader(null);
                                messages.innerHTML = "";
                            }

                            await loadFriends();
                        });
                    });
                

                const previewHTML = escapeHTML(friend.message)
                .replace("__CAMERA__", '<i class="fa-regular fa-image"></i>')
                .replace("__VIDEO__", '<i class="fa-solid fa-circle-play"></i>');
                const timeHTML = friend.lastTime ? `<span class="friend-time">${friend.lastTime}</span>` : "";

                // 안 읽은 개수는 서버가 이미 계산해서 주는 unreadCount를 그대로 사용한다.
                const unreadHTML = (friend.unreadCount > 0 && friend.id !== currentConversationID)
                    ? `<span class="unread-badge">${friend.unreadCount}</span>`
                    : "";

                const avatarImg = friend.isGroup
                    ? (friend.groupProfieImage || friend.profileImage || "/static/default_profile.png")
                    : (friend.profileImage || "/static/default_profile.png");
                
                newFriend.innerHTML = `
                    <div class="profile">
                        <img src="${avatarImg}" alt="Profile Image">
                        <span class="status-dot online"></span>
                    </div>
                    <div style="flex:1; min-width:0;">
                        <div class="friend-header-row">
                            <div class="friend-name">${escapeHTML(friend.name)}</div>
                            ${timeHTML}
                        </div>
                        <small class="friend-preview" title="${escapeHTML(friend.message || "")}">${previewHTML}</small>
                    </div>
                    ${unreadHTML}
                `;
                friendList.appendChild(newFriend);
            });
        }

        /* ======================================================
         * 친구 추가/삭제 (우측 패널)
         * ====================================================== */

        async function sendFriendRequest(username) {
            const trimmed = username.trim();
            if (trimmed === "") return;

            const response = await fetch("/api/friend-requests", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: trimmed })
            });

            const result = await response.json();

            if (! result.success) {
                showAlert(result.error);
                return;
            }

            if (result.autoAccepted) {
                // 상대가 이미 나에게 요청을 보내둔 상태라 바로 친구가 된 경우
                await loadFriends();
                renderFriendPanelList();
            } else {
                showAlert("친구 요청을 보냈습니다.");
            }
        }

        async function loadFriendRequests() {
            const response = await fetch("/api/friend-requests");
            const result = await response.json();

            outgoingFriendRequestList.innerHTML = "";

            if(!result.outgoing || result.outgoing.length === 0) {
                outgoingFriendRequestList.innerHTML = 
                `<div class="request-empty">보낸 친구 요청이 아직 없습니다.</div>`;
            } else {
                result.outgoing.forEach(function (request) {
                    const item = document.createElement("div");
                    item.className = "friend-request-item";

                    item.innerHTML = `
                        <span>${escapeHTML(request.display_name)}</span>
                        <button class="cancel-friend-request-btn">요청 취소</button>
                    `;

                    item.querySelector(".cancel-friend-request-btn")
                        .addEventListener("click", async function () {
                            
                            const response = await fetch(
                                `/api/friend-requests/${request.id}`,
                                { method: "DELETE" }
                            );

                            const result = await response.json();

                            if (!result.success) {
                                showAlert(result.error);
                                return;
                            }

                            await loadFriendRequests();

                        });

                    outgoingFriendRequestList.appendChild(item);
                });
            }

            renderFriendRequestList(result.incoming);
        }

        function renderFriendRequestList(incoming) {
            friendRequestList.innerHTML = "";

            if(incoming.length === 0) {
                friendRequestList.innerHTML = `<div class="friend-request-empty">받은 요청이 없습니다.</div>`;
                return;
            }

            incoming.forEach(function (req) {
                const item = document.createElement("div");
                item.className = "friend-request-item";
                item.innerHTML = `
                    <span>${escapeHTML(req.display_name)}</span>
                    <span class="accept-request-icon"><i class="fa-solid fa-check"></i></span>
                    <span class="decline-request-icon"><i class="fa-solid fa-xmark"></i></span>
                `;

                item.querySelector(".accept-request-icon").addEventListener("click", async function () {
                    await fetch(`/api/friend-requests/${req.id}/respond`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json"},
                        body: JSON.stringify({ accept:true })
                    });
                    await loadFriends();
                    await loadFriendRequests();
                    renderFriendPanelList();
                });

                item.querySelector(".decline-request-icon").addEventListener("click", async function () {
                    await fetch(`/api/friend-requests/${req.id}/respond`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ accept:false })
                    });
                    await loadFriendRequests();
                });

                friendRequestList.appendChild(item);
            });
        }

        async function loadGroupMembers() {
            groupMembersList.innerHTML = "";

            try {
                const response = await fetch(`/api/conversations/${currentConversationID}/members`);
                const result = await response.json();

                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                currentGroupMembers = result.members;
                currentGroupOwnerId = result.ownerId;

                const currentGroup = getCurrentFriend();
                groupNameText.innerText = currentGroup ? currentGroup.name : "";
                renameGroupBtn.style.display = (currentGroupOwnerId === MY_USER_ID) ? "inline-block" : "none";
                groupPhotoImg.src = result.groupProfileImage || "/static/default_profile.png";
                changeGroupPhotoBtn.style.display = (currentGroupOwnerId === MY_USER_ID) ? "flex" : "none";
                removeGroupPhotoBtn.style.display = (currentGroupOwnerId === MY_USER_ID) ? "block" : "none";

                currentGroupMembers.forEach(function (member) {
                    const row = document.createElement("div");
                    row.className = "group-member-row";

                    const avatarHTML = member.profileImage
                        ? `<img src="${member.profileImage}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;">`
                        : `<div style="width:32px; height:32px; border-radius:50%; background-color:var(--profile-bg); display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fa-solid fa-circle-user" style="color:white;"></i></div>`;

                    const ownerBadgeHTML = member.id === currentGroupOwnerId
                        ? `<span style="font-size:11px; color:var(--brand-color); font-weight:600;">방장</span>`
                        : "";

                    let actionHTML;
                    if (member.id === MY_USER_ID) {
                        actionHTML = `<span style="margin-left:auto; font-size:12px; color:gray;">나</span>`;
                    } else if (currentGroupOwnerId === MY_USER_ID) {
                        // 나(로그인한 사람)가 방장일 때만 다른 사람 추방 버튼을 보여준다.
                        actionHTML = `<span class="remove-member-icon" style="margin-left:auto; cursor:pointer; color:#e05252;"><i class="fa-solid fa-user-xmark"></i></span>`;
                    } else {
                        actionHTML = "";
                    }

                    row.innerHTML = `${avatarHTML}<span>${escapeHTML(member.name)}</span>${ownerBadgeHTML}${actionHTML}`;

                    const removeIcon = row.querySelector(".remove-member-icon");
                    if (removeIcon) {
                        removeIcon.addEventListener("click", function () {
                            showConfirm(`"${member.name}"님을 내보내시겠습니까?`, async function (confirmRemove) {
                                if (!confirmRemove) return;

                                try {
                                    const res = await fetch(`/api/conversations/${currentConversationID}/members/${member.id}`, { method: "DELETE" });
                                    const removeResult = await res.json();

                                    if (!removeResult.success) {
                                        showAlert(removeResult.error);
                                        return;
                                    }

                                    await loadGroupMembers();
                                } catch (err) {
                                    showAlert("서버와 통신 중 문제가 발생했습니다.");
                                }
                            });
                        });
                    }

                    groupMembersList.appendChild(row);
                });
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        }

        groupMembersBtn.addEventListener("click", async function () {
            await loadGroupMembers();
            groupMembersOverlay.style.display = "flex";
        });

        renameGroupBtn.addEventListener("click", async function () {
            const currentGroup = getCurrentFriend();
            const newName = prompt("새 그룹 이름을 입력하세요.", currentGroup ? currentGroup.name : "");
            if (newName === null) return;              // 취소 누른 경우
            const trimmed = newName.trim();
            if (trimmed === "") return;

            try {
                const response = await fetch(`/api/conversations/${currentConversationID}/name`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name: trimmed })
                });
                const result = await response.json();

                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                chatHeader.innerText = result.name;
                groupNameText.innerText = result.name;
                await loadFriends();
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        });

        closeGroupMembersBtn.addEventListener("click", function () {
            groupMembersOverlay.style.display = "none";
        });

        groupMembersOverlay.addEventListener("click", function (event) {
            if (event.target === groupMembersOverlay) groupMembersOverlay.style.display = "none";
        });

        leaveGroupBtn.addEventListener("click", function () {
            showConfirm("정말 이 그룹에서 나가시겠습니까? 다시 들어오려면 초대를 받아야 합니다.", async function (confirmLeave) {
                if (!confirmLeave) return;

                try {
                    await fetch(`/api/conversations/${currentConversationID}/leave`, { method: "DELETE" });
                    groupMembersOverlay.style.display = "none";

                    await loadFriends();
                    currentConversationID = friends.length > 0 ? friends[0].id : null;
                    updateChatHeader(friends.length > 0 ? friends[0] : null);
                    readFriends();
                    await readMessages();
                    updateBlockState();
                } catch (err) {
                    showAlert("서버와 통신 중 문제가 발생했습니다.");
                }
            });
        });

        function renderInviteMemberList() {
            inviteMemberList.innerHTML = "";

            const memberUsernames = new Set(currentGroupMembers.map(function (m) { return m.username; }));
            const invitableFriends = friends.filter(function (friend) {
                return !friend.isGroup && !memberUsernames.has(friend.peerUsername);
            });

            if (invitableFriends.length === 0) {
                inviteMemberList.innerHTML = `<div style="padding: 10px; font-size: 13px; color: #999;">초대할 수 있는 친구가 없습니다.</div>`;
                return;
            }

            invitableFriends.forEach(function (friend) {
                const row = document.createElement("label");
                row.style.cssText = "display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer;";
                row.innerHTML = `
                    <input type="checkbox" value="${escapeHTML(friend.peerUsername)}">
                    <span>${escapeHTML(friend.name)}</span>
                `;
                inviteMemberList.appendChild(row);
            });
        }

        openInviteMemberBtn.addEventListener("click", function () {
            renderInviteMemberList();
            inviteMemberOverlay.style.display = "flex";
        });

        inviteMemberCancelBtn.addEventListener("click", function () {
            inviteMemberOverlay.style.display = "none";
        });

        inviteMemberOverlay.addEventListener("click", function (event) {
            if (event.target === inviteMemberOverlay) inviteMemberOverlay.style.display = "none";
        });

        inviteMemberConfirmBtn.addEventListener("click", async function () {
            const checkedUsernames = Array.from(inviteMemberList.querySelectorAll("input[type=checkbox]:checked"))
                .map(function (box) { return box.value; });

            if (checkedUsernames.length === 0) {
                showAlert("초대할 친구를 선택해주세요.");
                return;
            }

            try {
                const response = await fetch(`/api/conversations/${currentConversationID}/members`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ usernames: checkedUsernames })
                });
                const result = await response.json();

                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                inviteMemberOverlay.style.display = "none";
                await loadGroupMembers();
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        });

        function renderFriendPanelList() {
            friendPanelList.innerHTML = "";

            friends.filter(function (friend) { return !friend.isGroup; }).forEach(function (friend) {
                const item = document.createElement("div");
                item.className = "friend-panel-item";

                // 그룹 채팅은 상대가 여럿이라 차단 개념이 적용되지 않으므로 버튼을 두지 않는다.
                const blockIconHTML = friend.isGroup
                    ? ""
                    : (friend.blockedByMe
                        ? `<span class="unblock-friend-icon" title="차단 해제"><i class="fa-solid fa-lock-open"></i></span>`
                        : `<span class="block-friend-icon" title="차단"><i class="fa-solid fa-ban"></i></span>`);

                item.innerHTML = `
                    <span>${escapeHTML(friend.name)}</span>
                    <div style="display:flex; align-items:center; gap:12px;">
                        ${blockIconHTML}
                        <span class="delete-friend-icon"><i class="fa-solid fa-trash"></i></span>
                    </div>
                `;

                item.querySelector(".delete-friend-icon").addEventListener("click", function () {
                    showConfirm(`"${friend.name}"님을 삭제하시겠습니까?`, async function (confirmDelete) {
                        if (!confirmDelete) return;

                        await fetch(`/api/conversations/${friend.id}/leave`, { method: "DELETE"});

                        if (currentConversationID === friend.id) {
                            currentConversationID = friends.length > 0 ? friends[0].id : null;
                            updateChatHeader(friends.length > 0 ? friends[0] : null);
                            readMessages();
                        }

                        await loadFriends();
                        renderFriendPanelList();
                        updateBlockState();
                    });
                });

                const unblockIcon = item.querySelector(".unblock-friend-icon");
                if (unblockIcon) {
                    unblockIcon.addEventListener("click", function () {
                        showConfirm(`"${friend.name}"님을 차단 해제하시겠습니까?`, async function (confirmUnblock) {
                            if (!confirmUnblock) return;

                            await fetch(`/api/blocks/${friend.peerId}`, { method: "DELETE" });

                            await loadFriends();
                            renderFriendPanelList();
                            updateBlockState();
                        });
                    });
                }

                const blockIcon = item.querySelector(".block-friend-icon");
                if (blockIcon) {
                    blockIcon.addEventListener("click", function () {
                        showConfirm(`"${friend.name}"님을 차단하시겠습니까? 차단하면 서로 메시지를 보낼 수 없어요.`, async function (confirmBlock) {
                            if (!confirmBlock) return;

                            const response = await fetch("/api/blocks", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ user_id: friend.peerId })
                            });
                            const result = await response.json();
                            if (!result.success) {
                                showAlert(result.error);
                                return;
                            }

                            await loadFriends();
                            renderFriendPanelList();
                            updateBlockState();
                        });
                    });
                }

                friendPanelList.appendChild(item);
            });
        }

        function renderNewGroupMemberList() {
            newGroupMemberList.innerHTML = "";

            const oneOnOnFriends = friends.filter(function (friend) { return !friend.isGroup; });

            if (oneOnOnFriends.length === 0) {
                newGroupMemberList.innerHTML = `<div style="padding: 10px; font-size: 13px; color: #999;">함께 그룹을 만들 친구가 없습니다.</div>`;
                return;
            }

            oneOnOnFriends.forEach(function (friend) {
                const row  = document.createElement("label");
                row.style.cssText = "display: flex; align-items: center; gap: 8px; padding:8px 12px; cursor:pointer font-size: 14px;";
                row.innerHTML = `
                    <input type="checkbox" value="${escapeHTML(friend.peerUsername)}">
                    <span>${escapeHTML(friend.name)}</span>
                `;
                newGroupMemberList.appendChild(row);
            });
        }

        openNewGroupBtn.addEventListener("click", function () {
            newGroupNameInput.value = "";
            renderNewGroupMemberList();
            newGroupOverlay.style.display = "flex";
        });

        newGroupCancelBtn.addEventListener("click", function () {
            newGroupOverlay.style.display = "none";
        });

        newGroupOverlay.addEventListener("click", function (event) {
            if (event.target === newGroupOverlay) newGroupOverlay.style.display = "none";
        });

        newGroupCreateBtn.addEventListener("click", async function () {
            const name = newGroupNameInput.value.trim();
            if (!name) {
                showAlert("그룹 이름을 입력해주세요.")
                return;
            }

            const checkedUsernames = Array.from(newGroupMemberList.querySelectorAll("input[type=checkbox]:checked"))
                .map(function (box) { return box.value; });

            if(checkedUsernames.length < 2) {
                showAlert("친구를 2명 이상 선택해주세요.");
                return;
            }

            try {
                const response = await fetch("/api/conversations", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name: name, usernames: checkedUsernames })
                });
                const result = await response.json();

                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                newGroupOverlay.style.display = "none";
                await loadFriends();

                currentConversationID = result.conversationId;
                const newGroup = getCurrentFriend();
                updateChatHeader(newGroup);
                updateBlockState();
                readFriends();
                await readMessages();
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        });

        addFriendConfirmBtn.addEventListener("click", function () {
            sendFriendRequest(newFriendInput.value);
            newFriendInput.value = "";
        });

        newFriendInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                sendFriendRequest(newFriendInput.value);
                newFriendInput.value = "";
            }
        });

        friendPanelTab.addEventListener("click", function () {
            friendPanel.classList.toggle("open");
            if (friendPanel.classList.contains("open")) {
                renderFriendPanelList();
                loadFriendRequests();
            }
        });

        closeFriendPanel.addEventListener("click", function () {
            friendPanel.classList.remove("open");
        });

        /* ======================================================
         * 설정 메뉴 / 프로필 편집 (UI만 준비된 기능)
         * ====================================================== */

        sideNavSettings.addEventListener("click", function (event) {
            event.stopPropagation();
            const rect = sideNavSettings.getBoundingClientRect();
            settingsMenu.style.display = "block";
            settingsMenu.style.pointerEvents = "auto";
            settingsMenu.style.left = (rect.right + window.scrollX + 10) + "px";
            settingsMenu.style.top = (rect.top + window.scrollY) + "px";
        });

        document.addEventListener("click", function (event) {
            if (!settingsMenu.contains(event.target) && !sideNavSettings.contains(event.target)) {
                settingsMenu.style.display = "none";
                settingsMenu.style.pointerEvents = "none";
            }
        });

        logoutBtn.addEventListener("click", function () {
            settingsMenu.style.display = "none";

            showConfirm("로그아웃 하시겠습니까?", async function (confirmLogout) {
                if (!confirmLogout) return;
                await fetch("/api/logout", { method: "POST" });
                window.location.href = "/login";
            });
        });

        editProfileBtn.addEventListener("click", function () {
            pendingProfileImageData = null;
            pendingProfileImageRemoval = false;
            savedProfileImageHTML = sideNavProfilePic.innerHTML;
            profileModalPic.innerHTML = savedProfileImageHTML;
            document.querySelector("#my-profile-name").value = document.querySelector("#current-username").innerText;
            myProfileOverlay.style.display = "flex";
        });

        myProfileCancelBtn.addEventListener("click", function () {
            profileModalPic.innerHTML = savedProfileImageHTML;
            pendingProfileImageData = null;
            pendingProfileImageRemoval = false;
            myProfileOverlay.style.display = "none";
        });

        myProfileSaveBtn.addEventListener("click", async function () {
            const newName = document.querySelector("#my-profile-name").value.trim();
            if (newName === "") {
                showAlert("이름을 입력해주세요.");
                return;
            }

            try {
                if (pendingProfileImageData) {
                    const imageResponse = await fetch("/api/account/profile-image", {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ image: pendingProfileImageData })
                    });
                    const imageResult = await imageResponse.json();
                    if (!imageResult.success) {
                        showAlert(imageResult.error);
                        return;
                    }
                    const imageHTML = `<img src="${imageResult.profile_image}" style="width:100%; height:100%; border-radius:50%; object-fit:cover;">`;
                    profileModalPic.innerHTML = imageHTML;
                    sideNavProfilePic.innerHTML = imageHTML;
                } else if (pendingProfileImageRemoval) {
                    const imageResponse = await fetch("/api/account/profile-image", { method: "DELETE" });
                    const imageResult = await imageResponse.json();
                    if (!imageResult.success) {
                        showAlert(imageResult.error);
                        return;
                    }
                    const defaultHTML = `<i class="fa-solid fa-circle-user"></i>`;
                    profileModalPic.innerHTML = defaultHTML;
                    sideNavProfilePic.innerHTML = defaultHTML;
                }

                const response = await fetch("/api/account/display-name", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ display_name: newName })
                });
                const result = await response.json();
                console.log("이름 변경 결과:", result);

                if (!result.success) {
                    showAlert(result.error);
                    return;
                }

                document.querySelector("#current-username").innerText = result.display_name;
                pendingProfileImageData = null;
                pendingProfileImageRemoval = false;
                myProfileOverlay.style.display = "none";
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        });

        /* ======================================================
         * 전송 버튼 / 엔터 입력
         * ====================================================== */

        button.addEventListener("click", function () { sendMessage(); });

        input.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        });

        document.addEventListener("click", function (event) {
            if (!messageMenu.contains(event.target)) closeMessageMenu();
            if (!attachMenu.contains(event.target)) attachMenu.style.display = "none";
        });

        function closeMessageMenu() {
            messageMenu.style.display = "none";
            messageMenu.style.pointerEvents = "none";
            messageMenu.style.left = "-9999px";
            messageMenu.style.top = "-9999px";
        }

        /* ======================================================
         * 반응(이모지) 선택 팝업
         * ====================================================== */

        reactionPicker.addEventListener("click", async function (event) {
            const emojiSpan = event.target.closest("span[data-emoji]");
            if (!emojiSpan) return;
            if (selectedIndex === -1) return;
            
            await fetch(`/api/messages/${selectedIndex}/react`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ emoji: emojiSpan.dataset.emoji })
            });

            await readMessages();
            reactionPicker.style.display = "none";
        });

        document.addEventListener("click", function (event) {
            if (!reactionPicker.contains(event.target) && event.target.tagName !== "SPAN") {
                reactionPicker.style.display = "none";
            }
        });

        /* ======================================================
         * 메시지 검색 UI
         * ====================================================== */

        searchToggleBtn.addEventListener("click", function () {
            if (searchBar.style.display === "flex") {
                searchBar.style.display = "none";
                searchInput.value = "";
                performSearch("");
            } else {
                searchBar.style.display = "flex";
                searchInput.focus();
            }
        });

        searchInput.addEventListener("input", function () { performSearch(this.value.trim()); });

        searchClose.addEventListener("click", function () {
            searchBar.style.display = "none";
            searchInput.value = "";
            performSearch("");
        });

        searchNext.addEventListener("click", function () {
            if (searchMatches.length === 0) return;
            currentMatchIndex = (currentMatchIndex + 1) % searchMatches.length;
            updateSearchCount();
            scrollToMatch();
        });

        searchPrev.addEventListener("click", function () {
            if (searchMatches.length === 0) return;
            currentMatchIndex = (currentMatchIndex - 1 + searchMatches.length) % searchMatches.length;
            updateSearchCount();
            scrollToMatch();
        });

        /* ======================================================
         * 드래그 앤 드롭 사진 첨부
         * ====================================================== */

        messages.addEventListener("dragover", function (e) { e.preventDefault(); });

        messages.addEventListener("drop", function (e) {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (!file || !file.type.startsWith("image")) {
                showAlert("이미지 파일만 첨부할 수 있습니다.");
                return;
            }
            sendImage(file);
        });

        /* ======================================================
         * 사진 갤러리 모아보기
         * ====================================================== */

        function renderGallery() {
            const chatList = chats[currentConversationID] || [];
            const images = chatList.filter(function (chat) { return chat.image; });

            if (images.length === 0) {
                galleryGrid.innerHTML = `<div class="gallery-empty">아직 주고받은 사진이 없습니다.</div>`;
                return;
            }

            galleryGrid.innerHTML = images.map(function (chat) {
                return `<img src="${chat.image}" data-image="${chat.image}">`;
            }).join("");
        }

        galleryToggleBtn.addEventListener("click", function () {
            renderGallery();
            galleryOverlay.style.display = "flex";
        });

        closeGallery.addEventListener("click", function () { galleryOverlay.style.display = "none"; });

        galleryOverlay.addEventListener("click", function (event) {
            if (event.target === galleryOverlay) galleryOverlay.style.display = "none";
        });

        galleryGrid.addEventListener("click", function (event) {
            const img = event.target.closest("img[data-image]");
            if (!img) return;
            galleryOverlay.style.display = "none";
            modalImage.src = img.dataset.image;
            imageModal.style.display = "flex";
        });

        accountSettingsItem.addEventListener("click", function () {
    settingsMenu.style.display = "none";
    accountSettingsOverlay.style.display = "flex";
});

let currentUpdateVersion = "";

function updateUpdateNoticeBadge() {
    if (!currentUpdateVersion) return;
    const seenVersion = localStorage.getItem("seenUpdateVersion");
    updateNoticeBadge.style.display =
        seenVersion === currentUpdateVersion ? "none" : "inline-block";
}

function renderUpdateHistory(updates) {
    updateHistoryList.replaceChildren();
    updates.forEach(function (update) {
        const item = document.createElement("article");
        item.className = "update-history-item";

        const top = document.createElement("div");
        top.className = "update-history-top";
        const title = document.createElement("strong");
        title.textContent = "업데이트";
        const date = document.createElement("span");
        date.textContent = update.date;
        top.append(title, date);

        const list = document.createElement("ul");
        const message = document.createElement("li");
        message.textContent = update.message;
        list.append(message);
        item.append(top, list);
        updateHistoryList.append(item);
    });
}

async function loadUpdateHistory() {
    try {
        const response = await fetch("/api/updates");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error("업데이트 내역 없음");

        if (!result.updates.length) {
            currentUpdateVersion = "";
            updateNoticeBadge.style.display = "none";
            updateHistoryList.textContent = "최근 7일 내 업데이트가 없습니다.";
            return;
        }

        currentUpdateVersion = result.latest_version;
        renderUpdateHistory(result.updates);
        updateUpdateNoticeBadge();
    } catch (error) {
        updateHistoryList.textContent = "업데이트 내역을 불러오지 못했습니다.";
    }
}

notificationSettingsItem.addEventListener("click", function () {
    settingsMenu.style.display = "none";
    notificationSettingsOverlay.style.display = "flex";

    if (currentUpdateVersion) {
        localStorage.setItem("seenUpdateVersion", currentUpdateVersion);
    }
    updateUpdateNoticeBadge();
});

notificationSettingsCloseBtn.addEventListener("click", function () {
    notificationSettingsOverlay.style.display = "none";
});

supportAttachment.addEventListener("change", function () {
    const file = supportAttachment.files[0];
    if (!file) {
        supportAttachmentName.textContent = "첨부 파일 없음";
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        supportAttachment.value = "";
        supportAttachmentName.textContent = "첨부 파일 없음";
        supportInquiryResult.className = "support-inquiry-result error";
        supportInquiryResult.textContent = "첨부파일은 10MB 이하만 보낼 수 있습니다.";
        return;
    }
    supportAttachmentName.textContent = file.name;
    supportInquiryResult.textContent = "";
    supportInquiryResult.className = "support-inquiry-result";
});

supportInquiryForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = supportMessage.value.trim();
    if (message.length < 10) {
        supportInquiryResult.className = "support-inquiry-result error";
        supportInquiryResult.textContent = "문의 내용은 10자 이상 입력해주세요.";
        supportMessage.focus();
        return;
    }

    supportInquirySubmitBtn.disabled = true;
    supportInquirySubmitBtn.textContent = "전송 중...";
    supportInquiryResult.textContent = "";
    supportInquiryResult.className = "support-inquiry-result";

    try {
        const formData = new FormData();
        formData.append("message", message);
        if (supportAttachment.files[0]) formData.append("attachment", supportAttachment.files[0]);

        const response = await fetch("/api/support-inquiries", { method: "POST", body: formData });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "문의 전송에 실패했습니다.");

        supportInquiryResult.className = "support-inquiry-result success";
        supportInquiryResult.textContent = result.message;
        supportInquiryForm.reset();
        supportAttachmentName.textContent = "첨부 파일 없음";
    } catch (error) {
        supportInquiryResult.className = "support-inquiry-result error";
        supportInquiryResult.textContent = error.message || "문의 전송에 실패했습니다. 잠시 후 다시 시도해주세요.";
    } finally {
        supportInquirySubmitBtn.disabled = false;
        supportInquirySubmitBtn.textContent = "문의 전송하기";
    }
});

helpItem.addEventListener("click", function () {
    settingsMenu.style.display = "none";
    helpOverlay.style.display = "flex";
});
helpCloseBtn.addEventListener("click", function () {
    helpOverlay.style.display = "none";
});

accountSettingsCloseBtn.addEventListener("click", function () {
    accountSettingsOverlay.style.display = "none";
});

saveUsernameBtn.addEventListener("click", async function () {
    try {
        const response = await fetch("/api/account/username", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                new_username: newUsernameInput.value.trim(),
                current_password: usernameChangePassword.value
            })
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        newUsernameInput.value = "";
        usernameChangePassword.value = "";
        showAlert("아이디가 변경되었습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
});

sendEmailCodeBtn.addEventListener("click", async function () {
    const email = newEmailInput.value.trim();
    if (!email) {
        showAlert("이메일을 입력해주세요.");
        return;
    }

    try {
        const response = await fetch("/api/account/email/send-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email })
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        showAlert("인증 코드가 이메일로 전송되었습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
});

saveEmailBtn.addEventListener("click", async function () {
    try {
        const response = await fetch("/api/account/email", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: newEmailInput.value.trim(),
                code: emailCodeInput.value.trim(),
                current_password: emailChangePassword.value
            })
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        currentEmailText.innerText = result.email;
        newEmailInput.value = "";
        emailCodeInput.value = "";
        emailChangePassword.value = "";
        showAlert("이메일이 변경되었습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
});

savePasswordBtn.addEventListener("click", async function () {
    try {
        const response = await fetch("/api/account/password", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: currentPasswordInput.value,
                new_password: newPasswordInput.value
            })
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        currentPasswordInput.value = "";
        newPasswordInput.value = "";
        showAlert("비밀번호가 변경되었습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
});

deleteAccountBtn.addEventListener("click", function () {
    const password = deleteAccountPassword.value;

    showConfirm("정말로 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.", async function (confirmDelete) {
        if (!confirmDelete) return;

        try {
            const response = await fetch("/api/account", {
                method: "DELETE",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: password })
            });
            const result = await response.json();

            if (!result.success) {
                showAlert(result.error);
                return;
            }

            window.location.href = "/login";
        } catch (err) {
            showAlert("서버와 통신 중 문제가 발생했습니다.");
        }
    });
});

changeGroupPhotoBtn.addEventListener("click", function () {
    groupPhotoInput.click();
});

groupPhotoInput.addEventListener("change", function () {
    const file = groupPhotoInput.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function () {
        try {
            const response = await fetch(`/api/conversations/${currentConversationID}/photo`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: reader.result })
            });
            const result = await response.json();

            if (!result.success) {
                showAlert(result.error);
                return;
            }

            groupPhotoImg.src = result.profile_image;
        } catch (err) {
            showAlert("서버와 통신 중 문제가 발생했습니다.");
        }
    };
    reader.readAsDataURL(file);

    groupPhotoInput.value = "";
});

removeGroupPhotoBtn.addEventListener("click", function () {
    showConfirm("그룹 사진을 삭제하시겠습니까?", async function (confirmRemove) {
        if (!confirmRemove) return;
        try {
            const response = await fetch(`/api/conversations/${currentConversationID}/photo`, { method: "DELETE" });
            const result = await response.json();

            if (!result.success) {
                showAlert(result.error);
                return;
            }

            groupPhotoImg.src = "/static/default_profile.png";
        } catch (err) {
            showAlert("서버와 통신 중 문제가 발생했습니다.");
        }
    });
});

changeProfilePicBtn.addEventListener("click", function () {
    profileImageInput.click();
});

profileModalPic.addEventListener("click", function () {
    profileImageInput.click();
});

profileImageInput.addEventListener("change", function () {
    const file = profileImageInput.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function () {
        pendingProfileImageData = reader.result;
        pendingProfileImageRemoval = false;
        profileModalPic.innerHTML = `<img src="${reader.result}" style="width:100%; height:100%; border-radius:50%; object-fit:cover;">`;
        return;
        try {
            const response = await fetch("/api/account/profile-image", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: reader.result })
            });
            const result = await response.json();

            if (!result.success) {
                showAlert(result.error);
                return;
            }

            const imgHTML = `<img src="${result.profile_image}" style="width:100%; height:100%; border-radius:50%; object-fit:cover;">`;
            profileModalPic.innerHTML = imgHTML;
            sideNavProfilePic.innerHTML = imgHTML;
        } catch (err) {
            showAlert("서버와 통신 중 문제가 발생했습니다.");
        }
    };
    reader.readAsDataURL(file);

    profileImageInput.value = "";
});

removeProfilePicBtn.addEventListener("click", function () {
    showConfirm("프로필 사진을 삭제하시겠습니까?", async function (confirmRemove) {
        if (!confirmRemove) return;
        pendingProfileImageData = null;
        pendingProfileImageRemoval = true;
        profileModalPic.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
        return;

        try {
            const response = await fetch("/api/account/profile-image", { method: "DELETE" });
            const result = await response.json();

            if (!result.success) {
                showAlert(result.error);
                return;
            }

            const defaultHTML = `<i class="fa-solid fa-circle-user"></i>`;
            profileModalPic.innerHTML = defaultHTML;
            sideNavProfilePic.innerHTML = defaultHTML;
        } catch (err) {
            showAlert("서버와 통신 중 문제가 발생했습니다.");
        }
    });
});

videoBtn.addEventListener("click", function () {
    videoInput.click();
    attachMenu.style.display = "none";
});

videoInput.addEventListener("change", function () {
    const file = videoInput.files[0];
    if (!file) return;
    sendVideo(file);
    videoInput.value = "";
});

async function sendVideo(file) {
    const time = formatNowTime();
    const today = todayDate();

    const formData = new FormData();
    formData.append("video", file);
    formData.append("time", time);
    formData.append("date", today);

    try {
        const response = await fetch(`/api/conversations/${currentConversationID}/messages/video`, {
            method: "POST",
            body: formData
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        await readMessages();
        updateFriendPreviewFromSever();
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
}

        /* ======================================================
         * 메시지 좌우 스와이프로 답장
         * ====================================================== */

        let swipeStartX = 0;
        let swipeDeltaX = 0;
        let swipeTarget = null;
        let swipeChat = null;
        const SWIPE_THRESHOLD = 60;
        const SWIPE_MAX = 90;

        function getClientX(event) {
            return event.touches ? event.touches[0].clientX : event.clientX;
        }

        function startSwipe(event, messageEl, chat) {
            if (event.type === "mousedown" && event.button !== 0) return;

            swipeTarget = messageEl;
            swipeChat = chat;
            swipeStartX = getClientX(event);
            swipeDeltaX = 0;
            swipeTarget.style.transition = "none";

            document.addEventListener("mousemove", onSwipeMove);
            document.addEventListener("mouseup", endSwipe);
            document.addEventListener("touchmove", onSwipeMove, { passive: false });
            document.addEventListener("touchend", endSwipe);
        }

        function onSwipeMove(event) {
            if (!swipeTarget) return;

            const currentX = getClientX(event);
            let delta = currentX - swipeStartX;
            delta = Math.max(-SWIPE_MAX, Math.min(SWIPE_MAX, delta));
            swipeDeltaX = delta;

            if (event.type === "touchmove" && Math.abs(delta) > 10) event.preventDefault();

            swipeTarget.style.transform = `translateX(${delta}px)`;

            const icon = swipeTarget.querySelector(".swipe-reply-icon");
            if (icon) {
                const progress = Math.min(Math.abs(delta) / SWIPE_THRESHOLD, 1);
                icon.style.opacity = progress;

                if (delta > 0) {
                    icon.style.left = "-30px";
                    icon.style.right = "auto";
                } else if (delta < 0) {
                    icon.style.right = "-30px";
                    icon.style.left = "auto";
                }
            }
        }

        function endSwipe() {
            if (!swipeTarget) return;

            swipeTarget.style.transition = "transform 0.2s ease";
            swipeTarget.style.transform = "translateX(0)";

            if (Math.abs(swipeDeltaX) >= SWIPE_THRESHOLD && swipeChat) {
                replyMessage = swipeChat;
                replyPreview.style.display = "block";

                if (swipeChat.image) {
                    replyText.style.display = "none";
                    replyImage.style.display = "block";
                    replyImage.src = swipeChat.image;
                } else {
                    replyImage.style.display = "none";
                    replyText.style.display = "block";
                    replyText.innerText = swipeChat.text;
                }

                input.focus();
            }

            const icon = swipeTarget.querySelector(".swipe-reply-icon");
            if (icon) icon.style.opacity = 0;

            swipeTarget = null;
            swipeChat = null;
            swipeDeltaX = 0;

            document.removeEventListener("mousemove", onSwipeMove);
            document.removeEventListener("mouseup", endSwipe);
            document.removeEventListener("touchmove", onSwipeMove);
            document.removeEventListener("touchend", endSwipe);
        }

        const socket = io();

        // 메시지 전송/수정/삭제/고정/반응 — 대화방 내용이 바뀔 때마다 여기로 신호가 옴
        socket.on("conversation_updated", async function (data) {
            if (data.conversationId === currentConversationID) {
                // 지금 내가 보고 있는 방이면: 읽음 처리하고 대화 내용을 새로 불러온다
                await fetch(`/api/conversations/${currentConversationID}/read`, { method: "POST" });
                if (Date.now() - lastMessageRefreshAt > 250) await readMessages();
            }
            // 열려있지 않은 방이어도 미리보기/안읽음 배지는 갱신해야 하니 항상 실행
            await loadFriends();
            updateChatHeader(getCurrentFriend()); 
            readFriends();
            updateBlockState();
        });

        // 친구 요청 도착/수락/거절, 차단/차단해제 — 친구 관계가 바뀔 때마다 여기로 신호가 옴
        socket.on("friend_updated", async function () {
            await loadFriends();
            readFriends();
            updateBlockState();
            if (friendPanel.classList.contains("open")) {
                renderFriendPanelList();
                await loadFriendRequests();
            }
        });

        /* ======================================================
         * 초기 렌더링
         * ====================================================== */

        readMessages();
        loadFriends().then(updateBlockState);
        loadUpdateHistory();
