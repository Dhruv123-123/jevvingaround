"""Goals from what the game says: a chat model reads the dialogue log and the world memory and writes the next goal
as a condition the code can check. It never presses a button and never sees RAM; it sees what a player would have
seen (the text on screen, where it was said) and what the run has found (places, doors).

A goal:

    {id, instruction, done: <condition>, target?: <where to head>, ticks?: <give up after>}

Conditions (all over discovered reads and the run memory, nothing game-specific):

    {new_place: true}            enter a place (map signature) not entered before the goal was set
    {leave_place: true}          be somewhere other than where the goal was set
    {place: <signature>}         be in a place already known (from the places list)
    {said: [word, ...]}          the game says a line containing one of these words after the goal was set
    {talks: n}                   n new lines of dialogue after the goal was set (talk to people)
    {screen: choice}             a menu or a choice is on screen
    {any: [<condition>, ...]}    one of them

Targets (hints for the navigator, optional): {toward: up|down|left|right}, {place: <signature>} (walk the known
door chain there), {line: <index into the dialogue list>} (go back to where that line was said).

The writer is called when there is no goal, when one is reached or given up, and when the game has said something
new and the player is walking again; at most `max_calls` times a run and no more often than `min_gap` ticks. Without
a chat model (or when its answer does not check) the goal is the generic one: find a place not entered yet.

Pack:   goals_from: dialogue        (optionally goals_cfg: {max_calls, min_gap, give_up})
"""
from __future__ import annotations
import json
import re
from typing import Any

from .memory import RunMemory, _norm

DIRS = ("up", "down", "left", "right")
EXPLORE = {"id": "explore", "instruction": "find somewhere new: walk into a place not entered yet", "done": {"new_place": True},
           "source": "default"}

SYSTEM = """You set goals for a program that plays a video game it has never seen. You never press buttons. You read
what the game has said (dialogue, signs, menus, read by OCR so letters may be wrong) and what the player has found,
and you write the ONE next goal as a condition the program can check.

Answer with JSON only:
{"why": "<one sentence>", "keep": false,
 "goal": {"instruction": "<a short imperative sentence for the player>",
          "done": <condition>, "target": <target or null>, "ticks": <how many decisions before giving up, 40..400>}}
Use "keep": true (and no goal) when the current goal is still right.

Conditions (pick the one that checks the outcome the game asked for):
  {"new_place": true}       enter a place not entered yet (leave a house, go to a new area, go downstairs)
  {"leave_place": true}     get out of the current place
  {"place": <id>}           go back to a known place (ids from the places list)
  {"said": ["word", ...]}   the game says a line containing one of these words (a name, an item, "received")
  {"talks": <n>}            hear n new lines of dialogue (talk to people here)
  {"screen": "choice"}      open a menu or reach a choice
  {"any": [<condition>, ...]}
Targets (where to head, or null): {"toward": "up"|"down"|"left"|"right"} (up is north),
  {"place": <id>} (a known place), {"line": <index of a dialogue line>} (back to where it was said).

Prefer what the dialogue asks for (someone told you to go somewhere, find someone, press a button). If nothing was
asked, explore: a new place, or talk to people. Do not repeat a goal that was just given up unless something changed."""


def check(cond: Any, places: set[str] | None = None, depth: int = 0) -> str | None:
    """None when the condition is well formed, else what is wrong."""
    if not isinstance(cond, dict) or len(cond) != 1 or depth > 2:
        return f"a condition is one key: {cond!r}"
    (k, v), = cond.items()
    if k in ("new_place", "leave_place"):
        return None if v is True else f"{k} takes true"
    if k == "place":
        return None if places is None or str(v) in places else f"unknown place {v!r}"
    if k == "said":
        ok = isinstance(v, list) and v and all(isinstance(w, str) and _norm(w) for w in v)
        return None if ok else "said takes a list of words"
    if k == "talks":
        return None if isinstance(v, int) and 1 <= v <= 20 else "talks takes 1..20"
    if k == "screen":
        return None if v in ("choice", "text", "walk") else "screen takes choice|text|walk"
    if k == "any":
        if not isinstance(v, list) or not v:
            return "any takes a list"
        for c in v:
            e = check(c, places, depth + 1)
            if e:
                return e
        return None
    return f"unknown condition {k!r}"


