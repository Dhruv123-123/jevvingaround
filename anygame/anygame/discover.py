"""Online discovery of a game's state from its RAM, while it is being played: the agent's own state, never a
disassembly's map (the published one, where there is one, is the grader's).

The device hands every button press here with work RAM before and after it, and every rendered frame with RAM and
whether the screen was blank (a fade). From those alone:

  position  the byte (or little-endian pair) that rises on right and falls on left and holds on up and down: x; the
            same for down and up: y. `cell` is its typical change for one press: 1 for a tile-stepping game, the
            step in pixels for a free-moving one.
  map       the bytes that change across a transition (a blank screen, or the position jumping) and never while
            walking. Several bytes change when a map loads (its id, bank, size, script pointer); together they are
            a map's signature, and the signature is the map id the world memory keys on.

Nothing here knows any game. What it finds is a data file (`discovered.yaml`) that a later run starts from.
"""
from __future__ import annotations
import json
from typing import Any
import numpy as np

LO, HI = 0xC000, 0xE000
N = HI - LO
DIRS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


def ram(mem) -> np.ndarray:
    try:
        return np.asarray(mem[LO:HI], dtype=np.int32)
    except TypeError:
        return np.array([mem[a] for a in range(LO, HI)], dtype=np.int32)


def _wrap(d: np.ndarray) -> np.ndarray:
    return np.where(d > 127, d - 256, np.where(d < -127, d + 256, d))


