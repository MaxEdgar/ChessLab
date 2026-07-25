# ChessLab

A local, Stockfish-powered chess analysis desktop application. Built with
PySide6 and python-chess, in the spirit of Lichess's analysis board or
Chess.com's analysis tool, but running entirely on your own machine against
your own Stockfish install.

This is not an online chess client. There is no server, no account, and no
network dependency once Stockfish is installed. You set up a position, move
either side freely, and get continuous, multi-line engine analysis while you
explore.

## Features

- Interactive board: click-to-move and drag-and-drop, legal-move highlighting,
  last-move and check highlighting, board flipping, adjustable square size,
  three built-in color themes.
- Continuous Stockfish analysis: live evaluation, MultiPV top lines, depth,
  nodes, NPS, principal variations, best-move arrow.
- Free analysis mode: play either color at will (a manual "set side to move"
  control), unlimited undo/redo, and branching — playing a new move from an
  earlier point in the line discards the old continuation, the same as any
  analysis board.
- Game management: new game, load/save PGN, load FEN from text or clipboard,
  copy FEN, reset position.
- Engine tools: Play Best Move, Hint, Show Threat (what the opponent would do
  if it were their move again), adjustable Threads/Hash/Skill Level/MultiPV/
  move time/depth, infinite-analysis toggle.
- Move-quality classification (Brilliant / Best / Excellent / Good /
  Inaccuracy / Mistake / Blunder) computed from centipawn loss as you play,
  shown as colored move-list entries and stored as PGN comments on export.
- A small offline opening-name lookup (~60 common openings) — no network
  database required.
- Optional Syzygy endgame tablebase support: point Engine Settings at a
  folder of `.rtbw`/`.rtbz` files and positions with few enough pieces show
  a perfect win/draw/loss + distance-to-zero readout in the status bar.
- Persistent settings: window layout, engine options, and display preferences
  are remembered between sessions.

## Screenshots

_Not included in this repository — run the app locally to see it in action._

## Requirements

- Python 3.10+
- A Stockfish binary (the engine itself is not bundled)
- Windows, Linux, or macOS

### Installing Stockfish

**Ubuntu / Debian:**

```bash
sudo apt install stockfish
```

**Windows:**

Download a build from [stockfishchess.org](https://stockfishchess.org/download/)
and unzip it somewhere convenient (e.g. `C:\Stockfish\stockfish.exe`). ChessLab
will also let you browse to the `.exe` directly the first time it runs if it
isn't found automatically.

**macOS:**

```bash
brew install stockfish
```

If ChessLab can't find Stockfish automatically on any platform, it will show a
dialog letting you browse to the executable, and remember your choice.

## Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/yourusername/chesslab.git
cd chesslab
pip install -r requirements.txt
```

Or install it as an editable package (adds a `chesslab` command):

```bash
pip install -e .
```

## Running

```bash
python -m chesslab
```

or, if installed as a package:

```bash
chesslab
```

## Keyboard shortcuts

| Action              | Shortcut                          |
|----------------------|-----------------------------------|
| New game             | Ctrl+N                            |
| Open PGN             | Ctrl+O                            |
| Save PGN             | Ctrl+S                            |
| Undo                 | Ctrl+Z                            |
| Redo                 | Ctrl+Shift+Z (Ctrl+Y on Windows)  |
| Copy FEN             | Ctrl+C                            |
| Paste FEN            | Ctrl+V                            |
| Start / stop analysis| Space                              |
| Flip board           | F                                  |
| Quit                 | Ctrl+Q                            |

## Project structure

```
chesslab/
  __init__.py     package metadata
  __main__.py     `python -m chesslab` entry point
  main.py         application bootstrap, logging, exception handling
  gui.py          MainWindow: menus, toolbar, docks, all signal wiring
  board.py         interactive board widget (QGraphicsView-based)
  engine.py        Stockfish/UCI integration on a dedicated asyncio thread
  analysis.py      game state, move history, PGN/FEN I/O, move classification
  panels.py        eval bar, engine-lines panel, move-list widget
  dialogs.py       promotion picker, engine-locate and settings dialogs
  pieces.py        vector piece rendering (python-chess's bundled SVG set)
  theme.py          dark stylesheet and board color palettes
  openings.py       small offline opening-name table
  tablebase.py      optional Syzygy endgame tablebase probing
  config.py         paths, persisted settings (QSettings-backed)
  utils.py          logging setup and small formatting helpers
```

### Architecture notes

- **Engine threading**: `chess.engine` is asyncio-based. `EngineManager` runs
  a private asyncio event loop on a dedicated `QThread`; all engine calls are
  scheduled onto it with `asyncio.run_coroutine_threadsafe`, and results come
  back to the GUI thread exclusively through Qt signals. The GUI thread never
  blocks on engine I/O.
- **Move history**: `GameController` keeps a linear, branchable move list
  (`moves_played`) plus a `current_ply` cursor. Undo/redo move the cursor;
  playing a new move while not at the tip of the line truncates the old
  continuation, matching how Lichess/Chess.com analysis boards branch.
- **Free analysis mode**: rather than bypassing python-chess's legality
  engine (which would make move generation meaningless), the "set side to
  move" actions simply flip `board.turn`, so the user can hand control to
  either color and always play fully legal moves for whichever side is set.
- **Pieces**: rendered from python-chess's bundled `cburnett` SVG piece set,
  so no image assets ship with the app and pieces stay crisp at any board
  size.

## Known limitations

- The opening book is a small hand-picked table, not a full ECO database —
  uncommon lines simply won't show a name.
- Move classification is a centipawn-loss heuristic computed from the live
  analysis stream, not a dedicated post-game re-analysis pass; classifying a
  move requires the engine to have reached a reasonable depth on both the
  position before and after it, which needs a moment of "thinking time"
  between moves (normal usage) rather than moves played back-to-back
  instantly.
- Syzygy tablebase support depends on you providing tablebase files
  separately (none are bundled); set the folder in Engine Settings. Files
  can be downloaded from https://tablebase.lichess.ovh/tables/standard/
  (a public mirror of the Syzygy tables) or generated yourself with the
  official Syzygy tools.

## License

MIT — see [LICENSE](LICENSE).
# ChessLab
