"""Online discovery of a game's state from its RAM, while it is being played: the agent's own state, never a
disassembly's map (the published one, where there is one, is the grader's).

The device hands every button press here with work RAM before and after it, and every rendered frame with RAM and
whether the screen was blank (a fade). From those alone:

  position  the byte (or little-endian pair) that rises on right and falls on left and holds on up and down: x; the
            same for down and up: y. `cell` is its typical change for one press: 1 for a tile-stepping game, the
            step in pixels for a free-moving one.
  map       the bytes that change across a transition (a blank screen, or the position jumping) and never while
            walking. Several bytes change when a map loads (its id, bank, size, script pointer); together they are
            a map's signature, and the signature is the map id the world memory keys on.

Nothing here knows any game. What it finds is a data file (`discovered.yaml`) that a later run starts from.
"""
from __future__ import annotations
import json
from typing import Any
import numpy as np

LO, HI = 0xC000, 0xE000
MOVED = 0.2         # a position byte moves on at least this share of its axis's presses (walls and turns take the rest)
HOLD_WALKS = 6      # a map value holds while the player walks at least this many moves (a step's bytes hold for one)
RING = 16           # frames back that a burst is measured against
BURST_MIN, BURST_X = 150, 2.5   # a burst: at least this many bytes changed over RING frames, and this many times the usual
WINDOW = 40          # events (rendered frames and presses) around a transition in which a map's bytes change
N = HI - LO
DIRS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


def ram(mem) -> np.ndarray:
    try:
        return np.asarray(mem[LO:HI], dtype=np.int32)
    except TypeError:
        return np.array([mem[a] for a in range(LO, HI)], dtype=np.int32)


def _z(a: np.ndarray) -> bytes:
    import zlib
    return zlib.compress(a.astype(np.uint8).tobytes(), 1)


def _unz(b: bytes) -> np.ndarray:
    import zlib
    return np.frombuffer(zlib.decompress(b), np.uint8).astype(np.int32)


def _split(ns: list[int]) -> float:
    """Where presses that did little part from presses that did a lot: the best two-group split of the counts'
    logarithms (Otsu), taken only when the groups are at least three times apart; otherwise everything counts."""
    v = np.sort(np.log1p(np.asarray([n for n in ns if n > 0], float)))
    if len(v) < 8:
        return 1.0
    best, cut = -1.0, None
    for i in range(1, len(v)):
        a, b = v[:i], v[i:]
        w = len(a) * len(b) * (a.mean() - b.mean()) ** 2
        if w > best:
            best, cut = w, i
    lo, hi = v[cut - 1], v[cut]
    if np.expm1(v[cut:]).mean() < 3 * np.expm1(v[:cut]).mean():
        return 1.0
    return float(np.expm1((lo + hi) / 2))


def _wrap(d: np.ndarray) -> np.ndarray:
    return np.where(d > 127, d - 256, np.where(d < -127, d + 256, d))


