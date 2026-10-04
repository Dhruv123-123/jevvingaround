"""Text read exactly from a tile-drawn screen: each glyph learned once, then every later line read in microseconds.

A Game Boy (and most 8- and 16-bit hardware) draws text as cells of a fixed grid, one character per cell: Pokemon's
text boxes, its menus and battle messages, Aevilia's dialogue box. So the pixels of a cell are the glyph's identity.
This read cuts the screen into its cells and keys each two-colour cell by its ink mask (the minority colour, so the
same letter in black-on-white and white-on-black is one glyph). A glyph's character is learned once:

  labeller  a line of cells with glyphs not known yet is shown to the chat model (Azure, never OpenRouter) as an image,
            and it answers one character per cell; an answer of the wrong length is discarded, and one that disagrees
            with the glyphs already known is too (it read a different line, or misread). With no chat model, OCR of the
            same clean line is the labeller, kept only when it finds one character per inked cell.
  trusted   a glyph is read once two lines agree on it, or one line agrees with at least three glyphs already trusted
            (two lines when its character is already another glyph's: a lookalike such as w read as v).
            Until then it reads as '?'.

Nothing here knows a game. The book of glyphs is data: kept in memory for the run and, with `book:` (a path, relative
to the pack) or ANYGAME_GLYPHS, saved and loaded so a later run starts from it.

    text: { kind: tiletext, when: { read: screen, in: [text, choice, button] }, otherwise: "",
            size: [160, 144], cell: 8, fallback: ocr }

The value is the text on screen: each run of cells that reads as text, top to bottom, joined by spaces. With
`fallback: ocr`, a screen whose text cells are still mostly unknown is read by OCR meanwhile.
"""
from __future__ import annotations
import base64
import json
import os
import re
import threading
from collections import Counter
from typing import Any

import cv2
import numpy as np

BREAK, BLANK = "\x00", " "
NOT_TEXT = "#"            # the labeller's answer for a cell that is not a character (a border, an icon)
SYSTEM = """You transcribe text from a video game screen. Each image is one line of a fixed-width pixel font, shown
enlarged: every character, punctuation included, takes exactly one cell, and words are separated by one empty cell.
You are told how many cells each word of a line has. Answer the line as a list of words with exactly those lengths.
Copy the case exactly as drawn: capitals stay capitals (a word drawn as POKéMON is "POKéMON", not "Pokémon"), small
letters stay small. Keep punctuation and digits (é ' - . ! ? / : , ; ( ) and so on). A cell that is not a character (a
piece of a box border, an icon, a picture) is "#", even when it touches a word; a cursor arrow pointing right is ">";
a small arrow pointing down is "▼" (never "v", which is the letter). If a cell holds two characters squeezed
together (like 's), give the letter.
Answer with JSON only: {"lines": [["word", "word", ...], ...]}, one list per image, in order."""


def _packed(frame: np.ndarray) -> np.ndarray:
    f = frame.astype(np.int32)
    if f.ndim == 2:
        return f
    return (f[:, :, 0] << 16) | (f[:, :, 1] << 8) | f[:, :, 2]


