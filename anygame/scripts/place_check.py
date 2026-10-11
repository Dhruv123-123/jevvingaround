"""Places named by a run's world memory, and by anygame.places, scored against the grader's map.

    python scripts/place_check.py <run>/log.jsonl [...]

For each run: how many places each names, how many grader maps it saw, and the share of reads spent in a place
that is mostly another map ("merged"). The grader's map is read only here, for scoring.
"""
from __future__ import annotations
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.places import DIRS, PlaceBook  # noqa: E402

WORD = re.compile(r"[a-z]+")


def moves_of(action: str) -> list[str]:
    """The directions an action pressed, from its log line ("walk explore_up: right up up (warp)")."""
    if not isinstance(action, str) or ":" not in action:
        return []
    body = action.split(":", 1)[1].split("→")[0]
    return [w for w in WORD.findall(body) if w in DIRS]


def score(pairs: list[tuple[object, object]]) -> dict[str, object]:
    by: dict[object, collections.Counter] = collections.defaultdict(collections.Counter)
    for truth, place in pairs:
        by[place][truth] += 1
    n = sum(sum(c.values()) for c in by.values())
    wrong = sum(sum(c.values()) - max(c.values()) for c in by.values())
    maps: dict[object, set] = collections.defaultdict(set)
    for place, c in by.items():
        for truth in c:
            maps[truth].add(place)
    return {"reads": n, "maps": len(maps), "places": len(by), "merged": round(wrong / max(n, 1), 3),
            "places_per_map": round(sum(len(v) for v in maps.values()) / max(len(maps), 1), 2)}


def replay(path: str, **kw) -> dict[str, object]:
    rows = [json.loads(line) for line in open(path)]
    book = PlaceBook(**kw)
    old, new = [], []
    for a, b in zip(rows, rows[1:]):
        s = b.get("screen") if isinstance(b.get("screen"), dict) else {}
        t = a.get("truth") or {}
        w = (s.get("world") or {}).get("here")
        if s.get("x") is None or s.get("y") is None or t.get("map") is None:
            continue
        moves = moves_of(a.get("action"))
        walking = (a.get("screen") or {}).get("screen") == "walk" and bool(moves)
        idle = str(a.get("action", "")).startswith("auto: wait")
        pid = book.see(s.get("map", 0), int(s["x"]), int(s["y"]), moves=moves, walking=walking, idle=idle)
        new.append((t["map"], pid))
        if w:
            old.append((t["map"], w["map"]))
    final = [(m, book.canonical(pid)) for m, pid in new]   # after merges: the places as the run ends up naming them
    return {"world": score(old), "placebook": score(new), "after_merges": score(final), "book": book.report()}


def main() -> None:
    for p in sys.argv[1:]:
        r = replay(p)
        name = p.split("pokemon-red/")[-1]
        print(f"{name}\n  world memory: {r['world']}\n  place book:   {r['placebook']}\n  after merges: {r['after_merges']}  {r['book']}")


if __name__ == "__main__":
    main()
