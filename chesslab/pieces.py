"""Vector piece rendering.

python-chess bundles the classic "cburnett" piece set as inline SVG paths
(``chess.svg.piece``). Using it means ChessLab needs no bundled image
assets and pieces always render crisply at any board size. Renderers are
cached per (piece, size) so resizing or redrawing the board doesn't pay
the SVG-parsing cost repeatedly.
"""

from __future__ import annotations

from functools import lru_cache

import chess
import chess.svg
from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer


@lru_cache(maxsize=None)
def _piece_svg_bytes(piece_symbol: str, size: int) -> bytes:
    piece = chess.Piece.from_symbol(piece_symbol)
    svg_text = chess.svg.piece(piece, size=size)
    return svg_text.encode("utf-8")


def get_piece_renderer(piece: chess.Piece, size: int) -> QSvgRenderer:
    """Return a (possibly cached-source) QSvgRenderer for the given piece.

    Note: QSvgRenderer instances are not shared directly since Qt objects
    tied to a scene shouldn't be reused across items, but the underlying
    SVG bytes are cached, so this is still cheap.
    """
    data = _piece_svg_bytes(piece.symbol(), size)
    return QSvgRenderer(QByteArray(data))


PIECE_SETS = ("cburnett",)  # Extension point: additional sets could be added
# by mapping set name -> a function producing SVG bytes for a given piece.