def check_target(t: Any, places: set[str], lines: int) -> str | None:
    if t is None:
        return None
    if not isinstance(t, dict) or len(t) != 1:
        return f"a target is one key: {t!r}"
    (k, v), = t.items()
    if k == "toward":
        return None if v in DIRS else "toward takes up|down|left|right"
    if k == "place":
        return None if str(v) in places else f"unknown place {v!r}"
    if k == "line":
        return None if isinstance(v, int) and 0 <= v < lines else "line takes an index into the dialogue list"
    return f"unknown target {k!r}"


def _json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in the answer")
    return json.loads(m.group(0))


class GoalBook:
    def __init__(self, memory: RunMemory, chat=None, cfg: dict[str, Any] | None = None, log=None):
        cfg = cfg or {}
        self.memory = memory
        self.chat = chat                          # anygame.chat.Chat, or None: the generic goal only
        self.max_calls = int(cfg.get("max_calls", 60))
        self.min_gap = int(cfg.get("min_gap", 12))
        self.give_up = int(cfg.get("give_up", 250))
        self.goals: list[dict[str, Any]] = []     # every goal set, with its outcome
        self.current: dict[str, Any] | None = None
        self.calls = 0
        self.failures = 0                         # answers that did not check
        self.last_call = -10**9
        self.latency_ms: list[int] = []
        self.log = log                            # a callable(dict): each call's prompt summary and answer
        self.n = 0

    # ---- checking -----------------------------------------------------------------------------------
    def _holds(self, cond: dict[str, Any], g: dict[str, Any], values: dict[str, Any]) -> bool:
        (k, v), = cond.items()
        m = values.get("map")
        here_known = values.get("x") is not None and m is not None
        if k == "new_place":
            return here_known and str(m) not in g["places_at_set"]
        if k == "leave_place":
            return here_known and m != g["map_at_set"]
        if k == "place":
            return here_known and str(m) == str(v)
        if k == "said":
            words = [_norm(w) for w in v]
            return any(any(w and w in _norm(d["text"]) for w in words) for d in self.memory.dialogue[g["line_at_set"]:])
        if k == "talks":
            return len(self.memory.dialogue) - g["line_at_set"] >= int(v)
        if k == "screen":
            return values.get("screen") == v
        if k == "any":
            return any(self._holds(c, g, values) for c in v)
        return False

    # ---- the tick -----------------------------------------------------------------------------------
    def update(self, tick: int, values: dict[str, Any], world=None) -> dict[str, Any] | None:
        g = self.current
        if g is not None:
            if self._holds(g["done"], g, values):
                self._close(g, "reached", tick)
            elif tick - g["set_tick"] > int(g.get("ticks") or self.give_up):
                self._close(g, "given up", tick)
        # not in the middle of what the game is saying (a text, a cutscene): a goal is written between them. A menu
        # or the world with the position not yet found counts, so a player who has not walked yet has a goal too
        scr = values.get("screen", "walk" if values.get("x") is not None else None)
        if scr not in ("walk", "choice", "button"):
            return self.quest()
        need = self.current is None
        news = self.memory.new_lines > 0 and tick - self.last_call >= self.min_gap
        if (need or news) and self.chat is not None and self.calls < self.max_calls:
            self._write(tick, values, world)
        if self.current is None:
            self._set(dict(EXPLORE), tick, values)
        return self.quest()

    def _close(self, g: dict[str, Any], outcome: str, tick: int) -> None:
        g["outcome"], g["closed_tick"] = outcome, tick
        self.memory.event(tick, "goal " + outcome, id=g["id"], instruction=g["instruction"])
        self.current = None

    def _set(self, goal: dict[str, Any], tick: int, values: dict[str, Any]) -> None:
        self.n += 1
        g = {**goal, "id": f"g{self.n}" if goal.get("id") != "explore" else f"explore{self.n}", "set_tick": tick,
             "map_at_set": values.get("map"), "places_at_set": sorted(self.memory.places),
             "line_at_set": len(self.memory.dialogue), "outcome": None}
        self.goals.append(g)
        self.current = g
        self.memory.event(tick, "goal set", id=g["id"], instruction=g["instruction"], done=g["done"], source=g.get("source"))

    def quest(self) -> dict[str, Any] | None:
        """What the agent and the navigator get: {id, instruction, target?} with the target in navigator terms."""
        g = self.current
        if g is None:
            return None
        q = {"id": g["id"], "instruction": g["instruction"]}
        t = g.get("target")
        if isinstance(t, dict):
            if "toward" in t:
                q["target"] = {"toward": t["toward"]}
            elif "place" in t:
                q["target"] = {"map": _as_map(t["place"])}
            elif "line" in t and 0 <= t["line"] < len(self.memory.dialogue):
                d = self.memory.dialogue[t["line"]]
                if d.get("tile") is not None:
                    q["target"] = {"map": d["map"], "x": d["tile"][0], "y": d["tile"][1]}
        return q

    # ---- the writer -----------------------------------------------------------------------------------
    def context(self, values: dict[str, Any], world=None) -> dict[str, Any]:
        lines = self.memory.dialogue
        start = max(0, len(lines) - 25)
        places = []
        for k, p in self.memory.places.items():
            tiles = len(world.visited.get(_as_map(k), ())) if world is not None else None
            doors = sum(1 for kk, w in world.warps.items() if str(kk[0]) == k and str(w[0]) != k) if world is not None else None
            places.append({"id": _as_map(k), "first_seen_tick": p["first_tick"], "times_entered": p["entered"], "tiles_walked": tiles, "doors_found": doors})
        return {
            "now": {"place": values.get("map"), "screen": values.get("screen")},
            "dialogue": [{"i": start + i, "place": d.get("map"), "tick": d["tick"], "text": d["text"][:200]} for i, d in enumerate(lines[start:])],
            "places": places,
            "goals_so_far": [{"instruction": g["instruction"], "done": g["done"], "outcome": g["outcome"] or "current"} for g in self.goals[-8:]],
            "current_goal": ({"instruction": self.current["instruction"], "done": self.current["done"]} if self.current else None),
        }

    def _write(self, tick: int, values: dict[str, Any], world=None) -> None:
        self.calls += 1
        self.last_call = tick
        self.memory.new_lines = 0
        ctx = self.context(values, world)
        places = {str(p["id"]) for p in ctx["places"]}
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(ctx)}]
        entry: dict[str, Any] = {"tick": tick, "kind": "goal_writer", "dialogue_lines": len(ctx["dialogue"])}
        try:
            text, usage, ms = self.chat.complete(msgs, max_tokens=1500)
            self.latency_ms.append(ms)
            entry.update({"ms": ms, "answer": text[:600], "tokens": usage.get("total_tokens")})
            a = _json(text)
            same = self.current is not None and (a.get("goal") or {}).get("done") == self.current["done"] and \
                (a.get("goal") or {}).get("target") == self.current.get("target")
            if (a.get("keep") or same) and self.current is not None:
                entry["result"] = "kept"           # the same goal again keeps its start (what counts as new is unchanged)
                return
            goal = a.get("goal") or {}
            err = None if goal.get("instruction") else "no instruction"
            err = err or check(goal.get("done"), places) or check_target(goal.get("target"), places, len(self.memory.dialogue))
            if err:
                self.failures += 1
                entry["result"] = f"rejected: {err}"
                return
            t = goal.get("target")
            if isinstance(t, dict) and "line" in t:
                d = self.memory.dialogue[t["line"]]
                if d.get("tile") is None:
                    goal["target"] = None
            if self.current is not None:
                self._close(self.current, "replaced", tick)
            self._set({"instruction": str(goal["instruction"])[:160], "done": goal["done"], "target": goal.get("target"),
                       "ticks": max(40, min(400, int(goal.get("ticks") or self.give_up))), "why": str(a.get("why", ""))[:200],
                       "source": "writer"}, tick, values)
            entry["result"] = "set " + self.current["id"]
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            entry["result"] = f"error: {str(e)[:160]}"
        finally:
            if self.log is not None:
                self.log(entry)

    def dump(self) -> dict[str, Any]:
        return {"goals": self.goals, "current": self.current["id"] if self.current else None, "calls": self.calls,
                "failures": self.failures, "n": self.n, "latency_ms": self.latency_ms}

    def load(self, d: dict[str, Any]) -> None:
        self.goals = list(d.get("goals") or [])
        cur = d.get("current")
        self.current = next((g for g in self.goals if g["id"] == cur), None)
        self.calls = int(d.get("calls", 0))
        self.failures = int(d.get("failures", 0))
        self.n = int(d.get("n", len(self.goals)))
        self.latency_ms = list(d.get("latency_ms") or [])

    def report(self) -> dict[str, Any]:
        return {"calls": self.calls, "rejected_or_failed": self.failures,
                "median_ms": sorted(self.latency_ms)[len(self.latency_ms) // 2] if self.latency_ms else None,
                "goals": [{k: g.get(k) for k in ("id", "instruction", "done", "target", "source", "set_tick", "closed_tick", "outcome")} for g in self.goals]}


def _as_map(k: Any) -> Any:
    try:
        return int(k)
    except (TypeError, ValueError):
        return k
