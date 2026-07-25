"""Stockfish (UCI) integration.

python-chess's engine protocol is asyncio-based. To keep the Qt GUI
thread free of any blocking I/O, :class:`EngineManager` owns a private
asyncio event loop running on its own ``QThread``. All engine operations
(open, analyze, stop, set options, quit) are scheduled onto that loop with
``asyncio.run_coroutine_threadsafe`` from the GUI thread, and results are
reported back via Qt signals, which Qt marshals safely across threads.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import chess
import chess.engine
from PySide6.QtCore import QObject, QThread, Signal, Slot

from chesslab.config import EngineOptions

logger = logging.getLogger("chesslab.engine")


@dataclass
class EngineInfoUpdate:
    """One engine 'info' line, normalized for the UI."""

    multipv: int
    depth: int
    seldepth: int
    score: Optional[chess.engine.PovScore]
    nodes: int
    nps: int
    time_s: float
    pv: list[chess.Move]
    board_fen_at_search: str


class _EngineLoopThread(QThread):
    """A QThread whose run() drives a private asyncio event loop forever."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = asyncio.Event  # placeholder type hint only

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._signal_ready)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def _signal_ready(self) -> None:
        pass  # hook point; readiness is detected by polling `self.loop`.

    def stop_loop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


class EngineManager(QObject):
    """Owns the Stockfish subprocess and exposes an async-free Qt API.

    Signals
    -------
    engineReady()
        Emitted once the engine process has started and identified itself.
    engineFailed(str)
        Emitted with a human-readable error if startup fails.
    infoUpdated(EngineInfoUpdate)
        Emitted for every MultiPV info line during a search.
    bestMoveFound(object, object)
        Emitted with (best_move: chess.Move | None, ponder: chess.Move | None)
        when a search concludes.
    searchStarted()
    searchStopped()
    """

    engineReady = Signal()
    engineFailed = Signal(str)
    infoUpdated = Signal(object)
    bestMoveFound = Signal(object, object)
    searchStarted = Signal()
    searchStopped = Signal()
    oneShotMoveReady = Signal(object, str)  # (chess.Move | None, request_tag)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = _EngineLoopThread()
        self._engine: Optional[chess.engine.UciProtocol] = None
        self._transport = None
        self._analysis: Optional[chess.engine.AnalysisResult] = None
        self._current_options = EngineOptions()
        self._path: Optional[str] = None
        self._thread.start()
        # Busy-wait briefly for the loop attribute to appear; the thread
        # sets it almost immediately upon run(). A tiny spin is simpler and
        # more portable here than a cross-thread condition variable for a
        # one-time startup handshake.
        import time

        for _ in range(200):
            if self._thread.loop is not None:
                break
            time.sleep(0.005)

    # -- lifecycle -----------------------------------------------------------
    def start_engine(self, path: str, options: EngineOptions) -> None:
        self._path = path
        self._current_options = options
        self._run_coro(self._async_start(path, options))

    async def _async_start(self, path: str, options: EngineOptions) -> None:
        try:
            transport, engine = await chess.engine.popen_uci(path)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            logger.exception("Failed to start engine at %s", path)
            self.engineFailed.emit(str(exc))
            return
        self._transport = transport
        self._engine = engine
        try:
            await engine.configure(options.to_uci_dict())
        except Exception:  # noqa: BLE001
            logger.warning("Some UCI options were rejected by the engine", exc_info=True)
        self.engineReady.emit()

    def set_options(self, options: EngineOptions) -> None:
        self._current_options = options
        if self._engine is not None:
            self._run_coro(self._async_configure(options))

    async def _async_configure(self, options: EngineOptions) -> None:
        if self._engine is None:
            return
        try:
            await self._engine.configure(options.to_uci_dict())
        except Exception:  # noqa: BLE001
            logger.warning("Failed to apply engine options", exc_info=True)

    def quit(self) -> None:
        loop = self._thread.loop
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._async_quit(), loop)
            try:
                # Block briefly so the subprocess is actually terminated and
                # the coroutine fully unwinds before we stop the loop out
                # from under it -- letting the loop stop mid-coroutine is
                # what left a dangling asyncio Task/transport on shutdown.
                future.result(timeout=3)
            except Exception:  # noqa: BLE001
                logger.warning("Engine shutdown did not complete cleanly", exc_info=True)
        self._thread.stop_loop()
        self._thread.wait(2000)

    async def _async_quit(self) -> None:
        if self._analysis is not None:
            self._analysis.stop()
            self._analysis = None
        if self._engine is not None:
            try:
                await self._engine.quit()
            except Exception:  # noqa: BLE001
                pass

    # -- analysis --------------------------------------------------------
    def start_analysis(self, board: chess.Board, options: EngineOptions) -> None:
        """Begin (or restart) analysis of the given position."""
        self._current_options = options
        self._run_coro(self._async_start_analysis(board.copy(), options))

    async def _async_start_analysis(self, board: chess.Board, options: EngineOptions) -> None:
        if self._engine is None:
            return
        if self._analysis is not None:
            # stop() only requests a stop; without waiting for it to
            # actually finish, immediately starting a new analysis command
            # races with the old one's "bestmove" bookkeeping inside
            # python-chess and can raise InvalidStateError. Waiting (with a
            # timeout as a safety net) makes restarts deterministic.
            self._analysis.stop()
            try:
                await asyncio.wait_for(self._analysis.wait(), timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
            self._analysis = None

        limit = self._build_limit(options)
        try:
            self._analysis = await self._engine.analysis(
                board, limit, multipv=max(1, options.multipv)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to start analysis")
            self.engineFailed.emit(str(exc))
            return

        self.searchStarted.emit()
        fen = board.fen()
        try:
            async for info in self._analysis:
                update = self._to_update(info, fen)
                if update is not None:
                    self.infoUpdated.emit(update)
        except Exception:  # noqa: BLE001
            logger.debug("Analysis stream ended", exc_info=True)
        finally:
            best = None
            ponder = None
            if self._analysis is not None:
                best = self._analysis.info.get("pv", [None])[0] if self._analysis.info else None
            self.bestMoveFound.emit(best, ponder)
            self.searchStopped.emit()

    @staticmethod
    def _build_limit(options: EngineOptions) -> chess.engine.Limit:
        if options.infinite_analysis:
            return chess.engine.Limit(
                depth=options.depth_limit or None,
                time=None,
            )
        if options.depth_limit:
            return chess.engine.Limit(depth=options.depth_limit)
        return chess.engine.Limit(time=max(0.05, options.move_time_ms / 1000.0))

    @staticmethod
    def _to_update(info: dict, fen: str) -> Optional[EngineInfoUpdate]:
        pv = info.get("pv")
        if not pv:
            return None
        return EngineInfoUpdate(
            multipv=int(info.get("multipv", 1)),
            depth=int(info.get("depth", 0)),
            seldepth=int(info.get("seldepth", 0)),
            score=info.get("score"),
            nodes=int(info.get("nodes", 0)),
            nps=int(info.get("nps", 0)),
            time_s=float(info.get("time", 0.0)),
            pv=list(pv),
            board_fen_at_search=fen,
        )

    def stop_analysis(self) -> None:
        self._run_coro(self._async_stop_analysis())

    async def _async_stop_analysis(self) -> None:
        if self._analysis is not None:
            self._analysis.stop()

    def request_best_move(self, board: chess.Board, movetime_ms: int, tag: str = "") -> None:
        """One-shot search for a single best move (used by 'Play best move',
        'Hint', and 'Show threat'). Result arrives via ``oneShotMoveReady``,
        never a raw Python callback, since this runs on the engine thread.
        """
        self._run_coro(self._async_best_move(board.copy(), movetime_ms, tag))

    async def _async_best_move(self, board: chess.Board, movetime_ms: int, tag: str) -> None:
        if self._engine is None:
            self.oneShotMoveReady.emit(None, tag)
            return
        try:
            result = await self._engine.play(
                board, chess.engine.Limit(time=max(0.05, movetime_ms / 1000.0))
            )
            self.oneShotMoveReady.emit(result.move, tag)
        except Exception:  # noqa: BLE001
            logger.exception("play() failed")
            self.oneShotMoveReady.emit(None, tag)

    # -- helpers -----------------------------------------------------------
    def _run_coro(self, coro) -> None:
        loop = self._thread.loop
        if loop is None:
            logger.error("Engine loop not ready; dropping request")
            return
        asyncio.run_coroutine_threadsafe(coro, loop)

    @property
    def is_running(self) -> bool:
        return self._engine is not None
