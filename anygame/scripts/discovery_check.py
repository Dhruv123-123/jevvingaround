"""How well did the agent discover its state? Reads a run's log (anygame play ... --log) on a ROM a grader knows and
compares what the agent found (screen.x/y/map) with the grader's truth beside each tick (truth.x/y/map).

    python3 scripts/discovery_check.py run/log.jsonl
"""
import collections
import json
import sys

rs = [json.loads(l) for l in open(sys.argv[1])]
rs = [r for r in rs if r.get("truth") and r.get("screen")]
known = [r for r in rs if r["screen"].get("x") is not None]
print(f"ticks {len(rs)}, position known on {len(known)} ({len(known) / max(1, len(rs)):.0%})")
# position: between consecutive ticks on the same true map, does the found x/y move when the true one does?
agree = total = 0
for a, b in zip(known, known[1:]):
    if a["truth"]["map"] != b["truth"]["map"]:
        continue
    for k in ("x", "y"):
        t = (b["truth"][k] - a["truth"][k]) != 0
        f = (b["screen"][k] - a["screen"][k]) != 0
        agree += t == f
        total += 1
print(f"position moves with the truth on {agree}/{total} axis-steps ({agree / max(1, total):.0%})")
by_map = collections.defaultdict(set)
for r in rs:
    if r["screen"].get("map"):
        by_map[r["truth"]["map"]].add(r["screen"]["map"])
sigs = collections.defaultdict(set)
for m, ss in by_map.items():
    for s in ss:
        sigs[s].add(m)
print(f"true maps {len(by_map)}, signatures {len(sigs)}; per true map: " + ", ".join(f"{m}: {len(s)}" for m, s in sorted(by_map.items())))
print(f"signatures shared by more than one true map: {sum(1 for s in sigs.values() if len(s) > 1)}")
