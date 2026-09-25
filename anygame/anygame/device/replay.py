"""Frames from a folder, taps to a log. For pack tests and for developing perception without a phone."""
from __future__ import annotations
import glob
import os
import cv2
from .base import Device


class ReplayDevice(Device):
    def __init__(self, folder: str):
        self.files = sorted(glob.glob(os.path.join(folder, "*.png")) + glob.glob(os.path.join(folder, "*.jpg")))
        if not self.files:
            raise ValueError(f"no frames in {folder}")
        self.i = 0
        self.actions: list[tuple] = []
        first = cv2.imread(self.files[0])
        self._size = (first.shape[1], first.shape[0])

    def size(self):
        return self._size

    def frame(self):
        f = cv2.imread(self.files[min(self.i, len(self.files) - 1)])
        self.i += 1
        return f

    @property
    def exhausted(self) -> bool:
        return self.i >= len(self.files)

    def tap(self, x, y):
        self.actions.append(("tap", x, y))

    def swipe(self, x0, y0, x1, y1, ms=120):
        self.actions.append(("swipe", x0, y0, x1, y1))

    def key(self, name):
        self.actions.append(("key", name))
