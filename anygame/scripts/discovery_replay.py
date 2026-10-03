"""Replay a recorded discovery trace (ANYGAME_DISCOVER_TRACE=<file> anygame play ...) through the current
discover.py and score it against a grader's RAM map: whether the found position moves with the true one, and how
many map signatures each true map got. Seconds instead of a fresh run, so changes to discovery can be compared.

    python3 scripts/discovery_replay.py trace.bin aevilia
"""
import collections
import pickle
import sys
import zlib

import numpy as np

from anygame.discover import Discoverer, LO, _unz

trace = pickle.loads(zlib.decompress(open(sys.argv[1], "rb").read()))
game = sys.argv[2] if len(sys.argv) > 2 else "aevilia"
if game == "aevilia":
    from anygame.graders.aevilia import W_LOADED_MAP as M, W_X as X, W_Y as Y
else:
    from anygame.graders.pokemon_red import W_CUR_MAP as M, W_X as X, W_Y as Y


class Mem:
    def __init__(self, a):
        self.a = a

    def __getitem__(self, i):
        return int(self.a[i - LO])


d = Discoverer()
rows = []
for ev in trace:
    if ev[0] == "p":
        d.press(ev[1], _unz(ev[2]), _unz(ev[3]), *(ev[4:5] or [True]))
    else:
        now = _unz(ev[2])
        d.frame(now, ev[1])
        if not ev[1]:
            rows.append((now, d.state(now)))
truth = lambda m: (m[M - LO], m[X - LO] | m[X + 1 - LO] << 8 if game == "aevilia" else m[X - LO], m[Y - LO] | m[Y + 1 - LO] << 8 if game == "aevilia" else m[Y - LO])  # noqa: E731
print("found", d.summary(), "transitions", d.transitions)
# as the run went (what the world memory saw), and with what was known by the end
for label, states in (("as it went", [s for _, s in rows]), ("final", [d.state(m) for m, _ in rows])):
    by_map, agree, total = collections.defaultdict(set), 0, 0
    prev = None
    for (m, _), s in zip(rows, states):
        t = truth(m)
        if s["map"] is not None:
            by_map[t[0]].add(s["map"])
        if prev and s["x"] is not None and prev[1]["x"] is not None and prev[0][0] == t[0]:
            for k, i in (("x", 1), ("y", 2)):
                agree += ((t[i] - prev[0][i]) != 0) == ((s[k] - prev[1][k]) != 0)
                total += 1
        prev = (t, s)
    sigs = collections.defaultdict(set)
    for tm, ss in by_map.items():
        for x in ss:
            sigs[x].add(tm)
    print(f"{label}: position moves with the truth {agree}/{total} ({agree / max(1, total):.0%}); true maps {len(by_map)}, signatures {len(sigs)} "
          f"({', '.join(f'{k}: {len(v)}' for k, v in sorted(by_map.items()))}); shared {sum(1 for v in sigs.values() if len(v) > 1)}")
if len(sys.argv) > 3:
    for a in sys.argv[3].split(","):
        i = int(a, 16) - LO
        print(hex(LO + i), "near", d.near[i], "changes", d.changes[i], "ups", d.ups[i], "distinct", d.values[:, i].sum())
if "--cands" in sys.argv:
    cand = (d.near >= 1) & (d.near >= 0.8 * d.changes) & (d.ups < 0.5 * d.changes)
    idx = np.where(cand)[0]
    idx = idx[np.argsort(-d.near[idx])][:25]
    for i in idx:
        vals = np.where(d.values[:, i])[0].tolist()
        print(hex(LO + i), "near", d.near[i], "changes", d.changes[i], "values", vals[:8])
