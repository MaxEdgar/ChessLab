#!/usr/bin/env bash
#
# ChessLab Installer
# ==================
# A polished, fully automated installer that handles:
#   - OS/distro detection (Ubuntu, Debian, Mint, Pop!_OS, Arch, Fedora, Windows)
#   - Python+venv setup
#   - PEP 668 (externally-managed-environment) via auto-created virtualenv
#   - Stockfish auto-detection and guided setup
#   - Dependency installation (PySide6, python-chess)
#   - Graceful reinstall/detect-skip on second run
#   - Friendly error recovery with meaningful messages
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# Environment variables:
#   CHESSLAB_VENV_PATH  - override the virtual environment path (default: ./venv)
#   CHESSLAB_SKIP_CONFIRM - set to "yes" to skip all prompts (non-interactive)

set -euo pipefail

# ─── ANSI helpers ─────────────────────────────────────────────────────────
BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
MAGENTA="\033[0;35m"
NC="\033[0m"             # No Color
CHECK="${GREEN}✔${NC}"
CROSS="${RED}✘${NC}"
DOT="${CYAN}●${NC}"
ARROW="${MAGENTA}→${NC}"

# ─── Globals ─────────────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PATH="${CHESSLAB_VENV_PATH:-$REPO_DIR/venv}"
OS_ID=""
OS_LIKE=""
PKG_MGR=""
STOCKFISH_PATH=""
INSTALL_LOG="$REPO_DIR/.install.log"

# ─── Helper functions ─────────────────────────────────────────────────────
log()    { echo -e "  $DOT $*"; }
ok()     { echo -e "  $CHECK ${GREEN}$*${NC}"; }
skip()   { echo -e "  ${CYAN}–${NC} ${CYAN}$*${NC}"; }
info()   { echo -e "  ${CYAN}ℹ${NC} ${CYAN}$*${NC}"; }
warn()   { echo -e "  ${YELLOW}⚠${NC} ${YELLOW}$*${NC}"; }
error()  { echo -e "  $CROSS ${RED}$*${NC}"; }
step()   { echo -e "\n  ${BOLD}${CYAN}── $* ──${NC}"; }
header() { echo -e "\n${BOLD}${MAGENTA}  $*${NC}\n"; }

prompt_yes_no() {
    # $1: prompt text, returns 0 for Yes, 1 for No
    if [ "${CHESSLAB_SKIP_CONFIRM:-}" = "yes" ]; then
        return 0
    fi
    local answer
    while true; do
        echo -ne "  ${ARROW} ${BOLD}$1${NC} ${DIM}(y/n)${NC} "
        read -r answer
        case "$answer" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "  ${DIM}Please answer y or n.${NC}" ;;
        esac
    done
}

