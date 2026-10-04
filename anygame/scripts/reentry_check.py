"""Going back somewhere needs the place book to know it when it gets there. For each read that enters a grader map
the run has been on before, is the place the book names one it named on that map before (known again), or a new
one? Replayed from a run's logs with and without door memory. The grader's map is read only for scoring.

    python scripts/reentry_check.py <log.jsonl> [...]
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.places import PlaceBook  # noqa: E402
from place_check import moves_of  # noqa: E402


def reentries(path: str, looks: bool = True, **kw) -> tuple[int, int, int]:
    rows = [json.loads(line) for line in open(path)]
    book = PlaceBook(**kw)
    named: dict = {}
    last_map, back, known = None, 0, 0
    for a, b in zip(rows, rows[1:]):
        s = b.get("screen") if isinstance(b.get("screen"), dict) else {}
        t = (b.get("truth") or {}).get("map")
        if s.get("x") is None or s.get("y") is None or t is None:
            continue
        moves = moves_of(a.get("action"))
        walking = (a.get("screen") or {}).get("screen") == "walk" and bool(moves)
        idle = str(a.get("action", "")).startswith("auto: wait")
        look = bytes.fromhex(b["print"]) if looks and b.get("print") else None
        pid = book.canonical(book.see(s.get("map", 0), int(s["x"]), int(s["y"]), moves=moves, walking=walking, idle=idle,
                                      look=look))
        if t != last_map and t in named:
            back += 1
            known += any(book.canonical(p) == pid for p in named[t])
        named.setdefault(t, set()).add(pid)
        last_map = t
    return back, known, sum(1 for p in book.places if p.merged_into is None)


def main() -> None:
    ways = {"before": dict(remember_doors=False, looks=False), "doors": dict(remember_doors=True, looks=False),
            "doors+looks": dict(remember_doors=True, looks=True)}
    tot = {k: [0, 0] for k in ways}
    for p in sys.argv[1:]:
        line = [p.split("/")[-2] + "/" + p.split("/")[-1]]
        for name, kw in ways.items():
            back, known, places = reentries(p, **kw)
            tot[name][0] += back
            tot[name][1] += known
            line.append(f"{name}: {known}/{back} known again, {places} places")
        print("  ".join(line))
    for name, (b, k) in tot.items():
        print(f"{name}: {k}/{b} re-entries known again ({k / max(b, 1):.0%})")


if __name__ == "__main__":
    main()
