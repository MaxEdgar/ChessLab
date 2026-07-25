"""Game state, move history, PGN/FEN I/O, and move-quality classification.

This module has no dependency on the engine's threading model; it only
understands ``chess.Board``/``chess.engine.PovScore`` data. That keeps it
independently testable and keeps :mod:`chesslab.engine` free of any game
bookkeeping concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import chess.pgn
from PySide6.QtCore import QObject, Signal

from chesslab.openings import lookup_opening

logger = logging.getLogger("chesslab.analysis")


CLASS_BRILLIANT = "Brilliant"
CLASS_BEST = "Best"
CLASS_EXCELLENT = "Excellent"
CLASS_GOOD = "Good"
CLASS_INACCURACY = "Inaccuracy"
CLASS_MISTAKE = "Mistake"
CLASS_BLUNDER = "Blunder"

CLASS_COLORS = {
    CLASS_BRILLIANT: "#26c2a3",
    CLASS_BEST: "#5cb85c",
    CLASS_EXCELLENT: "#8bc34a",
    CLASS_GOOD: "#9aa3b2",
    CLASS_INACCURACY: "#e0a63e",
    CLASS_MISTAKE: "#e07a3e",
    CLASS_BLUNDER: "#d9534f",
}


def _score_cp_from_mover_pov(score: chess.engine.PovScore, mover_is_white: bool) -> float:
    """Return a centipawn-ish float from the mover's perspective for comparison.

    Mate scores are mapped to large finite values so they compare sensibly
    against centipawn scores without special-casing every comparison site.
    """
    pov = score.white() if mover_is_white else score.black()
    mate = pov.mate()
    if mate is not None:
        return 100_000.0 if mate > 0 else -100_000.0
    cp = pov.score()
    return float(cp) if cp is not None else 0.0


def classify_move(
    eval_before: Optional[chess.engine.PovScore],
    eval_after: Optional[chess.engine.PovScore],
    mover_is_white: bool,
    was_only_good_move: bool = False,
    material_sacrificed: bool = False,
) -> Optional[str]:
    """Classify a played move by comparing engine eval before/after.

    Both scores must be from a search of the position *before* the move
    was played (eval_before) and the position *after* it was played
    (eval_after), each converted to the mover's point of view so that
    "loss" always means the mover's position got objectively worse.

    This is a heuristic, centipawn-loss-based classifier, consistent with
    how most consumer chess GUIs approximate move quality without a full
    game-level re-analysis.
    """
    if eval_before is None or eval_after is None:
        return None

    before = _score_cp_from_mover_pov(eval_before, mover_is_white)
    # eval_after is scored from the position after the move, where it is
    # the opponent's turn; flip sign convention by re-reading from mover POV.
    after = _score_cp_from_mover_pov(eval_after, mover_is_white)

    loss = before - after  # positive = position got worse for the mover

    if material_sacrificed and loss <= 20:
        return CLASS_BRILLIANT
    if loss <= 5:
        return CLASS_BEST if was_only_good_move else CLASS_EXCELLENT
    if loss <= 20:
        return CLASS_GOOD
    if loss <= 50:
        return CLASS_INACCURACY
    if loss <= 150:
        return CLASS_MISTAKE
    return CLASS_BLUNDER


@dataclass
class MoveRecord:
    ply: int
    move: chess.Move
    san: str
    fen_before: str
    fen_after: str
    eval_before: Optional[chess.engine.PovScore] = None
    eval_after: Optional[chess.engine.PovScore] = None
    classification: Optional[str] = None
    opening_name: Optional[str] = None


class GameController(QObject):
    """Owns the authoritative board plus a branchable move history.

    History model: ``moves_played`` holds every move on the current line;
    ``current_ply`` is the index into it representing the live board
    position (so the user can step backward/forward through the line).
    Playing a new move while not at the tip discards the old continuation
    from that point on, matching how every analysis board (Lichess,
    Chess.com) treats branching without a full PGN variation tree.
    """

    positionChanged = Signal()
    historyChanged = Signal()
    gameReset = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.board = chess.Board()
        self.starting_fen = chess.STARTING_FEN
        self.moves_played: list[MoveRecord] = []
        self.current_ply = 0

    # -- game lifecycle ----------------------------------------------------
    def new_game(self) -> None:
        self.board = chess.Board()
        self.starting_fen = chess.STARTING_FEN
        self.moves_played.clear()
        self.current_ply = 0
        self.gameReset.emit()
        self.historyChanged.emit()
        self.positionChanged.emit()

    def set_fen(self, fen: str) -> None:
        board = chess.Board(fen)  # raises ValueError if invalid; caller should catch
        self.board = board
        self.starting_fen = fen
        self.moves_played.clear()
        self.current_ply = 0
        self.gameReset.emit()
        self.historyChanged.emit()
        self.positionChanged.emit()

    def set_side_to_move(self, white_to_move: bool) -> None:
        """Manually flip whose turn it is, without playing a move.

        This is what lets an analysis board let the user "move for either
        side freely": rather than bypassing chess legality (which would
        make move generation meaningless), the user explicitly declares
        whose turn it is, then plays a fully legal move for that side.
        """
        if self.board.turn == white_to_move:
            return
        self.board.turn = white_to_move
        # Clear en-passant target since it no longer necessarily applies
        # once the side to move has been overridden by the user.
        self.board.ep_square = None
        self.positionChanged.emit()

    # -- moves ---------------------------------------------------------------
    def push_move(self, move: chess.Move) -> Optional[MoveRecord]:
        if move not in self.board.legal_moves:
            return None
        fen_before = self.board.fen()
        san = self.board.san(move)
        mover_white = self.board.turn
        self.board.push(move)
        fen_after = self.board.fen()

        # Branching: discard any old "future" once a new move is played
        # from a position that isn't the current tip of the line.
        del self.moves_played[self.current_ply :]

        record = MoveRecord(
            ply=self.current_ply,
            move=move,
            san=san,
            fen_before=fen_before,
            fen_after=fen_after,
        )
        full_sequence = self.san_sequence(upto_ply=self.current_ply) + [san]
        record.opening_name = lookup_opening(full_sequence)
        self.moves_played.append(record)
        self.current_ply += 1

        self.historyChanged.emit()
        self.positionChanged.emit()
        return record

    def push_uci(self, uci: str) -> Optional[MoveRecord]:
        try:
            move = self.board.parse_uci(uci)
        except ValueError:
            return None
        return self.push_move(move)

    def san_sequence(self, upto_ply: Optional[int] = None) -> list[str]:
        limit = self.current_ply if upto_ply is None else upto_ply
        return [record.san for record in self.moves_played[:limit]]

    def can_undo(self) -> bool:
        return self.current_ply > 0

    def can_redo(self) -> bool:
        return self.current_ply < len(self.moves_played)

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self.board.pop()
        self.current_ply -= 1
        self.positionChanged.emit()
        self.historyChanged.emit()
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        record = self.moves_played[self.current_ply]
        self.board.push(record.move)
        self.current_ply += 1
        self.positionChanged.emit()
        self.historyChanged.emit()
        return True

    def go_to_start(self) -> None:
        while self.undo():
            pass

    def go_to_end(self) -> None:
        while self.redo():
            pass

    def jump_to_ply(self, ply: int) -> None:
        ply = max(0, min(ply, len(self.moves_played)))
        while self.current_ply > ply:
            self.undo()
        while self.current_ply < ply:
            self.redo()

    def record_eval(
        self,
        ply: int,
        eval_before: Optional[chess.engine.PovScore],
        eval_after: Optional[chess.engine.PovScore],
        mover_is_white: bool,
        material_sacrificed: bool = False,
    ) -> None:
        if ply < 0 or ply >= len(self.moves_played):
            return
        record = self.moves_played[ply]
        record.eval_before = eval_before
        record.eval_after = eval_after
        record.classification = classify_move(
            eval_before, eval_after, mover_is_white, material_sacrificed=material_sacrificed
        )
        self.historyChanged.emit()

    @property
    def current_opening_name(self) -> Optional[str]:
        if self.current_ply == 0:
            return None
        return self.moves_played[self.current_ply - 1].opening_name

    # -- PGN / FEN -------------------------------------------------------
    def to_pgn_game(self, headers: Optional[dict] = None) -> chess.pgn.Game:
        game = chess.pgn.Game()
        if headers:
            for key, value in headers.items():
                game.headers[key] = value
        try:
            game.setup(chess.Board(self.starting_fen))
        except ValueError:
            game.setup(chess.Board())
        node = game
        board = chess.Board(self.starting_fen)
        for record in self.moves_played:
            node = node.add_variation(record.move)
            board.push(record.move)
            if record.classification:
                node.comment = record.classification
        return game

    def save_pgn(self, path: str | Path, headers: Optional[dict] = None) -> None:
        game = self.to_pgn_game(headers)
        with open(path, "w", encoding="utf-8") as fh:
            print(game, file=fh, end="\n\n")

    def load_pgn(self, path: str | Path) -> bool:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            game = chess.pgn.read_game(fh)
        if game is None:
            return False
        board = game.board()
        self.starting_fen = board.fen()
        self.board = board.copy()
        self.moves_played.clear()
        for move in game.mainline_moves():
            san = self.board.san(move)
            fen_before = self.board.fen()
            self.board.push(move)
            fen_after = self.board.fen()
            record = MoveRecord(
                ply=len(self.moves_played),
                move=move,
                san=san,
                fen_before=fen_before,
                fen_after=fen_after,
            )
            self.moves_played.append(record)
        self.current_ply = len(self.moves_played)
        self.gameReset.emit()
        self.historyChanged.emit()
        self.positionChanged.emit()
        return True

    def copy_fen(self) -> str:
        return self.board.fen()
