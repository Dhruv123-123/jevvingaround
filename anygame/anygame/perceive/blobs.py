"""Colour blobs: connected components of a named colour inside a zone, reported by cell. The no-model way to see
'red things' and 'blue things' on a field; what the vocab detector falls back to on cartoon sprites."""
from __future__ import annotations
import numpy as np
import cv2
from .common import color_mask, crop


def read(frame, rect, zone, r):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = rect.px(w, h)
    img = frame[y0:y1, x0:x1]
    min_area = int(r.get("min_area", 60))
    out: dict[str, list[dict]] = {}
    dets = []
    for side, hexstr in (r.get("colors") or {}).items():
        mask = color_mask(img, hexstr, int(r.get("tol", 40)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        items = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            cx, cy = cents[i]
            nx, ny = (x0 + cx) / w, (y0 + cy) / h
            cell = zone.cell_of(nx, ny) if zone else None
            size = "small" if area < min_area * 4 else "medium" if area < min_area * 16 else "large"
            items.append({"cell": cell.split(".", 1)[1] if cell else None, "size": size})
            bx, by, bw, bh = [int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT)]
            dets.append({"label": f"{side}", "conf": 1.0, "rect": (x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh)})
        out[side] = items[: int(r.get("max", 20))]
    return out, dets
