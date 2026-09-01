"""Interactive chessboard widget.

Rendering uses a ``QGraphicsScene`` of 64 squares plus one
``QGraphicsSvgItem`` per occupied square (vector piece glyphs from
:mod:`chesslab.pieces`). Interaction supports both click-to-move and
drag-and-drop, legal-move highlighting, last-move/check highlighting,
an optional best-move arrow, coordinates, and board flipping.

The widget never mutates game state itself beyond emitting
``moveAttempted`` with a validated legal move (or a promotion-pending
move needing a piece choice) — the surrounding :class:`~chesslab.analysis.
GameController` remains the single source of truth for the position.
"""

from __future__ import annotations

from typing import Optional

import chess
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from chesslab.pieces import get_piece_renderer
from chesslab.theme import BOARD_THEMES, BoardPalette

try:
    from PySide6.QtSvgWidgets import QGraphicsSvgItem
except ImportError:  # pragma: no cover - older PySide6 layout fallback
    from PySide6.QtSvg import QGraphicsSvgItem


class _PieceItem(QGraphicsSvgItem):
    """A single piece glyph positioned on the board scene."""

    def __init__(self, piece: chess.Piece, square: int, size: int) -> None:
        super().__init__()
        self.square = square
        self.piece = piece
        # setSharedRenderer() only stores a raw pointer on the C++ side; it
        # does not keep the QSvgRenderer alive from Python's perspective.
        # Without holding our own reference here, the renderer gets garbage
        # collected while this item still points at it, which segfaults on
        # teardown (or any redraw). Keeping `self._renderer` alive for the
        # lifetime of the item is required, not optional.
        self._renderer = get_piece_renderer(piece, size)
        self.setSharedRenderer(self._renderer)
        self.setZValue(10)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)


