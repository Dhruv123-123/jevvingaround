"""How well cut_between tells a scene change from a scroll: random walks from save states, each step's frames before
and after, scored against the grader's map change (read here only, for scoring).

    python scripts/cut_check.py <rom> <state> [--steps 300] [--seed 0]
"""
from __future__ import annotations
import argparse
import collections
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("state")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    from anygame.device.pyboy import PyBoyDevice
    from anygame.graders import for_rom
    from anygame.places import cut_between
    d = PyBoyDevice(f"pyboy://{a.rom}?state={a.state}")
    g = for_rom(a.rom)
    rnd = random.Random(a.seed)
    g.update(d.memory)
    m0 = g.last.get("map")
    table = collections.Counter()
    run: list[str] = []
    for _ in range(a.steps):
        before = d.screen().copy()
        if not run:                             # a direction kept for a few steps explores further than a coin flip
            run = [rnd.choice(["up", "down", "left", "right", "a"])] * rnd.randint(1, 6)
        k = run.pop()
        d.press(k, hold=16, after=40)
        g.update(d.memory)
        m1 = g.last.get("map")
        cut = cut_between(before, d.screen())
        table[(f"map {m0}->{m1}" if m1 != m0 else "same map", "cut" if cut else "no cut")] += 1
        m0 = m1
    for k, v in sorted(table.items()):
        print(f"  {k[0]:14s} {k[1]:7s} {v}")


if __name__ == "__main__":
    main()
