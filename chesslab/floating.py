"""Floating overlay chessboard window.

Launched via ``./run.sh --float``, or directly with
``python -m chesslab --float``.

Features
--------
* Frameless, always-on-top window at 80 % opacity
* Ctrl + left-click on the board → drag window
* Shift + right-click on the board → resize window
* Title-bar drag (no modifier needed)
* Right-click context menu on board
* Ctrl+N / toolbar "N" → new game (with side prompt)
* Ctrl+F / toolbar "F" → flip board
* Ctrl+H / toolbar "?" → hint
* Coach mode with blue best-move arrow
* Side-selection dialog on first launch and new game
"""

from __future__ import annotations

import logging
from typing import Optional

import chess
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chesslab.analysis import GameController
from chesslab.board import BoardView
from chesslab.config import AppSettings, EngineOptions, find_stockfish
from chesslab.dialogs import (
    PromotionDialog,
    StockfishLocateDialog,
    confirm,
    info,
    warn,
)
from chesslab.engine import EngineInfoUpdate, EngineManager
from chesslab.panels import EvalBar
from chesslab.theme import BOARD_THEMES

logger = logging.getLogger("chesslab.floating")


class _TitleBar(QWidget):
    """A draggable title bar for the frameless window."""

    window_drag_pressed = Signal(object)  # QPoint (global position at press)
    window_drag_moved = Signal(object)  # QPoint (global position during move)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("background-color: #1e1e2e;")
        self._dragging = False
        self._press_global = QPoint()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)

        self.label = QLabel(text)
        self.label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        layout.addWidget(self.label)
        layout.addStretch(1)

        self.btn_new = QPushButton("N")
        self.btn_new.setFixedSize(24, 24)
        self.btn_new.setToolTip("New Game (Ctrl+N)")
        self.btn_new.setStyleSheet(
            "color: #cdd6f4; background: #313244; border: none;"
            " border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.btn_new)

        self.btn_flip = QPushButton("F")
        self.btn_flip.setFixedSize(24, 24)
        self.btn_flip.setToolTip("Flip Board (F)")
        self.btn_flip.setStyleSheet(
            "color: #cdd6f4; background: #313244; border: none;"
            " border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.btn_flip)

        self.btn_hint = QPushButton("?")
        self.btn_hint.setFixedSize(24, 24)
        self.btn_hint.setToolTip("Hint (H)")
        self.btn_hint.setStyleSheet(
            "color: #cdd6f4; background: #313244; border: none;"
            " border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.btn_hint)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip("Close (Esc)")
        self.btn_close.setStyleSheet(
            "color: #f38ba8; background: #313244; border: none;"
            " border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.btn_close)

    def set_status(self, text: str) -> None:
        self.label.setText(text)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.LeftButton:
            self._dragging = True
            pos = event.globalPosition().toPoint()
            self.window_drag_pressed.emit(pos)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and self._dragging:
            self.window_drag_moved.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and self._dragging:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class FloatingBoardWindow(QWidget):
    """Frameless, semi-transparent overlay chessboard.

    This window sits on top of other applications, showing a live
    chessboard with Stockfish analysis. Drag with Ctrl+left-click on
    the board, resize with Shift+right-click, or use the title bar.
    """

    def __init__(self) -> None:
        super().__init__(None)  # No parent — standalone top-level window

        self.app_settings = AppSettings()
        self.engine_options = self.app_settings.load_engine_options()
        self.ui_prefs = self.app_settings.load_ui_preferences()

        self.game = GameController()
        self.engine = EngineManager()

        self._continuous_analysis = True
        self._coach_mode = True
        self._human_side: bool = chess.WHITE
        self._eval_text: str = ""

        # Drag & resize state
        self._board_dragging = False
        self._board_drag_start = QPoint()
        self._board_drag_win_start = QPoint()
        self._board_resizing = False
        self._title_drag_offset = QPoint()
        self._title_drag_base = QPoint()

        self._build_ui()
        self._connect_signals()

        self.setWindowTitle("ChessLab — Float")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowOpacity(0.80)

        self.resize(620, 660)

        QTimer.singleShot(150, self._ensure_engine_started)
        QTimer.singleShot(500, self._prompt_for_side)

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        self.title_bar = _TitleBar("♚ ChessLab")
        self.title_bar.window_drag_pressed.connect(self._on_title_drag_press)
        self.title_bar.window_drag_moved.connect(self._on_title_drag_move)
        self.title_bar.btn_new.clicked.connect(self._on_new_game)
        self.title_bar.btn_flip.clicked.connect(self._on_flip)
        self.title_bar.btn_hint.clicked.connect(self._on_hint)
        self.title_bar.btn_close.clicked.connect(self.close)
        main_layout.addWidget(self.title_bar)

        # Board area
        board_area = QWidget()
        board_area.setStyleSheet("background-color: #1e1e2e;")
        board_layout = QHBoxLayout(board_area)
        board_layout.setContentsMargins(8, 8, 8, 8)
        board_layout.setSpacing(8)

        self.eval_bar = EvalBar()
        board_layout.addWidget(self.eval_bar)

        self.board_view = BoardView()
        self.board_view.set_square_size(64)
        self.board_view.set_theme(BOARD_THEMES[self.ui_prefs.board_theme])
        self.board_view.set_flipped(self.ui_prefs.board_flipped)
        self.board_view.set_show_coordinates(True)
        self.board_view.set_show_legal_dots(True)
        self.board_view.set_show_best_arrow(True)
        board_layout.addWidget(self.board_view, 1)

        main_layout.addWidget(board_area, 1)

        # Install event filter on board for drag/resize interception
        self.board_view.installEventFilter(self)

        # Bottom status bar
        status_bar = QWidget()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet("background-color: #11111b;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(8, 2, 8, 2)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        self.depth_label = QLabel("")
        self.depth_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        status_layout.addWidget(self.depth_label)
        main_layout.addWidget(status_bar)

    # -- signal wiring -----------------------------------------------------

    def _connect_signals(self) -> None:
        self.game.positionChanged.connect(self._on_position_changed)
        self.game.historyChanged.connect(self._on_history_changed)
        self.game.gameReset.connect(self._on_game_reset)

        self.engine.engineReady.connect(self._on_engine_ready)
        self.engine.engineFailed.connect(self._on_engine_failed)
        self.engine.infoUpdated.connect(self._on_info_updated)
        self.engine.searchStarted.connect(
            lambda: self.title_bar.set_status("♚ ChessLab — Thinking...")
        )
        self.engine.searchStopped.connect(
            lambda: self.title_bar.set_status("♚ ChessLab")
        )
        self.engine.oneShotSearchStarted.connect(
            lambda tag: self.title_bar.set_status("♚ ChessLab — Thinking...")
        )
        self.engine.oneShotMoveReady.connect(self._on_one_shot_move)

        self.board_view.moveAttempted.connect(self._on_move_attempted)
        self.board_view.promotionNeeded.connect(self._on_promotion_needed)

    # -- event filter for board drag/resize ---------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if obj is not self.board_view:
            return super().eventFilter(obj, event)

        etype = event.type()

        if etype == event.Type.MouseButtonPress:
            modifiers = QApplication.keyboardModifiers()
            if modifiers == Qt.ControlModifier and event.button() == Qt.LeftButton:
                self._board_dragging = True
                self._board_drag_start = event.globalPosition().toPoint()
                self._board_drag_win_start = self.pos()
                return True  # Eat event — don't pass to BoardView
            if modifiers == Qt.ShiftModifier and event.button() == Qt.RightButton:
                self._board_resizing = True
                self._board_drag_start = event.globalPosition().toPoint()
                return True  # Eat event
            if event.button() == Qt.RightButton:
                # Show context menu
                self._show_context_menu(event.globalPosition().toPoint())
                return True

        elif etype == event.Type.MouseMove:
            if self._board_dragging:
                delta = event.globalPosition().toPoint() - self._board_drag_start
                self.move(self._board_drag_win_start + delta)
                return True
            if self._board_resizing:
                delta = event.globalPosition().toPoint() - self._board_drag_start
                new_w = max(320, self.width() + delta.x())
                new_h = max(360, self.height() + delta.y())
                self.resize(new_w, new_h)
                self._board_drag_start = event.globalPosition().toPoint()
                return True

        elif etype == event.Type.MouseButtonRelease:
            if self._board_dragging or self._board_resizing:
                self._board_dragging = False
                self._board_resizing = False
                return True

        return super().eventFilter(obj, event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        act_new = menu.addAction("New Game\tCtrl+N")
        act_flip = menu.addAction("Flip Board\tF")
        menu.addSeparator()
        act_hint = menu.addAction("Hint\tH")
        menu.addSeparator()
        act_close = menu.addAction("Close\tEsc")

        chosen = menu.exec(pos)
        if chosen == act_new:
            self._on_new_game()
        elif chosen == act_flip:
            self._on_flip()
        elif chosen == act_hint:
            self._on_hint()
        elif chosen == act_close:
            self.close()

    # -- title bar drag ----------------------------------------------------

    def _on_title_drag_press(self, global_pos: QPoint) -> None:
        """Store the offset between cursor and window top-left on press."""
        self._title_drag_offset = global_pos - self.pos()

    def _on_title_drag_move(self, global_pos: QPoint) -> None:
        """Move window to keep the cursor at the same relative position."""
        self.move(global_pos - self._title_drag_offset)

    # -- keyboard shortcuts ------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.matches(QKeySequence.StandardKey.New):
            self._on_new_game()
        elif event.key() == Qt.Key.Key_F:
            self._on_flip()
        elif event.key() == Qt.Key.Key_H:
            self._on_hint()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    # -- engine bootstrap --------------------------------------------------

    def _ensure_engine_started(self) -> None:
        path = self.app_settings.stockfish_path or find_stockfish()
        if not path:
            self._prompt_for_stockfish()
            return
        self.app_settings.stockfish_path = path
        self.status_label.setText("Starting engine...")
        self.engine.start_engine(path, self.engine_options)

    def _prompt_for_stockfish(self) -> None:
        dialog = StockfishLocateDialog(self)
        if dialog.exec() and dialog.selected_path:
            self.app_settings.stockfish_path = dialog.selected_path
            self.status_label.setText("Starting engine...")
            self.engine.start_engine(dialog.selected_path, self.engine_options)
        else:
            self.status_label.setText("No engine configured")

    def _on_engine_ready(self) -> None:
        self.status_label.setText("Engine ready")
        if self._continuous_analysis:
            self._restart_analysis()

    def _on_engine_failed(self, message: str) -> None:
        self.status_label.setText("Engine error")
        warn(self, "Engine Error", f"Stockfish reported an error:\n{message}")

    # -- game / position events -------------------------------------------

    def _on_position_changed(self) -> None:
        self.board_view.set_board(
            self.game.board,
            self.game.board.peek() if self.game.board.move_stack else None,
        )
        self.board_view.set_best_move(None)
        self._update_status()
        self._check_game_over()
        if self._continuous_analysis and self.engine.is_running:
            self._restart_analysis()

    def _on_history_changed(self) -> None:
        self._update_status()

    def _on_game_reset(self) -> None:
        pass

    def _restart_analysis(self) -> None:
        self.engine.start_analysis(self.game.board, self.engine_options)

    def _on_info_updated(self, update: EngineInfoUpdate) -> None:
        if update.board_fen_at_search != self.game.board.fen():
            return
        if update.multipv == 1:
            # Store eval text for display
            if update.score is not None:
                score = update.score
                if score.is_mate():
                    self._eval_text = f"#{score.mate()}"
                else:
                    cp = score.white().score(mate_score=100000)
                    self._eval_text = f"{cp / 100:+.2f}"
            else:
                self._eval_text = ""
            self.depth_label.setText(f"Depth {update.depth}/{update.seldepth}")
            self.eval_bar.set_score(update.score)
            if update.pv:
                if self._coach_mode and self.game.board.turn == self._human_side:
                    self.board_view.set_best_move(update.pv[0])
                    self.board_view.set_coach_from_square(update.pv[0].from_square)
                else:
                    self.board_view.set_best_move(None)
                    self.board_view.set_coach_from_square(None)
            self._update_status()

    def _on_one_shot_move(self, move: Optional[chess.Move], tag: str) -> None:
        if move is None:
            return
        if tag == "best":
            self.game.push_move(move)
        elif tag == "hint":
            self.board_view.set_best_move(move)
            info(self, "Hint", f"Engine suggests: {self.game.board.san(move)}")

    def _update_status(self) -> None:
        parts = []
        if self._eval_text:
            parts.append(self._eval_text)
        move_count = len(self.game.board.move_stack)
        if move_count:
            ply = self.game.current_ply
            full_move = (ply + 1) // 2
            parts.append(f"Move {full_move}")
        side = "White" if self.game.board.turn == chess.WHITE else "Black"
        parts.append(f"{side} to move")
        human = "White" if self._human_side == chess.WHITE else "Black"
        if self._coach_mode:
            parts.append(f"Playing {human}")
        self.status_label.setText(" · ".join(parts))

    def _check_game_over(self) -> None:
        board = self.game.board
        if not board.is_game_over():
            return
        if self.game.current_ply != len(self.game.moves_played):
            return
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            human = "White" if self._human_side == chess.WHITE else "Black"
            if winner == human:
                info(self, "🏆 Checkmate!", f"{winner} wins! Congratulations!")
            else:
                info(self, "Checkmate", f"{winner} wins.")
        elif board.is_stalemate():
            info(self, "Stalemate", "Draw by stalemate.")
        elif board.is_insufficient_material():
            info(self, "Draw", "Draw — insufficient material.")
        elif board.is_fifty_moves():
            info(self, "Draw", "Draw — 50-move rule.")
        elif board.is_repetition():
            info(self, "Draw", "Draw — threefold repetition.")

    # -- user actions -----------------------------------------------------

    def _on_new_game(self) -> None:
        if self.game.moves_played and not confirm(
            self, "New Game", "Discard current game and start a new one?"
        ):
            return
        self.game.new_game()
        QTimer.singleShot(100, self._prompt_for_side)

    def _on_flip(self) -> None:
        self.ui_prefs.board_flipped = not self.ui_prefs.board_flipped
        self.board_view.set_flipped(self.ui_prefs.board_flipped)

    def _on_hint(self) -> None:
        if not self.engine.is_running:
            warn(self, "Engine", "Engine is not running yet.")
            return
        self.engine.request_best_move(
            self.game.board, self.engine_options.move_time_ms, tag="hint"
        )

    def _on_move_attempted(self, move: chess.Move) -> None:
        self.game.push_move(move)

    def _on_promotion_needed(self, origin: int, target: int) -> None:
        color = self.game.board.turn
        dialog = PromotionDialog(color, self)
        if dialog.exec():
            self.board_view.emit_promotion_move(origin, target, dialog.chosen_piece_type)
        else:
            self.board_view.set_board(self.game.board)

    def _on_set_human_side(self, side: bool) -> None:
        self._human_side = side
        self.board_view.set_best_move(None)
        self.board_view.set_coach_from_square(None)
        self._update_status()

    def _prompt_for_side(self) -> None:
        """Show a dialog asking which side the user wants to play."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose Your Side")
        layout = QVBoxLayout(dialog)

        label = QLabel("Which side would you like to play?")
        label.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 8px;")
        layout.addWidget(label)

        hint = QLabel(
            "The blue arrow shows your best move on your turn.\n"
            "White always starts first."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        btn_white = QPushButton("♔  Play as White")
        btn_white.setMinimumHeight(60)
        btn_white.setStyleSheet(
            "font-size: 16px; background-color: #3a4250; color: #e7e9ee;"
            "border: 2px solid #4fa3d9; border-radius: 8px;"
        )
        btn_black = QPushButton("♚  Play as Black")
        btn_black.setMinimumHeight(60)
        btn_black.setStyleSheet(
            "font-size: 16px; background-color: #1a1a1a; color: #e7e9ee;"
            "border: 2px solid #4fa3d9; border-radius: 8px;"
        )
        button_row.addWidget(btn_white)
        button_row.addWidget(btn_black)
        layout.addLayout(button_row)

        result = {"side": chess.WHITE}

        def choose_white() -> None:
            result["side"] = chess.WHITE
            dialog.accept()

        def choose_black() -> None:
            result["side"] = chess.BLACK
            dialog.accept()

        btn_white.clicked.connect(choose_white)
        btn_black.clicked.connect(choose_black)

        dialog.exec()

        self._on_set_human_side(result["side"])

        self._coach_mode = True
        self.board_view.set_show_best_arrow(True)
        self._update_status()

        human = "White" if result["side"] == chess.WHITE else "Black"
        info(
            self,
            "Coach Mode",
            "The blue arrow shows your best move.\n\n"
            f"You are playing as {human}.\n\n"
            "💡 Ctrl+click the board → drag window\n"
            "💡 Shift+right-click → resize window\n"
            "💡 Ctrl+N → New Game\n"
            "💡 Right-click → Context menu",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.engine.quit()
        super().closeEvent(event)
