(function () {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const selectedTime = () => document.querySelector('input[name="timeControl"]:checked').value;
    async function create(mode, difficulty) {
        const response = await fetch("/api/chess/games", { method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:JSON.stringify({mode, timeControl:selectedTime(), difficulty}) });
        const data = await response.json();
        if (!response.ok || !data.success) return alert(data.error || "게임 생성에 실패했습니다.");
        location.href = `/chess/game/${data.game.id}`;
    }
    document.querySelectorAll(".mode-start").forEach(button => button.addEventListener("click", () => {
        const card = button.closest(".chess-mode-card"); create(card.dataset.mode, card.querySelector(".difficulty")?.value || "medium");
    }));
    document.querySelector(".join-room").addEventListener("click", async () => {
        const input = document.querySelector(".join-code input"); const roomCode = input.value.trim();
        if (!roomCode) return input.focus();
        const response = await fetch("/api/chess/join", {method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:JSON.stringify({roomCode})});
        const data = await response.json();
        if (!response.ok || !data.success) return alert(data.error || "방 입장에 실패했습니다.");
        location.href = `/chess/game/${data.game.id}`;
    });
    if (window.io) {
        const socket = io();
        document.querySelector(".random-match").addEventListener("click", event => {
            event.currentTarget.disabled = true; event.currentTarget.textContent = "상대를 찾는 중…";
            socket.emit("matchmaking:queue", {timeControl:selectedTime()});
        });
        socket.on("matchmaking:matched", game => { location.href = `/chess/game/${game.id}`; });
        socket.on("matchmaking:queued", () => {});
    }
    (async function loadHistory() {
        const list = document.querySelector("#chess-history-list");
        const response = await fetch("/api/chess/history"); const games = await response.json();
        const deleteAllButton = document.querySelector("#delete-all-chess-history");
        if (!response.ok || !games.length) { list.textContent = "아직 완료한 체스 게임이 없습니다."; deleteAllButton.hidden = true; return; }
        deleteAllButton.hidden = false;
        const resultText = {checkmate:"체크메이트", stalemate:"스테일메이트", draw_50_move:"50수 무승부", draw_threefold:"3회 반복", draw_agreed:"합의 무승부", resignation:"기권", timeout:"시간 초과", disconnect:"연결 끊김"};
        list.innerHTML = games.map(game => `<div class="chess-history-row"><span>${game.mode === "ai" ? "AI 대전" : game.mode === "local" ? "로컬 2인" : "온라인 대전"} · ${resultText[game.result?.status] || (game.status === "waiting" ? "대기 중" : "진행 중")}</span><div><a href="/chess/game/${game.id}">보기</a>${game.status === "finished" ? `<button class="history-delete" data-game-id="${game.id}" aria-label="전적 삭제"><i class="fa-solid fa-trash"></i></button>` : ""}</div></div>`).join("");
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
