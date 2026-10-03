"""Run the agent on the held-out games and grade it.

    python -m heldout.run --decider random                     # every game in suite.yaml, every seed
    python -m heldout.run --decider standin --games postbot --seeds 1
    python -m heldout.run --decider jev --out runs/jev         # checks credit with one call first
    python -m heldout.report runs/random runs/standin > heldout-score.md

Each run: the game's ROM (fetched and checked, see roms.py) is copied to a fresh folder so no save file carries over;
the agent gets a step-locked PyBoy device and a generic Game Boy pack (packs/gameboy-blind by default, or --pack),
with nothing about the game, not even its name; after every agent step the grader reads memory and latches milestones; the run stops at the first budget limit.
Output per run: <out>/<game>-<decider>-<seed>.jsonl (one line per step), a summary line in <out>/runs.jsonl, and
screenshots at each milestone and at the end.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                         # anygame/ (the pack and the stand-in live there)
DECIDERS = ("random", "standin", "top", "jev")


def load_suite(path: Path | None = None) -> dict[str, Any]:
    suite = yaml.safe_load((path or HERE / "suite.yaml").read_text())
    suite["games"] = {}
    for gid in list(suite.get("held_out") or []) + list(suite.get("development") or []):
        f = HERE / "games" / f"{gid}.yaml"
        if not f.exists():
            raise SystemExit(f"suite.yaml names '{gid}' but heldout/games/{gid}.yaml does not exist")
        g = yaml.safe_load(f.read_text())
        g["tier"] = "held_out" if gid in (suite.get("held_out") or []) else "development"
        suite["games"][gid] = g
    return suite


def budget_for(suite: dict[str, Any], game: dict[str, Any], scale: float = 1.0) -> dict[str, float]:
    b = dict(suite["budget"])
    b.update(game.get("budget") or {})
    return {k: (v * scale if k in ("frames", "presses", "wall_s", "jev_calls") else v) for k, v in b.items()}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class StandIn:
    """The top-pick stand-in (test/clm_stub.py) as a local server on the same protocol Jev speaks."""

    def __init__(self):
        self.port = _free_port()
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "test" / "clm_stub.py"), str(self.port)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("the stand-in server did not start")

    def close(self):
        self.proc.terminate()


def open_decider(name: str, seed: int, standin: StandIn | None):
    from anygame.sensors import open_sensor
    if name == "random":
        return open_sensor(f"random:{seed}")
    if name == "top":
        return open_sensor("top")              # in process: the first option of every choice, the compiler's top pick
    if name == "standin":
        return open_sensor(f"clm:http://127.0.0.1:{standin.port}", timeout=5)
    if name == "jev":
        return open_sensor("jev", timeout=float(os.environ.get("ANYGAME_JEV_TIMEOUT", "4")))
    raise SystemExit(f"--decider must be one of {DECIDERS}")


def check_jev() -> None:
    """One tiny call before any run: an account out of credit (402) stops here, not 1,500 steps later."""
    from anygame.jev import Jev
    try:
        Jev(timeout=10).ask({"game": "check"}, {"ok": {"type": "noul", "instructions": "Is this a check?"}})
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Jev is not available, nothing was run: {str(e)[:200]}")


def _screen_hash(pb) -> str:
    return hashlib.blake2b(pb.screen.ndarray[::4, ::4, :3].tobytes(), digest_size=8).hexdigest()


def _save_png(pb, path: Path) -> None:
    pb.screen.image.convert("RGB").save(path)


def run_one(suite: dict[str, Any], gid: str, decider: str, seed: int, out: Path, standin: StandIn | None = None,
            scale: float = 1.0, fetch: bool = True, pack_name: str | None = None, goals: bool = True) -> dict[str, Any]:
    from anygame.device.pyboy import PyBoyDevice
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from .grader import Grader
    from .roms import NoRom, resolve

    game = suite["games"][gid]
    budget = budget_for(suite, game, scale)
    default_pack = suite.get("pack", "gameboy-blind")
    pack_name = pack_name or default_pack
    label = decider if pack_name == default_pack else f"{pack_name}+{decider}"   # another agent is its own column
    row: dict[str, Any] = {"game": gid, "tier": game["tier"], "kind": game.get("kind"), "decider": label, "pack": pack_name, "seed": seed,
                           "milestones": len(game["milestones"]), "budget": budget}
    try:
        rom = resolve(game, fetch=fetch)
    except NoRom as e:
        row.update(skipped=str(e))
        return row
    work = Path(tempfile.mkdtemp(prefix=f"heldout-{gid}-"))
    try:
        local = work / rom.name
        shutil.copyfile(rom, local)              # a fresh folder: PyBoy loads <rom>.ram if one sits beside the ROM
        dev = suite.get("device") or {}
        boot = 120 + 17 * seed                   # the seed moves power-on by a few frames, so the game's RNG differs
        # clock=game: step-locked; a pack's own `emulator:` block may set step, hold and after for its agent
        url = f"pyboy://{local}?clock=game&step={dev.get('idle', 4)}&hold={dev.get('hold', 6)}&after={dev.get('after', 16)}&boot={boot}"
        device = PyBoyDevice(url)
        # the pack is copied too, so whatever the agent learns about this game (a discovered RAM map) dies with the
        # run: no seed starts from what an earlier seed found
        shutil.copytree(ROOT / "packs" / pack_name, work / "pack")
        pack = load_pack(work / "pack")
        sensor = open_decider(decider, seed, standin)
        agent = Agent(pack, device, sensor, None, background=False)
        gb = getattr(agent, "goalbook", None)
        if gb is not None and goals and os.environ.get("ANYGAME_LLM_BASE"):
            # a pack that writes goals from dialogue gets the chat model (Azure, ANYGAME_LLM_*), exactly as `anygame play`
            # gives it; it reads what the game said and never presses a button
            from anygame.chat import Chat
            gb.chat = Chat(timeout=90)
        grader = Grader(game)
        pb = device._pb                          # the grader's view; the agent only ever gets device.frame()
        mem = pb.memory.__getitem__
        tag = f"{gid}-{label}-{seed}"
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        steps, presses, calls, noop = 0, 0, 0, 0
        screens: set[str] = set()
        last_hash = None
        t0 = time.perf_counter()
        stop = None
        with open(out / f"{tag}.jsonl", "w") as log:
            while stop is None:
                rec = agent.step()
                steps += 1
                act = str(rec.get("action") or "wait")
                if act not in ("wait", "stop", "keep"):
                    presses += 1
                if "jev_ms" in rec and decider not in ("random", "top"):
                    calls += 1
                h = _screen_hash(pb)              # the frame the agent decided on (presses do not render)
                if h == last_hash:
                    noop += 1
                last_hash = h
                screens.add(h)
                at = {"step": steps, "frame": device.frames, "presses": presses, "wall_s": round(time.perf_counter() - t0, 2)}
                new = grader.update(mem, at)
                for mid in new:
                    _save_png(pb, shots / f"{tag}-{mid}.png")
                log.write(json.dumps({**at, "action": act, "choice": rec.get("choice"), "reached": new or None,
                                      "sensor_ms": rec.get("jev_ms"), "cost_usd": rec.get("cost_usd")}) + "\n")
                if act == "stop":
                    stop = f"agent stopped: {rec.get('reason')}"
                elif device.frames >= budget["frames"]:
                    stop = "frames"
                elif presses >= budget["presses"]:
                    stop = "presses"
                elif time.perf_counter() - t0 >= budget["wall_s"]:
                    stop = "wall_s"
                elif calls >= budget["jev_calls"]:
                    stop = "jev_calls"
                elif agent.total_cost >= budget["usd"]:
                    stop = "usd"
                elif len(grader.reached) == len(grader.milestones):
                    stop = "all milestones"
        _save_png(pb, shots / f"{tag}-end.png")
        nxt = grader.next_milestone()
        last = max(grader.reached.values(), key=lambda a: a["frame"], default=None)
        row.update(score=round(grader.score, 4), reached=list(grader.reached), reached_at=grader.reached, stop=stop,
                   steps=steps, presses=presses, frames=device.frames, wall_s=round(time.perf_counter() - t0, 1),
                   decider_calls=calls, cost_usd=round(agent.total_cost, 6), sensor_errors=agent.errors,
                   goal_writer=(gb.report() if gb is not None and gb.chat is not None else None),
                   distinct_screens=len(screens), unchanged_screen_rate=round(noop / max(1, steps), 3),
                   stalled_before=(nxt or {}).get("desc"),
                   frames_since_progress=device.frames - (last["frame"] if last else 0))
        agent.close()
        device.close()
        return row
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m heldout.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decider", required=True, choices=DECIDERS)
    ap.add_argument("--games", help="comma-separated game ids (default: every game in suite.yaml)")
    ap.add_argument("--seeds", help="comma-separated seeds (default: suite.yaml)")
    ap.add_argument("--pack", help="the agent's pack (default: suite.yaml's); a different pack is reported as its own column, <pack>+<decider>")
    ap.add_argument("--no-goals", action="store_true", help="do not give a goal-writing pack its chat model (generic goal only)")
    ap.add_argument("--out", help="output folder (default: runs/<decider>)")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply the frame/press/time/call budget (a quick check: 0.1)")
    ap.add_argument("--no-fetch", action="store_true", help="never download a ROM; use only what is in the cache")
    a = ap.parse_args(argv)
    suite = load_suite()
    games = a.games.split(",") if a.games else list(suite["games"])
    unknown = [g for g in games if g not in suite["games"]]
    if unknown:
        raise SystemExit(f"not in suite.yaml: {', '.join(unknown)}")
    seeds = [int(s) for s in a.seeds.split(",")] if a.seeds else list(suite["seeds"])
    out = Path(a.out or f"runs/{a.decider}")
    out.mkdir(parents=True, exist_ok=True)
    if a.decider == "jev":
        check_jev()
    standin = StandIn() if a.decider == "standin" else None
    try:
        for gid in games:
            for seed in seeds:
                row = run_one(suite, gid, a.decider, seed, out, standin, a.scale, fetch=not a.no_fetch, pack_name=a.pack, goals=not a.no_goals)
                with open(out / "runs.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
                brief = {k: row.get(k) for k in ("game", "decider", "seed", "score", "reached", "stop", "presses", "wall_s", "skipped") if row.get(k) is not None}
                print(json.dumps(brief), flush=True)
    finally:
        if standin:
            standin.close()


if __name__ == "__main__":
    main()
