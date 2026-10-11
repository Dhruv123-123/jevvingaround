"""Names heard at places (anygame/landmarks.py) from a run's log, scored against the grader's map.

    python scripts/landmark_check.py <log.jsonl> [...]

Each distinct line on screen is filed under the place the world memory was in (the last known one while text is up).
For every name with a place: the grader map most of that place's reads are on, and whether the name was said mostly
on that map. The grader's map is read only for scoring.
"""
from __future__ import annotations
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.landmarks import Landmarks  # noqa: E402
from anygame.memory import RunMemory  # noqa: E402


def rows(paths):
    for p in paths:
        for line in open(p):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def main(paths: list[str]) -> None:
    marks = Landmarks()
    place = None
    truth_of: dict = collections.defaultdict(collections.Counter)
    mem = RunMemory()
    for x in rows(paths):
        s = x.get("screen") if isinstance(x.get("screen"), dict) else {}
        w = s.get("world") if isinstance(s.get("world"), dict) else {}
        t = (x.get("truth") or {}).get("map_name") or (x.get("truth") or {}).get("map")
        if w.get("here"):
            place = w["here"]["map"]
            truth_of[place][t] += 1
        text = (s.get("text") or "").strip()
        if place is not None:
            mem.observe(x.get("tick", 0), None, {"map": place, "x": 0, "y": 0}, text)   # the run's own line log
    marks.update(mem.dialogue)
    print(f"{len(mem.dialogue)} lines, {len(marks.names())} names")
    for n in sorted(marks.names(), key=lambda n: -sum(marks.at[n].values())):
        p = marks.where(n)
        m = truth_of[p].most_common(1)[0][0] if p in truth_of else None
        print(f"  {n:12s} heard {sum(marks.at[n].values()):4d}  place {p}  (= {m})" if p is not None else
              f"  {n:12s} heard {sum(marks.at[n].values()):4d}  no place: {dict(marks.at[n].most_common(3))}")


if __name__ == "__main__":
    main(sys.argv[1:])
