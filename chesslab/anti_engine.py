"""Anti-Engine Analysis: human-like, professional-quality move selection.

Instead of returning the raw engine top move (which often looks robotic
and relies on deep tactical justification no human would find), this
module queries Stockfish for the top *N* candidate moves and then scores
each one with a battery of human-play heuristics.  The result is a move
that a strong club or professional player would naturally choose: sound,
principled, and easy to understand — yet still very strong.

Usage::

    anti = AntiEngineAnalysis()
    anti.set_engine(engine_manager)          # the existing EngineManager
    anti.analyze(board)                      # kicks off a background search
    move = anti.get_best_human_move()        # blocking; returns chess.Move or None

The module is intentionally independent of the GUI threading model; all
heavy lifting happens inside ``EngineManager``'s async loop.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import chess
import chess.engine

logger = logging.getLogger("chesslab.anti_engine")

# ---------------------------------------------------------------------------
# Piece-square bonus tables (simplified, White POV — mirror for Black).
# Encourage pieces toward natural, human-friendly squares.
# ---------------------------------------------------------------------------

_PAWN_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]

_KNIGHT_TABLE = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]

_BISHOP_TABLE = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]

_ROOK_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]

_QUEEN_TABLE = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]

_KING_MIDDLE_TABLE = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]

_KING_END_TABLE = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]

_PST = {
    chess.PAWN: _PAWN_TABLE,
    chess.KNIGHT: _KNIGHT_TABLE,
    chess.BISHOP: _BISHOP_TABLE,
    chess.ROOK: _ROOK_TABLE,
    chess.QUEEN: _QUEEN_TABLE,
    chess.KING: _KING_MIDDLE_TABLE,
}

MATERIAL_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------

def _pst_value(piece: chess.Piece, square: int) -> int:
    """Return the piece-square table bonus for a piece on a square."""
    table = _PST.get(piece.piece_type)
    if table is None:
        return 0
    # Mirror the table for Black (rows reversed)
    rank = chess.square_rank(square)
    file_idx = chess.square_file(square)
    if piece.color == chess.BLACK:
        rank = 7 - rank
    return table[rank * 8 + file_idx]


def _is_development_move(board: chess.Board, move: chess.Move) -> bool:
    """Return True if the move develops a piece from its starting square."""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return False
    if piece.piece_type == chess.PAWN:
        return False
    # Starting squares for each piece type
    start_squares = {
        chess.KNIGHT: [chess.B1, chess.G1, chess.B8, chess.G8],
        chess.BISHOP: [chess.C1, chess.F1, chess.C8, chess.F8],
        chess.ROOK: [chess.A1, chess.H1, chess.A8, chess.H8],
        chess.QUEEN: [chess.D1, chess.D8],
    }
    candidates = start_squares.get(piece.piece_type, [])
    return move.from_square in candidates


def _is_castle_move(board: chess.Board, move: chess.Move) -> bool:
    """Return True if the move is castling."""
    return board.is_castling(move)


def _center_control_delta(board: chess.Board, move: chess.Move) -> int:
    """Estimate how much the move improves center control (files d/e, ranks 3-6)."""
    center_squares = [
        chess.D4, chess.E4, chess.D5, chess.E5,
        chess.C3, chess.D3, chess.E3, chess.F3,
        chess.C6, chess.D6, chess.E6, chess.F6,
    ]
    score = 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    # Moving a piece into the center is good
    if move.to_square in center_squares:
        score += 15
    # Moving a pawn to control center squares
    if piece.piece_type == chess.PAWN:
        if move.to_square in [chess.D4, chess.E4, chess.D5, chess.E5]:
            score += 20
        # Pawn breaks in the center
        target_rank = chess.square_rank(move.to_square)
        if piece.color == chess.WHITE and target_rank == 3:
            score += 10
        elif piece.color == chess.BLACK and target_rank == 4:
            score += 10
    return score


def _king_safety_delta(board: chess.Board, move: chess.Move) -> int:
    """Estimate king safety improvement from a move."""
    score = 0
    # Castling is great for king safety
    if board.is_castling(move):
        score += 40
    # Moving king away from center in middlegame
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type == chess.KING:
        if not board.is_check():
            # Penalize moving king to an exposed square
            if board.is_attacked_by(not piece.color, move.to_square):
                score -= 20
    return score


def _tactical_value(board: chess.Board, move: chess.Move) -> int:
    """Score tactical features: captures, checks, threats."""
    score = 0
    # Captures (but not reckless ones)
    if board.is_capture(move):
        victim = board.piece_at(move.to_square)
        attacker = board.piece_at(move.from_square)
        if victim and attacker:
            # Good capture: cheaper piece takes expensive piece
            if MATERIAL_VALUES.get(victim.piece_type, 0) > MATERIAL_VALUES.get(attacker.piece_type, 0):
                score += 30
            # Equal or losing capture gets smaller bonus
            elif MATERIAL_VALUES.get(victim.piece_type, 0) == MATERIAL_VALUES.get(attacker.piece_type, 0):
                score += 10
            else:
                score -= 5  # Slight penalty for giving up material
    # Checks are sometimes good but not always
    test_board = board.copy()
    test_board.push(move)
    if test_board.is_check():
        score += 8
    # Attacking undefended pieces
    if board.is_attacked_by(board.turn, move.to_square):
        target = board.piece_at(move.to_square)
        if target:
            score += 5
    return score


def _opening_principles(board: chess.Board, move: chess.Move) -> int:
    """Score based on opening principles: develop pieces, castle early, don't move queen early."""
    score = 0
    move_number = board.fullmove_number
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0

    if move_number <= 15:  # Opening phase
        # Encourage piece development
        if _is_development_move(board, move):
            score += 25
        # Encourage castling early
        if board.is_castling(move):
            score += 35
        # Penalize moving queen early (except for specific known openings)
        if piece.piece_type == chess.QUEEN and move_number <= 8:
            # Exception: common queen moves like Qh4 in scholar's mate, Qd2, Qe2
            to_file = chess.square_file(move.to_square)
            if to_file not in [chess.D_FILE, chess.E_FILE]:
                score -= 15
        # Don't move the same piece twice in the opening (unless it's a knight repositioning)
        if piece.piece_type in [chess.KNIGHT, chess.BISHOP]:
            # Check if this piece has moved before
            for record_move in board.move_stack:
                if record_move.from_square == move.from_square:
                    score -= 10
                    break
    return score


