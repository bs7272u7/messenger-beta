/*
 * 채팅 화면(index.html)의 동작을 모두 담은 클라이언트 스크립트.
 *
 * 서버 데이터가 기준(source of truth)이고, 이 파일의 chats / friends 는
 * 화면을 빠르게 다시 그리기 위한 임시 캐시일 뿐이다. 값을 바꿀 때는
 * "API 호출 → 서버 응답 → 캐시 갱신 → 화면 다시 그리기" 순서를 따른다.
 *
 * 구성: fetch 보정 → 상태 변수 → 표시용 헬퍼 → DOM 참조 → 화면 열고 닫기
 *       → 설정 메뉴·테마 → 메시지 전송/렌더링 → 친구·그룹 관리 → 프로필 → 소켓 이벤트
 */

        // ============================================================
        // fetch 보정: CSRF 토큰 첨부와 세션 만료 처리
        // ============================================================
        const _originalFetch = window.fetch;
        // 서버가 템플릿(meta 태그)에 넣어 준 CSRF 토큰. 상태를 바꾸는 요청에 헤더로 실어 보낸다.
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        // 모든 fetch 호출을 감싼다. 호출하는 쪽 코드는 토큰이나 세션 만료를 신경 쓰지 않아도 된다.
        window.fetch = async function (...args) {
            const requestOptions = args[1] || {};
            const method = (requestOptions.method || (args[0] instanceof Request && args[0].method) || "GET").toUpperCase();
            // 읽기 전용(GET)이 아닌 요청에만 X-CSRF-Token 헤더를 붙인다.
            if (csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
                const headers = new Headers(requestOptions.headers || (args[0] instanceof Request ? args[0].headers : undefined));
                headers.set("X-CSRF-Token", csrfToken);
                args[1] = { ...requestOptions, headers };
            }
            const response = await _originalFetch(...args);
            // 401은 로그인이 풀렸다는 뜻이다. 어느 화면에서든 로그인 페이지로 되돌린다.
            if (response.status === 401) {
                window.location.href = "/login";
            }
            return response;
        };

        // ============================================================
        // 상태 변수
        // ============================================================
        let currentConversationID = null;
        // 메시지 메뉴(우클릭)가 가리키는 메시지와 그 ID.
        // 주의: selectedIndex와 editingIndex는 이름과 달리 배열 인덱스가 아니라 서버의 메시지 ID(chat.id)를 담는다.
        let selectedMessage = null;
        let selectedIndex = -1;
        // 수정 중인 메시지의 ID. null이면 수정 모드가 아니다.
        let editingIndex = null;
        // 답장 대상 메시지. null이면 답장 중이 아니다.
        let replyMessage = null;
        // 대화 내 검색: 검색어, 일치한 메시지 요소 목록, 현재 가리키는 일치 항목 번호.
        let searchQuery = "";
        let searchMatches = [];
        let currentMatchIndex = 0;

        // ============================================================
        // 데이터 로드 (서버 → 메모리)
        // ============================================================
        // 대화방 ID → 메시지 배열. 서버에서 받은 메시지를 보관하는 캐시다.
        const chats = {};
        // 대화방 목록(서버의 /api/conversations 응답). 이름은 friends지만 그룹 대화방도 들어 있다.
        let friends = [];
        // 실제 친구 목록(/api/friends). 채팅방을 숨겼는지와 무관하게 친구 관계를 나타낸다.
        let friendDirectory = [];
        // 메시지 새로고침이 겹쳐 실행되지 않게 하는 용도. 진행 중인 요청(Promise)과 마지막 새로고침 시각을 보관한다.
        let messageRefreshPromise = null;
        let lastMessageRefreshAt = 0;
        // 프로필 편집창에서 고른 새 사진(저장 전)과 삭제 예약 여부, 되돌리기용 원래 HTML.
        let pendingProfileImageData = null;
        let pendingProfileImageRemoval = false;
        let savedProfileImageHTML = "";

        /**
         * 서버에서 대화방 목록을 가져와 왼쪽 목록을 다시 그린다.
         */
        async function loadFriends() {
            const response  = await fetch("/api/conversations");
            friends = await response.json();
            readFriends();
        }

        /**
         * 서버에서 친구 목록을 가져와 friendDirectory에 저장한다(화면은 다시 그리지 않는다).
         */
        async function loadFriendDirectory() {
            const response = await fetch("/api/friends");
            const result = await response.json();
            friendDirectory = result.friends || [];
        }
            

        // ============================================================
        // 저장/시간/친구 조회 헬퍼
        // ============================================================
        /**
         * 현재 화면 언어에 맞는 날짜·시간 표시 로케일(예: 'ko-KR')을 돌려준다.
         */
        function getDisplayLocale() {
            const language = window.CloudI18n ? window.CloudI18n.getLanguage() : "ko";
            return { ko: "ko-KR", en: "en-US", zh: "zh-CN", ja: "ja-JP", es: "es-ES" }[language] || "ko-KR";
        }

        /**
         * 메시지 시각을 사용자의 기기 시간대로 보여 준다.
         *
         * 서버는 UTC 밀리초(sentAt)만 정확한 값으로 보관한다. sentAt이 없는 옛 메시지는 저장된 시간 문자열을 그대로 쓴다.
         */
        function formatMessageTime(chat) {
            if (!chat || !chat.sentAt) return (chat && chat.time) || "";
            return new Intl.DateTimeFormat(getDisplayLocale(), { hour: "numeric", minute: "2-digit" }).format(new Date(chat.sentAt));
        }

        /**
         * 메시지 날짜를 사용자의 기기 시간대로 보여 준다. sentAt이 없는 옛 메시지는 저장된 날짜 문자열을 쓴다.
         */
        function formatMessageDate(chat) {
            if (!chat || !chat.sentAt) return (chat && chat.date) || "";
            return new Intl.DateTimeFormat(getDisplayLocale(), { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(chat.sentAt));
        }

        /**
         * 시스템 메시지('OO님이 나갔습니다' 등)를 현재 언어의 문장으로 바꿔 보여 준다.
         *
         * 이름처럼 번역하면 안 되는 값과 안내 문구가 한 문장에 섞여 있어서, 서버가 저장한 한국어 원문은 그대로 두고
         * 화면에 표시할 때만 패턴을 찾아 번역 문장으로 조립한다. 알려진 패턴이 아니면 일반 번역 사전을 거친다.
         */
        function localizeSystemMessage(text) {
            const original = String(text || "");
            const i18n = window.CloudI18n;
            const language = i18n ? i18n.getLanguage() : "ko";
            // 서버(create_system_message)가 만드는 문장 형식과 정확히 같아야 한다. 서버 문구를 바꾸면 이 정규식도 바꿔야 한다.
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

        /**
         * 지금 열려 있는 대화방 정보를 돌려준다. 열린 대화방이 없으면 undefined.
         */
        function getCurrentFriend() {
            return friends.find(function (friend) { return friend.id === currentConversationID; });
        }

        /**
         * 대화방 목록과 채팅 헤더가 같은 규칙을 쓰도록, 대화방에 보여 줄 프로필 사진 주소를 한 곳에서 정한다.
         */
        function getConversationAvatar(friend) {
            if (friend.isGroup) return friend.groupProfileImage || "/static/default_profile.png";
            return friend.peerProfileImage || "/static/default_profile.png";
        }

        /**
         * 상대방 프로필 카드(배경·사진·소개글·접속 상태)를 연다. 그룹 대화방에서는 열지 않는다.
         */
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

        /**
         * 선택한 대화방에 맞춰 채팅 헤더와 오른쪽 '현재 대화' 패널을 갱신한다.
         *
         * friend가 없으면 '대화를 선택하세요' 상태로 되돌린다. 언어가 바뀔 때도 다시 호출해 문구를 새 언어로 맞춘다.
         */
        function updateChatHeader(friend) {
            if (!friend) {
                chatHeader.innerText = "";
                chatHeaderAvatar.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
                chatHeaderAvatar.onclick = null;
                chatHeaderMemberCount.style.display = "none";
                if (chatPanel) chatPanel.classList.add("no-conversation");
                applyChatTheme(null);
                desktopInfoName.innerText = window.CloudI18n ? window.CloudI18n.t("대화를 선택하세요") : "대화를 선택하세요";
                desktopInfoStatus.innerText = window.CloudI18n ? window.CloudI18n.t("친구를 추가하거나 채팅방을 선택해보세요.") : "친구를 추가하거나 채팅방을 선택해보세요.";
                desktopConversationActions.style.display = "none";
                return;
            }

            if (chatPanel) chatPanel.classList.remove("no-conversation");
            applyChatTheme(friend);
            chatHeader.innerText = friend.name;
            desktopInfoName.innerText = friend.name;
            const i18n = window.CloudI18n;
            desktopInfoStatus.innerText = friend.isGroup
                ? (i18n ? i18n.t("{count}명이 참여 중인 그룹 채팅입니다.") : "{count}명이 참여 중인 그룹 채팅입니다.").replace("{count}", friend.memberCount || 0)
                : (friend.isOnline ? (i18n ? i18n.t("현재 온라인입니다.") : "현재 온라인입니다.") : (i18n ? i18n.t("현재 오프라인입니다.") : "현재 오프라인입니다."));
            desktopConversationActions.style.display = "grid";
            desktopConversationPin.innerHTML = `<i class="fa-solid fa-thumbtack"></i> ${friend.isPinned ? "고정 해제" : "고정"}`;
            desktopConversationMute.innerHTML = `<i class="fa-solid fa-bell${friend.isMuted ? "" : "-slash"}"></i> ${friend.isMuted ? "알림 켜기" : "알림 끄기"}`;

            if (friend.isGroup) {
                // 그룹 사진. 서버 응답의 필드 이름이 groupProfileImage 또는 profileImage일 수 있어 둘 다 확인한다.
                const groupImg = friend.groupProfileImage || friend.profileImage;

                chatHeaderAvatar.innerHTML = groupImg
                    ? `<img src="${groupImg}">`
                    : `<i class="fa-solid fa-users"></i>`;

                // 그룹 사진을 누르면 큰 이미지로 보여 준다. 사진이 없으면 클릭 동작을 두지 않는다.
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
                // 1:1 대화에서는 상대 사진을 누르면 프로필 카드가 열린다(보기 전용).
                chatHeaderAvatar.onclick = function () { openProfileCard(friend); };
                chatHeaderMemberCount.style.display = "none";
            }
        }

        /**
         * 차단 안내 배너의 문구를 바꾼다.
         *
         * i18n은 요소의 최초 문구를 data-i18n-text에 보관했다가 언어가 바뀔 때 다시 적용한다.
         * 그래서 문구를 바꿀 때 기준값(data 속성)도 함께 갱신하지 않으면 다음 번역 때 원래 문구로 되돌아간다.
         */
        function setBannerMessage(koreanText) {
            const label = blockBanner.querySelector("span");
            label.dataset.i18nText = koreanText;
            label.textContent = window.CloudI18n ? window.CloudI18n.t(koreanText) : koreanText;
        }

        /**
         * 메시지 입력창의 안내 문구를 바꾼다. setBannerMessage와 같은 이유로 번역 기준값(data 속성)도 함께 갱신한다.
         */
        function setInputPlaceholder(koreanText) {
            input.dataset.i18nPlaceholder = koreanText;
            input.placeholder = window.CloudI18n ? window.CloudI18n.t(koreanText) : koreanText;
        }

        /**
         * 열려 있는 대화방이 '차단' 또는 '종료된 그룹' 상태면 입력창·전송·첨부 버튼을 잠그고 안내 배너를 띄운다.
         *
         * 차단은 내가 차단했거나 상대가 나를 차단한 경우 모두 해당한다.
         */
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

        /**
         * 메시지를 보낸 직후 서버를 다시 조회하기 전에도 대화방 목록의 미리보기를 바로 갱신한다.
         *
         * 미리보기 문구를 바꾸려면 getPreviewText()만 고치면 된다.
         */
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

        /**
         * 대화방 목록에 보여 줄 마지막 메시지 요약. 음성·파일·사진은 종류 이름으로 대신한다('__CAMERA__' 같은 표식은 목록에서 아이콘으로 바뀐다).
         */
        function getPreviewText(chatList) {
            if (!chatList || chatList.length === 0) return "";
            const last = chatList[chatList.length - 1];
            if (last.audio) return "음성 메시지";
            if (last.filePath) return "파일";
            return last.image ? "__CAMERA__사진" : last.text;
        }

        /**
         * 대화방 목록에 보여 줄 마지막 메시지의 시간 문자열.
         */
        function getPreviewTime(chatList) {
            if (!chatList || chatList.length === 0) return "";
            return chatList[chatList.length - 1].time;
        }

        /**
         * 메시지를 모든 상대가 읽었는지(안 읽은 사람이 0명인지) 판단한다.
         */
        function isMessageRead(chat) {
            return !chat.unreadCount || chat.unreadCount <= 0;
        }

        /**
         * 사용자 입력을 HTML에 넣기 전에 특수문자를 안전하게 바꾼다(XSS 방지).
         *
         * innerHTML로 값을 넣는 곳에서는 사용자 입력을 반드시 이 함수를 거쳐야 한다.
         */
        function escapeHTML(text) {
            if (text == null) return"";
            const div = document.createElement("div");
            div.textContent = text;
            return div.innerHTML;
        }

        /**
         * 파일 크기를 사람이 읽기 쉬운 문자열(KB, MB)로 바꾼다. 1MB 미만은 최소 1KB로 표시한다.
         */
        function formatFileSize(bytes) {
            const size = Number(bytes) || 0;
            if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))}KB`;
            return `${(size / (1024 * 1024)).toFixed(1)}MB`;
        }

        /**
         * 파일 메시지를 다운로드 카드(파일 이름, 크기) HTML로 만든다.
         */
        function buildFileMessageHTML(chat) {
            return `<a class="chat-file-card" href="${escapeHTML(chat.filePath)}" target="_blank" rel="noopener" download>
                <i class="fa-solid fa-file-arrow-down"></i><span><strong>${escapeHTML(chat.fileName || "첨부 파일")}</strong><small>${formatFileSize(chat.fileSize)}</small></span>
            </a>`;
        }

        /**
         * 메시지 본문을 안전한 HTML로 바꾸고, 검색어와 일치하는 부분을 강조(<mark>)한다.
         *
         * 검색어가 없으면 링크만 자동 연결한다. 검색어의 정규식 특수문자는 먼저 이스케이프한다.
         */
        function highlightText(text, query) {
            const safeText = escapeHTML(text);
            if (!query) return linkifyText(safeText);
            const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const regex = new RegExp("(" + escapedQuery + ")", "gi");
            return safeText.replace(regex, '<mark class="search-highlight">$1</mark>');
        }

        // 링크 미리보기 결과 캐시(주소 → 결과 또는 null). 같은 링크를 여러 번 서버에 물어보지 않게 한다.
        const linkPreviewCache = new Map();
        // http/https 주소를 찾는 정규식. 공백과 <, >, 따옴표 앞에서 끝난다.
        const urlPattern = /https?:\/\/[^\s<>"']+/gi;

        /**
         * 텍스트에서 첫 번째 링크를 찾는다. 문장 끝에 붙은 문장부호(.,!?;:))는 링크에서 뺀다.
         */
        function getFirstUrl(text) {
            const match = (text || "").match(urlPattern);
            return match ? match[0].replace(/[.,!?;:)]*$/, "") : null;
        }

        /**
         * 이미 이스케이프된 텍스트의 링크를 클릭 가능한 <a>로 바꾼다. 문장부호는 링크 밖에 남긴다.
         */
        function linkifyText(safeText) {
            return safeText.replace(urlPattern, function (url) {
                const cleanUrl = url.replace(/[.,!?;:)]*$/, "");
                const suffix = url.slice(cleanUrl.length);
                return `<a class="message-link" href="${cleanUrl}" target="_blank" rel="noopener noreferrer">${cleanUrl}</a>${suffix}`;
            });
        }

        /**
         * 서버에서 받은 링크 정보(제목·설명·이미지)로 미리보기 카드를 만든다. 이미지가 깨지면 이미지만 제거한다.
         */
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

        /**
         * 메시지 위에 링크 미리보기 카드를 붙인다.
         *
         * 미리보기는 서버가 대신 가져온다(내부망 접근 방지를 위해 서버에서 검사). 응답을 기다리는 사이 메시지가 화면에서 사라졌다면 아무것도 하지 않는다.
         */
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

        /**
         * 답장한 메시지 위에 보여 줄 원본 인용(이미지 또는 텍스트) HTML을 만든다.
         */
        function buildReplyQuoteHTML(reply) {
            if (reply.image) {
                return `<img src="${reply.image}" class="reply-quote-image">`;
            }
            return `<div class="reply-quote">${escapeHTML(reply.text)}</div>`;
        }

        /**
         * 기준 요소(rect) 옆에 메뉴를 놓고, 화면 밖으로 나가지 않게 좌표를 보정한다.
         *
         * 파일 카드와 음성 컨트롤도 같은 화면 좌표계로 계산해야 메뉴가 입력창 쪽으로 밀리지 않는다.
         */
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

        // ============================================================
        // DOM 요소 참조
        // ============================================================
        // 자주 쓰는 화면 요소를 처음 한 번만 찾아 변수에 담아 둔다. 요소 id는 templates/index.html과 맞아야 한다.
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
        // 메시지 반응(이모지) 선택창.
        const reactionPicker = document.querySelector("#reaction-picker");
        // 대화 내 검색 바.
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
        // 메시지 전달·신고 창.
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
        // 친구 관리 패널(친구 추가·검색, 요청, 새 그룹 만들기).
        const friendPanelTab = document.querySelector("#friend-panel-tab");
        const friendPanel = document.querySelector("#friend-panel");
        const closeFriendPanelBtn = document.querySelector("#close-friend-panel");
        const newFriendInput = document.querySelector("#new-friend-input");
        const addFriendConfirmBtn = document.querySelector("#add-friend-confirm-btn");
        const friendSearchInput = document.querySelector("#friend-search-input");
        const friendSearchBtn = document.querySelector("#friend-search-btn");
        const friendSearchResult = document.querySelector("#friend-search-result");
        const friendRequestList = document.querySelector("#friend-request-list");
        // 메시지함(받은 요청·보낸 요청).
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
        // 설정 메뉴와 프로필 편집창.
        const sideNavSettings = document.querySelector(".side-nav-settings");
        const settingsMenu = document.querySelector("#settings-menu");
        const mobileSheetBackdrop = document.querySelector("#mobile-sheet-backdrop");
        const logoutBtn = document.querySelector("#logout-btn");
        const editProfileBtn = document.querySelector("#edit-profile-btn");
        const myProfileOverlay = document.querySelector("#my-profile-overlay");
        const myProfileCloseBtn = document.querySelector("#my-profile-close-btn");
        const accountSettingsItem = document.querySelector("#account-settings-item");
        const notificationSettingsItem = document.querySelector("#notification-settings-item");
        // 알림 설정과 업데이트 내역.
        const updateNoticeBadge = document.querySelector("#update-notice-badge");
        const updateHistoryList = document.querySelector("#update-history-list");
        const previousUpdatesBtn = document.querySelector("#previous-updates-btn");
        const previousUpdatesOverlay = document.querySelector("#previous-updates-overlay");
        const previousUpdatesCloseBtn = document.querySelector("#previous-updates-close-btn");
        const previousUpdatesList = document.querySelector("#previous-updates-list");
        const notificationSettingsOverlay = document.querySelector("#notification-settings-overlay");
        const notificationSettingsCloseBtn = document.querySelector("#notification-settings-close-btn");
        const browserNotificationToggle = document.querySelector("#browser-notification-toggle");
        // 공지사항·도움말(아이디 찾기, 비밀번호 재설정, 문의)과 사용자 리뷰, 운영 경고 창.
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
        // 계정 설정(아이디·비밀번호 변경).
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
        // 사진 모아보기.
        const galleryToggleBtn = document.querySelector("#gallery-toggle-btn");
        const galleryOverlay = document.querySelector("#gallery-overlay");
        const closeGallery = document.querySelector("#close-gallery");
        const galleryGrid = document.querySelector("#gallery-grid");
        // 그룹 관리(멤버 목록, 초대, 이름·사진 변경, 나가기·종료).
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
        // 지금 열어 본 그룹의 멤버 목록과 방장 ID.
        let currentGroupMembers = [];
        let currentGroupOwnerId = null;

        // 채팅 화면 본체와 모바일 하단 메뉴, 채팅 테마 창, 오른쪽 '현재 대화' 패널.
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
        // 상대방 프로필 카드와 신고·차단 메뉴.
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
        // 프로필 카드가 가리키는 사용자와, 신고 창이 가리키는 대상.
        let profileCardTarget = null;
        let reportTarget = null;
        // 내 프로필 편집창(소개글, 공개 범위, 배경 사진).
        const myProfileBio = document.querySelector("#my-profile-bio");
        const myProfileVisibility = document.querySelector("#my-profile-visibility");
        const coverImageInput = document.querySelector("#cover-image-input");
        const removeCoverImageBtn = document.querySelector("#remove-cover-image-btn");
        const profileCoverPreview = document.querySelector("#profile-cover-preview");

        // ============================================================
        // 화면 열고 닫기 (모바일 레이아웃, 패널, 메뉴)
        // ============================================================
        /**
         * 모바일에서 대화창을 연다.
         *
         * 모바일은 한 화면에 목록과 대화창을 함께 두지 않는다. PC에서는 이 클래스가 CSS에 영향을 주지 않아 기존 레이아웃이 유지된다.
         */
        function openMobileChat() {
            if (window.matchMedia("(max-width: 767px)").matches) {
                document.body.classList.add("mobile-chat-open");
            }
        }

        /**
         * 모바일에서 대화창을 닫고 목록으로 돌아간다. 열려 있던 '더보기' 시트도 닫는다.
         */
        function closeMobileChat() {
            document.body.classList.remove("mobile-chat-open");
            mobileChatActionsSheet.classList.remove("open");
        }

        /**
         * 대화방의 채팅 테마(배경·말풍선 색)를 채팅 화면에 적용하고, 테마 선택창에서 현재 테마를 표시한다. 대화방이 없으면 기본 테마.
         */
        function applyChatTheme(friend) {
            chatPanel.classList.remove("chat-theme-heart", "chat-theme-teddy", "chat-theme-glass", "chat-theme-aurora", "chat-theme-mono", "chat-theme-spring", "chat-theme-summer", "chat-theme-autumn", "chat-theme-winter", "chat-theme-christmas", "chat-theme-halloween");
            const theme = friend && friend.chatTheme ? friend.chatTheme : "default";
            if (theme !== "default") chatPanel.classList.add(`chat-theme-${theme}`);
            chatThemeOptions.forEach(function (option) {
                option.classList.toggle("selected", option.dataset.theme === theme);
            });
        }

        /**
         * 테마가 속한 분류(기본/계절/시즌)를 돌려준다. 테마 선택창의 탭을 고를 때 쓴다.
         */
        function getThemeCategory(theme) {
            if (["spring", "summer", "autumn", "winter"].includes(theme)) return "season";
            if (["christmas", "halloween"].includes(theme)) return "event";
            return "basic";
        }

        /**
         * 테마 선택창에서 선택한 분류의 탭과 목록만 보이게 한다.
         */
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

        /**
         * 오늘 날짜에 어울리는 테마(현재 계절, 12월~1월 초는 크리스마스, 10월 중순 이후는 할로윈)에 '추천' 표시를 붙인다.
         */
        function updateSeasonalThemeRecommendations() {
            const today = new Date();
            const month = today.getMonth() + 1;
            const day = today.getDate();
            // 크리스마스 추천: 12월 전체와 1월 6일까지. 할로윈 추천: 10월 15일~31일.
            const christmasSeason = month === 12 || (month === 1 && day <= 6);
            const halloweenSeason = month === 10 && day >= 15 && day <= 31;
            // 북반구 기준 계절: 3~5월 봄, 6~8월 여름, 9~11월 가을, 그 외 겨울.
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

        // 페이지를 열 때 한 번 계산한다.
        updateSeasonalThemeRecommendations();

        /**
         * 모바일 채팅의 '더보기' 시트를 닫는다.
         */
        function closeMobileChatActions() {
            mobileChatActionsSheet.classList.remove("open");
            mobileChatActionsSheet.setAttribute("aria-hidden", "true");
        }

        /**
         * 현재 화면이 모바일 폭(767px 이하)인지 확인한다. CSS의 모바일 기준과 같아야 한다.
         */
        function isMobileViewport() {
            return window.matchMedia("(max-width: 767px)").matches;
        }

        /**
         * 모바일 하단 메뉴에서 현재 선택된 버튼만 강조한다.
         */
        function setMobileNavActive(activeButton) {
            [mobileChatNavBtn, mobileFriendsNavBtn, mobileProfileNavBtn, mobileSettingsNavBtn]
                .forEach(function (button) {
                    button.classList.toggle("active", button === activeButton);
                });
        }

        /**
         * 친구 관리 패널을 열고 친구 목록과 받은 요청을 최신 상태로 불러온다.
         */
        function openFriendPanel() {
            friendPanel.classList.add("open");
            if (isMobileViewport()) document.body.classList.add("mobile-friends-open");
            renderFriendPanelList();
            loadFriendRequests();
        }

        /**
         * 친구 관리 패널을 닫는다.
         */
        function closeFriendPanel() {
            friendPanel.classList.remove("open");
            document.body.classList.remove("mobile-friends-open");
        }

        /**
         * 메시지함을 연다. 열기 전에 요청 목록을 새로 불러와 오래된 정보가 보이지 않게 한다.
         */
        async function openFriendInbox() {
            closeFriendPanel();
            await loadFriendRequests();
            friendInboxOverlay.style.display = "flex";
        }

        /**
         * 메시지함을 닫는다.
         */
        function closeFriendInbox() {
            friendInboxOverlay.style.display = "none";
        }

        /**
         * 설정 메뉴를 닫는다. 펼쳐 둔 '편하게 보기' 항목도 함께 접는다.
         */
        function closeSettingsMenu() {
            settingsMenu.style.display = "none";
            settingsMenu.style.pointerEvents = "none";
            document.body.classList.remove("mobile-settings-open");
            if (officeComfortItem) {
                officeComfortItem.open = false;
            }
        }

        /**
         * 설정 메뉴를 연다.
         *
         * 모바일에서는 하단 시트로 열고, PC에서는 누른 버튼(anchor) 오른쪽에 놓되 화면 밖으로 나가지 않게 위치를 보정한다.
         */
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

        // 공용 확인/알림 창.
        const modalOverlay = document.querySelector("#modal-overlay");
        const modalMessage = document.querySelector("#modal-message");
        const modalCancelBtn = document.querySelector("#modal-cancel-btn");
        const modalConfirmBtn = document.querySelector("#modal-confirm-btn");

        // 설정 메뉴의 화면 설정: 다크 모드, 오피스 모드, 편하게 보기, 화면 테마, 언어.
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
        // 계정 삭제, 프로필 사진 변경·자르기(crop), 동영상 첨부, 이메일 변경에 쓰는 요소.
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
        // 이메일 인증 진행 상태: 인증번호를 보냈는지, 인증을 마쳤는지(계정 설정용과 비밀번호 재설정용 각각).
        let accountEmailCodeSent = false;
        let accountEmailVerified = false;
        let helpResetCodeSent = false;
        let helpResetVerified = false;

        // ============================================================
        // 다크모드
        // ============================================================
        // 다크 모드 선택은 브라우저(localStorage)에 저장해 두었다가 접속할 때 복원한다.
        const savedTheme = localStorage.getItem("theme");
        if (savedTheme === "dark") {
            document.body.classList.add("dark-mode");
            themeToggleIcon.className = "fa-solid fa-sun";
            themeToggleLabel.innerText = window.CloudI18n ? window.CloudI18n.t("라이트 모드") : "라이트 모드";
        }

        // 다크/라이트 전환. 선택은 localStorage에 저장하고 아이콘·문구를 바꾼다. 오피스 모드에서는 바꿀 수 없다.
        themeToggleItem.addEventListener("click", function (event) {
            event.stopPropagation();
            // 오피스 모드에서는 화면 모드(다크/라이트)가 고정되어 있어 바꿀 수 없다.
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

        /**
         * '편하게 보기' 설정값(대비, 글자 크기, 간격, 움직임 줄이기)을 읽는다.
         *
         * 오피스 모드는 기능을 바꾸지 않고, 오래 보는 업무용 화면의 시각 밀도만 차분하게 조절한다.
         * 움직임 줄이기는 저장된 선택이 없으면 운영체제의 '동작 줄이기' 설정을 따른다.
         */
        function getOfficeComfortSettings() {
            return {
                contrast: localStorage.getItem("officeContrast") || "comfort",
                textSize: localStorage.getItem("officeTextSize") || "medium",
                density: localStorage.getItem("officeDensity") || "comfortable",
                reduceMotion: localStorage.getItem("officeReduceMotion") === "true"
                    || (localStorage.getItem("officeReduceMotion") === null && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
            };
        }

        /**
         * 저장된 '편하게 보기' 설정을 body의 클래스와 설정 메뉴의 선택값에 반영한다.
         */
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

        /**
         * '편하게 보기' 항목을 항상 보이게 한다. 오피스 모드를 켰는지와 상관없이 언제든 열 수 있다.
         */
        function syncOfficeComfortVisibility() {
            officeComfortItem.hidden = false;
        }

        // ============================================================
        // Liquid Glass 테마(굴절 효과) 제어
        // ============================================================
        // 굴절 효과는 요소 '뒤'(backdrop)에만 걸리고 요소 안의 내용은 건드리지 않는다.
        // 그래서 패널에 강한 굴절을 줘도 안쪽 글자는 그대로 읽힌다. 말풍선은 수가 많고 대화할 때마다
        // 새로 생기므로 대상에서 뺀다.
        //
        // SVG 굴절 맵은 한 번 만들면 끝이지만, backdrop-filter 합성은 뒤 내용이 바뀔 때마다 다시 계산된다.
        // 큰 면적에 걸면 그 비용이 프레임을 잡아먹으므로, 아래 상수로 굴절을 거는 요소의 크기와 개수를 제한한다.
        // 큰 패널은 CSS 유리(blur + saturate)만 쓴다.
        const LG_MAX_AREA = 320000;
        const LG_MAX_SIDE = 1600;
        const LG_MAX_INSTANCES = 10;
        // 굴절 강도 프리셋(패널·바·팝오버). scale은 굴절 세기, chroma는 색 번짐, blur는 흐림 정도다. 현재는 LG_POPOVER만 대상에 쓰인다.
        const LG_PANEL = { scale: -180, chroma: 8, blur: 2, saturate: 1.6 };
        const LG_BAR = { scale: -140, chroma: 6, blur: 2, saturate: 1.6 };
        const LG_POPOVER = { scale: -112, chroma: 6, blur: 3, saturate: 1.5 };
        // 굴절을 거는 대상 목록. 잠깐 나타났다 사라지는 표면(팝오버·메뉴·모달)에만 건다.
        // 항상 떠 있는 헤더·입력창·패널에 걸면 화면이 바뀔 때마다 다시 계산되어 상시 프레임 비용이 되므로,
        // 그쪽은 CSS 흐림만으로 유리처럼 보이게 한다.
        const LG_TARGETS = [
            { selector: "#friend-panel", options: LG_POPOVER },
            { selector: "#settings-menu", options: LG_POPOVER },
            { selector: "#attach-menu", options: LG_POPOVER },
            { selector: "#message-menu", options: LG_POPOVER },
            { selector: "#mobile-chat-actions-sheet", options: LG_POPOVER },
            // 모달은 바깥 오버레이의 display가 바뀌므로, 유리는 안쪽 상자에 건다.
            { selector: ".modal-overlay .modal", options: LG_POPOVER },
            { selector: ".modal-overlay .settings-modal", options: LG_POPOVER },
            { selector: ".modal-overlay .chat-theme-modal", options: LG_POPOVER },
            { selector: ".modal-overlay .friend-inbox-modal", options: LG_POPOVER },
        ];
        // 표시 상태(style/class/hidden)가 바뀌는 요소들. 이들의 변화를 지켜보다가 굴절 대상을 다시 계산한다.
        const LG_WATCH_SELECTORS = [
            ".modal-overlay", "#settings-menu", "#attach-menu",
            "#message-menu", "#friend-panel", "#mobile-chat-actions-sheet",
        ];
        // backdrop-filter는 position:fixed 자손의 기준(containing block)을 바꿔 버린다.
        // 유리 패널 안의 고정 팝오버는 뷰포트가 아니라 패널 기준으로 배치되어 화면 밖으로 밀리거나 잘린다.
        // 그래서 이 요소들은 body 직속으로 옮겨 좌표를 되찾는다.
        // position:absolute 요소는 여기 넣으면 안 된다. 기준점이 원래 부모라서 옮기는 순간 엉뚱한 곳으로 날아간다(#attach-menu가 그 경우다).
        const LG_REPARENT = ["#message-menu", "#friend-panel", "#mobile-chat-actions-sheet"];

        /**
         * LG_REPARENT 목록의 요소를 body 바로 아래로 옮긴다(이미 옮겼으면 건너뛴다).
         */
        function lgReparentFixedPopovers() {
            LG_REPARENT.forEach(selector => {
                const element = document.querySelector(selector);
                if (element && element.parentElement !== document.body) {
                    document.body.appendChild(element);
                }
            });
        }

        // 굴절 효과가 걸린 요소 → liquidGlass 인스턴스. 타이머와 관찰자는 동기화 예약용이다.
        const lgInstances = new Map();
        let lgObserver = null;
        let lgTimer = null;

        /**
         * 굴절 효과를 써도 되는 환경인지 판단한다.
         *
         * 라이브러리를 못 불러와도 앱은 그대로 동작해야 하고, 오피스 모드·고대비·'투명도 줄이기' 설정에서는 가독성이 우선이다.
         * CPU 코어가 4개 이하인 저사양 기기에서도 꺼서 성능을 지킨다.
         */
        function lgEnabled() {
            if (typeof window.liquidGlass !== "function") return false;
            if (!document.body.classList.contains("theme-liquid-glass")) return false;
            if (document.body.classList.contains("office-mode")) return false;
            if (document.body.classList.contains("office-contrast-high")) return false;
            if (window.matchMedia("(prefers-reduced-transparency: reduce)").matches) return false;
            if ((navigator.hardwareConcurrency || 8) <= 4) return false;
            return true;
        }

        /**
         * 요소에 굴절 효과를 건다. 이미 걸려 있거나, 개수·크기 제한을 넘거나, 화면에 보이지 않으면 건너뛴다.
         */
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

        /**
         * 요소의 굴절 효과를 걷어낸다.
         */
        function lgDetach(element) {
            const instance = lgInstances.get(element);
            if (!instance) return;
            instance.destroy();
            lgInstances.delete(element);
        }

        /**
         * 걸려 있는 굴절 효과를 모두 걷어낸다.
         */
        function lgDetachAll() {
            lgInstances.forEach(instance => instance.destroy());
            lgInstances.clear();
        }

        /**
         * 현재 화면 상태에 맞게 굴절 효과를 다시 맞춘다. 보이는 대상에는 걸고, 숨겨진 대상에서는 걷는다. 효과를 쓸 수 없는 환경이면 전부 걷는다.
         */
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

        /**
         * lgSync를 잠시 뒤로 미룬다. 짧은 시간에 변화가 여러 번 생겨도 한 번만 실행되도록 이전 예약을 취소한다(디바운스).
         */
        function lgScheduleSync(delay) {
            clearTimeout(lgTimer);
            lgTimer = setTimeout(lgSync, delay);
        }

        /**
         * 메뉴와 모달은 열릴 때 비로소 크기가 생기므로, 표시 상태 변화와 창 크기 변경을 지켜보다가 굴절 대상을 다시 맞춘다.
         */
        function lgWatch() {
            if (lgObserver) return;
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

        /**
         * 저장된 화면 테마(liquid-glass 또는 classic)를 읽는다. 기본값은 liquid-glass(클라우드).
         */
        function getAppTheme() {
            return localStorage.getItem("appTheme") || "liquid-glass";
        }

        /**
         * 화면 테마를 적용한다. 클라우드(liquid-glass)면 굴절 효과를 켜고, 클래식이면 즉시 걷어낸다.
         */
        function applyAppTheme() {
            const theme = getAppTheme();
            const useGlass = theme === "liquid-glass";
            document.body.classList.toggle("theme-liquid-glass", useGlass);
            if (appThemeSelect) appThemeSelect.value = theme;
            if (!useGlass) {
                lgDetachAll();
                return;
            }
            // 켤 때는 굴절 맵 생성에 수십 ms가 걸리므로, 첫 화면 그리기를 막지 않도록 브라우저가 한가할 때로 미룬다.
            if (window.requestIdleCallback) window.requestIdleCallback(() => lgSync(), { timeout: 800 });
            else lgScheduleSync(150);
        }

        /**
         * 설정 메뉴의 언어 선택과 현재 언어 표시를 지금 적용된 언어에 맞춘다.
         */
        function syncLanguageSetting() {
            if (!window.CloudI18n || !languageSelect || !languageSettingCurrent) return;
            const language = window.CloudI18n.getLanguage();
            const labels = { ko: "한국어", en: "English", zh: "中文", ja: "日本語", es: "español" };
            languageSelect.value = language;
            languageSettingCurrent.textContent = labels[language];
        }

        /**
         * 다크/라이트 전환 버튼의 문구·아이콘을 현재 상태에 맞춘다. 오피스 모드에서는 화면 모드가 고정되므로 버튼을 잠금 표시로 바꾼다.
         */
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

        /**
         * 오피스 모드 버튼의 문구를 현재 상태(켜기/끄기)와 언어에 맞춰 다시 쓴다. 이어서 다크/라이트 버튼과 '편하게 보기' 표시도 맞춘다.
         */
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

        // 페이지를 열 때 화면 설정을 복원하는 초기화 구간. 오피스 모드 → 편하게 보기 → 테마 → 언어 순으로 적용한다.
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
        if (!getCurrentFriend()) updateChatHeader(null);

        // 언어가 바뀔 때(i18n.js가 알려 준다): 자동 번역에서 빠진 문구를 다시 쓰고, 서버에 선택 언어를 저장한다.
        window.addEventListener("cloud-language-change", async function (event) {
            syncLanguageSetting();
            syncOfficeModeLabel();
            updateChatHeader(getCurrentFriend() || null);
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

        // '편하게 보기'의 대비·글자 크기·간격 선택: 고른 값을 저장하고 바로 화면에 적용한다.
        [[officeContrastSelect, "officeContrast"], [officeTextSizeSelect, "officeTextSize"], [officeDensitySelect, "officeDensity"]].forEach(([control, key]) => {
            control.addEventListener("change", function () {
                localStorage.setItem(key, control.value);
                applyOfficeComfortSettings();
                // 고대비로 바꾸면 굴절을 꺼야 하므로 테마 상태를 다시 계산한다.
                lgSync();
            });
        });
        // '움직임 줄이기' 스위치: 선택을 저장하고 바로 적용한다.
        officeReduceMotion.addEventListener("change", function () {
            localStorage.setItem("officeReduceMotion", String(officeReduceMotion.checked));
            applyOfficeComfortSettings();
        });

        // 화면 테마(클라우드/클래식) 선택: 저장하고 바로 적용한다.
        if (appThemeSelect) {
            appThemeSelect.addEventListener("change", function () {
                localStorage.setItem("appTheme", appThemeSelect.value);
                applyAppTheme();
            });
        }

        // 오피스 모드 켜기/끄기. 켜는 동안에는 다크 모드를 잠시 해제하고(저장값은 유지), 끄면 저장해 둔 다크/라이트 선택을 복원한다.
        officeModeItem.addEventListener("click", function (event) {
            event.stopPropagation();
            closeSettingsMenu();
            const enabled = document.body.classList.toggle("office-mode");
            if (enabled) {
                // 사용자가 고른 화면 모드(다크/라이트)는 저장값으로 보존하고, 오피스 모드인 동안만 적용을 멈춘다.
                document.body.classList.remove("dark-mode");
            } else if (localStorage.getItem("theme") === "dark") {
                document.body.classList.add("dark-mode");
            }
            localStorage.setItem("officeMode", enabled ? "enabled" : "disabled");
            syncOfficeModeLabel();
            lgSync();
            showToast(enabled ? "오피스 모드를 적용했습니다." : "오피스 모드를 해제했습니다.");
        });

        // ============================================================
        // 커스텀 확인/알림 모달
        // ============================================================
        // 하나의 확인 모달에는 항상 하나의 작업만 연결한다.
        // 이전 취소 처리기가 남아 있으면, 친구 차단/삭제 때 과거 채팅방 삭제 모달을 다시 여는 상태 충돌이 생긴다.
        let activeModalAction = null;
        /**
         * 확인 모달을 닫고, 연결해 둔 작업이 있으면 사용자의 선택(확인=true, 취소=false)을 넘겨 실행한다.
         */
        function closeAppModal(confirmed) {
            const action = activeModalAction;
            activeModalAction = null;
            modalOverlay.style.display = "none";
            if (action) action(confirmed);
        }
        // 확인·취소 버튼과 바깥(어두운 영역) 클릭을 모두 closeAppModal로 모아 처리한다. 바깥 클릭은 취소와 같다.
        modalConfirmBtn.addEventListener("click", function () { closeAppModal(true); });
        modalCancelBtn.addEventListener("click", function () { closeAppModal(false); });
        modalOverlay.addEventListener("click", function (event) {
            if (event.target === modalOverlay) closeAppModal(false);
        });

        /**
         * 확인/취소 모달을 띄운다. 확인과 취소 모두 onConfirm(true|false)로 결과를 전달한다.
         */
        function showConfirm(message, onConfirm) {
            activeModalAction = onConfirm;
            modalMessage.innerText = window.CloudI18n ? window.CloudI18n.t(message) : message;
            modalCancelBtn.style.display = "inline-block";
            modalOverlay.style.display = "flex";
        }

        /**
         * 확인 버튼만 있는 알림 모달을 띄운다. 확인을 누르면 onClose를 실행한다.
         */
        function showAlert(message, onClose) {
            activeModalAction = function (confirmed) { if (confirmed && onClose) onClose(); };
            modalMessage.innerText = window.CloudI18n ? window.CloudI18n.t(message) : message;
            modalCancelBtn.style.display = "none";
            modalOverlay.style.display = "flex";
        }

        /**
         * 화면 구석에 잠깐 떴다 사라지는 알림을 띄운다. type은 success, error, info.
         *
         * 저장·복사처럼 즉시 끝나는 작업은 화면을 막는 모달 대신 이 토스트로 알린다.
         */
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

        // 전송 중인 작업 수. 0보다 크면 입력창과 전송 버튼을 잠근다(여러 작업이 겹쳐도 마지막이 끝날 때 풀리도록 카운터로 관리한다).
        let composerBusyCount = 0;

        /**
         * 메시지 전송 중 입력창·전송·첨부 버튼을 잠그거나 푼다. 전송 중에 입력값이 지워지거나 같은 파일이 중복 전송되는 일을 막는다.
         */
        function setComposerBusy(isBusy) {
            composerBusyCount = Math.max(0, composerBusyCount + (isBusy ? 1 : -1));
            const busy = composerBusyCount > 0;
            button.disabled = busy;
            plusBtn.disabled = busy;
            input.disabled = busy;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-busy", String(busy));
        }

        /**
         * 입력창에 포커스를 돌려준다. 메뉴·모달이 닫히는 동안 포커스가 빼앗기지 않도록 잠깐 기다렸다가 실행한다.
         */
        function focusInputSafely() {
            setTimeout(function () { input.focus(); }, 50);
        }

        // ============================================================
        // 대화 내 검색
        // ============================================================
        /**
         * 현재 대화방의 텍스트 메시지에서 검색어(대소문자 구분 없음)가 들어간 메시지를 찾고, 화면을 다시 그린 뒤 첫 결과로 이동한다.
         */
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

        /**
         * 검색 결과 개수 표시('현재/전체')를 갱신한다.
         */
        function updateSearchCount() {
            searchCount.innerText = searchMatches.length === 0
                ? "0/0"
                : (currentMatchIndex + 1) + "/" + searchMatches.length;
        }

        /**
         * 현재 가리키는 검색 결과 메시지가 화면 가운데 오도록 스크롤한다.
         */
        function scrollToMatch() {
            if (searchMatches.length === 0) return;
            const targetIndex = searchMatches[currentMatchIndex];
            const el = messages.querySelector('[data-msg-index="' + targetIndex + '"]');
            if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        }

        
        // ============================================================
        // 메시지 전송 / 수정
        // ============================================================
        /**
         * 입력창의 텍스트를 보낸다. 수정 모드(editingIndex가 있음)면 새 메시지가 아니라 기존 메시지를 수정한다.
         *
         * 전송 중에는 입력창을 잠그고, 성공하면 메시지 목록과 대화방 미리보기를 새로 불러온다.
         */
        async function sendMessage() {
            if (composerBusyCount > 0) return;
            const planeIcon = document.querySelector(".input-area button i.fa-paper-plane");
            if (planeIcon) {
                planeIcon.classList.remove("launch");
                // 강제 리플로우. 클래스를 뺐다 다시 붙여도 브라우저가 변화를 모르고 지나치기 때문에, 레이아웃을 한 번 읽어 같은 애니메이션을 연속으로 눌러도 다시 재생되게 한다.
                void planeIcon.offsetWidth;
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
                // 수정 모드: 새 메시지를 만들지 않고 기존 메시지(editingIndex)의 본문만 바꾼다.
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

            
        // ============================================================
        // 메시지 렌더링
        // ============================================================
        /**
         * 현재 대화방의 메시지를 서버에서 가져와 화면에 그린다.
         *
         * 이미 진행 중인 새로고침이 있으면 새 요청을 만들지 않고 그 결과를 함께 기다린다.
         * (소켓 알림과 직접 호출이 겹쳐도 요청이 한 번만 나가게 한다.)
         */
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

        /**
         * 서버에서 메시지를 받아 DOM으로 만들어 목록을 통째로 교체한다.
         *
         * 처리 순서: 빈 상태 처리 → 고정 메시지 표시 → 메시지마다(날짜 구분선, 시스템 메시지, 우클릭·더블클릭 메뉴,
         * 내 메시지/상대 메시지별 HTML, 스와이프 답장, 이미지 확대, 링크 미리보기) → 맨 아래로 스크롤.
         * 화면 조각(DocumentFragment)에 먼저 만든 뒤 한 번에 붙여 깜빡임과 재계산을 줄인다.
         */
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

            // DOM에 바로 붙이지 않고 조각에 모았다가 마지막에 한 번만 교체한다.
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

            // 고정된 메시지가 있으면 목록 위쪽 고정 바에 보여 주고, 누르면 고정을 푼다.
            const pinnedChat = chatList.find(function (chat) { return chat.pinned; }) || null;
            if (pinnedChat) {
                pinnedBox.style.display = "flex";
                pinnedBox.style.cursor = "pointer";

                // 고정 메시지 본문은 사용자가 쓴 글이라 반드시 escapeHTML을 거쳐 넣는다(XSS 방지).
                const pinnedPreview = pinnedChat.image
                    ? `<img src="${pinnedChat.image}" style="width:32px; height:32px; border-radius:8px; object-fit:cover;"><span style="flex:1;">사진</span>`
                    : `<span style="flex:1;">${escapeHTML(pinnedChat.text)}</span>`;

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

            // 날짜가 바뀌는 지점마다 날짜 구분선을 넣기 위해 직전 메시지의 날짜를 기억한다.
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

                // 시스템 메시지(입장·퇴장·테마 변경 등)는 말풍선이 아니라 가운데 안내 문구로 보여 주고, 메뉴나 답장 같은 상호작용은 붙이지 않는다.
                if (chat.messageType === "system") {
                    message.className = "message-system";
                    message.textContent = localizeSystemMessage(chat.text || "채팅방 안내");
                    renderTarget.appendChild(message);
                    return;
                }

                // 우클릭: 메시지 메뉴를 연다. 메시지 종류와 작성자에 따라 보일 항목을 다르게 한다(첨부는 복사·수정 불가, 수정·삭제는 내 메시지만, 신고는 남의 메시지만).
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

                // 더블클릭: 메시지 위에 반응(이모지) 선택창을 띄운다.
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

                // 반응 값은 API로 아무 문자열(최대 32자)이나 보낼 수 있으므로 이모지라도 escapeHTML을 거쳐 넣는다.
                const reactionsHTML = (chat.reactions && chat.reactions.length > 0)
                    ? `<div class="reactions-row">${chat.reactions.map(function (e) { return `<span class="reactions-badge">${escapeHTML(e)}</span>`; }).join("")}</div>`
                    : "";

                const editedHTML = chat.edited ? `<div class="edited-label">수정 됨</div>` : "";
                // 내 메시지 옆에, 아직 읽지 않은 사람 수를 숫자로 표시한다(모두 읽으면 사라진다).
                const readStatusHTML = (chat.mine && !isMessageRead(chat)) ? `<span class="read-status">${chat.unreadCount}</span>` : "";

                // 내 메시지(오른쪽 정렬)와 상대 메시지(왼쪽 정렬)는 같은 종류별 분기(음성·파일·동영상·사진·답장·일반 텍스트)를 따로 만든다.
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
                    // 상대 메시지. 그룹 채팅에서는 보낸 사람의 사진과 이름을 함께 보여 주기 위해 한 칸 더 감싼다.
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

                // 모바일에서 메시지를 옆으로 밀어 답장하는 동작(스와이프)을 위한 아이콘과 이벤트.
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

                // 링크 미리보기는 DOM에 붙인 뒤에 요청한다. 캐시된 결과는 동기적으로 처리되므로 붙기 전에 부르면 '연결됨' 검사에서 걸러진다.
                if (chat.text && !chat.image && !chat.video) appendLinkPreview(message, chat);
            });

            messages.replaceChildren(renderTarget);
            // 새로 그린 뒤에는 가장 최근 메시지가 보이도록 맨 아래로 이동한다.
            messages.scrollTop = messages.scrollHeight;
        }

        // ============================================================
        // 메시지 컨텍스트 메뉴 동작 (복사 / 답장 / 수정 / 삭제 / 고정 / 전달 / 신고)
        // ============================================================
        // 복사: 선택한 메시지의 텍스트를 클립보드에 넣는다.
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

        // 답장: 선택한 메시지를 답장 대상으로 두고 입력창 위에 미리보기를 띄운다.
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

        // 답장 취소: 답장 대상과 미리보기를 지운다.
        cancelReply.addEventListener("click", function () {
            replyMessage = null;
            replyPreview.style.display = "none";
            replyImage.style.display = "none";
            replyImage.src = "";
            input.focus();
        });

        // 수정 취소: 수정 모드를 끝내고 입력창과 전송 버튼을 원래대로 돌린다.
        cancelEdit.addEventListener("click", function () {
            editingIndex = null;
            editPreview.style.display = "none";
            input.value = "";
            button.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
            input.focus();
        });

        // 삭제: 확인을 받은 뒤 메시지를 지우고 목록을 새로 불러온다. 메뉴가 닫히는 동안 모달이 겹치지 않도록 잠깐 뒤에 연다.
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

        // 수정: 메시지 내용을 입력창에 채우고 수정 모드로 전환한다(전송 버튼이 체크 아이콘으로 바뀐다).
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

        // 고정: 서버가 고정 상태를 반전한다(이미 고정이면 해제). 대화방에는 고정 메시지가 하나만 있다.
        pinMessageButton.addEventListener("click", async function () {
            if (selectedIndex === -1) return;
            
            await fetch(`/api/messages/${selectedIndex}/pin`, {
                method: "POST"
        });

        await readMessages();
        messageMenu.style.display = "none";
    });

        // 전달: 현재 대화방을 뺀 내 채팅방 목록을 고르게 한 뒤 선택한 방으로 메시지를 보낸다.
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
        // 전달 창의 닫기 버튼과 '전달' 버튼. 전달할 대화방은 선택 목록에서 고른다.
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

        // 신고: 메시지 신고 창을 연다. 사용자 신고와 같은 창을 쓰므로 reportTarget에 대상 종류(message/user)를 기록한다.
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
            // 신고 대상이 사용자면 사용자 신고 API, 메시지면 메시지 신고 API로 보낸다.
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

        // ============================================================
        // 첨부: 사진 / 파일 / 음성
        // ============================================================
        imageBtn.addEventListener("click", function () {
            imageInput.click();
            attachMenu.style.display = "none";
        });

        // 사진은 여러 장을 한꺼번에 고를 수 있고, 순서대로 하나씩 보낸다.
        imageInput.addEventListener("change", async function () {
            const files = imageInput.files;
            if (!files || files.length === 0) return;
            for (const file of files) await sendImage(file);
        });

        /**
         * 사진 파일 하나를 data URL(base64)로 읽어 서버에 보낸다. 성공하면 목록을 새로 불러온다. 전송 중에는 입력창을 잠근다.
         */
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

        // 파일 첨부 버튼: 숨겨 둔 파일 선택창을 열고 첨부 메뉴는 닫는다.
        fileBtn.addEventListener("click", function () {
            fileInput.click();
            attachMenu.style.display = "none";
        });

        // 파일은 하나씩 보낸다. 사진과 달리 base64가 아니라 FormData(멀티파트)로 올린다.
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

        // 음성 녹음 상태: 녹음기, 녹음 조각, 자동 종료 타이머, 시작 시각.
        let audioRecorder = null;
        let audioChunks = [];
        let audioTimer = null;
        let audioStartedAt = 0;
        // 음성 메시지: 첫 번째 누름은 녹음 시작, 녹음 중에 다시 누르면 멈추고 전송한다. 30초가 지나면 자동으로 멈춘다.
        // 마이크 권한이 없으면 안내를 띄운다. 길이는 서버가 검사할 수 있도록 duration으로 함께 보낸다.
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

        // + 버튼: 첨부 메뉴(사진·파일·동영상·음성)를 열고 닫는다.
        plusBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            attachMenu.style.display = (attachMenu.style.display === "block") ? "none" : "block";
        });

        // 이미지 확대창: 닫기 버튼이나 바깥 영역을 누르면 닫는다.
        closeImage.addEventListener("click", function () { imageModal.style.display = "none"; });

        imageModal.addEventListener("click", function (e) {
            if (e.target === imageModal) imageModal.style.display = "none";
        });

        // 이미지 확대창의 다운로드 버튼: 보이는 이미지를 photo.png로 내려받는다.
        downloadImage.addEventListener("click", function () {
            const a = document.createElement("a");
            a.href = modalImage.src;
            a.download = "photo.png";
            a.click();
        });

        // ============================================================
        // 대화방 목록 렌더링
        // ============================================================
        /**
         * 대화방 목록(왼쪽)을 friends 배열로 다시 그린다.
         *
         * 항목마다 사진·접속 상태·이름(고정/알림끔 표시)·마지막 메시지 미리보기·시간·안 읽은 개수를 보여 준다.
         * 클릭하면 대화방을 열고 읽음 처리, 우클릭하면 목록에서 숨긴다.
         */
        function readFriends() {
            friendList.innerHTML = "";
            friendList.classList.toggle("is-empty", friends.length === 0);
            // 목록 위쪽의 '채팅방 N개' 요약 문구.
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

                // 대화방 선택: 헤더와 입력 잠금 상태를 먼저 바꾸고, 서버에 읽음 처리를 알린 뒤 메시지를 불러온다.
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

                    // 우클릭: 채팅방을 내 목록에서만 숨긴다(친구 관계와 대화 기록은 그대로). 숨긴 방이 열려 있었다면 대화창도 비운다.
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
                

                // 미리보기는 먼저 이스케이프한 뒤, 서버가 붙인 '__종류__' 표식만 아이콘으로 바꾼다.
                const previewHTML = escapeHTML(friend.message || "아직 대화가 없습니다.")
                .replace("__CAMERA__", '<i class="fa-regular fa-image"></i>')
                .replace("__VIDEO__", '<i class="fa-solid fa-circle-play"></i>')
                .replace("__FILE__", '<i class="fa-solid fa-paperclip"></i>')
                .replace("__AUDIO__", '<i class="fa-solid fa-microphone"></i>');
                const timeHTML = (friend.lastSentAt || friend.lastTime)
                    ? `<span class="friend-time">${formatMessageTime({ sentAt: friend.lastSentAt, time: friend.lastTime })}</span>`
                    : "";

                // 안 읽은 개수는 서버가 계산해 준 unreadCount를 그대로 쓴다. 지금 열어 둔 방은 읽는 중이므로 표시하지 않는다.
                const unreadHTML = (friend.unreadCount > 0 && friend.id !== currentConversationID)
                    ? `<span class="unread-badge">${friend.unreadCount}</span>`
                    : "";

                const avatarImg = getConversationAvatar(friend);

                newFriend.innerHTML = `
                    <div class="profile ${friend.isGroup ? "" : "friend-profile-trigger"}" ${friend.isGroup ? "" : 'role="button" tabindex="0" aria-label="상대방 프로필 보기"'}>
                        <img src="${avatarImg}" alt="Profile Image">
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
                // 1:1 대화방은 프로필 사진을 눌러 상대 프로필 카드를 열 수 있다(키보드 Enter/Space 지원). 그룹은 해당 없음.
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

        // ============================================================
        // 친구 추가/삭제 (오른쪽 패널)
        // ============================================================
        /**
         * 아이디로 친구 요청을 보낸다.
         *
         * 상대가 이미 나에게 요청을 보내 둔 경우 서버가 자동으로 수락하므로(autoAccepted), 그때는 목록을 새로 불러온다.
         */
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
                await loadFriends();
                await loadFriendDirectory();
                renderFriendPanelList();
            } else {
                showToast("친구 요청을 보냈습니다.");
            }
        }

        /**
         * 받은 요청·보낸 요청을 서버에서 가져와 메시지함과 숫자 배지를 갱신한다.
         *
         * 보낸 요청 목록은 여기서 그리고(요청 취소 버튼 포함), 받은 요청 목록은 renderFriendRequestList가 그린다.
         */
        async function loadFriendRequests() {
            const response = await fetch("/api/friend-requests");
            const result = await response.json();
            const incoming = result.incoming || [];
            const outgoing = result.outgoing || [];

            incomingRequestCount.innerText = incoming.length;
            outgoingRequestCount.innerText = outgoing.length;
            friendInboxBadge.hidden = incoming.length === 0;
            friendInboxBadge.textContent = incoming.length > 99 ? "99+" : incoming.length;

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

            renderFriendRequestList(incoming);
        }

        /**
         * 받은 친구 요청 목록을 그린다. 수락하면 대화방과 친구 목록을 새로 불러오고, 거절하면 요청 목록만 갱신한다.
         */
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
                    await loadFriendDirectory();
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

        /**
         * 그룹 멤버 목록을 서버에서 가져와 그룹 관리 창을 채운다.
         *
         * 방장이고 종료되지 않은 그룹이면 이름 변경·사진 변경·종료·초대·멤버 내보내기 버튼을 보여 준다.
         * MY_USER_ID(서버가 템플릿에 넣어 준 내 ID)와 비교해 '나' 표시와 방장 권한을 판단한다.
         */
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
                // 방장이면서 아직 종료되지 않은 그룹일 때만 그룹 정보를 수정할 수 있다. 서버도 같은 규칙으로 다시 검사한다.
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

        // 그룹 관리 창을 열 때마다 최신 멤버 목록을 불러온다.
        groupMembersBtn.addEventListener("click", async function () {
            await loadGroupMembers();
            groupMembersOverlay.style.display = "flex";
        });

        // 그룹 이름 변경: 브라우저 기본 입력창(prompt)으로 새 이름을 받는다. 취소(null)나 빈 값이면 아무것도 하지 않는다.
        renameGroupBtn.addEventListener("click", async function () {
            const currentGroup = getCurrentFriend();
            const newName = prompt("새 그룹 이름을 입력하세요.", currentGroup ? currentGroup.name : "");
            if (newName === null) return;
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

        // 그룹 관리 창 닫기(닫기 버튼, 바깥 클릭).
        closeGroupMembersBtn.addEventListener("click", function () {
            groupMembersOverlay.style.display = "none";
        });

        groupMembersOverlay.addEventListener("click", function (event) {
            if (event.target === groupMembersOverlay) groupMembersOverlay.style.display = "none";
        });

        // 그룹 나가기: 나간 뒤에는 남은 대화방 중 첫 번째를 열고, 하나도 없으면 빈 화면으로 돌아간다.
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

        // 그룹 종료(방장 전용): 이전 대화는 볼 수 있지만 새 메시지는 보낼 수 없게 된다.
        disableGroupBtn.addEventListener("click", function () {
            showConfirm("그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.", async function (ok) {
                if (!ok) return;
                const response = await fetch(`/api/conversations/${currentConversationID}/disable`, {method:"POST"});
                const result = await response.json();
                if (!response.ok || !result.success) return showToast(result.error || "종료하지 못했습니다.", "error");
                groupMembersOverlay.style.display="none"; await loadFriends(); await readMessages(); updateBlockState(); showToast("그룹 채팅을 종료했습니다.");
            });
        });

        /**
         * 그룹에 초대할 수 있는 친구(아직 멤버가 아닌 사람) 목록을 체크박스로 그린다.
         */
        function renderInviteMemberList() {
            inviteMemberList.innerHTML = "";

            // 이미 그룹에 있는 사람은 후보에서 뺀다. 서버가 이미 멤버인 사용자는 조용히 건너뛰긴 하지만, 화면에서도 보이지 않게 한다.
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

        // 그룹 초대 창: 열 때마다 초대 가능한 친구 목록을 새로 그린다.
        openInviteMemberBtn.addEventListener("click", function () {
            renderInviteMemberList();
            inviteMemberOverlay.style.display = "flex";
        });

        // 그룹 초대 창 닫기(취소 버튼, 바깥 클릭).
        inviteMemberCancelBtn.addEventListener("click", function () {
            inviteMemberOverlay.style.display = "none";
        });

        inviteMemberOverlay.addEventListener("click", function (event) {
            if (event.target === inviteMemberOverlay) inviteMemberOverlay.style.display = "none";
        });

        // 초대: 체크한 친구의 아이디를 서버로 보낸다. 한 명도 고르지 않으면 안내만 띄운다.
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

        /**
         * 친구 관리 패널의 친구 목록(friendDirectory)을 그린다.
         *
         * 친구마다 프로필 보기, 채팅방 열기, 차단/차단 해제, 친구 삭제 동작을 붙인다.
         * 차단·삭제처럼 되돌리기 어려운 동작은 확인 창을 거친다.
         */
        function renderFriendPanelList() {
            friendPanelList.innerHTML = "";

            friendDirectory.forEach(function (friend) {
                const item = document.createElement("div");
                item.className = "friend-panel-item";

                // 친구 항목에는 그룹이 없지만, 그룹에는 차단 개념이 적용되지 않는다는 규칙을 코드에 남겨 둔 것이다. 이미 차단했다면 '차단 해제' 아이콘을, 아니면 '차단' 아이콘을 보여 준다.
                const blockIconHTML = friend.isGroup
                    ? ""
                    : (friend.blockedByMe
                        ? `<span class="unblock-friend-icon" title="차단 해제"><i class="fa-solid fa-lock-open"></i></span>`
                        : `<span class="block-friend-icon" title="차단"><i class="fa-solid fa-ban"></i></span>`);

                item.innerHTML = `
                    <button type="button" class="friend-panel-profile-trigger" aria-label="${escapeHTML(friend.name)} 프로필 보기">
                        <img src="${escapeHTML(friend.peerProfileImage || "/static/default_profile.png")}" alt="">
                        <span>${escapeHTML(friend.name)}</span>
                    </button>
                    <div class="friend-panel-actions">
                        <button type="button" class="open-friend-chat-icon" title="채팅방 열기" aria-label="${escapeHTML(friend.name)}님과 채팅하기"><i class="fa-solid fa-comment-dots"></i></button>
                        ${blockIconHTML}
                        <span class="delete-friend-icon" title="친구 삭제"><i class="fa-solid fa-trash"></i></span>
                    </div>
                `;

                item.querySelector(".friend-panel-profile-trigger").addEventListener("click", function () {
                    openProfileCard(friend);
                });

                // 채팅방 열기: 숨겨 둔 1:1 방을 목록에 되살린 뒤(서버), 그 방을 열고 읽음 처리한다.
                item.querySelector(".open-friend-chat-icon").addEventListener("click", async function () {
                    const response = await fetch(`/api/friends/${friend.peerId}/conversation`, { method: "POST" });
                    const result = await response.json();
                    if (!response.ok || !result.success) {
                        showAlert(result.error || "채팅방을 열지 못했습니다.");
                        return;
                    }

                    await loadFriends();
                    const conversation = friends.find(function (entry) {
                        return entry.id === result.conversationId;
                    });
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
                    setTimeout(function () { input.focus(); }, 10);
                });

                // 친구 삭제: 친구 관계만 끊는다. 대화 기록은 남는다.
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

        /**
         * 새 그룹에 넣을 친구를 고르는 체크박스 목록을 그린다.
         */
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

        // 새 그룹 만들기 창: 열 때 이름 입력을 비우고 친구 목록을 새로 그린다.
        openNewGroupBtn.addEventListener("click", function () {
            newGroupNameInput.value = "";
            renderNewGroupMemberList();
            newGroupOverlay.style.display = "flex";
        });

        // 새 그룹 창 닫기(취소 버튼, 바깥 클릭).
        newGroupCancelBtn.addEventListener("click", function () {
            newGroupOverlay.style.display = "none";
        });

        newGroupOverlay.addEventListener("click", function (event) {
            if (event.target === newGroupOverlay) newGroupOverlay.style.display = "none";
        });

        // 새 그룹 만들기: 이름과 친구 선택을 확인한 뒤 서버에 만들고, 성공하면 그 대화방을 바로 연다.
        newGroupCreateBtn.addEventListener("click", async function () {
            const name = newGroupNameInput.value.trim();
            if (!name) {
                showAlert("그룹 이름을 입력해주세요.")
                return;
            }

            const checkedUsernames = Array.from(newGroupMemberList.querySelectorAll("input[type=checkbox]:checked"))
                .map(function (box) { return box.value; });

            // 그룹은 나를 포함해 3명 이상이어야 하므로 친구를 2명 이상 골라야 한다(서버도 같은 규칙을 검사한다).
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

        // 친구 추가: 버튼을 누르거나 입력창에서 Enter를 치면 아이디로 요청을 보낸다.
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

        /**
         * 아이디로 사용자를 찾아 프로필 카드와 '친구 추가' 버튼(이미 친구면 '친구' 표시)을 보여 준다. 아이디를 정확히 입력해야 한다.
         */
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

        // 친구 관리 패널 열기/닫기 토글.
        friendPanelTab.addEventListener("click", function () {
            if (friendPanel.classList.contains("open")) closeFriendPanel();
            else openFriendPanel();
        });

        // 친구 패널 닫기 버튼.
        closeFriendPanelBtn.addEventListener("click", function () {
            closeFriendPanel();
        });

        // 메시지함 열기와 닫기(닫기 버튼, 바깥 클릭).
        friendInboxBtn.addEventListener("click", openFriendInbox);
        friendInboxCloseBtn.addEventListener("click", closeFriendInbox);
        friendInboxOverlay.addEventListener("click", function (event) {
            if (event.target === friendInboxOverlay) closeFriendInbox();
        });
        // 메시지함 탭: '받은 요청'과 '보낸 요청' 중 선택한 목록만 보여 준다.
        friendInboxTabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                const incomingTab = tab.dataset.inboxTab === "incoming";
                friendInboxTabs.forEach(function (button) { button.classList.toggle("active", button === tab); });
                friendRequestList.hidden = !incomingTab;
                outgoingFriendRequestList.hidden = incomingTab;
            });
        });

        // 모바일 뒤로가기: 대화를 닫지 않고 목록만 보여 준다. 같은 방을 다시 눌러도 메시지가 유지된다.
        mobileBackBtn.addEventListener("click", function () {
            closeMobileChat();
            setMobileNavActive(mobileChatNavBtn);
        });

        // 모바일 채팅 '더보기' 시트 열기/닫기. 그룹 대화일 때만 그룹 전용 항목이 보이도록 클래스를 붙인다.
        mobileChatMoreBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            const isOpen = mobileChatActionsSheet.classList.toggle("open");
            mobileChatActionsSheet.classList.toggle("group-chat", !!(getCurrentFriend() && getCurrentFriend().isGroup));
            mobileChatActionsSheet.setAttribute("aria-hidden", String(!isOpen));
        });

        // '더보기' 시트의 항목 처리. 고정·알림 끄기는 여기서 직접 서버에 저장하고,
        // 테마·사진 모아보기·그룹 관리는 같은 기능의 PC용 버튼을 대신 눌러 동작을 재사용한다.
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

        /**
         * 현재 대화방의 개인 설정(is_pinned, is_muted) 하나를 서버에 저장하고 목록과 헤더를 갱신한다. 실패하면 오류를 던진다.
         */
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

        // 오른쪽 '현재 대화' 패널의 고정·알림 끄기 버튼. 누를 때마다 현재 값을 반대로 저장한다.
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

        // 바깥을 누르면 모바일 '더보기' 시트를 닫는다.
        document.addEventListener("click", function (event) {
            if (!mobileChatActionsSheet.contains(event.target) && !mobileChatMoreBtn.contains(event.target)) {
                closeMobileChatActions();
            }
        });

        // 휴대폰을 가로로 돌리거나 PC 폭으로 넓히면 모바일 전용 상태를 모두 닫아 데스크톱 2단 레이아웃으로 되돌린다.
        window.addEventListener("resize", function () {
            if (!isMobileViewport()) {
                closeMobileChat();
                closeMobileChatActions();
                document.body.classList.remove("mobile-friends-open", "mobile-settings-open");
            }
        });

        // ============================================================
        // 설정 메뉴 / 하단 메뉴 / 채팅 테마 / 프로필 편집
        // ============================================================
        // 톱니바퀴 버튼: 설정 메뉴를 연다. 바깥 클릭 처리(document 클릭)와 겹치지 않도록 이벤트 전파를 막는다.
        sideNavSettings.addEventListener("click", function (event) {
            event.stopPropagation();
            openSettingsMenu(sideNavSettings);
        });

        // 모바일 하단 메뉴: 채팅 목록 · 친구 관리 · 프로필 · 설정을 각각 한 번에 열고, 서로 겹쳐 열려 있던 패널은 닫는다.
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

        // 설정 메뉴 바깥을 누르면 메뉴를 닫는다.
        document.addEventListener("click", function (event) {
            if (!settingsMenu.contains(event.target) && !sideNavSettings.contains(event.target) && !mobileSettingsNavBtn.contains(event.target)) {
                closeSettingsMenu();
            }
        });

        // 모바일 시트 뒤의 어두운 배경을 누르면 설정 메뉴와 친구 패널을 닫는다.
        mobileSheetBackdrop.addEventListener("click", function () {
            closeSettingsMenu();
            closeFriendPanel();
        });

        // 채팅 테마 창 열기: 현재 대화방의 테마가 속한 분류 탭을 먼저 보여 준다. 대화방이 선택되지 않았으면 안내만 띄운다.
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

        // 채팅 테마 창 닫기(닫기 버튼, 바깥 클릭).
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

        // 테마 선택: 서버에 저장하면 대화방 멤버 모두의 화면에 적용되고, 바꾼 사실이 시스템 메시지로 남는다.
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

        // 로그아웃: 확인을 받은 뒤 서버 세션을 끝내고 로그인 화면으로 이동한다.
        logoutBtn.addEventListener("click", function () {
            closeSettingsMenu();

            showConfirm("로그아웃 하시겠습니까?", async function (confirmLogout) {
                if (!confirmLogout) return;
                await fetch("/api/logout", { method: "POST" });
                window.location.href = "/login";
            });
        });

        /**
         * 내 프로필 편집창을 연다. 저장 전 상태(사진·이름)를 기억해 두었다가 취소하면 되돌리고, 소개글·공개 범위·배경 사진은 서버에서 불러온다.
         */
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
            } catch (error) { }
            myProfileOverlay.style.display = "flex";
        }

        // 프로필 편집 버튼과 닫기(닫기 버튼, 바깥 클릭은 취소와 같다).
        editProfileBtn.addEventListener("click", openProfileEditor);

        // 취소: 저장하지 않은 사진 변경 내용을 버리고 편집 전 모습으로 되돌린다.
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

        // 저장: 사진(변경 또는 삭제) → 표시 이름 → 소개글·공개 범위 순서로 서버에 저장한다.
        // 중간 단계가 실패하면 그 자리에서 멈추고 오류를 보여 준다.
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

        // 배경 사진은 고르는 즉시 서버에 올린다(프로필 저장 버튼과 별개로 바로 반영).
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
        /**
         * 프로필 편집창의 배경 사진 미리보기를 갱신한다. 사진이 없으면 '배경사진 없음' 문구를 보여 준다.
         */
        function updateProfileCoverPreview(imageUrl) {
            profileCoverPreview.style.backgroundImage = imageUrl ? `url("${imageUrl}")` : "";
            profileCoverPreview.classList.toggle("has-image", Boolean(imageUrl));
            profileCoverPreview.innerHTML = imageUrl ? "" : '<span><i class="fa-regular fa-image"></i> 배경사진 없음</span>';
        }
        // 배경 사진 삭제: 서버에서 지우고 미리보기를 비운다.
        removeCoverImageBtn.addEventListener("click", async function () { const response = await fetch("/api/account/cover-image", {method:"DELETE"}); const result=await response.json(); if (result.success) updateProfileCoverPreview(null); showToast(result.success ? "배경사진을 제거했습니다." : result.error, result.success ? undefined : "error"); });
        // 프로필 카드 닫기(닫기 버튼, 바깥 클릭).
        profileCardClose.addEventListener("click", function () { profileCardOverlay.style.display="none"; });
        profileCardOverlay.addEventListener("click", function(event){ if(event.target===profileCardOverlay) profileCardOverlay.style.display="none"; });

        // ============================================================
        // 프로필 카드 ⋮ 메뉴 (신고하기 / 차단하기)
        // ============================================================
        profileCardMenuBtn.addEventListener("click", function (event) {
            event.stopPropagation();
            const willOpen = profileCardMenu.hidden;
            profileCardMenu.hidden = !willOpen;
            profileCardMenuBtn.setAttribute("aria-expanded", String(willOpen));
        });
        // 프로필 카드의 ⋮ 메뉴 바깥을 누르면 메뉴를 닫는다.
        document.addEventListener("click", function (event) {
            if (profileCardMenu.hidden) return;
            if (profileCardMenu.contains(event.target) || event.target === profileCardMenuBtn) return;
            profileCardMenu.hidden = true;
            profileCardMenuBtn.setAttribute("aria-expanded", "false");
        });
        // 차단: 확인을 받은 뒤 차단하고, 목록과 입력 잠금 상태를 갱신한다.
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
        // 신고: 메시지 신고와 같은 신고 창을 쓰되, 대상 종류를 '사용자'로 기록한다.
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

        // ============================================================
        // 전송 버튼 / 엔터 입력
        // ============================================================
        button.addEventListener("click", function () { sendMessage(); });

        input.addEventListener("keydown", function (event) {
            // Enter는 전송, Shift+Enter는 줄바꿈이다.
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        });

        // 메시지 메뉴와 첨부 메뉴 바깥을 누르면 닫는다.
        document.addEventListener("click", function (event) {
            // 메시지 메뉴·첨부 메뉴 바깥을 누르면 둘 다 닫는다.
            if (!messageMenu.contains(event.target)) closeMessageMenu();
            if (!attachMenu.contains(event.target)) attachMenu.style.display = "none";
        });

        /**
         * 메시지 메뉴를 닫는다. 화면 밖으로 치워 두어 다음에 열 때 위치 계산이 이전 값에 영향받지 않게 한다.
         */
        function closeMessageMenu() {
            messageMenu.style.display = "none";
            messageMenu.style.pointerEvents = "none";
            messageMenu.style.left = "-9999px";
            messageMenu.style.top = "-9999px";
        }

        // ============================================================
        // 반응(이모지) 선택 팝업
        // ============================================================
        // 이모지를 누르면 서버가 반응을 추가(이미 있으면 취소)하고, 목록을 다시 그린 뒤 선택창을 닫는다.
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

        // 반응 선택창 바깥을 누르면 닫는다(SPAN은 이모지 선택이므로 제외).
        document.addEventListener("click", function (event) {
            if (!reactionPicker.contains(event.target) && event.target.tagName !== "SPAN") {
                reactionPicker.style.display = "none";
            }
        });

        // ============================================================
        // 메시지 검색 UI
        // ============================================================
        // 검색 바 열기/닫기. 닫으면 검색어를 비워 강조 표시도 함께 없앤다.
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

        // 검색어를 입력할 때마다 바로 검색한다.
        searchInput.addEventListener("input", function () { performSearch(this.value.trim()); });

        searchClose.addEventListener("click", function () {
            searchBar.style.display = "none";
            searchInput.value = "";
            performSearch("");
        });

        // 다음/이전 검색 결과로 이동한다. 끝에서 처음으로, 처음에서 끝으로 이어지도록 나머지 연산을 쓴다.
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

        // ============================================================
        // 드래그 앤 드롭 사진 첨부
        // ============================================================
        // dragover를 막아 두어야 drop 이벤트를 받을 수 있다(브라우저 기본 동작은 파일을 새 탭에서 열어 버린다).
        messages.addEventListener("dragover", function (e) { e.preventDefault(); });

        // 끌어다 놓은 파일이 이미지일 때만 보낸다.
        messages.addEventListener("drop", function (e) {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (!file || !file.type.startsWith("image")) {
                showAlert("이미지 파일만 첨부할 수 있습니다.");
                return;
            }
            sendImage(file);
        });

        // ============================================================
        // 사진 갤러리 모아보기
        // ============================================================
        /**
         * 현재 대화방에서 주고받은 사진만 모아 격자로 보여 준다. 사진이 없으면 안내 문구를 보여 준다.
         */
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

        // 사진 모아보기: 열 때마다 최신 사진 목록을 새로 그린다.
        galleryToggleBtn.addEventListener("click", function () {
            renderGallery();
            galleryOverlay.style.display = "flex";
        });

        closeGallery.addEventListener("click", function () { galleryOverlay.style.display = "none"; });

        galleryOverlay.addEventListener("click", function (event) {
            if (event.target === galleryOverlay) galleryOverlay.style.display = "none";
        });

        // 갤러리에서 사진을 누르면 갤러리를 닫고 큰 이미지로 연다(이벤트 위임: 격자 하나에만 리스너를 둔다).
        galleryGrid.addEventListener("click", function (event) {
            const img = event.target.closest("img[data-image]");
            if (!img) return;
            galleryOverlay.style.display = "none";
            modalImage.src = img.dataset.image;
            imageModal.style.display = "flex";
        });

        // ============================================================
        // 계정 설정 · 업데이트 알림 · 브라우저 알림
        // ============================================================
        accountSettingsItem.addEventListener("click", function () {
    closeSettingsMenu();
    accountSettingsOverlay.style.display = "flex";
});

