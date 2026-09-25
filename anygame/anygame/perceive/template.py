"""Template matching against crops the pack author pasted in (assets/*.png). Exact and ~5 ms; ideal for fixed UI
such as cards in hand, buttons, icons. A grid zone yields one label per cell."""
from __future__ import annotations
import glob
import os
from functools import lru_cache
import numpy as np
import cv2
from .common import crop


@lru_cache(maxsize=32)
def _assets(pattern: str) -> tuple[tuple[str, np.ndarray], ...]:
    out = []
    for f in sorted(glob.glob(pattern)):
        img = cv2.imread(f, cv2.IMREAD_COLOR)
        if img is not None:
            out.append((os.path.splitext(os.path.basename(f))[0], img))
    return tuple(out)


def _best(cell: np.ndarray, assets, threshold: float):
    best, bs = None, -1.0
    for label, a in assets:
        # scale the asset to the cell width (packs are authored on one screen size; cells scale uniformly)
        scale = cell.shape[1] / a.shape[1]
        t = cv2.resize(a, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if t.shape[0] > cell.shape[0] or t.shape[1] > cell.shape[1]:
            t = t[: cell.shape[0], : cell.shape[1]]
        res = cv2.matchTemplate(cell, t, cv2.TM_CCOEFF_NORMED)
        s = float(res.max()) if res.size else -1.0
        if s > bs:
            best, bs = label, s
    return (best if bs >= threshold else None), round(bs, 3)


def read(frame, rect, zone, r, assets_dir):
    assets = _assets(os.path.join(str(assets_dir), r["assets"]))
    thr = float(r.get("threshold", 0.6))
    dets = []
    if zone and zone.grid:
        out = {}
        h, w = frame.shape[:2]
        for name, cr in zone.cells().items():
            label, score = _best(crop(frame, cr), assets, thr)
            out[name.split(".", 1)[1]] = label
            if label:
                dets.append({"label": label, "conf": score, "rect": cr.px(w, h)})
        return out, dets
    label, score = _best(crop(frame, rect), assets, thr)
    if label:
        dets.append({"label": label, "conf": score, "rect": rect.px(*frame.shape[1::-1])})
    return label, dets
