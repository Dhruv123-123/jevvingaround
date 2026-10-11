"""Pokemon Red from the long-horizon save (Blue's house in Pallet Town): how far north a screen-only agent gets.

Route 1 runs north from Pallet Town to Viridian City; its y byte counts down from 35 to 0. The script reports where
the presses went (each map, and battles), the first press on each map, and the northernmost y reached on Route 1.
Grader-side only: the agent never reads RAM.

    python scripts/screenonly_route1.py SEED PRESSES '{"advice": true}'
"""
from __future__ import annotations
import collections
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

ROUTE1, BATTLE = 12, 0xD057


def main() -> None:
    import screenonly_play as P
    from anygame.device.pyboy import PyBoyDevice
    from anygame.screen_agent import ScreenAgent
    seed, n = int(sys.argv[1]), int(sys.argv[2])
    kw = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    g = P.GAMES["pokemon"]
    work = tempfile.mkdtemp(prefix="sor1-")
    rom = os.path.join(work, "p.gb")
    shutil.copyfile(g["rom"], rom)
    dev = PyBoyDevice(f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * seed}&state={g['state']}")
    if kw.pop("advice", False):
        from anygame.chat import Chat
        kw["advisor"] = Chat(timeout=90)
        assert kw["advisor"].api in ("azure", "azure-models"), "the advisor runs on Azure only"
    a = ScreenAgent(dev, seed=seed, **kw)
    mem = dev._pb.memory
    where: collections.Counter = collections.Counter()
    first: dict[int, int] = {}
    north = 99
    for i in range(n):
        a.step()
        mp = mem[0xD35E]
        where["battle" if mem[BATTLE] else mp] += 1
        first.setdefault(mp, i)
        if mp == ROUTE1:
            north = min(north, mem[0xD361])
    dev.close()
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"seed": seed, "presses": n, "where": {str(k): v for k, v in where.most_common()},
                      "first": {str(k): v for k, v in first.items()}, "route1_north_y": north,
                      "viridian": 1 in first, "usd": round(a.total_cost, 4)}))


if __name__ == "__main__":
    main()
