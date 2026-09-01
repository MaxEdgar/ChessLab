"""Application configuration, paths, and persisted settings.

All user-configurable state (engine path, engine options, UI preferences)
is persisted through :class:`AppSettings`, a thin wrapper around
``QSettings`` that gives the rest of the application a typed, discoverable
interface instead of scattering raw ``QSettings`` calls throughout the code.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings

ORG_NAME = "ChessLab"
APP_NAME = "ChessLab"

# Directory used for logs and any cached data. Kept inside the user's
# standard config/cache location rather than next to the source tree so the
# app behaves correctly whether run from source or a packaged build.
if platform.system() == "Windows":
    _base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    APP_DATA_DIR = _base / APP_NAME
else:
    _base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    APP_DATA_DIR = _base / "chesslab"

LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "chesslab.log"

DEFAULT_ENGINE_THREADS = max(1, (os.cpu_count() or 4) - 1)
DEFAULT_ENGINE_HASH_MB = 256
DEFAULT_MULTIPV = 1
DEFAULT_SKILL_LEVEL = 18  # 0-20, 20 = full strength; 18 = strong human ~2200 Elo
DEFAULT_MOVE_TIME_MS = 3000
DEFAULT_DEPTH_LIMIT = 0  # 0 = unlimited / time-based
DEFAULT_LIMIT_STRENGTH = True  # enable UCI_LimitStrength for human-like play
DEFAULT_UCI_ELO = 2200  # target Elo when limit_strength is on

SQUARE_SIZE_DEFAULT = 72

# Bundled Stockfish location (shipped with ChessLab).
_REPO_DIR = Path(__file__).resolve().parent.parent
_BUNDLED_STOCKFISH = _REPO_DIR / "stockfish" / "stockfish"
_BUNDLED_STOCKFISH_EXE = _REPO_DIR / "stockfish" / "stockfish.exe"

# Common install locations checked when Stockfish isn't found on PATH.
_COMMON_STOCKFISH_PATHS_LINUX = [
    "/usr/games/stockfish",
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/snap/bin/stockfish",
]
_COMMON_STOCKFISH_PATHS_MACOS = [
    "/opt/homebrew/bin/stockfish",
    "/usr/local/bin/stockfish",
]
_COMMON_STOCKFISH_PATHS_WINDOWS = [
    r"C:\Program Files\Stockfish\stockfish.exe",
    r"C:\ProgramData\chocolatey\bin\stockfish.exe",
    r"C:\Stockfish\stockfish.exe",
]


def find_stockfish() -> Optional[str]:
    """Search bundled directory, PATH, and common install locations for a
    Stockfish binary.  The bundled copy (inside ``stockfish/``) is checked
    first so ChessLab works out of the box without a system-wide install.

    Returns the absolute path as a string if found, otherwise ``None``.
    """
    # 1. Bundled binary shipped with ChessLab
    bundled = _BUNDLED_STOCKFISH_EXE if platform.system() == "Windows" else _BUNDLED_STOCKFISH
    if bundled.is_file():
        return str(bundled)

    # 2. On PATH
    for candidate in ("stockfish", "stockfish.exe"):
        found = shutil.which(candidate)
        if found:
            return found

    # 3. Common install directories
    system = platform.system()
    if system == "Windows":
        candidates = _COMMON_STOCKFISH_PATHS_WINDOWS
    elif system == "Darwin":
        candidates = _COMMON_STOCKFISH_PATHS_MACOS
    else:
        candidates = _COMMON_STOCKFISH_PATHS_LINUX

    for path in candidates:
        if Path(path).is_file():
            return path
    return None


@dataclass
class EngineOptions:
    """UCI engine options the user can tune from the Engine dock."""

    threads: int = DEFAULT_ENGINE_THREADS
    hash_mb: int = DEFAULT_ENGINE_HASH_MB
    skill_level: int = DEFAULT_SKILL_LEVEL
    multipv: int = DEFAULT_MULTIPV
    move_time_ms: int = DEFAULT_MOVE_TIME_MS
    depth_limit: int = DEFAULT_DEPTH_LIMIT
    infinite_analysis: bool = True
    limit_strength: bool = DEFAULT_LIMIT_STRENGTH
    uci_elo: int = DEFAULT_UCI_ELO

    def to_uci_dict(self) -> dict:
        # Note: MultiPV is intentionally omitted here. python-chess's
        # engine.analysis()/engine.play() manage MultiPV automatically via
        # their own `multipv=` argument, and calling configure() with it
        # raises "cannot set MultiPV which is automatically managed".
        opts: dict = {
            "Threads": self.threads,
            "Hash": self.hash_mb,
            "Skill Level": self.skill_level,
        }
        if self.limit_strength:
            opts["UCI_LimitStrength"] = True
            opts["UCI_Elo"] = max(1320, min(self.uci_elo, 3190))
        else:
            opts["UCI_LimitStrength"] = False
        return opts

    @classmethod
    def human_like(cls) -> EngineOptions:
        """Return a preset configured for strong human-like play (~2200 Elo)."""
        return cls(
            skill_level=18,
            limit_strength=True,
            uci_elo=2200,
            infinite_analysis=True,
        )

    @classmethod
    def full_strength(cls) -> EngineOptions:
        """Return a preset configured for maximum engine strength."""
        return cls(
            skill_level=20,
            limit_strength=False,
            uci_elo=3190,
            infinite_analysis=True,
        )


@dataclass
class UiPreferences:
    board_theme: str = "midnight"
    piece_set: str = "cburnett"
    board_flipped: bool = False
    show_coordinates: bool = True
    show_legal_move_dots: bool = True
    show_best_move_arrow: bool = True
    square_size: int = SQUARE_SIZE_DEFAULT


class AppSettings:
    """Typed wrapper around QSettings for persisted application state."""

    def __init__(self) -> None:
        self._qs = QSettings(ORG_NAME, APP_NAME)

    # -- engine ----------------------------------------------------------
    @property
    def stockfish_path(self) -> Optional[str]:
        value = self._qs.value("engine/path", type=str)
        return value or None

    @stockfish_path.setter
    def stockfish_path(self, value: Optional[str]) -> None:
        self._qs.setValue("engine/path", value or "")

    @property
    def syzygy_path(self) -> Optional[str]:
        value = self._qs.value("engine/syzygy_path", type=str)
        return value or None

    @syzygy_path.setter
    def syzygy_path(self, value: Optional[str]) -> None:
        self._qs.setValue("engine/syzygy_path", value or "")

    def load_engine_options(self) -> EngineOptions:
        defaults = EngineOptions()
        return EngineOptions(
            threads=int(self._qs.value("engine/threads", defaults.threads)),
            hash_mb=int(self._qs.value("engine/hash_mb", defaults.hash_mb)),
            skill_level=int(self._qs.value("engine/skill_level", defaults.skill_level)),
            multipv=int(self._qs.value("engine/multipv", defaults.multipv)),
            move_time_ms=int(self._qs.value("engine/move_time_ms", defaults.move_time_ms)),
            depth_limit=int(self._qs.value("engine/depth_limit", defaults.depth_limit)),
            infinite_analysis=self._qs.value(
                "engine/infinite", defaults.infinite_analysis, type=bool
            ),
            limit_strength=self._qs.value(
                "engine/limit_strength", defaults.limit_strength, type=bool
            ),
            uci_elo=int(self._qs.value("engine/uci_elo", defaults.uci_elo)),
        )

    def save_engine_options(self, opts: EngineOptions) -> None:
        self._qs.setValue("engine/threads", opts.threads)
        self._qs.setValue("engine/hash_mb", opts.hash_mb)
        self._qs.setValue("engine/skill_level", opts.skill_level)
        self._qs.setValue("engine/multipv", opts.multipv)
        self._qs.setValue("engine/move_time_ms", opts.move_time_ms)
        self._qs.setValue("engine/depth_limit", opts.depth_limit)
        self._qs.setValue("engine/infinite", opts.infinite_analysis)
        self._qs.setValue("engine/limit_strength", opts.limit_strength)
        self._qs.setValue("engine/uci_elo", opts.uci_elo)

    # -- ui ----------------------------------------------------------------
    def load_ui_preferences(self) -> UiPreferences:
        defaults = UiPreferences()
        return UiPreferences(
            board_theme=str(self._qs.value("ui/board_theme", defaults.board_theme)),
            piece_set=str(self._qs.value("ui/piece_set", defaults.piece_set)),
            board_flipped=self._qs.value("ui/flipped", defaults.board_flipped, type=bool),
            show_coordinates=self._qs.value(
                "ui/show_coordinates", defaults.show_coordinates, type=bool
            ),
            show_legal_move_dots=self._qs.value(
                "ui/show_legal_dots", defaults.show_legal_move_dots, type=bool
            ),
            show_best_move_arrow=self._qs.value(
                "ui/show_best_arrow", defaults.show_best_move_arrow, type=bool
            ),
            square_size=int(self._qs.value("ui/square_size", defaults.square_size)),
        )

    def save_ui_preferences(self, prefs: UiPreferences) -> None:
        self._qs.setValue("ui/board_theme", prefs.board_theme)
        self._qs.setValue("ui/piece_set", prefs.piece_set)
        self._qs.setValue("ui/flipped", prefs.board_flipped)
        self._qs.setValue("ui/show_coordinates", prefs.show_coordinates)
        self._qs.setValue("ui/show_legal_dots", prefs.show_legal_move_dots)
        self._qs.setValue("ui/show_best_arrow", prefs.show_best_move_arrow)
        self._qs.setValue("ui/square_size", prefs.square_size)

    # -- window geometry ----------------------------------------------------
    def save_window_state(self, geometry: bytes, state: bytes) -> None:
        self._qs.setValue("window/geometry", geometry)
        self._qs.setValue("window/state", state)

    def load_window_geometry(self):
        return self._qs.value("window/geometry")

    def load_window_state(self):
        return self._qs.value("window/state")

    def sync(self) -> None:
        self._qs.sync()
