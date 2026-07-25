"""Entry point for ``python -m chesslab``."""

from __future__ import annotations

import sys


def _guard_wrong_entry_point() -> None:
    """Detect if the user accidentally ran ``python __main__.py`` directly
    instead of ``python -m chesslab``."""
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
            "    ./run.sh\n",
            file=sys.stderr,
        )
        sys.exit(1)


_guard_wrong_entry_point()

from chesslab.main import main  # noqa: E402 - import after guard

sys.exit(main())
