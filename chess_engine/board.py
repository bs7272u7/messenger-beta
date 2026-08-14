"""외부 체스 라이브러리 없이 FEN·SAN·합법 수를 처리하는 순수 체스 엔진."""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Iterable

FILES = "abcdefgh"
RANKS = "12345678"
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KNIGHT_STEPS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
KING_STEPS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
DIAGONALS = ((-1, -1), (-1, 1), (1, -1), (1, 1))
STRAIGHTS = ((-1, 0), (1, 0), (0, -1), (0, 1))
PIECE_VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}


def opponent(color: str) -> str:
    return "b" if color == "w" else "w"


def square_name(row: int, col: int) -> str:
    return f"{FILES[col]}{8 - row}"


def parse_square(square: str) -> tuple[int, int]:
    if len(square) != 2 or square[0] not in FILES or square[1] not in RANKS:
        raise ValueError("invalid square")
    return 8 - int(square[1]), FILES.index(square[0])


def piece_color(piece: str | None) -> str | None:
    return "w" if piece and piece.isupper() else ("b" if piece else None)


@dataclass(frozen=True)
class ChessMove:
    from_sq: str
    to_sq: str
    promotion: str | None = None
    is_en_passant: bool = False
    is_castling: bool = False

    @property
    def uci(self) -> str:
        return self.from_sq + self.to_sq + (self.promotion or "")


