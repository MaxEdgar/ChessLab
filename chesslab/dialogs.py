"""Small focused dialogs used by the main window."""

from __future__ import annotations

from typing import Optional

import chess
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chesslab.config import AppSettings, EngineOptions, UiPreferences, find_stockfish
from chesslab.theme import BOARD_THEMES


class PromotionDialog(QDialog):
    """Prompts which piece a pawn should promote to."""

    def __init__(self, color: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose promotion")
        self.setModal(True)
        self.chosen_piece_type = chess.QUEEN

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Promote pawn to:"))
        row = QHBoxLayout()
        options = [
            (chess.QUEEN, "Queen"),
            (chess.ROOK, "Rook"),
            (chess.BISHOP, "Bishop"),
            (chess.KNIGHT, "Knight"),
        ]
        for piece_type, label in options:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked, pt=piece_type: self._choose(pt))
            row.addWidget(btn)
        layout.addLayout(row)

    def _choose(self, piece_type: int) -> None:
        self.chosen_piece_type = piece_type
        self.accept()


class StockfishLocateDialog(QDialog):
    """Shown when Stockfish can't be auto-detected; lets the user browse."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Locate Stockfish")
        self.setModal(True)
        self.selected_path: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "ChessLab couldn't find a Stockfish engine automatically.\n"
                "Please locate the Stockfish executable, or install it first\n"
                "(e.g. 'sudo apt install stockfish' on Ubuntu, or download it\n"
                "from stockfishchess.org for Windows)."
            )
        )
        browse_row = QHBoxLayout()
        self.path_label = QLabel("No file selected")
        self.path_label.setWordWrap(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        browse_row.addWidget(self.path_label, 1)
        browse_row.addWidget(browse_btn)
        layout.addLayout(browse_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        start_dir = ""
        guess = find_stockfish()
        if guess:
            start_dir = guess
        path, _ = QFileDialog.getOpenFileName(self, "Select Stockfish executable", start_dir)
        if path:
            self.selected_path = path
            self.path_label.setText(path)


class EngineSettingsDialog(QDialog):
    """Lets the user tune UCI engine options and a few UI preferences."""

    def __init__(
        self,
        settings: AppSettings,
        options: EngineOptions,
        prefs: UiPreferences,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Engine & Display Settings")
        self._settings = settings
        self.options = options
        self.prefs = prefs

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 128)
        self.threads_spin.setValue(options.threads)
        form.addRow("Threads", self.threads_spin)

        self.hash_spin = QSpinBox()
        self.hash_spin.setRange(1, 65536)
        self.hash_spin.setValue(options.hash_mb)
        self.hash_spin.setSuffix(" MB")
        form.addRow("Hash size", self.hash_spin)

        self.skill_spin = QSpinBox()
        self.skill_spin.setRange(0, 20)
        self.skill_spin.setValue(options.skill_level)
        form.addRow("Skill level", self.skill_spin)

        self.multipv_spin = QSpinBox()
        self.multipv_spin.setRange(1, 8)
        self.multipv_spin.setValue(options.multipv)
        form.addRow("MultiPV (top moves shown)", self.multipv_spin)

        self.movetime_spin = QSpinBox()
        self.movetime_spin.setRange(50, 60000)
        self.movetime_spin.setSingleStep(50)
        self.movetime_spin.setValue(options.move_time_ms)
        self.movetime_spin.setSuffix(" ms")
        form.addRow("Move time (when not infinite)", self.movetime_spin)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(0, 60)
        self.depth_spin.setValue(options.depth_limit)
        self.depth_spin.setSpecialValueText("Unlimited")
        form.addRow("Depth limit (0 = unlimited)", self.depth_spin)

        self.infinite_check = QCheckBox("Analyze continuously (infinite)")
        self.infinite_check.setChecked(options.infinite_analysis)
        form.addRow(self.infinite_check)

        layout.addLayout(form)

        display_form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(BOARD_THEMES.keys()))
        self.theme_combo.setCurrentText(prefs.board_theme)
        display_form.addRow("Board theme", self.theme_combo)

        self.square_size_spin = QSpinBox()
        self.square_size_spin.setRange(36, 140)
        self.square_size_spin.setValue(prefs.square_size)
        display_form.addRow("Square size (px)", self.square_size_spin)

        self.coords_check = QCheckBox("Show coordinates")
        self.coords_check.setChecked(prefs.show_coordinates)
        display_form.addRow(self.coords_check)

        self.dots_check = QCheckBox("Show legal move dots")
        self.dots_check.setChecked(prefs.show_legal_move_dots)
        display_form.addRow(self.dots_check)

        self.arrow_check = QCheckBox("Show best-move arrow")
        self.arrow_check.setChecked(prefs.show_best_move_arrow)
        display_form.addRow(self.arrow_check)

        layout.addLayout(display_form)

        tb_row = QHBoxLayout()
        self.tablebase_edit = QLineEdit(settings.syzygy_path or "")
        self.tablebase_edit.setPlaceholderText("No tablebase directory set (optional)")
        tb_browse_btn = QPushButton("Browse...")
        tb_browse_btn.clicked.connect(self._browse_tablebase)
        tb_row.addWidget(QLabel("Syzygy tablebase folder"))
        tb_row.addWidget(self.tablebase_edit, 1)
        tb_row.addWidget(tb_browse_btn)
        layout.addLayout(tb_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_tablebase(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Syzygy tablebase folder")
        if directory:
            self.tablebase_edit.setText(directory)

    def result_tablebase_path(self) -> Optional[str]:
        text = self.tablebase_edit.text().strip()
        return text or None

    def result_options(self) -> EngineOptions:
        return EngineOptions(
            threads=self.threads_spin.value(),
            hash_mb=self.hash_spin.value(),
            skill_level=self.skill_spin.value(),
            multipv=self.multipv_spin.value(),
            move_time_ms=self.movetime_spin.value(),
            depth_limit=self.depth_spin.value(),
            infinite_analysis=self.infinite_check.isChecked(),
        )

    def result_prefs(self) -> UiPreferences:
        self.prefs.board_theme = self.theme_combo.currentText()
        self.prefs.square_size = self.square_size_spin.value()
        self.prefs.show_coordinates = self.coords_check.isChecked()
        self.prefs.show_legal_move_dots = self.dots_check.isChecked()
        self.prefs.show_best_move_arrow = self.arrow_check.isChecked()
        return self.prefs


def confirm(parent: QWidget, title: str, text: str) -> bool:
    reply = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes


def warn(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)
