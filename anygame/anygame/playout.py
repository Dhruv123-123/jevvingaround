"""A choice judged by where it leads: play it from a save state until the game asks again, and report what it said.

A menu entry's consequence after 90 frames is a screen that has started to change. A battle move needs several
seconds of text before the game shows what it did ("It's super effective!", "Enemy BULBASAUR fainted!"). A shop
purchase needs a confirmation, and an item needs its use played out. So from the current moment:

  1. press the keys of the choice;
  2. let the game run; whenever the screen has stood still for a while, look at whether the game is asking: a
     direction that changes the screen differently from waiting (a cursor moves, the player walks) means it is,
     and the play-out ends there;
  3. otherwise press A to page on (a text box waiting for a button), and keep going;
  4. keep every new text the screen showed, in order, and the numbers on screen before and after;
  5. put the game back exactly as it was.

The emulator is the forward model, so nothing here knows a game. Randomness (a miss, a critical hit) makes one play-out
a sample; `delays` plays the same choice after a few different wait lengths, which on most games changes the random
draws, and reports each.

    from anygame.playout import play_out, describe
    r = play_out(device, ["a"], read_text)        # read_text(screen) -> str, e.g. a tiletext reader
    describe(r)  →  "'SQUIRTLE used TACKLE!' 'Enemy BULBASAUR's DEFENSE fell!'; then asks again (8.1 s); 19/19 → 17/19"
"""
from __future__ import annotations
import re
from typing import Any, Callable

import numpy as np

NUM = re.compile(r"\d+(?:\s*/\s*\d+)?")


def _small(img: np.ndarray) -> np.ndarray:
    g = img.mean(axis=2) if img.ndim == 3 else img
    s = max(1, g.shape[0] // 144)
    return g[::s, ::s].astype(np.int16)


def _differs(a: np.ndarray, b: np.ndarray, thr: float = 0.5) -> bool:
    return float(np.abs(_small(a) - _small(b)).mean()) > thr


def numbers(text: str) -> list[str]:
    """The numbers in a screen's text, in reading order, a fraction ("19/ 19") kept as one."""
    return [re.sub(r"\s+", "", n) for n in NUM.findall(text or "")]


def asks(device, frames: int = 24, dirs: tuple[str, ...] = ("down", "right")) -> bool:
    """Whether the game is waiting for a choice now: a direction changes the screen differently from waiting."""
    seqs: dict[str, list] = {"wait": []}
    for d in dirs:
        seqs[d] = [d]
    out = device.branch(seqs, frames=frames)
    return any(_differs(out[d]["screen"], out["wait"]["screen"]) for d in dirs)


def play_out(device, keys: list[str], read_text: Callable[[np.ndarray], str], *, max_frames: int = 2400, step: int = 20,
             still: int = 2, hold: int = 4, gap: int = 10, delay: int = 0, restore: bool = True) -> dict[str, Any]:
    """Play `keys`, then run until the game asks again (or `max_frames`). Returns {lines, end, frames, pages,
    numbers_before, numbers_after, text_after}. The game is put back as it was unless `restore` is False."""
    snap = device.snapshot()
    disc, device.discoverer = getattr(device, "discoverer", None), None     # trying keys must not teach discovery
    t0 = device.frames
    lines: list[str] = []
    pages = 0
    end = "cap"
    try:
        before = read_text(device.screen())
        if delay:
            device.wait(delay)
        for k in keys:
            k, _, h = str(k).partition(":")
            device.press(k, hold=int(h) if h else hold, after=gap)
        prev = device.screen()
        calm = 0
        last_text = before
        while device.frames - t0 < max_frames:
            device.wait(step)
            img = device.screen()
            if _differs(img, prev):
                calm = 0
                prev = img
                continue
            calm += 1
            if calm < still:
                continue
            text = read_text(img)
            if text and text != last_text and not (lines and text == lines[-1]):
                lines.append(text)
            last_text = text
            if asks(device):
                end = "asks"
                break
            device.press("a", hold=hold, after=gap)      # a text box waiting for a button: page on
            pages += 1
            calm = 0
            prev = device.screen()
        after = read_text(device.screen())
        out = {"lines": lines, "end": end, "frames": device.frames - t0, "pages": pages, "text_before": before,
               "numbers_before": numbers(before), "numbers_after": numbers(after), "text_after": after}
    finally:
        if restore:
            device.restore(snap)
        device.discoverer = disc
    return out


def play_outs(device, keys: list[str], read_text, delays: tuple[int, ...] = (0, 7, 13), **kw) -> list[dict[str, Any]]:
    """The same choice played after a few wait lengths: samples of what it leads to."""
    return [play_out(device, keys, read_text, delay=d, **kw) for d in delays]


def new_lines(r: dict[str, Any]) -> list[str]:
    """The text a play-out produced: each line without the words that were already on screen before the choice (a
    status display, the menu itself), and without the typed-out prefixes of the same box."""
    from collections import Counter
    out: list[str] = []
    for t in r["lines"]:
        have = Counter((r.get("text_before") or "").split())
        words = []
        for w in t.split():
            if have[w] > 0:
                have[w] -= 1
            else:
                words.append(w)
        t = " ".join(w for w in words if w.strip("?"))      # a word read only as '?' carries nothing
        if not t:
            continue
        if out and t.startswith(out[-1]):
            out[-1] = t
        elif not out or out[-1] != t:
            out.append(t)
    return out


def describe(r: dict[str, Any] | list[dict[str, Any]], width: int = 240) -> str:
    """One line for the decider: what the game said, whether it asked again, and the numbers that moved."""
    rs = r if isinstance(r, list) else [r]
    first = rs[0]
    said = " ".join(f"'{t}'" for t in new_lines(first))
    bits = [said or "no new text"]
    ends = {x["end"] for x in rs}
    secs = first["frames"] / 60
    bits.append(f"then asks again ({secs:.1f} s)" if ends == {"asks"} else f"still going after {secs:.0f} s" if ends == {"cap"}
                else "sometimes asks again, sometimes still going")
    nb, na = first["numbers_before"], first["numbers_after"]
    moved = [f"{a} → {b}" for a, b in zip(nb, na) if a != b] if len(nb) == len(na) else []
    if moved:
        bits.append(", ".join(moved[:4]))
    if len(rs) > 1:
        endings = {tuple(new_lines(x))[-1:] for x in rs}
        if len(endings) > 1:
            bits.append(f"{len(endings)} different outcomes in {len(rs)} tries")
    return "; ".join(bits)[:width]
