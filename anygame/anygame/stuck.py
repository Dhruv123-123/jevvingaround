"""Noticing a stall: the agent doing the same things on the same screens with nothing new turning up. Nothing here
knows a game.

The live Pokemon run lost about $0.16 to three stalls it did not notice: Oak's "Hey! Don't go away yet!" sent the
player back about 80 times before the starter, a battle's move menu was read as the world and walked "down" for
1,700 ticks, and walks pushed back after a conversation. In each, the screens and positions cycled through a handful
of states the run had already seen, and the actions came from a short list.

What the detector sees is what the agent sees, never the grader:

  - an observation each step: the screen kind, the text read, the found position and map (any may be missing), and,
    when given, the frame. The frame is reduced to a coarse fingerprint (block means, a few grey levels) so a cursor
    moving between the same entries, or an idle animation, keeps cycling through the same few prints;
  - the action taken.

A step is **new** when its observation (or its frame's fingerprint) has not been seen in the run before. A stall is
`window` steps with at most `allow_new` new steps, in which the actions taken are at most `max_actions` different
ones. Exploring keeps finding positions, a conversation keeps finding text, a scrolling level keeps finding frames;
a loop finds none.

    stuck = Stuck()
    s = stuck.see(tick, action, kind=..., text=..., pos=(x, y, map), frame=img)    # every step
    if s: s["repeated"], s["since"], stuck.suggest(options)    # what to try instead, in order
"""
from __future__ import annotations
from collections import Counter, deque
from typing import Any, Iterable

import numpy as np


def fingerprint(frame: np.ndarray, blocks: tuple[int, int] = (18, 20), levels: int = 4) -> bytes:
    """A coarse print of a frame: the mean grey of each block, in a few levels. Small changes inside a block (a cursor
    glyph, a blinking arrow) rarely move a block across a level; a scroll or a new scene moves many."""
    g = frame.astype(np.float32)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)
    h, w = g.shape
    by, bx = blocks
    g = g[: h - h % by, : w - w % bx].reshape(by, h // by, bx, w // bx).mean(axis=(1, 3))
    return (np.clip(g, 0, 255) * levels // 256).astype(np.uint8).tobytes()


class Stuck:
    def __init__(self, window: int = 40, allow_new: int = 2, max_actions: int = 4, quiet: int = 20):
        self.window = window            # steps looked back over
        self.allow_new = allow_new      # new observations a stall may still have (a misread, a blink)
        self.max_actions = max_actions  # different actions a stall may take (a loop of walk, talk, page on)
        self.quiet = quiet              # steps after a raise before raising again (the break needs room to work)
        self.seen: set = set()
        self.prints: set = set()
        self.recent: deque = deque(maxlen=window)        # (tick, action, new?, observation key)
        self.raised_at: int | None = None
        self.events: list[dict[str, Any]] = []

    @staticmethod
    def _action(a: Any) -> str:
        """The action without the details that differ between repeats of the same choice ("explore_down: down
        left down → stop: ..." is explore_down)."""
        s = str(a or "")
        return s if s.startswith("auto") else s.split(":", 1)[0].strip()

    def see(self, tick: int, action: Any, kind: str | None = None, text: str | None = None,
            pos: Iterable | None = None, frame: np.ndarray | None = None) -> dict[str, Any] | None:
        key = (kind, (text or "").strip(), tuple(pos) if pos is not None else None)
        new = key not in self.seen
        self.seen.add(key)
        if frame is not None:
            fp = fingerprint(frame)
            # a frame never seen is news even when the reads say nothing (a platformer with no text or position)
            if fp not in self.prints:
                new = True
                self.prints.add(fp)
        act = self._action(action)
        self.recent.append((tick, act, new, key))
        if len(self.recent) < self.window:
            return None
        if self.raised_at is not None and tick - self.raised_at < self.quiet:
            return None
        fresh = sum(1 for r in self.recent if r[2])
        acts = Counter(r[1] for r in self.recent)
        if fresh > self.allow_new or len(acts) > self.max_actions:
            return None
        self.raised_at = tick
        states = Counter(r[3] for r in self.recent)
        out = {"tick": tick, "since": self.recent[0][0], "repeated": [a for a, _ in acts.most_common()],
               "counts": dict(acts), "states": len(states), "new": fresh}
        self.events.append(out)
        return out

    def suggest(self, options: Iterable[str]) -> list[str]:
        """What to try instead, in order: the options on offer this step that the stall did not take (in the order
        offered), then B, then the repeated ones last. A caller with play-outs can try each of these from a save state
        and keep the first that changes the screen."""
        took = {r[1] for r in self.recent}
        opts = [str(o) for o in options]
        untried = [o for o in opts if self._action(o) not in took and o not in took]
        tried = [o for o in opts if o not in untried]
        return untried + ["press B"] + tried
