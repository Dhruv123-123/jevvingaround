"""Vermilion Gym demos for a learned menu book (anygame/walk_book.py's FightBook with the press made before each screen):
search the trash cans one by one, row by row, so each can tried is next to the one before (the second switch is always
next to the first), until both electric locks open; then walk to Lt. Surge and talk to him. A RAM rule plays it (grader
side, a test helper like pokemon_fight_demos.py); each press is saved with its screen and the press before it, which is
all the book needs to tell "just walked up to this can" (A) from "just read what was in it" (walk on). Fights are
played out by the RAM helper and not recorded (the fight book has those).

    python scripts/pokemon_gym_demos.py STATE OUT.npz RUNS
"""
from __future__ import annotations
import collections
import io
import os
import random
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

ROM = "/mnt/project-files/roms/pokemon-red.gb"
STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
MAP, X, Y, BATTLE, LOCKS, BADGES = 0xD35E, 0xD362, 0xD361, 0xD057, 0xD773, 0xD356
GYM = 92
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
CANS = [(x, 7) for x in (1, 3, 5, 7, 9)] + [(x, 9) for x in (9, 7, 5, 3, 1)] + [(x, 11) for x in (1, 3, 5, 7, 9)]
SURGE = ((5, 2), "up")


def main() -> None:
    state, out, runs = sys.argv[1], sys.argv[2], int(sys.argv[3])
    pb = PyBoy(ROM, window="null", sound_emulated=False)
    with open(state, "rb") as f:
        pb.load_state(f)
    pb.tick(60)
    m = pb.memory
    rng = random.Random(2)

    def snap():
        b = io.BytesIO()
        pb.save_state(b)
        return b.getvalue()

    def screen():
        return pb.screen.ndarray[:, :, :3].copy()

    def fight():
        k = 0
        while m[BATTLE] and k < 2000:
            m[0xD16C], m[0xD16D] = m[0xD18D], m[0xD18E]          # healed (test helper)
            press(pb, "a", after=24)
            k += 1

    # the squares one can stand on (squares where a trainer sees you are left out)
    def squares():
        here = snap()
        seen, todo = {(m[X], m[Y]): here}, collections.deque([here])
        while todo:
            s = todo.popleft()
            for d in DIRS:
                pb.load_state(io.BytesIO(s))
                press(pb, d, after=20)
                if m[MAP] == GYM and not m[BATTLE] and (m[X], m[Y]) not in seen:
                    seen[(m[X], m[Y])] = snap()
                    todo.append(seen[(m[X], m[Y])])
        pb.load_state(io.BytesIO(here))
        return set(seen)

    start = snap()
    walk = squares()
    shut = set(walk)

    def path(a, b):
        par, q = {a: None}, collections.deque([a])
        while q and b not in par:
            p = q.popleft()
            for d, (dx, dy) in DIRS.items():
                n = (p[0] + dx, p[1] + dy)
                if n in walk and n not in par:
                    par[n] = (p, d)
                    q.append(n)
        steps = []
        while par.get(b):
            b, d = par[b]
            steps.append(d)
        return steps[::-1]

    # where to stand for each can: next to it, the nearest from the spot before
    stands, at = [], (m[X], m[Y])
    for c in CANS:
        opts = [((c[0] - dx, c[1] - dy), d) for d, (dx, dy) in DIRS.items() if (c[0] - dx, c[1] - dy) in walk]
        sq, d = min(opts, key=lambda o: len(path(at, o[0])))
        stands.append((sq, d))
        at = sq
    print("stands", stands, flush=True)

    shots, steps, prevs = [], [], []
    last = ["b"]

    def rec(b, after=24):
        shots.append(screen())
        steps.append(STEPS.index(b))
        prevs.append(STEPS.index(last[0]))
        last[0] = b
        press(pb, b, after=after)
        if b in DIRS:
            settle()

    def settle():                    # a fight (not recorded); the demos start with the gym's trainers beaten
        if m[BATTLE]:
            fight()
            read()

    def read():            # close the messages, a press at a time while the screen changes (twice still: done)
        still = 0
        for _ in range(16):
            pb.tick(30)
            before = screen()
            press(pb, "b", after=30)
            pb.tick(10)
            if not (screen() != before).any():
                still += 1
                if still == 2:
                    break
                continue
            still = 0
            shots.append(before)
            steps.append(STEPS.index("b"))
            prevs.append(STEPS.index(last[0]))
            last[0] = "b"

    def go(target):                                    # a step at a time, the way there worked out again each time
        for _ in range(40):
            way = path((m[X], m[Y]), target)
            if not way:
                return
            rec(way[0])

    won = 0
    for r in range(runs):
        pb.load_state(io.BytesIO(start))
        walk = shut
        for _ in range(rng.randrange(60)):             # another moment, so other switches (not recorded)
            pb.tick(1)
        k = rng.randrange(len(CANS))
        for _ in range(120):
            if m[BADGES] & 4:
                break
            if m[LOCKS] & 1:                           # both locks open: to Lt. Surge
                walk = squares()
                go(SURGE[0])
                print("at", m[X], m[Y], "of", len(walk), "squares", flush=True)
                rec(SURGE[1])
                rec("a")
                for _ in range(30):                    # through his talk into the fight, and the badge after
                    if m[BATTLE]:
                        fight()
                        read()
                    if m[BADGES] & 4:
                        break
                    rec("a", after=40)
                read()
                pb.screen.image.save(out + f".surge{r}.png")
                break
            sq, d = stands[k]
            go(sq)
            if (m[X], m[Y]) != sq:
                print("lost at", m[MAP], m[X], m[Y], "heading for", sq, "battle", m[BATTLE], flush=True)
                pb.screen.image.save(out + f".lost{r}.png")
                break
            rec(d)                                     # turn to the can (or bump it)
            rec("a")
            read()
            k = (k + 1) % len(CANS)
        won += bool(m[BADGES] & 4)
        print("run", r, "badge", bool(m[BADGES] & 4), "locks", hex(m[LOCKS]), "presses", len(steps), flush=True)
    np.savez_compressed(out, shots=np.array(shots), steps=np.array(steps, dtype=np.uint8),
                        prev=np.array(prevs, dtype=np.uint8))
    print("recorded", len(steps), "presses in", won, "of", runs, "badge runs to", out)


if __name__ == "__main__":
    main()
