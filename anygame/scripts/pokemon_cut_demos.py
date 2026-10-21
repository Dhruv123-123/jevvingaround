"""Cut demos for a learned menu book (anygame/walk_book.py's FightBook): from a save standing next to a small tree and
facing it, open the start menu, pick POKEMON, the first party member and CUT, then A through the messages (a RAM test
helper like pokemon_nurse_demos.py: RAM finds the menu cursors here; the agent sees only the screens). Each run starts
the start-menu cursor somewhere else, so the book sees the menu from every row, and most runs first open a wrong row
and back out of it with B.

    python scripts/pokemon_cut_demos.py STATE OUT.npz RUNS
"""
import io
import os
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
CURSOR, TEXT = 0xCC26, 0xC4F2
pb = PyBoy("/mnt/project-files/roms/pokemon-red.gb", window="null", sound_emulated=False)
pb.load_state(open(sys.argv[1], 'rb')); pb.tick(30); m = pb.memory
start = io.BytesIO(); pb.save_state(start); start = start.getvalue()
shots, steps = [], []


def step(b, rec=True):
    before = pb.screen.ndarray[:, :, :3].copy()
    press(pb, b, after=40)
    if rec:
        shots.append(before); steps.append(STEPS.index(b))
    return (pb.screen.ndarray[:, :, :3] != before).any()


tree = m[0xD362], m[0xD361]
for r in range(int(sys.argv[3])):
    pb.load_state(io.BytesIO(start)); pb.tick(1 + r * 7)
    step("start", rec=False)                                  # leave the start-menu cursor on row r first (not shown)
    for _ in range(r % 7): step("down", rec=False)
    step("b", rec=False)
    if r % 4:                                                  # turned away from the tree (as a walk book arrives
        step(("down", "left", "down")[r % 4 - 1], rec=False)    # stepping down): face it first
        if (m[0xD362], m[0xD361]) != tree:
            print("moved"); continue
        step("right")
    step("start")
    if r % 6 in (0, 2, 3, 5):                                           # a wrong row picked first (as a slow menu draw can make
        for _ in range(8):                                     # the book press A too soon): B back out of it
            if m[CURSOR] == r % 6: break
            step("up" if m[CURSOR] > r % 6 else "down", rec=False)
        step("a", rec=False)
        step("b")                                              # one B is back on the start menu from any of these rows
    for _ in range(8):
        if m[CURSOR] == 1: break
        step("up" if m[CURSOR] > 1 else "down")
    step("a")                                                  # POKEMON
    for _ in range(6):
        if m[CURSOR] == 0: break
        step("up")
    step("a")                                                  # first party member
    for _ in range(4):
        if m[CURSOR] == 0: break
        step("up")
    step("a")                                                  # CUT, the first field move
    for k in range(20):                                        # A through the messages until the field is back
        if not step("a") and k > 3: shots.pop(); steps.pop(); break
    print("run", r, "steps", len(steps), "at", m[0xD35E], m[0xD362], m[0xD361])
np.savez_compressed(sys.argv[2], shots=np.array(shots), steps=np.array(steps, dtype=np.uint8))