// 서버가 알려 준 가장 최근 업데이트 버전(커밋 해시 앞 7자리). 사용자가 마지막으로 확인한 버전과 비교해 NEW 배지를 보여 준다.
let currentUpdateVersion = "";

/**
 * 새 업데이트가 있으면 설정 메뉴의 NEW 배지를 보여 준다. 사용자가 알림 설정을 연 적 있는 버전이면 숨긴다.
 */
function updateUpdateNoticeBadge() {
    if (!currentUpdateVersion) return;
    const seenVersion = localStorage.getItem("seenUpdateVersion");
    updateNoticeBadge.style.display =
        seenVersion === currentUpdateVersion ? "none" : "inline-block";
}

/**
 * 업데이트 목록을 지정한 영역에 그린다. 텍스트는 textContent로만 넣어 외부(GitHub) 문구가 HTML로 해석되지 않게 한다.
 */
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

/**
 * 최근 업데이트 내역을 서버에서 가져와 알림 설정 창에 보여 주고 NEW 배지 상태를 갱신한다.
 */
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

/**
 * '이전 업데이트' 창을 열고 전체 내역을 불러온다.
 */
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

// 알림 설정을 열면 최신 업데이트를 확인한 것으로 보고 그 버전을 기록한 뒤 NEW 배지를 끈다.
notificationSettingsItem.addEventListener("click", function () {
    closeSettingsMenu();
    notificationSettingsOverlay.style.display = "flex";

    if (currentUpdateVersion) {
        localStorage.setItem("seenUpdateVersion", currentUpdateVersion);
    }
    updateUpdateNoticeBadge();
});

