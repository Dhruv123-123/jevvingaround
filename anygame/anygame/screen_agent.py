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

    def __init__(self, tol: float = 0.03, cap: int = 5000):
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


ADVICE = """You are helping an agent play a video game it has never seen. It sees only the screen and can press the
console's buttons: up, down, left, right, a, b, start, select. It has been exploring by trying buttons and has stopped
finding anything new. Look at the screen (and the earlier screens, oldest first, if given) and say what a person
would do next to make progress in the game: get past a title or menu, finish a dialogue, walk to an exit, door,
stairs, person or item that has not been visited, or start the actual game. Answer with JSON only:
{"why": "<one short sentence>", "presses": ["right", "right", "a", ...]}
with 1 to 12 presses, in order. Prefer a few deliberate presses toward one goal over many random ones."""


def _png(img_rgb: np.ndarray, scale: int = 3) -> str:
    import base64
    big = cv2.resize(img_rgb[:, :, ::-1], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", big)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def parse_presses(text: str, buttons) -> tuple[list[str], str]:
    import json
    try:
        d = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, AttributeError):
        return [], ""
    ps = [str(p).lower().strip() for p in (d.get("presses") or []) if str(p).lower().strip() in buttons]
    return ps[:12], str(d.get("why") or "")[:200]


class ScreenAgent:
    def __init__(self, device, seed: int = 0, buttons=BUTTONS, epsilon: float = 0.1, bonus: float = 0.5,
                 place_weight: float = 1.0, place_cell: int = 0, settle: int = 3,
                 frontier: bool = True, advisor=None, stuck: int = 30, max_advice: int = 150,
                 advice_per_screen: int = 2):
        self.place_cell = place_cell
        self.settle = settle
        self.frontier = frontier
        # the advisor (a chat model, Azure): asked only when exploring has stopped finding new states for `stuck`
        # presses, at most `advice_per_screen` times per screen and `max_advice` times in all; its presses are played
        # in order, then exploring resumes
        self.advisor, self.stuck, self.max_advice, self.advice_per_screen = advisor, stuck, max_advice, advice_per_screen
        self.advice: list[dict[str, Any]] = []
        self.asked: Counter = Counter()
        self.queue: list[str] = []
        self.since_new = 0
        self.recent: list[np.ndarray] = []
        self.effect: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # kind → button → [tries, changed]
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
        # odometry (press-and-watch): the camera's place in the current room, from how the picture scrolled, plus the
        # player's place on screen when it is known; a room starts at every scene change and is named by its first
        # screen. New places are novelty too, so walking into unseen ground counts even where screens never repeat.
        from .perceive.watch import Watcher
        self.watch = Watcher() if place_weight else None
        self.place_weight = place_weight
        self.room: str | None = None
        self.cam = [0, 0]
        self.prev_img: np.ndarray | None = None
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

    def _open(self, state: str) -> list[str]:
        """Buttons still worth a first try here: never pressed, or pressed once and nothing happened (a first press
        can only turn the player to face that way). Start and Select are left to chance."""
        e = self.edges.get(state, {})
        kind = self._kind(state)
        out = []
        for b in self.buttons:
            if PRIOR[b] < 0.5:
                continue
            tries, changed = self.effect[kind][b]
            if tries >= 15 and changed < 0.1 * tries:
                continue          # in this kind of state (walking, or a screen) this button has almost never done anything
            outs = e.get(b)
            if not outs or (sum(outs.values()) < 2 and set(outs) == {state}):
                out.append(b)
        return out

    @staticmethod
    def _kind(state: str) -> str:
        return "place" if "@" in state else "screen"

    def _plan(self, state: str, limit: int = 4000) -> str | None:
        """The first button on the shortest known way to a state with a button still to try (each press assumed to
        lead where it led most often)."""
        from collections import deque
        seen = {state}
        q = deque([(state, None)])
        while q and len(seen) < limit:
            s, first = q.popleft()
            if first is not None and self._open(s):
                return first
            for b, outs in self.edges.get(s, {}).items():
                if not outs:
                    continue
                nxt = outs.most_common(1)[0][0]
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, first or b))
        return None

    def choose(self, node: str) -> str:
        if self.rng.random() < self.epsilon:
            return self.rng.choices(self.buttons, [PRIOR[b] for b in self.buttons])[0]
        if self.frontier:
            open_ = self._open(node)
            if open_:
                return self.rng.choices(open_, [PRIOR[b] for b in open_])[0]
            b = self._plan(node)
            if b is not None:
                return b
        vals = {b: self._value(node, b) for b in self.buttons}
        top = max(vals.values())
        best = [b for b, v in vals.items() if v >= top - 1e-9]
        return self.rng.choice(best)

    def step(self) -> dict[str, Any]:
        img = native(self.dev.frame())
        node = self.nodes(img)
        # let a transition (a fade, a menu sliding in) finish before judging the press: up to `settle` more looks,
        # until the screen stays the same node
        for _ in range(self.settle):
            nxt = native(self.dev.frame())
            nn = self.nodes(nxt)
            img, same, node = nxt, nn == node, nn
            if same:
                break
        place = self._where(img, node)
        # the state: where the player stands in this room when it is found, else the screen itself (a menu, a title)
        state = place if place is not None else node
        if self.last is not None:
            prev, b = self.last
            gain = 0.0 if state == prev else self.novelty(state)
            self.edges[prev][b][state] += 1
            eff = self.effect[self._kind(prev)][b]
            eff[0] += 1
            eff[1] += state != prev
            y = self.yield_[b]
            y[0] += gain
            y[1] += 1
        self.since_new = 0 if self.visits[state] == 0 else self.since_new + 1
        self.visits[state] += 1
        if not self.recent or self.nodes(self.recent[-1]) != node:
            self.recent = (self.recent + [img])[-3:]
        how = "explore"
        if not self.queue and self.advisor is not None and self.since_new >= self.stuck and \
                len(self.advice) < self.max_advice and self.asked[node] < self.advice_per_screen:
            self._ask(img, node)
        if self.advice and "states_at" in self.advice[-1] and "new" not in self.advice[-1] and not self.queue:
            self.advice[-1]["new"] = len(self.visits) > self.advice[-1]["states_at"]
        if self.queue:
            b, how = self.queue.pop(0), "advice"
        else:
            b = self.choose(state)
        self.dev.press(b)
        self.last = (state, b)
        return {"action": b, "choice": {"node": node, "place": place, "states": len(self.visits), "how": how},
                "cost_usd": self.total_cost}

    def _ask(self, img: np.ndarray, node: str) -> None:
        self.asked[node] += 1
        self.since_new = 0
        # what earlier advice did: so it does not send the player back where it already went for nothing
        notes = []
        for e in self.advice[-5:]:
            if e.get("why"):
                notes.append(f"- {e['why']} ({' '.join(e.get('presses') or [])}): "
                             + ("found something new" if e.get("new") else "found nothing new"))
        seen_here = self.visits.get(node, 0)
        head = (f"Screens seen so far: {len(self.nodes.ids)}. This screen has been seen {seen_here} times.\n"
                + ("Your earlier advice, oldest first:\n" + "\n".join(notes) + "\n" if notes else "")
                + "Earlier screens, oldest first, then the current one.")
        parts: list[dict[str, Any]] = [{"type": "text", "text": head}]
        for im in self.recent[:-1] if len(self.recent) > 1 else []:
            parts.append({"type": "image_url", "image_url": {"url": _png(im, 2), "detail": "low"}})
        parts.append({"type": "image_url", "image_url": {"url": _png(img), "detail": "high"}})
        msgs = [{"role": "system", "content": ADVICE}, {"role": "user", "content": parts}]
        entry: dict[str, Any] = {"node": node, "states_at": len(self.visits)}
        try:
            before = self.advisor.cost
            text, usage, ms = self.advisor.complete(msgs, max_tokens=3000, extra={"reasoning_effort": "low"})
            self.total_cost += self.advisor.cost - before
            presses, why = parse_presses(text, self.buttons)
            entry.update(presses=presses, why=why, ms=ms)
            self.queue = list(presses)
        except Exception as e:  # noqa: BLE001 - a failed call costs one chance, not the run
            self.errors += 1
            entry["error"] = str(e)[:200]
        self.advice.append(entry)

    def _where(self, img: np.ndarray, node: str) -> str | None:
        """Move the odometer by what the last press did; return the player's place (room, cell) as a key, or None
        when the player is not found on this frame."""
        if self.watch is None:
            return None
        prev, self.prev_img = self.prev_img, img
        if prev is None:
            self.room = node
            return None
        eff = self.watch.see(prev, self.last[1] if self.last else None, img)
        if eff.scene:
            self.room, self.cam = node, [0, 0]
        else:
            self.cam[0] -= eff.shift[0]
            self.cam[1] -= eff.shift[1]
        box = self.watch.box(within=self.settle + 3)
        if box is None:
            return None
        # a place is one step of the player's (as press-and-watch measured it) on a side
        cell = self.place_cell or max(8, self.watch.steps.most_common(1)[0][0] if self.watch.steps else 16)
        px, py = self.cam[0] + box[0] + box[2] // 2, self.cam[1] + box[1] + box[3] // 2
        return f"{self.room}@{px // cell},{py // cell}"

    def close(self) -> None:
        pass