class ChessBoard:
    """서버가 최종 판정하는 체스판. 모든 수는 legal_moves()를 거쳐서만 적용한다."""

    def __init__(self, fen: str = STARTING_FEN):
        self.load_fen(fen)
        self.position_counts = Counter({self.position_key(): 1})
        self.san_history: list[str] = []

    def load_fen(self, fen: str) -> None:
        fields = fen.split()
        if len(fields) != 6:
            raise ValueError("invalid FEN")
        rows = fields[0].split("/")
        if len(rows) != 8:
            raise ValueError("invalid board in FEN")
        self.board: list[list[str | None]] = []
        for fen_row in rows:
            row: list[str | None] = []
            for char in fen_row:
                if char.isdigit():
                    row.extend([None] * int(char))
                elif char.lower() in "pnbrqk":
                    row.append(char)
                else:
                    raise ValueError("invalid piece in FEN")
            if len(row) != 8:
                raise ValueError("invalid row length in FEN")
            self.board.append(row)
        self.turn = fields[1]
        if self.turn not in {"w", "b"}:
            raise ValueError("invalid active color")
        self.castling = "" if fields[2] == "-" else fields[2]
        self.en_passant = None if fields[3] == "-" else fields[3]
        self.halfmove_clock = int(fields[4])
        self.fullmove_number = int(fields[5])

    @classmethod
    def from_fen(cls, fen: str) -> "ChessBoard":
        return cls(fen)

    def clone(self) -> "ChessBoard":
        duplicate = ChessBoard(self.fen())
        duplicate.position_counts = self.position_counts.copy()
        duplicate.san_history = self.san_history.copy()
        return duplicate

    def fen(self) -> str:
        parts = []
        for row in self.board:
            empty = 0
            text = ""
            for piece in row:
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        text += str(empty)
                        empty = 0
                    text += piece
            if empty:
                text += str(empty)
            parts.append(text)
        return f"{'/'.join(parts)} {self.turn} {self.castling or '-'} {self.en_passant or '-'} {self.halfmove_clock} {self.fullmove_number}"

    def position_key(self) -> str:
        # 반복 무승부는 수순 카운터를 제외한 현재 국면으로 판단한다.
        return " ".join(self.fen().split()[:4])

    def piece_at(self, square: str) -> str | None:
        row, col = parse_square(square)
        return self.board[row][col]

    def _set_piece(self, square: str, piece: str | None) -> None:
        row, col = parse_square(square)
        self.board[row][col] = piece

    def _king_square(self, color: str) -> str:
        target = "K" if color == "w" else "k"
        for row in range(8):
            for col in range(8):
                if self.board[row][col] == target:
                    return square_name(row, col)
        raise ValueError("king missing from board")

    def is_square_attacked(self, square: str, by_color: str) -> bool:
        row, col = parse_square(square)
        pawn_row = row + (1 if by_color == "w" else -1)
        pawn = "P" if by_color == "w" else "p"
        for pawn_col in (col - 1, col + 1):
            if 0 <= pawn_row < 8 and 0 <= pawn_col < 8 and self.board[pawn_row][pawn_col] == pawn:
                return True
        knight = "N" if by_color == "w" else "n"
        for dr, dc in KNIGHT_STEPS:
            r, c = row + dr, col + dc
            if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == knight:
                return True
        king = "K" if by_color == "w" else "k"
        for dr, dc in KING_STEPS:
            r, c = row + dr, col + dc
            if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == king:
                return True
        for directions, attackers in ((DIAGONALS, "BQ" if by_color == "w" else "bq"), (STRAIGHTS, "RQ" if by_color == "w" else "rq")):
            for dr, dc in directions:
                r, c = row + dr, col + dc
                while 0 <= r < 8 and 0 <= c < 8:
                    piece = self.board[r][c]
                    if piece:
                        if piece in attackers:
                            return True
                        break
                    r, c = r + dr, c + dc
        return False

    def in_check(self, color: str | None = None) -> bool:
        color = color or self.turn
        return self.is_square_attacked(self._king_square(color), opponent(color))

    def _ray_moves(self, row: int, col: int, directions: Iterable[tuple[int, int]], color: str) -> Iterable[ChessMove]:
        for dr, dc in directions:
            r, c = row + dr, col + dc
            while 0 <= r < 8 and 0 <= c < 8:
                target = self.board[r][c]
                if target is None:
                    yield ChessMove(square_name(row, col), square_name(r, c))
                else:
                    if piece_color(target) != color:
                        yield ChessMove(square_name(row, col), square_name(r, c))
                    break
                r, c = r + dr, c + dc

    def pseudo_legal_moves(self, color: str | None = None) -> list[ChessMove]:
        color = color or self.turn
        moves: list[ChessMove] = []
        direction, start_row, promotion_row = (-1, 6, 0) if color == "w" else (1, 1, 7)
        for row in range(8):
            for col in range(8):
                piece = self.board[row][col]
                if piece_color(piece) != color:
                    continue
                kind = piece.lower()
                from_sq = square_name(row, col)
                if kind == "p":
                    one_row = row + direction
                    if 0 <= one_row < 8 and self.board[one_row][col] is None:
                        destination = square_name(one_row, col)
                        if one_row == promotion_row:
                            moves.extend(ChessMove(from_sq, destination, promo) for promo in "qrbn")
                        else:
                            moves.append(ChessMove(from_sq, destination))
                        two_row = row + 2 * direction
                        if row == start_row and self.board[two_row][col] is None:
                            moves.append(ChessMove(from_sq, square_name(two_row, col)))
                    for dc in (-1, 1):
                        r, c = row + direction, col + dc
                        if not (0 <= r < 8 and 0 <= c < 8):
                            continue
                        target = self.board[r][c]
                        destination = square_name(r, c)
                        if target and piece_color(target) != color:
                            if r == promotion_row:
                                moves.extend(ChessMove(from_sq, destination, promo) for promo in "qrbn")
                            else:
                                moves.append(ChessMove(from_sq, destination))
                        elif self.en_passant == destination:
                            moves.append(ChessMove(from_sq, destination, is_en_passant=True))
                elif kind == "n":
                    for dr, dc in KNIGHT_STEPS:
                        r, c = row + dr, col + dc
                        if 0 <= r < 8 and 0 <= c < 8 and piece_color(self.board[r][c]) != color:
                            moves.append(ChessMove(from_sq, square_name(r, c)))
                elif kind == "b":
                    moves.extend(self._ray_moves(row, col, DIAGONALS, color))
                elif kind == "r":
                    moves.extend(self._ray_moves(row, col, STRAIGHTS, color))
                elif kind == "q":
                    moves.extend(self._ray_moves(row, col, DIAGONALS + STRAIGHTS, color))
                elif kind == "k":
                    for dr, dc in KING_STEPS:
                        r, c = row + dr, col + dc
                        if 0 <= r < 8 and 0 <= c < 8 and piece_color(self.board[r][c]) != color:
                            moves.append(ChessMove(from_sq, square_name(r, c)))
                    moves.extend(self._castle_moves(color))
        return moves

    def _castle_moves(self, color: str) -> list[ChessMove]:
        row, rights = (7, ("K", "Q")) if color == "w" else (0, ("k", "q"))
        king_square = square_name(row, 4)
        rook = "R" if color == "w" else "r"
        if self.board[row][4] != ("K" if color == "w" else "k") or self.in_check(color):
            return []
        result = []
        if rights[0] in self.castling and self.board[row][7] == rook and all(self.board[row][c] is None for c in (5, 6)):
            if not self.is_square_attacked(square_name(row, 5), opponent(color)) and not self.is_square_attacked(square_name(row, 6), opponent(color)):
                result.append(ChessMove(king_square, square_name(row, 6), is_castling=True))
        if rights[1] in self.castling and self.board[row][0] == rook and all(self.board[row][c] is None for c in (1, 2, 3)):
            if not self.is_square_attacked(square_name(row, 3), opponent(color)) and not self.is_square_attacked(square_name(row, 2), opponent(color)):
                result.append(ChessMove(king_square, square_name(row, 2), is_castling=True))
        return result

    def legal_moves(self, color: str | None = None) -> list[ChessMove]:
        color = color or self.turn
        legal = []
        for move in self.pseudo_legal_moves(color):
            candidate = self.clone()
            candidate._apply_unchecked(move)
            if not candidate.in_check(color):
                legal.append(move)
        return legal

    def find_move(self, from_sq: str, to_sq: str, promotion: str | None = None) -> ChessMove:
        normalized_promotion = promotion.lower() if promotion else None
        matches = [move for move in self.legal_moves() if move.from_sq == from_sq and move.to_sq == to_sq]
        if not matches:
            raise ValueError("illegal move")
        if normalized_promotion:
            matches = [move for move in matches if move.promotion == normalized_promotion]
        elif any(move.promotion for move in matches):
            matches = [move for move in matches if move.promotion == "q"]
        if len(matches) != 1:
            raise ValueError("promotion choice required")
        return matches[0]

    def _update_castling_rights(self, move: ChessMove, moving_piece: str, captured_piece: str | None) -> None:
        rights = set(self.castling)
        if moving_piece == "K": rights -= {"K", "Q"}
        if moving_piece == "k": rights -= {"k", "q"}
        for square, right in (("h1", "K"), ("a1", "Q"), ("h8", "k"), ("a8", "q")):
            if move.from_sq == square or (move.to_sq == square and captured_piece):
                rights.discard(right)
        self.castling = "".join(ch for ch in "KQkq" if ch in rights)

    def _apply_unchecked(self, move: ChessMove) -> None:
        moving_piece = self.piece_at(move.from_sq)
        captured_piece = self.piece_at(move.to_sq)
        if not moving_piece:
            raise ValueError("missing moving piece")
        from_row, from_col = parse_square(move.from_sq)
        to_row, to_col = parse_square(move.to_sq)
        self._set_piece(move.from_sq, None)
        if move.is_en_passant:
            captured_square = square_name(from_row, to_col)
            captured_piece = self.piece_at(captured_square)
            self._set_piece(captured_square, None)
        placed_piece = (move.promotion.upper() if moving_piece.isupper() else move.promotion) if move.promotion else moving_piece
        self._set_piece(move.to_sq, placed_piece)
        if move.is_castling:
            if to_col == 6:
                rook_from, rook_to = square_name(from_row, 7), square_name(from_row, 5)
            else:
                rook_from, rook_to = square_name(from_row, 0), square_name(from_row, 3)
            self._set_piece(rook_to, self.piece_at(rook_from))
            self._set_piece(rook_from, None)
        self._update_castling_rights(move, moving_piece, captured_piece)
        self.en_passant = square_name((from_row + to_row) // 2, from_col) if moving_piece.lower() == "p" and abs(to_row - from_row) == 2 else None
        self.halfmove_clock = 0 if moving_piece.lower() == "p" or captured_piece else self.halfmove_clock + 1
        if self.turn == "b":
            self.fullmove_number += 1
        self.turn = opponent(self.turn)

    def san(self, move: ChessMove) -> str:
        piece = self.piece_at(move.from_sq)
        if not piece:
            raise ValueError("missing piece")
        if move.is_castling:
            text = "O-O" if move.to_sq[0] == "g" else "O-O-O"
        else:
            is_capture = bool(self.piece_at(move.to_sq)) or move.is_en_passant
            prefix = "" if piece.lower() == "p" else piece.upper()
            if prefix:
                rivals = [candidate for candidate in self.legal_moves() if candidate != move and candidate.to_sq == move.to_sq and self.piece_at(candidate.from_sq) == piece]
                if rivals:
                    same_file = any(candidate.from_sq[0] == move.from_sq[0] for candidate in rivals)
                    same_rank = any(candidate.from_sq[1] == move.from_sq[1] for candidate in rivals)
                    prefix += move.from_sq[1] if same_file else (move.from_sq[0] if same_rank else move.from_sq)
            elif is_capture:
                prefix = move.from_sq[0]
            text = prefix + ("x" if is_capture else "") + move.to_sq
            if move.promotion:
                text += "=" + move.promotion.upper()
        after = self.clone()
        after._apply_unchecked(move)
        if after.in_check():
            text += "#" if not after.legal_moves() else "+"
        return text

    def push(self, move: ChessMove) -> str:
        if move not in self.legal_moves():
            raise ValueError("illegal move")
        notation = self.san(move)
        self._apply_unchecked(move)
        self.san_history.append(notation)
        self.position_counts[self.position_key()] += 1
        return notation

    def push_uci(self, from_sq: str, to_sq: str, promotion: str | None = None) -> str:
        return self.push(self.find_move(from_sq, to_sq, promotion))

    def is_insufficient_material(self) -> bool:
        pieces = []
        bishops = []
        for row in range(8):
            for col in range(8):
                piece = self.board[row][col]
                if piece and piece.lower() != "k":
                    pieces.append(piece.lower())
                    if piece.lower() == "b": bishops.append((row + col) % 2)
        if not pieces:
            return True
        if len(pieces) == 1 and pieces[0] in {"b", "n"}:
            return True
        return all(piece == "b" for piece in pieces) and len(set(bishops)) == 1

    def result(self) -> dict:
        legal = self.legal_moves()
        if not legal:
            return {"status": "checkmate", "winner": opponent(self.turn)} if self.in_check() else {"status": "stalemate", "winner": None}
        if self.halfmove_clock >= 100:
            return {"status": "draw_50_move", "winner": None}
        if self.position_counts[self.position_key()] >= 3:
            return {"status": "draw_threefold", "winner": None}
        if self.is_insufficient_material():
            return {"status": "draw_insufficient_material", "winner": None}
        return {"status": "active", "winner": None}

    def captured_pieces(self) -> dict[str, list[str]]:
        initial = Counter("RNBQKBNR" + "P" * 8 + "rnbqkbnr" + "p" * 8)
        remaining = Counter(piece for row in self.board for piece in row if piece)
        captured = initial - remaining
        return {"white": sorted([piece for piece in captured.elements() if piece.islower()]), "black": sorted([piece for piece in captured.elements() if piece.isupper()])}

    def state(self) -> dict:
        return {
            "fen": self.fen(), "turn": self.turn, "legalMoves": [move.uci for move in self.legal_moves()],
            "check": self.in_check(), "result": self.result(), "history": self.san_history,
            "captured": self.captured_pieces(),
        }
