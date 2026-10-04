"""Numbers the game prints (HP, a level, money, a count), read from the exact text and then found in RAM, so they stay
known when they are not on screen. Nothing here knows a game.

  read      each number in the screen's text with its label: the nearest word before it with two letters or more,
            and its shape ("#" or "#/#", with what is glued to it: ":L#", "x#", "$#"). "SQUIRTLE :L5 13/ 19" gives
            SQUIRTLE :L# = 5 and SQUIRTLE #/# = 13 of 19. A fraction also has a share (0.68).
  bound     each time a number is read, work RAM is kept beside it. Once a number has shown three different values,
            the bytes whose value matched it every time (one byte, a 16-bit pair either way round, or BCD) are where
            the game keeps it. From then on `values(ram)` reads it from RAM, on screen or not, by a vote of those
            places (a scratch copy that has moved on is outvoted).
  goals     `holds(cond, values)` checks {number: {name, at_least | at_most | share_at_least | share_at_most}}, the
            condition the goal writer uses for "heal: HP at least 80%" or "train until level 14".

    book = NumberBook()
    book.observe(text, ram)          # every tick with exact text (kind: tiletext) and work RAM
    book.values(ram)                 # {"SQUIRTLE #/#": {"value": 13, "of": 19, "share": 0.68, "from": "ram"}, ...}
"""
from __future__ import annotations
import re
from typing import Any

import numpy as np

LO = 0xC000
TOKEN = re.compile(r"(?P<pre>[^\s\d]{0,2}?)(?P<n>\d+)(?:\s*/\s*(?P<of>\d+))?(?P<post>[^\s\d/]{0,1})")
MIN_VALUES = 3


def _word(w: str) -> bool:
    return sum(c.isalpha() for c in w) >= 2 and not any(c.isdigit() for c in w) and "?" not in w


def parse(text: str) -> list[dict[str, Any]]:
    """[{name, value, of?, share?}] for every number in the text, in reading order."""
    out: list[dict[str, Any]] = []
    label = ""
    seen: dict[str, int] = {}
    pos = 0
    for m in TOKEN.finditer(text or ""):
        for w in text[pos:m.start()].split():
            if _word(w):
                label = w.strip(".,:;!?")
        pos = m.end()
        pre = m.group("pre") or ""
        if "?" in pre or pre.isalpha() and len(pre) > 1:
            pre = ""
        shape = f"{pre}#" + ("/#" if m.group("of") else "")
        name = f"{label} {shape}".strip()
        k = seen.get(name, 0)
        seen[name] = k + 1
        if k:
            name = f"{name} ({k + 1})"          # the same label and shape again on one screen: the second one
        d: dict[str, Any] = {"name": name, "value": int(m.group("n"))}
        if m.group("of"):
            d["of"] = int(m.group("of"))
            d["share"] = round(d["value"] / d["of"], 3) if d["of"] else None
        out.append(d)
    return out


def _encodings(ram: np.ndarray) -> dict[str, np.ndarray]:
    r = ram.astype(np.int64)
    nxt = np.concatenate([r[1:], [0]])
    bcd_ok = ((r & 0x0F) < 10) & ((r >> 4) < 10) & ((nxt & 0x0F) < 10) & ((nxt >> 4) < 10)
    bcd = np.where(bcd_ok, ((r >> 4) * 10 + (r & 0x0F)) * 100 + (nxt >> 4) * 10 + (nxt & 0x0F), -1)
    return {"u8": r, "u16be": r * 256 + nxt, "u16le": r + 256 * nxt, "bcd2": bcd}


def decode(ram: np.ndarray, kind: str, i: int) -> int:
    return int(_encodings(ram)[kind][i])


class NumberBook:
    def __init__(self, min_values: int = MIN_VALUES):
        self.min_values = min_values
        self.seen: dict[str, dict[str, Any]] = {}       # name → last reading, plus `of`
        self.cands: dict[str, dict[str, np.ndarray]] = {}   # name → encoding → still-possible addresses
        self.distinct: dict[str, set[int]] = {}
        self.bound: dict[str, list[tuple[str, int]]] = {}   # name → [(encoding, address)]

    def observe(self, text: str, ram: np.ndarray | None = None) -> list[dict[str, Any]]:
        got = parse(text)
        for d in got:
            n = d["name"]
            self.seen[n] = d
            if ram is None:
                continue
            enc = _encodings(ram)
            c = self.cands.get(n)
            if c is None:
                c = self.cands[n] = {k: np.flatnonzero(v == d["value"]) for k, v in enc.items()}
            else:
                for k in c:
                    c[k] = c[k][enc[k][c[k]] == d["value"]]
            self.distinct.setdefault(n, set()).add(d["value"])
            if len(self.distinct[n]) >= self.min_values:
                found = [(k, LO + int(i)) for k, idx in c.items() for i in idx[:8]]
                if found:
                    self.bound[n] = found
                else:
                    self.bound.pop(n, None)
        return got

    def values(self, ram: np.ndarray | None = None) -> dict[str, dict[str, Any]]:
        """Every number known: from RAM where it is bound (the first address that still holds), else the last reading."""
        out: dict[str, dict[str, Any]] = {}
        for n, d in self.seen.items():
            v = {k: d[k] for k in ("value", "of", "share") if k in d}
            v["from"] = "screen"
            if ram is not None and self.bound.get(n):
                # every place that matched it so far votes: a scratch copy that has moved on is outvoted by the
                # game's own variable and its other copies
                reads = [decode(ram, k, a - LO) for k, a in self.bound[n]]
                v["value"] = max(set(reads), key=reads.count)
                if v.get("of"):
                    v["share"] = round(v["value"] / v["of"], 3)
                v["from"] = "ram"
            out[n] = v
        return out

    def summary(self) -> dict[str, Any]:
        return {n: {"values_seen": sorted(self.distinct.get(n, ())), "bound": [(k, hex(a)) for k, a in self.bound.get(n, [])]}
                for n in self.seen}


def check(cond: Any, names: set[str] | None = None) -> str | None:
    """None when {number: {name, at_least|at_most|share_at_least|share_at_most}} is well formed, else what is wrong."""
    if not isinstance(cond, dict) or set(cond) != {"number"} or not isinstance(cond["number"], dict):
        return "a number condition is {number: {name, at_least|at_most|share_at_least|share_at_most}}"
    c = cond["number"]
    if names is not None and c.get("name") not in names:
        return f"unknown number {c.get('name')!r}"
    ops = [k for k in ("at_least", "at_most", "share_at_least", "share_at_most") if k in c]
    if len(ops) != 1 or not isinstance(c[ops[0]], (int, float)):
        return "give exactly one of at_least, at_most, share_at_least, share_at_most, as a number"
    return None


def holds(cond: dict[str, Any], values: dict[str, dict[str, Any]]) -> bool:
    c = cond["number"]
    v = values.get(c["name"])
    if v is None:
        return False
    if "at_least" in c:
        return v["value"] >= c["at_least"]
    if "at_most" in c:
        return v["value"] <= c["at_most"]
    s = v.get("share")
    if s is None:
        return False
    return s >= c["share_at_least"] if "share_at_least" in c else s <= c["share_at_most"]
