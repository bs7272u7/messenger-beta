/*
 * 모던 UI의 메시지 입력창.
 *
 * - 입력창 오른쪽에 음성(마이크)·사진/동영상·파일 아이콘이 있고, 글이나 첨부가 있으면 전송 버튼으로 바뀐다.
 * - 사진·동영상은 고르는 순간 보내지 않고 입력창 위에 미리보기로 쌓아 둔다. 미리보기 줄에서 하나씩 뺄 수 있고,
 *   앞의 사진 버튼으로 더 추가할 수 있다. 전송 버튼을 누르면 쌓아 둔 것을 순서대로 보내고, 글이 있으면 마지막에 글을 보낸다.
 * - 파일(문서)과 음성 메시지는 예전처럼 기존 버튼의 동작을 그대로 쓴다.
 *
 * script.js 뒤에 로드되며, 서버의 기존 전송 API(사진·동영상)와 script.js의 전역 함수(sendMessage, readMessages 등)를 그대로 쓴다.
 */
(function () {
    "use strict";

    const $ = (selector) => document.querySelector(selector);
    const area = $(".input-area");
    const textarea = $("#message");
    const tray = $("#modern-attach-tray");
    const mediaInput = $("#modern-media-input");
    const micButton = $("#modern-mic-btn");
    const mediaButton = $("#modern-media-btn");
    const fileButton = $("#modern-file-btn");
    const sendButton = $("#send-btn");
    if (!area || !textarea || !tray || !mediaInput || !micButton || !mediaButton || !fileButton || !sendButton) return;

    const MAX_ITEMS = 10;
    const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
    const MAX_VIDEO_BYTES = 20 * 1024 * 1024;
    const VIDEO_TYPES = ["video/mp4", "video/webm", "video/quicktime"];

    let staged = []; // { id, file, kind: "image" | "video", url }
    let stagedConversation = null;
    let nextId = 1;
    let sending = false;

    // ------------------------------------------------------------------
    // 상태 표시: 글이나 첨부가 있으면 has-text(전송 버튼 표시), 첨부가 있으면 has-media(미리보기 줄 표시)
    // ------------------------------------------------------------------
    function sync() {
        area.classList.toggle("has-text", textarea.value.trim() !== "" || staged.length > 0);
        area.classList.toggle("has-media", staged.length > 0);
    }

    // script.js가 전송 후 input.value = ""처럼 코드로 값을 바꿀 때는 input 이벤트가 없으므로, 값 setter를 감싸서 함께 처리한다.
    const nativeValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
    Object.defineProperty(textarea, "value", {
        configurable: true,
        get: function () { return nativeValue.get.call(this); },
        set: function (next) {
            nativeValue.set.call(this, next);
            sync();
        }
    });
    textarea.addEventListener("input", sync);

    // ------------------------------------------------------------------
    // 미리보기 줄
    // ------------------------------------------------------------------
    function render() {
        tray.hidden = staged.length === 0;
        tray.innerHTML = "";
        if (!staged.length) {
            sync();
            return;
        }
        const add = document.createElement("button");
        add.type = "button";
        add.className = "mc-add";
        add.dataset.act = "add";
        add.setAttribute("aria-label", "사진·동영상 추가");
        add.innerHTML = '<i class="fa-regular fa-image"></i>';
        tray.appendChild(add);

        staged.forEach((item) => {
            const tile = document.createElement("div");
            tile.className = "mc-item";
            tile.dataset.id = item.id;
            if (item.kind === "image") {
                const image = document.createElement("img");
                image.src = item.url;
                image.alt = "";
                tile.appendChild(image);
            } else {
                const video = document.createElement("video");
                video.src = item.url + "#t=0.1"; // 첫 화면(약 0.1초)을 미리보기 이미지로 쓴다
                video.preload = "metadata";
                video.muted = true;
                video.playsInline = true;
                tile.appendChild(video);
                tile.insertAdjacentHTML("beforeend", '<span class="mc-play"><i class="fa-solid fa-circle-play"></i></span>');
            }
            tile.insertAdjacentHTML("beforeend", '<button type="button" class="mc-remove" data-act="remove" aria-label="삭제"><i class="fa-solid fa-xmark"></i></button>');
            tray.appendChild(tile);
        });
        sync();
    }

    function release(item) {
        URL.revokeObjectURL(item.url);
    }

    function removeStaged(id) {
        const item = staged.find((entry) => entry.id === id);
        if (item) release(item);
        staged = staged.filter((entry) => entry.id !== id);
        render();
    }

    function clearStaged() {
        staged.forEach(release);
        staged = [];
        stagedConversation = null;
        render();
    }

    function kindOf(file) {
        if (file.type.startsWith("image/")) return "image";
        if (VIDEO_TYPES.includes(file.type) || /\.(mp4|webm|mov)$/i.test(file.name)) return "video";
        return null;
    }

    /** 고른 파일을 검사해서 미리보기 줄에 쌓는다. 형식·크기·개수에 맞지 않는 것은 안내만 하고 건너뛴다. */
    function stage(files) {
        if (!currentConversationID) {
            showToast("먼저 채팅방을 선택해주세요.", "error");
            return;
        }
        if (staged.length && stagedConversation !== currentConversationID) clearStaged();
        stagedConversation = currentConversationID;
        let skipped = "";
        files.forEach((file) => {
            const kind = kindOf(file);
            if (!kind) skipped = "사진과 동영상(mp4, webm, mov)만 보낼 수 있습니다.";
            else if (staged.length >= MAX_ITEMS) skipped = `한 번에 ${MAX_ITEMS}개까지 보낼 수 있습니다.`;
            else if (kind === "image" && file.size > MAX_IMAGE_BYTES) skipped = "사진은 10MB 이하만 보낼 수 있습니다.";
            else if (kind === "video" && file.size > MAX_VIDEO_BYTES) skipped = "동영상은 20MB 이하만 보낼 수 있습니다.";
            else staged.push({ id: nextId++, file, kind, url: URL.createObjectURL(file) });
        });
        if (skipped) showToast(skipped, "error");
        if (!staged.length) stagedConversation = null;
        render();
        textarea.focus();
    }

    tray.addEventListener("click", (event) => {
        if (sending) return;
        const button = event.target.closest("[data-act]");
        if (!button) return;
        if (button.dataset.act === "add") mediaInput.click();
        else if (button.dataset.act === "remove") removeStaged(Number(button.closest(".mc-item").dataset.id));
    });

    // ------------------------------------------------------------------
    // 아이콘 버튼
    // ------------------------------------------------------------------
    mediaButton.addEventListener("click", () => mediaInput.click());
    mediaInput.addEventListener("change", () => {
        stage(Array.from(mediaInput.files || []));
        mediaInput.value = "";
    });
    // 파일(문서)과 음성은 기존 버튼의 동작(바로 전송, 녹음 시작/종료)을 그대로 쓴다.
    fileButton.addEventListener("click", () => $("#file-btn").click());
    micButton.addEventListener("click", () => $("#audio-btn").click());

    // 녹음 중이면 마이크 아이콘을 빨갛게, 채팅을 보낼 수 없는 상태(차단·종료된 방)면 아이콘도 잠근다. 둘 다 기존 요소의 상태를 따른다.
    const audioButton = $("#audio-btn");
    if (audioButton) {
        new MutationObserver(() => micButton.classList.toggle("recording", audioButton.classList.contains("recording")))
            .observe(audioButton, { attributes: true, attributeFilter: ["class"] });
    }
    const plusButton = $("#plus-btn");
    if (plusButton) {
        new MutationObserver(() => {
            [micButton, mediaButton, fileButton].forEach((button) => { button.disabled = plusButton.disabled; });
            area.classList.toggle("is-locked", plusButton.disabled);
        }).observe(plusButton, { attributes: true, attributeFilter: ["disabled"] });
    }

    // 클립보드의 사진을 붙여넣으면 미리보기로 쌓는다.
    textarea.addEventListener("paste", (event) => {
        const files = Array.from((event.clipboardData && event.clipboardData.files) || []).filter((file) => kindOf(file));
        if (!files.length) return;
        event.preventDefault();
        stage(files);
    });

    // 다른 대화방으로 옮기면 쌓아 둔 첨부는 버린다(엉뚱한 방으로 가지 않게).
    const headerTitle = $(".chat-header-title");
    if (headerTitle) {
        new MutationObserver(() => {
            if (staged.length && currentConversationID !== stagedConversation) clearStaged();
        }).observe(headerTitle, { childList: true, characterData: true, subtree: true });
    }

    // ------------------------------------------------------------------
    // 전송: 쌓아 둔 사진·동영상을 순서대로 보내고, 글이 있으면 마지막에 글을 보낸다.
    // ------------------------------------------------------------------
    function readAsDataURL(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error("사진 파일을 읽지 못했습니다."));
            reader.readAsDataURL(file);
        });
    }

    async function postMedia(conversationId, item) {
        let response;
        if (item.kind === "image") {
            response = await fetch(`/api/conversations/${conversationId}/messages/image`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: await readAsDataURL(item.file) })
            });
        } else {
            const form = new FormData();
            form.append("video", item.file);
            response = await fetch(`/api/conversations/${conversationId}/messages/video`, { method: "POST", body: form });
        }
        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.error || (item.kind === "image" ? "사진을 보내지 못했습니다." : "동영상을 보내지 못했습니다."));
        }
    }

    async function sendStaged() {
        if (sending) return;
        const conversationId = currentConversationID;
        if (!conversationId || conversationId !== stagedConversation) {
            clearStaged();
            showToast("대화방이 바뀌어 첨부를 취소했습니다.", "error");
            return;
        }
        const hasText = textarea.value.trim() !== "";
        sending = true;
        area.classList.add("is-sending");
        setComposerBusy(true);
        let allSent = true;
        for (const item of staged.slice()) {
            try {
                await postMedia(conversationId, item);
                removeStaged(item.id);
            } catch (error) {
                // 보내지 못한 것은 미리보기에 남겨 두어 다시 시도할 수 있게 한다.
                showToast(error.message || "전송 중 문제가 발생했습니다.", "error");
                allSent = false;
                break;
            }
        }
        await readMessages();
        updateFriendPreviewFromServer();
        setComposerBusy(false);
        area.classList.remove("is-sending");
        sending = false;
        if (allSent) {
            stagedConversation = null;
            replyMessage = null;
            replyPreview.style.display = "none";
            // 글이 있으면 기존 글 전송 흐름(답장·길이 검사 등)을 그대로 쓴다.
            if (hasText) await sendMessage();
        }
        textarea.focus();
    }

    // 쌓아 둔 첨부가 있을 때만 전송 버튼·Enter를 가로챈다(수정 중일 때는 예전 흐름 그대로).
    function shouldSendStaged() {
        return staged.length > 0 && editingIndex === null;
    }
    sendButton.addEventListener("click", (event) => {
        if (!shouldSendStaged()) return;
        event.stopImmediatePropagation();
        sendStaged();
    }, true);
    textarea.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing || !shouldSendStaged()) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        sendStaged();
    }, true);

    sync();
})();
