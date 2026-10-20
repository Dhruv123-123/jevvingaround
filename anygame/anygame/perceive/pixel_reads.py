"""Cheap reads from pixels, every frame, with no model: gauges (an HP bar, a timer) and a menu cursor.

Both are found by shape, not by any game's layout, so the same rules run on every game:

- A gauge is a thin band (1 to 3 rows) between two long dark lines that span the same columns, the outline every
  bar is drawn with. Its fill is how much of the band, from the left, is not the screen's lightest shade.
- A cursor is the one small thing that moved when a d-pad button was pressed on a screen where nothing else did:
  the press made at most two small blobs of change (where it was, where it is).
"""
from __future__ import annotations

import cv2
import numpy as np


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def _runs(row: np.ndarray, minlen: int) -> list[tuple[int, int]]:
    """(start, end) of each run of True at least `minlen` long."""
    padded = np.concatenate(([False], row, [False])).astype(np.int8)
    d = np.diff(padded)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s >= minlen]


def _side(d: np.ndarray, y0: int, y1: int, x: int, reach: int = 4, near: int = 4) -> bool:
    """Every one of `reach` rows past the band, above or below, is dark somewhere within `near` columns of x: the side
    of a box. A box's double border is two lines with a light band between, like an empty gauge, but both its ends
    run on as the box's sides."""
    lo, hi = max(0, x - near), min(d.shape[1], x + near + 1)
    up = d[max(0, y0 - reach):y0, lo:hi]
    down = d[y1 + 1:y1 + 1 + reach, lo:hi]
    return any(len(p) == reach and p.any(axis=1).all() for p in (up, down))


def gauges(img: np.ndarray, minlen: int = 24, dark: int = 60) -> list[dict]:
    """Every outlined bar on the screen: {"x", "y", "w", "fill"} (fill 0..1 from the left), top to bottom."""
    g = _gray(img)
    d = g < dark
    h, _ = d.shape
    light = int(g.max())
    lines = {y: _runs(d[y], minlen) for y in range(h)}
    out, used = [], set()
    for y in range(h):
        for s, e in lines[y]:
            if (y, s) in used:
                continue
            for k in range(2, 5):              # the band between the lines: 1 to 3 rows
                if y + k >= h:
                    break
                match = next(((s2, e2) for s2, e2 in lines[y + k] if abs(s2 - s) <= 2 and abs(e2 - e) <= 3), None)
                if match is None:
                    continue
                inner = g[y + 1:y + k, s + 1:max(s, e - 1)]
                if inner.size == 0 or (inner < dark).mean() > 0.5:
                    break                      # a filled block or two text lines, not a bar
                if _side(d, y, y + k, s) and _side(d, y, y + k, e - 1):
                    break                      # a box's double border: both its sides run on past the band
                filled = (inner < light).any(axis=0)
                # the fill is the run from the left; a bar has no gaps in its fill
                n = int(np.argmin(filled)) if not filled.all() else filled.size
                out.append({"x": s, "y": y, "w": e - s, "fill": round(n / filled.size, 2)})
                used.add((y + k, match[0]))
                break
    return out


def cursor(before: np.ndarray, after: np.ndarray, max_side: int = 8, max_blobs: int = 3) -> tuple[int, int] | None:
    """Where a cursor moved to, from the frames either side of a d-pad press: the centre (x, y) of the pixels drawn
    dark by the press inside the narrowest blob of change (a cursor is at most a tile wide; a menu redrawing its
    other text makes wider blobs). None if the change was not a few small things."""
    a, b = _gray(before).astype(np.int16), _gray(after).astype(np.int16)
    diff = (np.abs(a - b) > 30).astype(np.uint8)
    if not diff.any() or diff.mean() > 0.02:
        return None
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(diff, np.ones((3, 3), np.uint8)), connectivity=8)
    if not 1 <= n - 1 <= max_blobs:
        return None
    thin = [i for i in range(1, n) if stats[i, 2] <= max_side + 2]
    for i in sorted(thin, key=lambda i: stats[i, 2]):
        ys, xs = np.nonzero((lab == i) & (diff > 0) & (b < 128))     # what the press drew, not what it erased
        if len(xs):
            return int(xs.mean()), int(ys.mean())
    return None
