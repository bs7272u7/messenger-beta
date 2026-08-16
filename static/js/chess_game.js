(function () {
    const shell = document.querySelector(".chess-game-shell");
    const gameId = shell.dataset.gameId;
    const currentUserId = Number(shell.dataset.currentUserId || 0);
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const boardElement = document.querySelector("#chess-board");
    const pieceGlyph = { P:"♙", N:"♘", B:"♗", R:"♖", Q:"♕", K:"♔", p:"♟", n:"♞", b:"♝", r:"♜", q:"♛", k:"♚" };
    let game = null, selected = null, pendingPromotion = null, flipped = false, lastMove = null, replayFen = null, hasLoadedState = false, chessAudioContext = null, movePending = false, renderedMoveCount = -1;
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
        const isWhite = piece === piece.toUpperCase();
        const glyphs = isWhite
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
        const ctx = chessAudioContext, now = ctx.currentTime;

        // 접촉 순간의 "톡" — 로우패스로 거른 짧은 노이즈로 나무판에 말이 닿는 질감을 낸다.
        const noiseDuration = .045;
        const noiseBuffer = ctx.createBuffer(1, Math.floor(ctx.sampleRate * noiseDuration), ctx.sampleRate);
        const noiseData = noiseBuffer.getChannelData(0);
        for (let i = 0; i < noiseData.length; i++) noiseData[i] = (Math.random() * 2 - 1) * (1 - i / noiseData.length);
        const noiseSource = ctx.createBufferSource(); noiseSource.buffer = noiseBuffer;
        const noiseFilter = ctx.createBiquadFilter(); noiseFilter.type = "lowpass"; noiseFilter.frequency.setValueAtTime(1200, now);
        const noiseGain = ctx.createGain(); noiseGain.gain.setValueAtTime(.5, now); noiseGain.gain.exponentialRampToValueAtTime(.001, now + noiseDuration);
        noiseSource.connect(noiseFilter).connect(noiseGain).connect(ctx.destination);
        noiseSource.start(now); noiseSource.stop(now + noiseDuration);

        // 저음역 바디 — 둔탁하고 묵직한 울림을 더한다.
        [[95, .09, .22], [150, .06, .12]].forEach(([frequency, duration, volume]) => {
            const oscillator = ctx.createOscillator(), gain = ctx.createGain();
            oscillator.type = "sine"; oscillator.frequency.setValueAtTime(frequency, now);
            gain.gain.setValueAtTime(volume, now); gain.gain.exponentialRampToValueAtTime(.001, now + duration);
            oscillator.connect(gain).connect(ctx.destination); oscillator.start(now); oscillator.stop(now + duration);
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
            button.dataset.square = square; button.draggable = !!piece && isMyTurn(); 
            if (square === selected) button.classList.add("selected");
            if (selectedTargets.includes(square)) button.classList.add("legal");
            if (lastMove && (lastMove.from === square || lastMove.to === square)) button.classList.add("last-move");
            if (game.check && piece && piece.toLowerCase() === "k" && (piece === "K" ? "w" : "b") === game.turn) button.classList.add("checked");
            if (piece) button.innerHTML = `<span class="chess-piece ${piece === piece.toUpperCase() ? "white" : "black"}">${viewPiece(piece)}</span>`;
            button.addEventListener("click", () => selectSquare(square));
            button.addEventListener("dragstart", event => { if (!isMyTurn()) return event.preventDefault(); event.dataTransfer.setData("text/plain", square); });
            button.addEventListener("dragover", event => event.preventDefault());
            button.addEventListener("drop", event => { event.preventDefault(); const from = event.dataTransfer.getData("text/plain"); if (from) attemptMove(from, square); });
            boardElement.appendChild(button);
        }));
        renderCoordinates(rows, cols);
    }
    /* 좌표 라벨은 보드와 같은 순서로 다시 그려, 보드를 뒤집어도 항상 맞는 좌표를 보여준다. */
    function renderCoordinates(rows, cols) {
        const rankBar = document.querySelector("#cc-ranks");
        const fileBar = document.querySelector("#cc-files");
        if (!rankBar || !fileBar) return;
        rankBar.innerHTML = rows.map(row => `<span>${8 - row}</span>`).join("");
        fileBar.innerHTML = cols.map(col => `<span>${"abcdefgh"[col]}</span>`).join("");
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
        // 카드 위치(하단=나, 상단=상대)만 고정한다. 기물 색상은 실제 흑/백을 그대로 보여준다.
        const mine = game.mode === "local" || game.myColor !== "b" ? game.white : game.black;
        const opponent = game.mode === "local" || game.myColor !== "b" ? game.black : game.white;
        const mineColor = game.mode === "local" || game.myColor !== "b" ? "w" : "b";
        const opponentColor = mineColor === "w" ? "b" : "w";
        document.querySelector("#white-name").textContent = mine.name;
        document.querySelector("#black-name").textContent = opponent.name;
        document.querySelector("#white-avatar").src = mine.profileImage || "/static/default_profile.png";
        document.querySelector("#black-avatar").src = opponent.profileImage || "/static/default_profile.png";
        document.querySelector("#white-rating").textContent = mine.rating == null ? "AI" : `RATING ${mine.rating}`;
        document.querySelector("#black-rating").textContent = opponent.rating == null ? (game.status === "waiting" ? "상대 입장 대기" : "AI") : `RATING ${opponent.rating}`;
        // 레퍼런스 상단 중앙의 "나 vs 상대" 대전 타이틀
        document.querySelector("#cc-match-title").textContent = game.status === "waiting"
            ? "상대 입장 대기 중"
            : `${mine.name} vs ${opponent.name}`;
        document.querySelector("#white-clock").textContent = displayClock(mineColor === "w" ? game.whiteRemainingMs : game.blackRemainingMs, mineColor);
        document.querySelector("#black-clock").textContent = displayClock(opponentColor === "w" ? game.whiteRemainingMs : game.blackRemainingMs, opponentColor);
        document.querySelector("#white-captured").textContent = (game.captured?.[opponentColor === "w" ? "white" : "black"] || []).map(piece => viewPiece(piece)).join(" ");
        document.querySelector("#black-captured").textContent = (game.captured?.[mineColor === "w" ? "white" : "black"] || []).map(piece => viewPiece(piece)).join(" ");
        document.querySelector("#room-code").textContent = game.status === "waiting" ? `초대 코드 ${game.roomCode}` : "";
        document.querySelector("#invite-friend-btn").hidden = game.status !== "waiting";

        // 하단 중앙 상태 알약: 누구 차례인지를 이름으로 알려준다.
        const myTurn = game.turn === game.myColor;
        const status =
            game.status === "waiting"
                ? "친구를 초대하거나 초대 코드를 알려주세요"
                : game.status === "active"
                    ? `${myTurn ? "내" : `${opponent.name}님`} 차례${game.check ? " · 체크!" : ""}`
                    : "게임 종료";

        document.querySelector("#game-status").textContent = status;
        document.querySelector("#game-status").classList.toggle("is-my-turn", game.status === "active" && myTurn);
        const drawOfferedByMe = game.drawOfferedBy === currentUserId;
        const drawOfferedByOpponent = Boolean(game.drawOfferedBy) && !drawOfferedByMe;
        drawBtn.hidden = game.mode !== "online" || game.status !== "active";
        drawBtn.classList.toggle("draw-offered", drawOfferedByOpponent);
        drawBtn.innerHTML = `<i class="fa-solid fa-dove"></i> ${drawOfferedByOpponent ? "무승부 수락" : drawOfferedByMe ? "무승부 제안 취소" : "무승부 제안"}`;
        if (drawOfferedByOpponent) document.querySelector("#game-status").textContent = "상대가 무승부를 제안했습니다.";
        else if (drawOfferedByMe) document.querySelector("#game-status").textContent = "무승부를 제안했습니다. 상대의 응답을 기다리는 중…";
        // 레퍼런스처럼 한 행에 [수 번호][백의 수][흑의 수]를 나란히 배치한다.
        const history = document.querySelector("#move-history"); history.innerHTML = "";
        const moves = game.moves || [];
        if (!moves.length) history.innerHTML = '<li class="cc-move-empty">아직 둔 수가 없습니다.</li>';
        function moveButton(move) {
            if (!move) return document.createElement("span");
            const button = document.createElement("button");
            button.type = "button"; button.className = "cc-move"; button.textContent = move.san;
            button.classList.toggle("is-current", replayFen === move.fen);
            button.addEventListener("click", () => {
                replayFen = replayFen === move.fen ? null : move.fen; selected = null; renderBoard(); renderMeta();
                document.querySelector("#game-status").textContent = replayFen ? `${move.number}수 뒤 국면을 보는 중 · 다시 누르면 현재 국면` : "현재 국면";
            });
            return button;
        }
        for (let index = 0; index < moves.length; index += 2) {
            const item = document.createElement("li"); item.className = "cc-move-row";
            const number = document.createElement("span"); number.className = "cc-move-no"; number.textContent = index / 2 + 1;
            item.append(number, moveButton(moves[index]), moveButton(moves[index + 1]));
            history.appendChild(item);
        }
        // 새 수가 들어왔을 때만 아래로 따라간다. 매 갱신마다 스크롤하면 기보를 되짚어볼 수 없다.
        if (moves.length !== renderedMoveCount) { history.scrollTop = history.scrollHeight; renderedMoveCount = moves.length; }
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
                icon.className = "fa-solid fa-scroll"; button.append(image, label, icon);
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

        const mine =
            game.mode === "local" || game.myColor !== "b"
                ? game.white
                : game.black;

        const opponent =
            game.mode === "local" || game.myColor !== "b"
                ? game.black
                : game.white;

        const player = isMe ? mine : opponent;

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
            playerModal.hidden = false;
        } catch (error) { alert(error.message); }
    }));
    document.querySelector("#flip-board").addEventListener("click", () => { flipped = !flipped; renderBoard(); });
    document.querySelector("#resign-btn").addEventListener("click", async () => { if (!confirm("정말 기권할까요?")) return; const response = await fetch(`/api/chess/games/${gameId}/resign`, {method:"POST", headers:{"X-CSRF-Token":csrf}}); const data = await response.json(); if (data.success) applyState(data.game); else alert(data.error); });
    const drawBtn = document.querySelector("#draw-btn");
    drawBtn.addEventListener("click", async () => {
        const offeredByMe = game?.drawOfferedBy === currentUserId;
        const method = offeredByMe ? "DELETE" : "POST";
        if (method === "POST" && !game?.drawOfferedBy && !confirm("무승부를 제안할까요?")) return;
        drawBtn.disabled = true;
        try {
            const response = await fetch(`/api/chess/games/${gameId}/draw`, {method, headers:{"X-CSRF-Token":csrf}});
            const data = await response.json();
            if (data.success) applyState(data.game); else alert(data.error);
        } finally { drawBtn.disabled = false; }
    });
    document.querySelector("#chess-chat-form").addEventListener("submit", event => { event.preventDefault(); const input = document.querySelector("#chess-chat-input"), text = input.value.trim(); if (text && socket) { socket.emit("chat:message", {gameId, text}); input.value = ""; } });
    document.querySelectorAll("#chess-emote-tray [data-emote]").forEach(button => button.addEventListener("click", () => { prepareChessAudio(); socket?.emit("emote:send", {gameId, emote:button.dataset.emote}); }));
    function showEmote(data) { const pop = document.querySelector("#chess-emote-pop"); pop.textContent = `${data.emoji} ${data.sender} · ${data.label}`; pop.hidden = false; clearTimeout(showEmote.timer); showEmote.timer = setTimeout(() => pop.hidden = true, 2400); prepareChessAudio(); if (chessAudioContext) playChessMoveSound(); }
    if (socket) { socket.emit("room:join", {gameId}); socket.emit("game:reconnect", {gameId}); socket.on("game:state_update", applyState); socket.on("game:start", applyState); socket.on("game:timeout", loadState); socket.on("game:error", data => alert(data.error || "게임 처리 중 오류가 발생했습니다.")); socket.on("chat:message", appendChat); socket.on("emote:receive", showEmote); }
    setInterval(() => { if (game?.status === "active") { renderMeta(); } }, 500);
    setInterval(() => { if (game?.status === "active") loadState(); }, 5000);
    loadState();
}());