class Discoverer:
    def __init__(self, min_presses: int = 10, threshold: float = 0.8):
        self.min_presses, self.threshold = min_presses, threshold
        z = lambda: np.zeros(N, np.int32)  # noqa: E731
        # per axis, per width (u8, u16le): presses on the axis, agreeing moves, any moves; presses on the other axis that left it still
        self.st = self._stats()
        # the same counts per map visit (between transitions): a byte that follows the d-pad in one room and sits still
        # in the next (a sprite slot, a cutscene's copy) is not the position; the current visit and the last few count
        self.seg = self._stats()
        self.segs: list[dict] = []
        # the map: every change of every byte, frame to frame, and which of them fell close to a transition
        self.event = 0
        self.changes = z()               # changes seen, all frames
        self.ups = z()                   # of those, a rise by exactly one (a counter, not an id)
        self.near = z()                  # transitions this byte changed near (within WINDOW events either side)
        self.last_change = np.full(N, -10**9, np.int64)
        self.credited = np.full(N, -1, np.int64)   # the transition a byte was last credited for
        self.last_trans_event = -10**9
        self.in_burst = False
        self.ring: list[np.ndarray] = []
        self.ema = 0.0
        self.presses = 0
        self.by_pad = z()                # changed by a d-pad press (a step, a door, a probe's step)
        self.by_other = z()              # changed by any other press (a menu, a text box, a button)
        self.pad_presses = 0
        self.by_door = z()               # changed by a d-pad press that looked like a door (see press)
        self.walks = 0
        self.walks_at = np.zeros(N, np.int64)
        self.holds = np.zeros(N, np.int32)
        self.holds_walked = np.zeros(N, np.int32)
        self.crossed = np.zeros(N, bool)    # a pair whose high byte moved with a small step: a position past 255
        self._xdeltas: list[int] = []
        self._moves: dict[bool, list[int]] = {}   # how far a step moves, for whole steps and for probes
        self.transitions = 0
        self.blank = False
        self.before_blank: np.ndarray | None = None
        self.found: dict[str, Any] = {}
        self.fixed: dict[str, Any] = {}  # loaded from a data file: no learning needed for these
        self.trace: list | None = None   # ANYGAME_DISCOVER_TRACE: every event kept, to replay offline (scripts/discovery_replay.py)

    @staticmethod
    def _stats() -> dict:
        z = lambda: np.zeros(N, np.int32)  # noqa: E731
        return {(ax, w): {"n": 0, "agree": z(), "moved": z(), "n_other": 0, "still": z()} for ax in "xy" for w in (1, 2)}

    # ---- evidence --------------------------------------------------------------------------------------
    def press(self, button: str, before: np.ndarray, after: np.ndarray, full: bool = True) -> None:
        """A press with work RAM before and after. `full`: a whole step was played (not a short probe from a save
        state), so the position change is what one step does and teaches the step size."""
        if self.trace is not None:
            self.trace.append(("p", button, _z(before), _z(after), full))
        d = DIRS.get(button)
        if "x" in self.found and "y" in self.found:
            c = after != before
            if d and (d[0] or d[1]):
                # a door rewrites several of the bytes that steps rarely change at once (the map's id, its bank,
                # tileset, script), and the step does not end one step along: the player lands elsewhere, or on the
                # same spot of another floor. A plain step (the usual distance, along the pressed direction)
                # scrolls the screen, which rewrites rarely changed tiles too
                dx = self.decode(after, "x") - self.decode(before, "x")
                dy = self.decode(after, "y") - self.decode(before, "y")
                along, across = (dx, dy) if d[0] else (dy, dx)
                moves = self._moves.setdefault(full, [])
                if along and not across and np.sign(along) == (d[0] or d[1]):
                    self._moves[full] = (moves + [abs(along)])[-40:]
                plain = not across and np.sign(along) == (d[0] or d[1]) and len(moves) >= 3 and abs(along) == int(np.median(moves))
                rare = c & (self.by_pad <= max(2, 0.02 * self.pad_presses)) & (self.by_other * 4 <= self.by_pad + 1)
                if not plain and rare.sum() >= 4:
                    self.by_door += c
                self.by_pad += c
                self.pad_presses += 1
            else:
                self.by_other += c
        if full and d and d[0] and "x" in self.found and "y" in self.found:
            dx = self.decode(after, "x") - self.decode(before, "x")
            if dx and not self.decode(after, "y") - self.decode(before, "y"):
                self._xdeltas = (self._xdeltas + [dx])[-40:]
                self.learn_cell(self._xdeltas)      # the median: a warp now and then does not move it
        jump = self._jump(before, after)
        if not jump and not self.blank:
            self.presses += 1
        if d is None or jump or self.blank:
            return
        if not full:
            # against waiting, a press that did little is no evidence either way: a text box ignores the d-pad but a
            # few bytes (the pad's own state) still differ, while a step rewrites far more (position, sprites, the
            # screen's tile map). Little is measured against this game's own recent presses
            n = int((after != before).sum())
            self._probe_n = (getattr(self, "_probe_n", []) + [n])[-200:]
            if n < _split(self._probe_n):
                return
        self._last_ram = after
        d8 = _wrap(after - before)
        b16, a16 = before[:-1] + 256 * before[1:], after[:-1] + 256 * after[1:]
        d16 = np.concatenate([a16 - b16, [0]])
        hi_step = np.concatenate([np.abs(_wrap(after[1:] - before[1:])) == 1, [False]])
        lo_wrap = ((before >= 0xC0) & (after < 0x40)) | ((before < 0x40) & (after >= 0xC0))
        self.crossed |= hi_step & lo_wrap & (np.abs(d16) < 64)     # the low byte wrapped and carried into the high one
        for ax, want, other in (("x", d[0], d[1]), ("y", d[1], d[0])):
            for w, dd in ((1, d8), (2, d16)):
                for s in (self.st[(ax, w)], self.seg[(ax, w)]):
                    if want:
                        s["n"] += 1
                        s["agree"] += (np.sign(dd) == want)
                        s["moved"] += (dd != 0)
                    elif other:
                        s["n_other"] += 1
                        s["still"] += (dd == 0)
        self._update()

    def frame(self, now: np.ndarray, blank: bool) -> None:
        """A rendered frame: every byte change is counted (the map's bytes change once per transition, almost nothing
        else does), and a blank screen (a fade) brackets a transition."""
        if self.trace is not None:
            self.trace.append(("f", bool(blank), _z(now)))
        last = getattr(self, "_last", None)
        self.event += 1
        playing = "x" in self.found and "y" in self.found   # title screens and menus before play churn everything
        if last is not None and playing:
            ch = now != last
            pos = (self.decode(now, "x"), self.decode(now, "y"))
            if pos != getattr(self, "_pos", None):
                self.walks += 1                          # the player moved since the last frame
                self._pos = pos
            if ch.any():
                idx = np.where(ch)[0]
                # every value a byte takes is a hold; a hold the player walked through (two moves or more) is how a
                # map's bytes behave, and a menu's or a text box's (held while the player stands still) is not
                walked = (self.walks - self.walks_at[idx]) >= HOLD_WALKS
                self.holds[idx] += 1
                self.holds_walked[idx] += walked
                self.walks_at[idx] = self.walks
                self.changes += ch
                self.ups += ch & ((now - last) % 256 == 1)
                self.last_change[ch] = self.event
                if self.event - self.last_trans_event <= WINDOW:
                    self._credit(ch)
            # a map load rewrites far more bytes over a few frames than walking does, with or without a fade or a
            # jump of the position (Aevilia's stairs land a few pixels from where they left): such a burst is the
            # transition. Measured against this game's own walking: how much changed since RING frames back
            if len(self.ring) == RING:
                net = int((now != self.ring[0]).sum())
                bar = max(BURST_MIN, BURST_X * self.ema)
                if net >= bar and not self.in_burst:
                    self.in_burst = True
                    self._transition()
                elif net < bar / 2:
                    self.in_burst = False
                if not self.in_burst:
                    self.ema = net if self.ema == 0 else 0.98 * self.ema + 0.02 * net
        self.ring = (self.ring + [now])[-RING:]
        if blank and not self.blank:
            self.blank, self.before_blank = True, last if last is not None else now
        elif not blank and self.blank:
            self.blank = False
            self.before_blank = None
        self._last = now

    def _credit(self, ch: np.ndarray) -> None:
        new = ch & (self.credited < self.transitions)
        self.near += new
        self.credited[new] = self.transitions

    def _jump(self, before: np.ndarray, after: np.ndarray) -> bool:
        """The found position moved by more than three cells in one press: a door, a map edge, a warp."""
        if "x" not in self.found or "y" not in self.found:
            return False
        bx, by, ax_, ay = (self.decode(v, k) for v in (before, after) for k in ("x", "y"))
        cell = max(1, self.found.get("cell", 1))
        return abs(ax_ - bx) > 3 * cell or abs(ay - by) > 3 * cell

    def _transition(self) -> None:
        if not ("x" in self.found and "y" in self.found):
            return
        self.transitions += 1
        self.last_trans_event = self.event
        self._credit(self.last_change >= self.event - WINDOW)
        if self.seg[("x", 1)]["n"] + self.seg[("y", 1)]["n"] >= self.min_presses:
            self.segs = (self.segs + [self.seg])[-3:]
        self.seg = self._stats()
        self._update()

    # ---- conclusions -----------------------------------------------------------------------------------
    def _score(self, s: dict) -> tuple[np.ndarray, np.ndarray] | None:
        """Per byte: the share of moving presses that moved it the right way, times the share of the other axis's
        presses that left it alone; and the share of this axis's presses that moved it at all."""
        if s["n"] < self.min_presses or s["n_other"] < self.min_presses // 2:
            return None
        moved = s["moved"] / s["n"]
        return (s["agree"] / np.maximum(s["moved"], 1)) * (s["still"] / s["n_other"]), moved

    def _walked(self, s: dict) -> bool:
        """On this visit something followed the d-pad on both axes: the player walked. A menu or a list has a cursor
        on one axis at most, and a visit spent in one says nothing about the position."""
        def ok(ax):
            for w in (1, 2):
                v = self._score(s[(ax, w)])
                if v is not None and float((v[0] * (v[1] > MOVED)).max()) >= self.threshold:
                    return True
            return False
        return ok("x") and ok("y")

    def _axis(self, ax: str, last: np.ndarray | None = None) -> dict[str, Any] | None:
        """The best position candidate on this axis. A press into a wall moves nothing, so the score is the share of
        presses that moved the byte that moved it the right way, times the share of the other axis's presses that
        left it alone, for a byte that moved on at least a third of this axis's presses. It must also hold on every
        recent map visit where something did follow the d-pad: the lowest visit score counts."""
        cands = []
        for w in (1, 2):
            sc = self._score(self.st[(ax, w)])
            if sc is None:
                continue
            score = sc[0] * (sc[1] > MOVED)
            for s in self.segs + [self.seg]:
                v = self._score(s[(ax, w)])
                if v is None or not self._walked(s):
                    continue                      # a visit spent against walls or in menus says nothing
                score = np.minimum(score, v[0] * (v[1] > MOVED))
            top = float(score.max())
            if top < self.threshold:
                continue
            cur = self.found.get(ax)
            if cur and (cur["type"] == "u8") == (w == 1) and score[cur["addr"] - LO] >= self.threshold:
                held = (float(score[cur["addr"] - LO]), w, cur["addr"] - LO, float(sc[1][cur["addr"] - LO]))
            keep = score >= top - 0.02
            idx = np.where(keep)[0]
            # among equals, the bytes that moved on the most presses: a position changes on every step that lands, a
            # block or chunk coordinate on some; and the one already found is always looked at
            idx = idx[np.argsort(-sc[1][idx], kind="stable")][:64].tolist()
            for i in idx:
                cands.append((float(score[i]), w, int(i), float(sc[1][i])))
        if not cands:
            return None
        best = max(c[0] for c in cands)
        cands = [c for c in cands if c[0] >= best - 0.02]
        # a pair whose high byte stays small is a position past 255 (pixels); a byte copied into the sprite table
        # scores as well while the camera is still, so the pair wins a tie
        def pref(c):
            score, w, i, moved = c
            hi_small = w == 2 and last is not None and i + 1 < N and last[i + 1] <= 3 and self.crossed[i]
            # then the byte that moves on most steps; ties: the higher address (buffers and sprite copies sit low)
            return (hi_small, w == 1, round(moved, 1), score, i)
        best = max(cands, key=pref)
        held = locals().get("held")
        # a track record: the byte found already stays while it passes, so one odd press (a step through a door, a
        # turn) cannot hand the position to a byte that agreed for a stretch; only one that moves on clearly more
        # steps (the real position against a block coordinate or a sprite slot) takes over
        if held and not (best[3] >= held[3] + 0.15 and best[0] >= held[0] - 0.02):
            best = held
        score, w, i, _ = best
        return {"addr": LO + i, "type": "u8" if w == 1 else "u16le", "score": round(score, 3)}

    def _dead(self, ax: str) -> bool:
        """The found byte stopped following the d-pad: on this visit something else follows it and this does not."""
        f = self.found.get(ax)
        if not f or self.seg[(ax, 1)]["n"] < 3 * self.min_presses:      # ten presses on arrival prove nothing
            return False
        if not self._walked(self.seg):
            return False
        mine = self._score(self.seg[(ax, 1 if f["type"] == "u8" else 2)])
        i = f["addr"] - LO
        return mine is not None and (mine[1][i] < 0.1 or mine[0][i] < 0.5)

    def _update(self) -> None:
        for ax in "xy":
            if ax in self.fixed:
                continue
            a = self._axis(ax, getattr(self, "_last_ram", None))
            if a:
                self.found[ax] = a
            elif self._dead(ax):
                del self.found[ax]                       # better unknown than wrong: the world memory walks blind
        if "x" in self.found and "cell" not in self.fixed:
            self.found["cell"] = self.found.get("cell") or 1
        if "map" not in self.fixed and "x" in self.found and "y" in self.found:
            m = self._map()
            if m:
                self.found["map"] = m
            elif "map" not in self.found:                # until a door is seen, everything so far is one place
                self.found["map"] = {"addrs": [], "doors": 0, "transitions": self.transitions}

    def _map(self) -> dict[str, Any] | None:
        """A map's bytes (its id, bank, tileset) change when a step takes the player through a door, stairs or a
        warp, and then hold while the player walks around. A menu or a text box changes bytes when a button is
        pressed, and those hold only while the player stands still; the screen and the sprites change on most
        steps. Neither bursts of rewritten memory nor fades find Pokemon's doors (its stairs warp inside the step
        and the screen buffer churns on every menu), so a door is a step that did not end one plain step along
        (see press); the signature is the bytes such steps changed, among those that steps change rarely and
        buttons almost never, that changed on the most steps."""
        done = self.holds + 1                                     # the current hold counts if walked through
        walked = self.holds_walked + ((self.walks - self.walks_at) >= HOLD_WALKS)
        P = (self.changes >= 1) & (self.changes < 64) & (walked >= 0.8 * done) & (self.ups < 0.5 * np.maximum(self.changes, 1))
        for ax in "xy":
            if ax in self.found:
                a = self.found[ax]["addr"] - LO
                P[a: a + (2 if self.found[ax]["type"] == "u16le" else 1)] = False
        # a map's bytes change when the player walks through a door, rarely, and not when a button opens a menu or a
        # text box; the bytes that changed at the most such steps tell the most places apart
        P &= (self.by_door >= 1) & (self.by_pad <= max(2, 0.02 * self.pad_presses)) & (self.by_other * 4 <= self.by_pad)
        if not P.any():
            return None
        idx = np.where(P)[0]
        top = self.by_pad[idx].max()
        idx = idx[self.by_pad[idx] >= 0.8 * top]
        idx = idx[np.argsort(-self.by_pad[idx], kind="stable")][:2]
        cur = self.found.get("map", {})
        if cur.get("addrs") and all(P[a - LO] for a in cur["addrs"]) and \
                self.by_pad[[a - LO for a in cur["addrs"]]].min() >= 0.7 * top:
            return {**cur, "doors": int(self.by_pad[idx].max())}   # a signature that still holds is kept
        return {"addrs": sorted(int(LO + i) for i in idx), "doors": int(self.by_pad[idx].max()), "transitions": self.transitions}

    def learn_cell(self, deltas: list[int]) -> None:
        """Typical change of x for one press, set by the device from presses it knows moved."""
        nz = [abs(d) for d in deltas if d]
        if nz:
            self.found["cell"] = int(np.median(nz))

    def decode(self, mem: np.ndarray, key: str) -> int | None:
        f = self.found.get(key)
        if not f:
            return None
        a = f["addr"] - LO
        return int(mem[a]) if f["type"] == "u8" else int(mem[a] + 256 * mem[a + 1])

    def state(self, mem: np.ndarray) -> dict[str, Any]:
        both = "x" in self.found and "y" in self.found      # one axis alone is as likely a menu cursor as a position
        out: dict[str, Any] = {"x": self.decode(mem, "x") if both else None, "y": self.decode(mem, "y") if both else None,
                               "map": None, "cell": self.found.get("cell")}
        m = self.found.get("map")
        if m:
            sig = [int(mem[a - LO]) for a in m["addrs"]]
            out["map"] = int.from_bytes(bytes(sig), "big") % (1 << 31)
        return out

    # ---- the data file ---------------------------------------------------------------------------------
    def dump(self) -> dict[str, Any]:
        return {k: v for k, v in self.found.items()}

    def load(self, d: dict[str, Any]) -> None:
        for k in ("x", "y", "map", "cell"):
            if d.get(k):
                self.found[k] = d[k]            # a starting point: what this run sees can replace or drop it

    def summary(self) -> str:
        return json.dumps({k: ({kk: (hex(vv) if kk == "addr" else vv) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in self.found.items()})
