"""Using things: a chain of choices toward a named outcome, found by playing chains out from a save state, and walls
tried again once the player has gained something.

Late in a long game, progress needs a thing used, not a place reached: a tree is cut with a move taught to a party
member, a guard lets you pass once you hold a drink, an item is withdrawn from a PC. Each is a chain of menu choices
(open a menu, pick an entry, pick another, confirm) whose end is an outcome the goal names. Nothing here knows a game:

  search    from now, open a menu (A at what the player faces, or START), and walk the menu tree breadth first: at
            each menu, the entries a direction reaches (the cursor's places), each picked with A, and the other
            buttons (B, SELECT, START: a pause menu that lists what each does), each played out until
            the game asks again (anygame/playout.py). A pick that leads to a new menu (one B backs out of: in the
            world B does nothing and directions walk) is a node to go deeper from; the
            first chain whose result passes `test` is returned with the exact presses and waits that replay it. The
            game is put back as it was.
  tests     `says(word, ...)`: a new line that tells of a gain (got, received, withdrew, learned ...) and names the
            words. `moves(pos, d)`: after the chain, a step in direction d moves the player (a wall that is no more).
  walls     `gains(lines)` finds lines that tell of a gain; `reopen(world)` makes the walls a world tracker had
            given up on worth one more bump, because what the player gained may be what opens them.

    from anygame.chains import search, says, moves, replay
    r = search(device, read_text, says("POTION"))      # {"found": True, "steps": [...], "trace": [...], ...}
    replay(device, r["trace"])                           # play the chain for real
"""
from __future__ import annotations
import re
from collections import deque
from typing import Any, Callable

import numpy as np

from .playout import _differs, _small, new_lines, play_out

# words in English game text that tell of something gained. A game in another language needs its own list
GAIN = re.compile(r"\b(got|gets|obtained|received|receives|learned|learns|learnt|withdrew|withdrawn|found|bought|"
                  r"picked up|took|now has|now have|gained|acquired|put away|taught|was given)\b", re.I)


# ---- recording and replaying ------------------------------------------------------------------------------------
class Recorder:
    """A device whose presses and waits are kept, so a chain found by search can be played again exactly. Everything
    else (snapshot, restore, branch, screen, memory) is the device's own; a branch restores, so it is not recorded."""

    def __init__(self, device):
        self._d = device
        self.trace: list[list] = []

    def press(self, k, hold=4, after=10):
        self.trace.append(["press", k, hold, after])
        return self._d.press(k, hold=hold, after=after)

    def wait(self, n):
        self.trace.append(["wait", n])
        return self._d.wait(n)

    def __getattr__(self, name):
        return getattr(self._d, name)

    def __setattr__(self, name, value):
        if name in ("_d", "trace"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._d, name, value)


def replay(device, trace: list[list]) -> None:
    for step in trace:
        if step[0] == "press":
            device.press(step[1], hold=step[2], after=step[3])
        else:
            device.wait(step[1])


# ---- a menu's entries -------------------------------------------------------------------------------------------
def entries(device, depth: int = 8, frames: int = 16, hold: int = 4, gap: int = 10,
            dirs: tuple[str, ...] = ("down", "right")) -> list[list[str]]:
    """The cursor places of the menu on screen: [] (where it is) and each place a direction reaches, pressed again
    and again until the cursor stops or comes round. A direction that changes nothing gives none."""
    snap = device.snapshot()
    try:
        device.wait(frames)
        shots = [device.screen()]
        device.restore(snap)
        out: list[list[str]] = [[]]
        for d in dirs:
            for n in range(1, depth + 1):
                device.restore(snap)
                for _ in range(n):
                    device.press(d, hold=hold, after=gap)
                device.wait(frames)
                img = device.screen()
                if any(not _differs(img, s) for s in shots):
                    break
                shots.append(img)
                out.append([d] * n)
    finally:
        device.restore(snap)
    return out


def backs(device, frames: int = 24) -> bool:
    """Whether B does something here: a menu or a prompt closes, while walking around B does nothing. A screen
    where the game asks but B changes nothing is the world, not a menu, and its directions walk."""
    out = device.branch({"b": ["b"], "wait": []}, frames=frames)
    return _differs(out["b"]["screen"], out["wait"]["screen"])


