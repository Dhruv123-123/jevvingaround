"""Play menu choices out to the next decision from a save state, and print what each led to.

    python scripts/playout_check.py <rom> <state> [--glyphs glyphs.json] [--choices 'fight=a' 'run=down,right,a' ...]
        [--then 'a']     (keys played and kept before the choices: e.g. open a sub-menu)

Text is read with `kind: tiletext` (glyphs from --glyphs, new ones labelled by the chat model when it is set).
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
    ap.add_argument("--glyphs", default=None)
    ap.add_argument("--then", default="")
    ap.add_argument("--choices", nargs="+", default=["fight=a", "item=down,a", "run=down,right,a"])
    ap.add_argument("--delays", default="0,7,13")
    ap.add_argument("--max-frames", type=int, default=2400)
    a = ap.parse_args()
    if a.glyphs:
        os.environ["ANYGAME_GLYPHS"] = a.glyphs
    from anygame.device.pyboy import PyBoyDevice
    from anygame.perceive import tiletext
    from anygame.playout import play_out, describe, new_lines
    d = PyBoyDevice(f"pyboy://{a.rom}?state={a.state}")
    rd = tiletext.reader({"kind": "tiletext", "sync": True})
    read = lambda img: rd.read(img)[0]  # noqa: E731
    if a.then:
        r = play_out(d, a.then.split(","), read, max_frames=a.max_frames, restore=False)
        print("then:", describe(r))
    print("on screen:", read(d.screen()))
    delays = tuple(int(x) for x in a.delays.split(","))
    out = {}
    for c in a.choices:
        name, _, keys = c.partition("=")
        t0 = time.perf_counter()
        rs = [play_out(d, keys.split(","), read, max_frames=a.max_frames, delay=dl) for dl in delays]
        ms = (time.perf_counter() - t0) * 1000 / len(rs)
        out[name] = {"describe": describe(rs), "lines": [new_lines(r) for r in rs], "end": [r["end"] for r in rs],
                     "frames": [r["frames"] for r in rs], "wall_ms_each": round(ms)}
        print(f"{name}: {describe(rs)}   [{round(ms)} ms wall each]")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    rd.book.save(a.glyphs) if a.glyphs else None


if __name__ == "__main__":
    main()
