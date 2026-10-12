"""A learned walker: screens seen on demonstration walks, each with the step that was taken from it, and the step to
take from a new screen by its nearest demonstration screens.

Demonstrations come from anywhere (for Pokemon, the RAM fixture walker heading for an exit); at play time the walker
sees only the screen. It answers only when the screen is close to one it has seen, so it stays quiet in menus, fights
and places it was never shown.
"""
from __future__ import annotations
import glob

import numpy as np

STEPS = ("up", "down", "left", "right")


def thumb(img: np.ndarray, k: int = 4) -> np.ndarray:
    """A native frame (rows, cols, 3) as a small grey picture, flattened."""
    g = img[:, :, :3].astype(np.float32).mean(axis=2)
    h, w = (g.shape[0] // k) * k, (g.shape[1] // k) * k
    return g[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3)).ravel()


class WalkBook:
    def __init__(self, pattern: str, near: float = 6.0, k: int = 5):
        shots, steps = [], []
        for path in sorted(glob.glob(pattern)):
            d = np.load(path)
            shots += [thumb(s) for s in d["shots"]]
            steps += list(d["steps"])
        self.x = np.array(shots, dtype=np.float32)
        self.y = np.array(steps, dtype=np.int64)
        self.near, self.k = near, k        # mean grey difference per pixel (0-255) for "the same screen"

    def __len__(self) -> int:
        return len(self.y)

    def act(self, img: np.ndarray) -> tuple[str | None, float]:
        """The step most of the nearest demonstration screens took, and the nearest distance; None when no
        demonstration screen is near."""
        if not len(self.y):
            return None, float("inf")
        d = np.abs(self.x - thumb(img)).mean(axis=1)
        idx = np.argsort(d)[: self.k]
        if d[idx[0]] > self.near:
            return None, float(d[idx[0]])
        votes = np.zeros(len(STEPS))
        for i in idx:
            if d[i] <= self.near:
                votes[self.y[i]] += 1.0 / (1.0 + d[i])
        return STEPS[int(votes.argmax())], float(d[idx[0]])
