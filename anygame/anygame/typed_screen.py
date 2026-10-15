"""The screen-only agent with a typed decider: the vision model names screens, Jev or OpenAI Decisions picks.

ScreenAgent asks a vision chat model what to press whenever exploring goes stale; that is a VLM playing the game.
Here the two jobs are split:

- The namer (Azure vision model) sees a screen only when no screen like it has been named before, and writes a label:
  what kind of screen it is, where it is, the words on it, what is where, and a few things a player could do there,
  each with its presses. Labels are cached by the screen's hash (8x8 block codes, as Nodes uses); a screen whose
  blocks match a named one, exactly or after a scroll of up to two blocks, borrows that label and costs nothing.
- The decider (typed: OpenAI Decisions or Jev, through anygame.sensors.open_sensor) is asked at the moments
  ScreenAgent would have asked the advisor. Its state is text built from the cache and the screen graph: the goal,
  this screen's label, the last few screens' labels, what each d-pad button has done from here, and how the last
  choices turned out. It answers two typed questions: which option to take (the label's actions, a walk each way,
  or "explore") and which way the goal lies (the explorer leans that way, as with the advisor's heading).

No RAM, no per-game code: the same agent runs the held-out games. Pick the decider with decider="openai" or "jev".
"""
from __future__ import annotations
import json
from typing import Any

import numpy as np

from .screen_agent import BUTTONS, ScreenAgent, _png, blocks, parse_presses

NAME = """You label screens of a video game for an agent that cannot see. It sees only the screen and presses the
console's buttons: up, down, left, right, a, b, start, select. Describe this one screen (the last picture; the
earlier ones show how it got here) so the agent can decide what to do next. Do not decide for it.

Answer with JSON only:
{"kind": "title|menu|dialogue|battle|map|other", "where": "<the place or screen, a few words>",
 "text": "<the words on screen, if any>", "see": ["<a thing and where it is from the player, e.g. 'door 3 steps up'>", ...],
 "options": [{"do": "<what this does, a few words>", "presses": ["up*3", "a"]}, ...]}
Give 2 to 6 options: the distinct useful things a player could do from exactly this screen (leave by each exit, talk
to someone, pick each menu entry, advance or close a text box, use each attack). Presses are in order, "up*3" means up
three times, at most 12 presses an option. If you recognise the game, use its names for places and things."""

DIRS = ("up", "down", "left", "right")


class LabelCache:
    """Screen labels keyed by the screen's block codes. `get` answers from the cache when it can: an exact hash, a
    near match (at most `near` of blocks differ), or on map screens a near match after a scroll of up to `shift`
    blocks. Menus, fights and dialogue need a close match (`near_ui`): a moved cursor changes the right presses."""

    def __init__(self, near: float = 0.08, near_ui: float = 0.03, shift: int = 2):
        self.near, self.near_ui, self.shift = near, near_ui, shift
        self.exact: dict[bytes, int] = {}
        self.codes: list[np.ndarray] = []
        self.labels: list[dict[str, Any]] = []
        self.hits = {"exact": 0, "near": 0, "scroll": 0, "new": 0}

    def find(self, b: np.ndarray) -> tuple[int | None, str]:
        raw = b.tobytes()
        if raw in self.exact:
            return self.exact[raw], "exact"
        if not self.codes:
            return None, "new"
        mat = np.stack(self.codes)
        diff = (mat != b[None]).mean(axis=(1, 2))
        j = int(diff.argmin())
        tol = self.near if self.labels[j].get("kind") == "map" else self.near_ui
        if diff[j] <= tol:
            return j, "near"
        maps = [i for i, l in enumerate(self.labels) if l.get("kind") == "map"]
        if not maps or not self.shift:
            return None, "new"
        sub = mat[maps]
        h, w = b.shape
        best, top = None, 1.0
        for dy in range(-self.shift, self.shift + 1):
            for dx in range(-self.shift, self.shift + 1):
                if not dx and not dy:
                    continue
                # the part of this screen that the labelled screen also shows, if the view scrolled by (dx, dy) blocks
                a = b[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)]
                o = sub[:, max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]
                d = (o != a[None]).mean(axis=(1, 2))
                k = int(d.argmin())
                if d[k] < top:
                    best, top = maps[k], float(d[k])
        if best is not None and top <= self.near:
            return best, "scroll"
        return None, "new"

    def add(self, b: np.ndarray, label: dict[str, Any]) -> int:
        self.codes.append(b.copy())
        self.labels.append(label)
        self.exact[b.tobytes()] = len(self.labels) - 1
        return len(self.labels) - 1


