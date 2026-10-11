"""Replays logged runs through anygame.upkeep: when it would have asked to leave and where it would have sent the
player, beside what happened (a blackout, the run's end). The grader's map is read only to name places here.

    python scripts/upkeep_replay.py <log.jsonl> [<log.jsonl> ...]     # several logs are one run, in order
    python scripts/upkeep_replay.py --names <log.jsonl> ...           # every fraction under its own name, as live

Numbers come from each read's text with numbers.parse. On these OCR logs a label is unreliable ("HP" one read,
"BULBASAUR" the next), so the replay takes the first "#/#" on a line as one number; a live run with exact text keeps
labels apart.
"""
from __future__ import annotations
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.numbers import parse  # noqa: E402
from anygame.places import PlaceBook  # noqa: E402
from anygame.upkeep import Upkeep  # noqa: E402
from place_check import moves_of  # noqa: E402

LOSS = re.compile(r"bla.ked|out o. useable|game over|you die", re.I)   # for the report only, never shown to Upkeep


def replay(paths: list[str], names: bool = False, keep=None) -> dict:
    book, keep = PlaceBook(), keep or Upkeep()
    truth_of = collections.defaultdict(collections.Counter)
    prev_action, active, out = None, None, []
    losses, last_tick = [], None
    for path in paths:
        for line in open(path):
            r = json.loads(line)
            s = r.get("screen") if isinstance(r.get("screen"), dict) else {}
            tick = int(r["tick"])
            last_tick = tick
            text = s.get("text") or ""
            if LOSS.search(text) and (not losses or tick - losses[-1] > 20):
                losses.append(tick)
            pid, moved = None, False
            if s.get("x") is not None and s.get("y") is not None:
                mv = moves_of(prev_action)
                n0 = len(book.events)
                pid = book.see(s.get("map", 0), int(s["x"]), int(s["y"]), moves=mv,
                               walking=bool(mv), idle=str(prev_action or "").startswith("auto: wait"))
                moved = not mv and any(e["kind"] in ("door", "join") for e in book.events[n0:])
                truth_of[pid][(r.get("truth") or {}).get("map")] += 1
            if names:
                # every fraction under the name the live run's NumberBook gives it (label + shape, "(2)" for a
                # repeat): move PP, the other side's numbers and one HP under several labels all arrive
                nums = {d["name"]: {"value": d["value"], "of": d["of"]} for d in parse(text) if d.get("of")}
            else:
                fr = [d for d in parse(text) if d.get("of") and not d["name"].endswith(")")]
                nums = {"#/#": {"value": fr[0]["value"], "of": fr[0]["of"]}} if fr else {}
            keep.see(tick, nums, place=pid, screen=s.get("screen"), moved=moved)
            a = keep.advice()
            key = None if a is None else (a["goal"].get("target") or {}).get("place")
            if (a is None) != (active is None) or (a is not None and key != active[1]):
                out.append({"tick": tick, "advice": None if a is None else a["why"], "target_place": key})
                active = None if a is None else (tick, key)
            prev_action = r.get("action")
    name = {p: c.most_common(1)[0][0] for p, c in truth_of.items()}
    for o in out:
        o["target_map"] = name.get(o["target_place"])
    return {"changes": out, "losses": losses, "end": last_tick, "events": keep.events, "numbers": keep.report()}


def main() -> None:
    args = sys.argv[1:]
    names = "--names" in args
    r = replay([a for a in args if a != "--names"], names=names)
    print("losses (from the text, for this report):", r["losses"], "end:", r["end"])
    for e in r["events"]:
        print(" ", e)
    for c in r["changes"]:
        print(" ", c)


if __name__ == "__main__":
    main()
