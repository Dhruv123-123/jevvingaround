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
import os
from typing import Any
import numpy as np

LO, HI = 0xC000, 0xE000
MAP_RULE = 5        # bumped when the map rule changes: a signature saved under another is not loaded
EVIDENCE_RULE = 4   # bumped when what the evidence counts changes: evidence saved under another is not loaded
EVIDENCE = ("changes", "ups", "holds", "holds_walked", "walks_at", "by_pad", "by_other", "full_any", "follows_pos",
            "_from", "_to", "_old", "_hist", "n_values", "by_warp", "returned", "full_w", "chg_w")
LOADED_HOLD = 150   # presses on an axis this run judges for itself before a position loaded from a save can change
SETTLED = 300       # updates the position held unchanged before lookaheads stop teaching it (early on they correct it)
STILL_MAX = 600     # such presses in a row after which a position that never moves is judged again (it froze)
RECENT = 40         # real d-pad presses looked back on to tell walking from a menu
MOVED = 0.2         # a position byte moves on at least this share of its axis's presses (walls and turns take the rest)
WALKED = 0.8        # a map value must have held through walking on this share of its holds
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


TRACE_MAGIC = b"ATR1"


def append_trace(path: str, trace: list, done: int) -> int:
    """Append trace[done:] to the file at `path` as one compressed chunk (a new file when `done` is 0, or when the
    trace was swapped for a shorter one, as a branch put back does); returns how many events are written."""
    import pickle
    import struct
    import zlib
    if done > len(trace):
        done = 0
    if done and not os.path.exists(path):
        done = 0
    chunk = zlib.compress(pickle.dumps(trace[done:]), 1)
    with open(path, "ab" if done else "wb") as f:
        if not done:
            f.write(TRACE_MAGIC)
        f.write(struct.pack("<I", len(chunk)) + chunk)
    return len(trace)


