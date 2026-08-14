(function () {
    const shell = document.querySelector(".chess-game-shell");
    const gameId = shell.dataset.gameId;
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const boardElement = document.querySelector("#chess-board");
    const pieceGlyph = { P:"♙", N:"♘", B:"♗", R:"♖", Q:"♕", K:"♔", p:"♟", n:"♞", b:"♝", r:"♜", q:"♛", k:"♚" };
    let game = null, selected = null, pendingPromotion = null, flipped = false, lastMove = null, replayFen = null, hasLoadedState = false, chessAudioContext = null;
    const socket = window.io ? io() : null;

    function squareFrom(row, col) { return "abcdefgh"[col] + (8 - row); }
    function fenPieces(fen) {
        const grid = Array.from({length:8}, () => Array(8).fill(null));
        fen.split(" ")[0].split("/").forEach((line, row) => { let col = 0; for (const token of line) { if (/\d/.test(token)) col += Number(token); else grid[row][col++] = token; } });
        return grid;
    }
    function legalTargets(from) { return (game?.legalMoves || []).filter(move => move.slice(0,2) === from).map(move => move.slice(2,4)); }
    function isMyTurn() { return !replayFen && game && game.status === "active" && (game.mode === "local" || game.myColor === game.turn); }
    function prepareChessAudio() {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        if (!chessAudioContext) chessAudioContext = new AudioContextClass();
        if (chessAudioContext.state === "suspended") chessAudioContext.resume();
    }
    function playChessMoveSound() {
        if (!chessAudioContext) return;
        const now = chessAudioContext.currentTime;
        [[175, .065, .13], [265, .045, .08]].forEach(([frequency, duration, volume]) => {
            const oscillator = chessAudioContext.createOscillator(), gain = chessAudioContext.createGain();
            oscillator.type = "triangle"; oscillator.frequency.setValueAtTime(frequency, now);
            gain.gain.setValueAtTime(volume, now); gain.gain.exponentialRampToValueAtTime(.001, now + duration);
            oscillator.connect(gain).connect(chessAudioContext.destination); oscillator.start(now); oscillator.stop(now + duration);
        });
    }
    function renderBoard() {
        if (!game) return; const grid = fenPieces(replayFen || game.fen); boardElement.innerHTML = "";
        const rows = flipped ? [...Array(8).keys()].reverse() : [...Array(8).keys()];
        const cols = flipped ? [...Array(8).keys()].reverse() : [...Array(8).keys()];
        const selectedTargets = selected ? legalTargets(selected) : [];
        rows.forEach(row => cols.forEach(col => {
            const square = squareFrom(row, col), piece = grid[row][col], button = document.createElement("button");
            button.className = `chess-square ${(row + col) % 2 ? "dark" : "light"}`;
            button.dataset.square = square; button.draggable = !!piece && isMyTurn();
            if (square === selected) button.classList.add("selected");
            if (selectedTargets.includes(square)) button.classList.add("legal");
            if (lastMove && (lastMove.from === square || lastMove.to === square)) button.classList.add("last-move");
            if (game.check && piece && piece.toLowerCase() === "k" && (piece === "K" ? "w" : "b") === game.turn) button.classList.add("checked");
            if (piece) button.innerHTML = `<span class="chess-piece ${piece === piece.toUpperCase() ? "white" : "black"}">${pieceGlyph[piece]}</span>`;
            button.addEventListener("click", () => selectSquare(square));
            button.addEventListener("dragstart", event => { if (!isMyTurn()) return event.preventDefault(); event.dataTransfer.setData("text/plain", square); });
            button.addEventListener("dragover", event => event.preventDefault());
            button.addEventListener("drop", event => { event.preventDefault(); const from = event.dataTransfer.getData("text/plain"); if (from) attemptMove(from, square); });
            boardElement.appendChild(button);
        }));
    }
    function selectSquare(square) {
        if (!isMyTurn()) return;
        const piece = fenPieces(replayFen || game.fen)[8 - Number(square[1])]["abcdefgh".indexOf(square[0])];
        if (selected && legalTargets(selected).includes(square)) return attemptMove(selected, square);
        if (piece && (game.mode === "local" || (piece === piece.toUpperCase() ? "w" : "b") === game.myColor) && (piece === piece.toUpperCase() ? "w" : "b") === game.turn) selected = square;
        else selected = null;
        renderBoard();
    }
    function attemptMove(from, to) {
        const promotionMoves = (game.legalMoves || []).filter(move => move.slice(0,4) === from + to && move.length === 5);
        if (promotionMoves.length) { pendingPromotion = {from, to}; document.querySelector("#promotion-dialog").hidden = false; return; }
        sendMove(from, to);
    }
    async function sendMove(from, to, promotion) {
        try {
            prepareChessAudio();
            const response = await fetch(`/api/chess/games/${gameId}/move`, {method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:JSON.stringify({from, to, promotion})});
            const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.error || "수를 둘 수 없습니다.");
            lastMove = {from, to}; selected = null; applyState(data.game);
        } catch (error) { alert(error.message); selected = null; renderBoard(); }
    }
    function displayClock(value, turn) {
        if (value === null || value === undefined) return "∞";
        let current = value;
        if (game.status === "active" && game.turn === turn && game.turnStartedMs) current -= Math.max(0, Date.now() - game.turnStartedMs);
        current = Math.max(0, current); return `${Math.floor(current / 60000)}:${String(Math.floor(current / 1000) % 60).padStart(2,"0")}`;
    }
    function renderMeta() {
        document.querySelector("#white-name").textContent = game.white.name;
        document.querySelector("#black-name").textContent = game.black.name;
        document.querySelector("#white-clock").textContent = displayClock(game.whiteRemainingMs, "w");
        document.querySelector("#black-clock").textContent = displayClock(game.blackRemainingMs, "b");
        document.querySelector("#white-captured").textContent = (game.captured?.black || []).map(piece => pieceGlyph[piece]).join(" ");
        document.querySelector("#black-captured").textContent = (game.captured?.white || []).map(piece => pieceGlyph[piece]).join(" ");
        document.querySelector("#room-code").textContent = game.mode === "online" ? `초대 코드 ${game.roomCode}` : game.mode === "ai" ? "AI 대전" : "로컬 2인";
        const status = game.status === "waiting" ? "친구가 초대 코드로 입장하기를 기다리는 중입니다." : game.status === "active" ? (game.mode === "ai" && game.turn === "b" ? "AI가 수를 생각 중입니다…" : `${game.turn === "w" ? "백" : "흑"} 차례${game.check ? " · 체크" : ""}`) : "게임 종료";
        document.querySelector("#game-status").textContent = status;
        const history = document.querySelector("#move-history"); history.innerHTML = "";
        (game.moves || []).forEach((move, index) => {
            const item = document.createElement("li"); const button = document.createElement("button");
            button.type = "button"; button.textContent = `${Math.floor(index / 2) + 1}${index % 2 ? "..." : "."} ${move.san}`;
            button.addEventListener("click", () => { replayFen = replayFen === move.fen ? null : move.fen; selected = null; renderBoard(); document.querySelector("#game-status").textContent = replayFen ? `${move.number}수 뒤 국면을 보고 있습니다. 다시 누르면 현재 국면으로 돌아갑니다.` : "현재 국면"; });
            item.appendChild(button); history.appendChild(item);
        });
        if (game.result?.status && game.result.status !== "active") showResult(game.result);
    }
    function showResult(result) {
        const names = { checkmate:"체크메이트", stalemate:"스테일메이트", draw_50_move:"50수 무승부", draw_threefold:"동일 국면 3회 반복", draw_insufficient_material:"기물 부족 무승부", draw_agreed:"합의 무승부", resignation:"기권", timeout:"시간 초과", disconnect:"연결 끊김" };
        const winner = result.winner === "w" ? game.white.name : result.winner === "b" ? game.black.name : null;
        document.querySelector("#result-title").textContent = names[result.status] || "게임 종료";
        document.querySelector("#result-description").textContent = winner ? `${winner}님의 승리입니다.` : "무승부로 게임이 종료되었습니다.";
        document.querySelector("#game-result-modal").hidden = false;
    }
    function applyState(state) {
        const previousMoveCount = game?.moves?.length || 0;
        const hasNewMove = hasLoadedState && (state.moves?.length || 0) > previousMoveCount;
        game = state; replayFen = null; renderBoard(); renderMeta();
        if (hasNewMove) playChessMoveSound();
        hasLoadedState = true;
    }
    async function loadState() { const response = await fetch(`/api/chess/games/${gameId}`); const data = await response.json(); if (!response.ok || !data.success) return alert(data.error || "게임을 불러오지 못했습니다."); applyState(data.game); }
    document.querySelectorAll("[data-promotion]").forEach(button => button.addEventListener("click", () => { document.querySelector("#promotion-dialog").hidden = true; sendMove(pendingPromotion.from, pendingPromotion.to, button.dataset.promotion); pendingPromotion = null; }));
    document.querySelector("#result-delete-history").addEventListener("click", async event => {
        if (!game || game.status !== "finished" || !confirm("이 전적과 기보를 삭제할까요?")) return;
        event.currentTarget.disabled = true;
        try {
            const response = await fetch(`/api/chess/history/${gameId}`, {method:"DELETE", headers:{"X-CSRF-Token":csrf}});
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || "전적 삭제에 실패했습니다.");
            location.href = "/chess";
        } catch (error) {
            event.currentTarget.disabled = false;
            alert(error.message);
        }
    });
    document.querySelector("#flip-board").addEventListener("click", () => { flipped = !flipped; renderBoard(); });
    document.querySelector("#resign-btn").addEventListener("click", async () => { if (!confirm("정말 기권할까요?")) return; const response = await fetch(`/api/chess/games/${gameId}/resign`, {method:"POST", headers:{"X-CSRF-Token":csrf}}); const data = await response.json(); if (data.success) applyState(data.game); else alert(data.error); });
    document.querySelector("#draw-btn").addEventListener("click", async () => { const response = await fetch(`/api/chess/games/${gameId}/draw`, {method:"POST", headers:{"X-CSRF-Token":csrf}}); const data = await response.json(); if (data.success) applyState(data.game); else alert(data.error); });
    if (socket) { socket.emit("room:join", {gameId}); socket.emit("game:reconnect", {gameId}); socket.on("game:state_update", applyState); socket.on("game:start", applyState); socket.on("game:timeout", loadState); socket.on("game:error", data => alert(data.error || "게임 처리 중 오류가 발생했습니다.")); }
    setInterval(() => { if (game?.status === "active") { renderMeta(); } }, 500);
    setInterval(() => { if (game?.status === "active") loadState(); }, 5000);
    loadState();
}());
