"""Side-panel widgets: evaluation bar, engine analysis panel, move list."""

from __future__ import annotations

from typing import Optional

import chess
import chess.engine
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chesslab.analysis import CLASS_COLORS, MoveRecord
from chesslab.theme import BAD, BG_PANEL, BG_PANEL_ALT, GOOD, TEXT_PRIMARY
from chesslab.utils import format_score, score_to_eval_bar_fraction


class EvalBar(QWidget):
    """A slim vertical bar showing the position evaluation, White-relative."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(28)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._fraction = 0.5
        self._label = "0.00"

    def set_score(self, score: Optional[chess.engine.PovScore]) -> None:
        self._fraction = score_to_eval_bar_fraction(score)
        self._label = format_score(score)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Black fills the whole bar, white fills from the bottom up to
        # `fraction`, so a fraction of 1.0 means all-white (White winning).
        painter.fillRect(rect, QColor("#1a1a1a"))
        white_height = int(rect.height() * self._fraction)
        white_rect = rect.adjusted(0, rect.height() - white_height, 0, 0)
        painter.fillRect(white_rect, QColor("#e9e9e9"))

        painter.setPen(QColor(TEXT_PRIMARY))
        text_y = 4 if self._fraction < 0.5 else rect.height() - 16
        text_color = QColor("#e9e9e9") if self._fraction < 0.5 else QColor("#1a1a1a")
        painter.setPen(text_color)
        painter.drawText(0, text_y, rect.width(), 14, Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()


class EnginePanel(QWidget):
    """Shows live search stats and the top MultiPV lines."""

    lineClicked = Signal(list)  # emits the PV (list[chess.Move]) for a clicked line

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        stats_row = QHBoxLayout()
        self.depth_label = QLabel("Depth: --")
        self.nodes_label = QLabel("Nodes: --")
        self.nps_label = QLabel("NPS: --")
        for lbl in (self.depth_label, self.nodes_label, self.nps_label):
            lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px;")
            stats_row.addWidget(lbl)
        layout.addLayout(stats_row)

        self.lines_tree = QTreeWidget()
        self.lines_tree.setHeaderLabels(["#", "Eval", "Line"])
        self.lines_tree.setRootIsDecorated(False)
        self.lines_tree.setAlternatingRowColors(True)
        self.lines_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.lines_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.lines_tree, 1)

        self._pv_by_row: dict[int, list[chess.Move]] = {}

    def update_stats(self, depth: int, seldepth: int, nodes: int, nps: int) -> None:
        self.depth_label.setText(f"Depth: {depth}/{seldepth}")
        self.nodes_label.setText(f"Nodes: {nodes:,}")
        self.nps_label.setText(f"NPS: {nps:,}")

    def set_line(
        self,
        multipv_index: int,
        score: Optional[chess.engine.PovScore],
        pv: list[chess.Move],
        board_for_san: chess.Board,
    ) -> None:
        row = multipv_index - 1
        while self.lines_tree.topLevelItemCount() <= row:
            self.lines_tree.addTopLevelItem(QTreeWidgetItem(["", "", ""]))

        item = self.lines_tree.topLevelItem(row)
        item.setText(0, str(multipv_index))
        item.setText(1, format_score(score))
        item.setText(2, self._pv_to_san(pv, board_for_san))
        self._pv_by_row[row] = pv

    def clear_lines(self) -> None:
        self.lines_tree.clear()
        self._pv_by_row.clear()

    @staticmethod
    def _pv_to_san(pv: list[chess.Move], board: chess.Board) -> str:
        san_parts = []
        scratch = board.copy(stack=False)
        for i, move in enumerate(pv[:8]):
            if move not in scratch.legal_moves:
                break
            move_no = scratch.fullmove_number
            prefix = f"{move_no}." if scratch.turn == chess.WHITE else (
                f"{move_no}..." if i == 0 else ""
            )
            san = scratch.san(move)
            scratch.push(move)
            san_parts.append(f"{prefix}{san}" if prefix else san)
        return " ".join(san_parts)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        row = self.lines_tree.indexOfTopLevelItem(item)
        pv = self._pv_by_row.get(row)
        if pv:
            self.lineClicked.emit(pv)


class MoveListWidget(QTableWidget):
    """A two-column (White/Black) move list with move-quality coloring."""

    moveSelected = Signal(int)  # ply index (1-based position after that ply)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["#", "White", "Black"])
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.cellClicked.connect(self._on_cell_clicked)
        self._ply_by_cell: dict[tuple[int, int], int] = {}

    def rebuild(self, records: list[MoveRecord]) -> None:
        self.setRowCount(0)
        self._ply_by_cell.clear()
        row = -1
        for i, record in enumerate(records):
            ply = i + 1
            is_white_move = i % 2 == 0
            if is_white_move:
                row += 1
                self.insertRow(row)
                move_no_item = QTableWidgetItem(str(row + 1))
                move_no_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.setItem(row, 0, move_no_item)

            col = 1 if is_white_move else 2
            text = record.san
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if record.classification:
                color = CLASS_COLORS.get(record.classification, TEXT_PRIMARY)
                item.setForeground(QBrush(QColor(color)))
                item.setToolTip(record.classification)
            self.setItem(row, col, item)
            self._ply_by_cell[(row, col)] = ply

    def highlight_ply(self, ply: int) -> None:
        self.clearSelection()
        for (row, col), p in self._ply_by_cell.items():
            if p == ply:
                self.setCurrentCell(row, col)
                return

    def _on_cell_clicked(self, row: int, column: int) -> None:
        ply = self._ply_by_cell.get((row, column))
        if ply is not None:
            self.moveSelected.emit(ply)
