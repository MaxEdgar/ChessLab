#!/usr/bin/env bash
#
# ChessLab Launcher
# =================
# A simple launcher that activates the virtual environment and starts ChessLab.
#
# Usage:
#   ./run.sh
#
# Environment variables:
#   CHESSLAB_VENV_PATH  - override the virtual environment path (default: ./venv)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PATH="${CHESSLAB_VENV_PATH:-$REPO_DIR/venv}"

# ─── Colors ──────────────────────────────────────────────────────────────
GREEN="\033[0;32m"
RED="\033[0;31m"
DIM="\033[2m"
NC="\033[0m"

# ─── Find Python in virtual environment ──────────────────────────────────
if [ -f "$VENV_PATH/bin/python" ]; then
    PYTHON="$VENV_PATH/bin/python"
elif [ -f "$VENV_PATH/Scripts/python.exe" ]; then
    PYTHON="$VENV_PATH/Scripts/python.exe"
else
    echo -e "${RED}Error:${NC} Virtual environment not found at ${DIM}$VENV_PATH${NC}"
    echo ""
    echo "  Run the installer first:"
    echo "    ${DIM}./install.sh${NC}"
    echo ""
    echo "  Or set CHESSLAB_VENV_PATH to the correct location:"
    echo "    ${DIM}CHESSLAB_VENV_PATH=/path/to/venv ./run.sh${NC}"
    exit 1
fi

# ─── Check if chesslab is importable ─────────────────────────────────────
# If the package isn't installed, try installing it in editable mode.
if ! "$PYTHON" -c "import chesslab" 2>/dev/null; then
    echo -e "${DIM}Installing ChessLab package...${NC}"
    "$PYTHON" -m pip install -e "$REPO_DIR" > /dev/null 2>&1 || {
        echo -e "${RED}Error:${NC} Could not install ChessLab package."
        exit 1
    }
fi

# ─── Launch ──────────────────────────────────────────────────────────────
echo -e "${GREEN}Starting ChessLab...${NC}"
# Pass any command-line arguments (e.g. --float) through to Python
exec "$PYTHON" -m chesslab "$@"
