"""Which named colour a region is closest to. Cheap way to know which screen you are on or whose turn it is."""
from __future__ import annotations
from .common import crop, mean_color, median_color, nearest_named


def _one(img, r):
    if img.size == 0:
        return r.get("otherwise", "unknown")
    inset = float(r.get("inset", 0))
    st = r.get("stat", "median")
    if st == "accent":
        sample = accent_color(img, float(r.get("min_share", 0.03)), inset=inset)
    else:
        if inset:
            m = int(inset * min(img.shape[:2]))
            img = img[m:img.shape[0] - m, m:img.shape[1] - m]
        sample = median_color(img) if st == "median" else mean_color(img)
    name, dist = nearest_named(sample, {str(k): v for k, v in r["options"].items()})
    val = name if dist <= float(r.get("max_dist", 120)) else r.get("otherwise", "unknown")
    if r.get("parse") == "int":
        try:
            return int(val)
        except (TypeError, ValueError):
            return r.get("empty", 0)
    return val


def accent_color(img, min_share: float = 0.03, tol: int = 40, inset: float = 0.0):
    """The colour of the thing drawn on a flat background. The background is the median of the cell's border
    band (the outer 8%), which a glyph never covers; the accent is the median of the interior pixels that differ
    from it. When fewer than min_share of them differ, the cell is empty and its background is returned.
    Glyphs (X, O, a chess piece), icons and markers become colour reads this way, whatever the glyph's size."""
    import numpy as np
    import cv2
    h, w = img.shape[:2]
    b = max(1, int(0.08 * min(h, w)))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3), img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    m = int(inset * min(h, w))
    inner = img[m:h - m, m:w - m] if m else img
    px = inner.reshape(-1, 3)
    lab = cv2.cvtColor(inner, cv2.COLOR_BGR2LAB).astype(np.int16).reshape(-1, 3)
    lab_bg = cv2.cvtColor(np.uint8([[bg]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.int16)
    mask = np.abs(lab - lab_bg).sum(axis=1) > tol * 3 // 2
    if mask.mean() < min_share:
        return tuple(int(v) for v in bg)
    return tuple(int(v) for v in np.median(px[mask], axis=0))


def _grid(frame, zone, r):
    """All cells of a grid in one go: per-cell median (or mean) colour, one Lab conversion, one distance matrix.
    ~10x faster than cell-by-cell on a 12x12 board, which matters when the game moves every few hundred ms."""
    import numpy as np
    import cv2
    from .common import hex_to_bgr
    names, samples = [], []
    inset = float(r.get("inset", 0))
    for name, cr in zone.cells().items():
        img = crop(frame, cr)
        if img.size == 0:
            continue
        if inset:
            m = int(inset * min(img.shape[:2]))
            img = img[m:img.shape[0] - m, m:img.shape[1] - m]
        px = img.reshape(-1, 3)
        st = r.get("stat", "median")
        samples.append(accent_color(img, float(r.get("min_share", 0.03))) if st == "accent" else (np.median(px, axis=0) if st == "median" else px.mean(axis=0)))
        names.append(name.split(".", 1)[1])
    if not names:
        return {}
    opts = {str(k): v for k, v in r["options"].items()}
    lab_s = cv2.cvtColor(np.uint8([samples]), cv2.COLOR_BGR2LAB)[0].astype(np.int16)         # (N, 3)
    lab_o = cv2.cvtColor(np.uint8([[hex_to_bgr(h) for h in opts.values()]]), cv2.COLOR_BGR2LAB)[0].astype(np.int16)  # (K, 3)
    dist = np.abs(lab_s[:, None, :] - lab_o[None, :, :]).sum(axis=2)                          # (N, K)
    keys = list(opts.keys())
    best, bd = dist.argmin(axis=1), dist.min(axis=1)
    max_dist = float(r.get("max_dist", 120))
    out = {}
    for i, name in enumerate(names):
        val = keys[best[i]] if bd[i] <= max_dist else r.get("otherwise", "unknown")
        if r.get("parse") == "int":
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = r.get("empty", 0)
        out[name] = val
    return out


def read(frame, rect, r, zone=None):
    if zone and zone.grid:
        return _grid(frame, zone, r)
    return _one(crop(frame, rect), r)
