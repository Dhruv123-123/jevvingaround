"""Play the development games screen-only and measure exploration from grader-side RAM (the agent never reads it).

Milestones are sparse (five per game), so two agents a few tweaks apart look the same on them. This script scores
the denser thing a screen-only explorer should be good at: how many distinct places (map, x, y from the position
bytes) and maps it reached in a fixed number of presses, on Pokemon Red (power-on, and from the long-horizon save
in Blue's house) and Aevilia. Random presses are the floor.

    python scripts/screenonly_play.py --agent screen --seeds 1,2,3 --presses 1500
    python scripts/screenonly_play.py --agent random --seeds 1,2,3
"""
from __future__ import annotations
import argparse
import json
import os
import random
import shutil
import statistics as st
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROMS = "/mnt/project-files/roms"
GAMES = {
    "pokemon-cold": {"rom": f"{ROMS}/pokemon-red.gb", "pos": lambda m: (m[0xD35E], m[0xD362], m[0xD361])},
    "pokemon": {"rom": f"{ROMS}/pokemon-red.gb", "state": "/mnt/project-files/anygame/pokemon-red/longhorizon/ck45700/emulator.state",
                "pos": lambda m: (m[0xD35E], m[0xD362], m[0xD361])},
    "aevilia": {"rom": f"{ROMS}/homebrew/aevilia.gbc",
                "pos": lambda m: (m[0xC3C4], (m[0xD712] | m[0xD713] << 8) // 16, (m[0xD710] | m[0xD711] << 8) // 16)},
}


class RandomAgent:
    BUTTONS = ["up", "down", "left", "right", "a", "b", "start", "select"]
    WEIGHTS = [3, 3, 3, 3, 2, 1, 0.4, 0.2]

    def __init__(self, dev, seed):
        self.dev, self.rng = dev, random.Random(seed)

    def step(self):
        self.dev.frame()
        b = self.rng.choices(self.BUTTONS, self.WEIGHTS)[0]
        self.dev.press(b)
        return {"action": b}


def play(game: str, agent: str, seed: int, presses: int, **kw) -> dict:
    from anygame.device.pyboy import PyBoyDevice
    g = GAMES[game]
    work = tempfile.mkdtemp(prefix="sop-")
    try:
        rom = os.path.join(work, os.path.basename(g["rom"]))
        shutil.copyfile(g["rom"], rom)
        url = f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * seed}"
        if g.get("state"):
            url += f"&state={g['state']}"
        dev = PyBoyDevice(url)
        if agent == "random":
            a = RandomAgent(dev, seed)
        else:
            from anygame.screen_agent import ScreenAgent
            kw = dict(kw)
            if kw.pop("advice", False):
                from anygame.chat import Chat
                kw["advisor"] = Chat(timeout=90)
                assert kw["advisor"].api in ("azure", "azure-models"), "the advisor runs on Azure only"
            a = ScreenAgent(dev, seed=seed, **kw)
        mem = dev._pb.memory
        places, maps = set(), set()
        curve = []
        t0 = time.time()
        for i in range(presses):
            a.step()
            p = g["pos"](mem)
            places.add(p)
            maps.add(p[0])
            if (i + 1) % 250 == 0:
                curve.append(len(places))
        dev.close()
        return {"game": game, "agent": agent, "seed": seed, "places": len(places), "maps": len(maps), "curve": curve,
                "wall_s": round(time.time() - t0, 1), "usd": round(getattr(a, "total_cost", 0.0), 4),
                "advice": getattr(a, "advice", None)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="screen", choices=("screen", "random"))
    ap.add_argument("--games", default="pokemon-cold,pokemon,aevilia")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--presses", type=int, default=1500)
    ap.add_argument("--kw", default="{}", help="ScreenAgent keyword arguments as JSON")
    ap.add_argument("--out")
    a = ap.parse_args()
    kw = json.loads(a.kw)
    rows = []
    for game in a.games.split(","):
        rs = [play(game, a.agent, int(s), a.presses, **kw) for s in a.seeds.split(",")]
        rows += rs
        print(json.dumps({"game": game, "agent": a.agent, "kw": kw, "places_mean": round(st.mean(r["places"] for r in rs), 1),
                          "places": [r["places"] for r in rs], "maps": [r["maps"] for r in rs],
                          "usd": round(sum(r["usd"] for r in rs), 4), "advice": sum(len(r["advice"] or []) for r in rs)}), flush=True)
    if a.out:
        with open(a.out, "a") as f:
            for r in rows:
                f.write(json.dumps({**r, "kw": kw}) + "\n")


if __name__ == "__main__":
    sys.exit(main())
