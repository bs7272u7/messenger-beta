(function () {
    const shell = document.querySelector(".chess-game-shell");
    const gameId = shell.dataset.gameId;
    const currentUserId = Number(shell.dataset.currentUserId || 0);
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const boardElement = document.querySelector("#chess-board");
    const pieceGlyph = { P:"♙", N:"♘", B:"♗", R:"♖", Q:"♕", K:"♔", p:"♟", n:"♞", b:"♝", r:"♜", q:"♛", k:"♚" };
    let game = null, selected = null, pendingPromotion = null, flipped = false, lastMove = null, replayFen = null, hasLoadedState = false, chessAudioContext = null, movePending = false;
    const socket = window.io ? io() : null;

    function squareFrom(row, col) { return "abcdefgh"[col] + (8 - row); }
    function fenPieces(fen) {
        const grid = Array.from({length:8}, () => Array(8).fill(null));
        fen.split(" ")[0].split("/").forEach((line, row) => { let col = 0; for (const token of line) { if (/\d/.test(token)) col += Number(token); else grid[row][col++] = token; } });
        return grid;
    }
    function legalTargets(from) { return (game?.legalMoves || []).filter(move => move.slice(0,2) === from).map(move => move.slice(2,4)); }
    function isMyTurn() { return !movePending && !replayFen && game && game.status === "active" && (game.mode === "local" || game.myColor === game.turn); }
    function isMine(piece) { return game?.mode === "local" ? piece === piece.toUpperCase() : (piece === piece.toUpperCase() ? "w" : "b") === game?.myColor; }
    function viewFlipped() { return Boolean(game?.myColor === "b") !== flipped; }
    function viewPiece(piece) {
        const type = piece.toLowerCase();
        const own = isMine(piece);
        const glyphs = own
            ? {p:"♙", n:"♘", b:"♗", r:"♖", q:"♕", k:"♔"}
            : {p:"♟", n:"♞", b:"♝", r:"♜", q:"♛", k:"♚"};
        return glyphs[type];
    }
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
        const rows = viewFlipped() ? [...Array(8).keys()].reverse() : [...Array(8).keys()];
        const cols = viewFlipped() ? [...Array(8).keys()].reverse() : [...Array(8).keys()];
        const selectedTargets = selected ? legalTargets(selected) : [];
        rows.forEach(row => cols.forEach(col => {
            const square = squareFrom(row, col), piece = grid[row][col], button = document.createElement("button");
            button.className = `chess-square ${(row + col) % 2 ? "dark" : "light"}`;
            button.dataset.square = square; button.draggable = !!piece && isMyTurn(); button.disabled = movePending;
            if (square === selected) button.classList.add("selected");
            if (selectedTargets.includes(square)) button.classList.add("legal");
            if (lastMove && (lastMove.from === square || lastMove.to === square)) button.classList.add("last-move");
            if (game.check && piece && piece.toLowerCase() === "k" && (piece === "K" ? "w" : "b") === game.turn) button.classList.add("checked");
            if (piece) button.innerHTML = `<span class="chess-piece ${isMine(piece) ? "white" : "black"}">${viewPiece(piece)}</span>`;
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
        if (movePending) return;
        movePending = true; boardElement.classList.add("is-pending");
        try {
            prepareChessAudio();
            const response = await fetch(`/api/chess/games/${gameId}/move`, {method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:JSON.stringify({from, to, promotion})});
            const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.error || "수를 둘 수 없습니다.");
            lastMove = {from, to}; selected = null; applyState(data.game);
        } catch (error) { alert(error.message); selected = null; renderBoard(); }
        finally { movePending = false; boardElement.classList.remove("is-pending"); renderBoard(); }
    }
    function displayClock(value, turn) {
        if (value === null || value === undefined) return "∞";
        let current = value;
        if (game.status === "active" && game.turn === turn && game.turnStartedMs) current -= Math.max(0, Date.now() - game.turnStartedMs);
        current = Math.max(0, current); return `${Math.floor(current / 60000)}:${String(Math.floor(current / 1000) % 60).padStart(2,"0")}`;
    }
    function renderMeta() {
        // 실제 서버 색상과 화면 색상을 분리한다. 양쪽 모두 자신의 진영을 백/하단으로 본다.
        const mine = game.mode === "local" || game.myColor !== "b" ? game.white : game.black;
        const opponent = game.mode === "local" || game.myColor !== "b" ? game.black : game.white;
        const mineColor = game.mode === "local" || game.myColor !== "b" ? "w" : "b";
        const opponentColor = mineColor === "w" ? "b" : "w";
        document.querySelector("#white-name").textContent = mine.name;
        document.querySelector("#black-name").textContent = opponent.name;
        document.querySelector("#white-rating").textContent = mine.rating == null ? "AI" : `RATING ${mine.rating}`;
        document.querySelector("#black-rating").textContent = opponent.rating == null ? (game.status === "waiting" ? "상대 입장 대기" : "AI") : `RATING ${opponent.rating}`;
        document.querySelector("#white-clock").textContent = displayClock(mineColor === "w" ? game.whiteRemainingMs : game.blackRemainingMs, mineColor);
        document.querySelector("#black-clock").textContent = displayClock(opponentColor === "w" ? game.whiteRemainingMs : game.blackRemainingMs, opponentColor);
        document.querySelector("#white-captured").textContent = (game.captured?.[opponentColor === "w" ? "white" : "black"] || []).map(piece => viewPiece(piece)).join(" ");
        document.querySelector("#black-captured").textContent = (game.captured?.[mineColor === "w" ? "white" : "black"] || []).map(piece => viewPiece(piece)).join(" ");
        document.querySelector("#room-code").textContent = game.mode === "online" ? `초대 코드 ${game.roomCode}` : game.mode === "ai" ? "AI 대전" : "로컬 2인";
        document.querySelector("#invite-friend-btn").hidden = !(game.mode === "online" && game.status === "waiting" && game.myColor === "w");
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
        renderChat(game.chatMessages || []);
    }
    function renderChat(messages) {
        const list = document.querySelector("#chess-chat-list"); list.innerHTML = "";
        messages.forEach(message => { const item = document.createElement("div"); item.className = message.sender_id === game.white.id && game.myColor === "w" || message.sender_id === game.black.id && game.myColor === "b" ? "mine" : ""; item.textContent = `${message.display_name || message.username}: ${message.text}`; list.appendChild(item); });
        list.scrollTop = list.scrollHeight;
    }
    function appendChat(message) { const messages = [...(game.chatMessages || []), message]; game.chatMessages = messages.slice(-40); renderChat(game.chatMessages); }
    function showResult(result) {
        const names = { checkmate:"체크메이트", stalemate:"스테일메이트", draw_50_move:"50수 무승부", draw_threefold:"동일 국면 3회 반복", draw_insufficient_material:"기물 부족 무승부", draw_agreed:"합의 무승부", resignation:"기권", timeout:"시간 초과", disconnect:"연결 끊김" };
        const winner = result.winner === "w" ? game.white.name : result.winner === "b" ? game.black.name : null;
        document.querySelector("#result-title").textContent = names[result.status] || "게임 종료";
        const changes = result.ratingChanges; const changeText = changes && game.mode === "online" ? ` 레이팅 ${game.myColor === "w" ? (changes.white >= 0 ? "+" : "") + changes.white : (changes.black >= 0 ? "+" : "") + changes.black}` : "";
        document.querySelector("#result-description").textContent = (winner ? `${winner}님의 승리입니다.` : "무승부로 게임이 종료되었습니다.") + changeText;
        document.querySelector("#game-result-modal").hidden = false;
    }
    function applyState(state) {
        const previousMoveCount = game?.moves?.length || 0;
        const hasNewMove = hasLoadedState && (state.moves?.length || 0) > previousMoveCount;
        // 방 전체로 전송된 상태라도 현재 로그인한 계정 기준으로 시점을 다시 계산한다.
        if (state.mode !== "local") state.myColor = Number(state.white?.id) === currentUserId ? "w" : Number(state.black?.id) === currentUserId ? "b" : null;
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
    const inviteModal = document.querySelector("#chess-invite-modal");
    const inviteFriends = document.querySelector("#chess-invite-friends");
    function closeInviteModal() { inviteModal.hidden = true; }
    document.querySelector("#close-chess-invite").addEventListener("click", closeInviteModal);
    document.querySelector("#invite-friend-btn").addEventListener("click", async () => {
        inviteModal.hidden = false;
        inviteFriends.textContent = "친구 목록을 불러오는 중…";
        try {
            const response = await fetch(`/api/chess/games/${gameId}/inviteable-friends`);
            const contentType = response.headers.get("content-type") || "";
            const data = contentType.includes("application/json") ? await response.json() : {success:false, error:"초대 목록을 불러오지 못했습니다. 페이지를 새로고침한 뒤 다시 시도해주세요."};
            if (!response.ok || !data.success) throw new Error(data.error || "친구 목록을 불러오지 못했습니다.");
            inviteFriends.innerHTML = "";
            if (!data.friends.length) { inviteFriends.textContent = "초대할 친구가 없습니다."; return; }
            data.friends.forEach(friend => {
                const button = document.createElement("button"); button.type = "button"; button.className = "chess-invite-friend";
                const image = document.createElement("img"), label = document.createElement("span"), username = document.createElement("small"), icon = document.createElement("i");
                image.src = friend.profile_image || "/static/default_profile.png"; image.alt = "";
                label.append(document.createTextNode(friend.display_name || friend.username)); username.textContent = `@${friend.username}`; label.appendChild(username);
                icon.className = "fa-solid fa-paper-plane"; button.append(image, label, icon);
                button.addEventListener("click", async () => {
                    button.disabled = true;
                    const response = await fetch(`/api/chess/games/${gameId}/invites`, {method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:JSON.stringify({userId:friend.id})});
                    const contentType = response.headers.get("content-type") || "";
                    const data = contentType.includes("application/json") ? await response.json() : {success:false, error:"초대를 보내지 못했습니다. 잠시 후 다시 시도해주세요."};
                    if (!response.ok || !data.success) { button.disabled = false; return alert(data.error || "초대를 보내지 못했습니다."); }
                    button.innerHTML = `<span>초대를 보냈습니다</span><i class="fa-solid fa-check"></i>`;
                });
                inviteFriends.appendChild(button);
            });
        } catch (error) { inviteFriends.textContent = error.message; }
    });
    const playerModal = document.querySelector("#chess-player-modal");
    let inspectedPlayer = null;
    function closePlayerModal() { playerModal.hidden = true; inspectedPlayer = null; }
    document.querySelector("#close-chess-player").addEventListener("click", closePlayerModal);
    playerModal.addEventListener("click", event => { if (event.target === playerModal) closePlayerModal(); });
    document.querySelectorAll(".chess-player-trigger").forEach(button => button.addEventListener("click", async () => {
        const isMe = button.dataset.playerSlot === "me";
        const player = isMe || game.mode === "local" || game.myColor !== "b" ? (isMe ? game.white : game.black) : (isMe ? game.black : game.white);
        if (!player?.id) return;
        try {
            const response = await fetch(`/api/chess/players/${player.id}`);
            const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.error || "프로필을 불러오지 못했습니다.");
            inspectedPlayer = data.player;
            document.querySelector("#chess-player-avatar").src = inspectedPlayer.profileImage || "/static/default_profile.png";
            document.querySelector("#chess-player-name").textContent = inspectedPlayer.name;
            document.querySelector("#chess-player-username").textContent = `@${inspectedPlayer.username}`;
            document.querySelector("#chess-player-rating").textContent = inspectedPlayer.rating ?? "-";
            const record = inspectedPlayer.record || {}; document.querySelector("#chess-player-record").textContent = `${record.wins || 0}승 ${record.draws || 0}무 ${record.losses || 0}패`;
            const addButton = document.querySelector("#chess-player-friend-btn");
            addButton.hidden = isMe || inspectedPlayer.isFriend;
            addButton.disabled = false; addButton.innerHTML = '<i class="fa-solid fa-user-plus"></i> 친구 추가';
            playerModal.hidden = false;
        } catch (error) { alert(error.message); }
    }));
    document.querySelector("#chess-player-friend-btn").addEventListener("click", async event => {
        if (!inspectedPlayer) return;
        event.currentTarget.disabled = true;
        const response = await fetch(`/api/chess/players/${inspectedPlayer.id}/friend-request`, {method:"POST", headers:{"X-CSRF-Token":csrf}});
        const data = await response.json();
        if (!response.ok || !data.success) { event.currentTarget.disabled = false; return alert(data.error || "친구 요청에 실패했습니다."); }
        event.currentTarget.innerHTML = '<i class="fa-solid fa-check"></i> 요청 완료';
    });
    document.querySelector("#flip-board").addEventListener("click", () => { flipped = !flipped; renderBoard(); });
    document.querySelector("#resign-btn").addEventListener("click", async () => { if (!confirm("정말 기권할까요?")) return; const response = await fetch(`/api/chess/games/${gameId}/resign`, {method:"POST", headers:{"X-CSRF-Token":csrf}}); const data = await response.json(); if (data.success) applyState(data.game); else alert(data.error); });
    document.querySelector("#draw-btn").addEventListener("click", async () => { const response = await fetch(`/api/chess/games/${gameId}/draw`, {method:"POST", headers:{"X-CSRF-Token":csrf}}); const data = await response.json(); if (data.success) applyState(data.game); else alert(data.error); });
    document.querySelector("#chess-chat-form").addEventListener("submit", event => { event.preventDefault(); const input = document.querySelector("#chess-chat-input"), text = input.value.trim(); if (text && socket) { socket.emit("chat:message", {gameId, text}); input.value = ""; } });
    document.querySelectorAll("#chess-emote-tray [data-emote]").forEach(button => button.addEventListener("click", () => { prepareChessAudio(); socket?.emit("emote:send", {gameId, emote:button.dataset.emote}); }));
    function showEmote(data) { const pop = document.querySelector("#chess-emote-pop"); pop.textContent = `${data.emoji} ${data.sender} · ${data.label}`; pop.hidden = false; clearTimeout(showEmote.timer); showEmote.timer = setTimeout(() => pop.hidden = true, 2400); prepareChessAudio(); if (chessAudioContext) playChessMoveSound(); }
    if (socket) { socket.emit("room:join", {gameId}); socket.emit("game:reconnect", {gameId}); socket.on("game:state_update", applyState); socket.on("game:start", applyState); socket.on("game:timeout", loadState); socket.on("game:error", data => alert(data.error || "게임 처리 중 오류가 발생했습니다.")); socket.on("chat:message", appendChat); socket.on("emote:receive", showEmote); }
    setInterval(() => { if (game?.status === "active") { renderMeta(); } }, 500);
    setInterval(() => { if (game?.status === "active") loadState(); }, 5000);
    loadState();
}());