# Banner width (between the ║ borders) is 40 characters.
print_banner() {
    echo ""
    echo -e "  ${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "  ${CYAN}║${NC}        ${BOLD}${MAGENTA}♚  ChessLab Installer  ♚${NC}         ${CYAN}║${NC}"
    echo -e "  ${CYAN}║${NC}     ${DIM}Stockfish-powered chess analysis${NC}     ${CYAN}║${NC}"
    echo -e "  ${CYAN}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

print_summary() {
    local success=$1
    echo ""
    if [ "$success" = true ]; then
        echo -e "  ${GREEN}${BOLD}🎉 ChessLab installation completed successfully!${NC}"
        echo ""
        echo -e "  ${ARROW} Run ChessLab:"
        echo -e "      ${BOLD}./run.sh${NC}"
        echo ""
        echo -e "  ${ARROW} Or activate the environment manually:"
        echo -e "      ${DIM}source ./venv/bin/activate${NC}"
        echo -e "      ${DIM}python -m chesslab${NC}"
        echo ""
        if [ -n "$STOCKFISH_PATH" ]; then
            echo -e "  ${CHECK} Stockfish detected at: ${DIM}$STOCKFISH_PATH${NC}"
        else
            echo -e "  ${YELLOW}⚠${NC} ${YELLOW}Stockfish was not found.${NC}"
            echo -e "    ChessLab will prompt you to locate it on first launch."
            echo ""
            echo -e "    ${DIM}Install it manually:${NC}"
            echo -e "      ${DIM}Ubuntu/Debian: sudo apt install stockfish${NC}"
            echo -e "      ${DIM}Arch:          sudo pacman -S stockfish${NC}"
            echo -e "      ${DIM}Fedora:        sudo dnf install stockfish${NC}"
            echo -e "      ${DIM}macOS:         brew install stockfish${NC}"
            echo -e "      ${DIM}Windows:       Download from stockfishchess.org${NC}"
        fi
    else
        echo -e "  ${RED}${BOLD}❌ ChessLab installation encountered errors.${NC}"
        echo -e "  ${DIM}Check the log file for details: $INSTALL_LOG${NC}"
        echo ""
        echo -e "  ${ARROW} You can re-run the installer after fixing the issue:"
        echo -e "      ${DIM}./install.sh${NC}"
    fi
    echo ""
}

# ─── OS Detection ─────────────────────────────────────────────────────────
detect_os() {
    log "Detecting operating system..."

    # Windows (Git Bash / WSL / MSYS2 / Cygwin)
    if [ "${OSTYPE:-}" = "msys" ] || [ "${OSTYPE:-}" = "cygwin" ] || \
       [ -n "${WSL_DISTRO_NAME:-}" ] || [ -n "${MSYSTEM:-}" ]; then
        OS_ID="windows"
        ok "Windows detected (WSL/Git Bash)"
        return 0
    fi

    if [ ! -f /etc/os-release ]; then
        OS_ID="unknown"
        warn "Cannot detect OS (/etc/os-release not found). Assuming Linux."
        return 0
    fi

    . /etc/os-release
    OS_ID="${ID,,}"
    OS_LIKE="${ID_LIKE,,}"

    ok "${PRETTY_NAME:-$OS_ID}"

    return 0
}

# ─── Package Manager Detection ───────────────────────────────────────────
detect_pkg_mgr() {
    case "$OS_ID" in
        ubuntu|debian|linuxmint|pop|neon|kali|raspbian|elementary|zorin)
            PKG_MGR="apt" ;;
        arch|manjaro|endeavouros|garuda|artix)
            PKG_MGR="pacman" ;;
        fedora|rhel|centos|rocky|alma)
            PKG_MGR="dnf" ;;
        opensuse*|suse)
            PKG_MGR="zypper" ;;
        alpine)
            PKG_MGR="apk" ;;
        void)
            PKG_MGR="xbps-install" ;;
        windows)
            PKG_MGR="" ;;  # No system package manager on Windows
        *)
            # Try to detect by availability
            for mgr in apt pacman dnf zypper apk xbps-install; do
                if command -v "$mgr" &>/dev/null; then
                    PKG_MGR="$mgr"
                    break
                fi
            done
            ;;
    esac

    if [ -n "$PKG_MGR" ]; then
        log "Package manager: ${BOLD}$PKG_MGR${NC}"
    else
        warn "No known package manager detected. Will use pip exclusively."
    fi
}

# ─── System Dependency Installation ──────────────────────────────────────
install_system_deps() {
    step "System Dependencies"

    # We need python3, python3-venv, and pip
    local need_python=false
    local need_venv=false
    local need_pip=false

    if ! command -v python3 &>/dev/null; then
        need_python=true
        warn "python3 not found"
    else
        ok "Python $(python3 --version 2>&1 | cut -d' ' -f2) found"
    fi

    # Check if venv module exists
    if ! python3 -c "import venv" 2>/dev/null; then
        need_venv=true
        warn "python3-venv not available"
    fi

    # On Windows via Git Bash, no system package manager
    if [ "$OS_ID" = "windows" ]; then
        if [ "$need_python" = true ]; then
            error "Python 3 is required. Please install it from https://www.python.org/downloads/"
            return 1
        fi
        if [ "$need_venv" = true ]; then
            warn "venv module not found. Ensure Python was installed with 'pip' and 'venv' support."
            return 1
        fi
        return 0
    fi

    # Build list of packages to install
    local pkgs=()
    if [ "$need_python" = true ]; then
        case "$PKG_MGR" in
            apt)      pkgs+=("python3") ;;
            pacman)   pkgs+=("python") ;;
            dnf)      pkgs+=("python3") ;;
            zypper)   pkgs+=("python3") ;;
            apk)      pkgs+=("python3") ;;
        esac
    fi
    if [ "$need_venv" = true ]; then
        case "$PKG_MGR" in
            apt)      pkgs+=("python3-venv") ;;
            pacman)   pkgs+=("python") ;;  # Arch includes venv in the main python package
            dnf)      pkgs+=("python3-venv") ;;
            zypper)   pkgs+=("python3-venv") ;;
        esac
    fi

    if [ "${#pkgs[@]}" -eq 0 ]; then
        ok "All system dependencies are already satisfied."
        return 0
    fi

    warn "The following packages need to be installed: ${pkgs[*]}"
    if ! prompt_yes_no "Install system packages (requires sudo)?"; then
        error "System packages are required. Please install them manually:"
        case "$PKG_MGR" in
            apt)   echo "  sudo apt update && sudo apt install -y ${pkgs[*]}" ;;
            pacman) echo "  sudo pacman -S --noconfirm ${pkgs[*]}" ;;
            dnf)   echo "  sudo dnf install -y ${pkgs[*]}" ;;
            zypper) echo "  sudo zypper install -y ${pkgs[*]}" ;;
        esac
        return 1
    fi

    # Install with sudo
    case "$PKG_MGR" in
        apt)
            sudo apt update >> "$INSTALL_LOG" 2>&1 || true
            sudo apt install -y "${pkgs[@]}" >> "$INSTALL_LOG" 2>&1
            ;;
        pacman)
            sudo pacman -S --noconfirm "${pkgs[@]}" >> "$INSTALL_LOG" 2>&1
            ;;
        dnf)
            sudo dnf install -y "${pkgs[@]}" >> "$INSTALL_LOG" 2>&1
            ;;
        zypper)
            sudo zypper install -y "${pkgs[@]}" >> "$INSTALL_LOG" 2>&1
            ;;
        *)
            error "Don't know how to install packages on this system."
            echo "  Please install manually: ${pkgs[*]}"
            return 1
            ;;
    esac

    ok "System packages installed successfully."
    return 0
}

