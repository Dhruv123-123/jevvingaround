from __future__ import annotations
import numpy as np
import cv2
from ..geometry import Rect


def crop(frame: np.ndarray, rect: Rect) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = rect.px(w, h)
    return frame[y0:y1, x0:x1]


def hex_to_bgr(hexstr: str) -> tuple[int, int, int]:
    s = hexstr.lstrip("#")
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return (b, g, r)


def color_mask(img: np.ndarray, hexstr: str, tol: int = 40) -> np.ndarray:
    """Pixels within `tol` (0-255, per channel, in Lab space) of a colour. Lab makes 'close enough' match how it looks."""
    target = np.uint8([[hex_to_bgr(hexstr)]])
    lab_t = cv2.cvtColor(target, cv2.COLOR_BGR2LAB)[0, 0].astype(np.int16)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.int16)
    dist = np.abs(lab - lab_t).sum(axis=2)
    return (dist <= tol * 3 // 2).astype(np.uint8) * 255


def mean_color(img: np.ndarray) -> tuple[int, int, int]:
    b, g, r = [int(v) for v in img.reshape(-1, 3).mean(axis=0)]
    return (b, g, r)


def median_color(img: np.ndarray) -> tuple[int, int, int]:
    """Robust to text and icons drawn over a flat background: the glyph is a minority of pixels."""
    b, g, r = [int(v) for v in np.median(img.reshape(-1, 3), axis=0)]
    return (b, g, r)


def nearest_named(bgr: tuple[int, int, int], options: dict[str, str]) -> tuple[str, float]:
    best, bd = "", 1e9
    src = cv2.cvtColor(np.uint8([[list(bgr)]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.int16)
    for name, hx in options.items():
        lab = cv2.cvtColor(np.uint8([[list(hex_to_bgr(hx))]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.int16)
        d = float(np.abs(lab - src).sum())
        if d < bd:
            best, bd = name, d
    return best, bd
