"""A learned walker: screens seen on demonstration walks, each with the step that was taken from it, and the step to
take from a new screen by its nearest demonstration screens.

Demonstrations come from anywhere (for Pokemon, the RAM fixture walker heading for an exit); at play time the walker
sees only the screen. It answers only when the screen is close to one it has seen, so it stays quiet in menus, fights
and places it was never shown.
"""
from __future__ import annotations
import glob

import numpy as np

STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")


def thumb(img: np.ndarray, k: int = 4) -> np.ndarray:
    """A native frame (rows, cols, 3) as a small grey picture, flattened."""
    g = img[:, :, :3].astype(np.float32).mean(axis=2)
    h, w = (g.shape[0] // k) * k, (g.shape[1] // k) * k
    return g[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3)).ravel()


class WalkBook:
    def __init__(self, pattern: str, near: float = 6.0, k: int = 5):
        shots, steps = [], []
        for path in sorted(p for part in pattern.split("|") for p in glob.glob(part)):   # "a*.npz|b.npz": several books
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
        # a screen seen exactly as it is now goes by the steps taken there: next to a door, the screens a step
        # away are often near enough to outvote it (a ship corridor where the stairs are one step to the side)
        exact = [i for i in idx if d[i] < 1e-3]
        for i in exact or idx:
            if d[i] <= self.near:
                votes[self.y[i]] += 1.0 / (1.0 + d[i])
        return STEPS[int(votes.argmax())], float(d[idx[0]])


def fight_view(img: np.ndarray) -> np.ndarray:
    """A fight screen for the fight book: the bottom box (messages, menus and the menu cursor) at half size, and the
    rest (the foe, the health bars) at a quarter."""
    g = img[:, :, :3].astype(np.float32).mean(axis=2)
    h, w = (g.shape[0] // 4) * 4, (g.shape[1] // 4) * 4
    cut = (h * 2 // 3) // 4 * 4
    box = g[cut:h, :w].reshape((h - cut) // 2, 2, w // 2, 2).mean(axis=(1, 3)).ravel()
    top = g[:cut, :w].reshape(cut // 4, 4, w // 4, 4).mean(axis=(1, 3)).ravel()
    return np.concatenate([box, top])


class FightBook:
    """Fight screens from demonstration fights and the press made on each (anygame scripts/pokemon_fight_demos.py for
    Pokemon); a new screen gets the press of the nearest one, when one is near. Menus differ from each other only by
    a small cursor, so it takes the single nearest screen rather than a vote."""

    def __init__(self, pattern: str, near: float = 4.0, box: bool = False):
        views, steps, prevs = [], [], []
        for path in sorted(p for part in pattern.split("|") for p in glob.glob(part)):
            d = np.load(path)
            views += [fight_view(s) for s in d["shots"]]
            steps += list(d["steps"])
            # demos may keep the press made before each screen ("prev"), so one screen can take different presses
            # (a trash can: A when just walked up to it, walk on once its message is closed)
            prevs += list(d["prev"]) if "prev" in d.files else [-1] * len(d["steps"])
        self.x = np.array(views, dtype=np.float32)
        self.y = np.array(steps, dtype=np.int64)
        self.p = np.array(prevs, dtype=np.int64)
        self.near = near
        # box: when no whole screen is near (a foe the demos never met), go by the bottom box alone (the message,
        # the menu and its cursor), for fights; a menu errand on the map needs the whole screen
        self.box = len(fight_view(np.zeros((144, 160, 3), np.uint8))) * 2 // 3 if box else 0

    def __len__(self) -> int:
        return len(self.y)

    def act(self, img: np.ndarray, prev: str | None = None, box: bool = True) -> tuple[str | None, float]:
        if not len(self.y):
            return None, float("inf")
        d = np.abs(self.x - fight_view(img)).mean(axis=1)
        if prev in STEPS:                     # demos made after the same press, or demos that kept no press
            d = np.where((self.p == STEPS.index(prev)) | (self.p < 0), d, np.inf)
        i = int(np.argmin(d))
        if d[i] > self.near and self.box and box:
            v = fight_view(img)[: self.box]
            db = np.abs(self.x[:, : self.box] - v).mean(axis=1)
            j = int(np.argmin(db))
            if db[j] <= self.near:
                return STEPS[self.y[j]], float(db[j])
        return (STEPS[self.y[i]] if d[i] <= self.near else None), float(d[i])
