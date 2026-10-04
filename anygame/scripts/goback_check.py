"""Going back to a place the run has been: the gameboy agent (top pick, no chat model) plays from power-on for
`--warm` steps, then is given the goal "go back to <place>" with the place book's id for a map it has been on, and
plays up to `--cap` more steps. Reports the step the player is on that map again (the grader's map, read only to
choose the target and to score) and the step the goal checks as reached (the run knowing it is there).

    python scripts/goback_check.py ROM --book BOOK.json --warm 320 --target REDS_HOUSE_2F --cap 300 [--out log.jsonl]
"""
from __future__ import annotations
import argparse, collections, importlib, json, os, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from anygame.device.pyboy import PyBoyDevice
from anygame.loop import Agent
from anygame.pack import load_pack
from anygame.sensors import open_sensor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--book", required=True)
    ap.add_argument("--warm", type=int, default=320)
    ap.add_argument("--target", required=True, help="the grader's map name to go back to")
    ap.add_argument("--cap", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="goback-"))
    rom = work / Path(a.rom).name
    shutil.copyfile(a.rom, rom)
    device = PyBoyDevice(f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={120 + 17 * a.seed}")
    shutil.copytree(ROOT / "packs" / "gameboy", work / "pack")
    p = work / "pack" / "pack.yaml"
    y = yaml.safe_load(p.read_text())
    book = work / "book.json"
    shutil.copyfile(a.book, book)
    for name in ("text", "menu"):
        y["read"][name]["labeller"] = "none"
        y["read"][name]["book"] = str(book)
    p.write_text(yaml.safe_dump(y, sort_keys=False))
    os.environ["ANYGAME_GLYPHS"] = str(book)
    grader = importlib.import_module("anygame.graders." + ("pokemon_red" if "pokemon" in rom.name else "aevilia"))
    agent = Agent(load_pack(work / "pack"), device, open_sensor("top"), None, background=False)
    log = open(a.out, "w") if a.out else None
    pids: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    target, arrived, reached = None, None, None
    for i in range(a.warm + a.cap):
        rec = agent.step()
        truth = grader.facts(device.memory).get("map_name")
        w = (rec.get("screen") or {}).get("world")
        here = (w.get("here") or {}).get("map") if isinstance(w, dict) and w.get("here") else None
        if here is not None and target is None:
            pids[truth][here] += 1
        if i + 1 == a.warm:
            if not pids.get(a.target):
                print(f"never on {a.target} in {a.warm} steps: {dict(pids)}")
                return
            target = pids[a.target].most_common(1)[0][0]
            values = {**(agent.last_values or {}), "map": here}
            agent.goalbook.impose({"id": "back", "instruction": f"go back to place {target}",
                                   "done": {"place": target}, "target": {"place": target}, "ticks": a.cap},
                                  agent.tick, values, source="test")
            print(f"step {i + 1}: on {truth} (place {here}); goal: back to place {target} ({a.target}); "
                  f"places so far {dict((k, dict(v)) for k, v in pids.items())}")
        if target is not None and i + 1 > a.warm:
            if arrived is None and truth == a.target:
                arrived = i + 1 - a.warm
            g = agent.goalbook.goals[-1] if agent.goalbook.goals else None
            back = next((x for x in agent.goalbook.goals if x.get("source") == "test"), None)
            if reached is None and back is not None and back.get("outcome") == "reached":
                reached = i + 1 - a.warm
        if log:
            log.write(json.dumps({"step": i + 1, "truth": truth, "here": here, "action": str(rec.get("action")),
                                  "goal": rec.get("goal")}) + "\n")
        if arrived is not None and reached is not None:
            break
    print(json.dumps({"target": a.target, "place": target, "arrived_after": arrived, "goal_reached_after": reached,
                      "cap": a.cap}))


if __name__ == "__main__":
    main()