def _key(img: np.ndarray) -> bytes:
    return (_small(img)[::4, ::4] // 32).astype(np.uint8).tobytes()


# ---- tests ------------------------------------------------------------------------------------------------------
def gains(lines: list[str], *words: str) -> list[str]:
    """The lines that tell of a gain, and name every one of `words` (any case)."""
    ws = [w.lower() for w in words]
    return [t for t in lines if GAIN.search(t) and all(w in t.lower() for w in ws)]


def says(*words: str) -> Callable:
    """A test: the step's new text tells of a gain naming `words`."""
    def test(device, r, lines):
        # whole lines, not new_lines(): the thing gained is often on screen before the pick (the list it is taken from)
        return bool(gains([t for t in r["lines"] if t != r.get("text_before")], *words))
    test.__name__ = "says " + " ".join(words)
    return test


def moves(pos: Callable[[], Any], d: str, close: tuple[str, ...] = ("b", "b", "b"), hold: int = 16,
          after: int = 16) -> Callable:
    """A test: after the chain (and B pressed to close what is still open), a step in `d` changes the position."""
    def test(device, r, lines):
        for k in close:
            device.press(k, hold=4, after=10)
        p0 = pos()
        device.press(d, hold=hold, after=after)
        p1 = pos()
        return None not in (p0 or (None,)) and None not in (p1 or (None,)) and p1 != p0
    test.__name__ = f"moves {d}"
    return test


# ---- the search -------------------------------------------------------------------------------------------------
def search(device, read_text: Callable[[np.ndarray], str], test: Callable, *,
           openers: tuple[tuple[str, ...], ...] = (("a",), ("start",)), max_depth: int = 4, max_tries: int = 60,
           buttons: tuple[str, ...] = ("b", "select", "start"), max_frames: int = 900, hold: int = 4, gap: int = 10,
           log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Breadth-first over menu chains from now. Returns {found, steps, trace, lines, tries, frames}: `steps` names
    each pick (the opener, then cursor keys + A) with the text it led to; `trace` replays the chain. The game is put
    back as it was."""
    root = device.snapshot()
    disc, device.discoverer = getattr(device, "discoverer", None), None     # trying keys must not teach discovery
    seen = {_key(device.screen())}
    tries = 0
    frames = 0
    best: dict[str, Any] = {"found": False, "steps": [], "trace": [], "lines": [], "tries": 0}
    # a node: (state, trace to reach it, steps, lines so far)
    q: deque = deque([(root, [], [], [], 0)])
    first = True
    try:
        while q and tries < max_tries:
            snap, trace, steps, lines, depth = q.popleft()
            device.restore(snap)
            picks = ([list(o) for o in openers] if first else
                     [e + ["a"] for e in entries(device, hold=hold, gap=gap)] + [[b] for b in buttons])
            first = False
            for keys in picks:
                if tries >= max_tries:
                    break
                device.restore(snap)
                rec = Recorder(device)
                r = play_out(rec, keys, read_text, max_frames=max_frames, hold=hold, gap=gap, restore=False)
                tries += 1
                frames += r["frames"]
                said = new_lines(r)
                step = {"keys": keys, "said": said, "end": r["end"]}
                st = steps + [step]
                ln = lines + said
                here = device.snapshot()
                img = device.screen()
                ok = bool(test(device, r, ln))
                device.restore(here)
                if log:
                    log(f"{'  ' * depth}{'+'.join(keys)}: {' | '.join(said)[:100]} [{r['end']}]{' ✓' if ok else ''}")
                if ok:
                    best = {"found": True, "steps": st, "trace": trace + rec.trace, "lines": ln}
                    return {**best, "tries": tries, "frames": frames}
                k = _key(img)
                if r["end"] in ("asks", "waits") and k not in seen and depth + 1 < max_depth and backs(device):
                    seen.add(k)
                    q.append((here, trace + rec.trace, st, ln, depth + 1))
        return {**best, "tries": tries, "frames": frames}
    finally:
        device.restore(root)
        device.discoverer = disc


# ---- walls tried again after a gain -----------------------------------------------------------------------------
def reopen(world, forget_after: int | None = None) -> int:
    """Make every wall a world tracker had given up on (bumped three times) worth one more bump: the next plan treats
    it as open and a bump marks it given-up again. Returns how many."""
    fa = int(forget_after if forget_after is not None else world.r.get("forget_after", 150))
    n = 0
    for k, b in world.blocked.items():
        if b[0] >= 3:
            b[0] = 2
            b[1] = world.steps - fa - 1
            n += 1
    world.walls_at.clear()
    return n


class Gains:
    """Watches the text a run reads; when a line tells of a new gain, reopens the world's walls. One call per tick:

        g = Gains(world); g.see(values.get("text", ""))      # → the new gain lines, if any
    """

    def __init__(self, world=None):
        self.world = world
        self.had: list[str] = []
        self.last: set[str] = set()
        self.reopened = 0

    def see(self, text: str) -> list[str]:
        now = set(gains([text or ""]))
        new = sorted(now - self.last)           # a gain line counts once while it stays on screen
        self.last = now
        if new:
            self.had.extend(new)
            if self.world is not None:
                self.reopened += reopen(self.world)
        return new
