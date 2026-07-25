"""Optional Syzygy endgame tablebase support.

No tablebase files are bundled with ChessLab (they're large and licensed
separately). If the user points :class:`TablebaseProbe` at a directory
containing ``.rtbw``/``.rtbz`` files (via Engine Settings), positions with
few enough pieces get a perfect win/draw/loss and distance-to-zero readout
instead of just an engine estimate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import chess
import chess.syzygy

logger = logging.getLogger("chesslab.tablebase")

# Syzygy tables cover positions with up to 6 (or 7, for the newer/larger
# sets) pieces total, including both kings.
MAX_TABLEBASE_PIECES = 7

WDL_LABELS = {
    2: "Win",
    1: "Cursed win",
    0: "Draw",
    -1: "Blessed loss",
    -2: "Loss",
}


class TablebaseProbe:
    """Thin, failure-tolerant wrapper around ``chess.syzygy``."""

    def __init__(self) -> None:
        self._tablebase: Optional[chess.syzygy.Tablebase] = None
        self._path: Optional[str] = None

    def open(self, directory: str) -> bool:
        self.close()
        try:
            tb = chess.syzygy.open_tablebase(directory)
        except Exception:  # noqa: BLE001
            logger.warning("Could not open Syzygy tablebase at %s", directory, exc_info=True)
            return False
        self._tablebase = tb
        self._path = directory
        return True

    def close(self) -> None:
        if self._tablebase is not None:
            try:
                self._tablebase.close()
            except Exception:  # noqa: BLE001
                pass
        self._tablebase = None
        self._path = None

    @property
    def is_open(self) -> bool:
        return self._tablebase is not None

    def applies_to(self, board: chess.Board) -> bool:
        return chess.popcount(board.occupied) <= MAX_TABLEBASE_PIECES

    def probe(self, board: chess.Board) -> Optional[str]:
        """Return a short human-readable readout, or None if unavailable.

        Returns None (rather than raising) whenever the tablebase isn't
        loaded, the position has too many pieces, or the position is
        illegal for tablebase lookup (e.g. still has castling rights),
        since this is a "nice to have" readout, not a critical path.
        """
        if self._tablebase is None or not self.applies_to(board):
            return None
        try:
            wdl = self._tablebase.probe_wdl(board)
        except (chess.syzygy.MissingTableError, KeyError, ValueError):
            return None
        except Exception:  # noqa: BLE001
            logger.debug("Tablebase WDL probe failed", exc_info=True)
            return None

        label = WDL_LABELS.get(wdl, "Unknown")
        try:
            dtz = self._tablebase.probe_dtz(board)
            return f"Tablebase: {label} (DTZ {dtz})"
        except Exception:  # noqa: BLE001
            return f"Tablebase: {label}"
