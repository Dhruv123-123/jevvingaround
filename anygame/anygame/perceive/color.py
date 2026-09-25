"""Which named colour a region is closest to. Cheap way to know which screen you are on or whose turn it is."""
from __future__ import annotations
from .common import crop, mean_color, median_color, nearest_named


def _one(img, r):
    if img.size == 0:
        return r.get("otherwise", "unknown")
    inset = float(r.get("inset", 0))
    if inset:
        m = int(inset * min(img.shape[:2]))
        img = img[m:img.shape[0] - m, m:img.shape[1] - m]
    stat = median_color if r.get("stat", "median") == "median" else mean_color
    name, dist = nearest_named(stat(img), {str(k): v for k, v in r["options"].items()})
    val = name if dist <= float(r.get("max_dist", 120)) else r.get("otherwise", "unknown")
    if r.get("parse") == "int":
        try:
            return int(val)
        except (TypeError, ValueError):
            return r.get("empty", 0)
    return val


def read(frame, rect, r, zone=None):
    if zone and zone.grid:
        return {name.split(".", 1)[1]: _one(crop(frame, cr), r) for name, cr in zone.cells().items()}
    return _one(crop(frame, rect), r)
