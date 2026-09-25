"""A fill bar (elixir, health, mana): fraction of the bar's length covered by its colour, scaled to the pack's range."""
from __future__ import annotations
import numpy as np
from .common import color_mask, crop


def read(frame, rect, r) -> float:
    img = crop(frame, rect)
    if img.size == 0:
        return 0.0
    mask = color_mask(img, r["color"], int(r.get("tol", 40)))
    axis = r.get("axis", "x")
    if axis == "x":
        per = mask.mean(axis=0) / 255.0          # per column
    else:
        per = mask.mean(axis=1)[::-1] / 255.0    # per row, bottom-up
    filled = (per > 0.3)
    # bars fill from the start: count the filled run from the origin, tolerate small gaps
    n = 0
    gap = 0
    for f in filled:
        if f:
            n += 1
            gap = 0
        else:
            gap += 1
            if gap > max(2, len(filled) // 40):
                break
            n += 1
    frac = min(1.0, n / max(1, len(filled)))
    scale = float(r.get("scale", 1))
    step = float(r.get("step", 0.1))
    return round(round(frac * scale / step) * step, 2)
