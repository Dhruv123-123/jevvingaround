"""Replays logged runs through the place book and anygame.heading. It reports two things:

1. How often the heading named the direction in which the next new place was actually found. That is the place
   book's first entry into a place, by a walk. Random is 25%.
2. On each walk decision, whether the run's explore pick went the heading's way.

    python scripts/heading_check.py <log.jsonl> [...]      # several logs are one run, in order
"""
from __future__ import annotations
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.heading import Heading  # noqa: E402
from anygame.places import PlaceBook  # noqa: E402
from place_check import moves_of  # noqa: E402


def replay(paths: list[str]) -> dict:
    book = PlaceBook()
    head = Heading(book)
    prev_action, prev_head = None, None
    found = collections.Counter()
    picks = collections.Counter()
    for path in paths:
        for line in open(path):
            r = json.loads(line)
            s = r.get("screen") if isinstance(r.get("screen"), dict) else {}
            if s.get("x") is None or s.get("y") is None:
                prev_action = r.get("action")
                continue
            mv = moves_of(prev_action)
            known = {p.id for p in book.places}
            n0 = len(book.events)
            pid = book.see(s.get("map", 0), int(s["x"]), int(s["y"]), moves=mv, walking=bool(mv),
                           idle=str(prev_action or "").startswith("auto: wait"))
            new = [e for e in book.events[n0:] if e["kind"] in ("join", "door") and e["to"] not in known]
            for e in new:
                kind = e["kind"]
                if not mv:
                    continue
                if prev_head is None:
                    found[f"{kind}: no heading yet"] += 1
                else:
                    found[f"{kind}: heading named it" if mv[-1] == prev_head else f"{kind}: another way"] += 1
            h = head.toward(pid)
            a = str(r.get("action") or "")
            if s.get("screen") == "walk" and a.startswith("explore_") and h:
                picks["went the heading's way" if a.startswith(f"explore_{h}") else "went another way"] += 1
            prev_head = h
            prev_action = r.get("action")
    return {"new places": dict(found), "explore picks": dict(picks), "places": book.report()}


if __name__ == "__main__":
    print(json.dumps(replay(sys.argv[1:]), indent=1))
