"""Nurse demos for a learned menu book (anygame/walk_book.py's FightBook): from a save standing below a Pokemon Center
nurse and facing her, hurt the first party member, then A through the healing and B out of the last message (a RAM
test helper like pokemon_menu_demos.py; the agent sees only the screens). Centers look alike, so one save serves all.

    python scripts/pokemon_nurse_demos.py STATE OUT.npz RUNS
"""
import io
import os
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
pb = PyBoy("/mnt/project-files/roms/pokemon-red.gb", window="null", sound_emulated=False)
pb.load_state(open(sys.argv[1], 'rb')); pb.tick(30); m = pb.memory
start = io.BytesIO(); pb.save_state(start); start = start.getvalue()
shots, steps, prevs = [], [], []
for r in range(int(sys.argv[3])):
    pb.load_state(io.BytesIO(start)); pb.tick(1 + r * 7)
    m[0xD16C], m[0xD16D] = 0, 5 + r * 4                      # hurt (test helper)
    last = "up"
    for k in range(40):
        full = m[0xD16C] * 256 + m[0xD16D] == m[0xD18D] * 256 + m[0xD18E]
        b = "a" if not full else "b"
        before = pb.screen.ndarray[:, :, :3].copy()
        press(pb, b, after=40)
        if full and not (pb.screen.ndarray[:, :, :3] != before).any():
            break
        shots.append(before); steps.append(STEPS.index(b)); prevs.append(STEPS.index(last)); last = b
    print("run", r, "healed", full, len(steps))
np.savez_compressed(sys.argv[2], shots=np.array(shots), steps=np.array(steps, dtype=np.uint8))