// 알림 설정 창 닫기.
notificationSettingsCloseBtn.addEventListener("click", function () {
    notificationSettingsOverlay.style.display = "none";
});

// 브라우저 알림 스위치의 초기 상태. 사용자가 켜 두었고(localStorage) 브라우저 권한도 실제로 허용된 경우에만 켜진 것으로 본다.
browserNotificationToggle.checked = localStorage.getItem("browserNotifications") === "enabled" && "Notification" in window && Notification.permission === "granted";

/**
 * VAPID 공개키(URL-safe base64)를 푸시 구독에 필요한 바이트 배열로 바꾼다. 길이를 4의 배수로 채우고 - _ 를 표준 문자로 되돌린다.
 */
function urlBase64ToUint8Array(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = atob(base64);
    return Uint8Array.from(rawData, character => character.charCodeAt(0));
}

/**
 * 웹 푸시 구독을 만들어 서버에 등록한다.
 *
 * 서버에 푸시 설정(VAPID 키)이 없으면 아무것도 하지 않는다. 서비스 워커는 /static/push-sw.js를 쓰며,
 * 이미 구독이 있으면 새로 만들지 않고 그 정보를 서버에 다시 보낸다.
 */
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

// 알림 스위치: 켤 때 브라우저 권한을 요청하고, 허용되면 푸시 구독까지 등록한다. 거부되면 스위치를 되돌린다.
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

