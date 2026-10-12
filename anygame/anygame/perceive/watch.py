"""Press and watch: what a button did, read from two frames and nothing else.

The game is its own physics engine. After every press the agent compares the frame before with the frame after:

1. **The background shift.** Content that moved as a whole (a scrolling map, a road under a car) is found by phase
   correlation and checked pixel by pixel; a screen that changed too much to line up is a scene change.
2. **Movers.** Pixels that differ once the background shift is undone are explained by something that moved on its
   own: for each patch of them, the displacement (relative to the background) under which most of its pixels equal
   the frame before. A sprite walking left over a scrolling map, a player standing still while the map scrolls under
   it (it moved relative to the background), a cursor jumping a row: each is a mover with its own displacement.
3. **The player.** The thing that follows the d-pad: movers seen on direction presses are linked into tracks by
   position, and each track counts how often it moved the way the press pointed and how often against it. The player
   is the track that agrees, over enough presses; it is located on later frames by its last place and by its
   poses (the pixel patterns it moved with), so a still player is still found.
4. **Walking.** With the player found, a direction press either moved it (the ground it stepped onto is walkable) or
   left it in place in the pose it already had (what is ahead blocks it). The cells involved are keyed by their pixels
   (cellbook keys), so one press teaches every place the same picture appears, and the verdicts outweigh any label a
   model gave the cell.

Nothing here knows a game: no RAM, no tile ids, no button meanings beyond "a d-pad press points somewhere".

    w = Watcher()
    for prev, press, cur in frames:
        eff = w.see(prev, press, cur)     # shift, movers, the player box, walk verdict
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np

from .cellbook import _hash

DIRS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}
R = 24                 # the furthest a mover is searched for between two frames (pixels, each axis)
SCENE = 0.45           # a frame differing on more than this share of the overlap is a new scene
MIN_PX = 10            # a mover explains at least this many pixels
EXPLAIN = 0.35         # ... and this share of its patch
MAX_SIDE = 64          # a changed patch wider or taller than this is scenery redrawn, not a mover
GHOST = 0.95          # share of a mover's pixels found unchanged elsewhere that makes it background
POSE_MIN = 24          # a pose kept to find the player by must have this many pixels


def pack(img: np.ndarray) -> np.ndarray:
    """RGB image as one int32 colour per pixel."""
    a = img.astype(np.int32)
    return (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]


def bg_shift(prev: np.ndarray, cur: np.ndarray, last: tuple[int, int] = (0, 0), steps=(8, 16)
             ) -> tuple[int, int, float]:
    """How the picture moved as a whole: (dx, dy, share of the overlap that agrees), cur[y, x] == prev[y-dy, x-dx].
    Candidates are no shift, the last shift, the phase-correlation peak (and its neighbours) and a step of each size
    in `steps` along each axis (a tiled floor fools phase correlation); the best by pixel agreement wins, no shift on
    a near tie."""
    p, c = pack(prev), pack(cur)
    h, w = p.shape
    cands = {(0, 0), tuple(last)} | {(sx * s, sy * s) for s in steps for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
    gp = cv2.cvtColor(prev, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gc = cv2.cvtColor(cur, cv2.COLOR_RGB2GRAY).astype(np.float32)
    if gp.std() > 0 and gc.std() > 0:
        (sx, sy), _ = cv2.phaseCorrelate(gp, gc)
        bx, by = int(round(sx)), int(round(sy))
        for ex in (-1, 0, 1):
            for ey in (-1, 0, 1):
                cands.add((bx + ex, by + ey))
    best = (-1.0, 0, 0)
    for dx, dy in cands:
        if abs(dx) > w // 2 or abs(dy) > h // 2:
            continue
        a = p[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
        b = c[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)]
        s = float((a == b).mean()) if a.size else 0.0
        s -= 0.002 * ((dx, dy) != (0, 0))
        if s > best[0]:
            best = (s, dx, dy)
    return best[1], best[2], round(best[0], 4)


def warp(prev: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """The packed frame before, moved by (dx, dy); -1 where nothing came in."""
    p = pack(prev)
    h, w = p.shape
    out = np.full_like(p, -1)
    out[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)] = p[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
    return out


@dataclass
class Mover:
    x: int
    y: int
    w: int
    h: int
    v: tuple[int, int]          # displacement relative to the background, pixels
    n: int                      # pixels it explains
    mask: np.ndarray            # explained pixels in its box
    key: str = ""

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


def movers(prev: np.ndarray, cur: np.ndarray, shift: tuple[int, int], limit: int = 12
           ) -> tuple[list[Mover], float, np.ndarray]:
    """Patches that moved on their own (see the module doc), the share of the overlap that changed, and the changed
    pixels."""
    W = warp(prev, *shift)
    c = pack(cur)
    valid = W >= 0
    diff = (c != W) & valid
    changed = float(diff.sum() / max(1, valid.sum()))
    if changed > SCENE or not diff.any():
        return [], changed, diff
    h, w = c.shape
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(diff.astype(np.uint8), np.ones((5, 5), np.uint8)), 8)
    order = sorted(range(1, n), key=lambda k: -stats[k, 4])[:limit]
    out: list[Mover] = []
    Wp = np.pad(W, R, constant_values=-1)
    Dp = np.pad(diff, R, constant_values=False)
    for k in order:
        x, y, bw, bh = (int(v) for v in stats[k, :4])
        if bw > MAX_SIDE or bh > MAX_SIDE:
            continue
        m = (lab[y:y + bh, x:x + bw] == k) & diff[y:y + bh, x:x + bw]
        patch = c[y:y + bh, x:x + bw]
        region = Wp[y:y + bh + 2 * R, x:x + bw + 2 * R]          # W around the patch, offset by R
        dregion = Dp[y:y + bh + 2 * R, x:x + bw + 2 * R]
        for _ in range(3):
            if m.sum() < MIN_PX:
                break
            agree = np.zeros((2 * R + 1, 2 * R + 1), np.float32)
            for col in np.unique(patch[m]):
                t = (m & (patch == col)).astype(np.float32)
                agree += cv2.matchTemplate(((region == col) & dregion).astype(np.float32), t, cv2.TM_CCORR)
            agree[R, R] = 0
            iy, ix = np.unravel_index(int(agree.argmax()), agree.shape)
            best = float(agree[iy, ix])
            if best < MIN_PX or best < EXPLAIN * m.sum():
                break
            # the patch's pixels came from W at (p - v): region offset (ix, iy) is v = (R - ix, R - iy)
            v = (R - ix, R - iy)
            # a pixel moved here only if the place it came from changed too: a repeating floor next to a walking
            # sprite matches itself at the step's offset, but nothing left it
            src = region[iy:iy + bh, ix:ix + bw]
            ex = m & (src == patch) & dregion[iy:iy + bh, ix:ix + bw]
            if ex.sum() < MIN_PX:
                break
            m = m & ~ex
            # a ghost: the place a sprite left, now showing background that repeats nearby (a tiled floor). Its pixels
            # are also found, all at one offset, in parts of the frame before that did not change: not a mover
            stat = np.zeros_like(agree)
            for col in np.unique(patch[ex]):
                t = (ex & (patch == col)).astype(np.float32)
                stat += cv2.matchTemplate(((region == col) & ~dregion).astype(np.float32), t, cv2.TM_CCORR)
            if float(stat.max()) >= GHOST * ex.sum():
                continue
            ys, xs = np.nonzero(ex)
            x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
            mk = ex[y0:y1, x0:x1]
            pix = np.where(mk, patch[y0:y1, x0:x1], 0)
            out.append(Mover(x + int(x0), y + int(y0), int(x1 - x0), int(y1 - y0), (int(v[0]), int(v[1])),
                             int(ex.sum()), mk, _hash(bytes(mk.shape) + pix.astype(np.int32).tobytes())))
    return out, changed, diff


def _match(reg: np.ndarray, pix: np.ndarray, mk: np.ndarray) -> np.ndarray:
    """For every place in packed `reg`, how many of the pattern's masked pixels it draws exactly."""
    ph, pw = mk.shape
    agree = np.zeros((reg.shape[0] - ph + 1, reg.shape[1] - pw + 1), np.float32)
    for col in np.unique(pix[mk]):
        agree += cv2.matchTemplate((reg == col).astype(np.float32), (mk & (pix == col)).astype(np.float32), cv2.TM_CCORR)
    return agree


