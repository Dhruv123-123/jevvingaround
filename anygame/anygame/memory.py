"""Run memory: what a long game needs remembered beyond the screen, for the whole run, and checkpoints to resume it.

  dialogue  every distinct line the game said, with where the player stood and when (the source of goals: a quest
            is told, not shown)
  places    the map signatures seen, in the order first entered, with when; how many tiles each has
  events    goals set, reached and given up; doors and maps found; who said what where (for the goal writer)

Nothing here knows which game it is: positions and map ids are the discovered ones (`found.*`), the text is OCR.

A checkpoint is a directory: the emulator's save state, the world memory, this memory, the discoverer's findings and
the agent's goal state. `anygame play --resume <dir>` (with `--checkpoint-every N`) continues a run from the last
one, which is what makes a 40-hour game a series of runs rather than one that must never crash.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def similar(a: str, b: str) -> bool:
    """Two OCR readings of the same line: one contains the other once letters are normalised, or they share most
    words (OCR drops and doubles letters, so exact matching would log every line several times)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    wa, wb = set(na.split()), set(nb.split())
    return len(wa & wb) >= 0.7 * min(len(wa), len(wb))


class RunMemory:
    def __init__(self, max_lines: int = 400):
        self.dialogue: list[dict[str, Any]] = []      # {tick, frames, map, x, y, text}
        self.places: dict[str, dict[str, Any]] = {}   # str(map) → {first_tick, entered, tiles}
        self.events: list[dict[str, Any]] = []        # {tick, kind, ...}
        self.max_lines = max_lines
        self.last_map: Any = None
        self.new_lines = 0                            # lines added since the goal writer last read them

    def observe(self, tick: int, frames: int | None, values: dict[str, Any], text: str | None, tile: tuple | None = None) -> dict[str, Any] | None:
        """One tick's reads (`tile`: the navigator's (x, y) for the position). Returns the new dialogue entry, if any."""
        m, x, y = values.get("map"), values.get("x"), values.get("y")
        if x is not None and m is not None:
            k = str(m)
            if k not in self.places:
                self.places[k] = {"first_tick": tick, "entered": 0}
                self.events.append({"tick": tick, "kind": "new_place", "map": m})
            if m != self.last_map:
                self.places[k]["entered"] += 1
                self.last_map = m
        if not isinstance(text, str) or len(_norm(text)) < 3:
            return None
        text = text.strip()
        recent = self.dialogue[-4:]
        for e in reversed(recent):
            if similar(e["text"], text):
                if len(text) > len(e["text"]):
                    e["text"] = text           # the same line, typed out further or read better
                return None
        last_pos = next((d for d in reversed(self.dialogue) if d.get("x") is not None), None)
        e = {"tick": tick, "frames": frames, "map": m, "x": x, "y": y, "tile": list(tile) if tile else None, "text": text}
        if x is None and last_pos is not None:
            e.update({"map": last_pos["map"], "x": last_pos["x"], "y": last_pos["y"], "tile": last_pos.get("tile"), "pos": "last known"})
        self.dialogue.append(e)
        del self.dialogue[: -self.max_lines]
        self.new_lines += 1
        return e

    def event(self, tick: int, kind: str, **kw) -> None:
        self.events.append({"tick": tick, "kind": kind, **kw})
        del self.events[:-500]

    def recent_dialogue(self, n: int = 20) -> list[dict[str, Any]]:
        return self.dialogue[-n:]

    def dump(self) -> dict[str, Any]:
        return {"dialogue": self.dialogue, "places": self.places, "events": self.events, "last_map": self.last_map}

    def load(self, d: dict[str, Any]) -> None:
        self.dialogue = list(d.get("dialogue") or [])
        self.places = dict(d.get("places") or {})
        self.events = list(d.get("events") or [])
        self.last_map = d.get("last_map")


# ---- checkpoints --------------------------------------------------------------------------------------------
def save_checkpoint(agent, path: str) -> str:
    """The whole run's state in a directory: emulator state, world, memory, goals, discovered RAM map, counters."""
    os.makedirs(path, exist_ok=True)
    dev = agent.device
    if hasattr(dev, "save_state"):
        dev.save_state(os.path.join(path, "emulator.state"))
    disc = getattr(dev, "discoverer", None)
    d: dict[str, Any] = {
        "tick": agent.tick, "total_cost": agent.total_cost, "auto_ticks": agent.auto_ticks,
        "worlds": {k: w.dump() for k, w in agent.worlds.items()},
        "memory": agent.memory.dump() if getattr(agent, "memory", None) is not None else None,
        "goals": agent.goalbook.dump() if getattr(agent, "goalbook", None) is not None else None,
        "remembered": agent.remembered,
        "discovered": disc.dump() if disc is not None and getattr(disc, "found", None) else None,
        "audit": agent.auditor.dump() if getattr(agent, "auditor", None) is not None else None,
    }
    tmp = os.path.join(path, "run.json.tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    os.replace(tmp, os.path.join(path, "run.json"))
    return path


def load_checkpoint(agent, path: str) -> dict[str, Any]:
    with open(os.path.join(path, "run.json")) as f:
        d = json.load(f)
    dev = agent.device
    st = os.path.join(path, "emulator.state")
    if os.path.exists(st) and hasattr(dev, "load_state"):
        dev.load_state(st)
    disc = getattr(dev, "discoverer", None)
    if disc is not None and d.get("discovered"):
        disc.load(d["discovered"])
    agent.tick = int(d.get("tick", 0))
    agent.total_cost = float(d.get("total_cost", 0.0))
    agent.auto_ticks = int(d.get("auto_ticks", 0))
    agent.remembered = d.get("remembered") or {}
    from .perceive.world import WorldTracker
    from .perceive.menu import MenuTracker
    for rid, wd in (d.get("worlds") or {}).items():
        r = agent.base.reads.get(rid)
        if r is None:
            continue
        w = MenuTracker(r) if r.get("kind") == "menu" else WorldTracker(r)
        w.load(wd)
        agent.worlds[rid] = w
    if d.get("memory") and getattr(agent, "memory", None) is not None:
        agent.memory.load(d["memory"])
    if d.get("goals") and getattr(agent, "goalbook", None) is not None:
        agent.goalbook.load(d["goals"])
        agent.quest = agent.goalbook.quest()
    if d.get("audit") and getattr(agent, "auditor", None) is not None:
        agent.auditor.load(d["audit"])
    return d