def parse_label(text: str) -> dict[str, Any]:
    try:
        d = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, AttributeError):
        return {}
    opts = []
    for o in (d.get("options") or [])[:6]:
        if not isinstance(o, dict):
            continue
        presses, _ = parse_presses(json.dumps({"presses": o.get("presses") or []}), BUTTONS)
        if presses:
            opts.append({"do": str(o.get("do") or "")[:80], "presses": presses[:12]})
    kind = str(d.get("kind") or "other").lower().strip()
    return {"kind": kind if kind in ("title", "menu", "dialogue", "battle", "map", "other") else "other",
            "where": str(d.get("where") or "")[:80], "text": str(d.get("text") or "")[:200],
            "see": [str(s)[:80] for s in (d.get("see") or [])][:8], "options": opts}


def _short(presses: list[str]) -> str:
    out, i = [], 0
    while i < len(presses):
        j = i
        while j < len(presses) and presses[j] == presses[i]:
            j += 1
        out.append(presses[i] + (f"*{j - i}" if j - i > 1 else ""))
        i = j
    return " ".join(out)


class TypedScreenAgent(ScreenAgent):
    def __init__(self, device, decider, namer=None, labels: LabelCache | None = None, walk: int = 4,
                 generic_goal: str = "make progress in the game: get past menus and text, reach new places", **kw):
        # the namer is the chat model ScreenAgent calls its advisor; here it only labels screens
        super().__init__(device, advisor=namer or kw.pop("advisor", None), **kw)
        self.decider = decider
        self.labels = labels if labels is not None else LabelCache()
        self.walk = walk
        self.generic_goal = generic_goal
        self.trail: list[str] = []            # the last few distinct screens' labels, as short text
        self.label_cost, self.decide_cost, self.label_calls, self.decide_calls = 0.0, 0.0, 0, 0
        if self.advisor is None:
            # with no namer, the decider still has the graph; nothing is ever sent to it
            self.advisor = _NoNamer()

    # ScreenAgent calls _ask when exploring has gone stale (or every `every` presses in a place)
    def _ask(self, img: np.ndarray, node: str) -> None:
        self.asked[node] += 1
        stale, self.since_new = self.since_new, 0
        self.since_ask = 0
        entry: dict[str, Any] = {"node": node, "states_at": len(self.visits)}
        label = self._label(img, entry)
        state, opts = self._state(label, node, stale)
        qs = {
            "do": {"type": "choice", "instructions": "Which option makes the most progress toward the goal from this "
                   "screen? Prefer an option that leads somewhere new or that the screen's text asks for; avoid options "
                   "that led nowhere before.", "criteria": {k: v["desc"] for k, v in opts.items()}},
            "heading": {"type": "choice", "instructions": "On a map screen, which screen direction does the goal lie in "
                        "from here? 'none' in menus, fights and text, or when it is in no particular direction.",
                        "criteria": {"up": "toward the top of the screen", "down": "toward the bottom", "left": "toward the "
                                     "left", "right": "toward the right", "none": "no particular direction"}},
        }
        try:
            r = self.decider.ask(state, qs)
            self.decide_calls += 1
            usd = float(r.get("cost_usd") or 0.0)
            self.decide_cost += usd
            self.total_cost += usd
            ans = r["answers"]
            pick = (ans.get("do") or {}).get("choice")
            o = opts.get(pick) or opts["explore"]
            self.queue = list(o["presses"])
            h = (ans.get("heading") or {}).get("choice")
            self.heading = h if h in DIRS and label.get("kind") in ("map", None) else None
            entry.update(presses=self.queue, why=o["desc"][:200], pick=pick, heading=self.heading,
                         goal=self.goal or None, ms=r.get("latency_ms"),
                         conf=(ans.get("do") or {}).get("confidence"))
        except Exception as e:  # noqa: BLE001 - a failed call costs one chance, not the run
            self.errors += 1
            entry["error"] = str(e)[:200]
        self.advice.append(entry)

    def _label(self, img: np.ndarray, entry: dict[str, Any]) -> dict[str, Any]:
        b = blocks(img)
        j, how = self.labels.find(b)
        self.labels.hits[how] += 1
        entry["label"] = how
        if j is not None:
            return self.labels.labels[j]
        if isinstance(self.advisor, _NoNamer):
            return {}
        parts: list[dict[str, Any]] = [{"type": "text", "text": "Earlier screens, oldest first, then the one to label."}]
        for im in self.recent[:-1] if len(self.recent) > 1 else []:
            parts.append({"type": "image_url", "image_url": {"url": _png(im, 2), "detail": "low"}})
        parts.append({"type": "image_url", "image_url": {"url": _png(img), "detail": "high"}})
        try:
            before = self.advisor.cost
            text, _, _ = self.advisor.complete([{"role": "system", "content": NAME}, {"role": "user", "content": parts}],
                                               max_tokens=3000, extra={"reasoning_effort": self.effort})
            usd = self.advisor.cost - before
            self.label_cost += usd
            self.total_cost += usd
            self.label_calls += 1
            label = parse_label(text)
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            entry["label_error"] = str(e)[:200]
            return {}
        if label:
            self.labels.add(b, label)
        return label

    def _moves(self, node: str) -> dict[str, str]:
        """What each d-pad button has done from this state, from the screen graph."""
        state = getattr(self, "here", node)
        out = {}
        for d in DIRS:
            outs = self.edges.get(state, {}).get(d)
            if not outs:
                out[d] = "not tried from here"
                continue
            n = sum(outs.values())
            same = outs.get(state, 0)
            new = sum(c for s, c in outs.items() if s != state and self.visits[s] <= 2)
            out[d] = (f"tried {n}x: blocked {same}x" + (f", reached little-seen places {new}x" if new else "")
                      + (", moved to places seen before" if n - same - new > 0 else ""))
        return out

    def _state(self, label: dict[str, Any], node: str, stale: int = 0) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        opts: dict[str, dict[str, Any]] = {}
        for i, o in enumerate(label.get("options") or []):
            opts[f"o{i + 1}"] = {"presses": o["presses"], "desc": f"{o['do']} ({_short(o['presses'])})"}
        moves = self._moves(node)
        if label.get("kind", "map") in ("map", "other") or not label:
            for d in DIRS:
                opts[f"walk_{d}"] = {"presses": [d] * self.walk, "desc": f"walk {d} {self.walk} steps; from here: {moves[d]}"}
        opts.setdefault("press_a", {"presses": ["a"], "desc": "press A once (talk, confirm, advance text)"})
        opts.setdefault("press_b", {"presses": ["b"], "desc": "press B once (cancel, back out of a menu)"})
        opts["explore"] = {"presses": [], "desc": "let the explorer try untried buttons and places for a while"}
        recent = []
        for e in self.advice[-5:]:
            if e.get("pick"):
                recent.append(f"{e['why'][:60]} -> " + ("found something new" if e.get("new") else "found nothing new"))
        here = (label.get("where") or "") + (f" ({label['kind']})" if label.get("kind") else "")
        if here and (not self.trail or self.trail[-1] != here):
            self.trail = (self.trail + [here])[-6:]
        state = {
            "goal": self.goal or self.generic_goal,
            "screen": {k: label[k] for k in ("kind", "where", "text", "see") if label.get(k)} or "unlabelled",
            "recent screens, oldest first": self.trail[:-1],
            "progress": {"presses without finding a new place": stale,
                         "screens seen": len(self.nodes.ids), "times on this screen": self.visits.get(node, 0)},
            "last choices, oldest first": recent,
        }
        return state, opts

    def summary(self) -> dict[str, Any]:
        return {"label_calls": self.label_calls, "label_usd": round(self.label_cost, 4), "decide_calls": self.decide_calls,
                "decide_usd": round(self.decide_cost, 5), "cache": dict(self.labels.hits), "labels": len(self.labels.labels)}


class _NoNamer:
    cost = 0.0


def screen_agent(device, seed: int = 0, advisor=None, decider: str | None = None, labels: LabelCache | None = None, **kw):
    """ScreenAgent, or with `decider` ("openai", "openai:<model>", "jev") the typed-decider agent with `advisor` as its
    namer. Any decider other than Jev runs off OpenRouter, by the project's rule."""
    if not decider:
        return ScreenAgent(device, seed=seed, advisor=advisor, **kw)
    from .sensors import open_sensor
    return TypedScreenAgent(device, open_sensor(decider, timeout=20), namer=advisor, labels=labels, seed=seed, **kw)
