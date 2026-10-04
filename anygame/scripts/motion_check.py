"""What each button does to the player from a save state: axes found and one line per input.

    python scripts/motion_check.py <rom> <state> [--out motion.json]
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
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from anygame.device.pyboy import PyBoyDevice
    from anygame.motion import describe, learn
    d = PyBoyDevice(f"pyboy://{a.rom}?state={a.state}")
    t0 = time.perf_counter()
    m = learn(d)
    m["wall_s"] = round(time.perf_counter() - t0, 2)
    m["describe"] = describe(m)
    print("axes:", m["axes"], f"({m['wall_s']} s)")
    for line in m["describe"]:
        print(" ", line)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(m, f, indent=1)


if __name__ == "__main__":
    main()
