"""The first-badge stages in one run: one screen-only agent goes from a save through each stage in turn, a new goal
in its notebook at each, with no save loaded between stages. Pokemon Red only (grader-side RAM, as in
screenonly_skill.py).

    python scripts/screenonly_chain.py STATE SEED STAGES.json '{"fights": true}' [KEEP]

STAGES.json is a list of {"goal", "target" (map id, "levelN", "healed" or "badge"), "presses", "advice" (calls allowed in this
stage), "walker" (a walk book for this stage, optional; it only acts on screens near its demos)}.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROM = "/mnt/project-files/roms/pokemon-red.gb"


def done(mem, target: str) -> bool:
    if target == "healed":                      # first party member at full HP
        return mem[0xD16C] * 256 + mem[0xD16D] == mem[0xD18D] * 256 + mem[0xD18E]
    if target == "badge":
        return bool(mem[0xD356] & 1)
    if target.startswith("level"):
        return mem[0xD18C] >= int(target[5:])
    return mem[0xD35E] == int(target)


def main() -> None:
    from anygame.device.pyboy import PyBoyDevice
    from anygame.screen_agent import ScreenAgent
    from anygame.walk_book import WalkBook
    from anygame.chat import Chat
    state, seed, stages = sys.argv[1], int(sys.argv[2]), json.load(open(sys.argv[3]))
    kw = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
    keep = sys.argv[5] if len(sys.argv) > 5 else None      # save a state after each stage passed, as KEEP-N.state
    work = tempfile.mkdtemp(prefix="sochain-")
    rom = os.path.join(work, "p.gb")
    shutil.copyfile(ROM, rom)
    dev = PyBoyDevice(f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * seed}&state={state}")
    chat = Chat(timeout=90)
    assert chat.api in ("azure", "azure-models"), "the advisor runs on Azure only"
    a = ScreenAgent(dev, seed=seed, advisor=chat, **kw)
    mem = dev._pb.memory
    out = []
    for st in stages:
        a.goal = st["goal"]
        a.walker = WalkBook(st["walker"]) if st.get("walker") else None
        a.max_advice = len(a.advice) + st.get("advice", 150)
        got, maps = None, []
        for i in range(st["presses"]):
            a.step()
            if not maps or maps[-1] != mem[0xD35E]:
                maps.append(mem[0xD35E])
            if done(mem, st["target"]):
                got = i
                break
        out.append({"target": st["target"], "reached": got, "maps": maps[:30], "level": mem[0xD18C],
                    "hp": mem[0xD16C] * 256 + mem[0xD16D], "usd": round(a.total_cost, 4)})
        print(json.dumps(out[-1]), file=sys.stderr, flush=True)
        if got is None:
            break
        if keep:
            with open(f"{keep}-{len(out)}.state", "wb") as f:
                dev._pb.save_state(f)
    dev.close()
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"seed": seed, "stages": out, "passed": sum(s["reached"] is not None for s in out),
                      "badge": bool(mem[0xD356] & 1), "advice": len(a.advice), "usd": round(a.total_cost, 4)}))


if __name__ == "__main__":
    main()
