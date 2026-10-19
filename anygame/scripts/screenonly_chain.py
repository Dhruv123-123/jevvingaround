"""The first-badge stages in one run: one screen-only agent goes from a save through each stage in turn, a new goal
in its notebook at each, with no save loaded between stages. Pokemon Red only (grader-side RAM, as in
screenonly_skill.py).

    python scripts/screenonly_chain.py STATE SEED STAGES.json '{"fights": true}' [KEEP]

A run cut off part-way resumes with CHAIN_FROM=K and STATE = its KEEP save after stage K-1 (redo indices stay
those of the whole list).

STAGES.json is a list of {"goal", "target" (map id, "levelN", "healed", "respawnMAP", "bagITEM", "nobagITEM", "partyN", "moveN", "badge" or "badgeN"), "presses", "advice" (calls allowed in this
stage), "walker" (a walk book for this stage, optional; it only acts on screens near its demos), "fresh" (true: a new agent
for this stage, with no memory of the run so far), "with" (optional settings merged into the run's for this stage's fresh
agent, e.g. a fight book only for the caves), "redo" (optional {"map": M, "from": K, "times": N}: landing on map M (or any map in a list), as
a lost fight wakes up at the last Pokemon Center, sends the run back to stage K, at most N times from this stage; {"hp": F,
...} instead fires when a fight ends below that fraction of health; a list of these is checked in order)}.

With {"decider": "openai"} or {"decider": "jev"} in the settings, the agent is anygame/typed_screen.py's: the Azure
model names each new screen once and the typed decider picks what to do. Add "framewise": true for
anygame/framewise.py's agent (both models on threads of their own; a stage's "presses" still counts presses).
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROM = "/mnt/project-files/roms/pokemon-red.gb"


def redo_list(st: dict) -> list[dict]:
    r = st.get("redo") or []
    return r if isinstance(r, list) else [r]


def redo_due(mem, r: dict, moved: bool) -> bool:
    """A redo fires on landing on one of its maps, or (with "hp") when a fight ends with the first party member below
    that fraction of its health (grader-side, like the targets)."""
    if "hp" in r:
        return not mem[0xD057] and mem[0xD16C] * 256 + mem[0xD16D] < r["hp"] * (mem[0xD18D] * 256 + mem[0xD18E])
    return moved and mem[0xD35E] in (r["map"] if isinstance(r["map"], list) else [r["map"]])


def done(mem, target: str) -> bool:
    if target == "healed":                      # first party member at full HP
        return mem[0xD16C] * 256 + mem[0xD16D] == mem[0xD18D] * 256 + mem[0xD18E]
    if target.startswith("bag") or target.startswith("nobag"):     # item id in the bag, or gone from it
        n = min(mem[0xD31D], 20)
        held = int(target.lstrip("nobag")) in [mem[0xD31E + 2 * k] for k in range(n)]
        return held if target.startswith("bag") else not held
    if target.startswith("respawn"):            # healed at a Pokemon Center, so a lost fight wakes up there
        return mem[0xD719] == int(target[7:])
    if target.startswith("badge"):              # badgeN: the Nth badge (plain "badge" is the first)
        return bool(mem[0xD356] >> (int(target[5:] or 1) - 1) & 1)
    if target.startswith("party"):              # this many Pokemon in the party (the starter is party1)
        return mem[0xD163] >= int(target[5:])
    if target.startswith("move"):               # moveN: the first party member knows move N (15 is Cut)
        return int(target[4:]) in [mem[0xD173 + k] for k in range(4)]
    if target.startswith("level"):
        return mem[0xD18C] >= int(target[5:])
    return mem[0xD35E] == int(target)


def main() -> None:
    from anygame.device.pyboy import PyBoyDevice
    from anygame.typed_screen import LabelCache, screen_agent
    from anygame.walk_book import WalkBook
    from anygame.chat import Chat
    state, seed, stages = sys.argv[1], int(sys.argv[2]), json.load(open(sys.argv[3]))
    kw = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
    keep = sys.argv[5] if len(sys.argv) > 5 else None      # save a state after each stage passed, as KEEP-N.state (and KEEP-N.json)
    work = tempfile.mkdtemp(prefix="sochain-")
    rom = os.path.join(work, "p.gb")
    shutil.copyfile(ROM, rom)
    dev = PyBoyDevice(f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * seed}&state={state}")
    chat = Chat(timeout=90)
    assert chat.api in ("azure", "azure-models"), "the advisor runs on Azure only"
    # '{"decider": "openai"}' (or "jev"): the chat model only names screens, once per new screen, and the typed
    # decider makes every choice; the names are kept across fresh agents (it is perception, not memory of the run)
    labels = LabelCache()
    a = screen_agent(dev, seed=seed, advisor=chat, labels=labels, **kw)
    typed = []
    mem = dev._pb.memory
    out, said, before = [], [], 0.0             # each advice call with the map it was made on (grader-side)
    trace = open(os.environ["CHAIN_TRACE"], "w", buffering=1) if os.environ.get("CHAIN_TRACE") else None
    k, redos = int(os.environ.get("CHAIN_FROM", 0)), {}    # CHAIN_FROM=K: resume at stage K from a KEEP save
    while k < len(stages):
        st = stages[k]
        k += 1
        if st.get("fresh"):                     # start this stage with a new agent: no memory of the run so far
            before += a.total_cost
            if hasattr(a, "summary"):
                typed.append(a.summary())
            if hasattr(a, "close"):
                a.close()
            a = screen_agent(dev, seed=seed, advisor=chat, labels=labels, **{**kw, **st.get("with", {})})
        a.goal = st["goal"]
        a.walker = WalkBook(st["walker"]) if st.get("walker") else None
        a.walk_talked = set()                   # a new stage may need the same person again (the nurse after training)
        a.walk_rest = 0
        a.max_advice = len(a.advice) + st.get("advice", 150)
        got, maps = None, []
        for i in range(st["presses"]):
            n = len(a.advice)
            a.step_press() if hasattr(a, "step_press") else a.step()
            for e in a.advice[n:]:
                said.append({"map": mem[0xD35E], "stage": len(out), "goal": e.get("goal"), "why": e.get("why"),
                             **({"pick": e.get("pick"), "label": e.get("label")} if "pick" in e or "label" in e else {})})
            if trace and i % 25 == 0:          # CHAIN_TRACE=path: where the run is every 25 presses (grader-side)
                trace.write(json.dumps([len(out), i, mem[0xD35E], mem[0xD362], mem[0xD361], mem[0xD057],
                                        mem[0xD16C] * 256 + mem[0xD16D], mem[0xD18C], a.last_how]) + "\n")
                if i % 500 == 0:               # and the screen now and then, to see what a stuck run is looking at
                    from PIL import Image
                    Image.fromarray(dev._pb.screen.ndarray[:, :, :3]).save(os.environ["CHAIN_TRACE"] + ".png")
            moved = not maps or maps[-1] != mem[0xD35E]
            if moved:
                maps.append(mem[0xD35E])
            if done(mem, st["target"]):
                got = i
                break
            back = next((r for r in redo_list(st) if i and redos.get(k, 0) < r.get("times", 3) and redo_due(mem, r, moved)), None)
            if back:
                got, redos[k], k = "redo", redos.get(k, 0) + 1, back["from"]
                break
        out.append({"target": st["target"], "reached": got, "maps": maps[:30], "level": mem[0xD18C],
                    "hp": mem[0xD16C] * 256 + mem[0xD16D], "usd": round(before + a.total_cost, 4)})
        print(json.dumps(out[-1]), file=sys.stderr, flush=True)
        if got is None:
            break
        if got == "redo":
            continue
        if keep:
            with open(f"{keep}-{len(out)}.state", "wb") as f:
                dev._pb.save_state(f)
            with open(f"{keep}-{len(out)}.json", "w") as f:   # what the save is, if the run is killed before its log lands
                json.dump({"stage": k - 1, **out[-1], "redos": sum(redos.values())}, f)
    if hasattr(a, "summary"):
        typed.append(a.summary())
    if hasattr(a, "close"):
        a.close()
    dev.close()
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"seed": seed, "stages": out, "passed": sum(s["reached"] not in (None, "redo") for s in out), "redos": sum(redos.values()),
                      "badge": bool(mem[0xD356] & 1), "badges": bin(mem[0xD356]).count("1"), "advice": len(a.advice), "typed": typed, "said": said, "usd": round(before + a.total_cost, 4)}))


if __name__ == "__main__":
    main()