# ─── Virtual Environment ─────────────────────────────────────────────────
setup_virtualenv() {
    step "Virtual Environment"

    # Check if venv already exists
    if [ -d "$VENV_PATH" ]; then
        log "Existing virtual environment found at ${DIM}$VENV_PATH${NC}"
        if prompt_yes_no "Recreate it? (Removes and starts fresh)"; then
            log "Removing old virtual environment..."
            rm -rf "$VENV_PATH"
            log "Creating fresh virtual environment..."
            python3 -m venv "$VENV_PATH" >> "$INSTALL_LOG" 2>&1
            ok "Virtual environment recreated."
        else
            ok "Using existing virtual environment."
        fi
    else
        log "Creating virtual environment..."
        python3 -m venv "$VENV_PATH" >> "$INSTALL_LOG" 2>&1
        ok "Virtual environment created at ${DIM}$VENV_PATH${NC}"
    fi

    # Verify it works
    if [ ! -f "$VENV_PATH/bin/python" ] && [ ! -f "$VENV_PATH/Scripts/python.exe" ]; then
        error "Virtual environment creation failed. Check $INSTALL_LOG for details."
        return 1
    fi
    return 0
}

activate_venv() {
    if [ -f "$VENV_PATH/bin/activate" ]; then
        # shellcheck disable=SC1090
        source "$VENV_PATH/bin/activate"
    elif [ -f "$VENV_PATH/Scripts/activate" ]; then
        # shellcheck disable=SC1090
        source "$VENV_PATH/Scripts/activate"
    else
        error "Cannot activate virtual environment."
        return 1
    fi
}

