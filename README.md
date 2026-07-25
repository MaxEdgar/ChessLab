# ♚ ChessLab

**A local, Stockfish-powered chess analysis desktop application.**

Built with PySide6 and python-chess, inspired by Lichess's analysis board
and Chess.com's analysis tool — but running entirely on your own machine
against your own Stockfish installation.

✅ No accounts &nbsp;·&nbsp; ✅ No server &nbsp;·&nbsp; ✅ No network required
&nbsp;·&nbsp; ✅ Fully offline &nbsp;·&nbsp; ✅ Free & open source (MIT)

---

## ✨ Features

- **Interactive board** — click-to-move, drag-and-drop, legal-move dots,
  last-move/check highlights, board flipping, adjustable size, 3 color themes.
- **Live Stockfish analysis** — multi-line evaluation (MultiPV), depth, nodes,
  NPS, principal variations, best-move arrow.
- **Free analysis mode** — play either side at will, unlimited undo/redo,
  branching (playing from an earlier point discards the old continuation).
- **Game management** — New Game, load/save PGN, paste/copy FEN, reset.
- **Engine tools** — Play Best Move, Hint, adjustable Threads/Hash/Skill
  Level/MultiPV/depth/time, infinite analysis toggle.
- **Move quality** — Brilliant / Best / Excellent / Good / Inaccuracy /
  Mistake / Blunder classification by centipawn loss.
- **Opening names** — 60+ common openings identified offline.
- **Syzygy tablebase** — perfect win/draw/loss + distance-to-zero for
  endgames (tablebase files not bundled; you provide them).
- **Persistent settings** — window layout, engine options, display
  preferences remembered between sessions.

---

## 🚀 Quick Start

### One-command install (Linux / macOS)

```bash
git clone https://github.com/yourusername/chesslab.git
cd chesslab
chmod +x install.sh
./install.sh
```

The installer will:
1. Detect your OS and package manager (apt, pacman, dnf, etc.)
2. Install any missing system packages (Python, venv, pip)
3. Create a virtual environment (handles PEP 668 automatically, no
   `--break-system-packages` needed)
4. Install PySide6 and python-chess
5. Install ChessLab as an editable package
6. Detect or install Stockfish
7. Verify everything works

### Run

```bash
./run.sh
```

That's it. The script activates the venv and launches ChessLab.

### Manual install

If you prefer to do things by hand:

```bash
git clone https://github.com/yourusername/chesslab.git
cd chesslab

# Create a virtual environment (required — avoids PEP 668 headaches)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install ChessLab as an editable package
pip install -e .

# Launch
python -m chesslab
```

### Windows

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/)
   (check ✅ "Add Python to PATH" during installation).
2. Download Stockfish from [stockfishchess.org](https://stockfishchess.org/download/)
   and unzip it.
3. Open PowerShell or Command Prompt in the ChessLab folder:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m chesslab
```

ChessLab will ask you to locate the Stockfish `.exe` on first launch.

---

## 📖 Usage

### Board controls

| Action | How |
|--------|-----|
| Move a piece | Click the piece, then click the target square (or drag-and-drop) |
| Promote a pawn | A dialog appears automatically |
| Flip the board | Press `F` or click the toolbar button |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| New Game | `Ctrl+N` |

### Engine analysis

- **Continuous analysis** runs automatically when the engine is ready.
  The best move for the side to move is shown with a blue arrow.
- **Space** toggles analysis on/off.
- **Play Best Move** — the engine plays its recommended move.
- **Hint** — shows the engine's suggested move without playing it.
- **Engine Settings** — configure threads, hash size, skill level, MultiPV,
  move time, depth limit.
- **Show Threat** — highlights what the opponent would play if it were
  their turn again (red arrow).

### Managing games

- **Open PGN** (`Ctrl+O`) — load a game from a PGN file.
- **Save PGN** (`Ctrl+S`) — save the current game as PGN (move quality
  classifications are stored as comments).
- **Copy/Paste FEN** (`Ctrl+C` / `Ctrl+V`) — share or set positions.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | New Game |
| `Ctrl+O` | Open PGN |
| `Ctrl+S` | Save PGN |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+C` | Copy FEN |
| `Ctrl+V` | Paste FEN |
| `Space` | Toggle analysis |
| `F` | Flip board |
| `Ctrl+Q` | Quit |

---

## 🛠️ Requirements

- **Python 3.10 or newer**
- **Stockfish** — the chess engine (not bundled; see below)
- One of: **Windows 10/11**, **Linux** (Ubuntu, Debian, Mint, Pop!_OS,
  Arch, Fedora, etc.), or **macOS**

### Installing Stockfish

| OS | Command |
|----|---------|
| Ubuntu / Debian / Mint / Pop!_OS | `sudo apt install stockfish` |
| Arch / Manjaro | `sudo pacman -S stockfish` |
| Fedora | `sudo dnf install stockfish` |
| macOS (Homebrew) | `brew install stockfish` |
| Windows | Download from [stockfishchess.org](https://stockfishchess.org/download/) |

The installer (`./install.sh`) can do this for you automatically. If
Stockfish can't be found, ChessLab shows a dialog to browse to it.

---

## 📁 Project Structure

```
chesslab/
├── __init__.py      Package metadata and version
├── __main__.py      Entry point: `python -m chesslab`
├── main.py          App bootstrap, logging, exception hook
├── gui.py           MainWindow: menus, toolbar, docks, signal wiring
├── board.py         Interactive chessboard widget (QGraphicsView)
├── engine.py        Stockfish/UCI on a dedicated asyncio QThread
├── analysis.py      Game state, move history, PGN/FEN I/O, classification
├── panels.py        Eval bar, engine-lines panel, move-list widget
├── dialogs.py       Promotion picker, engine-locate and settings dialogs
├── pieces.py        Vector piece rendering (SVG from python-chess)
├── theme.py         Dark stylesheet + board color palettes
├── openings.py      Offline opening-name table (60+ entries)
├── tablebase.py     Syzygy endgame tablebase probing
├── config.py        Paths, persisted settings (QSettings-backed)
├── utils.py         Logging setup, formatting helpers
├── install.sh       Automated installer
├── run.sh           Launcher script
├── requirements.txt Python dependencies
└── pyproject.toml   Package metadata and build config
```

### Architecture Notes

- **Engine threading** — `chess.engine` is asyncio-based. `EngineManager`
  runs its own event loop on a dedicated `QThread`; all engine calls are
  marshalled via `asyncio.run_coroutine_threadsafe`. The GUI thread never
  blocks on engine I/O.
- **Move history** — `GameController` keeps a branchable move list with a
  `current_ply` cursor. Undo/redo move the cursor; playing a new move from
  a non-tip position truncates the old continuation.
- **Free analysis mode** — Set side to move via toolbar buttons (flips
  `board.turn`) so you can enter legal moves for either color.
- **Pieces** — Rendered from python-chess's bundled `cburnett` SVG set.
  No external image assets needed. Crisp at any board size.

---

## ⚠️ Known Limitations

- **Opening book** — A hand-picked table of ~60 openings; uncommon lines
  show no name. This keeps things fully offline.
- **Move classification** — A centipawn-loss heuristic from the live
  analysis stream, not a dedicated re-analysis. Needs a moment of engine
  thinking between moves.
- **Syzygy tablebase** — Not bundled. Download from
  [tablebase.lichess.ovh](https://tablebase.lichess.ovh/tables/standard/)
  and point Engine Settings to the folder.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Built with ❤️ for chess players who want full control over their analysis.*
