"""Find a chain of menu choices toward a named outcome from a save state, and print the tree it tried.

    python scripts/chains_check.py <rom> <state> [--walk up:16,up:16] [--then a] [--says POTION] [--moves up]
        [--openers a,start] [--max-tries 60] [--glyphs glyphs.json]

--says: a line telling of a gain that names these words. --moves: a step in that direction moves the player
afterwards (position from the device's discovered x, y). Text is read with `kind: tiletext`.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("state")
    ap.add_argument("--walk", default="")
    ap.add_argument("--then", default="", help="keys played out (and kept) before the search, e.g. 'a' to read a sign")
    ap.add_argument("--says", nargs="*", default=None)
    ap.add_argument("--moves", default=None)
    ap.add_argument("--openers", default="a,start")
    ap.add_argument("--max-tries", type=int, default=60)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--glyphs", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.glyphs:
        os.environ["ANYGAME_GLYPHS"] = a.glyphs
    from anygame.chains import moves, replay, says, search
    from anygame.device.pyboy import PyBoyDevice
    from anygame.perceive import tiletext
    d = PyBoyDevice(f"pyboy://{a.rom}?state={a.state}")
    rd = tiletext.reader({"kind": "tiletext", "sync": True})
    read = lambda img: rd.read(img)[0]  # noqa: E731
    for k in filter(None, a.walk.split(",")):
        k, _, h = k.partition(":")
        d.press(k, hold=int(h or 4), after=12)
    if a.then:
        from anygame.playout import describe, play_out
        print("then:", describe(play_out(d, a.then.split(","), read, restore=False)))
    if a.moves:
        def pos():
            f = (d.state() or {}).get("found") or {}
            return (f.get("map"), f.get("x"), f.get("y"))
        test = moves(pos, a.moves)
    else:
        test = says(*(a.says or []))
    t0 = time.perf_counter()
    r = search(d, read, test, openers=tuple((o,) for o in a.openers.split(",")), max_tries=a.max_tries,
               max_depth=a.max_depth, log=print)
    r["wall_s"] = round(time.perf_counter() - t0, 1)
    print(json.dumps({k: v for k, v in r.items() if k != "trace"}, indent=1, ensure_ascii=False))
    if r["found"]:
        replay(d, r["trace"])
        print("replayed; now on screen:", read(d.screen()))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)
    if a.glyphs:
        rd.book.save(a.glyphs)


if __name__ == "__main__":
    main()
