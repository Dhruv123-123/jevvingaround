"""Framewise vs typed on a wall clock: the game runs in real time (60 fps) whether or not the agent is thinking.

    python scripts/framewise_bench.py STATE SECONDS AGENT [DECIDER] [SEED]

AGENT is "typed" (typed_screen.py: the game runs on while the agent waits for the namer and the decider) or
"framewise" (framewise.py: both models on their own threads). DECIDER defaults to stub:400, a free stand-in with
Jev's latency (Jev itself has no credit as of Oct 17). The namer is the Azure chat model, as everywhere. Prints one
JSON line: presses, the screen graph's states, the places the player stood (grader-side RAM, Pokemon Red), maps,
wall time the loop spent blocked in a model call, and spend.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROM = "/mnt/project-files/roms/pokemon-red.gb"


def main() -> None:
    from anygame.chat import Chat
    from anygame.device.pyboy import PyBoyDevice
    from anygame.framewise import FramewiseAgent
    from anygame.sensors import open_sensor
    from anygame.typed_screen import TypedScreenAgent
    state, secs, kind = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    dec = sys.argv[4] if len(sys.argv) > 4 else "stub:400"
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    work = tempfile.mkdtemp(prefix="fwbench-")
    rom = os.path.join(work, "p.gb")
    shutil.copyfile(ROM, rom)
    dev = PyBoyDevice(f"pyboy://{rom}?clock=wall&fps=60&hold=6&after=16&state={state}")
    chat = Chat(timeout=90)
    assert chat.api in ("azure", "azure-models"), "the namer runs on Azure only"
    decider = open_sensor(dec, timeout=20)
    goal = os.environ.get("BENCH_GOAL", "")
    if kind == "framewise":
        # BENCH_KW: FramewiseAgent settings as JSON, e.g. '{"name_effort": "none"}'
        a = FramewiseAgent(dev, decider, namer=chat, seed=seed, **json.loads(os.environ.get("BENCH_KW") or "{}"))
    else:
        a = TypedScreenAgent(dev, decider, namer=chat, seed=seed)
    a.goal = goal
    mem = dev._pb.memory
    cells, maps, blocked, steps = set(), [], 0.0, 0
    target = int(os.environ["BENCH_TARGET"]) if os.environ.get("BENCH_TARGET") else None   # a map id to reach
    reached = None
    f0, t0 = dev.frames, time.perf_counter()
    while time.perf_counter() - t0 < secs:
        s = time.perf_counter()
        a.step()
        took = time.perf_counter() - s
        if took > 0.1:                      # a step that took longer than six frames was waiting on a model
            blocked += took
        steps += 1
        # a press runs its frames at once; hold the loop so the game never runs ahead of real time (60 fps)
        ahead = (dev.frames - f0) / 60 - (time.perf_counter() - t0)
        if ahead > 0:
            time.sleep(ahead)
            dev._last = time.perf_counter()     # the press's own frames covered that time
        cells.add((mem[0xD35E], mem[0xD362], mem[0xD361]))
        if not maps or maps[-1] != mem[0xD35E]:
            maps.append(mem[0xD35E])
        if target is not None and reached is None and mem[0xD35E] == target:
            reached = round(time.perf_counter() - t0, 1)
            if os.environ.get("BENCH_STOP"):
                break
    wall = time.perf_counter() - t0
    out = {"agent": kind, "decider": dec, "state": os.path.basename(state), "seed": seed, "wall_s": round(wall, 1),
           "game_frames": dev.frames - f0, "steps": steps,
           "presses": a.n["presses"] if kind == "framewise" else steps, "graph_states": len(a.visits),
           "cells": len(cells), "maps": maps[:40], "distinct_maps": len(set(maps)), "target": target, "reached_s": reached, "blocked_s": round(blocked, 1),
           "usd": round(a.total_cost if kind != "framewise" else a.cost(), 4), "typed": a.summary()}
    if hasattr(a, "close"):
        a.close()
    print(json.dumps(out))
    dev.close()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
