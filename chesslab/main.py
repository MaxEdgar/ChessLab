"""ChessLab entry point."""

from __future__ import annotations

import logging
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from chesslab.config import APP_NAME, ORG_NAME
from chesslab.gui import MainWindow
from chesslab.theme import DARK_QSS
from chesslab.utils import setup_logging

logger = logging.getLogger("chesslab.main")


def _guard_wrong_entry_point() -> None:
    """Detect if the user accidentally ran ``python main.py`` instead of
    ``python -m chesslab`` and show a helpful message instead of a cryptic
    ``ModuleNotFoundError``.

    When a file inside a package is run directly, Python adds that file's
    directory to ``sys.path[0]`` rather than the package root, making
    ``from chesslab.xxx`` imports fail. We detect this by checking whether
    ``chesslab`` is importable as a top-level package.
    """
    try:
        import chesslab  # noqa: F401 - verify the package is reachable
    except ImportError:
        print(
            "ERROR: ChessLab must be launched with:\n"
            "\n"
            "    python -m chesslab\n"
            "\n"
            "Or, if you installed ChessLab via the installer:\n"
            "\n"
            "    ./run.sh\n"
            "\n"
            "Running main.py directly does not work because Python cannot"
            " find the 'chesslab' package this way.",
            file=sys.stderr,
        )
        sys.exit(1)


def _install_exception_hook(app: QApplication) -> None:
    """Show a dialog and log the traceback instead of silently crashing.

    A GUI application that dies to an unhandled exception with no visible
    error is one of the most common sources of "it just closed" bug
    reports, so every uncaught exception is surfaced to the user as well
    as the log file.
    """

    def handle(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                "Unexpected Error",
                "ChessLab hit an unexpected error and may be unstable.\n"
                "Details were written to the log file.\n\n" + text[-1200:],
            )
        except Exception:  # noqa: BLE001 - never let the handler itself crash
            pass

    sys.excepthook = handle


def main(float_mode: bool = False) -> int:
    _guard_wrong_entry_point()
    setup_logging(logging.INFO)
    logger.info("Starting ChessLab (float_mode=%s)", float_mode)

    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(DARK_QSS)

    _install_exception_hook(app)

    if float_mode:
        from chesslab.floating import FloatingBoardWindow

        window = FloatingBoardWindow()
    else:
        window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main(float_mode="--float" in sys.argv))