def _middlegame_principles(board: chess.Board, move: chess.Move) -> int:
    """Score based on middlegame principles: piece activity, pawn structure."""
    score = 0
    move_number = board.fullmove_number
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0

    if 15 < move_number <= 40:  # Middlegame
        # Encourage piece activity
        if piece.piece_type in [chess.KNIGHT, chess.BISHOP]:
            if _is_development_move(board, move):
                score += 10
        # Pawn structure: avoid isolated/doubled pawns (simplified)
        if piece.piece_type == chess.PAWN:
            # Central pawn pushes are good
            to_file = chess.square_file(move.to_square)
            if to_file in [chess.D_FILE, chess.E_FILE]:
                score += 10
    return score


def _endgame_principles(board: chess.Board, move: chess.Move) -> int:
    """Score based on endgame principles: king activity, passed pawns."""
    score = 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0

    # In endgame, king should be active
    if piece.piece_type == chess.KING:
        if not board.is_check():
            # Centralize king
            to_file = chess.square_file(move.to_square)
            to_rank = chess.square_rank(move.to_square)
            center_dist = abs(to_file - 3.5) + abs(to_rank - 3.5)
            score += int(20 - center_dist * 5)

    # Passed pawns should advance
    if piece.piece_type == chess.PAWN:
        score += 15  # General bonus for advancing pawns in endgame

    return score


