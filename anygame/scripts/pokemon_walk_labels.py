"""Relabel walk demos with the shortest way out: every step that moved in any demo is an edge between two squares;
from each square, the step on a shortest path to the exit squares (the northernmost ones seen, by default) is its
label. Writes one book of (screen, best step) for anygame/walk_book.py. Grader-side RAM positions are used only here.

    python scripts/pokemon_walk_labels.py 'DEMOS/*.npz' OUT.npz [exit: north|south|east|west, [MAP:]X,Y:SIDE for one square and the step out of it, or MAP to
    end on entering that map]; squares are (map, x, y), and a step through a door joins two maps
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
    nxt: dict = collections.defaultdict(set)         # square (map, x, y) -> {(step, next square)}
    for path in sorted(glob.glob(pattern)):
        d = np.load(path)
        rows = list(zip(d["shots"], d["steps"], d["where"]))
        for i, (s, a, w) in enumerate(rows):
            m, x, y = (int(v) for v in w)
            dx, dy = D[int(a)]
            n = (m, x + dx, y + dy)
            after = rows[i + 1][2] if i + 1 < len(rows) else d["end"] if "end" in d else None
            if after is not None and int(after[0]) != m:       # a step through a door to another map
                n = tuple(int(v) for v in after)
            elif after is not None:
                ax, ay = int(after[1]) - x, int(after[2]) - y
                if (ax, ay) in ((dx, dy), (2 * dx, 2 * dy)):
                    n = tuple(int(v) for v in after)    # where the step really led: one square, or a jump down a ledge
                elif (ax, ay) != (0, 0) and abs(ax) + abs(ay) <= 3:
                    n = None                # the next row is not where this step went (presses in between were not
                                            # recorded, a fight, a wander): no edge, rather than a wrong one
            if n is not None:
                nxt[(m, x, y)].add((int(a), n))
            shots.append(s)
            wheres.append((m, x, y))
    cells = set(nxt) | {c for v in nxt.values() for _, c in v}
    out_step = None
    if side.isdigit():                  # entering a map ends the way: the squares with a step into it
        goal = sorted({c for c, outs in nxt.items() for _, n in outs if n[0] == int(side)} | {c for c in cells if c[0] == int(side)})
    elif ":" in side:                   # one exit square and the step out of it: 13,26:north or MAP:13,26:north
        *where, side = side.split(":")
        xy = tuple(int(v) for v in where[-1].split(","))
        goal = [c for c in cells if c[1:] == xy and (len(where) == 1 or c[0] == int(where[0]))]
        out_step = {"north": 0, "south": 1, "west": 2, "east": 3}[side]
    else:
        key = {"north": lambda c: c[2], "south": lambda c: -c[2], "west": lambda c: c[1], "east": lambda c: -c[1]}[side]
        best = min(key(c) for c in cells)
        goal = [c for c in cells if key(c) == best]
        out_step = {"north": 0, "south": 1, "west": 2, "east": 3}[side]
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
    keep_s, keep_a = [], []
    for s, w in zip(shots, wheres):
        if w in dist and dist[w] == 0 and out_step is not None:   # on an exit square: step out through the exit
            keep_s.append(s)
            keep_a.append(out_step)
            continue
        opts = [(dist.get(n, 10 ** 9), a) for a, n in nxt.get(w, ())]
        if opts and min(opts)[0] < 10 ** 9 and w in dist and dist[w] > 0:
            keep_s.append(s)
            keep_a.append(min(opts)[1])
    np.savez_compressed(out, shots=np.array(keep_s), steps=np.array(keep_a, dtype=np.uint8))
    print(f"{len(keep_s)} of {len(shots)} screens labelled; {len(dist)} of {len(cells)} squares reach the exit "
          f"({len(goal)} exit squares, longest way {max(dist.values())} steps)")


if __name__ == "__main__":
    main()