@dataclass
class Track:
    """A thing seen moving: where it is now, and how its moves lined up with the d-pad."""
    x: float
    y: float
    w: int
    h: int
    agree: int = 0
    against: int = 0
    dirs: Counter = field(default_factory=Counter)      # presses it followed, by direction
    recent: float = 0.0         # agreement minus twice the disagreement, fading by DECAY a press
    recent_i: int = 0
    locked: int = 0             # scrolls it kept its place on screen through (a camera that follows it)
    free: int = 0               # scrolls it moved on screen through
    last: int = 0               # frame it was last seen
    poses: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)   # key → (colours, mask)

    @property
    def axes(self) -> int:
        return bool(self.dirs["left"] or self.dirs["right"]) + bool(self.dirs["up"] or self.dirs["down"])

    @property
    def score(self) -> float:
        return (self.agree - 2 * self.against) / (self.agree + self.against + 2)


@dataclass
class Effect:
    shift: tuple[int, int]
    agree: float
    changed: float
    scene: bool
    movers: list[Mover]
    player: tuple[int, int, int, int] | None = None     # x, y, w, h on the frame after
    moved: bool | None = None                           # a direction press moved the player (None: not judged)
    step: tuple[int, int] | None = None                 # the player's move relative to the background


LINK = 10               # a mover continues a track whose box centre is within this many pixels of where it stood
RECENT = 8             # a press that changed nothing is a bump only if the player walked this few frames ago
DECAY = 0.98           # per press: how fast a track's recent agreement with the d-pad fades


