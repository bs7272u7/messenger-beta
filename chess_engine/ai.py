"""서버에서만 계산하는 미니맥스 체스 AI. 브라우저는 추천 수를 알 수 없다."""
from __future__ import annotations

import random
import time
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


class SearchTimeout(Exception):
    """AI 한 수에 허용한 생각 시간을 넘겼을 때 탐색을 안전하게 중단한다."""


def _move_order_score(board: ChessBoard, move: ChessMove) -> int:
    """캡처와 프로모션부터 탐색해 알파-베타 가지치기 효율을 높인다."""
    target = board.board[8 - int(move.to_sq[1])]["abcdefgh".index(move.to_sq[0])]
    moving = board.board[8 - int(move.from_sq[1])]["abcdefgh".index(move.from_sq[0])]
    capture_score = PIECE_VALUES.get(target.lower(), 0) * 16 if target else 0
    moving_score = PIECE_VALUES.get(moving.lower(), 0) if moving else 0
    promotion_score = PIECE_VALUES.get(move.promotion or "", 0) * 10
    return capture_score - moving_score + promotion_score


def _search(board: ChessBoard, depth: int, alpha: int, beta: int, perspective: str, deadline: float) -> tuple[int, ChessMove | None]:
    if time.monotonic() >= deadline:
        raise SearchTimeout
    if depth == 0 or board.result()["status"] != "active":
        return evaluate(board, perspective), None
    maximizing = board.turn == perspective
    best_move = None
    moves = board.legal_moves()
    moves.sort(key=lambda move: _move_order_score(board, move), reverse=True)
    if maximizing:
        value = -10**9
        for move in moves:
            next_board = board.clone(); next_board.push(move)
            score, _ = _search(next_board, depth - 1, alpha, beta, perspective, deadline)
            if score > value: value, best_move = score, move
            alpha = max(alpha, value)
            if alpha >= beta: break
        return value, best_move
    value = 10**9
    for move in moves:
        next_board = board.clone(); next_board.push(move)
        score, _ = _search(next_board, depth - 1, alpha, beta, perspective, deadline)
        if score < value: value, best_move = score, move
        beta = min(beta, value)
        if alpha >= beta: break
    return value, best_move


def choose_move(board: ChessBoard, difficulty: str = "medium") -> ChessMove | None:
    moves = board.legal_moves()
    if not moves: return None
    # 작은 배포 서버에서는 고정 깊이 5보다 시간 제한을 둔 반복 심화가 더 안정적이다.
    depth = {"easy": 2, "medium": 3, "hard": 4}.get(difficulty, 3)
    budget = {"easy": 0.18, "medium": 0.55, "hard": 1.15}.get(difficulty, 0.55)
    if difficulty == "easy" and random.random() < 0.45: return random.choice(moves)
    deadline = time.monotonic() + budget
    best_move = random.choice(moves)
    for current_depth in range(1, depth + 1):
        try:
            _, candidate = _search(board, current_depth, -10**9, 10**9, board.turn, deadline)
            if candidate:
                best_move = candidate
        except SearchTimeout:
            break
    return best_move