class GlyphBook:
    def __init__(self, path: str | None = None):
        self.path = path
        self.labels: dict[str, str] = {}             # glyph key → its character ('#' not a character)
        self.votes: dict[str, Counter] = {}
        self.queue: dict[tuple, np.ndarray] = {}     # a line of keys (None = empty cell) → its strip image, waiting
        self.asked: set[tuple] = set()
        self.calls = 0
        self.rejected = 0
        self.ms: list[int] = []
        self.lock = threading.RLock()
        if path and os.path.exists(path):
            self.load(path)

    # ---- learning -------------------------------------------------------------------------------------------
    @staticmethod
    def runs(keys: list[str | None]) -> list[list[int]]:
        """The inked cells of a line, grouped into words (an empty cell between them)."""
        out: list[list[int]] = [[]]
        for i, k in enumerate(keys):
            if k:
                out[-1].append(i)
            elif out[-1]:
                out.append([])
        return [r for r in out if r]

    def vote(self, keys: list[str | None], answer: str, source: str) -> bool:
        """One reading of a line, as text. It is kept only when its words have exactly the lengths of the line's runs of
        inked cells (so each character lands on its cell, whatever the reader did with spacing), and when it agrees
        with the glyphs already trusted."""
        runs, words = self.runs(keys), answer.split()
        if len(runs) != len(words) or any(len(r) != len(w) for r, w in zip(runs, words)):
            self.rejected += 1
            return False
        glyph: dict[str, str] = {}
        for r, w in zip(runs, words):
            for i, ch in zip(r, w):
                if glyph.setdefault(keys[i], ch) != ch:      # one glyph read as two characters: a misread line
                    self.rejected += 1
                    return False
        known = [(k, c) for k, c in glyph.items() if k in self.labels]
        agree = sum(1 for k, c in known if self.labels[k] == c)
        if known and agree < 0.9 * len(known):
            self.rejected += 1
            return False
        with self.lock:
            for k, c in glyph.items():          # once per line: a letter twice in a word is one reading
                if k in self.labels:
                    continue
                v = self.votes.setdefault(k, Counter())
                v[c] += 1
                top, n = v.most_common(1)[0]
                # two agreeing lines; or, from the chat model, one line whose other glyphs it read exactly as trusted
                # (three of them, or every one of at least one: a short status line such as "19/ 19")
                vouched = agree >= 3 or (agree >= 1 and agree == len(known))
                if vouched and c != "#" and any(lab == c and o != k for o, lab in self.labels.items()):
                    # a character another glyph is already read as: a second glyph for it (a shifted copy) is
                    # possible, but so is a lookalike misread (w read as v, the cursor read as R). Two lines decide
                    vouched = False
                if (n >= 2 and n > 0.66 * sum(v.values())) or (vouched and len(v) == 1 and source == "chat"):
                    self.labels[k] = top
        return True

    def pending(self) -> int:
        return len(self.queue)

    def label(self, chat=None, max_lines: int = 12, scale: int = 6, log=None) -> int:
        """Ask for the waiting lines: the chat model when there is one, else OCR. Returns lines accepted."""
        with self.lock:
            lines = [(k, img) for k, img in self.queue.items() if any(x and x not in self.labels for x in k)][:max_lines]
            for k, _ in lines:
                self.queue.pop(k, None)
                self.asked.add(k)
            if len(self.queue) > 200:          # lines whose glyphs were all learned meanwhile, or a flood: keep the newest
                for k in list(self.queue)[:-200]:
                    self.queue.pop(k)
        if not lines:
            return 0
        ok = 0
        if chat is not None:
            desc = "; ".join(f"line {i + 1}: words of " + ", ".join(str(len(r)) for r in self.runs(list(k))) + " cells"
                             for i, (k, _) in enumerate(lines))
            parts: list[dict[str, Any]] = [{"type": "text", "text": desc}]
            for _, img in lines:
                parts.append({"type": "image_url", "image_url": {"url": _png_url(_strip(img, scale))}})
            self.calls += 1
            entry: dict[str, Any] = {"kind": "glyph_labeller", "lines": len(lines)}
            try:
                text, usage, ms = chat.complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": parts}],
                                                max_tokens=6000, extra={"reasoning_effort": "low"})
                self.ms.append(ms)
                entry.update(ms=ms, tokens=usage.get("total_tokens"))
                m = re.search(r"\{.*\}", text, re.S)
                got = json.loads(m.group(0)).get("lines") if m else None
                if not isinstance(got, list):
                    raise ValueError(f"no lines in the answer: {text[:120]!r}")
                for (k, _), a in zip(lines, got):
                    ok += self.vote(list(k), " ".join(map(str, a)) if isinstance(a, list) else str(a), "chat")
                entry.update(accepted=ok, answers=[str(a)[:60] for a in got])
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)[:200]
                with self.lock:
                    for k, _ in lines:       # asked again later
                        self.asked.discard(k)
            if log is not None:
                log(entry)
        else:
            for k, img in lines:
                ok += self._ocr_vote(list(k), img)
        if ok and self.path:
            self.save(self.path)
        return ok

    def _ocr_vote(self, keys: list[str | None], img: np.ndarray) -> bool:
        from .ocr import engine
        res, _ = engine()(_strip(img, 4))
        return self.vote(keys, " ".join(t[1] for t in (res or [])), "ocr")

    # ---- the data file ----------------------------------------------------------------------------------------
    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            with self.lock:
                json.dump({"labels": dict(self.labels), "votes": {k: dict(v) for k, v in self.votes.items()}}, f)
        os.replace(tmp, path)

    def load(self, path: str) -> None:
        d = json.load(open(path))
        self.labels.update(d.get("labels") or {})
        for k, v in (d.get("votes") or {}).items():
            self.votes.setdefault(k, Counter()).update(v)


