(function () {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const selectedTime = () => document.querySelector('input[name="timeControl"]:checked').value;

    /* ======================================================
     * 방 만들기 / 코드로 입장
     * ====================================================== */
    const createBtn = document.querySelector("#cc-create-game");
    const joinToggleBtn = document.querySelector("#cc-join-game");
    const joinPanel = document.querySelector("#cc-join-panel");
    const joinInput = document.querySelector("#cc-join-code-input");
    const joinSubmitBtn = document.querySelector("#cc-join-submit");

    createBtn.addEventListener("click", async () => {
        createBtn.disabled = true;
        try {
            const response = await fetch("/api/chess/games", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
                body: JSON.stringify({ mode: "online", timeControl: selectedTime() })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || "게임 생성에 실패했습니다.");
            location.href = `/chess/game/${data.game.id}`;
        } catch (error) {
            createBtn.disabled = false;
            alert(error.message);
        }
    });

    joinToggleBtn.addEventListener("click", () => {
        const willOpen = joinPanel.hidden;
        joinPanel.hidden = !willOpen;
        joinToggleBtn.setAttribute("aria-expanded", String(willOpen));
        if (willOpen) joinInput.focus();
    });

    async function submitJoinCode() {
        const roomCode = joinInput.value.trim();
        if (!roomCode) return joinInput.focus();
        joinSubmitBtn.disabled = true;
        try {
            const response = await fetch("/api/chess/join", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
                body: JSON.stringify({ roomCode })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || "방 입장에 실패했습니다.");
            location.href = `/chess/game/${data.game.id}`;
        } catch (error) {
            joinSubmitBtn.disabled = false;
            alert(error.message);
        }
    }
    joinSubmitBtn.addEventListener("click", submitJoinCode);
    joinInput.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); submitJoinCode(); } });

    /* ======================================================
     * 체스 규칙 모달
     * ====================================================== */
    const rulesModal = document.querySelector("#chess-rules-modal");
    document.querySelector("#chess-rules-btn").addEventListener("click", () => { rulesModal.hidden = false; });
    document.querySelector("#close-chess-rules").addEventListener("click", () => { rulesModal.hidden = true; });
    rulesModal.addEventListener("click", event => { if (event.target === rulesModal) rulesModal.hidden = true; });
    document.querySelectorAll("[data-rules-tab]").forEach(tabBtn => tabBtn.addEventListener("click", () => {
        const target = tabBtn.dataset.rulesTab;
        document.querySelectorAll("[data-rules-tab]").forEach(btn => btn.classList.toggle("active", btn === tabBtn));
        document.querySelectorAll("[data-rules-panel]").forEach(panel => { panel.hidden = panel.dataset.rulesPanel !== target; });
    }));
    document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        if (!rulesModal.hidden) rulesModal.hidden = true;
    });

    /* ======================================================
     * 최근 전적
     * ====================================================== */
    (async function loadHistory() {
        const list = document.querySelector("#chess-history-list");
        const response = await fetch("/api/chess/history"); const games = await response.json();
        const deleteAllButton = document.querySelector("#delete-all-chess-history");
        if (!response.ok || !games.length) { list.textContent = "아직 완료한 체스 게임이 없습니다."; deleteAllButton.hidden = true; return; }
        deleteAllButton.hidden = false;
        const resultText = {checkmate:"체크메이트", stalemate:"스테일메이트", draw_50_move:"50수 무승부", draw_threefold:"3회 반복", draw_insufficient_material:"기물 부족 무승부", draw_agreed:"합의 무승부", resignation:"항복", timeout:"시간 초과", disconnect:"연결 끊김"};
        list.innerHTML = games.map(game => {
            const winner = game.result?.winner;
            const outcome = !winner ? "draw" : winner === game.myColor ? "win" : "loss";
            const outcomeText = {win:"승리", loss:"패배", draw:"무승부"}[outcome];
            return `<div class="chess-history-row"><span><span class="chess-outcome-badge chess-outcome-${outcome}">${outcomeText}</span>${resultText[game.result?.status] || (game.status === "waiting" ? "대기 중" : "진행 중")}</span><div><a href="/chess/game/${game.id}">보기</a>${game.status === "finished" ? `<button class="history-delete" data-game-id="${game.id}" aria-label="전적 삭제"><i class="fa-solid fa-trash"></i></button>` : ""}</div></div>`;
        }).join("");
        list.querySelectorAll(".history-delete").forEach(button => button.addEventListener("click", async () => {
            if (!confirm("이 전적과 기보를 삭제할까요?")) return;
            const response = await fetch(`/api/chess/history/${button.dataset.gameId}`, {method:"DELETE", headers:{"X-CSRF-Token":csrf}});
            const data = await response.json(); if (!response.ok || !data.success) return alert(data.error || "전적 삭제에 실패했습니다.");
            button.closest(".chess-history-row").remove();
            if (!list.children.length) list.textContent = "아직 완료한 체스 게임이 없습니다.";
        }));
    }());
    document.querySelector("#delete-all-chess-history").addEventListener("click", async event => {
        if (!confirm("종료된 내 체스 전적과 기보를 모두 삭제할까요? 레이팅은 유지됩니다.")) return;
        const response = await fetch("/api/chess/history", {method:"DELETE", headers:{"X-CSRF-Token":csrf}});
        const data = await response.json();
        if (!response.ok || !data.success) return alert(data.error || "전적을 삭제하지 못했습니다.");
        document.querySelector("#chess-history-list").textContent = "아직 완료한 체스 게임이 없습니다.";
        event.currentTarget.disabled = true;
    });
}());
