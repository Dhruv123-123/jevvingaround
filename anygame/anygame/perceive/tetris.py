"""The Tetris compiler: a frame's grid becomes the falling piece, the stack's shape, and a short list of
landings with their consequences computed. Jev chooses a landing; the loop plays it as a key macro.

This is the general pattern for a game with a small action set and a cheap world model: enumerate the
candidates, simulate each one exactly, present the top few as a typed choice. `runs` in Connect Four is the
one-line version; this is the full one.

Read config:  { kind: tetris, in: <grid read>, next_in: <preview grid read>, empty: ".", top_k: 6,
                moves_per_row: 3, keys: { rotate: ArrowUp, left: ArrowLeft, right: ArrowRight, drop: Space } }
Value:        { phase: spawned|falling|none, shape, rot, col, row, next, stack: {…}, landings: {a: "…", …},
                reachable_only: bool, last_placement: ok|missed|null }
"""
from __future__ import annotations
import re
from typing import Any

# SRS shapes as (dx, dy) offsets from the piece origin, per rotation; identical to games/tetris.html
SHAPES: dict[str, list[list[tuple[int, int]]]] = {
    "I": [[(0, 1), (1, 1), (2, 1), (3, 1)], [(2, 0), (2, 1), (2, 2), (2, 3)], [(0, 2), (1, 2), (2, 2), (3, 2)], [(1, 0), (1, 1), (1, 2), (1, 3)]],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]] * 4,
    "T": [[(1, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (2, 1), (1, 2)], [(0, 1), (1, 1), (2, 1), (1, 2)], [(1, 0), (0, 1), (1, 1), (1, 2)]],
    "S": [[(1, 0), (2, 0), (0, 1), (1, 1)], [(1, 0), (1, 1), (2, 1), (2, 2)], [(1, 1), (2, 1), (0, 2), (1, 2)], [(0, 0), (0, 1), (1, 1), (1, 2)]],
    "Z": [[(0, 0), (1, 0), (1, 1), (2, 1)], [(2, 0), (1, 1), (2, 1), (1, 2)], [(0, 1), (1, 1), (1, 2), (2, 2)], [(1, 0), (0, 1), (1, 1), (0, 2)]],
    "J": [[(0, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (2, 0), (1, 1), (1, 2)], [(0, 1), (1, 1), (2, 1), (2, 2)], [(1, 0), (1, 1), (0, 2), (1, 2)]],
    "L": [[(2, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (1, 2), (2, 2)], [(0, 1), (1, 1), (2, 1), (0, 2)], [(0, 0), (1, 0), (1, 1), (1, 2)]],
}
UNIQUE_ROTS = {"I": [0, 1], "O": [0], "T": [0, 1, 2, 3], "S": [0, 1], "Z": [0, 1], "J": [0, 1, 2, 3], "L": [0, 1, 2, 3]}
LABELS = "abcdefghij"


def _norm(cells: set[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    mx, my = min(c for c, _ in cells), min(r for _, r in cells)
    return frozenset((c - mx, r - my) for c, r in cells)


_SHAPE_INDEX: dict[frozenset[tuple[int, int]], list[tuple[str, int]]] = {}
for _s, _rots in SHAPES.items():
    for _r, _offs in enumerate(_rots):
        _SHAPE_INDEX.setdefault(_norm(set(_offs)), []).append((_s, _r))


def identify(cells: set[tuple[int, int]]) -> tuple[str, int, int, int] | None:
    """(shape, rot, x, y) for four cells, or None. Prefers rotation 0 (a fresh spawn) when shapes coincide."""
    if len(cells) != 4:
        return None
    key = _norm(cells)
    cands = _SHAPE_INDEX.get(key)
    if not cands:
        return None
    s, r = sorted(cands, key=lambda sr: sr[1])[0]
    offs = SHAPES[s][r]
    mx, my = min(c for c, _ in cells), min(rr for _, rr in cells)
    ox, oy = min(dx for dx, _ in offs), min(dy for _, dy in offs)
    return s, r, mx - ox, my - oy


def grid_cells(src: dict[str, Any] | list[str], empty: str) -> tuple[set[tuple[int, int]], int, int]:
    """Filled (col, row) cells, 0-based, from a {c<col>r<row>: value} read or a list of row strings; plus (W, H)."""
    filled: set[tuple[int, int]] = set()
    if isinstance(src, list):
        for r, row in enumerate(src):
            for c, ch in enumerate(row):
                if ch != empty:
                    filled.add((c, r))
        return filled, (len(src[0]) if src else 0), len(src)
    w = h = 0
    for k, v in src.items():
        m = re.match(r"c(\d+)r(\d+)$", k)
        if not m:
            continue
        c, r = int(m.group(1)) - 1, int(m.group(2)) - 1
        w, h = max(w, c + 1), max(h, r + 1)
        if str(v) != empty:
            filled.add((c, r))
    return filled, w, h


def features(stack: set[tuple[int, int]], w: int, h: int) -> dict[str, Any]:
    heights = []
    for c in range(w):
        col = [r for cc, r in stack if cc == c]
        heights.append(h - min(col) if col else 0)
    holes = 0
    for c in range(w):
        top = h - heights[c]
        holes += sum(1 for r in range(top + 1, h) if (c, r) not in stack)
    bump = sum(abs(heights[i] - heights[i + 1]) for i in range(w - 1))
    well_col, well_depth = -1, 0
    for c in range(w):
        left = heights[c - 1] if c > 0 else 99
        right = heights[c + 1] if c < w - 1 else 99
        d = min(left, right) - heights[c]
        if d > well_depth:
            well_col, well_depth = c, d
    return {"heights": heights, "max_height": max(heights) if heights else 0, "holes": holes, "bumpiness": bump,
            "well_col": well_col + 1 if well_col >= 0 else None, "well_depth": well_depth, "sum_height": sum(heights)}


def drop(stack: set[tuple[int, int]], shape: str, rot: int, x: int, w: int, h: int) -> tuple[set[tuple[int, int]], int] | None:
    """Cells where the piece lands when dropped from the top at origin x; None if it does not fit at all."""
    offs = SHAPES[shape][rot]
    if any(not (0 <= x + dx < w) for dx, _ in offs):
        return None
    y = -min(dy for _, dy in offs) - 1
    last = None
    while True:
        cells = {(x + dx, y + dy) for dx, dy in offs}
        if any(r >= h or (c, r) in stack for c, r in cells if r >= 0) or any(r >= h for _, r in cells):
            break
        last = (cells, y)
        y += 1
    if last is None or any(r < 0 for _, r in last[0]):
        return None
    return last


def settle(stack: set[tuple[int, int]], cells: set[tuple[int, int]], w: int, h: int) -> tuple[set[tuple[int, int]], int]:
    """Lock the cells into the stack and clear full rows. Returns (new stack, lines cleared)."""
    s = set(stack) | cells
    full = sorted({r for _, r in s if all((c, r) in s for c in range(w))})
    if not full:
        return s, 0
    out: set[tuple[int, int]] = set()
    for c, r in s:
        if r in full:
            continue
        shift = sum(1 for fr in full if fr > r)
        out.add((c, r + shift))
    return out, len(full)


def score(base: dict[str, Any], after: dict[str, Any], lines: int) -> float:
    """A plain placement heuristic (Dellacherie-flavoured) used only to rank candidates for the model."""
    return (0.76 * lines - 0.51 * after["sum_height"] - 0.36 * after["holes"] - 0.18 * after["bumpiness"]
            - 1.5 * max(0, after["holes"] - base["holes"]))


class TetrisTracker:
    """Per-run state: which cells are the settled stack, which piece we have seen, what we predicted."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.keys = {"rotate": "ArrowUp", "left": "ArrowLeft", "right": "ArrowRight", "drop": "Space", **(cfg.get("keys") or {})}
        self.top_k = int(cfg.get("top_k", 6))
        self.moves_per_row = float(cfg.get("moves_per_row", 3))
        self.last_piece: tuple[str, int, int] | None = None   # (shape, x, y) seen last tick
        self.piece_seq = 0
        self.macros: dict[str, list[str]] = {}
        self.predicted: set[tuple[int, int]] | None = None
        self.settled: set[tuple[int, int]] | None = None     # the stack as we expect it after our last placement
        self.lines_cleared = 0                                # exact, from confirmed placements; no OCR needed
        self._pending_lines = 0
        self.last_placement: str | None = None

    def read(self, board: Any, preview: Any) -> dict[str, Any]:
        empty = str(self.cfg.get("empty", "."))
        filled, w, h = grid_cells(board, empty)
        self._w, self._h = w, h
        nxt = None
        if preview is not None:
            pc, _, _ = grid_cells(preview, empty)
            ident = identify(pc) if len(pc) == 4 else None
            nxt = ident[0] if ident else None
        # the falling piece. First choice: whatever is filled beyond the stack we expect after our last placement
        # (works even when the new piece spawns touching a tall stack). Fallback: the topmost 4-connected
        # component that is a lone tetromino (works with no history, e.g. on a fixture).
        active: set[tuple[int, int]] | None = None
        ident = None
        expected = self.settled          # the stack we predicted after our last placement, before this frame overwrites it
        if expected is not None and expected <= filled:
            extra = filled - expected
            if len(extra) == 4 and identify(extra):
                active, ident = extra, identify(extra)
        if active is None:
            comps = _components(filled)
            comps.sort(key=lambda comp: min(r for _, r in comp))
            for comp in comps:
                if len(comp) == 4:
                    ident = identify(comp)
                    if ident:
                        active = comp
                break   # the topmost component is not a lone tetromino and history did not help: wait a tick
        stack = filled - (active or set())
        if active is not None:
            self.settled = stack
        feats = features(stack, w, h)
        out: dict[str, Any] = {"phase": "none", "shape": None, "rot": None, "col": None, "row": None, "next": nxt,
                               "stack": {k: v for k, v in feats.items() if k != "heights"} | {"danger": feats["max_height"] >= h - 6},
                               "landings": {}, "last_placement": self.last_placement, "lines_cleared": self.lines_cleared}
        out["last_placement"] = None
        if self.predicted is not None and active is not None:
            # the piece landed where we said if the stack we expected (after line clears) is what we see under the new piece
            self.last_placement = "ok" if (expected is not None and expected == filled - active) else "missed"
            out["last_placement"] = self.last_placement
            if self.last_placement == "ok":
                self.lines_cleared += self._pending_lines
            self._pending_lines = 0
            self.predicted = None
            if self.last_placement == "missed":
                self.settled = None        # our model of the stack is wrong: rebuild it from the frame
        if not ident or active is None:
            self.macros = {}
            return out
        shape, rot, x, y = ident
        key = (shape, x, y)
        if self.last_piece is None or self.last_piece[0] != shape or y < self.last_piece[2] or self.last_piece[2] - y > 4:
            self.piece_seq += 1
            phase = "spawned"
        else:
            phase = "falling"
        self.last_piece = key
        out.update({"phase": phase, "shape": shape, "rot": rot, "col": x + 1, "row": y + 1})
        # how many rows this piece still has to fall straight down: the budget for horizontal moves and rotations
        straight = drop(stack, shape, rot, x, w, h)
        rows_left = (straight[1] - y) if straight else 0
        cands = []
        for r2 in UNIQUE_ROTS[shape]:
            offs = SHAPES[shape][r2]
            for x2 in range(-min(dx for dx, _ in offs), w - max(dx for dx, _ in offs)):
                landed = drop(stack, shape, r2, x2, w, h)
                if not landed:
                    continue
                cells, _ = landed
                new_stack, lines = settle(stack, cells, w, h)
                after = features(new_stack, w, h)
                rots = (r2 - rot) % 4
                moves = rots + abs(x2 - x)
                reachable = moves <= rows_left * self.moves_per_row + 1
                well_kept = feats["well_col"] is None or all(c != feats["well_col"] - 1 for c, _ in cells) or lines > 0
                cands.append({"rot": r2, "x": x2, "cells": cells, "lines": lines, "holes": after["holes"] - feats["holes"],
                              "height": after["max_height"], "bump": after["bumpiness"], "well_kept": well_kept, "reachable": reachable,
                              "score": score(feats, after, lines), "rots": rots, "dx": x2 - x})
        reach = [c for c in cands if c["reachable"]] or cands
        reach.sort(key=lambda c: -c["score"])
        self.macros = {}
        for i, c in enumerate(reach[: self.top_k]):
            lab = LABELS[i]
            desc = (f"rot{c['rot']} col{c['x'] + 1}: clears {c['lines']}, holes {c['holes']:+d}, height {c['height']}, "
                    f"bumpiness {c['bump']}, {'keeps well' if c['well_kept'] else 'FILLS the well'}")
            out["landings"][lab] = desc
            keys = [self.keys["rotate"]] * c["rots"] + [self.keys["left"] if c["dx"] < 0 else self.keys["right"]] * abs(c["dx"]) + [self.keys["drop"]]
            self.macros[lab] = keys
            c["label"] = lab
        out["lines_cleared"] = self.lines_cleared
        out["reachable_only"] = all(c["reachable"] for c in reach[: self.top_k])
        out["rows_left"] = rows_left
        self._cands = {c.get("label"): c for c in reach[: self.top_k]}
        return out

    def predict(self, label: str) -> None:
        """Called after the macro is sent: remember where the piece should land and what the stack becomes."""
        c = getattr(self, "_cands", {}).get(label)
        self.predicted = set(c["cells"]) if c else None
        self._pending_lines = int(c["lines"]) if c else 0
        if c and self.settled is not None:
            self.settled, _ = settle(self.settled, set(c["cells"]), self._w, self._h)


def _components(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    seen: set[tuple[int, int]] = set()
    comps = []
    for start in sorted(cells, key=lambda cr: (cr[1], cr[0])):
        if start in seen:
            continue
        comp, todo = set(), [start]
        while todo:
            c, r = todo.pop()
            if (c, r) in seen or (c, r) not in cells:
                continue
            seen.add((c, r))
            comp.add((c, r))
            todo += [(c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)]
        comps.append(comp)
    return comps
