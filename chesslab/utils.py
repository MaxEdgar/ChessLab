"""Shared helper functions: logging setup, formatting, small utilities."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

import chess

from chesslab.config import LOG_DIR, LOG_FILE


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging: rotating file handler plus console output."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("chesslab")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def format_score(score: Optional[chess.engine.PovScore], pov_white: bool = True) -> str:
    """Format an engine score for display, e.g. '+1.35' or '#-3'."""
    if score is None:
        return "--"
    pov = score.white() if pov_white else score.pov(not pov_white)
    mate = pov.mate()
    if mate is not None:
        return f"#{mate}" if mate > 0 else f"#{mate}"
    cp = pov.score()
    if cp is None:
        return "--"
    value = cp / 100.0
    sign = "+" if value > 0 else ("" if value < 0 else "")
    return f"{sign}{value:.2f}"


def score_to_eval_bar_fraction(score: Optional[chess.engine.PovScore]) -> float:
    """Map a score (White's POV) to a 0..1 fraction for the evaluation bar.

    0.5 is balanced, 1.0 is a total white advantage, 0.0 total black
    advantage. Uses a smooth logistic-style compression so huge centipawn
    swings don't peg the bar instantly, mirroring how most chess GUIs
    render their eval bars.
    """
    if score is None:
        return 0.5
    pov = score.white()
    mate = pov.mate()
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    cp = pov.score()
    if cp is None:
        return 0.5
    # Logistic compression centered at 0cp, scaled so ~300cp ~= 0.8 fraction.
    import math

    k = 0.0038
    fraction = 1.0 / (1.0 + math.exp(-k * cp))
    return max(0.0, min(1.0, fraction))


def square_name(square: int) -> str:
    return chess.square_name(square)


def piece_unicode(piece: chess.Piece) -> str:
    symbols = {
        chess.PAWN: "P",
        chess.KNIGHT: "N",
        chess.BISHOP: "B",
        chess.ROOK: "R",
        chess.QUEEN: "Q",
        chess.KING: "K",
    }
    letter = symbols[piece.piece_type]
    return letter if piece.color == chess.WHITE else letter.lower()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