/**
 * 새 메시지가 왔을 때 브라우저 알림을 띄운다.
 *
 * 화면을 보고 있는 중이거나, 알림을 꺼 둔 경우, 알림을 끈 대화방이면 띄우지 않는다.
 */
function showBrowserNotification(conversationId) {
    if (document.visibilityState === "visible" || localStorage.getItem("browserNotifications") !== "enabled") return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const friend = friends.find(function (item) { return item.id === conversationId; });
    if (!friend || friend.isMuted) return;
    new Notification(friend.name, { body: friend.message || "새 메시지가 도착했습니다.", icon: "/static/favicon-180x180.png" });
}

// 알림을 켜 둔 상태로 다시 접속하면 푸시 구독을 최신 상태로 유지한다(실패해도 화면 사용에는 영향 없다).
if (browserNotificationToggle.checked) {
    registerPushSubscription().catch(function () {});
}

// 이전 업데이트 창 열기와 닫기(닫기 버튼, 바깥 클릭).
previousUpdatesBtn.addEventListener("click", openPreviousUpdates);
previousUpdatesCloseBtn.addEventListener("click", function () {
    previousUpdatesOverlay.style.display = "none";
});
previousUpdatesOverlay.addEventListener("click", function (event) {
    if (event.target === previousUpdatesOverlay) previousUpdatesOverlay.style.display = "none";
});