# ─── Python Dependencies ─────────────────────────────────────────────────
install_python_deps() {
    step "Python Dependencies"

    activate_venv

    # Upgrade pip — only show if version actually changed
    local pip_before
    pip_before="$(python -m pip --version 2>/dev/null | cut -d' ' -f2)"
    python -m pip install --upgrade pip >> "$INSTALL_LOG" 2>&1
    local pip_after
    pip_after="$(python -m pip --version 2>/dev/null | cut -d' ' -f2)"
    if [ "$pip_before" != "$pip_after" ]; then
        ok "pip upgraded (${pip_before} → ${pip_after})"
    else
        info "pip already up to date (${pip_after})"
    fi

    # Gather what we need to install from requirements.txt
    local needs_install=()
    if [ -f "$REPO_DIR/requirements.txt" ]; then
        while IFS= read -r req_raw || [ -n "$req_raw" ]; do
            # Strip blank/comment lines
            req="$(echo "$req_raw" | sed 's/#.*//' | xargs)"
            [ -z "$req" ] && continue

            # Extract just the package name (before any version specifier)
            local pkg_name
            pkg_name="$(echo "$req" | sed 's/[><=!].*//' | xargs)"
            [ -z "$pkg_name" ] && continue

            if pip show "$pkg_name" > /dev/null 2>&1; then
                local ver
                ver="$(pip show "$pkg_name" 2>/dev/null | grep '^Version:' | cut -d' ' -f2)"
                log "  ${DIM}$pkg_name ${GREEN}${ver}${NC} ${DIM}(already installed)${NC}"
            else
                needs_install+=("$req")
            fi
        done < "$REPO_DIR/requirements.txt"
    else
        # No requirements.txt — use defaults
        local default_deps=("PySide6>=6.7,<7.0" "chess>=1.11,<2.0")
        for dep in "${default_deps[@]}"; do
            pkg_name="$(echo "$dep" | sed 's/[><=!].*//' | xargs)"
            if ! pip show "$pkg_name" > /dev/null 2>&1; then
                needs_install+=("$dep")
            else
                local ver
                ver="$(pip show "$pkg_name" 2>/dev/null | grep '^Version:' | cut -d' ' -f2)"
                log "  ${DIM}$pkg_name ${GREEN}${ver}${NC} ${DIM}(already installed)${NC}"
            fi
        done
    fi

    if [ "${#needs_install[@]}" -eq 0 ]; then
        skip "All Python packages already up to date."
    else
        pip install --upgrade "${needs_install[@]}" >> "$INSTALL_LOG" 2>&1
        ok "${#needs_install[@]} package(s) installed."
    fi

    # Install the package itself in development mode
    if pip show chesslab > /dev/null 2>&1; then
        local cl_ver
        cl_ver="$(pip show chesslab 2>/dev/null | grep '^Version:' | cut -d' ' -f2)"
        # Still reinstall in editable mode in case source changed
        pip install -e "$REPO_DIR" >> "$INSTALL_LOG" 2>&1
        info "ChessLab ${cl_ver} (re-linked)"
    else
        log "Installing ChessLab package..."
        pip install -e "$REPO_DIR" >> "$INSTALL_LOG" 2>&1
        ok "ChessLab package installed."
    fi
}

# ─── Stockfish Detection ─────────────────────────────────────────────────
detect_stockfish() {
    step "Stockfish Detection"

    # Common locations
    local stockfish_candidates=(
        "stockfish"
        "/usr/games/stockfish"
        "/usr/bin/stockfish"
        "/usr/local/bin/stockfish"
        "/snap/bin/stockfish"
        "/opt/homebrew/bin/stockfish"
    )

    # Try installing via package manager first
    local found=false
    for candidate in "${stockfish_candidates[@]}"; do
        if command -v "$candidate" &>/dev/null || [ -f "$candidate" ]; then
            STOCKFISH_PATH="$candidate"
            found=true
            break
        fi
    done

    if [ "$found" = true ]; then
        ok "Stockfish found at ${DIM}$STOCKFISH_PATH${NC}"
        stockfish_version="$("$STOCKFISH_PATH" --version 2>/dev/null || "$STOCKFISH_PATH" version 2>/dev/null || echo "")"
        if [ -n "$stockfish_version" ]; then
            echo "            ${DIM}Version: $stockfish_version${NC}"
        fi
        return 0
    fi

    warn "Stockfish not found in PATH or common locations."

    # Offer to install via package manager
    if [ "$OS_ID" != "windows" ]; then
        if prompt_yes_no "Install Stockfish via package manager?"; then
            case "$PKG_MGR" in
                apt)
                    sudo apt install -y stockfish >> "$INSTALL_LOG" 2>&1
                    ;;
                pacman)
                    sudo pacman -S --noconfirm stockfish >> "$INSTALL_LOG" 2>&1
                    ;;
                dnf)
                    sudo dnf install -y stockfish >> "$INSTALL_LOG" 2>&1
                    ;;
                zypper)
                    sudo zypper install -y stockfish >> "$INSTALL_LOG" 2>&1
                    ;;
                apk)
                    sudo apk add stockfish >> "$INSTALL_LOG" 2>&1
                    ;;
                *)
                    warn "Don't know how to install Stockfish on this OS."
                    ;;
            esac

            # Re-check after install
            if command -v stockfish &>/dev/null; then
                STOCKFISH_PATH="$(command -v stockfish)"
                ok "Stockfish installed at ${DIM}$STOCKFISH_PATH${NC}"
                return 0
            fi
        else
            log "You can install Stockfish manually:"
            log "  Ubuntu/Debian: ${DIM}sudo apt install stockfish${NC}"
            log "  Arch:          ${DIM}sudo pacman -S stockfish${NC}"
            log "  Fedora:        ${DIM}sudo dnf install stockfish${NC}"
            log "  macOS:         ${DIM}brew install stockfish${NC}"
            log "  Windows:       ${DIM}Download from https://stockfishchess.org/download/${NC}"
            echo ""
            if prompt_yes_no "Do you already have Stockfish installed at a custom location?"; then
                log "ChessLab will prompt you to locate it on first launch."
            fi
        fi
    else
        warn "Please download Stockfish from https://stockfishchess.org/download/"
        log "ChessLab will prompt you to locate it on first launch."
    fi
}

