"""Design-review probe: find a Game Boy game's position bytes with no knowledge of the ROM, then time exact lookahead.

1. Boot the ROM and press random buttons until play has started (`--warmup` presses).
2. Press random directions and diff work RAM (0xC000-0xDFFF) around each press. A byte that rises on right and
   falls on left, and does not move on up or down, is an x coordinate; the same for y. Scores near 2.0 are clean.
3. From that state, try all four directions from a save state and restore it (exact lookahead from the emulator
   itself), and time it.

    python scripts/review_ram_probe.py /mnt/project-files/roms/homebrew/aevilia.gbc
"""
from __future__ import annotations
import argparse
import io
import json
import random
import time
import numpy as np

BUTTONS = ["a", "b", "start", "select", "up", "down", "left", "right"]
DIRS = ["up", "down", "left", "right"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--probes", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    from pyboy import PyBoy
    rng = random.Random(a.seed)
    pb = PyBoy(a.rom, window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    pb.tick(240, render=False)

    def press(b: str) -> None:
        pb.button_press(b)
        pb.tick(6, render=False)
        pb.button_release(b)
        pb.tick(24, render=False)

    def ram() -> np.ndarray:
        return np.array(pb.memory[0xC000:0xE000], dtype=np.int16)

    for _ in range(a.warmup):
        press(rng.choice(BUTTONS))
    deltas, labels = [], []
    for _ in range(a.probes):
        b = rng.choice(DIRS)
        r0 = ram()
        press(b)
        deltas.append(ram() - r0)
        labels.append(b)
    D, L = np.array(deltas), np.array(labels)
    moved = (D != 0).sum(0) >= 10
    m = {d: L == d for d in DIRS}
    sx = np.where(moved, (D[m["right"]] > 0).mean(0) + (D[m["left"]] < 0).mean(0) - (D[m["up"]] != 0).mean(0) - (D[m["down"]] != 0).mean(0), -9)
    sy = np.where(moved, (D[m["down"]] > 0).mean(0) + (D[m["up"]] < 0).mean(0) - (D[m["left"]] != 0).mean(0) - (D[m["right"]] != 0).mean(0), -9)
    xa, ya = 0xC000 + int(np.argmax(sx)), 0xC000 + int(np.argmax(sy))
    out = {"x_candidates": [(hex(0xC000 + j), round(float(sx[j]), 2)) for j in np.argsort(-sx)[:3]],
           "y_candidates": [(hex(0xC000 + j), round(float(sy[j]), 2)) for j in np.argsort(-sy)[:3]]}
    times, branches = [], None
    for _ in range(30):
        t0 = time.perf_counter()
        s = io.BytesIO()
        pb.save_state(s)
        res = {}
        for b in DIRS:
            s.seek(0)
            pb.load_state(s)
            press(b)
            res[b] = (pb.memory[xa], pb.memory[ya])
        s.seek(0)
        pb.load_state(s)
        times.append((time.perf_counter() - t0) * 1000)
        branches = branches or {"from": (pb.memory[xa], pb.memory[ya]), **res}
        press(rng.choice(DIRS))
    out["lookahead_4_branches_ms_median"] = round(float(np.median(times)), 1)
    out["state_bytes"] = len(s.getvalue())
    out["example_branches"] = branches
    pb.stop(save=False)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