def _strip(img: np.ndarray, scale: int) -> np.ndarray:
    """A line of cells enlarged, with a one-cell margin: what the labeller sees."""
    pad = cv2.copyMakeBorder(img, 4, 4, 4, 4, cv2.BORDER_REPLICATE)
    return cv2.resize(pad, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def _png_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def cells(frame: np.ndarray, size: tuple[int, int] = (160, 144), cell: int = 8, offset: tuple[int, int] = (0, 0)):
    """The screen at its native size cut into cells. Returns (native image, keys grid, kinds grid): kind 0 is a cell of
    one colour (empty), 1 two colours with a small ink mask (glyph-like, keyed), 2 anything else (a picture)."""
    h, w = frame.shape[:2]
    s = max(1, h // size[1])
    img = frame[::s, ::s][: size[1], : size[0]]
    ox, oy = offset
    rows, cols = (img.shape[0] - oy) // cell, (img.shape[1] - ox) // cell
    p = _packed(img[oy: oy + rows * cell, ox: ox + cols * cell])
    c = p.reshape(rows, cell, cols, cell).transpose(0, 2, 1, 3).reshape(rows, cols, cell * cell)
    lo, hi = c.min(2), c.max(2)
    n_lo = (c == lo[..., None]).sum(2)
    n_hi = (c == hi[..., None]).sum(2)
    two = (n_lo + n_hi == cell * cell) & (lo != hi)
    ink = np.where((n_lo <= n_hi)[..., None], c == lo[..., None], c == hi[..., None])
    n_ink = ink.sum(2)
    kinds = np.where(lo == hi, 0, np.where(two & (n_ink >= 3) & (n_ink <= cell * cell * 5 // 8), 1, 2))
    bits = np.packbits(ink.astype(np.uint8), axis=2)
    keys = [[bits[r, q].tobytes().hex() if kinds[r, q] == 1 else None for q in range(cols)] for r in range(rows)]
    return img, keys, kinds


class TileText:
    def __init__(self, r: dict[str, Any], book: GlyphBook):
        self.r = r
        self.book = book
        self.size = tuple(r.get("size", (160, 144)))
        self.cell = int(r.get("cell", 8))
        self.offset = tuple(r.get("offset", (0, 0)))
        self.min_run = int(r.get("min_run", 3))
        self.batch = int(r.get("batch", 6))           # lines waiting before the labeller is called
        self.max_calls = int(r.get("max_calls", 40))
        self.chat = None
        self.chat_tried = False
        self.log = None
        self.last: dict[str, Any] = {}
        self.sync = bool(r.get("sync", False))
        self.patience = int(r.get("patience", 20))      # reads a short queue waits before it is labelled anyway
        self.reads_since = 0
        self._job = None

    def wait(self) -> None:
        """Until the labeller in the background is done (a check script's end; a run never waits)."""
        if self._job is not None:
            self._job.result()

    def _chat(self):
        if self.r.get("labeller", "chat") != "chat" or self.chat_tried:
            return self.chat
        self.chat_tried = True
        if os.environ.get("ANYGAME_LLM_BASE") and os.environ.get("ANYGAME_LLM_MODEL"):
            try:
                from ..chat import Chat
                self.chat = Chat(timeout=90)
            except SystemExit:
                self.chat = None
        return self.chat

    def read(self, frame: np.ndarray) -> tuple[str, dict[str, Any]]:
        img, keys, kinds = cells(frame, self.size, self.cell, self.offset)
        b = self.book
        segments: list[str] = []
        unknown = known = 0
        for r, row in enumerate(keys):
            seg: list[tuple[str, str | None]] = []
            for q, k in enumerate(row + [None]):
                kind = kinds[r, q] if q < len(row) else 2
                lab = b.labels.get(k) if kind == 1 else None
                if kind == 2 or lab == NOT_TEXT:
                    u, n = self._segment(seg, segments)       # a picture or a border piece ends a run of text
                    unknown, known, seg = unknown + u, known + n, []
                else:
                    seg.append((BLANK, None) if kind == 0 else (lab if lab is not None else "?", k))
            self._collect(img, row, kinds[r], r)
        self.reads_since += 1
        # a full batch, a screen with nothing known yet, or a few lines that have waited long enough (a status
        # display's digits may be the only new glyphs for a long while)
        waiting = b.pending()
        if waiting and (waiting >= self.batch or (unknown and not known) or self.reads_since >= self.patience):
            self.reads_since = 0
            chat = self._chat()
            if chat is None or b.calls < self.max_calls:
                if self.sync:
                    b.label(chat, log=self.log)
                elif self._job is None or self._job.done():
                    # the labeller takes seconds: the run goes on reading what is known, and the rest reads as '?'
                    self._job = _pool().submit(b.label, chat, 12, 6, self.log)
        text = " ".join(segments)
        self.last = {"known": known, "unknown": unknown, "glyphs": len(b.labels), "pending": b.pending(), "calls": b.calls}
        return text, self.last

    def _segment(self, seg: list[tuple[str, str | None]], out: list[str]) -> tuple[int, int]:
        """A run of cells between pictures: text when it has two inked cells and more than one glyph."""
        ks = [k for _, k in seg if k]
        if len(ks) < 2 or (len(set(ks)) == 1 and len(ks) > 3):
            return 0, 0                 # one glyph repeated: a border or a pattern, not words
        text = re.sub(r" {2,}", "  ", "".join(c for c, _ in seg)).strip()
        unknown = text.count("?")
        if unknown == len(ks) and len(ks) < self.min_run:
            return 0, 0
        out.append(text)
        return unknown, len(ks) - unknown

    def _collect(self, img: np.ndarray, row: list[str | None], kinds: np.ndarray, r: int) -> None:
        """Queue each run of glyph-like cells on this row that holds a glyph not known yet."""
        b, c = self.book, self.cell
        q, n = 0, len(row)
        while q < n:
            if kinds[q] != 1:
                q += 1
                continue
            e = q
            while e < n and (kinds[e] == 1 or (kinds[e] == 0 and e + 1 < n and kinds[e + 1] == 1)):
                e += 1
            run = row[q:e]
            ks = [k for k in run if k]
            if len(ks) >= self.min_run and len(set(ks)) >= 2 and any(k not in b.labels for k in ks):
                key = tuple(run)
                with b.lock:
                    if key not in b.asked and key not in b.queue:
                        ox, oy = self.offset
                        b.queue[key] = img[oy + r * c: oy + (r + 1) * c, ox + q * c: ox + e * c].copy()
            q = e


_BOOKS: dict[str, GlyphBook] = {}
_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(1, thread_name_prefix="glyphs")
    return _POOL

_READERS: dict[int, TileText] = {}


def reader(r: dict[str, Any], pack_dir: str | None = None) -> TileText:
    """One reader per read config, one book per path (or one in-memory book), for the life of the process."""
    t = _READERS.get(id(r))
    if t is None:
        path = os.environ.get("ANYGAME_GLYPHS") or r.get("book")
        if path and pack_dir and not os.path.isabs(path):
            path = os.path.join(pack_dir, path)
        bk = _BOOKS.get(path or "")
        if bk is None:
            bk = _BOOKS[path or ""] = GlyphBook(path)
        t = _READERS[id(r)] = TileText(r, bk)
    return t


def read(frame: np.ndarray, r: dict[str, Any], pack_dir: str | None = None, rect=None, zone=None) -> str:
    t = reader(r, pack_dir)
    text, st = t.read(frame)
    if r.get("fallback") == "ocr" and st["unknown"] > max(2, st["known"]) and rect is not None:
        from . import ocr
        return ocr.read(frame, rect, zone, {"upscale": 0.67})
    return text