# ─── Create run.sh ───────────────────────────────────────────────────────
create_run_script() {
    if [ -f "$REPO_DIR/run.sh" ]; then
        log "Found existing run.sh."
        if [ -x "$REPO_DIR/run.sh" ]; then
            ok "run.sh is executable."
        else
            log "Making run.sh executable..."
            chmod +x "$REPO_DIR/run.sh"
            ok "Done."
        fi
    else
        warn "run.sh not found. It should have been created by the installer."
        warn "You can create it manually or re-run the installer."
    fi
}

# ─── Verify Installation ─────────────────────────────────────────────────
verify_install() {
    step "Verification"

    activate_venv

    local all_ok=true

    if python -c "import chess" 2>/dev/null; then
        local chess_ver
        chess_ver="$(python -c "import chess; print(chess.__version__)" 2>/dev/null || echo "installed")"
        ok "python-chess ${DIM}$chess_ver${NC}"
    else
        error "python-chess failed to import."
        all_ok=false
    fi

    if python -c "import PySide6" 2>/dev/null; then
        local pyside_ver
        pyside_ver="$(python -c "import PySide6; print(PySide6.__version__)" 2>/dev/null || echo "installed")"
        ok "PySide6 ${DIM}$pyside_ver${NC}"
    else
        error "PySide6 failed to import."
        all_ok=false
    fi

    if python -c "import chesslab" 2>/dev/null; then
        ok "ChessLab ${DIM}$(python -c "import chesslab; print(chesslab.__version__)" 2>/dev/null || echo "package")${NC}"
    else
        error "ChessLab package failed to import."
        all_ok=false
    fi

    if [ -n "$STOCKFISH_PATH" ] || command -v stockfish &>/dev/null; then
        ok "Stockfish ${DIM}available${NC}"
    fi

    if [ "$all_ok" = true ]; then
        return 0
    else
        return 1
    fi
}

# ─── Permissions ──────────────────────────────────────────────────────────
set_permissions() {
    # Make run.sh executable
    if [ -f "$REPO_DIR/run.sh" ]; then
        chmod +x "$REPO_DIR/run.sh"
    fi
    chmod +x "$REPO_DIR/install.sh"
}

# ─── Main ────────────────────────────────────────────────────────────────
main() {
    print_banner

    # Start logging
    echo "--- ChessLab Installer Log --- $(date) ---" > "$INSTALL_LOG"

    # ── Step 0: Internet Check ──
    step "Internet Connection"
    log "Checking internet connectivity..."
    if command -v curl &>/dev/null; then
        if curl -s --connect-timeout 5 -o /dev/null https://pypi.org 2>/dev/null; then
            ok "Connected to the internet."
        else
            warn "Cannot reach PyPI (pypi.org). Package installation may fail."
            if ! prompt_yes_no "Continue anyway?"; then
                error "Installation cancelled. Please check your internet connection."
                exit 1
            fi
        fi
    elif command -v wget &>/dev/null; then
        if wget -q --timeout=5 --spider https://pypi.org 2>/dev/null; then
            ok "Connected to the internet."
        else
            warn "Cannot reach PyPI (pypi.org). Package installation may fail."
            if ! prompt_yes_no "Continue anyway?"; then
                error "Installation cancelled. Please check your internet connection."
                exit 1
            fi
        fi
    else
        warn "Cannot check internet (curl/wget not available)."
    fi

    # ── Step 1: OS Detection ──
    detect_os
    detect_pkg_mgr

    # ── Step 2: System Dependencies ──
    if ! install_system_deps; then
        print_summary false
        exit 1
    fi

    # ── Step 3: Virtual Environment ──
    if ! setup_virtualenv; then
        print_summary false
        exit 1
    fi

    # ── Step 4: Python Dependencies ──
    if ! install_python_deps; then
        print_summary false
        exit 1
    fi

    # ── Step 5: Stockfish ──
    detect_stockfish

    # ── Step 6: Create run.sh ──
    create_run_script

    # ── Step 7: Set permissions ──
    set_permissions

    # ── Step 8: Verify ──
    if ! verify_install; then
        print_summary false
        exit 1
    fi

    print_summary true
}

main "$@"
