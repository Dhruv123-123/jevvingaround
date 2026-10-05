"""Screen-only perception: pixels in, a label for every 8x8 cell out, the big model asked only about what is new.

The agent sees the screen and nothing else (no RAM, no tile ids). A tile-drawn game repeats a small set of 8x8
pictures, so each cell's pixels are its identity: the book keys every cell by a hash of its pixels and keeps one
label per key. A cell whose key is in the book is answered by a lookup (microseconds); a cell that is not is novel.
Screens with novel cells are sent to the chat model (Azure, never OpenRouter), a few per call, each as an image with
a grid; it answers a letter per cell, and only the novel cells' letters are taken. The rest of its answer checks
the labels already in the book: a disagreement is recorded as a contradiction.

A label has three states: unseen (no key), labelled (the model said so), verified (the game confirmed it: the player
walked onto the cell, or two separate screens got the same letter for it). A verified label the model or the game
later contradicts is counted, and the cell goes back to the model with the next batch.

    book = CellBook()
    keys = book.keys(native_rgb)          # 18x20 grid of cell keys (phase found from the pixels if scrolled)
    novel = book.novel(keys)              # positions not in the book
    labeller.add(native_rgb, keys); labeller.flush(book)   # one call for up to `per_call` screens

Nothing here knows a game; the book is data, saved and loaded as JSON.
"""
from __future__ import annotations
import base64
import hashlib
import json
from collections import Counter
from typing import Any, Callable

import numpy as np
import cv2

CELL = 8
# one letter per cell, as the model answers it
LABELS = {"T": "text", "G": "ground", "D": "door", "W": "wall", "P": "player", "E": "entity", "M": "ui", "B": "blank",
          "U": "unknown"}
WALKABLE = {"G", "D"}
ENTITY = {"P", "E"}


def native(frame: np.ndarray, size: tuple[int, int] = (160, 144)) -> np.ndarray:
    """A device frame (BGR, possibly scaled up) at the console's own resolution, RGB."""
    h, w = frame.shape[:2]
    if (w, h) != size:
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_NEAREST)
    return np.ascontiguousarray(frame[:, :, :3][:, :, ::-1])


def _hash(b: bytes) -> str:
    return hashlib.blake2b(b, digest_size=8).hexdigest()


