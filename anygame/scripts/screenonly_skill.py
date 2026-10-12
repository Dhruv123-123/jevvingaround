"""A skill test for the screen-only agent's advisor: from a saved spot, with a goal written into its notebook, how often
and how fast does it get there? Pokemon Red only (grader-side RAM: the map byte and the bag).

    python scripts/screenonly_skill.py STATE GOAL MAP SEED PRESSES '{"targets": true}'

e.g. from a Viridian City save, goal "Go into the Poke Mart (the building with the blue roof)", map 42. MAP "parcel"
runs until Oak's Parcel has been picked up and handed over (it enters the bag at the Mart and leaves it in Oak's lab);
MAP "badge" runs until the Boulder Badge is won; "levelN" until the first party member reaches level N.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROM = "/mnt/project-files/roms/pokemon-red.gb"
PARCEL = 0x46


def has_parcel(mem) -> bool:
    n = min(mem[0xD31D], 20)
    return any(mem[0xD31E + 2 * k] == PARCEL for k in range(n))


def main() -> None:
    from anygame.device.pyboy import PyBoyDevice
    from anygame.screen_agent import ScreenAgent
    from anygame.chat import Chat
    state, goal, target, seed, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
    kw = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
    work = tempfile.mkdtemp(prefix="sosk-")
    rom = os.path.join(work, "p.gb")
    shutil.copyfile(ROM, rom)
    dev = PyBoyDevice(f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * seed}&state={state}")
    chat = Chat(timeout=90)
    assert chat.api in ("azure", "azure-models"), "the advisor runs on Azure only"
    a = ScreenAgent(dev, seed=seed, advisor=chat, **kw)
    a.goal = goal
    mem = dev._pb.memory
    errand, badge = target == "parcel", target == "badge"
    level = int(target[5:]) if target.startswith("level") else None
    target = None if errand or badge or level else int(target)
    got = None
    maps = []
    parcel: dict[str, int] = {}
    for i in range(n):
        a.step()
        mp = mem[0xD35E]
        if not maps or maps[-1] != mp:
            maps.append(mp)
        if level:
            if mem[0xD18C] >= level:
                got = i
                break
        elif badge:
            if mem[0xD356] & 1:
                got = i
                break
        elif errand:
            held = has_parcel(mem)
            if held:
                parcel.setdefault("got", i)
            elif "got" in parcel:
                parcel["gave"] = got = i
                break
        elif mp == target:
            got = i
            break
    end = {"map": mem[0xD35E], "level": mem[0xD18C], "hp": mem[0xD16C] * 256 + mem[0xD16D], "badges": mem[0xD356]}
    dev.close()
    shutil.rmtree(work, ignore_errors=True)
    walks = [e.get("walk") for e in a.advice if "target" in e]
    print(json.dumps({"seed": seed, "reached": got, "maps": maps, "parcel": parcel, "end": end, "advice": len(a.advice),
                      "walks": walks,
                      "log": [{k: e.get(k) for k in ("goal", "why", "target", "walk", "presses", "error") if e.get(k)}
                              for e in a.advice],
                      "usd": round(a.total_cost, 4)}))


if __name__ == "__main__":
    main()
