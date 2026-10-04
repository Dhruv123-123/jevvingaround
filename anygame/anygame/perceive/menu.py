"""Menus and choices as one question with candidates: what each entry is and what choosing it does, found by trying.

A derived read, `kind: menu`, for any screen where the d-pad moves something without moving the player (the probe's
`choice`): a title menu, a yes/no, a character select, a battle's FIGHT/ITEM/RUN, a move list, a shop. From a save
state it

  1. presses each direction 1..`depth` times (every branch runs the same number of frames, so a blinking cursor is
     in the same phase in all of them) and keeps the distinct screens: the entries the cursor can reach, and the
     shortest key sequence to each;
  2. finds the cursor in each (the part of the screen that differs between entries and is drawn, not background)
     and reads the text on that row: the entry's label;
  3. from each entry presses A and lets the game run, and reads what came of it: the new text on screen, whether
     the player can walk now, whether the screen is the same menu (nothing happened) or a new one;
  4. does the same for B (back out), START and SELECT (a screen where only a button does anything is a choice too);
  5. puts the game back exactly as it was.

The decider gets one choice among `pick_<k>` with each entry's label and consequence, plus what was picked on this
same menu before. Nothing is known about the game: Aevilia's character select, Pokemon's battle menu and a shop are
the same read. `macro` actions play the pick with run(): the key sequence, then A.

    menu: { kind: menu, when: { read: screen, equals: choice }, depth: 5, settle: 90, pos: [found.x, found.y] }
"""
from __future__ import annotations
import hashlib
from typing import Any, Callable

import numpy as np

DIRS = ("down", "up", "right", "left")


