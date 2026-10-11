"""Numbers through a battle: from a save state at a battle menu, pick the first entry twice (FIGHT, then the first
move) turn after turn, read the screen exactly (kind: tiletext), and bind each printed number to the RAM that follows
it. Prints each turn's numbers and, at the end, where each number was found.

    python scripts/numbers_check.py <rom> <state> [--turns 9] [--glyphs glyphs.json]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("state")
    ap.add_argument("--turns", type=int, default=9)
    ap.add_argument("--glyphs", default=None)
    a = ap.parse_args()
    if a.glyphs:
        os.environ["ANYGAME_GLYPHS"] = a.glyphs
    from anygame.device.pyboy import PyBoyDevice
    from anygame.discover import ram
    from anygame.numbers import NumberBook
    from anygame.perceive import tiletext
    from anygame.playout import play_out
    d = PyBoyDevice(f"pyboy://{a.rom}?state={a.state}")
    rd = tiletext.reader({"kind": "tiletext", "sync": True})
    read = lambda img: rd.read(img)[0]  # noqa: E731
    book = NumberBook()
    for turn in range(a.turns):
        text = read(d.screen())
        got = book.observe(text, ram(d.memory))
        print(turn, {g["name"]: g["value"] for g in got})
        r1 = play_out(d, ["a"], read, restore=False)
        r2 = play_out(d, ["a"], read, restore=False)
        if "cap" in (r1["end"], r2["end"]):
            break                               # the battle is over or the game stopped asking
    print(json.dumps(book.summary(), indent=1))
    print("now:", json.dumps(book.values(ram(d.memory))))
    if a.glyphs:
        rd.book.save(a.glyphs)


if __name__ == "__main__":
    main()
