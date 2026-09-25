from __future__ import annotations
import numpy as np


class Device:
    """Frames in, taps out. Coordinates on the way in are pixels of the frame this device returns."""

    def size(self) -> tuple[int, int]:
        raise NotImplementedError

    def frame(self) -> np.ndarray:
        """BGR uint8 array, shape (h, w, 3)."""
        raise NotImplementedError

    def tap(self, x: int, y: int) -> None:
        raise NotImplementedError

    def swipe(self, x0: int, y0: int, x1: int, y1: int, ms: int = 120) -> None:
        raise NotImplementedError

    def key(self, name: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} has no keys")

    def close(self) -> None:
        pass
