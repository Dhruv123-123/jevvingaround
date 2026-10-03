"""Find a game's position bytes by playing it: the general path to a RAM map for a game nobody has mapped.

Walks the player with random d-pad presses and keeps the work RAM bytes (and 16-bit pairs) whose change tracks
the presses: x goes up on right and down on left and does not move on up or down; y the same for down and up.
A press that hits a wall changes nothing, which only weakens a candidate a little. The bytes that change when x
and y jump far at once (a door, a map edge) are map-id candidates.

    anygame ramscan pyboy://game.gbc?state=overworld.state --presses 80
"""
from __future__ import annotations
import json
import random
from typing import Any
import numpy as np

WRAM = (0xC000, 0xE000)
HRAM = (0xFF80, 0xFFFF)
DIRS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


def snapshot(mem) -> np.ndarray:
    return np.array([mem[a] for a in range(*WRAM)] + [mem[a] for a in range(*HRAM)], dtype=np.int32)


def addr_of(i: int) -> int:
    n = WRAM[1] - WRAM[0]
    return WRAM[0] + i if i < n else HRAM[0] + (i - n)


def _score(deltas: np.ndarray, want: np.ndarray, other: np.ndarray) -> np.ndarray:
    """deltas: (presses, bytes) signed changes; want: +1/-1/0 per press on this axis; other: 1 where the press was
    on the other axis. A position byte moves with the sign of `want` and stays put on the other axis."""
    on = want != 0
    s = np.sign(deltas)
    agree = (s[on] == want[on][:, None]).mean(0)                    # moved the right way on this axis's presses
    still = (deltas[other.astype(bool)] == 0).mean(0) if other.any() else np.ones(deltas.shape[1])
    return agree * still


def scan(device, presses: int = 60, hold: int = 12, after: int = 24, seed: int = 0) -> dict[str, Any]:
    rng = random.Random(seed)
    mem = device.memory
    snaps = [snapshot(mem)]
    moves = []
    for _ in range(presses):
        d = rng.choice(list(DIRS))
        device.press(d, hold=hold, after=after)
        moves.append(d)
        snaps.append(snapshot(mem))
    S = np.stack(snaps)                                   # (presses+1, bytes)
    D8 = np.diff(S, axis=0)
    D8 = np.where(D8 > 127, D8 - 256, np.where(D8 < -127, D8 + 256, D8))     # wraparound
    lo, hi = S[:, :-1], S[:, 1:]
    S16 = lo + 256 * hi                                   # little-endian pairs starting at each byte
    D16 = np.diff(S16, axis=0)
    wx = np.array([DIRS[m][0] for m in moves])
    wy = np.array([DIRS[m][1] for m in moves])
    out: dict[str, Any] = {"presses": presses, "x": [], "y": []}
    for axis, want, other in (("x", wx, wy != 0), ("y", wy, wx != 0)):
        cands = []
        for width, D in ((1, D8), (2, D16)):
            sc = _score(D, want, other)
            # a byte that never moved is not a position, and a counter that moves on every press is not either
            moved = (D[want != 0] != 0).mean(0)
            sc = sc * (moved > 0.3)
            for i in np.argsort(-sc)[:8]:
                if sc[i] < 0.6:
                    break
                step = np.median(np.abs(D[want != 0][:, i][D[want != 0][:, i] != 0])) if moved[i] > 0 else 0
                cands.append({"addr": hex(addr_of(int(i))), "type": "u8" if width == 1 else "u16le", "score": round(float(sc[i]), 2),
                              "moved": round(float(moved[i]), 2), "step": int(step), "value": int(S[-1, i] if width == 1 else S16[-1, i])})
        # a u16 that only wins because its low byte does is the same candidate: keep the u8 unless the pair scores higher
        cands.sort(key=lambda c: (-c["score"], c["type"] != "u8"))
        out[axis] = cands[:6]
    return out


def main(args) -> None:
    from .device import open_device
    d = open_device(args.device, None)
    try:
        print(json.dumps(scan(d, presses=args.presses, seed=args.seed), indent=1))
    finally:
        d.close()
