"""How many labeller calls a cold glyph book takes to read a game's text, by labelling policy, with an oracle in place
of the chat model: a finished book from an earlier run answers each line (a glyph it does not know reads as a
character of its own). No model is called, so the policies compare for free.

    python scripts/glyph_coldstart.py <rom> <finished book.json> [--state S] [--steps 1500]
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.perceive.tiletext import GlyphBook, TileText  # noqa: E402


class Oracle:
    def __init__(self, labels: dict[str, str]):
        self.labels = labels
        self.calls = 0

    def answer(self, book: GlyphBook, max_lines: int) -> int:
        lines = book.pick(max_lines)
        if not lines:
            return 0
        book.calls += 1
        ok = 0
        for k, _ in lines:
            words = ["".join(self.labels.get(x) or chr(0x4E00 + int(x[:4], 16) % 2000) for x in (k[i] for i in r))
                     for r in book.runs(list(k))]
            ok += book.vote(list(k), " ".join(words), "chat")
        return ok


def run(frames, labels, scenery_once, max_lines, max_calls=40, batch=6, patience=20):
    book = GlyphBook()
    book.scenery_once = scenery_once
    t = TileText({"labeller": "none", "max_calls": max_calls, "batch": batch, "patience": patience}, book)
    oracle = Oracle(labels)
    known = unknown = 0
    first_full = None
    for i, f in enumerate(frames):
        # TileText.read's own trigger, with the oracle in place of the background labeller
        _, info = _read_only(t, f)
        waiting = book.pending()
        if waiting and (waiting >= t.batch or (info["unknown"] and not info["known"]) or t.reads_since >= t.patience):
            t.reads_since = 0
            if book.calls < max_calls:
                oracle.answer(book, max_lines)
        if i >= len(frames) - 300:
            known += info["known"]
            unknown += info["unknown"]
        if first_full is None and book.calls and not book.pending():
            first_full = i
    return {"calls": book.calls, "glyphs": len(book.labels),
            "text": sum(1 for v in book.labels.values() if v != "#"), "not_text": sum(1 for v in book.labels.values() if v == "#"),
            "read_last_300": round(known / max(1, known + unknown), 3)}


def _read_only(t: TileText, frame):
    """TileText.read without its labeller call (the caller plays the labeller)."""
    from anygame.perceive import tiletext as tt
    img, keys, kinds = tt.cells(frame, t.size, t.cell, t.offset)
    segments: list[str] = []
    unknown = known = 0
    for r, row in enumerate(keys):
        seg = []
        for q, k in enumerate(row + [None]):
            kind = kinds[r, q] if q < len(row) else 2
            lab = t.book.labels.get(k) if kind == 1 else None
            if kind == 2 or lab == tt.NOT_TEXT:
                u, n = t._segment(seg, segments)
                unknown, known, seg = unknown + u, known + n, []
            else:
                seg.append((tt.BLANK, None) if kind == 0 else (lab if lab is not None else "?", k))
        t._collect(img, row, kinds[r], r)
    t.reads_since += 1
    return " ".join(segments), {"known": known, "unknown": unknown}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("book")
    ap.add_argument("--state", default=None)
    ap.add_argument("--steps", type=int, default=1500)
    a = ap.parse_args()
    from anygame.device.pyboy import PyBoyDevice
    d = PyBoyDevice(f"pyboy://{a.rom}" + (f"?state={a.state}" if a.state else ""))
    rnd = random.Random(0)
    frames = []
    for _ in range(a.steps):
        frames.append(d.screen().copy())
        d.press(rnd.choice(["a", "a", "b", "start", "up", "down", "left", "right"]), hold=8, after=20)
    labels = json.load(open(a.book)).get("labels", {})
    for name, kw in [("before: 6 waiting lines start a call of up to 12", dict(scenery_once=False, max_lines=12)),
                     ("scenery settled in one reading", dict(scenery_once=True, max_lines=12)),
                     ("+ 12 waiting lines start a call of up to 24", dict(scenery_once=True, max_lines=24, batch=12)),
                     ("+ 24 waiting lines start a call of up to 48", dict(scenery_once=True, max_lines=48, batch=24))]:
        print(f"  {name:48s} {run(frames, labels, **kw)}")


if __name__ == "__main__":
    main()