class Discoverer:
    def __init__(self, min_presses: int = 10, threshold: float = 0.8):
        self.min_presses, self.threshold = min_presses, threshold
        z = lambda: np.zeros(N, np.int32)  # noqa: E731
        # per axis, per width (u8, u16le): presses on the axis, agreeing moves, any moves; presses on the other axis that left it still
        self.st = {(ax, w): {"n": 0, "agree": z(), "moved": z(), "n_other": 0, "still": z(), "steps": []} for ax in "xy" for w in (1, 2)}
        self.walk_changes = z()          # changed during a press with no transition
        self.trans_changes = z()         # changed across a transition
        self.trans_up = z()              # of those, rose by exactly one (a counter, not an id)
        self.transitions = 0
        self.blank = False
        self.before_blank: np.ndarray | None = None
        self.found: dict[str, Any] = {}
        self.fixed: dict[str, Any] = {}  # loaded from a data file: no learning needed for these

    # ---- evidence --------------------------------------------------------------------------------------
    def press(self, button: str, before: np.ndarray, after: np.ndarray) -> None:
        d = DIRS.get(button)
        jump = self._jump(before, after)
        if jump:
            self._transition(before, after)
        elif not self.blank:
            self.walk_changes += (after != before)
        if d is None or jump or self.blank:
            return
        self._last_ram = after
        d8 = _wrap(after - before)
        b16, a16 = before[:-1] + 256 * before[1:], after[:-1] + 256 * after[1:]
        d16 = np.concatenate([a16 - b16, [0]])
        for ax, want, other in (("x", d[0], d[1]), ("y", d[1], d[0])):
            for w, dd in ((1, d8), (2, d16)):
                s = self.st[(ax, w)]
                if want:
                    s["n"] += 1
                    s["agree"] += (np.sign(dd) == want)
                    s["moved"] += (dd != 0)
                elif other:
                    s["n_other"] += 1
                    s["still"] += (dd == 0)
        self._update()

    def frame(self, now: np.ndarray, blank: bool) -> None:
        """A rendered frame: a blank screen (a fade) brackets a transition."""
        if blank and not self.blank:
            self.blank, self.before_blank = True, getattr(self, "_last", now)
        elif not blank and self.blank:
            self.blank = False
            if self.before_blank is not None:
                self._transition(self.before_blank, now)
            self.before_blank = None
        self._last = now

    def _jump(self, before: np.ndarray, after: np.ndarray) -> bool:
        """The found position moved by more than three cells in one press: a door, a map edge, a warp."""
        if "x" not in self.found or "y" not in self.found:
            return False
        bx, by, ax_, ay = (self.decode(v, k) for v in (before, after) for k in ("x", "y"))
        cell = max(1, self.found.get("cell", 1))
        return abs(ax_ - bx) > 3 * cell or abs(ay - by) > 3 * cell

    def _transition(self, before: np.ndarray, after: np.ndarray) -> None:
        self.transitions += 1
        ch = after != before
        self.trans_changes += ch
        self.trans_up += ch & ((after - before) % 256 == 1)
        self._update()

    # ---- conclusions -----------------------------------------------------------------------------------
    def _axis(self, ax: str, last: np.ndarray | None = None) -> dict[str, Any] | None:
        """The best position candidate on this axis. A press into a wall moves nothing, so the score is the share of
        presses that moved the byte that moved it the right way, times the share of the other axis's presses that
        left it alone, for a byte that moved on at least a third of this axis's presses."""
        cands = []
        for w in (1, 2):
            s = self.st[(ax, w)]
            if s["n"] < self.min_presses or s["n_other"] < self.min_presses // 2:
                continue
            moved = s["moved"] / s["n"]
            score = (s["agree"] / np.maximum(s["moved"], 1)) * (s["still"] / s["n_other"]) * (moved > 0.3)
            top = float(score.max())
            if top < self.threshold:
                continue
            for i in np.where(score >= top - 0.02)[0][:16]:
                cands.append((float(score[i]), w, int(i)))
        if not cands:
            return None
        best = max(c[0] for c in cands)
        cands = [c for c in cands if c[0] >= best - 0.02]
        # a pair whose high byte stays small is a position past 255 (pixels); a byte copied into the sprite table
        # scores as well while the camera is still, so the pair wins a tie
        def pref(c):
            score, w, i = c
            hi_small = w == 2 and last is not None and i + 1 < N and last[i + 1] <= 3
            return (hi_small, w == 1, score, -i)
        score, w, i = max(cands, key=pref)
        return {"addr": LO + i, "type": "u8" if w == 1 else "u16le", "score": round(score, 3)}

    def _update(self) -> None:
        for ax in "xy":
            if ax in self.fixed:
                continue
            a = self._axis(ax, getattr(self, "_last_ram", None))
            if a:
                self.found[ax] = a
        if "x" in self.found and "cell" not in self.fixed:
            self.found["cell"] = self.found.get("cell") or 1
        if self.transitions and "map" not in self.fixed:
            cand = (self.trans_changes > 0) & (self.walk_changes == 0) & (self.trans_up < np.maximum(self.trans_changes, 2))
            for ax in "xy":                                  # the position bytes jump at a door; they are not the map
                if ax in self.found:
                    a = self.found[ax]["addr"] - LO
                    cand[a: a + (2 if self.found[ax]["type"] == "u16le" else 1)] = False
            idx = np.where(cand)[0]
            # the bytes that changed on the most transitions first; a signature of up to eight
            idx = idx[np.argsort(-self.trans_changes[idx], kind="stable")][:8]
            if len(idx):
                self.found["map"] = {"addrs": sorted(int(LO + i) for i in idx), "transitions": self.transitions}

    def learn_cell(self, deltas: list[int]) -> None:
        """Typical change of x for one press, set by the device from presses it knows moved."""
        nz = [abs(d) for d in deltas if d]
        if nz:
            self.found["cell"] = int(np.median(nz))

    def decode(self, mem: np.ndarray, key: str) -> int | None:
        f = self.found.get(key)
        if not f:
            return None
        a = f["addr"] - LO
        return int(mem[a]) if f["type"] == "u8" else int(mem[a] + 256 * mem[a + 1])

    def state(self, mem: np.ndarray) -> dict[str, Any]:
        both = "x" in self.found and "y" in self.found      # one axis alone is as likely a menu cursor as a position
        out: dict[str, Any] = {"x": self.decode(mem, "x") if both else None, "y": self.decode(mem, "y") if both else None,
                               "map": None, "cell": self.found.get("cell")}
        m = self.found.get("map")
        if m:
            sig = [int(mem[a - LO]) for a in m["addrs"]]
            out["map"] = int.from_bytes(bytes(sig), "big") % (1 << 31)
        return out

    # ---- the data file ---------------------------------------------------------------------------------
    def dump(self) -> dict[str, Any]:
        return {k: v for k, v in self.found.items()}

    def load(self, d: dict[str, Any]) -> None:
        for k in ("x", "y", "map", "cell"):
            if d.get(k):
                self.found[k] = d[k]
                self.fixed[k] = d[k]

    def summary(self) -> str:
        return json.dumps({k: ({kk: (hex(vv) if kk == "addr" else vv) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in self.found.items()})
