"""Main application window and top-level wiring.

``MainWindow`` connects four independently testable pieces:

* :class:`~chesslab.analysis.GameController` -- authoritative board/history
* :class:`~chesslab.engine.EngineManager` -- Stockfish process/analysis
* :class:`~chesslab.board.BoardView` -- interactive board rendering
* :class:`~chesslab.panels` widgets -- eval bar, engine lines, move list

It intentionally contains no chess logic of its own; it only routes
signals between the pieces above and manages window chrome (menus,
toolbar, docks, dialogs, shortcuts, persisted window state).
"""

from __future__ import annotations

import logging
from typing import Optional

import chess
import chess.engine
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from chesslab.analysis import GameController
from chesslab.board import BoardView
from chesslab.config import AppSettings, EngineOptions, find_stockfish
from chesslab.dialogs import (
    EngineSettingsDialog,
    PromotionDialog,
    StockfishLocateDialog,
    confirm,
    info,
    warn,
)
from chesslab.engine import EngineInfoUpdate, EngineManager
from chesslab.openings import lookup_opening
from chesslab.panels import EnginePanel, EvalBar, MoveListWidget
from chesslab.tablebase import TablebaseProbe
from chesslab.theme import BOARD_THEMES

logger = logging.getLogger("chesslab.gui")

MATERIAL_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


