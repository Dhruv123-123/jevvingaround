"""Steps of the gameboy agent on one ROM with the top-pick decider, timed: wall seconds per step, the action chosen,
the screen kind, and whether the step explored a menu. Text is read with a finished glyph book and no labeller, so
two runs of the same code make the same decisions, and two versions of the code can be compared step by step.

    python scripts/step_profile.py ROM --steps 120 --book BOOK.json --out log.jsonl [--seed 1] [--state S.state]

The device is set up as the held-out harness sets it (heldout/run.py): clock=game, the seed moving power-on."""
from __future__ import annotations
import argparse, json, shutil, sys, tempfile, time
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
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--book", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--state", default=None)
    ap.add_argument("--stuck", action="store_true", help="run anygame/stuck.py on every step, frames included, and log its raises")
    ap.add_argument("--full", default=None, help="also write each step's record (screen, action, truth) here, for place_check.py")
    ap.add_argument("--shots", default=None, help="a folder: the screen of every 10th explored step")
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="stepprof-"))
    rom = work / Path(a.rom).name
    shutil.copyfile(a.rom, rom)
    boot = 120 + 17 * a.seed
    url = f"pyboy://{rom}?clock=game&step=4&hold=6&after=16&boot={boot}" + (f"&state={a.state}" if a.state else "")
    device = PyBoyDevice(url)
    shutil.copytree(ROOT / "packs" / "gameboy", work / "pack")
    p = work / "pack" / "pack.yaml"
    y = yaml.safe_load(p.read_text())
    book = None
    if a.book:
        book = work / "book.json"
        shutil.copyfile(a.book, book)
    for name in ("text", "menu"):
        r = y["read"][name]
        r["labeller"] = "none"
        if book:
            r["book"] = str(book)
    p.write_text(yaml.safe_dump(y, sort_keys=False))
    if book:
        import os
        os.environ["ANYGAME_GLYPHS"] = str(book)     # the menu reader's cells use the same book, as in the held-out runs
    agent = Agent(load_pack(work / "pack"), device, open_sensor("top"), None, background=False)
    mt = None
    stuck = None
    if a.stuck:
        from anygame.stuck import Stuck
        stuck = Stuck()
    full = None
    if a.full:
        import os
        os.environ["ANYGAME_LOG_TRUTH"] = "1"     # the grader's map beside the reads, for scoring only
        full = open(a.full, "w")
        grader = None
        for g in ("pokemon_red", "aevilia"):
            if g.split("_")[0] in Path(a.rom).name:
                import importlib
                grader = importlib.import_module(f"anygame.graders.{g}")
    with open(a.out, "w") as log:
        for i in range(a.steps):
            if mt is None:
                mt = _find_menu(agent)
            before = getattr(mt, "reads", 0) if mt else 0
            t0 = time.perf_counter()
            rec = agent.step()
            dt = time.perf_counter() - t0
            if mt is None:
                mt = _find_menu(agent)
            s = rec.get("screen") or {}
            raised = None
            if stuck is not None:
                pos = (s.get("x"), s.get("y"), s.get("map")) if s.get("x") is not None else None
                raised = stuck.see(i + 1, rec.get("action"), kind=s.get("screen"), text=s.get("text"), pos=pos,
                                   frame=device.screen())
            log.write(json.dumps({"stuck": raised, "text": (s.get("text") or "")[:80], "y": s.get("y"), "map": s.get("map"),"step": i + 1, "wall_s": round(dt, 3), "frame": device.frames,
                                  "action": str(rec.get("action")), "kind": s.get("screen"),
                                  "x": s.get("x"), "explored": (getattr(mt, "reads", 0) if mt else 0) > before,
                                  "entries": (s.get("menu") or {}).get("entries")}) + "\n")
            log.flush()
            if full is not None:
                r = {k: rec.get(k) for k in ("tick", "screen", "action", "goal")}
                from anygame.stuck import fingerprint
                r["print"] = fingerprint(device.screen()).hex()      # what the screen looked like, coarsely
                if grader is not None:
                    f = grader.facts(device.memory)
                    r["truth"] = {"map": f.get("map"), "map_name": f.get("map_name")}
                full.write(json.dumps(r, default=str) + "\n")
            if a.shots and (getattr(mt, "reads", 0) if mt else 0) > before and mt.reads % 10 == 1:
                import cv2
                Path(a.shots).mkdir(parents=True, exist_ok=True)
                cv2.imwrite(f"{a.shots}/step{i + 1:04d}.png", device.screen()[:, :, ::-1])


def _find_menu(agent):
    return next((w for w in getattr(agent, "worlds", {}).values() if type(w).__name__ == "MenuTracker"), None)


if __name__ == "__main__":
    main()
