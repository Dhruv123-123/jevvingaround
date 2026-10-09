"""A screen-only agent: pixels in, buttons out, nothing about the game.

The agent's whole world model is a graph of screens it has seen. A node is a screen fingerprint (the frame shrunk and
its colours coarsened, so a blinking cursor or a moving sprite a few pixels over does not make a new node too
often); an edge is a button pressed on that screen and the screens it led to. It plays to see new screens, the way a
person pokes at an unknown game:

- On a screen it has seen, each button is worth the novelty of where it led before (a screen seen n times is worth
  1/sqrt(n)), plus an exploration bonus for buttons tried rarely there.
- On a new screen, a button is worth what it has been worth on average everywhere so far (a running novelty yield
  per button), so a game where the d-pad opens up the world and Start only pauses teaches that within a minute.
- A press that changed nothing is worth nothing; a little randomness keeps it from looping.

No RAM, no tile ids, no per-game code. The device gives frames and takes presses; the grader (if any) is elsewhere.

    agent = ScreenAgent(device, seed=1)
    while True:
        rec = agent.step()          # {"action": "right", "choice": {...}}
"""
from __future__ import annotations
import hashlib
import math
import random
from collections import Counter, defaultdict
from typing import Any

import cv2
import numpy as np

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
# a prior on how often each button is worth trying before the agent has seen anything (as a person would: the pad
# and A first, Start rarely, Select almost never)
PRIOR = {"up": 1.0, "down": 1.0, "left": 1.0, "right": 1.0, "a": 1.0, "b": 0.6, "start": 0.3, "select": 0.1}


def native(frame_bgr: np.ndarray, size: tuple[int, int] = (160, 144)) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    if (w, h) != size:
        frame_bgr = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_NEAREST)
    return np.ascontiguousarray(frame_bgr[:, :, :3][:, :, ::-1])


def blocks(img: np.ndarray, cell: int = 8, levels: int = 4) -> np.ndarray:
    """The screen shrunk `cell` times (block means), grey levels cut to `levels`: one small code per 8x8 block."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(g, (g.shape[1] // cell, g.shape[0] // cell), interpolation=cv2.INTER_AREA)
    return (small.astype(np.int32) * levels // 256).astype(np.uint8)


def fingerprint(img: np.ndarray, cell: int = 4, levels: int = 4) -> str:
    return hashlib.blake2b(blocks(img, cell, levels).tobytes(), digest_size=8).hexdigest()


class Nodes:
    """Screens as nodes, matched with tolerance: a screen whose blocks differ from a known node's on at most `tol`
    of them is that node (a sprite walking across a still room, a title screen's animation). Known nodes are kept in
    a matrix and compared all at once; the exact hash is tried first."""

    def __init__(self, tol: float = 0.06, cap: int = 5000):
        self.tol, self.cap = tol, cap
        self.exact: dict[bytes, str] = {}
        self.ids: list[str] = []
        self.mat = np.zeros((0, 1), np.uint8)

    def __call__(self, img: np.ndarray) -> str:
        b = blocks(img)
        raw = b.tobytes()
        if raw in self.exact:
            return self.exact[raw]
        flat = b.reshape(1, -1)
        if self.mat.shape[0] and self.mat.shape[1] == flat.shape[1]:
            d = (self.mat != flat).sum(axis=1)
            j = int(d.argmin())
            if d[j] <= self.tol * flat.shape[1]:
                self.exact[raw] = self.ids[j]
                return self.ids[j]
        nid = hashlib.blake2b(raw, digest_size=8).hexdigest()
        self.exact[raw] = nid
        if len(self.ids) < self.cap:
            self.ids.append(nid)
            self.mat = flat.copy() if not self.mat.shape[0] or self.mat.shape[1] != flat.shape[1] else np.vstack([self.mat, flat])
        return nid


class ScreenAgent:
    def __init__(self, device, seed: int = 0, buttons=BUTTONS, epsilon: float = 0.1, bonus: float = 0.5):
        self.dev = device
        self.rng = random.Random(seed)
        self.buttons = list(buttons)
        self.epsilon = epsilon
        self.bonus = bonus
        self.nodes = Nodes()
        self.visits: Counter = Counter()                                  # node → times seen
        self.edges: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))   # node → button → next nodes
        self.yield_: dict[str, list[float]] = {b: [PRIOR[b], 1.0] for b in self.buttons}       # button → [sum, n]
        self.last: tuple[str, str] | None = None
        self.total_cost = 0.0
        self.errors = 0
        self.goalbook = None

    def novelty(self, node: str) -> float:
        return 1.0 / math.sqrt(1 + self.visits[node])

    def _value(self, node: str, b: str) -> float:
        outs = self.edges[node][b] if node in self.edges else None
        prior = self.yield_[b][0] / self.yield_[b][1]
        if not outs:
            return prior + self.bonus
        n = sum(outs.values())
        nov = sum(c * (0.0 if nxt == node else self.novelty(nxt)) for nxt, c in outs.items()) / n
        total = sum(sum(o.values()) for o in self.edges[node].values())
        return nov + self.bonus * math.sqrt(math.log(1 + total) / n) * 0.5

    def choose(self, node: str) -> str:
        if self.rng.random() < self.epsilon:
            return self.rng.choices(self.buttons, [PRIOR[b] for b in self.buttons])[0]
        vals = {b: self._value(node, b) for b in self.buttons}
        top = max(vals.values())
        best = [b for b, v in vals.items() if v >= top - 1e-9]
        return self.rng.choice(best)

    def step(self) -> dict[str, Any]:
        img = native(self.dev.frame())
        node = self.nodes(img)
        if self.last is not None:
            prev, b = self.last
            gain = 0.0 if node == prev else self.novelty(node)
            self.edges[prev][b][node] += 1
            s = self.yield_[b]
            s[0] += gain
            s[1] += 1
        self.visits[node] += 1
        b = self.choose(node)
        self.dev.press(b)
        self.last = (node, b)
        return {"action": b, "choice": {"node": node, "nodes": len(self.visits)}}

    def close(self) -> None:
        pass