class BoardView(QGraphicsView):
    """Renders a ``chess.Board`` and reports user move attempts."""

    moveAttempted = Signal(object)  # emits a chess.Move (promotion default: queen)
    promotionNeeded = Signal(object, object)  # (from_square, to_square) -> caller resolves
    squareClicked = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.square_size = 72
        self.flipped = False
        self.show_coordinates = True
        self.show_legal_dots = True
        self.show_best_arrow = True
        self.palette_theme: BoardPalette = BOARD_THEMES["midnight"]

        self.board = chess.Board()
        self._piece_items: dict[int, _PieceItem] = {}
        self._square_items: dict[int, QGraphicsRectItem] = {}
        self._overlay_items: list[QGraphicsItem] = []
        self._coord_items: list[QGraphicsSimpleTextItem] = []

        self._selected_square: Optional[int] = None
        self._drag_item: Optional[_PieceItem] = None
        self._drag_origin_square: Optional[int] = None
        self._drag_start_pos = QPointF()
        self._last_move: Optional[chess.Move] = None
        self._best_move: Optional[chess.Move] = None
        self._threat_move: Optional[chess.Move] = None
        self._coach_from_square: Optional[int] = None

        self._build_squares()
        self.set_board(self.board)

    # -- geometry ---------------------------------------------------------
    def board_pixel_size(self) -> int:
        return self.square_size * 8

    def _file_rank_to_visual(self, file_idx: int, rank_idx: int) -> tuple[int, int]:
        """Map chess file/rank (0-7, a1 origin) to on-screen column/row."""
        col = file_idx if not self.flipped else 7 - file_idx
        row = (7 - rank_idx) if not self.flipped else rank_idx
        return col, row

    def _square_to_scene_rect(self, square: int) -> QRectF:
        file_idx = chess.square_file(square)
        rank_idx = chess.square_rank(square)
        col, row = self._file_rank_to_visual(file_idx, rank_idx)
        s = self.square_size
        return QRectF(col * s, row * s, s, s)

    def _scene_pos_to_square(self, pos: QPointF) -> Optional[int]:
        s = self.square_size
        col = int(pos.x() // s)
        row = int(pos.y() // s)
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        file_idx = col if not self.flipped else 7 - col
        rank_idx = (7 - row) if not self.flipped else row
        return chess.square(file_idx, rank_idx)

    # -- building / redrawing ----------------------------------------------
    def _build_squares(self) -> None:
        for item in self._square_items.values():
            self._scene.removeItem(item)
        self._square_items.clear()

        for square in chess.SQUARES:
            rect_geo = self._square_to_scene_rect(square)
            rect = QGraphicsRectItem(rect_geo)
            rect.setZValue(0)
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            self._scene.addItem(rect)
            self._square_items[square] = rect
        self._paint_squares()
        self._scene.setSceneRect(0, 0, self.board_pixel_size(), self.board_pixel_size())
        self._build_coordinates()

    def _paint_squares(self) -> None:
        light = QColor(self.palette_theme.light_square)
        dark = QColor(self.palette_theme.dark_square)
        for square, rect in self._square_items.items():
            is_light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            rect.setBrush(QBrush(light if is_light else dark))

    def _build_coordinates(self) -> None:
        for item in self._coord_items:
            self._scene.removeItem(item)
        self._coord_items.clear()
        if not self.show_coordinates:
            return

        s = self.square_size
        font = QFont()
        font.setPointSize(max(7, s // 8))
        for file_idx in range(8):
            col, _ = self._file_rank_to_visual(file_idx, 0)
            label = chess.FILE_NAMES[file_idx]
            text = QGraphicsSimpleTextItem(label)
            text.setFont(font)
            text.setBrush(QBrush(QColor(self.palette_theme.dark_square).lighter(140)))
            text.setPos(col * s + s - 12, self.board_pixel_size() - 16)
            text.setZValue(5)
            self._scene.addItem(text)
            self._coord_items.append(text)
        for rank_idx in range(8):
            _, row = self._file_rank_to_visual(0, rank_idx)
            label = str(rank_idx + 1)
            text = QGraphicsSimpleTextItem(label)
            text.setFont(font)
            text.setBrush(QBrush(QColor(self.palette_theme.dark_square).lighter(140)))
            text.setPos(3, row * s + 2)
            text.setZValue(5)
            self._scene.addItem(text)
            self._coord_items.append(text)

    def set_board(self, board: chess.Board, last_move: Optional[chess.Move] = None) -> None:
        self.board = board
        self._last_move = last_move if last_move is not None else (
            board.peek() if board.move_stack else None
        )
        self._redraw_pieces()
        self._redraw_overlays()

    def _redraw_pieces(self) -> None:
        for item in self._piece_items.values():
            self._scene.removeItem(item)
        self._piece_items.clear()

        for square in chess.SQUARES:
            piece = self.board.piece_at(square)
            if piece is None:
                continue
            item = _PieceItem(piece, square, self.square_size)
            rect = self._square_to_scene_rect(square)
            item.setPos(rect.topLeft())
            self._scale_piece_item(item)
            self._scene.addItem(item)
            self._piece_items[square] = item

    def _scale_piece_item(self, item: _PieceItem) -> None:
        bounds = item.boundingRect()
        if bounds.width() <= 0:
            return
        scale = self.square_size / bounds.width()
        item.setScale(scale)

    def _redraw_overlays(self) -> None:
        for item in self._overlay_items:
            self._scene.removeItem(item)
        self._overlay_items.clear()

        if self._last_move is not None:
            self._highlight_square(self._last_move.from_square, self.palette_theme.last_move)
            self._highlight_square(self._last_move.to_square, self.palette_theme.last_move)

        if self._selected_square is not None:
            self._highlight_square(self._selected_square, self.palette_theme.selected)
            if self.show_legal_dots:
                for move in self.board.legal_moves:
                    if move.from_square == self._selected_square:
                        self._draw_legal_dot(move.to_square, capture=self.board.is_capture(move))

        if self.board.is_check():
            king_square = self.board.king(self.board.turn)
            if king_square is not None:
                self._highlight_square(king_square, self.palette_theme.check)

        # Coach mode: highlight the piece the engine recommends moving
        if self._coach_from_square is not None and self._best_move is not None:
            self._highlight_square(self._coach_from_square, self.palette_theme.selected)

        if self.show_best_arrow and self._best_move is not None:
            # Check if this move leads to checkmate
            arrow_color = self.palette_theme.arrow
            if self._best_move in self.board.legal_moves:
                test_board = self.board.copy()
                test_board.push(self._best_move)
                if test_board.is_checkmate():
                    arrow_color = "#2ecc71c0"  # green for checkmate
            self._draw_arrow(
                self._best_move.from_square, self._best_move.to_square, arrow_color
            )
        if self._threat_move is not None:
            self._draw_arrow(
                self._threat_move.from_square, self._threat_move.to_square, "#d9534fb0"
            )

    def _highlight_square(self, square: int, color_hex: str) -> None:
        rect_geo = self._square_to_scene_rect(square)
        rect = QGraphicsRectItem(rect_geo)
        rect.setBrush(QBrush(QColor(color_hex)))
        rect.setPen(QPen(Qt.PenStyle.NoPen))
        rect.setZValue(1)
        self._scene.addItem(rect)
        self._overlay_items.append(rect)

    def _draw_legal_dot(self, square: int, capture: bool) -> None:
        rect_geo = self._square_to_scene_rect(square)
        s = self.square_size
        if capture:
            margin = s * 0.06
            dot = QGraphicsEllipseItem(
                rect_geo.x() + margin,
                rect_geo.y() + margin,
                s - 2 * margin,
                s - 2 * margin,
            )
            dot.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            pen = QPen(QColor(self.palette_theme.legal_dot))
            pen.setWidth(max(3, s // 14))
            dot.setPen(pen)
        else:
            radius = s * 0.16
            cx = rect_geo.x() + s / 2
            cy = rect_geo.y() + s / 2
            dot = QGraphicsEllipseItem(cx - radius, cy - radius, radius * 2, radius * 2)
            dot.setBrush(QBrush(QColor(self.palette_theme.legal_dot)))
            dot.setPen(QPen(Qt.PenStyle.NoPen))
        dot.setZValue(2)
        self._scene.addItem(dot)
        self._overlay_items.append(dot)

    def _draw_arrow(self, from_sq: int, to_sq: int, color_hex: str) -> None:
        s = self.square_size
        start_rect = self._square_to_scene_rect(from_sq)
        end_rect = self._square_to_scene_rect(to_sq)
        start = start_rect.center()
        end = end_rect.center()

        line = QLineF(start, end)
        color = QColor(color_hex)

        shaft = QGraphicsLineItem(line)
        pen = QPen(color)
        pen.setWidth(max(4, s // 10))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        shaft.setPen(pen)
        shaft.setZValue(3)
        self._scene.addItem(shaft)
        self._overlay_items.append(shaft)

        angle = line.angle()
        arrow_size = s * 0.28
        p1 = end
        p2 = QPointF(
            end.x() - arrow_size * 0.9 * _cos_deg(angle - 22),
            end.y() + arrow_size * 0.9 * _sin_deg(angle - 22),
        )
        p3 = QPointF(
            end.x() - arrow_size * 0.9 * _cos_deg(angle + 22),
            end.y() + arrow_size * 0.9 * _sin_deg(angle + 22),
        )
        head = QGraphicsPolygonItem(QPolygonF([p1, p2, p3]))
        head.setBrush(QBrush(color))
        head.setPen(QPen(Qt.PenStyle.NoPen))
        head.setZValue(3)
        self._scene.addItem(head)
        self._overlay_items.append(head)

    # -- public setters ------------------------------------------------------
    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self._build_squares()
        self._redraw_pieces()
        self._redraw_overlays()

    def set_square_size(self, size: int) -> None:
        self.square_size = size
        self._build_squares()
        self._redraw_pieces()
        self._redraw_overlays()
        self.setFixedSize(self.board_pixel_size() + 2, self.board_pixel_size() + 2)

    def set_theme(self, palette_theme: BoardPalette) -> None:
        self.palette_theme = palette_theme
        self._paint_squares()
        self._build_coordinates()
        self._redraw_overlays()

    def set_show_coordinates(self, show: bool) -> None:
        self.show_coordinates = show
        self._build_coordinates()

    def set_show_legal_dots(self, show: bool) -> None:
        self.show_legal_dots = show
        self._redraw_overlays()

    def set_show_best_arrow(self, show: bool) -> None:
        self.show_best_arrow = show
        self._redraw_overlays()

    def set_best_move(self, move: Optional[chess.Move]) -> None:
        self._best_move = move
        self._redraw_overlays()

    @property
    def best_move(self) -> Optional[chess.Move]:
        """Return the current best-move arrow target, or ``None``."""
        return self._best_move

    def set_threat_move(self, move: Optional[chess.Move]) -> None:
        self._threat_move = move
        self._redraw_overlays()

    def set_coach_from_square(self, square: Optional[int]) -> None:
        """In Coach Mode, highlight the square containing the piece the
        engine recommends moving. Set to ``None`` to clear."""
        self._coach_from_square = square
        self._redraw_overlays()

    def clear_selection(self) -> None:
        self._selected_square = None
        self._redraw_overlays()

    # -- mouse interaction ---------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = self.mapToScene(event.position().toPoint())
        square = self._scene_pos_to_square(pos)
        if square is None:
            return super().mousePressEvent(event)

        piece_item = self._piece_items.get(square)
        if piece_item is not None:
            self._drag_item = piece_item
            self._drag_origin_square = square
            self._drag_start_pos = pos
            piece_item.setZValue(20)
        self.squareClicked.emit(square)
        self._handle_square_click(square)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_item is not None:
            pos = self.mapToScene(event.position().toPoint())
            s = self.square_size
            bounds = self._drag_item.boundingRect()
            scale = self._drag_item.scale()
            self._drag_item.setPos(
                pos.x() - bounds.width() * scale / 2, pos.y() - bounds.height() * scale / 2
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_item is not None and self._drag_origin_square is not None:
            pos = self.mapToScene(event.position().toPoint())
            target_square = self._scene_pos_to_square(pos)
            origin_square = self._drag_origin_square
            moved_far = (pos - self._drag_start_pos).manhattanLength() > self.square_size * 0.35

            self._drag_item.setZValue(10)
            self._drag_item = None
            self._drag_origin_square = None

            if moved_far and target_square is not None and target_square != origin_square:
                self._try_move(origin_square, target_square)
            else:
                # Treat as a click rather than a drag; snap back and let
                # click-to-move selection logic (already applied on press)
                # stand.
                self._redraw_pieces()
                self._redraw_overlays()
        super().mouseReleaseEvent(event)

    def _handle_square_click(self, square: int) -> None:
        if self._selected_square is None:
            piece = self.board.piece_at(square)
            if piece is not None:
                self._selected_square = square
                self._redraw_overlays()
            return

        if square == self._selected_square:
            self._selected_square = None
            self._redraw_overlays()
            return

        origin = self._selected_square
        piece_at_target = self.board.piece_at(square)
        origin_piece = self.board.piece_at(origin)
        # Defensive: guard against None dereference. If the piece at origin
        # was somehow removed between selection and this click, reset selection.
        if origin_piece is None:
            self._selected_square = None
            self._redraw_overlays()
            return
        if piece_at_target is not None and piece_at_target.color == origin_piece.color:
            # Clicking another friendly piece re-selects instead of moving.
            self._selected_square = square
            self._redraw_overlays()
            return

        self._selected_square = None
        self._try_move(origin, square)

    def _try_move(self, origin: int, target: int) -> None:
        piece = self.board.piece_at(origin)
        promotion = None
        if piece is not None and piece.piece_type == chess.PAWN:
            target_rank = chess.square_rank(target)
            if (piece.color == chess.WHITE and target_rank == 7) or (
                piece.color == chess.BLACK and target_rank == 0
            ):
                promotion = chess.QUEEN  # default; GUI layer may re-prompt
                candidate = chess.Move(origin, target, promotion=promotion)
                if candidate in self.board.legal_moves:
                    self.promotionNeeded.emit(origin, target)
                    return

        move = chess.Move(origin, target, promotion=promotion)
        if move in self.board.legal_moves:
            self.moveAttempted.emit(move)
        else:
            self._redraw_pieces()
            self._redraw_overlays()

    def emit_promotion_move(self, origin: int, target: int, piece_type: int) -> None:
        move = chess.Move(origin, target, promotion=piece_type)
        if move in self.board.legal_moves:
            self.moveAttempted.emit(move)
        else:
            self._redraw_pieces()
            self._redraw_overlays()


def _cos_deg(deg: float) -> float:
    import math

    return math.cos(math.radians(deg))


def _sin_deg(deg: float) -> float:
    import math

    return math.sin(math.radians(deg))
