"""A small, local opening-name lookup.

ChessLab works fully offline, so rather than depending on an external ECO
database this ships a compact table of common openings keyed by their
initial SAN move sequence. It covers the openings a club player is most
likely to encounter; anything outside the table simply shows no name,
which is preferable to a network dependency for a local analysis tool.
"""

from __future__ import annotations

# Ordered from longest to shortest match is handled at lookup time, so entries
# can be added in any order. Keys are space-joined SAN sequences from the
# starting position (no move numbers).
OPENING_BOOK: dict[str, str] = {
    "e4": "King's Pawn Opening",
    "e4 e5": "Open Game",
    "e4 e5 Nf3": "King's Knight Opening",
    "e4 e5 Nf3 Nc6": "Italian / Spanish complex",
    "e4 e5 Nf3 Nc6 Bb5": "Ruy Lopez",
    "e4 e5 Nf3 Nc6 Bc4": "Italian Game",
    "e4 e5 Nf3 Nc6 Bc4 Bc5": "Italian Game: Giuoco Piano",
    "e4 e5 Nf3 Nc6 Bb5 a6": "Ruy Lopez: Morphy Defense",
    "e4 e5 Nf3 Nf6": "Petrov's Defense",
    "e4 e5 Nc3": "Vienna Game",
    "e4 e5 Bc4": "Bishop's Opening",
    "e4 e5 f4": "King's Gambit",
    "e4 c5": "Sicilian Defense",
    "e4 c5 Nf3": "Sicilian Defense",
    "e4 c5 Nf3 d6": "Sicilian Defense: Najdorf complex",
    "e4 c5 Nf3 Nc6": "Sicilian Defense: Open",
    "e4 c5 Nf3 e6": "Sicilian Defense: Taimanov / Kan complex",
    "e4 c5 c3": "Sicilian Defense: Alapin Variation",
    "e4 c5 Nc3": "Sicilian Defense: Closed",
    "e4 e6": "French Defense",
    "e4 e6 d4 d5": "French Defense",
    "e4 c6": "Caro-Kann Defense",
    "e4 c6 d4 d5": "Caro-Kann Defense",
    "e4 d5": "Scandinavian Defense",
    "e4 d6": "Pirc Defense",
    "e4 g6": "Modern Defense",
    "e4 Nf6": "Alekhine's Defense",
    "d4": "Queen's Pawn Opening",
    "d4 d5": "Closed Game",
    "d4 d5 c4": "Queen's Gambit",
    "d4 d5 c4 e6": "Queen's Gambit Declined",
    "d4 d5 c4 c6": "Slav Defense",
    "d4 d5 c4 dxc4": "Queen's Gambit Accepted",
    "d4 Nf6": "Indian Defense",
    "d4 Nf6 c4": "Indian Defense",
    "d4 Nf6 c4 g6": "King's Indian / Grunfeld complex",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6": "King's Indian Defense",
    "d4 Nf6 c4 g6 Nc3 d5": "Grunfeld Defense",
    "d4 Nf6 c4 e6": "Indian Defense: East Indian complex",
    "d4 Nf6 c4 e6 Nc3 Bb4": "Nimzo-Indian Defense",
    "d4 Nf6 c4 e6 Nf3 b6": "Queen's Indian Defense",
    "d4 f5": "Dutch Defense",
    "d4 g6": "Modern Defense (via 1.d4)",
    "c4": "English Opening",
    "c4 e5": "English Opening: Reversed Sicilian",
    "c4 Nf6": "English Opening",
    "Nf3": "Reti Opening",
    "Nf3 d5": "Reti Opening",
    "Nf3 Nf6": "Reti Opening: Symmetrical",
    "f4": "Bird's Opening",
    "b3": "Nimzo-Larsen Attack",
    "g3": "King's Fianchetto Opening",
}


def lookup_opening(san_moves: list[str]) -> str | None:
    """Return the deepest matching opening name for a SAN move sequence."""
    best: str | None = None
    for length in range(min(len(san_moves), 8), 0, -1):
        key = " ".join(san_moves[:length])
        if key in OPENING_BOOK:
            best = OPENING_BOOK[key]
            break
    return best