// ============================================================
// 고객 문의 · 운영 경고
// ============================================================
supportAttachment.addEventListener("change", function () {
    const file = supportAttachment.files[0];
    if (!file) {
        supportAttachmentName.textContent = "첨부 파일 없음";
        return;
    }
    // 첨부 용량(10MB)은 서버 제한(SUPPORT_ATTACHMENT_MAX_BYTES)과 같다. 업로드 전에 미리 알려 불필요한 전송을 막는다.
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

// 문의 전송: 10자 이상인지 확인하고, 전송하는 동안 버튼을 잠근다. 성공하면 양식을 비우고 내역을 다시 불러온다.
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

/**
 * 내가 보낸 문의 내역(상태, 내용, 관리자 답변)을 불러와 그린다. 답변 대기 중인 문의만 수정할 수 있다.
 */
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

// 아직 확인하지 않은 운영 경고 목록. 하나씩 차례로 보여 주고 확인하면 다음 경고로 넘어간다.
let unreadModerationWarnings = [];

/**
 * 확인하지 않은 경고 중 가장 오래된 것을 팝업으로 보여 준다. 남은 경고가 없으면 팝업을 닫는다.
 */
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

/**
 * 접속할 때 읽지 않은 운영 경고를 가져와 보여 준다.
 */
async function loadUnreadModerationWarnings() {
    try {
        const response = await fetch("/api/moderation/warnings");
        if (!response.ok) return;
        unreadModerationWarnings = await response.json();
        showNextModerationWarning();
    } catch (error) {
    }
}

/**
 * 내가 받은 운영 경고 기록 전체를 도움말 창에 보여 준다.
 */
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

// '확인했습니다': 서버에 읽음을 기록한 뒤 다음 경고를 보여 준다. 처리 중에는 버튼을 잠근다.
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

// 문의 내역의 수정·삭제 버튼 처리(이벤트 위임). 버튼의 data-edit-inquiry / data-delete-inquiry 값이 문의 ID다.
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

/**
 * 인증번호 카운트다운을 멈춘다. hide가 true면 타이머 표시도 숨긴다. 인증 성공·재발송·만료 때 같은 방식으로 쓴다.
 */
function stopInlineVerificationTimer(timerElement, hide = false) {
    if (timerElement._interval) clearInterval(timerElement._interval);
    timerElement._interval = null;
    if (hide) {
        timerElement.textContent = "";
        timerElement.hidden = true;
    }
}

/**
 * 인증번호 유효시간(3분 = 180초) 카운트다운을 시작하고, 0이 되면 '만료됨'으로 바꾼 뒤 onExpire를 호출한다. 서버의 인증번호 유효시간과 같아야 한다.
 */
function startInlineVerificationTimer(timerElement, onExpire) {
    stopInlineVerificationTimer(timerElement);
    let remaining = 180;
    timerElement.hidden = false;

    /**
     * 남은 시간을 mm:ss로 표시하고 1초 줄인다. 0이 되면 타이머를 멈추고 만료 처리를 호출한다.
     */
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

// ============================================================
// 계정 복구 (아이디 찾기 / 비밀번호 재설정)
// ============================================================
// 로그인 화면과 같은 서버 API를 재사용한다. 화면만 다를 뿐 인증번호 발송·검증 규칙은 서버 한 곳에서 관리한다.
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

// 비밀번호 재설정 1단계 - 인증번호 받기. 서버는 가입 여부와 상관없이 같은 안내 문구를 돌려준다.
// 성공하면 인증번호 입력칸을 열고 3분 카운트다운을 시작하며, 이전 인증 상태는 모두 초기화한다.
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

// 2단계 - 인증번호 확인. 맞으면 입력칸을 잠그고(readOnly) 타이머를 멈춘 뒤 '인증 완료'로 표시한다.
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

// 이메일을 고치면 이미 받은 인증번호는 다른 주소용이므로 인증 상태와 입력칸을 모두 접는다.
helpResetEmail.addEventListener("input", function () {
    if (!helpResetCodeSent) return;
    helpResetCodeSent = false;
    helpResetVerified = false;
    stopInlineVerificationTimer(helpResetCodeTimer, true);
    helpResetFields.hidden = true;
});

// 3단계 - 새 비밀번호로 변경. 인증을 마치지 않았다면 요청하지 않는다(서버도 인증번호를 다시 검증한다).
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

/**
 * 공개된 공지사항을 가져와 도움말 창에 보여 준다. 제목과 날짜는 이스케이프해서 넣는다.
 */
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

// 내가 쓴 리뷰의 ID. 있으면 작성 양식이 '수정 모드'가 되고(리뷰 수정·삭제 버튼), 없으면 '등록 모드'다. 리뷰는 한 계정당 하나다.
let myReviewId = null;
/**
 * 내 리뷰가 있으면 수정 모드(내용 채움, 삭제 버튼 표시)로, 없으면 등록 모드로 양식을 바꾼다.
 */
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
/**
 * 전체 리뷰 목록을 그리고, 그중 내 리뷰를 찾아 작성 양식 모드를 맞춘다.
 */
async function loadReviews() {
    try {
        const reviews = await fetch("/api/reviews").then(response => response.json());
        reviewList.innerHTML = reviews.length ? reviews.map(review => `<article class="update-history-item${review.isMine ? " review-list-item-mine" : ""}"><div><strong>${"★".repeat(review.rating)}${"☆".repeat(5-review.rating)} · ${escapeHTML(review.display_name || review.username)}${review.isMine ? " (나)" : ""}</strong><span>${escapeHTML(review.created_at.slice(0,10))}</span></div><p>${escapeHTML(review.content)}</p>${review.admin_reply ? `<p><strong>관리자 답장</strong><br>${escapeHTML(review.admin_reply)}</p>` : ""}</article>`).join("") : "<p>첫 번째 리뷰를 남겨주세요.</p>";
        setReviewComposeMode(reviews.find(review => review.isMine) || null);
    } catch (error) { reviewList.innerHTML=""; }
}
// 내 리뷰가 있으면 수정(PATCH), 없으면 새로 등록(POST)한다. 별점·글자 수 검증은 서버가 한다.
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
// 내 리뷰 삭제: 확인을 받은 뒤 지우고 양식을 비운다.
reviewDeleteBtn.addEventListener("click", async function () {
    if (!myReviewId || !confirm("작성한 리뷰를 삭제할까요?")) return;
    const response = await fetch(`/api/reviews/${myReviewId}`, {method:"DELETE"});
    const result = await response.json();
    if (!response.ok || !result.success) return showToast(result.error || "리뷰 삭제에 실패했습니다.", "error");
    reviewRating.value=""; reviewContent.value=""; loadReviews(); showToast("리뷰를 삭제했습니다.");
});

        // '공지사항·도움말' 창을 열 때 공지, 내 문의 내역, 받은 운영 경고를 한꺼번에 최신으로 불러온다.
        helpItem.addEventListener("click", function () {
            closeSettingsMenu();
            loadPublicNotices();
            loadSupportInquiryHistory();
            loadModerationWarningHistory();
            helpOverlay.style.display = "flex";
        });
        // 도움말 창 닫기.
        helpCloseBtn.addEventListener("click", function () {
            helpOverlay.style.display = "none";
        });

        // '사용자 리뷰' 창을 열 때 리뷰 목록을 새로 불러온다.
        reviewsItem.addEventListener("click", function () {
            closeSettingsMenu();
            loadReviews();
            reviewsOverlay.style.display = "flex";
        });
        // 리뷰 창 닫기(닫기 버튼, 바깥 클릭).
        reviewsCloseBtn.addEventListener("click", function () { reviewsOverlay.style.display = "none"; });
        reviewsOverlay.addEventListener("click", function (event) { if (event.target === reviewsOverlay) reviewsOverlay.style.display = "none"; });

accountSettingsCloseBtn.addEventListener("click", function () {
    accountSettingsOverlay.style.display = "none";
});

// 아이디 변경: 새 아이디와 현재 비밀번호를 서버로 보낸다. 규칙(영문 소문자·숫자 5자 이상) 검사는 서버가 한다.
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

// 이메일 변경 1단계 - 새 이메일로 인증번호 보내기. 성공하면 3분 카운트다운을 시작한다.
// 만료되면 인증번호 입력을 막고 다시 요청하도록 안내한다.
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

// 2단계 - 인증번호 확인. 맞으면 입력칸을 잠그고 '인증 완료'로 표시한다.
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

// 이메일 주소를 다시 고치면 이전 인증은 무효이므로 인증 상태를 초기화하고 인증번호를 다시 받도록 안내한다.
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

// 3단계 - 이메일 변경 저장. 인증을 마쳤고 현재 비밀번호가 맞아야 서버가 변경해 준다.
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

// 비밀번호 변경: 새 비밀번호와 확인 입력이 같은지 먼저 확인한 뒤 서버로 보낸다(규칙 검사는 서버가 한다).
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

// 계정 삭제: 비밀번호를 입력받아 확인 창을 띄운 뒤 삭제를 요청한다. 되돌릴 수 없으므로 서버도 비밀번호를 다시 검사한다. 성공하면 로그인 화면으로 이동한다.
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

// ============================================================
// 원형 프로필/그룹 사진 편집기
// ============================================================
// 원본을 임의로 줄이지 않고, 사용자가 고른 영역만 512px 정사각형으로 저장한다.
// 화면의 편집 영역은 320px 정사각형이고, 저장할 때 512/320 비율로 확대해서 그린다.
const CROP_VIEWPORT_SIZE = 320;
// 편집 중인 사진의 상태: 대상(profile/group), 이미지, 현재 배율과 기본 배율, 이미지 왼쪽 위 좌표(x, y), 드래그 상태.
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

/**
 * 사진이 편집 영역을 벗어나 빈 공간이 생기지 않도록 이동 범위를 제한한다. 사진은 항상 영역을 꽉 채워야 한다.
 */
function constrainCropPosition() {
    const renderedWidth = cropState.image.naturalWidth * cropState.scale;
    const renderedHeight = cropState.image.naturalHeight * cropState.scale;
    cropState.x = Math.min(0, Math.max(CROP_VIEWPORT_SIZE - renderedWidth, cropState.x));
    cropState.y = Math.min(0, Math.max(CROP_VIEWPORT_SIZE - renderedHeight, cropState.y));
}

/**
 * 현재 배율과 위치로 사진을 편집 캔버스에 그린다. 사진이 투명한 부분은 연한 회색으로 채운다.
 */
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

/**
 * 사진 편집창을 닫고 편집 상태를 비운다.
 */
function closeImageCropper() {
    cropState.target = null;
    cropState.image = null;
    cropState.dragging = false;
    imageCropOverlay.style.display = "none";
}

/**
 * 선택한 이미지 파일로 편집창을 연다.
 *
 * 처음에는 영역을 꽉 채우는 최소 배율로 가운데에 놓는다. target은 'profile'(내 프로필) 또는 'group'(그룹 사진).
 * 브라우저가 MIME 형식을 알려 주지 않는 경우를 위해 확장자도 함께 확인한다.
 */
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
        // 짧은 변이 영역을 꽉 채우는 배율이 기본(100%)이다. 이보다 작게 줄일 수는 없다.
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

/**
 * 자른 그룹 사진을 서버에 저장하고 화면의 그룹 사진을 바꾼다. 실패하면 오류를 던진다.
 */
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

// 확대/축소: 영역의 중심에 보이던 지점이 그대로 중심에 남도록 위치를 다시 계산한다.
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

// 사진 이동(드래그): 포인터를 캔버스에 붙잡아(pointer capture) 영역 밖으로 나가도 드래그가 이어지게 한다. 마우스·터치를 함께 지원한다.
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
    // 화면에 보이는 캔버스 크기가 CSS로 달라질 수 있어, 포인터 이동량을 캔버스 좌표로 환산한다.
    const displayScale = CROP_VIEWPORT_SIZE / bounds.width;
    cropState.x += (event.clientX - cropState.pointerX) * displayScale;
    cropState.y += (event.clientY - cropState.pointerY) * displayScale;
    cropState.pointerX = event.clientX;
    cropState.pointerY = event.clientY;
    constrainCropPosition();
    renderCropPreview();
});

/**
 * 드래그를 끝내고 붙잡아 둔 포인터를 놓는다.
 */
function finishCropDrag(event) {
    cropState.dragging = false;
    if (imageCropCanvas.hasPointerCapture(event.pointerId)) imageCropCanvas.releasePointerCapture(event.pointerId);
}
imageCropCanvas.addEventListener("pointerup", finishCropDrag);
imageCropCanvas.addEventListener("pointercancel", finishCropDrag);

// 적용: 편집 영역을 512px 정사각형 JPEG(품질 0.94)로 만든다.
// 내 프로필 사진은 '저장' 버튼을 눌러야 서버에 올라가도록 미리 보관만 하고(pendingProfileImageData), 그룹 사진은 바로 업로드한다.
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

// 그룹 사진 변경: 파일을 고르면 편집창이 열린다. 같은 파일을 다시 골라도 change가 일어나도록 선택값은 비운다.
changeGroupPhotoBtn.addEventListener("click", function () {
    groupPhotoInput.click();
});

groupPhotoInput.addEventListener("change", function () {
    const file = groupPhotoInput.files[0];
    if (!file) return;
    openImageCropper(file, "group");
    groupPhotoInput.value = "";
});

// 그룹 사진 삭제: 확인을 받은 뒤 서버에서 지우고 기본 이미지로 되돌린다.
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

// 내 프로필 사진 변경: 버튼이나 사진 자체(키보드 Enter/Space 포함)를 누르면 파일 선택창이 열린다.
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

// 프로필 사진 삭제는 바로 지우지 않고 '삭제 예약' 상태로 두었다가, 프로필 저장 버튼을 눌러야 서버에 반영된다.
removeProfilePicBtn.addEventListener("click", function () {
    showConfirm("프로필 사진을 삭제하시겠습니까?", async function (confirmRemove) {
        if (!confirmRemove) return;
        pendingProfileImageData = null;
        pendingProfileImageRemoval = true;
        profileModalPic.innerHTML = `<i class="fa-solid fa-circle-user"></i>`;
    });
});

// 동영상 첨부: 파일을 고르면 바로 전송한다(형식·크기 검사는 서버가 한다).
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

/**
 * 동영상 파일 하나를 FormData로 서버에 보낸다. 전송 중에는 입력창을 잠그고, 성공하면 목록을 새로 불러온다.
 */
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

        // ============================================================
        // 메시지 좌우 스와이프로 답장
        // ============================================================
        // 스와이프 상태: 시작 위치, 이동량, 대상 메시지 요소와 데이터. 60px 이상 밀면 답장으로 인식하고, 시각적으로는 최대 90px까지만 움직인다.
        let swipeStartX = 0;
        let swipeDeltaX = 0;
        let swipeTarget = null;
        let swipeChat = null;
        const SWIPE_THRESHOLD = 60;
        const SWIPE_MAX = 90;

        /**
         * 마우스와 터치 이벤트 모두에서 가로 좌표를 꺼낸다.
         */
        function getClientX(event) {
            return event.touches ? event.touches[0].clientX : event.clientX;
        }

        /**
         * 스와이프를 시작한다. 마우스는 왼쪽 버튼만 인정한다. 이동·종료 이벤트는 시작할 때만 문서에 붙이고 끝나면 뗀다.
         */
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

        /**
         * 손가락/마우스를 따라 메시지를 옆으로 움직이고, 밀린 정도에 따라 답장 아이콘을 서서히 보여 준다. 세로 스크롤과 충돌하지 않게 가로로 10px 넘게 움직이면 기본 스크롤을 막는다.
         */
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

        /**
         * 스와이프를 끝낸다. 메시지를 원래 자리로 되돌리고, 기준(60px) 이상 밀었다면 그 메시지를 답장 대상으로 정한다.
         */
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

        // ============================================================
        // 실시간 이벤트 (Socket.IO)
        // ============================================================
        // 서버와 웹소켓 연결을 만든다. 서버는 이벤트에 데이터를 거의 싣지 않고 '무엇이 바뀌었는지'만 알려 주며, 화면은 API로 최신 상태를 다시 가져온다.
        const socket = io();

        // 대화방 내용이 바뀌었다는 신호(전송·수정·삭제·고정·반응·그룹 변경).
        // 지금 보고 있는 방이면 읽음 처리 후 메시지를 다시 불러오고(250ms 안에 방금 새로고침했다면 생략), 아니어도 목록의 미리보기와 안 읽은 배지는 항상 갱신한다.
        socket.on("conversation_updated", async function (data) {
            if (data.conversationId === currentConversationID) {
                await fetch(`/api/conversations/${currentConversationID}/read`, { method: "POST" });
                if (Date.now() - lastMessageRefreshAt > 250) await readMessages();
            }
            await loadFriends();
            showBrowserNotification(data.conversationId);
            updateChatHeader(getCurrentFriend()); 
            readFriends();
            updateBlockState();
        });

        // 친구 관계가 바뀌었다는 신호(요청 도착·수락·거절, 차단·해제, 프로필 변경, 그룹 초대). 친구·대화방·요청 목록을 모두 새로 불러온다.
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

        // 1:1 대화방 상대의 접속 상태가 바뀌면 목록의 온라인 표시를 갱신한다.
        // 서버는 그 상대에게만 보내며, 목록 전체를 다시 받지 않고 이미 가진 항목의 isOnline만 고쳐 다시 그린다.
        socket.on("presence_updated", function (data) {
            const peerRooms = friends.filter(function (friend) {
                return !friend.isGroup && friend.peerId === data.userId;
            });
            let changed = false;
            peerRooms.forEach(function (friend) {
                if (friend.isOnline !== !!data.online) {
                    friend.isOnline = !!data.online;
                    changed = true;
                }
            });
            if (!changed) return;
            readFriends();
            // 지금 열어 둔 대화의 상대라면 헤더의 접속 표시도 갱신한다.
            const openFriend = peerRooms.find(function (friend) { return friend.id === currentConversationID; });
            if (openFriend) updateChatHeader(openFriend);
        });

        // 관리자가 내 계정을 정지한 경우: 사유를 보여 주고 로그인 화면으로 보낸다.
        socket.on("account_suspended", function (data) {
            showAlert(`이용이 정지되었습니다. 사유: ${data.reason || "운영 정책 위반"}`, function () {
                window.location.href = "/login";
            });
        });

        // 관리자가 내 계정을 삭제한 경우: 안내 후 로그인 화면으로 보낸다.
        socket.on("account_deleted", function () {
            showAlert("계정이 삭제되었습니다.", function () {
                window.location.href = "/login";
            });
        });

        // ============================================================
        // 초기 렌더링
        // ============================================================
        // 페이지를 열면 현재 상태를 한꺼번에 불러온다: 메시지(열린 방이 있다면), 대화방·친구 목록, 받은 요청, 업데이트 내역, 읽지 않은 운영 경고.
        readMessages();
        Promise.all([loadFriends(), loadFriendDirectory()]).then(updateBlockState);
        loadFriendRequests();
        loadUpdateHistory();
        loadUnreadModerationWarnings();