def _small(img: np.ndarray) -> np.ndarray:
    """The emulator screen at 1x in grey: what is compared."""
    g = img.mean(axis=2) if img.ndim == 3 else img
    h, w = g.shape
    s = max(1, h // 144)
    return g[::s, ::s].astype(np.int16)


def _key(img: np.ndarray) -> str:
    return hashlib.sha1((_small(img) // 8).astype(np.int8).tobytes()).hexdigest()[:12]


def _same(a: np.ndarray, b: np.ndarray, thr: float = 0.15) -> bool:
    return float(np.abs(_small(a) - _small(b)).mean()) <= thr


def _cursor_box(img: np.ndarray, others: list[np.ndarray]) -> tuple[int, int, int, int] | None:
    """Where this screen's cursor is: of the places that differ from the other entries' screens, the one where this
    screen draws something (not the background colour). Returns (x0, y0, x1, y1) in the screen's pixels."""
    import cv2
    if not others:
        return None
    g = _small(img)
    mask = np.zeros(g.shape, np.uint8)
    for o in others:
        mask |= (np.abs(g - _small(o)) > 24).astype(np.uint8)
    if not mask.any():
        return None
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    vals, counts = np.unique(g, return_counts=True)
    bg = vals[np.argmax(counts)]
    best, best_score = None, -1.0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 4:
            continue
        sub = g[y:y + h, x:x + w][lab[y:y + h, x:x + w] == i]
        score = float((np.abs(sub - bg) > 24).mean())
        if score > best_score:
            best, best_score = (x, y, x + w, y + h), score
    if best is None:
        return None
    s = img.shape[0] / g.shape[0]
    return tuple(int(v * s) for v in best)


def _ocr_boxes(img: np.ndarray) -> list[tuple[float, float, float, float, str]]:
    """(x0, y0, x1, y1, text) for every text box on screen."""
    from .ocr import engine
    import cv2
    up = 0.67                 # 2x the Game Boy's own pixels: its 8 px font reads far better there than larger
    big = cv2.resize(img, None, fx=up, fy=up, interpolation=cv2.INTER_AREA)
    res, _ = engine()(big)
    out = []
    for box, text, _conf in res or []:
        xs = [p[0] / up for p in box]
        ys = [p[1] / up for p in box]
        out.append((min(xs), min(ys), max(xs), max(ys), text))
    return out


def _tile_boxes(img: np.ndarray, r: dict[str, Any]) -> list[tuple[float, float, float, float, str]] | None:
    """The same boxes read exactly from the screen's cells (perceive/tiletext.py, the glyph book the text read uses).
    None while most of the text on screen is glyphs not learned yet: the caller reads it by OCR meanwhile."""
    from . import tiletext
    t = tiletext.reader(r, None)
    _, st = t.read(img)
    if st["unknown"] > max(2, st["known"]):
        return None
    _, keys, kinds = tiletext.cells(img, t.size, t.cell, t.offset)
    s = max(1, img.shape[0] // t.size[1])
    c, (ox, oy) = t.cell * s, t.offset
    out = []
    for rr, row in enumerate(keys):
        run: list[tuple[int, str]] = []
        for q, k in enumerate(row + [None]):
            kind = kinds[rr, q] if q < len(row) else 2
            lab = t.book.labels.get(k) if kind == 1 else None
            if kind == 1 and lab not in (None, tiletext.NOT_TEXT):
                run.append((q, lab))
                continue
            if kind == 0 and run and q + 1 < len(row) and kinds[rr, q + 1] == 1:
                run.append((q, " "))          # one blank cell between words
                continue
            text = "".join(ch for _, ch in run).strip()
            if len(text) >= 2:
                x0, x1 = ox * s + run[0][0] * c, ox * s + (run[-1][0] + 1) * c
                out.append((float(x0), float(oy * s + rr * c), float(x1), float(oy * s + (rr + 1) * c), text))
            run = []
    return out


def _label(boxes, cur: tuple[int, int, int, int] | None) -> str:
    """The text on the cursor's row, nearest it (to its right first: a cursor arrow sits left of its entry)."""
    if cur is None:
        return ""
    cy = (cur[1] + cur[3]) / 2
    row = [b for b in boxes if b[1] - 6 <= cy <= b[3] + 6]
    if not row:
        return ""
    cx = cur[2]
    row.sort(key=lambda b: (0 if b[2] >= cur[0] else 1, abs(b[0] - cx)))
    return row[0][4].lstrip(">▶►→ ")      # the cursor's own glyph is not part of the entry's name


def _words(t: str) -> list[str]:
    return [w for w in "".join(c if c.isalnum() else " " for c in t.upper()).split() if len(w) > 1]


class MenuTracker:
    def __init__(self, r: dict[str, Any]):
        self.r = r
        self.depth = int(r.get("depth", 5))
        self.hold = int(r.get("hold", 4))
        self.gap = int(r.get("gap", 10))          # frames after each cursor press
        self.settle = int(r.get("settle", 90))     # frames after A or B before reading the result
        self.cache: dict[str, dict[str, Any]] = {}   # screen key → the read
        self.history: dict[str, list[str]] = {}      # screen key → labels picked on it before, with what came of it
        self.plans: dict[str, list[str]] = {}
        self.macros: dict[str, list[str]] = {}
        self.last_key: str | None = None
        self.last_landings: dict[str, str] = {}
        self.branches = 0
        self.reads = 0
        self.tile_cfg = dict(r.get("tiletext") or {})       # the cell grid, if not the Game Boy's 160x144 / 8 px
        self.seen: dict[str, tuple[np.ndarray, str]] = {}   # screens the run has shown: small image, its text
        self.loops: dict[str, dict[str, int]] = {}   # screen key → label → times it came straight back to this menu
        self._pending: tuple[str, str] | None = None  # the last pick: (screen key, label)
        self._since = 0                              # ticks seen since that pick

    def see(self, screen: np.ndarray, text: str | None = None) -> None:
        """A screen the run passed through (any tick): an outcome that looks like one of these leads back to it."""
        k = _key(screen)
        self._since += 1
        if k not in self.seen:
            self.seen[k] = (_small(screen), (text or "")[:60])
            if len(self.seen) > 300:
                self.seen.pop(next(iter(self.seen)))

    def _like_seen(self, img: np.ndarray, exclude: np.ndarray | None = None) -> str | None:
        g = _small(img)
        best, bd = None, float(self.r.get("seen_within", 4.0))
        for sm, txt in self.seen.values():
            if sm.shape != g.shape or (exclude is not None and float(np.abs(sm - exclude).mean()) < 1.0):
                continue
            d = float(np.abs(sm - g).mean())
            if d < bd:
                best, bd = txt or "(no text)", d
        return best

    # ---- reading the menu by trying -------------------------------------------------------------------
    def _play(self, device, keys: list[str], total: int) -> np.ndarray:
        used = 0
        for k in keys:
            device.press(k, hold=self.hold, after=self.gap)
            used += self.hold + self.gap
        if total > used:
            device.wait(total - used)
        self.branches += 1
        return device.screen()

    def explore(self, device, pos: Callable[[], tuple] | None = None) -> dict[str, Any]:
        snap = device.snapshot()
        disc, device.discoverer = getattr(device, "discoverer", None), None   # trying keys must not teach discovery
        total = self.depth * (self.hold + self.gap) + 2
        try:
            base = self._play(device, [], total)
            device.restore(snap)
            entries: list[tuple[list[str], np.ndarray]] = [([], base)]
            for d in DIRS:
                prev = base
                for n in range(1, self.depth + 1):
                    device.restore(snap)
                    img = self._play(device, [d] * n, total)
                    if _same(img, prev) or any(_same(img, e[1]) for e in entries):
                        break       # the cursor stopped (an end of the list) or came round again (a wrapping list)
                    entries.append(([d] * n, img))
                    prev = img
            # what choosing each entry does, and what B does
            pos0 = pos() if pos else None
            outcomes = []
            for keys, img in entries:
                device.restore(snap)
                outcomes.append(self._outcome(device, keys + ["a"], total, img, pos))     # against the entry, cursor on it
            if self.r.get("outcome") == "playout":
                # an entry that does something is also played on until the game asks again (anygame/playout.py): a
                # battle move's result is seconds of text later, past the short watch above
                from ..playout import play_out, describe
                for (keys, _), oc in zip(entries, outcomes):
                    if oc["same_screen"]:
                        continue
                    device.restore(snap)
                    r = play_out(device, [k for k in keys] + ["a"], self._read_text, hold=self.hold, gap=self.gap,
                                 max_frames=int(self.r.get("playout_frames", 1800)))
                    oc["playout"] = describe(r, 200)
            device.restore(snap)
            back = self._outcome(device, ["b"], total, base, pos)
            buttons = {}
            for b in self.r.get("buttons") or ["start", "select"]:
                device.restore(snap)
                buttons[b] = self._outcome(device, [b], total, base, pos)
        finally:
            device.restore(snap)
            device.discoverer = disc
        boxes = self._boxes(base)
        base_words = set(_words(" ".join(b[4] for b in boxes)))
        shots = [e[1] for e in entries]
        out = {"entries": []}
        for i, ((keys, img), oc) in enumerate(zip(entries, outcomes)):
            cur = _cursor_box(img, shots[:i] + shots[i + 1:])
            lab = _label(self._boxes(img) if i else boxes, cur) if len(entries) > 1 else ""
            out["entries"].append({"keys": keys, "label": lab, **oc})
        out["back"] = back
        out["buttons"] = buttons
        out["base_text"] = " ".join(b[4] for b in boxes)[:160]
        out["pos_before"] = pos0
        for e in out["entries"] + [back] + list(buttons.values()):
            new = [w for w in _words(e.pop("_text", "")) if w not in base_words]
            e["new_text"] = " ".join(dict.fromkeys(new))[:120]
        return out

    def _read_text(self, img: np.ndarray) -> str:
        tb = self._boxes(img, ocr=False)
        if tb is None:
            from .ocr import _text
            return _text(img, 0.67)
        return " ".join(b[4] for b in tb)

    def _boxes(self, img: np.ndarray, ocr: bool = True):
        """Text boxes on a screen: from the cells (`text: tiletext`) where the glyphs are known, else by OCR."""
        if self.r.get("text") == "tiletext":
            tb = _tile_boxes(img, self.tile_cfg)
            if tb is not None:
                return tb
        return _ocr_boxes(img) if ocr else None

    def _outcome(self, device, keys: list[str], total: int, ref: np.ndarray, pos) -> dict[str, Any]:
        img = self._play(device, keys, total + self.settle)
        tb = self._boxes(img, ocr=False)
        if tb is None:
            from .ocr import _text
            txt = _text(img, 0.67)
        else:
            txt = " ".join(b[4] for b in tb)
        p = pos() if pos else None
        g = _small(img)
        change = float(np.abs(g - _small(ref)).mean())
        return {"_text": txt, "change": round(change, 1), "walking": p is not None and None not in p, "same_screen": change < 1.0,
                "blank": float(g.std()) < 3.0, "back_to": self._like_seen(img, exclude=_small(ref))}

    # ---- the read ------------------------------------------------------------------------------------------
    def read(self, device, screen: np.ndarray, pos: Callable[[], tuple] | None = None) -> dict[str, Any]:
        k = _key(screen)
        if self._pending and self._pending[0] == k and self._since <= int(self.r.get("loop_within", 3)):
            # the last pick here led straight back to this same menu (a box that closes, an empty bag): a loop
            lp = self.loops.setdefault(k, {})
            lp[self._pending[1]] = lp.get(self._pending[1], 0) + 1
        self._pending = None
        self.last_key = k
        self.see(screen)
        m = self.cache.get(k)
        if m is None:
            m = self.explore(device, pos)
            self.cache[k] = m
            self.reads += 1
        landings, plans = {}, {}
        n = len(m["entries"])
        for i, e in enumerate(m["entries"]):
            lab = f"pick_{i + 1}"
            name = f"'{e['label']}'" if e["label"] else f"entry {i + 1} of {n}"
            where = "where the cursor is now" if not e["keys"] else f"{len(e['keys'])} x {e['keys'][0]}"
            landings[lab] = f"{name} ({where}) → {self._said(e)}"
            plans[lab] = e["keys"] + ["a"]
        b = m["back"]
        if not b["same_screen"]:
            landings["back_out"] = f"press B → {self._said(b)}"
            plans["back_out"] = ["b"]
        for bn, be in (m.get("buttons") or {}).items():
            # START or SELECT: on a screen where only a button does anything (a pause, a map, a "press START" prompt)
            if not be["same_screen"]:
                landings[f"press_{bn}"] = f"press {bn.upper()} → {self._said(be)}"
                plans[f"press_{bn}"] = [bn]
        lost = pos is not None and None in (pos() or (None,))
        firsts = {e["keys"][0] for e in m["entries"] if len(e["keys"]) == 1}
        if lost and len(firsts) >= 3:
            # each direction reached its own "entry" in one press and none came round again: more like a player
            # turning to face four ways than a menu. While where you are is unknown, offer holding each direction (a
            # walk, in a game where a tap only turns); walking is also what lets the position be found
            hold = int(self.r.get("walk_hold", 16))
            for d in ("up", "down", "left", "right"):
                landings[f"walk_{d}"] = f"hold {d.upper()} for a step (if this is the world and not a menu, you walk {d})"
                plans[f"walk_{d}"] = [f"{d}:{hold}"]
        before = self.history.get(k) or []
        times = {lab: sum(1 for h in before if h.startswith(lab + ":")) for lab in landings}
        for lab, t in times.items():
            if t:
                landings[lab] += " [chosen here before]"      # not a count: a stable read lets "did nothing" be noticed
        # best first, for a decider that takes the top: entries that do something and were not tried here yet, in
        # cursor order; then ones tried before (fewest first); entries that change nothing last
        idle = {lab for lab in landings if lab.startswith("pick_") and m["entries"][int(lab[5:]) - 1]["same_screen"]}
        back = {lab for lab in landings if lab.startswith("pick_") and m["entries"][int(lab[5:]) - 1].get("back_to") is not None}
        if len(idle) < sum(1 for lab in landings if lab.startswith("pick_")):
            for lab in idle:                 # an entry that does nothing is not a choice while others do something
                landings.pop(lab)
                plans.pop(lab, None)
        # an entry that came straight back here twice is not offered again while something else is
        looped = {lab for lab, c in (self.loops.get(k) or {}).items() if c >= 2 and lab in landings}
        if looped and len(looped) < len(landings):
            for lab in looped:
                landings.pop(lab)
                plans.pop(lab, None)
        def group(lab):
            if lab in idle:
                return 4
            if lab == "back_out" or lab.startswith("press_"):
                return 3
            if lab.startswith("walk_"):
                return 1 + (1 if times[lab] else 0)
            return 0 if not times[lab] and lab not in back else 2
        order = sorted(landings, key=lambda lab: (group(lab), times[lab], list(landings).index(lab)))
        landings = {lab: landings[lab] for lab in order}
        self.plans = plans
        self.macros = {kk: list(v) for kk, v in plans.items()}
        self.last_landings = landings
        return {"entries": n, "text": m["base_text"], "landings": landings}

    @staticmethod
    def _said(e: dict[str, Any]) -> str:
        if e["same_screen"]:
            return "nothing changes"
        if e.get("playout"):
            back = f"; first goes to a screen seen before ('{e['back_to']}')" if e.get("back_to") is not None else ""
            return "played on: " + e["playout"] + back
        bits = []
        if e["walking"]:
            bits.append("you can walk after it")
        if e.get("back_to") is not None:
            bits.append(f"goes back to a screen seen before ('{e['back_to']}')")
        elif e.get("blank"):
            bits.append("the screen goes blank: a new scene loads")
        if e["new_text"]:
            bits.append(f"new text: '{e['new_text']}'")
        elif not bits:
            bits.append("the screen changes, no new text")
        return "; ".join(bits)

    def predict(self, label: str) -> None:
        pass

    def run(self, device, label: str, look: Callable[[], dict[str, Any]], **_) -> str:
        plan = self.plans.get(label)
        if not plan:
            return f"{label}: no plan"
        for k in plan:
            k, _, h = k.partition(":")
            device.press(k, hold=int(h) if h else self.hold, after=self.gap)
        if self.last_key:
            self.history.setdefault(self.last_key, []).append(f"{label}:{self.last_landings.get(label, '')[:60]}")
            self._pending, self._since = (self.last_key, label), 0
        return f"{label}: " + " ".join(k.split(":")[0].upper() for k in plan)

    def dump(self) -> dict[str, Any]:
        return {"history": self.history, "loops": self.loops}

    def load(self, d: dict[str, Any]) -> None:
        self.history = dict(d.get("history") or {})
        self.loops = {k: dict(v) for k, v in (d.get("loops") or {}).items()}
