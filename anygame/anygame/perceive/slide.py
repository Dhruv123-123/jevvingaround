"""The 2048 compiler: a 4x4 grid of numbers becomes the four swipes, each simulated exactly and ranked by an
expectimax search over the random tile that spawns after it. Jev picks a swipe from that ranked, annotated list.

Same pattern as the Tetris compiler (enumerate, simulate, present the top few): a swipe that does not move the board
is never offered, and every offered swipe carries its consequences (points merged, empty cells after, whether the
largest tile stays in its corner) plus its rank.

Read config:  { kind: slide, in: <grid read>, depth: 2, corner: c4r4 }
              depth = swipes searched (1 = this swipe and the spawn after it; 2 = also our best reply to that spawn)
Value:        { legal: [swipes, best first], best: <swipe>|none, ranked: {swipe: "#1 best: …", …}, empty: n, max: n,
                max_in_corner: bool }
"""
from __future__ import annotations
from functools import lru_cache
from typing import Any

DIRS = ("up", "down", "left", "right")
CORNERS = {"c1r1": (0, 0), "c4r1": (0, 3), "c1r4": (3, 0), "c4r4": (3, 3)}


def _slide_row(row: tuple[int, ...]) -> tuple[tuple[int, ...], int]:
    t = [x for x in row if x]
    out: list[int] = []
    gain = 0
    i = 0
    while i < len(t):
        if i + 1 < len(t) and t[i] == t[i + 1]:
            out.append(t[i] * 2)
            gain += t[i] * 2
            i += 2
        else:
            out.append(t[i])
            i += 1
    return tuple(out + [0] * (4 - len(out))), gain


def move(g: tuple[int, ...], d: str) -> tuple[tuple[int, ...], int]:
    """(grid after the swipe, points merged); row-major, row 0 at the top, exactly as games/2048.html slides."""
    nb = [0] * 16
    gain = 0
    for k in range(4):
        if d == "left":
            idx = [k * 4 + m for m in range(4)]
        elif d == "right":
            idx = [k * 4 + 3 - m for m in range(4)]
        elif d == "up":
            idx = [m * 4 + k for m in range(4)]
        else:
            idx = [(3 - m) * 4 + k for m in range(4)]
        line, s = _slide_row(tuple(g[i] for i in idx))
        gain += s
        for i, v in zip(idx, line):
            nb[i] = v
    return tuple(nb), gain


def _weights(corner: tuple[int, int]) -> tuple[float, ...]:
    """A snake of powers of four anchored at the corner: the largest tile there, the chain winding back along the edge."""
    order: list[tuple[int, int]] = []
    for i, r in enumerate(range(3, -1, -1)):
        cols = range(3, -1, -1) if i % 2 == 0 else range(4)
        order += [(r, c) for c in cols]
    w = [0.0] * 16
    for n, (r, c) in enumerate(order):
        rr = r if corner[0] == 3 else 3 - r
        cc = c if corner[1] == 3 else 3 - c
        w[rr * 4 + cc] = 4.0 ** (15 - n) / 4.0 ** 10
    return tuple(w)


def _score(g: tuple[int, ...], w: tuple[float, ...]) -> float:
    empty = sum(1 for v in g if v == 0)
    snake = sum(v * wi for v, wi in zip(g, w))
    return snake + 64.0 * empty


@lru_cache(maxsize=200_000)
def _best(g: tuple[int, ...], depth: int, w: tuple[float, ...]) -> float:
    """The value of the best swipe from g, searching `depth` swipes; a board with no legal swipe is lost."""
    best = None
    for d in DIRS:
        ng, gain = move(g, d)
        if ng == g:
            continue
        v = _chance(ng, depth - 1, w) + gain
        best = v if best is None or v > best else best
    return -1e9 if best is None else best


def _chance(g: tuple[int, ...], depth: int, w: tuple[float, ...]) -> float:
    """Expected value over the tile the game spawns (a 2 nine times in ten, else a 4, on a uniform empty cell)."""
    empties = [i for i, v in enumerate(g) if v == 0]
    if not empties:
        return _score(g, w) if depth <= 0 else _best(g, depth, w)
    if depth <= 0:
        return _score(g, w)
    total = 0.0
    for i in empties:
        for tile, p in ((2, 0.9), (4, 0.1)):
            ng = g[:i] + (tile,) + g[i + 1:]
            total += p * _best(ng, depth, w)
    return total / len(empties)


def grid_of(src: Any) -> tuple[int, ...] | None:
    """Row-major 16-tuple from a {c<col>r<row>: n} read (or a flat list of 16)."""
    if isinstance(src, (list, tuple)) and len(src) == 16:
        return tuple(int(v or 0) for v in src)
    if not isinstance(src, dict):
        return None
    g = [0] * 16
    for k, v in src.items():
        try:
            c, r = k[1:].split("r")
            g[(int(r) - 1) * 4 + int(c) - 1] = int(v or 0)
        except (ValueError, IndexError):
            return None
    return tuple(g)


def rank(g: tuple[int, ...], depth: int = 2, corner: str = "c4r4") -> dict[str, Any]:
    cr = CORNERS.get(corner, (3, 3))
    w = _weights(cr)
    top = max(g) if g else 0
    rows = []
    for d in DIRS:
        ng, gain = move(g, d)
        if ng == g:
            continue
        value = _chance(ng, depth - 1, w) + gain
        rows.append((value, d, gain, sum(1 for v in ng if v == 0), ng[cr[0] * 4 + cr[1]] == top and top > 0))
    rows.sort(key=lambda x: -x[0])
    _best.cache_clear()
    ranked: dict[str, str] = {}
    for n, (_v, d, gain, empty, anchored) in enumerate(rows):
        tag = "#1 best" if n == 0 else f"#{n + 1}"
        corner_txt = "largest tile stays in the corner" if anchored else "largest tile NOT in the corner"
        ranked[d] = f"{tag}: merges +{gain}, {empty} empty after, {corner_txt}"
    return {"legal": [r[1] for r in rows], "best": rows[0][1] if rows else "none", "ranked": ranked,
            "empty": sum(1 for v in g if v == 0), "max": top, "max_in_corner": top > 0 and g[cr[0] * 4 + cr[1]] == top}


def slide_of(src: Any, r: dict[str, Any]) -> dict[str, Any] | None:
    g = grid_of(src)
    if g is None:
        return None
    return rank(g, int(r.get("depth", 2)), str(r.get("corner", "c4r4")))