def _material_balance(board: chess.Board) -> int:
    """White material minus Black material, in pawns."""
    total = 0
    for piece_type, value in MATERIAL_VALUES.items():
        total += value * len(board.pieces(piece_type, chess.WHITE))
        total -= value * len(board.pieces(piece_type, chess.BLACK))
    return total


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ChessLab — Stockfish Analysis Board")
        self.resize(1400, 900)

        self.app_settings = AppSettings()
        self.engine_options = self.app_settings.load_engine_options()
        self.ui_prefs = self.app_settings.load_ui_preferences()

        self.game = GameController()
        self.engine = EngineManager()
        self.tablebase = TablebaseProbe()
        if self.app_settings.syzygy_path:
            self.tablebase.open(self.app_settings.syzygy_path)

        self._continuous_analysis = True
        self._pending_promotion: Optional[tuple[int, int]] = None
        self._last_multipv_infos: dict[int, EngineInfoUpdate] = {}
        self._eval_by_fen: dict[str, chess.engine.PovScore] = {}
        self._pending_classification_ply: Optional[int] = None
        self._pending_classification_before: Optional[chess.engine.PovScore] = None
        self._pending_classification_mover_white: bool = True
        self._pending_classification_material_before: int = 0
        self._threat_mode = False
        self._coach_mode = True
        self._coach_mode_info_shown = False
        # Track which side the human is playing. The coach arrow only shows
        # when it's this side's turn — never for the opponent.
        self._human_side: bool = chess.WHITE

        self._build_ui()
        self._connect_signals()
        self._restore_window_state()
        QTimer.singleShot(150, self._ensure_engine_started)
        # Ask which side to play first
        QTimer.singleShot(500, self._prompt_for_side)

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.eval_bar = EvalBar()
        layout.addWidget(self.eval_bar)

        self.board_view = BoardView()
        self.board_view.set_square_size(self.ui_prefs.square_size)
        self.board_view.set_theme(BOARD_THEMES[self.ui_prefs.board_theme])
        self.board_view.set_flipped(self.ui_prefs.board_flipped)
        self.board_view.set_show_coordinates(self.ui_prefs.show_coordinates)
        self.board_view.set_show_legal_dots(self.ui_prefs.show_legal_move_dots)
        self.board_view.set_show_best_arrow(self.ui_prefs.show_best_move_arrow)
        board_wrap = QVBoxLayout()
        board_wrap.addStretch(1)
        board_row = QHBoxLayout()
        board_row.addStretch(1)
        board_row.addWidget(self.board_view)
        board_row.addStretch(1)
        board_wrap.addLayout(board_row)
        board_wrap.addStretch(1)
        layout.addLayout(board_wrap, 1)

        self.setCentralWidget(central)

        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self._build_statusbar()

    def _build_docks(self) -> None:
        self.engine_panel = EnginePanel()
        engine_dock = QDockWidget("Engine Analysis", self)
        engine_dock.setObjectName("engine_dock")
        engine_dock.setWidget(self.engine_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, engine_dock)

        self.move_list = MoveListWidget()
        move_dock = QDockWidget("Moves", self)
        move_dock.setObjectName("move_dock")
        move_dock.setWidget(self.move_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, move_dock)

        self.tabifyDockWidget(engine_dock, move_dock)
        engine_dock.raise_()

        self.engine_dock = engine_dock
        self.move_dock = move_dock

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_new = QAction("New Game", self)
        self.act_new.setShortcut(QKeySequence.StandardKey.New)
        toolbar.addAction(self.act_new)

        self.act_open_pgn = QAction("Open PGN", self)
        self.act_open_pgn.setShortcut(QKeySequence.StandardKey.Open)
        toolbar.addAction(self.act_open_pgn)

        self.act_save_pgn = QAction("Save PGN", self)
        self.act_save_pgn.setShortcut(QKeySequence.StandardKey.Save)
        toolbar.addAction(self.act_save_pgn)
        toolbar.addSeparator()

        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        toolbar.addAction(self.act_undo)

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        toolbar.addAction(self.act_redo)

        self.act_start = QAction("|<", self)
        toolbar.addAction(self.act_start)
        self.act_end = QAction(">|", self)
        toolbar.addAction(self.act_end)
        toolbar.addSeparator()

        self.act_flip = QAction("Flip Board", self)
        self.act_flip.setShortcut(QKeySequence("F"))
        toolbar.addAction(self.act_flip)
        toolbar.addSeparator()

        self.act_analyze = QAction("Analyze", self)
        self.act_analyze.setCheckable(True)
        self.act_analyze.setChecked(True)
        self.act_analyze.setShortcut(QKeySequence("Space"))
        toolbar.addAction(self.act_analyze)

        self.act_best_move = QAction("Play Best Move", self)
        toolbar.addAction(self.act_best_move)

        self.act_hint = QAction("Hint", self)
        toolbar.addAction(self.act_hint)

        self.act_threat = QAction("Show Threat", self)
        self.act_threat.setCheckable(True)
        self.act_threat.setChecked(False)
        self.act_threat.setToolTip("Show what the opponent would play if they had an extra move (red arrow)")
        toolbar.addAction(self.act_threat)

        self.act_coach = QAction("Coach Mode", self)
        self.act_coach.setCheckable(True)
        self.act_coach.setChecked(True)
        self.act_coach.setToolTip("Show the engine's recommended move with a blue arrow and highlight the piece to move")
        toolbar.addAction(self.act_coach)

        self.toolbar = toolbar

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_open_pgn)
        file_menu.addAction(self.act_save_pgn)
        file_menu.addSeparator()

        self.act_load_fen = QAction("Load FEN...", self)
        file_menu.addAction(self.act_load_fen)
        self.act_copy_fen = QAction("Copy FEN", self)
        self.act_copy_fen.setShortcut(QKeySequence("Ctrl+C"))
        file_menu.addAction(self.act_copy_fen)
        self.act_paste_fen = QAction("Paste FEN", self)
        self.act_paste_fen.setShortcut(QKeySequence("Ctrl+V"))
        file_menu.addAction(self.act_paste_fen)
        file_menu.addSeparator()
        self.act_reset_position = QAction("Reset to Starting Position", self)
        file_menu.addAction(self.act_reset_position)
        file_menu.addSeparator()
        self.act_quit = QAction("Quit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)
        file_menu.addAction(self.act_quit)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addAction(self.act_start)
        edit_menu.addAction(self.act_end)

        engine_menu = menu_bar.addMenu("&Engine")
        engine_menu.addAction(self.act_analyze)
        engine_menu.addAction(self.act_best_move)
        engine_menu.addAction(self.act_hint)
        engine_menu.addAction(self.act_threat)
        engine_menu.addAction(self.act_coach)
        engine_menu.addSeparator()
        self.act_engine_settings = QAction("Engine Settings...", self)
        engine_menu.addAction(self.act_engine_settings)
        self.act_locate_engine = QAction("Locate Stockfish...", self)
        engine_menu.addAction(self.act_locate_engine)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.act_flip)
        view_menu.addAction(self.engine_dock.toggleViewAction())
        view_menu.addAction(self.move_dock.toggleViewAction())

        help_menu = menu_bar.addMenu("&Help")
        self.act_about = QAction("About ChessLab", self)
        help_menu.addAction(self.act_about)

    def _build_statusbar(self) -> None:
        self.status_opening_label = QLabel("")
        self.status_tablebase_label = QLabel("")
        self.status_engine_label = QLabel("Engine: starting...")
        self.status_perspective_label = QLabel("")
        self.statusBar().addWidget(self.status_opening_label, 1)
        self.statusBar().addPermanentWidget(self.status_perspective_label)
        self.statusBar().addPermanentWidget(self.status_tablebase_label)
        self.statusBar().addPermanentWidget(self.status_engine_label)

    # -- signal wiring -------------------------------------------------------
    def _connect_signals(self) -> None:
        self.game.positionChanged.connect(self._on_position_changed)
        self.game.historyChanged.connect(self._on_history_changed)
        self.game.gameReset.connect(self._on_game_reset)

        self.engine.engineReady.connect(self._on_engine_ready)
        self.engine.engineFailed.connect(self._on_engine_failed)
        self.engine.infoUpdated.connect(self._on_info_updated)
        self.engine.searchStarted.connect(lambda: self.status_engine_label.setText("Thinking..."))
        self.engine.searchStopped.connect(lambda: self.status_engine_label.setText("Ready"))
        self.engine.oneShotSearchStarted.connect(self._on_one_shot_search_started)
        self.engine.oneShotMoveReady.connect(self._on_one_shot_move)

        self.board_view.moveAttempted.connect(self._on_move_attempted)
        self.board_view.promotionNeeded.connect(self._on_promotion_needed)
        self.engine_panel.lineClicked.connect(self._on_engine_line_clicked)
        self.move_list.moveSelected.connect(self.game.jump_to_ply)

        self.act_new.triggered.connect(self._on_new_game)
        self.act_open_pgn.triggered.connect(self._on_open_pgn)
        self.act_save_pgn.triggered.connect(self._on_save_pgn)
        self.act_load_fen.triggered.connect(self._on_load_fen)
        self.act_copy_fen.triggered.connect(self._on_copy_fen)
        self.act_paste_fen.triggered.connect(self._on_paste_fen)
        self.act_reset_position.triggered.connect(self._on_new_game)

        self.act_undo.triggered.connect(self._on_undo)
        self.act_redo.triggered.connect(self._on_redo)
        self.act_start.triggered.connect(lambda: self._jump(self.game.go_to_start))
        self.act_end.triggered.connect(lambda: self._jump(self.game.go_to_end))

        self.act_flip.triggered.connect(self._on_flip)
        self.act_analyze.toggled.connect(self._on_analyze_toggled)
        self.act_best_move.triggered.connect(self._on_play_best_move)
        self.act_hint.triggered.connect(self._on_hint)
        self.act_threat.toggled.connect(self._on_threat_toggled)
        self.act_coach.toggled.connect(self._on_coach_toggled)

        self.act_engine_settings.triggered.connect(self._on_engine_settings)
        self.act_locate_engine.triggered.connect(self._on_locate_engine)
        self.act_about.triggered.connect(self._on_about)

    # -- engine bootstrap ----------------------------------------------------
    def _ensure_engine_started(self) -> None:
        path = self.app_settings.stockfish_path or find_stockfish()
        if not path:
            self._prompt_for_stockfish()
            return
        self.app_settings.stockfish_path = path
        self.status_engine_label.setText("Starting engine...")
        self.engine.start_engine(path, self.engine_options)

    def _prompt_for_stockfish(self) -> None:
        dialog = StockfishLocateDialog(self)
        if dialog.exec() and dialog.selected_path:
            self.app_settings.stockfish_path = dialog.selected_path
            self.status_engine_label.setText("Starting engine...")
            self.engine.start_engine(dialog.selected_path, self.engine_options)
        else:
            self.status_engine_label.setText("No engine configured")

    def _on_engine_ready(self) -> None:
        self.status_engine_label.setText("Engine ready")
        if self._continuous_analysis:
            self._restart_analysis()
        self._update_perspective_label()

    def _on_engine_failed(self, message: str) -> None:
        self.status_engine_label.setText("Engine error")
        warn(self, "Engine Error", f"Stockfish reported an error:\n{message}")

    # -- game/position events -------------------------------------------
    def _on_position_changed(self) -> None:
        self.board_view.set_board(
            self.game.board, self.game.board.peek() if self.game.board.move_stack else None
        )
        self.board_view.set_best_move(None)
        # Don't clear threat_move here — it stays visible until toggled off
        # or replaced by a new threat result.
        self.engine_panel.clear_lines()
        self._update_opening_status()
        self._update_tablebase_status()
        self._update_perspective_label()
        self._check_game_over()
        if self._threat_mode and self.engine.is_running:
            # Stop analysis before requesting threat — play() can't run
            # concurrently with analysis. Analysis restarts after the threat
            # result arrives (see ``_on_one_shot_move``).
            self.engine.stop_analysis()
            self._request_threat()
        elif self._continuous_analysis and self.engine.is_running:
            self._restart_analysis()

    def _on_history_changed(self) -> None:
        self.move_list.rebuild(self.game.moves_played)
        self.move_list.highlight_ply(self.game.current_ply)
        self.act_undo.setEnabled(self.game.can_undo())
        self.act_redo.setEnabled(self.game.can_redo())

    def _on_game_reset(self) -> None:
        self._eval_by_fen.clear()
        self._pending_classification_ply = None

    def _update_opening_status(self) -> None:
        name = self.game.current_opening_name
        self.status_opening_label.setText(name or "")

    def _update_tablebase_status(self) -> None:
        if not self.tablebase.is_open:
            self.status_tablebase_label.setText("")
            return
        readout = self.tablebase.probe(self.game.board)
        self.status_tablebase_label.setText(readout or "")

    # -- analysis loop --------------------------------------------------
    def _restart_analysis(self) -> None:
        self._last_multipv_infos.clear()
        self.engine.start_analysis(self.game.board, self.engine_options)
        # Track what we'll need for classification once the next move is
        # played: the pre-move evaluation of the position we're about to
        # analyze, keyed by FEN so it survives regardless of timing.
        self._pending_classification_material_before = _material_balance(self.game.board)

    def _on_info_updated(self, update: EngineInfoUpdate) -> None:
        if update.board_fen_at_search != self.game.board.fen():
            return  # stale info from a position we've since moved away from
        self._last_multipv_infos[update.multipv] = update
        self.engine_panel.set_line(update.multipv, update.score, update.pv, self.game.board)
        if update.multipv == 1:
            self.engine_panel.update_stats(update.depth, update.seldepth, update.nodes, update.nps)
            self.eval_bar.set_score(update.score)
            self._eval_by_fen[update.board_fen_at_search] = update.score
            # Show depth in status bar so user sees Stockfish thinking
            if update.depth > 0:
                self.status_engine_label.setText(f"Depth {update.depth}/{update.seldepth}")
            if update.pv:
                # In coach mode, ONLY show the arrow when it's the human's turn.
                if self._coach_mode and self.game.board.turn == self._human_side:
                    self.board_view.set_best_move(update.pv[0])
                    self.board_view.set_coach_from_square(update.pv[0].from_square)
                else:
                    self.board_view.set_best_move(None)
                    self.board_view.set_coach_from_square(None)
            self._maybe_finish_classification(update)

    def _maybe_finish_classification(self, update: EngineInfoUpdate) -> None:
        """If the last-played move's resulting position now has a solid
        evaluation, classify that move by comparing it to the eval the
        position *before* the move had (captured the moment analysis of
        it last reported, before the move was made).
        """
        if self.game.current_ply == 0 or update.depth < 12:
            return
        last_record = self.game.moves_played[self.game.current_ply - 1]
        if last_record.classification is not None:
            return
        if update.board_fen_at_search != last_record.fen_after:
            return
        eval_before = self._eval_by_fen.get(last_record.fen_before)
        eval_after = update.score
        mover_was_white = chess.Board(last_record.fen_before).turn == chess.WHITE
        material_before = _material_balance(chess.Board(last_record.fen_before))
        material_after = _material_balance(chess.Board(last_record.fen_after))
        mover_sign = 1 if mover_was_white else -1
        material_delta_for_mover = (material_after - material_before) * mover_sign
        sacrificed = material_delta_for_mover <= -2
        self.game.record_eval(
            self.game.current_ply - 1,
            eval_before,
            eval_after,
            mover_was_white,
            material_sacrificed=sacrificed,
        )

    def _on_one_shot_search_started(self, tag: str) -> None:
        """Show 'Thinking...' when a one-shot search begins (Hint, Play Best, Threat)."""
        self.status_engine_label.setText("Thinking...")

    def _on_one_shot_move(self, move: Optional[chess.Move], tag: str) -> None:
        # Restore status — if continuous analysis is running the next
        # _on_info_updated will overwrite with depth; if not, go to Ready.
        if not self._continuous_analysis:
            self.status_engine_label.setText("Ready")
        if move is None:
            return
        if tag == "best":
            self.game.push_move(move)
        elif tag == "hint":
            self.board_view.set_best_move(move)
            info(self, "Hint", f"Engine suggests: {self.game.board.san(move)}")
        elif tag == "threat":
            if self._threat_mode:
                self.board_view.set_threat_move(move)
                # Restart continuous analysis now that the threat search is done
                if self._continuous_analysis and self.engine.is_running:
                    self._restart_analysis()

    def _check_game_over(self) -> None:
        """Detect checkmate, stalemate, or other game-ending conditions
        and show a dialog. Only fires at the TIP of the move line (not when
        navigating back through history), so PGN browsing won't flood dialogs.
        """
        board = self.game.board
        if not board.is_game_over():
            return
        # Only alert when at the latest position (not browsing history)
        if self.game.current_ply != len(self.game.moves_played):
            return
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            human = "White" if self._human_side == chess.WHITE else "Black"
            if winner == human:
                info(self, "🏆 Checkmate!", f"{winner} wins by checkmate! Congratulations!")
            else:
                info(self, "Checkmate", f"{winner} wins by checkmate.")
        elif board.is_stalemate():
            info(self, "Stalemate", "The game is a draw by stalemate.")
        elif board.is_insufficient_material():
            info(self, "Draw", "Draw — insufficient material to checkmate.")
        elif board.is_fifty_moves():
            info(self, "Draw", "Draw — 50 moves without a capture or pawn move.")
        elif board.is_repetition():
            info(self, "Draw", "Draw — threefold repetition.")
        elif not any(board.generate_legal_moves()):
            info(self, "Game Over", "No legal moves available.")

    def _request_threat(self) -> None:
        if not self.engine.is_running or self.game.board.is_check():
            return
        try:
            threat_board = self.game.board.copy()
            threat_board.push(chess.Move.null())
        except Exception:  # noqa: BLE001
            return
        self.engine.request_best_move(threat_board, self.engine_options.move_time_ms, tag="threat")

    # -- toolbar/menu actions --------------------------------------------
    def _on_new_game(self) -> None:
        if self.game.moves_played and not confirm(
            self, "New Game", "Discard the current position and start a new game?"
        ):
            return
        self.game.new_game()
        # Ask which side to play for the new game
        QTimer.singleShot(100, self._prompt_for_side)

    def _on_open_pgn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PGN", "", "PGN files (*.pgn)")
        if not path:
            return
        try:
            ok = self.game.load_pgn(path)
        except Exception as exc:  # noqa: BLE001
            warn(self, "Load PGN", f"Could not load PGN:\n{exc}")
            return
        if not ok:
            warn(self, "Load PGN", "No game found in that PGN file.")

    def _on_save_pgn(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save PGN", "game.pgn", "PGN files (*.pgn)")
        if not path:
            return
        try:
            self.game.save_pgn(path)
        except Exception as exc:  # noqa: BLE001
            warn(self, "Save PGN", f"Could not save PGN:\n{exc}")

    def _on_load_fen(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        fen, ok = QInputDialog.getText(self, "Load FEN", "FEN string:")
        if not ok or not fen.strip():
            return
        try:
            self.game.set_fen(fen.strip())
        except ValueError as exc:
            warn(self, "Invalid FEN", f"That FEN could not be parsed:\n{exc}")

    def _on_copy_fen(self) -> None:
        QApplication.clipboard().setText(self.game.copy_fen())
        self.statusBar().showMessage("FEN copied to clipboard", 3000)

    def _on_paste_fen(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        try:
            self.game.set_fen(text)
        except ValueError as exc:
            warn(self, "Invalid FEN", f"Clipboard does not contain a valid FEN:\n{exc}")

    def _on_undo(self) -> None:
        self.game.undo()

    def _on_redo(self) -> None:
        self.game.redo()

    def _jump(self, fn) -> None:
        fn()

    def _on_flip(self) -> None:
        self.ui_prefs.board_flipped = not self.ui_prefs.board_flipped
        self.board_view.set_flipped(self.ui_prefs.board_flipped)
        self.app_settings.save_ui_preferences(self.ui_prefs)

    def _on_analyze_toggled(self, checked: bool) -> None:
        self._continuous_analysis = checked
        if checked:
            self._restart_analysis()
        else:
            self.engine.stop_analysis()

    def _on_play_best_move(self) -> None:
        if not self.engine.is_running:
            warn(self, "Engine", "Engine is not running yet.")
            return
        self.engine.request_best_move(self.game.board, self.engine_options.move_time_ms, tag="best")

    def _on_hint(self) -> None:
        if not self.engine.is_running:
            warn(self, "Engine", "Engine is not running yet.")
            return
        self.engine.request_best_move(self.game.board, self.engine_options.move_time_ms, tag="hint")

    def _on_threat_toggled(self, checked: bool) -> None:
        self._threat_mode = checked
        if checked:
            # Stop continuous analysis before requesting threat
            self.engine.stop_analysis()
            self._request_threat()
        else:
            self.board_view.set_threat_move(None)
            # Resume analysis now that threat mode is off
            if self._continuous_analysis:
                self._restart_analysis()

    def _on_coach_toggled(self, checked: bool) -> None:
        """Coach mode: show the engine's recommended move with a blue arrow
        and highlight the piece, but ONLY when it's YOUR turn. Never shows
        the opponent's predicted move.
        """
        self._coach_mode = checked
        if checked:
            self.board_view.set_show_best_arrow(True)
            if not self._continuous_analysis:
                self.act_analyze.setChecked(True)
            self._update_perspective_label()
        else:
            self.board_view.set_show_best_arrow(self.ui_prefs.show_best_move_arrow)
            self.board_view.set_coach_from_square(None)
            self.status_perspective_label.setText("")

    def _on_set_human_side(self, side: bool) -> None:
        """Set which side the human is playing. The coach arrow will only
        show when it's this side's turn. Does NOT change the board turn —
        White always starts first in chess.
        """
        self._human_side = side
        self._update_perspective_label()
        # Force clear/reset the coach arrow so stale opponent moves vanish
        self.board_view.set_best_move(None)
        self.board_view.set_coach_from_square(None)

    def _prompt_for_side(self) -> None:
        """Show a dialog asking which side the user wants to play.
        Called on first launch and after new game.
        The board stays normal — White starts first.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome to ChessLab")
        layout = QVBoxLayout(dialog)

        label = QLabel("Which side would you like to play?")
        label.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 8px;")
        layout.addWidget(label)

        hint = QLabel(
            "The blue arrow shows your best move when it's your turn.\n"
            "White always starts first — play any side at any time."
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

        def choose_white():
            result["side"] = chess.WHITE
            dialog.accept()

        def choose_black():
            result["side"] = chess.BLACK
            dialog.accept()

        btn_white.clicked.connect(choose_white)
        btn_black.clicked.connect(choose_black)

        dialog.exec()

        side = result["side"]
        self._on_set_human_side(side)

        # Activate coach mode
        self._coach_mode = True
        self.board_view.set_show_best_arrow(True)
        self.act_coach.setChecked(True)

        # Show coach info now that side is known
        if not self._coach_mode_info_shown:
            self._coach_mode_info_shown = True
            human = "White" if side == chess.WHITE else "Black"
            info(
                self,
                "Coach Mode",
                "Coach Mode shows you your best move with a blue arrow.\n\n"
                f"You are playing as {human}. The arrow only appears on "
                f"YOUR turn ({human}'s turn).\n\n"
                "💡 To start a new game and switch sides, click 'New Game'.\n"
                "💡 To make your move, click the highlighted piece and "
                "then the target square, or drag-and-drop.",
            )

    def _update_perspective_label(self) -> None:
        """Update the status bar label showing whose turn the analysis is for.
        Shows a "Guide:" label when coach mode is active, or a simpler
        perspective label when the engine is running and analyzing.
        """
        if not self.engine.is_running or not self._continuous_analysis:
            self.status_perspective_label.setText("")
            return
        human = "White" if self._human_side == chess.WHITE else "Black"
        turn = self.game.board.turn
        turn_side = "White" if turn == chess.WHITE else "Black"
        if self._coach_mode:
            if turn == self._human_side:
                self.status_perspective_label.setText(f"Your turn ({human}) — arrow shows your best move")
            else:
                self.status_perspective_label.setText(f"Waiting for {turn_side}...")
        else:
            self.status_perspective_label.setText(f"Analyzing: {turn_side}'s turn")

    def _on_move_attempted(self, move: chess.Move) -> None:
        self.game.push_move(move)

    def _on_promotion_needed(self, origin: int, target: int) -> None:
        color = self.game.board.turn
        dialog = PromotionDialog(color, self)
        if dialog.exec():
            self.board_view.emit_promotion_move(origin, target, dialog.chosen_piece_type)
        else:
            self.board_view.set_board(self.game.board)  # snap back, no move made

    def _on_engine_line_clicked(self, pv: list[chess.Move]) -> None:
        if pv:
            self.board_view.set_best_move(pv[0])

    def _on_engine_settings(self) -> None:
        dialog = EngineSettingsDialog(self.app_settings, self.engine_options, self.ui_prefs, self)
        if not dialog.exec():
            return
        self.engine_options = dialog.result_options()
        self.ui_prefs = dialog.result_prefs()
        self.app_settings.save_engine_options(self.engine_options)
        self.app_settings.save_ui_preferences(self.ui_prefs)

        new_tb_path = dialog.result_tablebase_path()
        if new_tb_path != self.app_settings.syzygy_path:
            self.app_settings.syzygy_path = new_tb_path
            if new_tb_path:
                if not self.tablebase.open(new_tb_path):
                    warn(self, "Tablebase", "Could not open a Syzygy tablebase at that location.")
            else:
                self.tablebase.close()
            self._update_tablebase_status()

        self.engine.set_options(self.engine_options)
        self.board_view.set_square_size(self.ui_prefs.square_size)
        self.board_view.set_theme(BOARD_THEMES[self.ui_prefs.board_theme])
        self.board_view.set_show_coordinates(self.ui_prefs.show_coordinates)
        self.board_view.set_show_legal_dots(self.ui_prefs.show_legal_move_dots)
        self.board_view.set_show_best_arrow(self.ui_prefs.show_best_move_arrow)
        if self._continuous_analysis:
            self._restart_analysis()

    def _on_locate_engine(self) -> None:
        self._prompt_for_stockfish()

    def _on_about(self) -> None:
        info(
            self,
            "About ChessLab",
            "ChessLab — a local, Stockfish-powered chess analysis board.\n\n"
            "Built with PySide6 and python-chess. Not an online client: "
            "everything runs on this machine against your local Stockfish "
            "installation.",
        )

    # -- window state ------------------------------------------------------
    def _restore_window_state(self) -> None:
        geometry = self.app_settings.load_window_geometry()
        state = self.app_settings.load_window_state()
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        self.app_settings.save_window_state(self.saveGeometry(), self.saveState())
        self.app_settings.sync()
        self.tablebase.close()
        self.engine.quit()
        super().closeEvent(event)
