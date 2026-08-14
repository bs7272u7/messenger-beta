"""서버에서만 계산하는 미니맥스 체스 AI. 브라우저는 추천 수를 알 수 없다."""
from __future__ import annotations

import random
from .board import ChessBoard, ChessMove, PIECE_VALUES

PIECE_SQUARE = {
    "p": (0, 5, 5, 0, 5, 10, 50, 0), "n": (-50, -30, -10, -5, -5, -10, -30, -50),
    "b": (-20, -10, -10, -10, -10, -10, -10, -20), "r": (0, 0, 0, 5, 5, 0, 0, 0),
    "q": (-20, -10, -10, -5, -5, -10, -10, -20), "k": (20, 20, 0, -10, -10, 0, 20, 20),
}


def evaluate(board: ChessBoard, perspective: str) -> int:
    result = board.result()
    if result["status"] == "checkmate":
        return 100000 if result["winner"] == perspective else -100000
    if result["status"] != "active":
        return 0
    score = 0
    for row in range(8):
        for col in range(8):
            piece = board.board[row][col]
            if not piece:
                continue
            value = PIECE_VALUES[piece.lower()] + PIECE_SQUARE[piece.lower()][row if piece.isupper() else 7 - row]
            score += value if piece.isupper() == (perspective == "w") else -value
    mobility = len(board.legal_moves())
    king_safety = (-70 if board.in_check(perspective) else 0) + (70 if board.in_check("b" if perspective == "w" else "w") else 0)
    return score + (mobility if board.turn == perspective else -mobility) + king_safety


def _search(board: ChessBoard, depth: int, alpha: int, beta: int, perspective: str) -> tuple[int, ChessMove | None]:
    if depth == 0 or board.result()["status"] != "active":
        return evaluate(board, perspective), None
    maximizing = board.turn == perspective
    best_move = None
    moves = board.legal_moves()
    random.shuffle(moves)
    if maximizing:
        value = -10**9
        for move in moves:
            next_board = board.clone(); next_board.push(move)
            score, _ = _search(next_board, depth - 1, alpha, beta, perspective)
            if score > value: value, best_move = score, move
            alpha = max(alpha, value)
            if alpha >= beta: break
        return value, best_move
    value = 10**9
    for move in moves:
        next_board = board.clone(); next_board.push(move)
        score, _ = _search(next_board, depth - 1, alpha, beta, perspective)
        if score < value: value, best_move = score, move
        beta = min(beta, value)
        if alpha >= beta: break
    return value, best_move


def choose_move(board: ChessBoard, difficulty: str = "medium") -> ChessMove | None:
    moves = board.legal_moves()
    if not moves: return None
    # 어려움은 중반·종반처럼 분기 수가 줄면 5수까지, 초반에는 응답성을 위해 4수로 제한한다.
    depth = {"easy": 2, "medium": 3, "hard": 5 if len(moves) <= 12 else 4}.get(difficulty, 3)
    if difficulty == "easy" and random.random() < 0.45: return random.choice(moves)
    return _search(board, depth, -10**9, 10**9, board.turn)[1]
