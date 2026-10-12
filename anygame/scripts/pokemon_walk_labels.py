"""Relabel walk demos with the shortest way out: every step that moved in any demo is an edge between two squares;
from each square, the step on a shortest path to the exit squares (the northernmost ones seen, by default) is its
label. Writes one book of (screen, best step) for anygame/walk_book.py. Grader-side RAM positions are used only here.

    python scripts/pokemon_walk_labels.py 'DEMOS/*.npz' OUT.npz [exit: north|south|east|west, or X,Y:SIDE for one square and the step out of it]
"""
from __future__ import annotations
import collections
import glob
import sys

import numpy as np

D = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}


def main() -> None:
    pattern, out = sys.argv[1], sys.argv[2]
    side = sys.argv[3] if len(sys.argv) > 3 else "north"
    shots, wheres = [], []
    nxt: dict = collections.defaultdict(set)
    for path in sorted(glob.glob(pattern)):
        d = np.load(path)
        for s, a, w in zip(d["shots"], d["steps"], d["where"]):
            _, x, y = (int(v) for v in w)
            dx, dy = D[int(a)]
            nxt[(x, y)].add((int(a), (x + dx, y + dy)))
            shots.append(s)
            wheres.append((x, y))
    cells = set(nxt) | {c for v in nxt.values() for _, c in v}
    spot = None
    if ":" in side:                     # one exit square, e.g. a door: 13,26:north
        xy, side = side.split(":")
        spot = tuple(int(v) for v in xy.split(","))
    key = {"north": lambda c: c[1], "south": lambda c: -c[1], "west": lambda c: c[0], "east": lambda c: -c[0]}[side]
    best = min(key(c) for c in cells)
    goal = [spot] if spot else [c for c in cells if key(c) == best]
    back: dict = collections.defaultdict(set)
    for c, outs in nxt.items():
        for _, n in outs:
            back[n].add(c)
    dist = {c: 0 for c in goal}
    todo = collections.deque(goal)
    while todo:
        c = todo.popleft()
        for p in back[c]:
            if p not in dist:
                dist[p] = dist[c] + 1
                todo.append(p)
    out_step = {"north": 0, "south": 1, "west": 2, "east": 3}[side]
    keep_s, keep_a = [], []
    for s, w in zip(shots, wheres):
        if w in goal:                   # on an exit square: step out through the exit
            keep_s.append(s)
            keep_a.append(out_step)
            continue
        opts = [(dist.get(n, 10 ** 9), a) for a, n in nxt.get(w, ())]
        if opts and min(opts)[0] < 10 ** 9 and w in dist:
            keep_s.append(s)
            keep_a.append(min(opts)[1])
    np.savez_compressed(out, shots=np.array(keep_s), steps=np.array(keep_a, dtype=np.uint8))
    print(f"{len(keep_s)} of {len(shots)} screens labelled; {len(dist)} of {len(cells)} squares reach the exit "
          f"({len(goal)} exit squares, longest way {max(dist.values())} steps)")


if __name__ == "__main__":
    main()