def score_move_human_like(board: chess.Board, move: chess.Move) -> float:
    """Score a move for human-likeness and practical strength.

    Returns a float score — higher is more human-like and strong.
    The scoring combines:
    - Engine evaluation (primary signal)
    - Piece-square tables (positional soundness)
    - Opening/middlegame/endgame principles
    - Tactical awareness
    """
    score = 0.0

    # 1. Piece-square table bonus
    piece = board.piece_at(move.from_square)
    if piece:
        # PST value after move
        board.push(move)
        pst_after = _pst_value(piece, move.to_square)
        # PST value before move (approximate)
        pst_before = _pst_value(piece, move.from_square)
        score += (pst_after - pst_before) * 0.5
        board.pop()

    # 2. Center control
    score += _center_control_delta(board, move) * 0.8

    # 3. King safety
    score += _king_safety_delta(board, move) * 0.6

    # 4. Tactical value
    score += _tactical_value(board, move) * 0.7

    # 5. Opening principles
    score += _opening_principles(board, move) * 0.9

    # 6. Middlegame principles
    score += _middlegame_principles(board, move) * 0.7

    # 7. Endgame principles
    score += _endgame_principles(board, move) * 0.8

    # 8. Penalize engine-like moves: very long quiet moves that go nowhere
    # (simplified: penalize moving to squares far from the action)
    if not board.is_capture(move) and not board.is_check():
        to_file = chess.square_file(move.to_square)
        to_rank = chess.square_rank(move.to_square)
        center_dist = abs(to_file - 3.5) + abs(to_rank - 3.5)
        if center_dist > 5:
            score -= 10

    return score


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

@dataclass
class CandidateMove:
    """A candidate move with its engine eval and human-likeness score."""
    move: chess.Move
    engine_score: float  # centipawns from engine
    human_score: float   # human-likeness score
    combined: float = 0.0

    def __post_init__(self) -> None:
        # Combined score: 60% engine strength + 40% human-likeness
        self.combined = self.engine_score * 0.6 + self.human_score * 0.4


class AntiEngineAnalysis:
    """Select moves that look natural and human-like while still being strong.

    Instead of blindly returning Stockfish's top move, this queries the
    engine for the top *N* candidates and picks the one that scores best
    on a battery of human-play heuristics: piece development, center
    control, king safety, opening principles, and positional soundness.

    The result is a move a professional player might choose — strong,
    principled, and easy to understand — not an engine line that only
    makes sense 20 moves deep.
    """

    def __init__(self) -> None:
        self._engine = None  # EngineManager reference
        self._multipv = 5    # number of candidates to consider
        self._candidates: list[CandidateMove] = []
        self._analyzing = False

    def set_engine(self, engine) -> None:
        """Set the EngineManager instance to use for analysis."""
        self._engine = engine

    def analyze(self, board: chess.Board, time_ms: int = 3000) -> None:
        """Start an analysis of the given position.

        This requests the engine to analyze with MultiPV enabled so we
        get multiple candidate moves to choose from.
        """
        if self._engine is None or not self._engine.is_running:
            logger.warning("AntiEngineAnalysis: engine not running")
            return

        self._analyzing = True
        self._candidates.clear()

        # We use the engine's analysis infrastructure but with higher MultiPV
        # to get multiple candidates. The engine manager handles the async loop.
        self._engine.request_anti_engine_analysis(board, time_ms, self._multipv)

    def receive_candidates(self, board: chess.Board, moves_data: list) -> None:
        """Called by the engine manager with candidate move data.

        ``moves_data`` is a list of tuples: (move, score_pov, pv)
        where score_pov is a PovScore from the engine.
        """
        self._candidates.clear()

        for move, score, pv in moves_data:
            # Convert score to centipawns from the mover's perspective
            engine_cp = 0.0
            if score is not None:
                pov = score.white() if board.turn == chess.WHITE else score.black()
                mate = pov.mate()
                if mate is not None:
                    engine_cp = 10000.0 if mate > 0 else -10000.0
                else:
                    cp = pov.score()
                    engine_cp = float(cp) if cp is not None else 0.0

            # Calculate human-likeness score
            human = score_move_human_like(board, move)

            candidate = CandidateMove(move=move, engine_score=engine_cp, human_score=human)
            self._candidates.append(candidate)

        # Sort by combined score (best first)
        self._candidates.sort(key=lambda c: c.combined, reverse=True)
        self._analyzing = False

        if self._candidates:
            best = self._candidates[0]
            logger.info(
                "AntiEngine: best human-like move=%s engine=%.0f human=%.1f combined=%.1f",
                best.move, best.engine_score, best.human_score, best.combined,
            )

    def get_best_human_move(self) -> Optional[chess.Move]:
        """Return the best human-like move, or None if no candidates."""
        if not self._candidates:
            return None
        return self._candidates[0].move

    def get_candidates(self) -> list[CandidateMove]:
        """Return all scored candidates (for display/debugging)."""
        return list(self._candidates)

    @property
    def is_analyzing(self) -> bool:
        return self._analyzing