def load_trace(path: str) -> list:
    """A trace written by append_trace (or, older, one compressed pickle)."""
    import pickle
    import struct
    import zlib
    raw = open(path, "rb").read()
    if not raw.startswith(TRACE_MAGIC):
        return pickle.loads(zlib.decompress(raw))
    out, i = [], len(TRACE_MAGIC)
    while i + 4 <= len(raw):
        n = struct.unpack("<I", raw[i:i + 4])[0]
        if i + 4 + n > len(raw):
            break                                   # a chunk cut short by a killed run
        out += pickle.loads(zlib.decompress(raw[i + 4:i + 4 + n]))
        i += 4 + n
    return out


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
        self.by_warp = z()               # changed by a d-pad press that moved the player further than a step
        self.warps = 0
        self.returned = z()              # changes that took a byte back to a value it had before
        self._prev_c = np.zeros(N, bool)
        self._prev_back = np.zeros(N, bool)
        self.follows_pos = z()           # changed back by the step back: drawn around the player, not the map
        self._from, self._to, self._old = np.full(N, -1, np.int64), np.full(N, -1, np.int64), z()
        self._hist = np.zeros(N, np.uint64)
        self._seen = np.zeros((N, 256), bool)   # the values each byte has taken after a press
        self.n_values = z()
        self._seen_walking = np.zeros((N, 256), bool)   # the same, from presses once the position is known
        self.full_any = z()              # changed by a press the game went on from (not a probe from a save state)
        # the same two counts (presses, all frames) since the warps were last counted afresh: a byte's changes
        # off the warps are judged against the warps counted over the same stretch
        self.full_w, self.chg_w = z(), z()
        self.other_presses = 0
        self.walks = 0
        self.walks_at = np.zeros(N, np.int64)
        self.holds = np.zeros(N, np.int32)
        self.holds_walked = np.zeros(N, np.int32)
        self.crossed = np.zeros(N, bool)    # a pair whose high byte moved with a small step: a position past 255
        self._xdeltas: list[int] = []
        self.transitions = 0
        self.blank = False
        self.before_blank: np.ndarray | None = None
        self.found: dict[str, Any] = {}
        self._still = 0                  # real d-pad presses in a row that moved neither found axis
        self.fixed: dict[str, Any] = {}  # loaded from a data file: no learning needed for these
        self.trace: list | None = None   # ANYGAME_DISCOVER_TRACE: every event kept, to replay offline (scripts/discovery_replay.py)

    @staticmethod
    def _stats() -> dict:
        z = lambda: np.zeros(N, np.int32)  # noqa: E731
        return {(ax, w): {"n": 0, "agree": z(), "moved": z(), "n_other": 0, "still": z()} for ax in "xy" for w in (1, 2)}

    # ---- evidence --------------------------------------------------------------------------------------
    def press(self, button: str, before: np.ndarray, after: np.ndarray, full: bool = True, continues: bool = False) -> None:
        """A press with work RAM before and after. `full`: a whole step was played (not a short probe from a save
        state), so the position change is what one step does and teaches the step size. `continues`: the game goes
        on from `after`, so the press is judged by the RAM just before whatever comes next: a tap starts a step
        that Pokemon finishes (and writes the position) after the press is over."""
        if self.trace is not None:
            self.trace.append(("p", button, _z(before), _z(after), full, continues))
        if not continues:
            # a lookahead from a save state (or a press from an older trace): judged now. It does not settle the
            # press the game is still finishing: its RAM is a branch's, and a door's fade can outlast its wait
            self._press(button, before, after, full, real=full)
            return
        if getattr(self, "_pending", None):
            self._pending[2] = before                   # where the game had got to when the next press came
        self._settle()
        self._pending = [button, before, after, full]

    def _settle(self) -> None:
        if getattr(self, "_pending", None):
            button, before, after, full = self._pending
            self._pending = None
            self._press(button, before, after, full, real=True)

    def _press(self, button: str, before: np.ndarray, after: np.ndarray, full: bool, real: bool) -> None:
        """`real`: the game went on from this press (not a probe from a save state)."""
        d = DIRS.get(button)
        v = after.astype(np.intp) & 0xFF
        new = ~self._seen[np.arange(N), v]
        self._seen[np.arange(N), v] = True
        self.n_values += new
        warp = False
        if "x" in self.found and "y" in self.found:
            c = after != before
            if real and d and (d[0] or d[1]):
                # which found axis the last real d-pad presses moved: on a menu or a battle screen neither does
                moved_axes = {ax for ax in "xy" if self.decode(after, ax) != self.decode(before, ax)}
                self._axis_moves = ((getattr(self, "_axis_moves", []) + [moved_axes])[-RECENT:])
                self._still = 0 if moved_axes else self._still + 1
            back = c & self._seen_walking[np.arange(N), v]     # back to a value it had while the player walked
            if real:
                self._seen_walking[np.arange(N), v] = True
            if d and (d[0] or d[1]):
                p0 = (self.decode(before, "x"), self.decode(before, "y"))
                p1 = (self.decode(after, "x"), self.decode(after, "y"))
                # a door or a seamless edge between maps (Pallet Town to Route 1) moves the player further than a
                # step: the map's bytes change on such presses and almost never on others. Pokemon writes the new
                # map's id as the player steps onto the door and the new position only after the fade, a press
                # later, so the press before counts too
                cell = self.found.get("cell") or 1
                warp = None not in p0 + p1 and abs(p1[0] - p0[0]) + abs(p1[1] - p0[1]) > 2 * cell
                if p0 != p1:
                    # a tile drawn around the player changes on a step and changes back on the step back; the map's
                    # bytes, changed by stairs, stay changed when the player steps off them (and stepping back over
                    # a seamless edge is a warp, not a step)
                    k0, k1 = hash(p0) & 0x7FFFFFFF, hash(p1) & 0x7FFFFFFF
                    if not warp:
                        self.follows_pos += c & (self._from == k1) & (self._to == k0) & (after == self._old)
                    self._from[c], self._to[c], self._old[c] = k0, k1, before[c]
                self.by_pad += c
                self.pad_presses += 1
                if real and warp:
                    self.by_warp += c | self._prev_c
                    self.warps += 1
                    # back through a door to a place seen before: its id comes back, a landing spot's tiles rarely
                    self.returned += back | self._prev_back
            else:
                self.by_other += c                      # a cutscene after a talk can move the player to another map
                self.other_presses += 1
            if real:
                self._prev_c, self._prev_back = c, back
            if real:
                self.full_any += c
                self.full_w += c
            # which presses changed a byte, folded into one number: a map's id, bank, tileset and script pointers all
            # change on exactly the same presses, a screen tile or a sprite with few others
            self._hist[c] = self._hist[c] * np.uint64(1000003) + np.uint64(self.pad_presses + self.other_presses)
        # a warp is judged against the step size, so it is left out only once the step size is known (from a save, or
        # from enough steps): before that every step of a game that counts pixels looks like one
        known = getattr(self, "_cell_known", False) or len(self._xdeltas) >= 10
        if full and d and d[0] and not (warp and known) and "x" in self.found and "y" in self.found:
            dx = self.decode(after, "x") - self.decode(before, "x")
            if dx and not self.decode(after, "y") - self.decode(before, "y"):
                self._xdeltas = (self._xdeltas + [dx])[-40:]
                self.learn_cell(self._xdeltas)      # the median, and never a warp: a door loop is warps back to back
        jump = self._jump(before, after)
        if not jump and not self.blank:
            self.presses += 1
        if d is None or jump or self.blank:
            return
        if full:
            # a d-pad press in a battle menu or a text box moves a cursor (a few bytes); a step rewrites the
            # sprites and the screen's tile map. A long battle would otherwise read as hundreds of presses
            # that moved nothing, and the position would fall below the share it must move on
            n = int((after != before).sum())
            self._full_n = (getattr(self, "_full_n", []) + [n])[-200:]
            if n < _split(self._full_n):
                return
        if not full and getattr(self, "_pos_age", 0) >= SETTLED:
            # once the position has held for a while, lookaheads teach it nothing more: in a battle's menu the cursor byte follows
            # up and down and stays on left and right against waiting exactly like a position, and probe after probe
            # there handed y to it (the Rattata stall on Route 1). Real presses still judge it
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
        # through a door the position jumps to the new map's spot whatever the press was: it says nothing about which
        # bytes follow the d-pad, and a byte that held still through it (a sprite tile) would gain on it
        for ax, want, other in (("x", d[0], d[1]), ("y", d[1], d[0])) if not (warp and known) else ():
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
                self.chg_w += ch
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
        cur = self.found.get(ax)
        if cur and ax in getattr(self, "_loaded", ()) and self.st[(ax, 1)]["n"] < LOADED_HOLD:
            # a position resumed from a save had a whole run behind it, which the save does not carry: a few
            # presses here (a door gone in and out of, a stretch along a wall) cannot hand it to a byte that agreed
            # with them; only one that stops following on a walked visit loses it
            return None if self._dead(ax) else cur
        moves = getattr(self, "_axis_moves", [])
        if cur and "x" in self.found and "y" in self.found and len(moves) >= RECENT and \
                not any(moves[-RECENT:]) and self._still < STILL_MAX:
            # the position has not moved on any of the last real d-pad presses: the player is not walking (a menu, a
            # battle, a job grid), and a byte that follows the d-pad there is a cursor, not the position. Kept as it
            # is, for a while: a position that froze (a sprite copy left behind by a door) is judged again after that
            return cur
        cands = []
        for w in (1, 2):
            # the share a byte must move on is judged over visits where the player walked: a long battle or a
            # stretch of menus is d-pad presses that move no position, and would sink the real one
            walked = [v[(ax, w)] for v in self.segs + [self.seg] if self._walked(v)]
            total = {k: sum(v[k] for v in walked) for k in walked[0]} if walked else self.st[(ax, w)]
            sc = self._score(total)
            if sc is None:
                continue
            # a position walks through many values; the direction the player faces or last pressed (a sprite's
            # step vector: -1, 0, 1) follows the d-pad as well when presses turn the player more than they move him
            score = sc[0] * (sc[1] > MOVED) * (self.n_values >= 4)
            for s in self.segs + [self.seg]:
                v = self._score(s[(ax, w)])
                if v is None or not self._walked(s):
                    continue                      # a visit spent against walls or in menus says nothing
                # on a visit spent mostly turning, talking or against walls the position moves on few presses;
                # what it must not do is stop following (a sprite copy frozen after a door) or follow wrongly
                score = np.minimum(score, v[0] * (v[1] > MOVED / 4))
            top = float(score.max())
            if top < self.threshold:
                continue
            cur = self.found.get(ax)
            if cur and (cur["type"] == "u8") == (w == 1) and score[cur["addr"] - LO] >= self.threshold:
                held = (float(score[cur["addr"] - LO]), w, cur["addr"] - LO, float(sc[1][cur["addr"] - LO]))
            keep = (score >= top - 0.02) | ((score >= top - 0.12) & (sc[1] >= sc[1][int(score.argmax())] + 0.3))
            idx = np.where(keep)[0]
            # among equals, the bytes that moved on the most presses: a position changes on every step that lands, a
            # block or chunk coordinate on some; and the one already found is always looked at
            idx = idx[np.argsort(-sc[1][idx], kind="stable")][:64].tolist()
            for i in idx:
                cands.append((float(score[i]), w, int(i), float(sc[1][i])))
        if not cands:
            return None
        top = max(cands, key=lambda c: (c[0], c[3]))
        # a byte that moves on clearly more steps stays in the running a little below the best score: a block or
        # map-view coordinate runs on smoothly across a map's edge (scoring higher on a short stretch with a few
        # warps) but moves on every other step, the position on every step
        cands = [c for c in cands if c[0] >= top[0] - 0.02 or (c[0] >= top[0] - 0.12 and c[3] >= top[3] + 0.3)]
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
        pos = tuple(self.found[ax]["addr"] if ax in self.found else None for ax in "xy")
        if pos != getattr(self, "_warp_pos", pos):
            # warps are judged by the position bytes: a wrong one (a menu cursor taken for y) jumps all over, so
            # what it called warps is forgotten when the position changes hands
            self.by_warp[:] = 0
            self.returned[:] = 0
            self.full_w[:] = 0
            self.chg_w[:] = 0
            self.warps = 0
        if pos == getattr(self, "_warp_pos", None) and None not in pos:
            self._pos_age = getattr(self, "_pos_age", 0) + 1
        else:
            self._pos_age = 0
        self._warp_pos = pos
        if "map" not in self.fixed and "x" in self.found and "y" in self.found:
            m = self._map()
            if m:
                self.found["map"] = m
            elif "map" not in self.found or self.pad_presses >= 50:
                # nothing passes (yet, or any more): everything so far is one place. A signature loaded from an
                # earlier run is kept for the first few steps, while this run's evidence is too thin to judge it
                self.found["map"] = {"addrs": [], "doors": 0, "transitions": self.transitions, "rule": MAP_RULE}

    def _map(self) -> dict[str, Any] | None:
        """A map's bytes (its id, bank, tileset, script pointers) change together when a press takes the player
        through a door, up stairs, or into a cutscene, and then hold while the player walks around. The surest sign
        of a new map is a warp: a d-pad press that moves the player further than a step (a door, or a seamless
        edge like Pallet Town to Route 1, where y jumps from 0 to 35). Bytes that changed on most warps and on few
        other presses, and came back to an earlier value when the player came back through a door, are the map's
        id; the one that took the most values wins, with its other half if one changed on exactly the same
        presses. Until the player has come back somewhere, a byte qualifies if presses change it rarely, it held
        through walking, and stepping back does not change it back (a tile drawn around the player does); the
        signature is then the largest group of such bytes that changed on exactly the same presses."""
        done = self.holds + 1                                     # the current hold counts if walked through
        walked = self.holds_walked + ((self.walks - self.walks_at) >= HOLD_WALKS)
        P = (self.changes >= 1) & (self.changes < 64) & (self.ups < 0.5 * np.maximum(self.changes, 1))
        for ax in "xy":
            if ax in self.found:
                a = self.found[ax]["addr"] - LO
                P[a: a + (2 if self.found[ax]["type"] == "u16le" else 1)] = False
        # a map's bytes change when the player walks through a door, rarely, and not when a button opens a menu or a
        # text box; the bytes that changed at the most such steps tell the most places apart
        P &= (self.full_any >= 1) & (self.by_pad >= 1) & (self.follows_pos == 0) & (self.by_pad <= max(2, 0.02 * self.pad_presses)) & \
            (self.by_other <= max(1, 0.02 * self.other_presses))
        # a short visit (in through a door and straight out) is one hold not walked through: allowed once
        held = P & (self.holds_walked >= np.minimum(WALKED * self.holds, self.holds - 1))   # in use: its current value is still new
        P &= walked >= np.minimum(WALKED * done, done - 1)
        W = np.zeros(N, bool)
        if self.warps:
            # bytes that changed on most warps and on few plain steps or buttons: a map's, even before it held
            # (no cap on its changes: a long game goes through hundreds of doors)
            W = (self.by_warp >= max(1, 0.5 * self.warps)) & (self.follows_pos == 0) & \
                (self.full_w - self.by_warp <= np.maximum(2, 0.3 * self.by_warp)) & (self.by_other <= 1 + 0.5 * self.by_warp) & \
                (self.chg_w <= 2 * self.by_warp + 2)
            for ax in "xy":
                a = self.found[ax]["addr"] - LO
                W[a: a + (2 if self.found[ax]["type"] == "u16le" else 1)] = False
            held |= W
            P |= W
        cur = self.found.get("map", {})
        keep = bool(cur.get("addrs")) and all(held[a - LO] for a in cur["addrs"])
        if not P.any():
            return {**cur} if keep else None
        idx = np.where(P)[0]
        back = idx[(self.returned[idx] >= 1) & W[idx] & (self.by_warp[idx] >= 0.8 * self.warps)]
        if len(back):
            # a place's bytes come back when the player does; the one that took the most values tells the most
            # places apart (a byte that only says indoors or out takes two)
            off = np.maximum(self.full_w[back] - self.by_warp[back], 0) + np.maximum(self.chg_w[back] - self.by_warp[back], 0)
            # ties (a map's sprite table loads with its id and comes back with it too): the byte lookaheads into a
            # door changed most (the id is written as the player steps onto the door, sprites and tiles only after
            # the fade), then the higher address (sprite tables and buffers sit low)
            order = np.lexsort((-back, -self.by_pad[back], -self.n_values[back], off, -self.by_warp[back]))
            back = back[order]
            # a second byte only if it changed on exactly the same presses (an id's other half); the map the
            # player came from also comes back, but on other presses, and would split a place by its entrance
            group = back[self._hist[back] == self._hist[back[0]]]
            back = group[:2]
            if keep and set(a - LO for a in cur["addrs"]) <= set(group.tolist()):
                return {**cur, "doors": int(self.by_pad[back].max()), "rule": MAP_RULE}   # still the best: kept
            return {"addrs": sorted(int(LO + i) for i in back), "doors": int(self.by_pad[back].max()),
                    "transitions": self.transitions, "rule": MAP_RULE}
        # the biggest group of bytes that changed on the same steps; among equals, the one that changed most
        groups, inv, size = np.unique(self._hist[idx], return_inverse=True, return_counts=True)
        best = max(range(len(groups)), key=lambda g: (size[g], self.by_pad[idx[inv == g]].max()))
        if size[best] < 3:
            return {**cur} if keep else None
        idx = idx[inv == best]
        top = self.by_pad[idx].max()
        idx = idx[self.by_pad[idx] >= 0.8 * top]
        idx = idx[np.argsort(-self.by_pad[idx], kind="stable")][:2]
        if keep and self.by_pad[[a - LO for a in cur["addrs"]]].min() >= 0.7 * top and \
                self.by_warp[[a - LO for a in cur["addrs"]]].min() >= self.by_warp[idx].max():
            return {**cur, "doors": int(self.by_pad[idx].max()), "rule": MAP_RULE}   # a signature that still holds is kept
        return {"addrs": sorted(int(LO + i) for i in idx), "doors": int(self.by_pad[idx].max()), "transitions": self.transitions,
                "rule": MAP_RULE}

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
    def dump(self, evidence: bool = True) -> dict[str, Any]:
        """What was found; with `evidence`, also what the map was judged from, so a run resumed from a checkpoint
        goes on from the same evidence instead of from nothing (a few presses' worth lets one-off bytes through)."""
        out: dict[str, Any] = {k: v for k, v in self.found.items()}
        if evidence and "x" in self.found:
            import base64
            import io
            b = io.BytesIO()
            arrays = {k: getattr(self, k) for k in EVIDENCE}
            arrays["_seen"] = np.packbits(self._seen, axis=1)
            arrays["_seen_walking"] = np.packbits(self._seen_walking, axis=1)
            np.savez_compressed(b, **arrays, counts=np.array([self.walks, self.pad_presses, self.other_presses, self.warps]))
            out["evidence"] = {"rule": EVIDENCE_RULE, "npz": base64.b64encode(b.getvalue()).decode()}
        return out

    def load(self, d: dict[str, Any]) -> None:
        for k in ("x", "y", "map", "cell"):
            if k == "map" and d.get(k) and d[k].get("rule") != MAP_RULE:
                continue                        # a signature found by an older rule (screen tiles, sprites): not kept
            if d.get(k):
                self.found[k] = d[k]            # a starting point: what this run sees can replace or drop it
        self._loaded = {ax for ax in "xy" if d.get(ax)}
        self._cell_known = bool(d.get("cell"))
        ev = d.get("evidence")
        if ev and ev.get("rule") == EVIDENCE_RULE:   # counts kept across a ranking change: the map is re-judged from them
            import base64
            import io
            z = np.load(io.BytesIO(base64.b64decode(ev["npz"])))
            for k in EVIDENCE:
                if k in z and z[k].shape == getattr(self, k).shape:
                    setattr(self, k, z[k].astype(getattr(self, k).dtype))
            self._seen = np.unpackbits(z["_seen"], axis=1)[:, :256].astype(bool)
            self._seen_walking = np.unpackbits(z["_seen_walking"], axis=1)[:, :256].astype(bool)
            self.walks, self.pad_presses, self.other_presses, self.warps = (int(v) for v in z["counts"])
            if "full_w" not in z:
                # saved before the changes off the warps were counted over the warps' stretch: the warps can't be
                # weighed against them, so they are counted afresh from here (the position and the rest are kept)
                self.by_warp[:] = 0
                self.returned[:] = 0
                self.warps = 0

    def summary(self) -> str:
        return json.dumps({k: ({kk: (hex(vv) if kk == "addr" else vv) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in self.found.items()})