def grid(img: np.ndarray, phase: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Cell keys of a native RGB image, cut at pixel offset `phase` (dx, dy): an array of strings, rows x cols."""
    dx, dy = phase
    h, w = img.shape[:2]
    rows, cols = (h - dy) // CELL, (w - dx) // CELL
    sub = img[dy:dy + rows * CELL, dx:dx + cols * CELL]
    blocks = sub.reshape(rows, CELL, cols, CELL, -1).transpose(0, 2, 1, 3, 4).reshape(rows * cols, -1)
    keys = np.array([_hash(b.tobytes()) for b in blocks], dtype=object)
    return keys.reshape(rows, cols)


class CellBook:
    """Cell key → label entry. An entry: votes (letter → count), label (the leading letter), state ('labelled' or
    'verified'), seen (frames it appeared in), contradictions."""

    def __init__(self):
        self.cells: dict[str, dict[str, Any]] = {}
        self.screens: dict[str, int] = {}          # whole-screen key → times seen
        self.phase = (0, 0)
        self.pending: set[str] = set()             # sent or queued for the model, no answer yet

    # ---- looking up ---------------------------------------------------------------------------
    def keys(self, img: np.ndarray, search: bool = True) -> np.ndarray:
        """The cell keys at the screen's grid phase. A scrolled screen is cut where most cells are already known: the
        last phase first, (0, 0) next, and all 64 only when both answer under half the cells."""
        tried: dict[tuple[int, int], np.ndarray] = {}

        def hits(p):
            tried[p] = grid(img, p)
            k = tried[p]
            return sum(1 for v in k.flat if v in self.cells) / k.size

        best = max(((hits(p), p) for p in {self.phase, (0, 0)}), key=lambda t: (t[0], t[1] == (0, 0)))
        if search and best[0] < 0.5 and len(self.cells) >= 50:
            for p in [(dx, dy) for dy in range(CELL) for dx in range(CELL)]:
                if p not in tried:
                    s = hits(p)
                    if s > best[0] + 0.1:
                        best = (s, p)
        self.phase = best[1]
        return tried[best[1]]

    def screen_key(self, img: np.ndarray) -> str:
        return _hash(np.ascontiguousarray(img).tobytes())

    def see(self, img: np.ndarray, keys: np.ndarray) -> dict[str, Any]:
        """Count one frame: its cells' and screen's sightings. Returns what the book could answer for it."""
        sk = self.screen_key(img)
        screen_known = sk in self.screens
        self.screens[sk] = self.screens.get(sk, 0) + 1
        flat = list(keys.flat)
        known = [k in self.cells for k in flat]
        for k, kn in zip(flat, known):
            if kn:
                self.cells[k]["seen"] += 1
        return {"cells": len(flat), "known": sum(known), "screen_known": screen_known,
                "novel": [i for i, kn in enumerate(known) if not kn]}

    def label(self, key: str) -> str | None:
        e = self.cells.get(key)
        return e["label"] if e else None

    def labels(self, keys: np.ndarray) -> np.ndarray:
        return np.vectorize(lambda k: self.label(k) or "?", otypes=[object])(keys)

    def novel(self, keys: np.ndarray) -> list[tuple[int, int]]:
        return [(r, c) for r in range(keys.shape[0]) for c in range(keys.shape[1])
                if keys[r, c] not in self.cells and keys[r, c] not in self.pending]

    # ---- learning ------------------------------------------------------------------------------
    def vote(self, key: str, letter: str, source: str = "model") -> str:
        """One answer for a cell. Returns 'new', 'agree' or 'contradict'."""
        letter = letter.upper() if letter.upper() in LABELS else "U"
        e = self.cells.get(key)
        if e is None:
            self.cells[key] = {"votes": {letter: 1}, "label": letter, "state": "labelled", "seen": 1,
                               "contradictions": 0, "source": source}
            return "new"
        e["votes"][letter] = e["votes"].get(letter, 0) + 1
        if letter == e["label"] or letter == "U":
            if e["state"] == "labelled" and letter != "U" and sum(e["votes"].values()) >= 2:
                e["state"] = "verified"
            return "agree"
        e["contradictions"] += 1
        lead = max(e["votes"].items(), key=lambda kv: kv[1])[0]
        if lead != e["label"]:
            e["label"], e["state"] = lead, "labelled"
        return "contradict"

    def confirm(self, key: str, walkable: bool) -> str:
        """The game's own answer about a cell (the player walked onto it, or bumped into it twice). A cell the model
        never saw is learned from it; one it saw is verified or contradicted."""
        letter = "G" if walkable else "W"
        e = self.cells.get(key)
        if e is None:
            self.cells[key] = {"votes": {letter: 1}, "label": letter, "state": "verified", "seen": 1,
                               "contradictions": 0, "source": "game"}
            return "new"
        if (e["label"] in WALKABLE) == walkable and e["label"] not in ENTITY:
            e["state"] = "verified"
            return "agree"
        if e["label"] in ENTITY or e["label"] in ("U", "B", "T", "M"):
            return "skip"                      # the game says nothing about these letters
        e["contradictions"] += 1
        e["votes"][letter] = e["votes"].get(letter, 0) + 2      # the game outweighs one model answer
        e["label"], e["state"] = max(e["votes"].items(), key=lambda kv: kv[1])[0], "verified"
        return "contradict"

    def stats(self) -> dict[str, Any]:
        st = Counter(e["state"] for e in self.cells.values())
        lab = Counter(e["label"] for e in self.cells.values())
        return {"cells": len(self.cells), "screens": len(self.screens), "states": dict(st), "labels": dict(lab),
                "contradictions": sum(e["contradictions"] for e in self.cells.values())}

    def dump(self) -> dict[str, Any]:
        return {"cells": self.cells, "phase": list(self.phase)}

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.dump(), f)

    def load(self, path: str | dict) -> None:
        d = path if isinstance(path, dict) else json.load(open(path))
        self.cells.update(d.get("cells") or {})
        self.phase = tuple(d.get("phase") or (0, 0))


# ---- walking from pixels ----------------------------------------------------------------------------
DIRS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


def shift(prev: np.ndarray, cur: np.ndarray, direction: str, steps=(8, 16)) -> int:
    """How far the picture moved against `direction` (a scrolling screen follows the player): the step that makes the
    overlapping parts equal on at least 90% of pixels, else 0."""
    dx, dy = DIRS[direction]
    for s in steps:
        ox, oy = -dx * s, -dy * s          # content moves opposite to the walk
        h, w = prev.shape[:2]
        a = prev[max(0, -oy):h - max(0, oy), max(0, -ox):w - max(0, ox)]
        b = cur[max(0, oy):h - max(0, -oy), max(0, ox):w - max(0, -ox)]
        if a.size and (a == b).all(axis=2).mean() >= 0.9:
            return s
    return 0


def player_cells(labels: np.ndarray) -> list[tuple[int, int]]:
    return [(r, c) for r in range(labels.shape[0]) for c in range(labels.shape[1]) if labels[r, c] == "P"]


def ahead(cells: list[tuple[int, int]], direction: str, shape: tuple[int, int], reach: int = 2) -> list[tuple[int, int]]:
    """The cells just past the player's lowest cells in the direction pressed (its feet: the ground it would step on)."""
    if not cells:
        return []
    feet_row = max(r for r, _ in cells)
    feet = [(r, c) for r, c in cells if r >= feet_row - 1]
    dx, dy = DIRS[direction]
    rows, cols = shape
    out = set()
    if dx:
        edge = max(c for _, c in feet) if dx > 0 else min(c for _, c in feet)
        for r in {r for r, _ in feet}:
            for k in range(1, reach + 1):
                out.add((r, edge + dx * k))
    else:
        edge = max(r for r, _ in feet) if dy > 0 else min(r for r, _ in feet)
        for c in {c for _, c in feet}:
            for k in range(1, reach + 1):
                out.add((edge + dy * k, c))
    return sorted((r, c) for r, c in out if 0 <= r < rows and 0 <= c < cols)


# ---- the labeller -------------------------------------------------------------------------------------
SYSTEM = """You label small pieces of a video game screen. The first image is the whole screen, enlarged, with the
pieces outlined. The second image is a sheet of numbered tiles: each tile shows one piece (inside the red square)
with a little of what surrounds it. For every number answer one letter for the piece inside the red square:
T text (a letter, digit or punctuation mark of written text)
G ground the player can walk or stand on (floor, path, grass, platform top, road)
D door, stairs, ladder or exit
W wall or obstacle the player cannot pass (trees, water, furniture, rock, fences, solid blocks)
P the player character (any part of it)
E another character or object that moves or can be picked up (people, enemies, items, projectiles)
M menu, window border, HUD, cursor or other interface graphics that are not letters
B blank or background with nothing on it (empty sky, plain fill, black)
U unsure
Judge each piece by what is drawn inside its red square and where it sits on the whole screen: a piece next to a
character but showing none of it is labelled by what it does show. Answer with JSON only, one entry per
number: {"0": "G", "1": "W", ...}"""


def _png(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img_bgr)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def screen_image(img_rgb: np.ndarray, boxes: list[tuple[int, int]], scale: int = 3) -> np.ndarray:
    """The screen enlarged with the given cells (pixel corners) outlined."""
    big = cv2.resize(img_rgb[:, :, ::-1], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    for x, y in boxes:
        cv2.rectangle(big, (x * scale, y * scale), ((x + CELL) * scale - 1, (y + CELL) * scale - 1), (0, 0, 255), 1)
    return big


def crop(img_rgb: np.ndarray, x: int, y: int, ctx: int = CELL) -> np.ndarray:
    """A cell (pixel corner x, y) with `ctx` pixels around it, padded grey at the screen's edge, RGB."""
    pad = np.pad(img_rgb, ((ctx, ctx), (ctx, ctx), (0, 0)), constant_values=128)
    return pad[y:y + CELL + 2 * ctx, x:x + CELL + 2 * ctx]


def sheet(crops: list[np.ndarray], scale: int = 4, cols: int = 8) -> np.ndarray:
    """Numbered tiles, the centre cell of each outlined, BGR."""
    side = crops[0].shape[0] * scale
    lab = 18
    rows = (len(crops) + cols - 1) // cols
    out = np.full((rows * (side + lab), cols * (side + 6), 3), 255, np.uint8)
    for n, c in enumerate(crops):
        r, k = divmod(n, cols)
        x0, y0 = k * (side + 6), r * (side + lab) + lab
        out[y0:y0 + side, x0:x0 + side] = cv2.resize(c[:, :, ::-1], (side, side), interpolation=cv2.INTER_NEAREST)
        a = (side - CELL * scale) // 2
        cv2.rectangle(out, (x0 + a - 1, y0 + a - 1), (x0 + a + CELL * scale, y0 + a + CELL * scale), (0, 0, 255), 2)
        cv2.putText(out, str(n), (x0 + 2, y0 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return out


def parse(text: str, n: int) -> str | None:
    """The model's letters, one per piece ('U' for a number it left out); None when it answered under half of them."""
    try:
        s = text[text.index("{"): text.rindex("}") + 1]
        d = json.loads(s)
    except (ValueError, AttributeError):
        return None
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("labels"), str):                     # a run of letters
        letters = "".join(ch for ch in d["labels"].upper() if ch.isalpha())
        return letters if len(letters) == n else None
    got = {str(k).strip(): str(v).strip().upper()[:1] for k, v in d.items()}
    if sum(1 for i in range(n) if got.get(str(i))) < n / 2:
        return None
    return "".join(got.get(str(i)) or "U" for i in range(n))


class Labeller:
    """Novel cells, one crop per new key, sent `per_call` keys at a time with the newest screen as context.
    `budget` (dollars) stops it; `spent` returns the dollars spent so far by everything sharing the budget."""

    def __init__(self, chat=None, per_call: int = 40, max_screens: int = 6, budget: float | None = None,
                 spent: Callable[[], float] | None = None, extra: dict[str, Any] | None = None, log=None):
        self.chat = chat
        self.per_call = per_call
        self.max_screens = max_screens
        self.budget = budget
        self.spent = spent or (lambda: chat.cost if chat else 0.0)
        self.extra = extra if extra is not None else {"reasoning_effort": "low"}
        self.queue: list[tuple[str, np.ndarray]] = []       # (key, crop)
        self.screens = 0
        self.context: tuple[np.ndarray, list[tuple[int, int]]] | None = None
        self.calls = 0
        self.failed = 0
        self.log = log

    def over(self) -> bool:
        return self.budget is not None and self.spent() >= self.budget

    def add(self, img: np.ndarray, keys: np.ndarray, phase: tuple[int, int], book: CellBook, tag: Any = None) -> bool:
        """Queue the screen's new keys (one crop each). Returns whether anything was queued."""
        dx, dy = phase
        boxes = []
        for r in range(keys.shape[0]):
            for c in range(keys.shape[1]):
                k = keys[r, c]
                if k in book.cells or k in book.pending:
                    continue
                book.pending.add(k)
                x, y = dx + c * CELL, dy + r * CELL
                boxes.append((x, y))
                self.queue.append((k, crop(img, x, y)))
        if not boxes:
            return False
        self.screens += 1
        self.context = (img, boxes)
        return True

    def ready(self) -> bool:
        return len(self.queue) >= self.per_call or (self.screens >= self.max_screens and bool(self.queue))

    def flush(self, book: CellBook) -> dict[str, Any] | None:
        """Send up to `per_call` queued keys as one call and enter the answers in the book."""
        if not self.queue or self.chat is None or self.over():
            return None
        batch, self.queue = self.queue[:self.per_call], self.queue[self.per_call:]
        self.screens = 0 if not self.queue else 1
        img, boxes = self.context
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": f"{len(batch)} numbered pieces (0 to {len(batch) - 1})."},
            {"type": "image_url", "image_url": {"url": _png(screen_image(img, boxes)), "detail": "high"}},
            {"type": "image_url", "image_url": {"url": _png(sheet([c for _, c in batch])), "detail": "high"}}]
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": parts}]
        entry: dict[str, Any] = {"kind": "cell_labeller", "keys": len(batch)}
        try:
            text, usage, ms = self.chat.complete(msgs, max_tokens=4000, extra=self.extra)
        except Exception as e:  # noqa: BLE001 — one failed call loses a batch, not the run
            self.failed += 1
            book.pending.difference_update(k for k, _ in batch)
            entry["error"] = str(e)[:200]
            if self.log:
                self.log(entry)
            return entry
        self.calls += 1
        letters = parse(text, len(batch))
        book.pending.difference_update(k for k, _ in batch)
        tally: Counter = Counter()
        if letters is None:
            tally["bad_answer"] += 1
            self.queue = batch + self.queue if self.failed < 50 else self.queue      # once more, in the next call
            book.pending.update(k for k, _ in batch)
            self.failed += 1
        else:
            for (k, _), L in zip(batch, letters):
                tally[book.vote(k, L)] += 1
        entry.update({"ms": ms, "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")},
                      "tally": dict(tally), "letters": letters, "raw": None if letters else text[:400], "keys_sent": [k for k, _ in batch]})
        if self.log:
            self.log(entry)
        return entry
