"""Replay a long-horizon run's goal-writer calls through anygame.goalgate: which calls the gate would have made, and
what the writer answered at the ones it skips.

    python scripts/goal_budget_replay.py <run dir with ckpt/run.json and log.jsonl.goals.jsonl> [...]

Each call is classed by its answer: kept (the goal stayed), same (the goal it replaced, again), generic (enter a new
place, no direction), or specific. A skipped call that was specific is a goal the gate would have lost.
"""
from __future__ import annotations
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def classify(call, prev_key):
    if call["result"] == "kept":
        return "kept", prev_key
    try:
        a = json.loads(re.search(r"\{.*\}", call["answer"], re.S).group(0))
    except Exception:  # noqa: BLE001
        return "unreadable", prev_key
    g = a.get("goal") or {}
    key = (json.dumps(g.get("done"), sort_keys=True), json.dumps(g.get("target"), sort_keys=True))
    if key == prev_key:
        return "same", key
    if g.get("done") == {"new_place": True} and not g.get("target"):
        return "generic", key
    return "specific", key


def replay(run: str) -> dict:
    from anygame.goalgate import GoalGate
    d = json.load(open(os.path.join(run, "ckpt", "run.json")))
    dialogue = d["memory"]["dialogue"]
    goals = d["goals"]["goals"]
    calls = [json.loads(x) for x in open(os.path.join(run, "log.jsonl.goals.jsonl")) if x.strip()]
    calls = [c for c in calls if c["tick"] <= d["tick"]]
    gate = GoalGate()
    out = Counter()
    lost = []
    prev_key = None
    pos = 0
    for c in calls:
        t = c["tick"]
        while pos < len(dialogue) and dialogue[pos]["tick"] <= t:
            gate.see(dialogue[pos]["text"])
            pos += 1
        ended = [g for g in goals if g.get("closed_tick") is not None and g["closed_tick"] <= t]
        last = max(ended, key=lambda g: g["closed_tick"]) if ended else None
        current = [g for g in goals if g["set_tick"] < t and (g.get("closed_tick") is None or g["closed_tick"] > t)]
        need = not current
        kind, prev_key = classify(c, prev_key)
        frames = int(dialogue[pos - 1]["frames"]) if pos else 0
        ok, why = gate.ask(t, frames, need=need, ended=last["outcome"] if last else None)
        if ok:
            gate.called(t, frames, "kept" if kind == "kept" else "set")
            out[("asked", kind)] += 1
        else:
            out[("skipped", kind)] += 1
            if kind == "specific":
                lost.append((t, json.loads(re.search(r"\{.*\}", c["answer"], re.S).group(0))["goal"]["instruction"], why))
    return {"run": run, "calls": len(calls), "by": {f"{a} {b}": n for (a, b), n in sorted(out.items())},
            "would_call": sum(n for (a, _), n in out.items() if a == "asked"), "lost_specific": lost}


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(json.dumps(replay(r), indent=1))
