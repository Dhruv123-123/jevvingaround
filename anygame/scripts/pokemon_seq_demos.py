"""Demos of a fixed press sequence for a learned menu book (anygame/walk_book.py's FightBook), for an errand that
always starts from the same door, such as Bill's cottage: each press that changed the screen is kept with the screen
before it. A test helper like pokemon_nurse_demos.py; the agent sees only the screens.

    python scripts/pokemon_seq_demos.py STATE OUT.npz RUNS "u2 r3 r a40 w5 l4 u a8 w5 b4 w3 r2 u r a40"
    (a letter is the button (u d l r a b s for start), the number how many presses; w waits that many seconds)
"""
import io
import os
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
KEYS = {"u": "up", "d": "down", "l": "left", "r": "right", "a": "a", "b": "b", "s": "start"}
pb = PyBoy("/mnt/project-files/roms/pokemon-red.gb", window="null", sound_emulated=False)
pb.load_state(open(sys.argv[1], 'rb')); pb.tick(30)
start = io.BytesIO(); pb.save_state(start); start = start.getvalue()
shots, steps = [], []
for r in range(int(sys.argv[3])):
    pb.load_state(io.BytesIO(start)); pb.tick(1 + r * 7)
    for t in sys.argv[4].split():
        k, n = t[0], int(t[1:] or 1)
        for _ in range(n):
            if k == "w":
                pb.tick(60)
                continue
            before = pb.screen.ndarray[:, :, :3].copy()
            press(pb, KEYS[k], hold=16 if k in "udlr" else 6, after=40)
            if (pb.screen.ndarray[:, :, :3] != before).any():
                shots.append(before); steps.append(STEPS.index(KEYS[k]))
    print("run", r, "steps", len(steps))
np.savez_compressed(sys.argv[2], shots=np.array(shots), steps=np.array(steps, dtype=np.uint8))
