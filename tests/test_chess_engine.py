import unittest

from chess_engine import ChessBoard


class ChessEngineTests(unittest.TestCase):
    def test_starting_position_has_twenty_legal_moves(self):
        self.assertEqual(len(ChessBoard().legal_moves()), 20)

    def test_pawn_double_move_and_en_passant_window(self):
        board = ChessBoard()
        for move in (("e2", "e4"), ("a7", "a6"), ("e4", "e5"), ("d7", "d5")):
            board.push_uci(*move)
        self.assertIn("e5d6", [move.uci for move in board.legal_moves()])
        board.push_uci("a2", "a3")
        self.assertNotIn("e5d6", [move.uci for move in board.legal_moves()])

    def test_castling_cannot_cross_attack(self):
        board = ChessBoard("r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1")
        self.assertNotIn("e1g1", [move.uci for move in board.legal_moves()])

    def test_promotion_and_checkmate(self):
        board = ChessBoard("7k/P7/8/8/8/8/7K/8 w - - 0 1")
        self.assertIn("a7a8q", [move.uci for move in board.legal_moves()])
        board = ChessBoard()
        for move in (("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")):
            board.push_uci(*move)
        self.assertEqual(board.result()["status"], "checkmate")

    def test_stalemate_and_insufficient_material(self):
        self.assertEqual(ChessBoard("7k/5Q2/7K/8/8/8/8/8 b - - 0 1").result()["status"], "stalemate")
        self.assertEqual(ChessBoard("7k/8/8/8/8/8/8/K7 w - - 0 1").result()["status"], "draw_insufficient_material")

    def test_pinned_piece_cannot_expose_king(self):
        board = ChessBoard("4r2k/8/8/8/8/8/4R3/4K3 w - - 0 1")
        self.assertNotIn("e2d2", [move.uci for move in board.legal_moves()])

    def test_threefold_repetition(self):
        board = ChessBoard()
        for move in (("g1", "f3"), ("g8", "f6"), ("f3", "g1"), ("f6", "g8")) * 2:
            board.push_uci(*move)
        self.assertEqual(board.result()["status"], "draw_threefold")


if __name__ == "__main__":
    unittest.main()