class Watcher:
    """Press-and-watch over a stream of frames. Keeps the tracks, the player's poses and a walk book (cell key →
    walk / blocked counts from the game)."""

    def __init__(self):
        self.i = 0
        self.last_shift = (0, 0)
        self.tracks: list[Track] = []
        self.player: Track | None = None
        self.walk: dict[str, Counter] = {}
        self.steps: Counter = Counter()          # the player's step size along the press (pixels)
        self.last_moved = -10 ** 6

    def box(self, within: int = 0) -> tuple[int, int, int, int] | None:
        """The player's box as last seen, if it was seen on one of the latest `within` + 1 frames."""
        p = self.player
        return (int(p.x), int(p.y), p.w, p.h) if p is not None and self.i - p.last <= within else None

    # ---- the player -------------------------------------------------------------------------------
    def _link(self, m: Mover, shift: tuple[int, int]) -> Track:
        """The track this mover continues (its box before the move near the track's place), or a new one."""
        cx, cy = m.centre
        px, py = cx - m.v[0] - shift[0], cy - m.v[1] - shift[1]       # where it stood on the frame before
        best = None
        for t in self.tracks:
            if self.i - t.last > 50:
                continue
            tx, ty = t.x + t.w / 2, t.y + t.h / 2
            d = min(max(abs(tx - px), abs(ty - py)), max(abs(tx - cx), abs(ty - cy)))
            if d <= LINK and (best is None or d < best[0]):
                best = (d, t)
        if best:
            t = best[1]
        else:
            t = Track(m.x, m.y, m.w, m.h)
            self.tracks.append(t)
        t.x, t.y, t.w, t.h, t.last = m.x, m.y, m.w, m.h, self.i
        return t

    @staticmethod
    def _distinct(cur: np.ndarray, pix: np.ndarray, mk: np.ndarray, at: tuple[int, int]) -> bool:
        """A pose is worth keeping only if it is drawn nowhere else on the frame (a patch of tiled floor is)."""
        agree = _match(pack(cur), pix, mk)
        n = int(mk.sum())
        hits = np.argwhere(agree >= 0.9 * n)
        return not any(abs(int(x) - at[0]) > 2 or abs(int(y) - at[1]) > 2 for y, x in hits)

    def _find_pose(self, cur: np.ndarray, near: tuple[float, float] | None) -> tuple[int, int, int, int] | None:
        """The player's place on a frame where it did not move: one of its poses drawn exactly, near its last place
        first."""
        if not self.player or not self.player.poses:
            return None
        c = pack(cur)
        h, w = c.shape
        best = None
        for key, (pix, mk) in list(self.player.poses.items())[-12:]:
            ph, pw = mk.shape
            n = int(mk.sum())
            if n < POSE_MIN:
                continue
            if near is not None:
                x0 = int(max(0, near[0] - pw / 2 - LINK)); y0 = int(max(0, near[1] - ph / 2 - LINK))
                x1 = int(min(w, near[0] + pw / 2 + LINK)); y1 = int(min(h, near[1] + ph / 2 + LINK))
            else:
                x0, y0, x1, y1 = 0, 0, w, h
            if x1 - x0 < pw or y1 - y0 < ph:
                continue
            agree = _match(c[y0:y1, x0:x1], pix, mk)
            iy, ix = np.unravel_index(int(agree.argmax()), agree.shape)
            s = float(agree[iy, ix]) / n
            if s >= (0.9 if near is not None else 0.97) and (best is None or s > best[0]):
                best = (s, (x0 + ix, y0 + iy, pw, ph))
        return best[1] if best else None

    def see(self, prev: np.ndarray, press: str | None, cur: np.ndarray, keys_prev=None) -> Effect:
        """One press: what moved, where the player is after it, and whether a direction press moved it."""
        self.i += 1
        dx, dy, agree = bg_shift(prev, cur, self.last_shift, {8, 16} | {s for s, _ in self.steps.most_common(2)})
        ms, changed, diff = movers(prev, cur, (dx, dy))
        scene = agree < 0.5 or changed > SCENE
        eff = Effect((dx, dy), agree, changed, scene, ms)
        if scene:
            self.last_shift = (0, 0)
            eff.player = None
            if self.player:
                self.player.last = min(self.player.last, self.i - 10)     # found again only by its poses
            return eff
        self.last_shift = (dx, dy)
        d = DIRS.get(press or "")
        before = (self.player.x, self.player.y, self.player.w, self.player.h) if self.player and self.i - self.player.last <= 1 else None
        linked: dict[int, list[Mover]] = {}
        for m in ms:
            t = self._link(m, (dx, dy))
            linked.setdefault(id(t), []).append(m)
            if d:
                along = m.v[0] * d[0] + m.v[1] * d[1]
                t.recent *= DECAY ** (self.i - t.recent_i)
                t.recent_i = self.i
                if along > 0:
                    t.agree += 1
                    t.dirs[press] += 1
                    t.recent += 1
                elif along < 0:
                    t.against += 1
                    t.recent -= 2
            if len(t.poses) < 64 and m.key not in t.poses and m.n >= POSE_MIN:
                pix = np.where(m.mask, pack(cur)[m.y:m.y + m.h, m.x:m.x + m.w], 0)
                if self._distinct(cur, pix, m.mask, (m.x, m.y)):
                    t.poses[m.key] = (pix, m.mask.copy())
        # the player follows the d-pad on both axes; a thing that follows it on one axis only is a menu cursor
        cand = [t for t in self.tracks if t.agree >= 3 and t.score >= 0.5 and t.axes == 2 and self.i - t.last <= 200]
        if cand:
            def now(t):
                return t.recent * DECAY ** (self.i - t.recent_i)
            best = max(cand, key=lambda t: (now(t), t.last))
            if self.player is None or best is not self.player and now(best) > now(self.player) + 2:
                if self.player is not None:
                    # the old track's poses stay with the player: it is the same thing, re-found
                    for k, v in self.player.poses.items():
                        best.poses.setdefault(k, v)
                self.player = best
        p = self.player
        mine: Mover | None = None
        if p is not None:
            if id(p) in linked:
                mine = max(linked[id(p)], key=lambda m: m.n)
                eff.player = (mine.x, mine.y, mine.w, mine.h)
                p.last = self.i
            else:
                recent = self.i - p.last <= 3
                near = (p.x + p.w / 2, p.y + p.h / 2) if recent else None
                bx, by = int(p.x), int(p.y)
                box = None
                if recent and not diff[by:by + p.h, bx:bx + p.w].any() and ((dx, dy) == (0, 0) or p.locked > p.free):
                    box = (bx, by, p.w, p.h)       # nothing changed where it stood (and it stays put on a scroll)
                if box is None:
                    box = self._find_pose(cur, near)
                if box is not None:
                    p.x, p.y, p.w, p.h = box
                    p.last = self.i
                    eff.player = box
            if mine is not None and (dx, dy) != (0, 0):
                if (mine.v[0] + dx, mine.v[1] + dy) == (0, 0):
                    p.locked += 1                  # the picture scrolled under it and it kept its place on screen
                else:
                    p.free += 1
        # walking: a direction press with the player found on both frames
        if d and before and eff.player:
            if mine is not None:
                eff.step = mine.v
                along = mine.v[0] * d[0] + mine.v[1] * d[1]
                if along > 0:
                    eff.moved = True
                    self.steps[along] += 1
                    self.last_moved = self.i
            elif (dx, dy) == (0, 0):
                bx, by, bw, bh = (int(v) for v in before)
                if not diff.any() and self.i - self.last_moved <= RECENT:
                    eff.step = (0, 0)
                    eff.moved = False      # nothing about the player changed, not even its pose (a turn would)
        return eff

    @staticmethod
    def _overlaps(m: Mover, box: tuple[int, int, int, int]) -> bool:
        x, y, w, h = box
        return not (m.x + m.w <= x or x + w <= m.x or m.y + m.h <= y or y + h <= m.y)

    def _same(self, m: Mover, box: tuple[int, int, int, int]) -> bool:
        x, y, w, h = box
        return abs(m.x - x) <= 4 and abs(m.y - y) <= 4


