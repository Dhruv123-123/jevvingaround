"""Structural fingerprints: a 16x16 Lab grid of the frame, so "which screen is this" is a nearest-neighbour
lookup in microseconds. Same layout and encoding as the extension (ext/src/core/fingerprint.ts), so packs
carry fingerprints that both runtimes read."""
from __future__ import annotations
import base64
import numpy as np
import cv2

SIDE = 16


def fingerprint(frame: np.ndarray) -> np.ndarray:
    """uint8[SIDE*SIDE*3]: L, a, b per cell (OpenCV 8-bit Lab), from a BGR frame."""
    small = cv2.resize(frame, (SIDE, SIDE), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    return lab.reshape(-1).astype(np.uint8)


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean Lab distance per cell: ~0 same frame, <25 same layout, >40 a different screen."""
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).sum()) / (len(a) / 3)


def to_b64(fp: np.ndarray) -> str:
    return base64.b64encode(fp.tobytes()).decode()


def from_b64(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.uint8)


class Index:
    def __init__(self, threshold: float = 40.0):
        self.threshold = threshold
        self.entries: list[tuple[str, np.ndarray]] = []

    def add(self, name: str, fp: np.ndarray | str) -> None:
        self.entries.append((name, from_b64(fp) if isinstance(fp, str) else fp))

    def nearest(self, fp: np.ndarray) -> tuple[str, float] | None:
        best = None
        for name, e in self.entries:
            if len(e) != len(fp):
                continue
            d = distance(e, fp)
            if best is None or d < best[1]:
                best = (name, d)
        return best

    def known(self, fp: np.ndarray) -> tuple[str, float] | None:
        n = self.nearest(fp)
        return n if n and n[1] <= self.threshold else None
