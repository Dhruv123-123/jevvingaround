"""Jev frame by frame, with the vision model live behind it: two lanes that never wait on each other.

The typed agent (typed_screen.py) stops the game while it asks: the vision model names a new screen (seconds), then
the decider picks (Jev, ~400 ms). Here the game never waits.

- Slow lane: the vision model (the namer, Azure) runs on its own thread. The frame loop hands it every screen whose
  hash has no label yet; it labels the newest first (the one the player is looking at), drops ones it no longer
  needs, and writes each label to the blackboard. One call per new screen, as before; nothing waits for it.
- Blackboard: the labels (LabelCache, keyed by 8x8 block codes) and the subgoal each label carries, shared by both
  lanes under one lock.
"""
from __future__ import annotations
import threading
import time
from collections import deque
from typing import Any, Callable

import numpy as np

from .screen_agent import _png
from .typed_screen import NAME, LabelCache, parse_label

SUBGOAL = """
The agent's goal: %s
Add "subgoal" to the JSON: the next step toward that goal from exactly this screen, a few words."""


class Blackboard:
    """Labels by screen hash, written by the slow lane and read every frame by the fast one."""

    def __init__(self, labels: LabelCache | None = None):
        self.lock = threading.Lock()
        self.labels = labels if labels is not None else LabelCache()
        self.version = 0                  # bumps on every write: a reader can tell the board changed

    def find(self, b: np.ndarray) -> tuple[int | None, str]:
        with self.lock:
            return self.labels.find(b)

    def label(self, j: int | None) -> dict[str, Any]:
        if j is None:
            return {}
        with self.lock:
            return self.labels.labels[j]

    def write(self, b: np.ndarray, label: dict[str, Any]) -> int:
        with self.lock:
            j, how = self.labels.find(b)
            if how != "exact":
                j = self.labels.add(b, label)
            self.version += 1
            return j


class SlowLane:
    """The namer on its own thread. `want` never blocks: it queues a screen (newest first, at most `depth` waiting;
    the oldest are dropped, as the player has moved on) unless the board can already name it or it is queued."""

    def __init__(self, namer, board: Blackboard, effort: str = "low", depth: int = 3,
                 on_label: Callable[[int, dict[str, Any]], None] | None = None):
        self.namer, self.board, self.effort, self.depth = namer, board, effort, depth
        self.on_label = on_label
        self.q: deque = deque()
        self.queued: set[bytes] = set()
        self.cv = threading.Condition()
        self.stop = False
        self.calls, self.errors, self.dropped, self.cost = 0, 0, 0, 0.0
        self.ms: list[int] = []
        self.busy = False
        self.t = threading.Thread(target=self._run, daemon=True, name="slow-lane")
        self.t.start()

    def want(self, b: np.ndarray, img: np.ndarray, recent: list[np.ndarray] | None = None, goal: str = "") -> bool:
        key = b.tobytes()
        with self.cv:
            if key in self.queued:
                return False
            self.q.append((key, b.copy(), img.copy(), [r.copy() for r in (recent or [])[-2:]], goal))
            self.queued.add(key)
            while len(self.q) > self.depth:
                old = self.q.popleft()
                self.queued.discard(old[0])
                self.dropped += 1
            self.cv.notify()
        return True

    def idle(self) -> bool:
        with self.cv:
            return not self.q and not self.busy

    def _run(self) -> None:
        while True:
            with self.cv:
                while not self.q and not self.stop:
                    self.cv.wait()
                if self.stop:
                    return
                key, b, img, recent, goal = self.q.pop()          # newest first
                self.busy = True
            try:
                if self.board.find(b)[0] is None:                  # named meanwhile (a near screen): nothing to do
                    label = self._name(img, recent, goal)
                    if label:
                        j = self.board.write(b, label)
                        if self.on_label is not None:
                            self.on_label(j, label)
            finally:
                with self.cv:
                    self.queued.discard(key)
                    self.busy = False

    def _name(self, img: np.ndarray, recent: list[np.ndarray], goal: str) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"type": "text", "text": "Earlier screens, oldest first, then the one to label."}]
        for im in recent:
            parts.append({"type": "image_url", "image_url": {"url": _png(im, 2), "detail": "low"}})
        parts.append({"type": "image_url", "image_url": {"url": _png(img), "detail": "high"}})
        system = NAME + (SUBGOAL % goal if goal else "")
        t0 = time.perf_counter()
        try:
            before = self.namer.cost
            text, _, _ = self.namer.complete([{"role": "system", "content": system}, {"role": "user", "content": parts}],
                                             max_tokens=3000, extra={"reasoning_effort": self.effort})
            self.cost += self.namer.cost - before
            self.calls += 1
        except Exception:  # noqa: BLE001 - a failed label is a screen the explorer keeps until it is asked again
            self.errors += 1
            return {}
        finally:
            self.ms.append(int((time.perf_counter() - t0) * 1000))
        return parse_label(text)

    def close(self) -> None:
        with self.cv:
            self.stop = True
            self.cv.notify_all()