# ---- the walk book: what the game said about the ground ------------------------------------------------
class WalkBook:
    """Cell key → how often the player stepped onto it and how often it stopped the player. Keys are the cellbook's
    pixel keys, so a verdict about one patch of grass holds for every patch drawn the same."""

    def __init__(self):
        self.votes: dict[str, Counter] = {}

    @staticmethod
    def targets(keys: np.ndarray, phase: tuple[int, int], box: tuple[int, int, int, int], press: str,
                step: int) -> list[str]:
        """The keys of the cells (grid `keys` cut at `phase`) whose centres lie in the square of side `step` one step
        ahead of the player's box centre."""
        dx, dy = DIRS[press]
        x, y, w, h = box
        cx, cy = x + w / 2 + dx * step, y + h / 2 + dy * step
        half = max(step, 8) / 2
        px, py = phase
        out = []
        for r in range(keys.shape[0]):
            for c in range(keys.shape[1]):
                mx, my = px + c * 8 + 4, py + r * 8 + 4          # the cell's centre
                if abs(mx - cx) <= half and abs(my - cy) <= half:
                    out.append(keys[r, c])
        return out

    def add(self, cells: list[str], walkable: bool) -> None:
        for k in cells:
            self.votes.setdefault(k, Counter())["walk" if walkable else "block"] += 1

    def says(self, cells: list[str]) -> bool | None:
        """Walkable (every cell stepped onto at least once), blocked (a cell only ever blocked), or None (a cell never
        judged)."""
        if not cells:
            return None
        verdict = True
        for k in cells:
            v = self.votes.get(k)
            if not v:
                return None
            if v["walk"] == 0:
                verdict = False        # a cell the player ever stepped onto is ground: blocks come from things on it
        return verdict
