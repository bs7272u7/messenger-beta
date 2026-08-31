        /*
         * 재현님이 버튼 동작을 수정할 때 가장 먼저 보는 화면 제어 파일입니다.
         * 서버 데이터는 API가 기준이고, 이 파일의 chats/friends는 화면을 빠르게 그리기 위한 임시 상태입니다.
         * ====================================================== */
        /* ======================================================
         * 세션 만료 처리: API가 401을 주면 로그인 페이지로 보낸다.
         * ====================================================== */
        const _originalFetch = window.fetch;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        window.fetch = async function (...args) {
            const requestOptions = args[1] || {};
            const method = (requestOptions.method || (args[0] instanceof Request && args[0].method) || "GET").toUpperCase();
            if (csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
                const headers = new Headers(requestOptions.headers || (args[0] instanceof Request ? args[0].headers : undefined));
                headers.set("X-CSRF-Token", csrfToken);
                args[1] = { ...requestOptions, headers };
            }
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
        let friendDirectory = [];
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

        async function loadFriendDirectory() {
            const response = await fetch("/api/friends");
            const result = await response.json();
            friendDirectory = result.friends || [];
        }
            

        /* ======================================================
         * 저장/시간/친구 조회 헬퍼
         * ====================================================== */

        function getDisplayLocale() {
            const language = window.CloudI18n ? window.CloudI18n.getLanguage() : "ko";
            return { ko: "ko-KR", en: "en-US", zh: "zh-CN", ja: "ja-JP", es: "es-ES" }[language] || "ko-KR";
        }

        // 서버는 UTC 시각만 보관하고, 재현님을 포함한 각 사용자의 기기 시간대에서 자연스럽게 다시 표시한다.
        function formatMessageTime(chat) {
            if (!chat || !chat.sentAt) return (chat && chat.time) || "";
            return new Intl.DateTimeFormat(getDisplayLocale(), { hour: "numeric", minute: "2-digit" }).format(new Date(chat.sentAt));
        }

        function formatMessageDate(chat) {
            if (!chat || !chat.sentAt) return (chat && chat.date) || "";
            return new Intl.DateTimeFormat(getDisplayLocale(), { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(chat.sentAt));
        }

        // 시스템 메시지는 이름처럼 번역하면 안 되는 값과 안내 문구가 한 문장에 섞여 있다.
        // 저장된 원문은 유지하고, 화면에 표시할 때만 현재 언어의 문장 형태로 바꾼다.
        function localizeSystemMessage(text) {
            const original = String(text || "");
            const i18n = window.CloudI18n;
            const language = i18n ? i18n.getLanguage() : "ko";
            const themeChanged = original.match(/^(.+?)님이 (.+) 테마로 변경했습니다\.$/);
            if (themeChanged) {
                const [, name, theme] = themeChanged;
                const themeLabel = i18n ? i18n.t(theme) : theme;
                const templates = {
                    en: `${name} changed the chat theme to ${themeLabel}.`,
                    zh: `${name} 将聊天主题更改为${themeLabel}。`,
                    ja: `${name}さんがチャットテーマを${themeLabel}に変更しました。`,
                    es: `${name} cambió el tema del chat a ${themeLabel}.`
                };
                return templates[language] || original;
            }

            const memberLeft = original.match(/^(.+?)님이 나갔습니다\.$/);
            if (memberLeft) {
                const name = memberLeft[1];
                return ({ en: `${name} left the group.`, zh: `${name} 离开了群组。`, ja: `${name}さんがグループを退出しました。`, es: `${name} salió del grupo.` }[language]) || original;
            }

            const groupEnded = original.match(/^(.+?)님이 그룹 채팅을 종료했습니다\. 이전 대화는 계속 볼 수 있습니다\.$/);
            if (groupEnded) {
                const name = groupEnded[1];
                return ({ en: `${name} ended the group chat. Previous messages remain available.`, zh: `${name} 结束了群聊。仍可查看历史消息。`, ja: `${name}さんがグループチャットを終了しました。過去のメッセージは引き続き閲覧できます。`, es: `${name} cerró el chat grupal. Los mensajes anteriores seguirán disponibles.` }[language]) || original;
            }
            return i18n ? i18n.t(original) : original;
        }

        function getCurrentFriend() {
            return friends.find(function (friend) { return friend.id === currentConversationID; });
        }

        // 대화방 목록과 채팅 헤더가 같은 프로필 규칙을 쓰도록 한 곳에서 결정한다.
        function getConversationAvatar(friend) {
            if (friend.isGroup) return friend.groupProfileImage || "/static/default_profile.png";
            return friend.peerProfileImage || "/static/default_profile.png";
        }

        // 그룹은 한 명의 접속 상태를 나타낼 수 없으므로 온라인 점을 표시하지 않는다.
        function getPresenceIndicatorHTML(friend) {
            if (friend.isGroup) return "";
            const state = friend.isOnline ? "online" : "offline";
            const label = friend.isOnline ? "온라인" : "오프라인";
            return `<span class="status-dot ${state}" title="${label}" aria-label="${label}"></span>`;
        }

        function openProfileCard(friend) {
            if (!friend || friend.isGroup || !friend.peerId) return;
            profileCardAvatar.src = friend.peerProfileImage || "/static/default_profile.png";
            profileCardCover.style.backgroundImage = friend.peerCoverImage ? `url("${friend.peerCoverImage}")` : "";
            profileCardName.textContent = friend.name;
            profileCardBio.textContent = friend.peerBio || "소개글이 없습니다.";
            const i18n = window.CloudI18n;
            profileCardPresence.textContent = friend.isOnline
                ? `● ${i18n ? i18n.t("온라인") : "온라인"}`
                : `● ${i18n ? i18n.t("오프라인") : "오프라인"}`;
            profileCardTarget = { peerId: friend.peerId, name: friend.name };
            profileCardMenu.hidden = true;
            profileCardMenuBtn.setAttribute("aria-expanded", "false");
            profileCardOverlay.style.display = "flex";
        }

        function updateChatHeader(friend) {
            if (!friend) {
                chatHeader.innerText = "";
                chatHeaderAvatar.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
                chatHeaderAvatar.onclick = null;
                chatHeaderMemberCount.style.display = "none";
                if (chatPanel) chatPanel.classList.add("no-conversation");
                applyChatTheme(null);
                desktopInfoName.innerText = window.CloudI18n ? window.CloudI18n.t("대화를 선택하세요") : "대화를 선택하세요";
                desktopInfoStatus.innerText = "";
                desktopConversationActions.style.display = "none";
                return;
            }

            if (chatPanel) chatPanel.classList.remove("no-conversation");
            applyChatTheme(friend);
            chatHeader.innerText = friend.name;
            desktopInfoName.innerText = friend.name;
            const i18n = window.CloudI18n;
            desktopInfoStatus.innerText = friend.isGroup
                ? `${friend.memberCount || 0}명이 참여 중인 그룹 채팅입니다.`
                : (friend.isOnline ? (i18n ? i18n.t("현재 온라인입니다.") : "현재 온라인입니다.") : (i18n ? i18n.t("현재 오프라인입니다.") : "현재 오프라인입니다."));
            desktopConversationActions.style.display = "grid";
            desktopConversationPin.innerHTML = `<i class="fa-solid fa-thumbtack"></i> ${friend.isPinned ? "고정 해제" : "고정"}`;
            desktopConversationMute.innerHTML = `<i class="fa-solid fa-bell${friend.isMuted ? "" : "-slash"}"></i> ${friend.isMuted ? "알림 켜기" : "알림 끄기"}`;

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
                chatHeaderAvatar.onclick = function () { openProfileCard(friend); };
                chatHeaderMemberCount.style.display = "none";
            }
        }

        /* i18n은 각 요소의 최초 문구를 data-i18n-* 에 보관했다가 다시 적용한다.
         * 그래서 문구를 바꿀 때 기준값도 같이 갱신하지 않으면,
         * 다음 번역 시점에 원래 문구로 되돌아간다. */
        function setBannerMessage(koreanText) {
            const label = blockBanner.querySelector("span");
            label.dataset.i18nText = koreanText;
            label.textContent = window.CloudI18n ? window.CloudI18n.t(koreanText) : koreanText;
        }

        function setInputPlaceholder(koreanText) {
            input.dataset.i18nPlaceholder = koreanText;
            input.placeholder = window.CloudI18n ? window.CloudI18n.t(koreanText) : koreanText;
        }

        /* 현재 열려있는 대화방이 차단 상태(내가 차단했거나, 상대가 나를 차단)면
         * 입력창/전송/첨부 버튼을 잠그고 안내 배너를 띄운다. */
        function updateBlockState() {
            const friend = getCurrentFriend();
            const disabledGroup = !!(friend && friend.isGroup && friend.isDisabled);
            const blockedDirectChat = !!(friend && !friend.isGroup && (friend.blockedByMe || friend.blockedMe));
            const blocked = disabledGroup || blockedDirectChat;

            blockBanner.style.display = blocked ? "flex" : "none";
            if (blocked) {
                setBannerMessage(disabledGroup
                    ? "종료된 그룹 채팅방입니다. 이전 대화만 확인할 수 있습니다."
                    : "차단된 사용자와는 메시지를 주고받을 수 없습니다.");
            }
            input.disabled = blocked;
            button.disabled = blocked;
            plusBtn.disabled = blocked;
            setInputPlaceholder(friend && friend.isDisabled
                ? "종료된 그룹 채팅입니다. 이전 대화만 볼 수 있습니다."
                : (blocked ? "차단된 사용자입니다" : "메시지를 입력하세요"));
        }

        // 메시지 전송 직후에는 서버 재조회 전에도 목록 미리보기를 즉시 갱신한다.
        // 나중에 미리보기 문구를 바꾸고 싶다면 getPreviewText()만 수정하면 된다.
        function updateFriendPreviewFromServer() {
            const friend = getCurrentFriend();
            const chatList = chats[currentConversationID] || [];
            if (friend) {
                friend.message = getPreviewText(chatList);
                friend.lastTime = getPreviewTime(chatList);
                friend.lastSentAt = chatList.length ? chatList[chatList.length - 1].sentAt : null;
                readFriends();
            }
        }

        function getPreviewText(chatList) {
            if (!chatList || chatList.length === 0) return "";
            const last = chatList[chatList.length - 1];
            if (last.audio) return "음성 메시지";
            if (last.filePath) return "파일";
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

        function formatFileSize(bytes) {
            const size = Number(bytes) || 0;
            if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))}KB`;
            return `${(size / (1024 * 1024)).toFixed(1)}MB`;
        }

        function buildFileMessageHTML(chat) {
            return `<a class="chat-file-card" href="${escapeHTML(chat.filePath)}" target="_blank" rel="noopener" download>
                <i class="fa-solid fa-file-arrow-down"></i><span><strong>${escapeHTML(chat.fileName || "첨부 파일")}</strong><small>${formatFileSize(chat.fileSize)}</small></span>
            </a>`;
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

        /* # 기준 요소(rect) 옆에 메뉴를 띄우고, 화면 밖으로 나가지 않게 좌표를 보정한다.
         * 파일 카드와 음성 컨트롤도 같은 화면 좌표계에서 계산해야 메뉴가 입력창 쪽으로 밀리지 않는다. */
        function positionMenuNear(menuEl, rect, preferLeft) {
            const menuWidth = menuEl.offsetWidth;
            const menuHeight = menuEl.offsetHeight;

            let left = preferLeft
                ? rect.left - menuWidth - 10
                : rect.right + 10;
            let top = rect.top;

            if (left < 10) left = rect.right + 10;
            if (left + menuWidth > window.innerWidth) left = rect.left - menuWidth - 10;
            if (left < 10) left = 10;

            if (top + menuHeight > window.innerHeight) top = rect.bottom - menuHeight;
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
        const fileBtn = document.querySelector("#file-btn");
        const fileInput = document.querySelector("#file-input");
        const audioBtn = document.querySelector("#audio-btn");
        const audioInput = document.querySelector("#audio-input");
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
        const forwardMessageButton = document.querySelector("#forward-message");
        const reportMessageButton = document.querySelector("#report-message");
        const forwardMessageOverlay = document.querySelector("#forward-message-overlay");
        const forwardMessageClose = document.querySelector("#forward-message-close");
        const forwardConversationSelect = document.querySelector("#forward-conversation-select");
        const forwardMessageSubmit = document.querySelector("#forward-message-submit");
        const reportMessageOverlay = document.querySelector("#report-message-overlay");
        const reportMessageClose = document.querySelector("#report-message-close");
        const reportReasonSelect = document.querySelector("#report-reason-select");
        const reportDetail = document.querySelector("#report-detail");
        const reportModalTitle = document.querySelector("#report-modal-title");
        const reportMessageSubmit = document.querySelector("#report-message-submit");
        const friendPanelTab = document.querySelector("#friend-panel-tab");
        const friendPanel = document.querySelector("#friend-panel");
        const closeFriendPanelBtn = document.querySelector("#close-friend-panel");
        const newFriendInput = document.querySelector("#new-friend-input");
        const addFriendConfirmBtn = document.querySelector("#add-friend-confirm-btn");
        const friendSearchInput = document.querySelector("#friend-search-input");
        const friendSearchBtn = document.querySelector("#friend-search-btn");
        const friendSearchResult = document.querySelector("#friend-search-result");
        const friendRequestList = document.querySelector("#friend-request-list");
        const friendInboxBtn = document.querySelector("#friend-inbox-btn");
        const friendInboxOverlay = document.querySelector("#friend-inbox-overlay");
        const friendInboxCloseBtn = document.querySelector("#friend-inbox-close-btn");
        const friendInboxTabs = document.querySelectorAll("[data-inbox-tab]");
        const incomingRequestCount = document.querySelector("#incoming-request-count");
        const outgoingRequestCount = document.querySelector("#outgoing-request-count");
        const friendInboxBadge = document.querySelector("#friend-inbox-badge");
        const friendPanelList = document.querySelector("#friend-panel-list");
        const openNewGroupBtn = document.querySelector("#open-new-group-btn");
        const newGroupOverlay = document.querySelector("#new-group-overlay");
        const newGroupNameInput = document.querySelector("#new-group-name-input");
        const newGroupMemberList = document.querySelector("#new-group-member-list");
        const newGroupCancelBtn = document.querySelector("#new-group-cancel-btn");
        const newGroupCreateBtn = document.querySelector("#new-group-create-btn");
        const sideNavSettings = document.querySelector(".side-nav-settings");
        const settingsMenu = document.querySelector("#settings-menu");
        const mobileSheetBackdrop = document.querySelector("#mobile-sheet-backdrop");
        const logoutBtn = document.querySelector("#logout-btn");
        const editProfileBtn = document.querySelector("#edit-profile-btn");
        const myProfileOverlay = document.querySelector("#my-profile-overlay");
        const myProfileCloseBtn = document.querySelector("#my-profile-close-btn");
        const accountSettingsItem = document.querySelector("#account-settings-item");
        const notificationSettingsItem = document.querySelector("#notification-settings-item");
        const updateNoticeBadge = document.querySelector("#update-notice-badge");
        const updateHistoryList = document.querySelector("#update-history-list");
        const previousUpdatesBtn = document.querySelector("#previous-updates-btn");
        const previousUpdatesOverlay = document.querySelector("#previous-updates-overlay");
        const previousUpdatesCloseBtn = document.querySelector("#previous-updates-close-btn");
        const previousUpdatesList = document.querySelector("#previous-updates-list");
        const notificationSettingsOverlay = document.querySelector("#notification-settings-overlay");
        const notificationSettingsCloseBtn = document.querySelector("#notification-settings-close-btn");
        const browserNotificationToggle = document.querySelector("#browser-notification-toggle");
        const helpItem = document.querySelector("#help-item");
        const helpOverlay = document.querySelector("#help-overlay");
        const helpCloseBtn = document.querySelector("#help-close-btn");
        const reviewsItem = document.querySelector("#reviews-item");
        const reviewsOverlay = document.querySelector("#reviews-overlay");
        const reviewsCloseBtn = document.querySelector("#reviews-close-btn");
        const publicNoticeList = document.querySelector("#public-notice-list");
        const helpFindUsernameEmail = document.querySelector("#help-find-username-email");
        const helpFindUsernameBtn = document.querySelector("#help-find-username-btn");
        const helpFindUsernameResult = document.querySelector("#help-find-username-result");
        const helpResetEmail = document.querySelector("#help-reset-email");
        const helpResetCodeBtn = document.querySelector("#help-reset-code-btn");
        const helpResetFields = document.querySelector("#help-reset-fields");
        const helpResetCode = document.querySelector("#help-reset-code");
        const helpResetVerifyBtn = document.querySelector("#help-reset-verify-btn");
        const helpResetCodeTimer = document.querySelector("#help-reset-code-timer");
        const helpResetVerificationStatus = document.querySelector("#help-reset-verification-status");
        const helpResetNewPassword = document.querySelector("#help-reset-new-password");
        const helpResetSubmitBtn = document.querySelector("#help-reset-submit-btn");
        const helpResetResult = document.querySelector("#help-reset-result");
        const supportInquiryForm = document.querySelector("#support-inquiry-form");
        const supportMessage = document.querySelector("#support-message");
        const supportAttachment = document.querySelector("#support-attachment");
        const supportAttachmentName = document.querySelector("#support-attachment-name");
        const supportInquiryResult = document.querySelector("#support-inquiry-result");
        const supportInquirySubmitBtn = document.querySelector("#support-inquiry-submit-btn");
        const supportInquiryHistory = document.querySelector("#support-inquiry-history");
        const moderationWarningOverlay = document.querySelector("#moderation-warning-overlay");
        const moderationWarningReason = document.querySelector("#moderation-warning-reason");
        const moderationWarningDate = document.querySelector("#moderation-warning-date");
        const moderationWarningAcknowledge = document.querySelector("#moderation-warning-acknowledge");
        const moderationWarningHistory = document.querySelector("#moderation-warning-history");
        const reviewRating = document.querySelector("#review-rating");
        const reviewContent = document.querySelector("#review-content");
        const reviewSubmitBtn = document.querySelector("#review-submit-btn");
        const reviewDeleteBtn = document.querySelector("#review-delete-btn");
        const reviewComposeHint = document.querySelector("#review-compose-hint");
        const reviewList = document.querySelector("#review-list");
        const accountSettingsOverlay = document.querySelector("#account-settings-overlay");
        const accountSettingsCloseBtn = document.querySelector("#account-settings-close-btn");
        const newUsernameInput = document.querySelector("#new-username-input");
        const usernameChangePassword = document.querySelector("#username-change-password");
        const saveUsernameBtn = document.querySelector("#save-username-btn");
        const currentPasswordInput = document.querySelector("#current-password-input");
        const newPasswordInput = document.querySelector("#new-password-input");
        const newPasswordConfirmationInput = document.querySelector("#new-password-confirmation-input");
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
        const disableGroupBtn = document.querySelector("#disable-group-btn");
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
        const mobileBackBtn = document.querySelector("#mobile-back-btn");
        const chatThemeBtn = document.querySelector("#chat-theme-btn");
        const chatThemeOverlay = document.querySelector("#chat-theme-overlay");
        const chatThemeCloseBtn = document.querySelector("#chat-theme-close-btn");
        const chatThemeOptions = document.querySelectorAll(".chat-theme-option");
        const chatThemeCategories = document.querySelectorAll(".chat-theme-category");
        const chatThemePanels = document.querySelectorAll(".chat-theme-panel");
        const mobileChatMoreBtn = document.querySelector("#mobile-chat-more-btn");
        const mobileChatActionsSheet = document.querySelector("#mobile-chat-actions-sheet");
        const mobileChatNavBtn = document.querySelector("#mobile-chat-nav-btn");
        const mobileFriendsNavBtn = document.querySelector("#mobile-friends-nav-btn");
        const mobileProfileNavBtn = document.querySelector("#mobile-profile-nav-btn");
        const mobileSettingsNavBtn = document.querySelector("#mobile-settings-nav-btn");
        const chatHeaderAvatar = document.querySelector("#chat-header-avatar");
        const chatHeaderMemberCount = document.querySelector("#chat-header-member-count");
        const blockBanner = document.querySelector("#block-banner");
        const conversationSummary = document.querySelector("#conversation-summary");
        const desktopInfoName = document.querySelector("#desktop-info-name");
        const desktopInfoStatus = document.querySelector("#desktop-info-status");
        const desktopConversationActions = document.querySelector("#desktop-conversation-actions");
        const desktopConversationPin = document.querySelector("#desktop-conversation-pin");
        const desktopConversationMute = document.querySelector("#desktop-conversation-mute");
        const profileCardOverlay = document.querySelector("#profile-card-overlay");
        const profileCardClose = document.querySelector("#profile-card-close");
        const profileCardCover = document.querySelector("#profile-card-cover");
        const profileCardAvatar = document.querySelector("#profile-card-avatar");
        const profileCardName = document.querySelector("#profile-card-name");
        const profileCardBio = document.querySelector("#profile-card-bio");
        const profileCardPresence = document.querySelector("#profile-card-presence");
        const profileCardMenuBtn = document.querySelector("#profile-card-menu-btn");
        const profileCardMenu = document.querySelector("#profile-card-menu");
        const profileCardReportItem = document.querySelector("#profile-card-report");
        const profileCardBlockItem = document.querySelector("#profile-card-block");
        let profileCardTarget = null;
        let reportTarget = null;
        const myProfileBio = document.querySelector("#my-profile-bio");
        const myProfileVisibility = document.querySelector("#my-profile-visibility");
        const coverImageInput = document.querySelector("#cover-image-input");
        const removeCoverImageBtn = document.querySelector("#remove-cover-image-btn");
        const profileCoverPreview = document.querySelector("#profile-cover-preview");

        // 모바일은 한 화면에 목록과 대화창을 함께 두지 않는다.
        // PC에서는 이 클래스가 CSS에 영향을 주지 않아 기존 레이아웃을 그대로 유지한다.
        function openMobileChat() {
            if (window.matchMedia("(max-width: 767px)").matches) {
                document.body.classList.add("mobile-chat-open");
            }
        }

        function closeMobileChat() {
            document.body.classList.remove("mobile-chat-open");
            mobileChatActionsSheet.classList.remove("open");
        }

        function applyChatTheme(friend) {
            chatPanel.classList.remove("chat-theme-heart", "chat-theme-teddy", "chat-theme-glass", "chat-theme-aurora", "chat-theme-mono", "chat-theme-spring", "chat-theme-summer", "chat-theme-autumn", "chat-theme-winter", "chat-theme-christmas", "chat-theme-halloween");
            const theme = friend && friend.chatTheme ? friend.chatTheme : "default";
            if (theme !== "default") chatPanel.classList.add(`chat-theme-${theme}`);
            chatThemeOptions.forEach(function (option) {
                option.classList.toggle("selected", option.dataset.theme === theme);
            });
        }

        function getThemeCategory(theme) {
            if (["spring", "summer", "autumn", "winter"].includes(theme)) return "season";
            if (["christmas", "halloween"].includes(theme)) return "event";
            return "basic";
        }

        function showThemeCategory(category) {
            chatThemeCategories.forEach(function (button) {
                const isActive = button.dataset.themeCategory === category;
                button.classList.toggle("active", isActive);
                button.setAttribute("aria-selected", String(isActive));
            });
            chatThemePanels.forEach(function (panel) {
                const isActive = panel.dataset.themePanel === category;
                panel.classList.toggle("active", isActive);
                panel.hidden = !isActive;
            });
        }

        function updateSeasonalThemeRecommendations() {
            const today = new Date();
            const month = today.getMonth() + 1;
            const day = today.getDate();
            const christmasSeason = month === 12 || (month === 1 && day <= 6);
            const halloweenSeason = month === 10 && day >= 15 && day <= 31;
            const currentSeasonTheme = month >= 3 && month <= 5 ? "spring"
                : month >= 6 && month <= 8 ? "summer"
                : month >= 9 && month <= 11 ? "autumn" : "winter";
            chatThemeOptions.forEach(function (option) {
                const isRecommended = (option.dataset.theme === "christmas" && christmasSeason)
                    || (option.dataset.theme === "halloween" && halloweenSeason)
                    || option.dataset.theme === currentSeasonTheme;
                option.classList.toggle("season-recommended", isRecommended);
            });
        }

        updateSeasonalThemeRecommendations();

        function closeMobileChatActions() {
            mobileChatActionsSheet.classList.remove("open");
            mobileChatActionsSheet.setAttribute("aria-hidden", "true");
        }

        function isMobileViewport() {
            return window.matchMedia("(max-width: 767px)").matches;
        }

        function setMobileNavActive(activeButton) {
            [mobileChatNavBtn, mobileFriendsNavBtn, mobileProfileNavBtn, mobileSettingsNavBtn]
                .forEach(function (button) {
                    button.classList.toggle("active", button === activeButton);
                });
        }

        function openFriendPanel() {
            friendPanel.classList.add("open");
            if (isMobileViewport()) document.body.classList.add("mobile-friends-open");
            renderFriendPanelList();
            loadFriendRequests();
        }

        function closeFriendPanel() {
            friendPanel.classList.remove("open");
            document.body.classList.remove("mobile-friends-open");
        }

        async function openFriendInbox() {
            closeFriendPanel();
            await loadFriendRequests();
            friendInboxOverlay.style.display = "flex";
        }

        function closeFriendInbox() {
            friendInboxOverlay.style.display = "none";
        }

        function closeSettingsMenu() {
            settingsMenu.style.display = "none";
            settingsMenu.style.pointerEvents = "none";
            document.body.classList.remove("mobile-settings-open");
            if (officeComfortItem) {
                // 설정 메뉴를 닫으면 펼쳐 둔 편하게 보기 항목도 함께 접는다.
                officeComfortItem.open = false;
            }
        }

        function openSettingsMenu(anchor) {
            settingsMenu.style.display = "block";
            settingsMenu.style.pointerEvents = "auto";
            if (isMobileViewport()) {
                document.body.classList.add("mobile-settings-open");
                return;
            }

            const rect = anchor.getBoundingClientRect();
            const preferredLeft = rect.right + window.scrollX + 10;
            const maxLeft = window.scrollX + window.innerWidth - settingsMenu.offsetWidth - 10;
            settingsMenu.style.left = Math.max(10, Math.min(preferredLeft, maxLeft)) + "px";
            settingsMenu.style.top = (rect.top + window.scrollY) + "px";
        }

        const modalOverlay = document.querySelector("#modal-overlay");
        const modalMessage = document.querySelector("#modal-message");
        const modalCancelBtn = document.querySelector("#modal-cancel-btn");
        const modalConfirmBtn = document.querySelector("#modal-confirm-btn");

        const themeToggleItem = document.querySelector("#theme-toggle-item");
        const themeToggleIcon = document.querySelector("#theme-toggle-icon");
        const themeToggleLabel = document.querySelector("#theme-toggle-label");
        const officeModeItem = document.querySelector("#office-mode-item");
        const officeModeIcon = document.querySelector("#office-mode-icon");
        const officeModeLabel = document.querySelector("#office-mode-label");
        const officeComfortItem = document.querySelector("#office-comfort-item");
        const officeContrastSelect = document.querySelector("#office-contrast-select");
        const officeTextSizeSelect = document.querySelector("#office-text-size-select");
        const officeDensitySelect = document.querySelector("#office-density-select");
        const officeReduceMotion = document.querySelector("#office-reduce-motion");
        const appThemeSelect = document.querySelector("#app-theme-select");
        const languageSelect = document.querySelector("#language-select");
        const languageSettingCurrent = document.querySelector("#language-setting-current");
        const deleteAccountPassword = document.querySelector("#delete-account-password");
        const deleteAccountBtn = document.querySelector("#delete-account-btn");
        const profileImageInput = document.querySelector("#profile-image-input");
        const changeProfilePicBtn = document.querySelector("#change-profile-pic-btn");
        const removeProfilePicBtn = document.querySelector("#remove-profile-pic-btn");
        const profileModalPic = document.querySelector("#profile-modal-pic");
        const sideNavProfilePic = document.querySelector("#side-nav-profile-pic");
        const imageCropOverlay = document.querySelector("#image-crop-overlay");
        const imageCropTitle = document.querySelector("#image-crop-title");
        const imageCropCanvas = document.querySelector("#image-crop-canvas");
        const imageCropZoom = document.querySelector("#image-crop-zoom");
        const imageCropCloseBtn = document.querySelector("#image-crop-close-btn");
        const imageCropCancelBtn = document.querySelector("#image-crop-cancel-btn");
        const imageCropApplyBtn = document.querySelector("#image-crop-apply-btn");
        const videoBtn = document.querySelector("#video-btn");
        const videoInput = document.querySelector("#video-input");
        const newEmailInput = document.querySelector("#new-email-input");
        const sendEmailCodeBtn = document.querySelector("#send-email-code-btn");
        const emailCodeInput = document.querySelector("#email-code-input");
        const verifyEmailCodeBtn = document.querySelector("#verify-email-code-btn");
        const emailCodeTimer = document.querySelector("#email-code-timer");
        const emailCodeStatus = document.querySelector("#email-code-status");
        const emailChangePassword = document.querySelector("#email-change-password");
        const saveEmailBtn = document.querySelector("#save-email-btn");
        const currentEmailText = document.querySelector("#current-email-text");
        const outgoingFriendRequestList = document.querySelector(
            "#outgoing-friend-request-list"
        );
        let accountEmailCodeSent = false;
        let accountEmailVerified = false;
        let helpResetCodeSent = false;
        let helpResetVerified = false;

        /* ======================================================
         * 다크모드
         * ====================================================== */

        const savedTheme = localStorage.getItem("theme");
        if (savedTheme === "dark") {
            document.body.classList.add("dark-mode");
            themeToggleIcon.className = "fa-solid fa-sun";
            themeToggleLabel.innerText = window.CloudI18n ? window.CloudI18n.t("라이트 모드") : "라이트 모드";
        }

        themeToggleItem.addEventListener("click", function (event) {
            event.stopPropagation();
            if (document.body.classList.contains("office-mode")) {
                showToast("오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.");
                return;
            }
            closeSettingsMenu();
            document.body.classList.toggle("dark-mode");

            if (document.body.classList.contains("dark-mode")) {
                localStorage.setItem("theme", "dark");
                themeToggleIcon.className = "fa-solid fa-sun";
                themeToggleLabel.innerText = window.CloudI18n ? window.CloudI18n.t("라이트 모드") : "라이트 모드";
            } else {
                localStorage.setItem("theme", "light");
                themeToggleIcon.className = "fa-solid fa-moon";
                themeToggleLabel.innerText = window.CloudI18n ? window.CloudI18n.t("다크 모드") : "다크 모드";
            }
        });

        // 오피스 모드는 기능을 바꾸지 않고, 오래 보는 업무용 시각 밀도만 차분하게 조절한다.
        function getOfficeComfortSettings() {
            return {
                contrast: localStorage.getItem("officeContrast") || "comfort",
                textSize: localStorage.getItem("officeTextSize") || "medium",
                density: localStorage.getItem("officeDensity") || "comfortable",
                reduceMotion: localStorage.getItem("officeReduceMotion") === "true"
                    || (localStorage.getItem("officeReduceMotion") === null && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
            };
        }

        function applyOfficeComfortSettings() {
            const settings = getOfficeComfortSettings();
            ["comfort", "standard", "high"].forEach(value => document.body.classList.toggle(`office-contrast-${value}`, settings.contrast === value));
            ["small", "medium", "large"].forEach(value => document.body.classList.toggle(`office-text-${value}`, settings.textSize === value));
            ["comfortable", "normal", "compact"].forEach(value => document.body.classList.toggle(`office-density-${value}`, settings.density === value));
            document.body.classList.toggle("office-reduce-motion", settings.reduceMotion);
            officeContrastSelect.value = settings.contrast;
            officeTextSizeSelect.value = settings.textSize;
            officeDensitySelect.value = settings.density;
            officeReduceMotion.checked = settings.reduceMotion;
        }

        function syncOfficeComfortVisibility() {
            // 편하게 보기는 오피스 모드와 독립적으로 언제든 열 수 있다.
            officeComfortItem.hidden = false;
        }

        /* ======================================================
           Liquid Glass 테마
           굴절은 요소 뒤(backdrop)에만 걸리고 요소 안의 내용은 건드리지 않는다.
           그래서 패널에 강한 굴절을 줘도 안쪽 글자는 그대로 읽힌다.
           반대로 말풍선은 수가 많고 대화할 때마다 새로 생성되므로 대상에서 뺀다.
           ====================================================== */
        // 맵 생성은 1회성이지만 backdrop-filter 합성은 뒤 내용이 바뀔 때마다 다시 돈다.
        // 큰 면적에 SVG 굴절을 걸면 그 비용이 프레임을 잡아먹으므로,
        // 굴절은 중간 크기 이하 표면에만 걸고 큰 패널은 CSS 유리(blur+saturate)만 쓴다.
        const LG_MAX_AREA = 320000;
        const LG_MAX_SIDE = 1600;
        const LG_MAX_INSTANCES = 10;
        const LG_PANEL = { scale: -180, chroma: 8, blur: 2, saturate: 1.6 };
        const LG_BAR = { scale: -140, chroma: 6, blur: 2, saturate: 1.6 };
        const LG_POPOVER = { scale: -112, chroma: 6, blur: 3, saturate: 1.5 };
        const LG_TARGETS = [
            { selector: ".friend-list", options: LG_PANEL },
            { selector: "#desktop-chat-info", options: LG_PANEL },
            // .chat은 90만 픽셀이라 굴절을 걸면 합성 비용이 커진다. CSS 유리만 적용한다.
            { selector: ".chat-header", options: LG_BAR },
            { selector: ".input-area", options: LG_BAR },
            { selector: "#friend-panel", options: LG_POPOVER },
            { selector: "#settings-menu", options: LG_POPOVER },
            { selector: "#attach-menu", options: LG_POPOVER },
            { selector: "#message-menu", options: LG_POPOVER },
            { selector: "#mobile-chat-actions-sheet", options: LG_POPOVER },
            // 모달은 오버레이의 display가 바뀌므로 유리는 안쪽 상자에 건다.
            { selector: ".modal-overlay .modal", options: LG_POPOVER },
            { selector: ".modal-overlay .settings-modal", options: LG_POPOVER },
            { selector: ".modal-overlay .chat-theme-modal", options: LG_POPOVER },
            { selector: ".modal-overlay .friend-inbox-modal", options: LG_POPOVER },
        ];
        // 표시 상태가 바뀌는 요소들. 이들의 변화를 보고 대상 목록을 다시 계산한다.
        const LG_WATCH_SELECTORS = [
            ".modal-overlay", "#settings-menu", "#attach-menu",
            "#message-menu", "#friend-panel", "#mobile-chat-actions-sheet",
        ];
        // backdrop-filter는 position:fixed 자손의 컨테이닝 블록을 만든다.
        // 유리 패널 안에 있는 고정 팝오버는 뷰포트가 아니라 패널 기준으로 배치돼
        // 화면 밖으로 밀리거나 패널의 overflow에 잘린다. body 직속으로 옮겨 좌표를 되찾는다.
        // position:absolute 요소는 여기 넣으면 안 된다. 기준점이 원래 부모라서
        // 옮기는 순간 엉뚱한 곳으로 날아간다(#attach-menu가 그런 경우다).
        const LG_REPARENT = ["#message-menu", "#friend-panel", "#mobile-chat-actions-sheet"];

        function lgReparentFixedPopovers() {
            LG_REPARENT.forEach(selector => {
                const element = document.querySelector(selector);
                if (element && element.parentElement !== document.body) {
                    document.body.appendChild(element);
                }
            });
        }

        const lgInstances = new Map();
        let lgObserver = null;
        let lgTimer = null;

        function lgEnabled() {
            // 스크립트를 불러오지 못해도 앱은 그대로 동작해야 한다.
            if (typeof window.liquidGlass !== "function") return false;
            if (!document.body.classList.contains("theme-liquid-glass")) return false;
            // 오피스 모드와 고대비 설정에서는 가독성이 우선이므로 굴절을 끈다.
            if (document.body.classList.contains("office-mode")) return false;
            if (document.body.classList.contains("office-contrast-high")) return false;
            if (window.matchMedia("(prefers-reduced-transparency: reduce)").matches) return false;
            if ((navigator.hardwareConcurrency || 8) <= 4) return false;
            return true;
        }

        function lgAttach(element, options) {
            if (!element || lgInstances.has(element)) return;
            if (lgInstances.size >= LG_MAX_INSTANCES) return;
            const width = element.offsetWidth;
            const height = element.offsetHeight;
            if (!width || !height) return;
            if (width * height > LG_MAX_AREA) return;
            if (width > LG_MAX_SIDE || height > LG_MAX_SIDE) return;
            try {
                lgInstances.set(element, window.liquidGlass(element, options));
            } catch (error) {
                console.warn("리퀴드 글래스를 적용하지 못했습니다.", error);
            }
        }

        function lgDetach(element) {
            const instance = lgInstances.get(element);
            if (!instance) return;
            instance.destroy();
            lgInstances.delete(element);
        }

        function lgDetachAll() {
            lgInstances.forEach(instance => instance.destroy());
            lgInstances.clear();
        }

        function lgSync() {
            if (!lgEnabled()) {
                lgDetachAll();
                return;
            }
            LG_TARGETS.forEach(({ selector, options }) => {
                document.querySelectorAll(selector).forEach(element => {
                    const visible = element.offsetWidth > 0 && element.offsetHeight > 0;
                    if (visible) lgAttach(element, options);
                    else lgDetach(element);
                });
            });
        }

        function lgScheduleSync(delay) {
            clearTimeout(lgTimer);
            lgTimer = setTimeout(lgSync, delay);
        }

        function lgWatch() {
            if (lgObserver) return;
            // 메뉴와 모달은 열릴 때 비로소 크기가 생기므로 표시 상태 변화를 지켜본다.
            lgObserver = new MutationObserver(() => lgScheduleSync(60));
            LG_WATCH_SELECTORS.forEach(selector => {
                document.querySelectorAll(selector).forEach(element => {
                    lgObserver.observe(element, {
                        attributes: true,
                        attributeFilter: ["style", "class", "hidden"],
                    });
                });
            });
            window.addEventListener("resize", () => lgScheduleSync(200), { passive: true });
        }

        function getAppTheme() {
            return localStorage.getItem("appTheme") || "liquid-glass";
        }

        function applyAppTheme() {
            const theme = getAppTheme();
            const useGlass = theme === "liquid-glass";
            document.body.classList.toggle("theme-liquid-glass", useGlass);
            if (appThemeSelect) appThemeSelect.value = theme;
            // 끌 때는 즉시 걷어내고, 켤 때는 맵 생성이 수십 ms 걸리므로
            // 첫 페인트를 막지 않도록 한가할 때로 미룬다.
            if (!useGlass) {
                lgDetachAll();
                return;
            }
            if (window.requestIdleCallback) window.requestIdleCallback(() => lgSync(), { timeout: 800 });
            else lgScheduleSync(150);
        }

        function syncLanguageSetting() {
            if (!window.CloudI18n || !languageSelect || !languageSettingCurrent) return;
            const language = window.CloudI18n.getLanguage();
            const labels = { ko: "한국어", en: "English", zh: "中文", ja: "日本語", es: "español" };
            languageSelect.value = language;
            languageSettingCurrent.textContent = labels[language];
        }

        function syncThemeToggleAvailability() {
            const officeEnabled = document.body.classList.contains("office-mode");
            themeToggleItem.classList.toggle("disabled", officeEnabled);
            themeToggleItem.setAttribute("aria-disabled", officeEnabled ? "true" : "false");
            const i18n = window.CloudI18n;
            if (officeEnabled) {
                themeToggleIcon.className = "fa-solid fa-lock";
                themeToggleLabel.innerText = i18n ? i18n.t("화면 모드 고정됨") : "화면 모드 고정됨";
                themeToggleItem.title = i18n ? i18n.t("오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.") : "오피스 모드에서는 다크/라이트 모드를 바꿀 수 없습니다.";
                return;
            }
            const isDark = document.body.classList.contains("dark-mode");
            themeToggleIcon.className = isDark ? "fa-solid fa-sun" : "fa-solid fa-moon";
            themeToggleLabel.innerText = isDark ? (i18n ? i18n.t("라이트 모드") : "라이트 모드") : (i18n ? i18n.t("다크 모드") : "다크 모드");
            themeToggleItem.removeAttribute("title");
        }

        function syncOfficeModeLabel() {
            const enabled = document.body.classList.contains("office-mode");
            const i18n = window.CloudI18n;
            officeModeIcon.className = enabled ? "fa-solid fa-briefcase" : "fa-solid fa-briefcase";
            officeModeLabel.innerText = enabled
                ? (i18n ? i18n.t("오피스 모드 끄기") : "오피스 모드 끄기")
                : (i18n ? i18n.t("오피스 모드 켜기") : "오피스 모드 켜기");
            syncThemeToggleAvailability();
            syncOfficeComfortVisibility();
        }

        if (localStorage.getItem("officeMode") === "enabled") {
            document.body.classList.add("office-mode");
            document.body.classList.remove("dark-mode");
        }
        syncOfficeModeLabel();
        applyOfficeComfortSettings();
        lgReparentFixedPopovers();
        applyAppTheme();
        lgWatch();
        syncLanguageSetting();

        window.addEventListener("cloud-language-change", async function (event) {
            syncLanguageSetting();
            // 이미 화면에 있던 시스템 메시지도 새 언어의 문장 형태로 다시 그린다.
            await readMessages();
            try {
                const response = await fetch("/api/account/language", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ language: event.detail.language })
                });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "언어 설정을 저장하지 못했습니다.");
            } catch (error) {
                showToast(error.message || "언어 설정을 저장하지 못했습니다.", "error");
            }
        });

        [[officeContrastSelect, "officeContrast"], [officeTextSizeSelect, "officeTextSize"], [officeDensitySelect, "officeDensity"]].forEach(([control, key]) => {
            control.addEventListener("change", function () {
                localStorage.setItem(key, control.value);
                applyOfficeComfortSettings();
                // 고대비로 바꾸면 굴절을 꺼야 하므로 테마 상태를 다시 계산한다.
                lgSync();
            });
        });
        officeReduceMotion.addEventListener("change", function () {
            localStorage.setItem("officeReduceMotion", String(officeReduceMotion.checked));
            applyOfficeComfortSettings();
        });

        if (appThemeSelect) {
            appThemeSelect.addEventListener("change", function () {
                localStorage.setItem("appTheme", appThemeSelect.value);
                applyAppTheme();
            });
        }

        officeModeItem.addEventListener("click", function (event) {
            event.stopPropagation();
            closeSettingsMenu();
            const enabled = document.body.classList.toggle("office-mode");
            if (enabled) {
                // 사용자가 선택해 둔 화면 모드는 보존하고, 오피스 모드 동안만 적용을 멈춘다.
                document.body.classList.remove("dark-mode");
            } else if (localStorage.getItem("theme") === "dark") {
                document.body.classList.add("dark-mode");
            }
            localStorage.setItem("officeMode", enabled ? "enabled" : "disabled");
            syncOfficeModeLabel();
            // 오피스 모드에서는 굴절을 끄고, 해제하면 다시 적용한다.
            lgSync();
            showToast(enabled ? "오피스 모드를 적용했습니다." : "오피스 모드를 해제했습니다.");
        });

        /* ======================================================
         * 커스텀 확인/알림 모달
         * ====================================================== */

        // 하나의 확인 모달에는 항상 하나의 작업만 연결한다. 이전 취소 처리기가 남아
        // 친구 차단/삭제 때 과거 채팅방 삭제 모달을 다시 열던 상태 충돌을 막는다.
        let activeModalAction = null;
        function closeAppModal(confirmed) {
            const action = activeModalAction;
            activeModalAction = null;
            modalOverlay.style.display = "none";
            if (action) action(confirmed);
        }
        modalConfirmBtn.addEventListener("click", function () { closeAppModal(true); });
        modalCancelBtn.addEventListener("click", function () { closeAppModal(false); });
        modalOverlay.addEventListener("click", function (event) {
            if (event.target === modalOverlay) closeAppModal(false);
        });

        function showConfirm(message, onConfirm) {
            activeModalAction = onConfirm;
            modalMessage.innerText = window.CloudI18n ? window.CloudI18n.t(message) : message;
            modalCancelBtn.style.display = "inline-block";
            modalOverlay.style.display = "flex";
        }

        function showAlert(message, onClose) {
            activeModalAction = function (confirmed) { if (confirmed && onClose) onClose(); };
            modalMessage.innerText = window.CloudI18n ? window.CloudI18n.t(message) : message;
            modalCancelBtn.style.display = "none";
            modalOverlay.style.display = "flex";
        }

        // 저장·복사처럼 즉시 끝나는 작업은 화면을 막는 모달 대신 짧은 토스트로 알려준다.
        function showToast(message, type = "success") {
            const toast = document.createElement("div");
            const icon = type === "success" ? "fa-circle-check" : type === "error" ? "fa-circle-exclamation" : "fa-circle-info";
            toast.className = `toast ${type}`;
            const localizedMessage = window.CloudI18n ? window.CloudI18n.t(message) : message;
            toast.innerHTML = `<i class="fa-solid ${icon}"></i><span>${escapeHTML(localizedMessage)}</span>`;
            document.querySelector("#toast-region").appendChild(toast);
            setTimeout(function () {
                toast.classList.add("out");
                toast.addEventListener("animationend", function () { toast.remove(); }, { once: true });
            }, 2600);
        }

        let composerBusyCount = 0;

        // 전송 중 입력값이 지워지거나 같은 파일이 중복 전송되는 일을 막는다.
        function setComposerBusy(isBusy) {
            composerBusyCount = Math.max(0, composerBusyCount + (isBusy ? 1 : -1));
            const busy = composerBusyCount > 0;
            button.disabled = busy;
            plusBtn.disabled = busy;
            input.disabled = busy;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-busy", String(busy));
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
            if (composerBusyCount > 0) return;
            const planeIcon = document.querySelector(".input-area button i.fa-paper-plane");
            if (planeIcon) {
                planeIcon.classList.remove("launch");
                void planeIcon.offsetWidth;      // 같은 애니메이션을 연속으로 눌러도 재생되게 강제 리플로우
                planeIcon.classList.add("launch");
            }

            const text = input.value.trim();
            if (text === "") return;

            if (!currentConversationID) {
                showAlert("먼저 채팅방을 선택해주세요.");
                return;
            }

            setComposerBusy(true);
            try {
                if (editingIndex !== null) {
                    const response = await fetch(`/api/messages/${editingIndex}`, {
                        method: "PATCH",
                        headers: {"Content-Type": "application/json" },
                        body: JSON.stringify({ text:text })
                    });
                    const result = await response.json();
                    if (!response.ok || !result.success) throw new Error(result.error || "메시지를 수정하지 못했습니다.");

                    await readMessages();
                    updateFriendPreviewFromServer();

                    editingIndex = null;
                    input.value = "";
                    replyMessage = null;
                    replyPreview.style.display = "none";
                    editPreview.style.display = "none";
                    button.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
                    showToast("메시지를 수정했습니다.");
                    return;
                }

                const response = await fetch(`/api/conversations/${currentConversationID}/messages`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json"},
                    body: JSON.stringify({
                        text: text,
                        mine: true,
                        reply: replyMessage,
                        read: false
                    })
                });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "메시지를 보내지 못했습니다.");

                await readMessages();
                updateFriendPreviewFromServer();

                input.value = "";
                replyMessage = null;
                replyPreview.style.display = "none";
            } catch (error) {
                showToast(error.message || "서버와 통신 중 문제가 발생했습니다.", "error");
            } finally {
                setComposerBusy(false);
            }

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
                    </div>
                `;
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
                const displayDate = formatMessageDate(chat);
                const displayTime = formatMessageTime(chat);

                if (displayDate !== lastDate) {
                    const dateLine = document.createElement("div");
                    dateLine.className = "date-divider";
                    dateLine.innerText = displayDate;
                    renderTarget.appendChild(dateLine);
                    lastDate = displayDate;
                }

                const message = document.createElement("div");
                message.dataset.msgIndex = index;

                if (chat.messageType === "system") {
                    message.className = "message-system";
                    message.textContent = localizeSystemMessage(chat.text || "채팅방 안내");
                    renderTarget.appendChild(message);
                    return;
                }

                message.addEventListener("contextmenu", function (event) {
                    event.preventDefault();

                    selectedMessage = chat;
                    selectedIndex = chat.id;
                    pinLabel.innerText = chat.pinned ? "고정 해제" : "고정";

                    if (chat.image || chat.video || chat.filePath || chat.audio) {
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
                    forwardMessageButton.style.display = "block";
                    reportMessageButton.style.display = chat.mine ? "none" : "block";
                    messageMenu.style.display = "block";
                    messageMenu.style.pointerEvents = "auto";

                    let target = message.querySelector(
                        ".chat-image, .chat-file-card, .chat-audio, .bubble, .message-left"
                    );
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

                    if (chat.audio) {
                        message.innerHTML = `<div class="time">${readStatusHTML}${displayTime}</div><audio class="chat-audio" controls src="${chat.audio}"></audio>`;
                    } else if (chat.filePath) {
                        message.innerHTML = `
                            <div class="time">${readStatusHTML}${displayTime}</div>
                            ${buildFileMessageHTML(chat)}
                        `;
                    } else if (chat.video) {
                        message.innerHTML = `
                            ${reactionsHTML}
                            <div class="time">${readStatusHTML}${displayTime}</div>
                            <div class="image-bubble">
                                <video src="${chat.video}" class="chat-image" controls style="max-width: 250px; border-radius: 12px; display: block;"></video>
                            </div>
                        `;
                    } else if (chat.image) {
                        message.innerHTML = `
                            ${reactionsHTML}
                            <div class="time">${readStatusHTML}${displayTime}</div>
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
                                <div class="time">${readStatusHTML}${displayTime}</div>
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
                                <div class="time">${readStatusHTML}${displayTime}</div>
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

                    if (chat.audio) {
                        innerContent = `<audio class="chat-audio" controls src="${chat.audio}"></audio><div class="time">${displayTime}</div>`;
                    } else if (chat.filePath) {
                        innerContent = `
                            ${buildFileMessageHTML(chat)}
                            <div class="time">${displayTime}</div>
                        `;
                    } else if (chat.video) {
                        innerContent = `
                            <div class="image-bubble">
                                <video src="${chat.video}" class="chat-image" controls style="max-width: 250px; border-radius: 12px; display: block;"></video>
                            </div>
                            <div class="time">${displayTime}</div>
                            ${reactionsHTML}
                        `;
                    } else if (chat.image) {
                        innerContent = `
                            <div class="image-bubble">
                                <img src="${chat.image}" class="chat-image">
                            </div>
                            <div class="time">${displayTime}</div>
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
                                <div class="time">${displayTime}</div>
                            </div>
                            ${reactionsHTML}
                        `;
                    } else {
                        innerContent = `
                            <div class="bubble-row">
                                <div class="message-left">${highlightText(chat.text, searchQuery)}</div>
                                <div class="time">${displayTime}</div>
                            </div>
                            ${reactionsHTML}
                        `;
                    }

                    message.innerHTML = isGroupChat
                        ? `${avatarHTML}<div class="msg-content-col">${senderNameHTML}${innerContent}</div>`
                        : innerContent;
                }

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

                // 캐시된 미리보기는 동기적으로 처리되므로, DOM에 붙은 뒤에 호출해야 연결 여부 검사를 통과한다.
                if (chat.text && !chat.image && !chat.video) appendLinkPreview(message, chat);
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
                showToast("메시지를 복사했습니다.");
                focusInputSafely();
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
                        updateFriendPreviewFromServer();
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

        forwardMessageButton.addEventListener("click", function () {
            if (!selectedIndex) return;
            forwardConversationSelect.innerHTML = friends
                .filter(function (friend) { return friend.id !== currentConversationID; })
                .map(function (friend) { return `<option value="${friend.id}">${escapeHTML(friend.name)}</option>`; })
                .join("");
            closeMessageMenu();
            if (!forwardConversationSelect.options.length) {
                showToast("전달할 다른 채팅방이 없습니다.", "error");
                return;
            }
            forwardMessageOverlay.style.display = "flex";
        });
        forwardMessageClose.addEventListener("click", function () { forwardMessageOverlay.style.display = "none"; });
        forwardMessageSubmit.addEventListener("click", async function () {
            const response = await fetch(`/api/messages/${selectedIndex}/forward`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ conversation_id: Number(forwardConversationSelect.value) })
            });
            const result = await response.json();
            if (!response.ok || !result.success) return showToast(result.error || "전달에 실패했습니다.", "error");
            forwardMessageOverlay.style.display = "none";
            showToast("메시지를 전달했습니다.");
        });

        reportMessageButton.addEventListener("click", function () {
            if (!selectedIndex) return;
            reportTarget = { type: "message", id: selectedIndex };
            reportModalTitle.textContent = "메시지 신고";
            reportReasonSelect.value = "";
            reportDetail.value = "";
            closeMessageMenu();
            reportMessageOverlay.style.display = "flex";
        });
        reportMessageClose.addEventListener("click", function () { reportMessageOverlay.style.display = "none"; });
        reportMessageSubmit.addEventListener("click", async function () {
            if (!reportTarget) return;
            if (!reportReasonSelect.value) return showToast("신고 사유를 선택해주세요.", "error");
            const url = reportTarget.type === "user" ? `/api/users/${reportTarget.id}/report` : `/api/messages/${reportTarget.id}/report`;
            const response = await fetch(url, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason: reportReasonSelect.value, detail: reportDetail.value.trim() })
            });
            const result = await response.json();
            if (!response.ok || !result.success) return showToast(result.error || "신고 접수에 실패했습니다.", "error");
            reportMessageOverlay.style.display = "none";
            showToast("신고가 접수되었습니다.");
        });

        /* ======================================================
         * 사진 첨부 / 전송
         * ====================================================== */

        imageBtn.addEventListener("click", function () {
            imageInput.click();
            attachMenu.style.display = "none";
        });

        imageInput.addEventListener("change", async function () {
            const files = imageInput.files;
            if (!files || files.length === 0) return;
            for (const file of files) await sendImage(file);
        });

        async function sendImage(file) {
            if (!currentConversationID) {
                showAlert("먼저 채팅방을 선택해주세요.");
                return;
            }
            setComposerBusy(true);
            try {
                const imageData = await new Promise(function (resolve, reject) {
                    const reader = new FileReader();
                    reader.onload = function () { resolve(reader.result); };
                    reader.onerror = function () { reject(new Error("사진 파일을 읽지 못했습니다.")); };
                    reader.readAsDataURL(file);
                });
                const response = await fetch(`/api/conversations/${currentConversationID}/messages/image`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ image: imageData })
                });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "사진을 보내지 못했습니다.");

                await readMessages();
                updateFriendPreviewFromServer();
                replyMessage = null;
                replyPreview.style.display = "none";
                showToast("사진을 보냈습니다.");
            } catch (error) {
                showToast(error.message || "사진 전송 중 문제가 발생했습니다.", "error");
            } finally {
                imageInput.value = "";
                setComposerBusy(false);
                setTimeout(function () { input.focus(); }, 10);
            }
        }

        fileBtn.addEventListener("click", function () {
            fileInput.click();
            attachMenu.style.display = "none";
        });

        fileInput.addEventListener("change", async function () {
            const file = fileInput.files[0];
            if (!file || !currentConversationID) return;
            setComposerBusy(true);
            try {
                const formData = new FormData();
                formData.append("file", file);
                const response = await fetch(`/api/conversations/${currentConversationID}/messages/file`, { method: "POST", body: formData });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "파일을 보내지 못했습니다.");
                await readMessages();
                updateFriendPreviewFromServer();
                showToast("파일을 보냈습니다.");
            } catch (error) {
                showToast(error.message || "파일 전송에 실패했습니다.", "error");
            } finally {
                fileInput.value = "";
                setComposerBusy(false);
            }
        });

        let audioRecorder = null;
        let audioChunks = [];
        let audioTimer = null;
        let audioStartedAt = 0;
        audioBtn.addEventListener("click", async function () {
            if (!currentConversationID) return showToast("먼저 채팅방을 선택해주세요.", "error");
            if (!navigator.mediaDevices || !window.MediaRecorder) return showToast("이 브라우저에서는 음성 메시지를 지원하지 않습니다.", "error");
            try {
                if (audioRecorder && audioRecorder.state === "recording") { audioRecorder.stop(); return; }
                const stream = await navigator.mediaDevices.getUserMedia({ audio:true });
                audioChunks = [];
                audioRecorder = new MediaRecorder(stream);
                audioRecorder.ondataavailable = event => { if (event.data.size) audioChunks.push(event.data); };
                audioRecorder.onstop = async function () {
                    clearTimeout(audioTimer); stream.getTracks().forEach(track => track.stop()); audioBtn.classList.remove("recording");
                    const blob = new Blob(audioChunks, {type:audioRecorder.mimeType || "audio/webm"});
                    if (!blob.size) return;
                    const form = new FormData(); form.append("audio", new File([blob], "voice.webm", {type:blob.type})); form.append("duration", String(Math.min(30, (Date.now() - audioStartedAt) / 1000)));
                    const response = await fetch(`/api/conversations/${currentConversationID}/messages/audio`, {method:"POST", body:form}); const result = await response.json();
                    if (!response.ok || !result.success) return showToast(result.error || "음성 전송에 실패했습니다.", "error");
                    await readMessages(); updateFriendPreviewFromServer();
                };
                audioStartedAt = Date.now(); audioRecorder.start(); audioBtn.classList.add("recording"); showToast("녹음 중입니다. 다시 누르면 전송합니다. (최대 30초)");
                audioTimer = setTimeout(() => { if (audioRecorder && audioRecorder.state === "recording") audioRecorder.stop(); }, 30000);
            } catch (error) { showToast("마이크 권한을 허용해주세요.", "error"); }
        });

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
            friendList.classList.toggle("is-empty", friends.length === 0);
            conversationSummary.innerText = friends.length > 0
                ? `${friends.length}개의 채팅방`
                : "대화를 선택해 시작하세요";

            if (friends.length === 0) {
                friendList.innerHTML = `
                    <div class="empty-friends">
                        <i class="fa-solid fa-user-group"></i>
                        <strong>아직 채팅방 없어요</strong>
                    </div>
                `;
                return;
            }

            friends.forEach(function (friend) {
                const newFriend = document.createElement("div");
                newFriend.className = friend.id === currentConversationID ? "friend active" : "friend";

                newFriend.addEventListener("click", async function () {
                    currentConversationID = friend.id;
                    openMobileChat();
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

                        showConfirm("채팅방을 목록에서 숨기시겠습니까? 친구 관계와 이전 대화는 유지됩니다.", async function (confirmDelete) {
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
                

                const previewHTML = escapeHTML(friend.message || "아직 대화가 없습니다.")
                .replace("__CAMERA__", '<i class="fa-regular fa-image"></i>')
                .replace("__VIDEO__", '<i class="fa-solid fa-circle-play"></i>')
                .replace("__FILE__", '<i class="fa-solid fa-paperclip"></i>')
                .replace("__AUDIO__", '<i class="fa-solid fa-microphone"></i>');
                const timeHTML = (friend.lastSentAt || friend.lastTime)
                    ? `<span class="friend-time">${formatMessageTime({ sentAt: friend.lastSentAt, time: friend.lastTime })}</span>`
                    : "";

                // 안 읽은 개수는 서버가 이미 계산해서 주는 unreadCount를 그대로 사용한다.
                const unreadHTML = (friend.unreadCount > 0 && friend.id !== currentConversationID)
                    ? `<span class="unread-badge">${friend.unreadCount}</span>`
                    : "";

                const avatarImg = getConversationAvatar(friend);
                const statusHTML = getPresenceIndicatorHTML(friend);
                
                newFriend.innerHTML = `
                    <div class="profile ${friend.isGroup ? "" : "friend-profile-trigger"}" ${friend.isGroup ? "" : 'role="button" tabindex="0" aria-label="상대방 프로필 보기"'}>
                        <img src="${avatarImg}" alt="Profile Image">
                        ${statusHTML}
                    </div>
                    <div style="flex:1; min-width:0;">
                        <div class="friend-header-row">
                            <div class="friend-name">${friend.isPinned ? '<i class="fa-solid fa-thumbtack" title="고정된 채팅방"></i> ' : ''}${escapeHTML(friend.name)} ${friend.isMuted ? '<i class="fa-solid fa-bell-slash" title="알림 꺼짐"></i>' : ''}</div>
                            ${timeHTML}
                        </div>
                        <small class="friend-preview" title="${escapeHTML(friend.message || "")}">${previewHTML}</small>
                    </div>
                    ${unreadHTML}
                `;
                if (!friend.isGroup) {
                    const profileTrigger = newFriend.querySelector(".friend-profile-trigger");
                    const openFriendProfile = function (event) {
                        event.stopPropagation();
                        openProfileCard(friend);
                    };
                    profileTrigger.addEventListener("click", openFriendProfile);
                    profileTrigger.addEventListener("keydown", function (event) {
                        if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            openFriendProfile(event);
                        }
                    });
                }
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
                showToast("친구 요청을 보냈습니다.");
            }
        }

        async function loadFriendRequests() {
            const response = await fetch("/api/friend-requests");
            const result = await response.json();
            const chessResult = window.CLOUD_CHESS_UI_ENABLED
                ? await fetch("/api/chess/invites").then(async function (chessResponse) {
                    return chessResponse.ok ? chessResponse.json() : { invites: [] };
                })
                : { invites: [] };
            const incoming = result.incoming || [];
            const outgoing = result.outgoing || [];
            const chessInvites = chessResult.invites || [];

            incomingRequestCount.innerText = incoming.length + chessInvites.length;
            outgoingRequestCount.innerText = outgoing.length;
            friendInboxBadge.hidden = incoming.length + chessInvites.length === 0;
            friendInboxBadge.textContent = incoming.length + chessInvites.length > 99 ? "99+" : incoming.length + chessInvites.length;

            outgoingFriendRequestList.innerHTML = "";

            if(outgoing.length === 0) {
                outgoingFriendRequestList.innerHTML = 
                `<div class="request-empty">보낸 친구 요청이 아직 없습니다.</div>`;
            } else {
                outgoing.forEach(function (request) {
                    const item = document.createElement("div");
                    item.className = "friend-request-item";

                    item.innerHTML = `
                        <img class="request-profile-image" src="${escapeHTML(request.profile_image || "/static/default_profile.png")}"><span><strong>${escapeHTML(request.display_name || request.username)}</strong><small>친구 요청을 보냈습니다.</small></span>
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

            renderFriendRequestList(incoming, chessInvites);
        }

        function renderFriendRequestList(incoming, chessInvites = []) {
            friendRequestList.innerHTML = "";

            if(incoming.length === 0 && chessInvites.length === 0) {
                friendRequestList.innerHTML = `<div class="friend-request-empty">받은 요청이 없습니다.</div>`;
                return;
            }

            chessInvites.forEach(function (invite) {
                const item = document.createElement("div");
                item.className = "friend-request-item chess-inbox-invite";
                item.innerHTML = `
                    <img class="request-profile-image" src="${escapeHTML(invite.profile_image || "/static/default_profile.png")}"><span><strong><i class="fa-solid fa-chess-knight"></i> ${escapeHTML(invite.display_name || invite.username)}</strong><small>체스 대국에 초대했습니다.</small></span>
                    <span class="accept-request-icon" title="수락"><i class="fa-solid fa-check"></i></span>
                    <span class="decline-request-icon" title="거절"><i class="fa-solid fa-xmark"></i></span>
                `;
                item.querySelector(".accept-request-icon").addEventListener("click", async function () {
                    const response = await fetch(`/api/chess/invites/${invite.id}/accept`, { method:"POST", headers:{"X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || ""} });
                    const result = await response.json();
                    if (!response.ok || !result.success) return showAlert(result.error || "체스 초대를 수락하지 못했습니다.");
                    location.href = `/chess/game/${result.game.id}`;
                });
                item.querySelector(".decline-request-icon").addEventListener("click", async function () {
                    const response = await fetch(`/api/chess/invites/${invite.id}/decline`, { method:"POST", headers:{"X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || ""} });
                    const result = await response.json();
                    if (!response.ok || !result.success) return showAlert(result.error || "체스 초대를 거절하지 못했습니다.");
                    await loadFriendRequests();
                });
                friendRequestList.appendChild(item);
            });

            incoming.forEach(function (req) {
                const item = document.createElement("div");
                item.className = "friend-request-item";
                item.innerHTML = `
                    <img class="request-profile-image" src="${escapeHTML(req.profile_image || "/static/default_profile.png")}"><span><strong>${escapeHTML(req.display_name || req.username)}</strong><small>친구 요청을 보냈습니다.</small></span>
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
                const groupEditable = currentGroupOwnerId === MY_USER_ID && currentGroup && !currentGroup.isDisabled;
                groupNameText.innerText = currentGroup ? currentGroup.name : "";
                renameGroupBtn.style.display = groupEditable ? "inline-block" : "none";
                disableGroupBtn.style.display = groupEditable ? "inline-block" : "none";
                groupPhotoImg.src = result.groupProfileImage || "/static/default_profile.png";
                changeGroupPhotoBtn.style.display = groupEditable ? "flex" : "none";
                removeGroupPhotoBtn.style.display = groupEditable ? "block" : "none";
                openInviteMemberBtn.style.display = groupEditable ? "inline-flex" : "none";

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
                    } else if (groupEditable) {
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

        disableGroupBtn.addEventListener("click", function () {
            showConfirm("그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.", async function (ok) {
                if (!ok) return;
                const response = await fetch(`/api/conversations/${currentConversationID}/disable`, {method:"POST"});
                const result = await response.json();
                if (!response.ok || !result.success) return showToast(result.error || "종료하지 못했습니다.", "error");
                groupMembersOverlay.style.display="none"; await loadFriends(); await readMessages(); updateBlockState(); showToast("그룹 채팅을 종료했습니다.");
            });
        });

        function renderInviteMemberList() {
            inviteMemberList.innerHTML = "";

            const memberUsernames = new Set(currentGroupMembers.map(function (m) { return m.username; }));
            const invitableFriends = friendDirectory.filter(function (friend) {
                return !memberUsernames.has(friend.peerUsername);
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

            friendDirectory.forEach(function (friend) {
                const item = document.createElement("div");
                item.className = "friend-panel-item";

                // 그룹 채팅은 상대가 여럿이라 차단 개념이 적용되지 않으므로 버튼을 두지 않는다.
                const blockIconHTML = friend.isGroup
                    ? ""
                    : (friend.blockedByMe
                        ? `<span class="unblock-friend-icon" title="차단 해제"><i class="fa-solid fa-lock-open"></i></span>`
                        : `<span class="block-friend-icon" title="차단"><i class="fa-solid fa-ban"></i></span>`);

                const chessInviteIconHTML = !window.CLOUD_CHESS_UI_ENABLED || friend.blockedByMe || friend.blockedMe
                    ? ""
                    : `<span class="chess-invite-friend-icon" title="체스 초대" role="button" tabindex="0" aria-label="${escapeHTML(friend.name)}님에게 체스 초대">
                        <i class="fa-solid fa-chess-knight"></i>
                    </span>`;

                item.innerHTML = `
                    <button type="button" class="friend-panel-profile-trigger" aria-label="${escapeHTML(friend.name)} 프로필 보기">
                        <img src="${escapeHTML(friend.peerProfileImage || "/static/default_profile.png")}" alt="">
                        <span>${escapeHTML(friend.name)}</span>
                    </button>
                    <div class="friend-panel-actions">
                        ${chessInviteIconHTML}
                        ${blockIconHTML}
                        <span class="delete-friend-icon" title="친구 삭제"><i class="fa-solid fa-trash"></i></span>
                    </div>
                `;

                item.querySelector(".friend-panel-profile-trigger").addEventListener("click", function () {
                    openProfileCard(friend);
                });

                const chessInviteIcon = item.querySelector(".chess-invite-friend-icon");
                if (chessInviteIcon) {
                    const sendChessInvite = async function (event) {
                        event.preventDefault();
                        event.stopPropagation();
                        if (chessInviteIcon.classList.contains("is-sending")) return;

                        chessInviteIcon.classList.add("is-sending");
                        chessInviteIcon.setAttribute("aria-busy", "true");

                        try {
                            const response = await fetch(`/api/chess/quick-invite/${friend.peerId}`, {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ timeControl: "unlimited" })
                            });
                            const result = await response.json();
                            if (!response.ok || !result.success) {
                                throw new Error(result.error || "체스 초대를 보내지 못했습니다.");
                            }

                            showToast(`"${friend.name}"님에게 체스 초대를 보냈습니다.`);
                            window.location.href = `/chess/game/${result.game.id}`;
                        } catch (error) {
                            chessInviteIcon.classList.remove("is-sending");
                            chessInviteIcon.removeAttribute("aria-busy");
                            showAlert(error.message || "체스 초대를 보내는 중 문제가 발생했습니다.");
                        }
                    };

                    chessInviteIcon.addEventListener("click", sendChessInvite);
                    chessInviteIcon.addEventListener("keydown", function (event) {
                        if (event.key === "Enter" || event.key === " ") sendChessInvite(event);
                    });
                }

                item.querySelector(".delete-friend-icon").addEventListener("click", function () {
                    showConfirm(`"${friend.name}"님을 삭제하시겠습니까?`, async function (confirmDelete) {
                        if (!confirmDelete) return;

                        const response = await fetch(`/api/friends/${friend.peerId}`, { method: "DELETE" });
                        const result = await response.json();
                        if (!response.ok || !result.success) {
                            showAlert(result.error || "친구를 삭제하지 못했습니다.");
                            return;
                        }
                        await loadFriendDirectory();
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

                            await loadFriendDirectory();
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

                            await loadFriendDirectory();
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

            const oneOnOnFriends = friendDirectory;

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

        async function searchFriendProfile() {
            const username = friendSearchInput.value.trim();
            if (!username) return;
            friendSearchResult.innerHTML = '<span class="friend-search-loading">검색 중...</span>';
            try {
                const response = await fetch(`/api/users/search?username=${encodeURIComponent(username)}`);
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "사용자를 찾을 수 없습니다.");
                const user = result.user;
                const cardFriend = {
                    isGroup: false, peerId: user.id, name: user.display_name || user.username,
                    peerProfileImage: user.profile_image, peerCoverImage: user.cover_image,
                    peerBio: user.bio, isOnline: user.is_online
                };
                friendSearchResult.innerHTML = `
                    <div class="friend-search-card">
                        <button type="button" class="friend-search-profile" aria-label="${escapeHTML(cardFriend.name)} 프로필 보기"><img src="${escapeHTML(user.profile_image || "/static/default_profile.png")}" alt=""><span><strong>${escapeHTML(cardFriend.name)}</strong><small>@${escapeHTML(user.username)}</small></span></button>
                        ${user.is_friend ? '<span class="friend-search-state">친구</span>' : `<button type="button" class="friend-search-add" data-username="${escapeHTML(user.username)}">친구 추가</button>`}
                    </div>`;
                friendSearchResult.querySelector(".friend-search-profile").addEventListener("click", function () { openProfileCard(cardFriend); });
                const addButton = friendSearchResult.querySelector(".friend-search-add");
                if (addButton) addButton.addEventListener("click", async function () { await sendFriendRequest(user.username); });
            } catch (error) {
                friendSearchResult.innerHTML = `<span class="friend-search-error">${escapeHTML(error.message)}</span>`;
            }
        }
        friendSearchBtn.addEventListener("click", searchFriendProfile);
        friendSearchInput.addEventListener("keydown", function (event) { if (event.key === "Enter") { event.preventDefault(); searchFriendProfile(); } });

        friendPanelTab.addEventListener("click", function () {
            if (friendPanel.classList.contains("open")) closeFriendPanel();
            else openFriendPanel();
        });

        closeFriendPanelBtn.addEventListener("click", function () {
            closeFriendPanel();
        });

        friendInboxBtn.addEventListener("click", openFriendInbox);
        friendInboxCloseBtn.addEventListener("click", closeFriendInbox);
        friendInboxOverlay.addEventListener("click", function (event) {
            if (event.target === friendInboxOverlay) closeFriendInbox();
        });
        friendInboxTabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                const incomingTab = tab.dataset.inboxTab === "incoming";
                friendInboxTabs.forEach(function (button) { button.classList.toggle("active", button === tab); });
                friendRequestList.hidden = !incomingTab;
                outgoingFriendRequestList.hidden = incomingTab;
            });
        });

        mobileBackBtn.addEventListener("click", function () {
            // 대화는 닫지 않고 목록만 보여준다. 다시 같은 방을 눌러도 메시지가 유지된다.
            closeMobileChat();
            setMobileNavActive(mobileChatNavBtn);
        });

        mobileChatMoreBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            const isOpen = mobileChatActionsSheet.classList.toggle("open");
            mobileChatActionsSheet.classList.toggle("group-chat", !!(getCurrentFriend() && getCurrentFriend().isGroup));
            mobileChatActionsSheet.setAttribute("aria-hidden", String(!isOpen));
        });

        mobileChatActionsSheet.addEventListener("click", async function (event) {
            const actionButton = event.target.closest("[data-chat-action]");
            if (!actionButton) return;
            const sourceButton = {
                theme: chatThemeBtn,
                gallery: galleryToggleBtn,
                members: groupMembersBtn,
            }[actionButton.dataset.chatAction];
            closeMobileChatActions();
            if (["pin", "mute"].includes(actionButton.dataset.chatAction)) {
                const friend = getCurrentFriend();
                if (!friend) return;
                const field = actionButton.dataset.chatAction === "pin" ? "is_pinned" : "is_muted";
                const nextValue = actionButton.dataset.chatAction === "pin" ? !friend.isPinned : !friend.isMuted;
                const response = await fetch(`/api/conversations/${friend.id}/preferences`, {
                    method: "PATCH", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ [field]: nextValue })
                });
                const result = await response.json();
                if (!response.ok || !result.success) return showToast(result.error || "설정을 변경하지 못했습니다.", "error");
                await loadFriends();
                updateChatHeader(getCurrentFriend());
                readFriends();
                return showToast(nextValue ? (field === "is_pinned" ? "채팅방을 고정했습니다." : "이 채팅방 알림을 껐습니다.") : (field === "is_pinned" ? "채팅방 고정을 해제했습니다." : "이 채팅방 알림을 켰습니다."));
            }
            if (sourceButton) sourceButton.click();
        });

        async function updateConversationPreference(field, value) {
            const friend = getCurrentFriend();
            if (!friend) return;
            const response = await fetch(`/api/conversations/${friend.id}/preferences`, {
                method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [field]: value })
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "설정을 변경하지 못했습니다.");
            await loadFriends();
            updateChatHeader(getCurrentFriend());
            readFriends();
        }

        desktopConversationPin.addEventListener("click", async function () {
            const friend = getCurrentFriend();
            if (!friend) return;
            try { await updateConversationPreference("is_pinned", !friend.isPinned); showToast(!friend.isPinned ? "채팅방을 고정했습니다." : "채팅방 고정을 해제했습니다."); } catch (error) { showToast(error.message, "error"); }
        });
        desktopConversationMute.addEventListener("click", async function () {
            const friend = getCurrentFriend();
            if (!friend) return;
            try { await updateConversationPreference("is_muted", !friend.isMuted); showToast(!friend.isMuted ? "이 채팅방 알림을 껐습니다." : "이 채팅방 알림을 켰습니다."); } catch (error) { showToast(error.message, "error"); }
        });

        document.addEventListener("click", function (event) {
            if (!mobileChatActionsSheet.contains(event.target) && !mobileChatMoreBtn.contains(event.target)) {
                closeMobileChatActions();
            }
        });

        window.addEventListener("resize", function () {
            // 휴대폰을 가로로 돌리거나 PC 폭으로 넓히면 데스크톱 2단 레이아웃으로 복귀한다.
            if (!isMobileViewport()) {
                closeMobileChat();
                closeMobileChatActions();
                document.body.classList.remove("mobile-friends-open", "mobile-settings-open");
            }
        });

        /* ======================================================
         * 설정 메뉴 / 프로필 편집 (UI만 준비된 기능)
         * ====================================================== */

        sideNavSettings.addEventListener("click", function (event) {
            event.stopPropagation();
            openSettingsMenu(sideNavSettings);
        });

        // 모바일 하단 메뉴: 채팅 목록·친구 관리·프로필·설정을 각각 한 번에 연다.
        mobileChatNavBtn.addEventListener("click", function () {
            closeMobileChat();
            closeFriendPanel();
            closeSettingsMenu();
            setMobileNavActive(mobileChatNavBtn);
        });

        mobileFriendsNavBtn.addEventListener("click", function () {
            closeSettingsMenu();
            if (friendPanel.classList.contains("open")) closeFriendPanel();
            else openFriendPanel();
            setMobileNavActive(mobileFriendsNavBtn);
        });

        mobileProfileNavBtn.addEventListener("click", function () {
            closeSettingsMenu();
            closeFriendPanel();
            openProfileEditor();
            setMobileNavActive(mobileProfileNavBtn);
        });

        mobileSettingsNavBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            closeFriendPanel();
            openSettingsMenu(mobileSettingsNavBtn);
            setMobileNavActive(mobileSettingsNavBtn);
        });

        document.addEventListener("click", function (event) {
            if (!settingsMenu.contains(event.target) && !sideNavSettings.contains(event.target) && !mobileSettingsNavBtn.contains(event.target)) {
                closeSettingsMenu();
            }
        });

        mobileSheetBackdrop.addEventListener("click", function () {
            closeSettingsMenu();
            closeFriendPanel();
        });

        chatThemeBtn.addEventListener("click", function () {
            if (!currentConversationID) {
                showAlert("먼저 채팅방을 선택해주세요.");
                return;
            }
            const friend = getCurrentFriend();
            applyChatTheme(friend);
            showThemeCategory(getThemeCategory(friend && friend.chatTheme ? friend.chatTheme : "default"));
            chatThemeOverlay.style.display = "flex";
        });

        chatThemeCloseBtn.addEventListener("click", function () {
            chatThemeOverlay.style.display = "none";
        });

        chatThemeOverlay.addEventListener("click", function (event) {
            if (event.target === chatThemeOverlay) chatThemeOverlay.style.display = "none";
        });

        chatThemeCategories.forEach(function (category) {
            category.addEventListener("click", function () {
                showThemeCategory(category.dataset.themeCategory);
            });
        });

        chatThemeOptions.forEach(function (option) {
            option.addEventListener("click", async function () {
                const friend = getCurrentFriend();
                if (!friend) return;
                const theme = option.dataset.theme;
                try {
                    const response = await fetch(`/api/conversations/${friend.id}/theme`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ theme })
                    });
                    const result = await response.json();
                    if (!response.ok || !result.success) throw new Error(result.error || "테마 변경에 실패했습니다.");
                    friend.chatTheme = result.theme;
                    applyChatTheme(friend);
                    chatThemeOverlay.style.display = "none";
                } catch (error) {
                    showAlert(error.message || "테마 변경에 실패했습니다.");
                }
            });
        });

        logoutBtn.addEventListener("click", function () {
            closeSettingsMenu();

            showConfirm("로그아웃 하시겠습니까?", async function (confirmLogout) {
                if (!confirmLogout) return;
                await fetch("/api/logout", { method: "POST" });
                window.location.href = "/login";
            });
        });

        async function openProfileEditor() {
            pendingProfileImageData = null;
            pendingProfileImageRemoval = false;
            savedProfileImageHTML = sideNavProfilePic.innerHTML;
            profileModalPic.innerHTML = savedProfileImageHTML;
            document.querySelector("#my-profile-name").value = document.querySelector("#current-username").innerText;
            try {
                const profile = await fetch("/api/account/profile").then(response => response.json());
                myProfileBio.value = profile.bio || "";
                myProfileVisibility.value = profile.profile_visibility || "friends";
                updateProfileCoverPreview(profile.cover_image);
            } catch (error) { /* 기본 편집은 계속 가능 */ }
            myProfileOverlay.style.display = "flex";
        }

        editProfileBtn.addEventListener("click", openProfileEditor);

        myProfileCancelBtn.addEventListener("click", function () {
            profileModalPic.innerHTML = savedProfileImageHTML;
            pendingProfileImageData = null;
            pendingProfileImageRemoval = false;
            myProfileOverlay.style.display = "none";
        });
        myProfileCloseBtn.addEventListener("click", function () { myProfileCancelBtn.click(); });
        myProfileOverlay.addEventListener("click", function (event) {
            if (event.target === myProfileOverlay) myProfileCancelBtn.click();
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
                const profileResponse = await fetch("/api/account/profile", { method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({bio:myProfileBio.value.trim(), profile_visibility:myProfileVisibility.value}) });
                const profileResult = await profileResponse.json();
                if (!profileResponse.ok || !profileResult.success) throw new Error(profileResult.error || "프로필 정보를 저장하지 못했습니다.");
                pendingProfileImageData = null;
                pendingProfileImageRemoval = false;
                myProfileOverlay.style.display = "none";
            } catch (err) {
                showAlert("서버와 통신 중 문제가 발생했습니다.");
            }
        });

        coverImageInput.addEventListener("change", function () {
            const file = coverImageInput.files[0]; if (!file) return;
            const reader = new FileReader();
            reader.onload = async function () {
                const response = await fetch("/api/account/cover-image", {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({image:reader.result})});
                const result = await response.json();
                if (result.success) updateProfileCoverPreview(result.cover_image);
                showToast(result.success ? "배경사진을 변경했습니다." : result.error, result.success ? undefined : "error");
            }; reader.readAsDataURL(file);
        });
        function updateProfileCoverPreview(imageUrl) {
            profileCoverPreview.style.backgroundImage = imageUrl ? `url("${imageUrl}")` : "";
            profileCoverPreview.classList.toggle("has-image", Boolean(imageUrl));
            profileCoverPreview.innerHTML = imageUrl ? "" : '<span><i class="fa-regular fa-image"></i> 배경사진 없음</span>';
        }
        removeCoverImageBtn.addEventListener("click", async function () { const response = await fetch("/api/account/cover-image", {method:"DELETE"}); const result=await response.json(); if (result.success) updateProfileCoverPreview(null); showToast(result.success ? "배경사진을 제거했습니다." : result.error, result.success ? undefined : "error"); });
        profileCardClose.addEventListener("click", function () { profileCardOverlay.style.display="none"; });
        profileCardOverlay.addEventListener("click", function(event){ if(event.target===profileCardOverlay) profileCardOverlay.style.display="none"; });

        /* ======================================================
         * 프로필 카드 ⋮ 메뉴 — 신고하기 / 차단하기
         * ====================================================== */
        profileCardMenuBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            const willOpen = profileCardMenu.hidden;
            profileCardMenu.hidden = !willOpen;
            profileCardMenuBtn.setAttribute("aria-expanded", String(willOpen));
        });
        document.addEventListener("click", function (event) {
            if (profileCardMenu.hidden) return;
            if (profileCardMenu.contains(event.target) || event.target === profileCardMenuBtn) return;
            profileCardMenu.hidden = true;
            profileCardMenuBtn.setAttribute("aria-expanded", "false");
        });
        profileCardBlockItem.addEventListener("click", function () {
            profileCardMenu.hidden = true;
            const target = profileCardTarget;
            if (!target) return;
            showConfirm(`"${target.name}"님을 차단하시겠습니까? 차단하면 서로 메시지를 보낼 수 없어요.`, async function (confirmed) {
                if (!confirmed) return;
                const response = await fetch("/api/blocks", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: target.peerId })
                });
                const result = await response.json();
                if (!result.success) return showAlert(result.error);
                profileCardOverlay.style.display = "none";
                await loadFriends();
                renderFriendPanelList();
                updateBlockState();
                showToast(`"${target.name}"님을 차단했습니다.`);
            });
        });
        profileCardReportItem.addEventListener("click", function () {
            profileCardMenu.hidden = true;
            const target = profileCardTarget;
            if (!target) return;
            reportTarget = { type: "user", id: target.peerId };
            reportModalTitle.textContent = `${target.name}님 신고`;
            reportReasonSelect.value = "";
            reportDetail.value = "";
            reportMessageOverlay.style.display = "flex";
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
    closeSettingsMenu();
    accountSettingsOverlay.style.display = "flex";
});

let currentUpdateVersion = "";

function updateUpdateNoticeBadge() {
    if (!currentUpdateVersion) return;
    const seenVersion = localStorage.getItem("seenUpdateVersion");
    updateNoticeBadge.style.display =
        seenVersion === currentUpdateVersion ? "none" : "inline-block";
}

function renderUpdateHistory(updates, target = updateHistoryList) {
    target.replaceChildren();
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
        target.append(item);
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
            updateHistoryList.textContent = "최근 업데이트 내역이 없습니다.";
            return;
        }

        currentUpdateVersion = result.latest_version;
        renderUpdateHistory(result.updates);
        updateUpdateNoticeBadge();
    } catch (error) {
        updateHistoryList.textContent = "업데이트 내역을 불러오지 못했습니다.";
    }
}

async function openPreviousUpdates() {
    previousUpdatesOverlay.style.display = "flex";
    previousUpdatesList.textContent = "이전 업데이트 내역을 불러오는 중입니다.";

    try {
        const response = await fetch("/api/updates?all=1");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error("이전 업데이트 내역 없음");

        if (!result.updates.length) {
            previousUpdatesList.textContent = "표시할 이전 업데이트 내역이 없습니다.";
            return;
        }
        renderUpdateHistory(result.updates, previousUpdatesList);
    } catch (error) {
        previousUpdatesList.textContent = "이전 업데이트 내역을 불러오지 못했습니다.";
    }
}

notificationSettingsItem.addEventListener("click", function () {
    closeSettingsMenu();
    notificationSettingsOverlay.style.display = "flex";

    if (currentUpdateVersion) {
        localStorage.setItem("seenUpdateVersion", currentUpdateVersion);
    }
    updateUpdateNoticeBadge();
});

notificationSettingsCloseBtn.addEventListener("click", function () {
    notificationSettingsOverlay.style.display = "none";
});

browserNotificationToggle.checked = localStorage.getItem("browserNotifications") === "enabled" && "Notification" in window && Notification.permission === "granted";

function urlBase64ToUint8Array(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = atob(base64);
    return Uint8Array.from(rawData, character => character.charCodeAt(0));
}

async function registerPushSubscription() {
    if (!("serviceWorker" in navigator)) return;
    const config = await fetch("/api/push-config").then(response => response.json());
    if (!config.enabled || !config.publicKey) return;
    const registration = await navigator.serviceWorker.register("/static/push-sw.js");
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
        subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(config.publicKey) });
    }
    await fetch("/api/push-subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(subscription) });
}

browserNotificationToggle.addEventListener("change", async function () {
    if (!("Notification" in window)) {
        showToast("이 브라우저는 알림을 지원하지 않습니다.", "error");
        this.checked = false;
        return;
    }
    if (this.checked) {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
            this.checked = false;
            localStorage.removeItem("browserNotifications");
            showToast("브라우저 알림 권한이 허용되지 않았습니다.", "error");
            return;
        }
        localStorage.setItem("browserNotifications", "enabled");
        try { await registerPushSubscription(); } catch (error) { console.warn("푸시 구독 등록 실패", error); }
        showToast("브라우저 알림을 켰습니다.");
    } else {
        localStorage.removeItem("browserNotifications");
    }
});

function showBrowserNotification(conversationId) {
    if (document.visibilityState === "visible" || localStorage.getItem("browserNotifications") !== "enabled") return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const friend = friends.find(function (item) { return item.id === conversationId; });
    if (!friend || friend.isMuted) return;
    new Notification(friend.name, { body: friend.message || "새 메시지가 도착했습니다.", icon: "/static/favicon-180x180.png" });
}

if (browserNotificationToggle.checked) {
    registerPushSubscription().catch(function () {});
}

previousUpdatesBtn.addEventListener("click", openPreviousUpdates);
previousUpdatesCloseBtn.addEventListener("click", function () {
    previousUpdatesOverlay.style.display = "none";
});
previousUpdatesOverlay.addEventListener("click", function (event) {
    if (event.target === previousUpdatesOverlay) previousUpdatesOverlay.style.display = "none";
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
        loadSupportInquiryHistory();
    } catch (error) {
        supportInquiryResult.className = "support-inquiry-result error";
        supportInquiryResult.textContent = error.message || "문의 전송에 실패했습니다. 잠시 후 다시 시도해주세요.";
    } finally {
        supportInquirySubmitBtn.disabled = false;
        supportInquirySubmitBtn.textContent = "문의 전송하기";
    }
});

async function loadSupportInquiryHistory() {
    try {
        const response = await fetch("/api/support-inquiries/history");
        const inquiries = await response.json();
        if (!response.ok) throw new Error("문의 내역을 불러오지 못했습니다.");
        supportInquiryHistory.innerHTML = inquiries.length ? inquiries.map(function (inquiry) {
            const statusLabel = inquiry.status === "pending" ? "답변 대기" : inquiry.status === "answered" ? "답변 완료" : "처리 완료";
            const editable = inquiry.status === "pending";
            return `<article class="support-history-item">
                <div class="support-history-head"><strong>${statusLabel}</strong><span>${escapeHTML((inquiry.created_at || "").slice(0, 16))}</span></div>
                <p>${escapeHTML(inquiry.message)}</p>
                ${inquiry.attachment_url ? `<a href="${escapeHTML(inquiry.attachment_url)}" target="_blank" rel="noopener">첨부 파일 보기</a>` : ""}
                ${inquiry.admin_reply ? `<div class="support-admin-reply"><strong><i class="fa-solid fa-reply"></i> 관리자 답변</strong><p>${escapeHTML(inquiry.admin_reply)}</p></div>` : ""}
                <div class="support-history-actions">${editable ? `<button type="button" data-edit-inquiry="${inquiry.id}">수정</button>` : ""}<button type="button" data-delete-inquiry="${inquiry.id}" class="danger">삭제</button></div>
            </article>`;
        }).join("") : '<p class="support-history-empty">보낸 문의가 없습니다.</p>';
    } catch (error) {
        supportInquiryHistory.innerHTML = '<p class="support-history-empty">문의 내역을 불러오지 못했습니다.</p>';
    }
}

let unreadModerationWarnings = [];

function showNextModerationWarning() {
    const warning = unreadModerationWarnings[0];
    if (!warning) {
        moderationWarningOverlay.style.display = "none";
        return;
    }
    moderationWarningReason.textContent = warning.reason || "운영 정책 위반";
    moderationWarningDate.textContent = `처리 일시 · ${(warning.created_at || "").slice(0, 16)}`;
    moderationWarningAcknowledge.textContent = unreadModerationWarnings.length > 1
        ? `확인했습니다 (${unreadModerationWarnings.length})`
        : "확인했습니다";
    moderationWarningOverlay.style.display = "flex";
}

async function loadUnreadModerationWarnings() {
    try {
        const response = await fetch("/api/moderation/warnings");
        if (!response.ok) return;
        unreadModerationWarnings = await response.json();
        showNextModerationWarning();
    } catch (error) {
        // 경고 안내 조회 실패가 채팅 화면 사용을 막으면 안 된다.
    }
}

async function loadModerationWarningHistory() {
    try {
        const response = await fetch("/api/moderation/warnings/history");
        const warnings = await response.json();
        if (!response.ok) throw new Error("운영 안내를 불러오지 못했습니다.");
        moderationWarningHistory.innerHTML = warnings.length ? warnings.map(function (warning) {
            return `<article class="support-history-item moderation-history-item"><div class="support-history-head"><strong><i class="fa-solid fa-triangle-exclamation"></i> 운영 경고</strong><span>${escapeHTML((warning.created_at || "").slice(0, 16))}</span></div><p>${escapeHTML(warning.reason || "운영 정책 위반")}</p></article>`;
        }).join("") : '<p class="support-history-empty">받은 운영 안내가 없습니다.</p>';
    } catch (error) {
        moderationWarningHistory.innerHTML = '<p class="support-history-empty">운영 안내를 불러오지 못했습니다.</p>';
    }
}

moderationWarningAcknowledge.addEventListener("click", async function () {
    const warning = unreadModerationWarnings[0];
    if (!warning) return;
    moderationWarningAcknowledge.disabled = true;
    try {
        const response = await fetch(`/api/moderation/warnings/${warning.id}/acknowledge`, { method: "POST" });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "경고 확인 처리에 실패했습니다.");
        unreadModerationWarnings.shift();
        showNextModerationWarning();
    } catch (error) {
        showToast(error.message || "경고 확인 처리에 실패했습니다.", "error");
    } finally {
        moderationWarningAcknowledge.disabled = false;
    }
});

supportInquiryHistory.addEventListener("click", async function (event) {
    const editId = event.target.dataset.editInquiry;
    const deleteId = event.target.dataset.deleteInquiry;
    if (editId) {
        const item = event.target.closest(".support-history-item");
        const previous = item.querySelector(".support-history-head").nextElementSibling.textContent;
        const message = prompt("문의 내용을 수정하세요.", previous);
        if (message === null) return;
        const response = await fetch(`/api/support-inquiries/${editId}`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message})});
        const result = await response.json();
        if (!response.ok || !result.success) return showToast(result.error || "수정에 실패했습니다.", "error");
        showToast("문의 내용을 수정했습니다.");
    } else if (deleteId) {
        if (!confirm("이 문의 내역을 삭제할까요?")) return;
        const response = await fetch(`/api/support-inquiries/${deleteId}`, {method:"DELETE"});
        const result = await response.json();
        if (!response.ok || !result.success) return showToast(result.error || "삭제에 실패했습니다.", "error");
        showToast("문의 내역을 삭제했습니다.");
    } else return;
    loadSupportInquiryHistory();
});

/* 인증 성공·재발송·만료 때 동일하게 사용할 3분 카운트다운 처리다. */
function stopInlineVerificationTimer(timerElement, hide = false) {
    if (timerElement._interval) clearInterval(timerElement._interval);
    timerElement._interval = null;
    if (hide) {
        timerElement.textContent = "";
        timerElement.hidden = true;
    }
}

function startInlineVerificationTimer(timerElement, onExpire) {
    stopInlineVerificationTimer(timerElement);
    let remaining = 180;
    timerElement.hidden = false;

    function tick() {
        const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
        const seconds = String(remaining % 60).padStart(2, "0");
        timerElement.textContent = `${minutes}:${seconds}`;
        if (remaining <= 0) {
            stopInlineVerificationTimer(timerElement);
            timerElement.textContent = "만료됨";
            onExpire();
            return;
        }
        remaining -= 1;
    }

    tick();
    timerElement._interval = setInterval(tick, 1000);
}

/* ==============================================================
 * 계정 복구: 로그인 화면과 같은 Flask API를 재사용한다.
 * 화면만 다를 뿐, 인증번호 발송·검증 규칙은 서버 한 곳에서 관리한다.
 * ============================================================ */
helpFindUsernameBtn.addEventListener("click", async function () {
    const email = helpFindUsernameEmail.value.trim();
    if (!email) {
        helpFindUsernameResult.textContent = "가입 이메일 주소를 입력해주세요.";
        helpFindUsernameEmail.focus();
        return;
    }

    helpFindUsernameBtn.disabled = true;
    helpFindUsernameBtn.textContent = "발송 중...";
    try {
        const response = await fetch("/api/find-username", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email })
        });
        const result = await response.json();
        helpFindUsernameResult.textContent = result.success
            ? result.message
            : (result.error || "아이디 안내 이메일 전송에 실패했습니다.");
    } catch (error) {
        helpFindUsernameResult.textContent = "서버와 통신 중 문제가 발생했습니다.";
    } finally {
        helpFindUsernameBtn.disabled = false;
        helpFindUsernameBtn.textContent = "아이디 안내 메일 보내기";
    }
});

helpResetCodeBtn.addEventListener("click", async function () {
    const email = helpResetEmail.value.trim();
    if (!email) {
        helpResetResult.textContent = "가입 이메일 주소를 입력해주세요.";
        helpResetEmail.focus();
        return;
    }

    helpResetCodeBtn.disabled = true;
    helpResetCodeBtn.textContent = "발송 중...";
    try {
        const response = await fetch("/api/password-reset/send-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "인증번호 이메일 전송에 실패했습니다.");
        helpResetResult.textContent = result.message || result.error || "인증번호를 보냈습니다.";
        helpResetFields.hidden = false;
        helpResetCodeSent = true;
        helpResetVerified = false;
        helpResetCode.value = "";
        helpResetCode.readOnly = false;
        helpResetVerificationStatus.textContent = "";
        helpResetVerificationStatus.className = "inline-verification-status";
        helpResetVerifyBtn.classList.remove("verified");
        helpResetVerifyBtn.textContent = "인증하기";
        helpResetVerifyBtn.disabled = false;
        startInlineVerificationTimer(helpResetCodeTimer, function () {
            helpResetCodeSent = false;
            helpResetVerificationStatus.textContent = "인증번호가 만료되었습니다. 다시 요청해주세요.";
            helpResetVerificationStatus.className = "inline-verification-status error";
            helpResetVerifyBtn.disabled = true;
        });
        helpResetCode.focus();
    } catch (error) {
        helpResetResult.textContent = error.message || "서버와 통신 중 문제가 발생했습니다.";
    } finally {
        helpResetCodeBtn.disabled = false;
        helpResetCodeBtn.textContent = "인증번호 받기";
    }
});

helpResetVerifyBtn.addEventListener("click", async function () {
    const email = helpResetEmail.value.trim();
    const code = helpResetCode.value.trim();
    if (!helpResetCodeSent || !email || !code) {
        helpResetVerificationStatus.textContent = "이메일과 인증번호 6자리를 입력해주세요.";
        helpResetVerificationStatus.className = "inline-verification-status error";
        return;
    }

    helpResetVerifyBtn.disabled = true;
    helpResetVerifyBtn.textContent = "확인 중...";
    try {
        const response = await fetch("/api/password-reset/verify-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, code })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "인증에 실패했습니다.");

        helpResetVerified = true;
        helpResetCode.readOnly = true;
        stopInlineVerificationTimer(helpResetCodeTimer, true);
        helpResetVerificationStatus.textContent = "✓ 이메일 인증이 완료되었습니다.";
        helpResetVerificationStatus.className = "inline-verification-status success";
        helpResetVerifyBtn.classList.add("verified");
        helpResetVerifyBtn.textContent = "인증 완료";
    } catch (error) {
        helpResetVerified = false;
        helpResetVerificationStatus.textContent = error.message || "인증에 실패했습니다.";
        helpResetVerificationStatus.className = "inline-verification-status error";
        helpResetVerifyBtn.textContent = "인증하기";
    } finally {
        helpResetVerifyBtn.disabled = helpResetVerified;
    }
});

helpResetEmail.addEventListener("input", function () {
    if (!helpResetCodeSent) return;
    helpResetCodeSent = false;
    helpResetVerified = false;
    stopInlineVerificationTimer(helpResetCodeTimer, true);
    helpResetFields.hidden = true;
});

helpResetSubmitBtn.addEventListener("click", async function () {
    const email = helpResetEmail.value.trim();
    const code = helpResetCode.value.trim();
    const newPassword = helpResetNewPassword.value;
    if (!code || !newPassword) {
        helpResetResult.textContent = "인증번호와 새 비밀번호를 모두 입력해주세요.";
        return;
    }
    if (!helpResetVerified) {
        helpResetResult.textContent = "인증번호 인증을 먼저 완료해주세요.";
        return;
    }

    helpResetSubmitBtn.disabled = true;
    helpResetSubmitBtn.textContent = "변경 중...";
    try {
        const response = await fetch("/api/password-reset/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, code, new_password: newPassword })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "비밀번호 변경에 실패했습니다.");

        helpResetResult.textContent = "비밀번호가 변경되었습니다.";
        helpResetCode.value = "";
        helpResetNewPassword.value = "";
        helpResetCodeSent = false;
        helpResetVerified = false;
        helpResetCode.readOnly = false;
        helpResetVerifyBtn.classList.remove("verified");
        helpResetVerifyBtn.textContent = "인증하기";
    } catch (error) {
        helpResetResult.textContent = error.message || "서버와 통신 중 문제가 발생했습니다.";
    } finally {
        helpResetSubmitBtn.disabled = false;
        helpResetSubmitBtn.textContent = "비밀번호 변경";
    }
});

async function loadPublicNotices() {
    try {
        const response = await fetch("/api/notices");
        const notices = await response.json();
        publicNoticeList.innerHTML = notices.length
            ? notices.map(function (notice) { return `<article class="update-history-item"><div><strong>${escapeHTML(notice.title)}</strong><span>${escapeHTML(notice.created_at.slice(0, 10))}</span></div><p>${escapeHTML(notice.content)}</p></article>`; }).join("")
            : '<p style="font-size:13px;">현재 등록된 공지사항이 없습니다.</p>';
    } catch (error) {
        publicNoticeList.innerHTML = '<p style="font-size:13px;">공지사항을 불러오지 못했습니다.</p>';
    }
}

let myReviewId = null;
function setReviewComposeMode(myReview) {
    myReviewId = myReview ? myReview.id : null;
    reviewComposeHint.hidden = !myReview;
    reviewDeleteBtn.hidden = !myReview;
    reviewSubmitBtn.textContent = myReview ? "리뷰 수정" : "리뷰 등록";
    if (myReview) {
        reviewRating.value = String(myReview.rating);
        reviewContent.value = myReview.content;
    }
}
async function loadReviews() {
    try {
        const reviews = await fetch("/api/reviews").then(response => response.json());
        reviewList.innerHTML = reviews.length ? reviews.map(review => `<article class="update-history-item${review.isMine ? " review-list-item-mine" : ""}"><div><strong>${"★".repeat(review.rating)}${"☆".repeat(5-review.rating)} · ${escapeHTML(review.display_name || review.username)}${review.isMine ? " (나)" : ""}</strong><span>${escapeHTML(review.created_at.slice(0,10))}</span></div><p>${escapeHTML(review.content)}</p>${review.admin_reply ? `<p><strong>관리자 답장</strong><br>${escapeHTML(review.admin_reply)}</p>` : ""}</article>`).join("") : "<p>첫 번째 리뷰를 남겨주세요.</p>";
        setReviewComposeMode(reviews.find(review => review.isMine) || null);
    } catch (error) { reviewList.innerHTML=""; }
}
reviewSubmitBtn.addEventListener("click", async function () {
    const rating = Number(reviewRating.value);
    const content = reviewContent.value.trim();
    const response = myReviewId
        ? await fetch(`/api/reviews/${myReviewId}`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({rating, content})})
        : await fetch("/api/reviews", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({rating, content})});
    const result = await response.json();
    if (!response.ok || !result.success) return showToast(result.error || "리뷰 저장에 실패했습니다.", "error");
    loadReviews(); showToast(myReviewId ? "리뷰를 수정했습니다." : "리뷰를 등록했습니다.");
});
reviewDeleteBtn.addEventListener("click", async function () {
    if (!myReviewId || !confirm("작성한 리뷰를 삭제할까요?")) return;
    const response = await fetch(`/api/reviews/${myReviewId}`, {method:"DELETE"});
    const result = await response.json();
    if (!response.ok || !result.success) return showToast(result.error || "리뷰 삭제에 실패했습니다.", "error");
    reviewRating.value=""; reviewContent.value=""; loadReviews(); showToast("리뷰를 삭제했습니다.");
});

        helpItem.addEventListener("click", function () {
            closeSettingsMenu();
            loadPublicNotices();
            loadSupportInquiryHistory();
            loadModerationWarningHistory();
            helpOverlay.style.display = "flex";
        });
        helpCloseBtn.addEventListener("click", function () {
            helpOverlay.style.display = "none";
        });

        reviewsItem.addEventListener("click", function () {
            closeSettingsMenu();
            loadReviews();
            reviewsOverlay.style.display = "flex";
        });
        reviewsCloseBtn.addEventListener("click", function () { reviewsOverlay.style.display = "none"; });
        reviewsOverlay.addEventListener("click", function (event) { if (event.target === reviewsOverlay) reviewsOverlay.style.display = "none"; });

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
        showToast("아이디가 변경되었습니다.");
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

    sendEmailCodeBtn.disabled = true;
    sendEmailCodeBtn.textContent = "발송 중...";
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

        accountEmailCodeSent = true;
        accountEmailVerified = false;
        emailCodeInput.value = "";
        emailCodeInput.readOnly = false;
        emailCodeStatus.textContent = "인증번호를 이메일로 보냈습니다.";
        emailCodeStatus.className = "inline-verification-status";
        verifyEmailCodeBtn.classList.remove("verified");
        verifyEmailCodeBtn.textContent = "인증하기";
        verifyEmailCodeBtn.disabled = false;
        startInlineVerificationTimer(emailCodeTimer, function () {
            accountEmailCodeSent = false;
            emailCodeStatus.textContent = "인증번호가 만료되었습니다. 다시 요청해주세요.";
            emailCodeStatus.className = "inline-verification-status error";
            verifyEmailCodeBtn.disabled = true;
        });
        showToast("인증 코드를 이메일로 전송했습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    } finally {
        sendEmailCodeBtn.disabled = false;
        sendEmailCodeBtn.textContent = "인증코드 받기";
    }
});

verifyEmailCodeBtn.addEventListener("click", async function () {
    const email = newEmailInput.value.trim();
    const code = emailCodeInput.value.trim();
    if (!accountEmailCodeSent || !email || !code) {
        emailCodeStatus.textContent = "이메일과 인증번호 6자리를 입력해주세요.";
        emailCodeStatus.className = "inline-verification-status error";
        return;
    }

    verifyEmailCodeBtn.disabled = true;
    verifyEmailCodeBtn.textContent = "확인 중...";
    try {
        const response = await fetch("/api/verify-email-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, code })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "인증에 실패했습니다.");

        accountEmailVerified = true;
        emailCodeInput.readOnly = true;
        stopInlineVerificationTimer(emailCodeTimer, true);
        emailCodeStatus.textContent = "✓ 이메일 인증이 완료되었습니다.";
        emailCodeStatus.className = "inline-verification-status success";
        verifyEmailCodeBtn.classList.add("verified");
        verifyEmailCodeBtn.textContent = "인증 완료";
    } catch (err) {
        accountEmailVerified = false;
        emailCodeStatus.textContent = err.message || "인증에 실패했습니다.";
        emailCodeStatus.className = "inline-verification-status error";
        verifyEmailCodeBtn.textContent = "인증하기";
    } finally {
        verifyEmailCodeBtn.disabled = accountEmailVerified;
    }
});

newEmailInput.addEventListener("input", function () {
    if (!accountEmailCodeSent) return;
    accountEmailCodeSent = false;
    accountEmailVerified = false;
    stopInlineVerificationTimer(emailCodeTimer, true);
    emailCodeInput.value = "";
    emailCodeInput.readOnly = false;
    emailCodeStatus.textContent = "이메일이 변경되어 인증번호를 다시 받아야 합니다.";
    emailCodeStatus.className = "inline-verification-status";
    verifyEmailCodeBtn.classList.remove("verified");
    verifyEmailCodeBtn.textContent = "인증하기";
    verifyEmailCodeBtn.disabled = false;
});

saveEmailBtn.addEventListener("click", async function () {
    if (!accountEmailVerified) {
        showAlert("인증번호 인증을 먼저 완료해주세요.");
        return;
    }
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
        accountEmailCodeSent = false;
        accountEmailVerified = false;
        emailCodeInput.readOnly = false;
        verifyEmailCodeBtn.classList.remove("verified");
        verifyEmailCodeBtn.textContent = "인증하기";
        emailCodeStatus.textContent = "";
        showToast("이메일이 변경되었습니다.");
    } catch (err) {
        showAlert("서버와 통신 중 문제가 발생했습니다.");
    }
});

savePasswordBtn.addEventListener("click", async function () {
    if (newPasswordInput.value !== newPasswordConfirmationInput.value) {
        showAlert("새 비밀번호 확인이 일치하지 않습니다.");
        newPasswordConfirmationInput.focus();
        return;
    }

    try {
        const response = await fetch("/api/account/password", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: currentPasswordInput.value,
                new_password: newPasswordInput.value,
                password_confirmation: newPasswordConfirmationInput.value
            })
        });
        const result = await response.json();

        if (!result.success) {
            showAlert(result.error);
            return;
        }

        currentPasswordInput.value = "";
        newPasswordInput.value = "";
        newPasswordConfirmationInput.value = "";
        showToast("비밀번호가 변경되었습니다.");
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

/* ==============================================================
 * 원형 프로필/그룹 사진 편집기
 * 원본을 임의로 축소하지 않고, 사용자가 고른 영역만 512px 정사각형으로 저장한다.
 * ============================================================ */
const CROP_VIEWPORT_SIZE = 320;
const cropState = {
    target: null,
    image: null,
    scale: 1,
    baseScale: 1,
    x: 0,
    y: 0,
    dragging: false,
    pointerX: 0,
    pointerY: 0,
};

function constrainCropPosition() {
    const renderedWidth = cropState.image.naturalWidth * cropState.scale;
    const renderedHeight = cropState.image.naturalHeight * cropState.scale;
    cropState.x = Math.min(0, Math.max(CROP_VIEWPORT_SIZE - renderedWidth, cropState.x));
    cropState.y = Math.min(0, Math.max(CROP_VIEWPORT_SIZE - renderedHeight, cropState.y));
}

function renderCropPreview() {
    if (!cropState.image) return;
    const context = imageCropCanvas.getContext("2d");
    context.clearRect(0, 0, CROP_VIEWPORT_SIZE, CROP_VIEWPORT_SIZE);
    context.fillStyle = "#eef2f7";
    context.fillRect(0, 0, CROP_VIEWPORT_SIZE, CROP_VIEWPORT_SIZE);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(
        cropState.image,
        cropState.x,
        cropState.y,
        cropState.image.naturalWidth * cropState.scale,
        cropState.image.naturalHeight * cropState.scale
    );
}

function closeImageCropper() {
    cropState.target = null;
    cropState.image = null;
    cropState.dragging = false;
    imageCropOverlay.style.display = "none";
}

function openImageCropper(file, target) {
    const supportedExtension = /\.(jpe?g|jfif|png|webp|gif)$/i.test(file.name || "");
    if (!file.type.startsWith("image/") && !supportedExtension) {
        showAlert("이미지 파일만 선택할 수 있습니다.");
        return;
    }

    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = function () {
        URL.revokeObjectURL(objectUrl);
        cropState.target = target;
        cropState.image = image;
        cropState.baseScale = Math.max(CROP_VIEWPORT_SIZE / image.naturalWidth, CROP_VIEWPORT_SIZE / image.naturalHeight);
        cropState.scale = cropState.baseScale;
        cropState.x = (CROP_VIEWPORT_SIZE - image.naturalWidth * cropState.scale) / 2;
        cropState.y = (CROP_VIEWPORT_SIZE - image.naturalHeight * cropState.scale) / 2;
        imageCropZoom.value = "100";
        imageCropTitle.textContent = target === "group" ? "그룹 사진 조절" : "프로필 사진 조절";
        renderCropPreview();
        imageCropOverlay.style.display = "flex";
    };
    image.onerror = function () {
        URL.revokeObjectURL(objectUrl);
        showAlert("사진을 읽지 못했습니다. 다른 이미지 파일을 선택해주세요.");
    };
    image.src = objectUrl;
}

async function uploadCroppedGroupPhoto(imageData) {
    const response = await fetch(`/api/conversations/${currentConversationID}/photo`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: imageData })
    });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || "그룹 사진을 저장하지 못했습니다.");
    groupPhotoImg.src = result.profile_image;
}

imageCropZoom.addEventListener("input", function () {
    if (!cropState.image) return;
    const oldScale = cropState.scale;
    const sourceCenterX = (CROP_VIEWPORT_SIZE / 2 - cropState.x) / oldScale;
    const sourceCenterY = (CROP_VIEWPORT_SIZE / 2 - cropState.y) / oldScale;
    cropState.scale = cropState.baseScale * (Number(imageCropZoom.value) / 100);
    cropState.x = CROP_VIEWPORT_SIZE / 2 - sourceCenterX * cropState.scale;
    cropState.y = CROP_VIEWPORT_SIZE / 2 - sourceCenterY * cropState.scale;
    constrainCropPosition();
    renderCropPreview();
});

imageCropCanvas.addEventListener("pointerdown", function (event) {
    if (!cropState.image) return;
    cropState.dragging = true;
    cropState.pointerX = event.clientX;
    cropState.pointerY = event.clientY;
    imageCropCanvas.setPointerCapture(event.pointerId);
});

imageCropCanvas.addEventListener("pointermove", function (event) {
    if (!cropState.dragging || !cropState.image) return;
    const bounds = imageCropCanvas.getBoundingClientRect();
    const displayScale = CROP_VIEWPORT_SIZE / bounds.width;
    cropState.x += (event.clientX - cropState.pointerX) * displayScale;
    cropState.y += (event.clientY - cropState.pointerY) * displayScale;
    cropState.pointerX = event.clientX;
    cropState.pointerY = event.clientY;
    constrainCropPosition();
    renderCropPreview();
});

function finishCropDrag(event) {
    cropState.dragging = false;
    if (imageCropCanvas.hasPointerCapture(event.pointerId)) imageCropCanvas.releasePointerCapture(event.pointerId);
}
imageCropCanvas.addEventListener("pointerup", finishCropDrag);
imageCropCanvas.addEventListener("pointercancel", finishCropDrag);

imageCropApplyBtn.addEventListener("click", async function () {
    if (!cropState.image || !cropState.target) return;
    const outputSize = 512;
    const output = document.createElement("canvas");
    output.width = outputSize;
    output.height = outputSize;
    const context = output.getContext("2d");
    const ratio = outputSize / CROP_VIEWPORT_SIZE;
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.fillStyle = "#eef2f7";
    context.fillRect(0, 0, outputSize, outputSize);
    context.drawImage(
        cropState.image,
        cropState.x * ratio,
        cropState.y * ratio,
        cropState.image.naturalWidth * cropState.scale * ratio,
        cropState.image.naturalHeight * cropState.scale * ratio
    );
    const imageData = output.toDataURL("image/jpeg", 0.94);
    const target = cropState.target;
    closeImageCropper();

    try {
        if (target === "profile") {
            pendingProfileImageData = imageData;
            pendingProfileImageRemoval = false;
            profileModalPic.innerHTML = `<img src="${imageData}" style="width:100%; height:100%; border-radius:50%; object-fit:cover;">`;
            return;
        }
        await uploadCroppedGroupPhoto(imageData);
        showToast("그룹 사진이 변경되었습니다.");
    } catch (error) {
        showAlert(error.message || "사진 저장 중 문제가 발생했습니다.");
    }
});

imageCropCloseBtn.addEventListener("click", closeImageCropper);
imageCropCancelBtn.addEventListener("click", closeImageCropper);
imageCropOverlay.addEventListener("click", function (event) {
    if (event.target === imageCropOverlay) closeImageCropper();
});

changeGroupPhotoBtn.addEventListener("click", function () {
    groupPhotoInput.click();
});

groupPhotoInput.addEventListener("change", function () {
    const file = groupPhotoInput.files[0];
    if (!file) return;
    openImageCropper(file, "group");
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

profileModalPic.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        profileImageInput.click();
    }
});

profileImageInput.addEventListener("change", function () {
    const file = profileImageInput.files[0];
    if (!file) return;
    openImageCropper(file, "profile");
    profileImageInput.value = "";
});

removeProfilePicBtn.addEventListener("click", function () {
    showConfirm("프로필 사진을 삭제하시겠습니까?", async function (confirmRemove) {
        if (!confirmRemove) return;
        pendingProfileImageData = null;
        pendingProfileImageRemoval = true;
        profileModalPic.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
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
    if (!currentConversationID) {
        showAlert("먼저 채팅방을 선택해주세요.");
        return;
    }
    setComposerBusy(true);
    const formData = new FormData();
    formData.append("video", file);

    try {
        const response = await fetch(`/api/conversations/${currentConversationID}/messages/video`, {
            method: "POST",
            body: formData
        });
        const result = await response.json();

        if (!response.ok || !result.success) throw new Error(result.error || "동영상을 보내지 못했습니다.");

        await readMessages();
        updateFriendPreviewFromServer();
        showToast("동영상을 보냈습니다.");
    } catch (err) {
        showToast(err.message || "동영상 전송 중 문제가 발생했습니다.", "error");
    } finally {
        setComposerBusy(false);
        setTimeout(function () { input.focus(); }, 10);
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
            showBrowserNotification(data.conversationId);
            updateChatHeader(getCurrentFriend()); 
            readFriends();
            updateBlockState();
        });
        socket.on("chess_invite", async function () {
            if (!window.CLOUD_CHESS_UI_ENABLED) return;
            await loadFriendRequests();
            showToast("메시지함에 체스 대국 초대가 도착했습니다.", "info");
        });

        // 친구 요청 도착/수락/거절, 차단/차단해제 — 친구 관계가 바뀔 때마다 여기로 신호가 옴
        socket.on("friend_updated", async function () {
            await loadFriendDirectory();
            await loadFriends();
            readFriends();
            updateBlockState();
            await loadFriendRequests();
            if (friendPanel.classList.contains("open")) {
                renderFriendPanelList();
            }
        });

        // 상대방의 접속 상태가 바뀌면 목록의 온라인 표시를 바로 갱신한다.
        socket.on("presence_updated", async function () {
            await loadFriends();
        });

        socket.on("account_suspended", function (data) {
            showAlert(`이용이 정지되었습니다. 사유: ${data.reason || "운영 정책 위반"}`, function () {
                window.location.href = "/login";
            });
        });

        socket.on("account_deleted", function () {
            showAlert("계정이 삭제되었습니다.", function () {
                window.location.href = "/login";
            });
        });

        /* ======================================================
         * 초기 렌더링
         * ====================================================== */

        readMessages();
        Promise.all([loadFriends(), loadFriendDirectory()]).then(updateBlockState);
        loadFriendRequests();
        loadUpdateHistory();
        loadUnreadModerationWarnings();
