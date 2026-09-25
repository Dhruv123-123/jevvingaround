"""Numbers and short text via RapidOCR (ONNX, CPU). Per cell when the zone has a grid."""
from __future__ import annotations
import re
import numpy as np
import cv2
from .common import crop

_engine = None


def engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _text(img: np.ndarray, upscale: float = 2.0) -> str:
    if img.size == 0:
        return ""
    if upscale != 1:
        img = cv2.resize(img, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    res, _ = engine()(img)
    if not res:
        return ""
    return " ".join(t[1] for t in res).strip()


def _parse(text: str, r):
    p = r.get("parse")
    if p == "int":
        m = re.findall(r"\d+", text.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("S", "5"))
        return int("".join(m)) if m else r.get("empty", 0)
    return text


def read(frame, rect, zone, r):
    if zone and zone.grid:
        # one OCR pass over the whole zone, then assign each text box to the cell its centre falls in
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = rect.px(w, h)
        img = frame[y0:y1, x0:x1]
        up = float(r.get("upscale", 1.5))
        big = cv2.resize(img, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up != 1 else img
        res, _ = engine()(big)
        out = {name.split(".", 1)[1]: r.get("empty", 0) if r.get("parse") == "int" else "" for name in zone.cells()}
        for box, text, conf in (res or []):
            cx = (sum(pt[0] for pt in box) / 4) / up + x0
            cy = (sum(pt[1] for pt in box) / 4) / up + y0
            cell = zone.cell_of(cx / w, cy / h)
            if cell:
                out[cell.split(".", 1)[1]] = _parse(text, r)
        return out
    return _parse(_text(crop(frame, rect), float(r.get("upscale", 2))), r)
