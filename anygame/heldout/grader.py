"""Milestones as conditions on game memory, latched once reached.

A condition is a small dict (YAML in games/<id>.yaml):

    {u8: 0xC0A4, ge: 3}                     # one byte; ops: eq ne gt ge lt le, in: [..]
    {u16: 0xC99B, ge: 100}                  # two bytes, little endian (u16be: big endian)
    {bcd: 0xC5F1, bytes: 3, ge: 300}        # binary-coded decimal, little endian unless order: be
    {bit: 0xD356, n: 0}                     # bit n set (badges, event flags)
    {all: [..]}  {any: [..]}

A milestone is {id, desc, when, after?}: `after` names a milestone that must already be reached, for a value that is
also the power-on value (a map id of 0 before the game has loaded any map). A game can instead name a Python grader,
`grader: python:<module>:<function>`, called with a memory reader and returning {milestone id: reached now}.

The grader is the only thing that reads memory. It is given the emulator; the agent is given only frames.
"""
from __future__ import annotations
import importlib
from typing import Any, Callable

OPS = {"eq": lambda v, x: v == x, "ne": lambda v, x: v != x, "gt": lambda v, x: v > x, "ge": lambda v, x: v >= x,
       "lt": lambda v, x: v < x, "le": lambda v, x: v <= x, "in": lambda v, x: v in x}
Mem = Callable[[int], int]


def _bcd(mem: Mem, addr: int, n: int, order: str) -> int:
    raw = [mem(addr + i) for i in range(n)]
    if order == "le":
        raw = raw[::-1]
    v = 0
    for b in raw:
        v = v * 100 + (b >> 4) * 10 + (b & 15)
    return v


def value(c: dict[str, Any], mem: Mem) -> int:
    if "u8" in c:
        return mem(int(c["u8"]))
    if "u16" in c:
        a = int(c["u16"])
        return mem(a) | (mem(a + 1) << 8)
    if "u16be" in c:
        a = int(c["u16be"])
        return (mem(a) << 8) | mem(a + 1)
    if "bcd" in c:
        return _bcd(mem, int(c["bcd"]), int(c.get("bytes", 1)), c.get("order", "le"))
    if "bit" in c:
        return (mem(int(c["bit"])) >> int(c["n"])) & 1
    raise ValueError(f"condition {c}: needs one of u8, u16, u16be, bcd, bit, all, any")


def holds(c: dict[str, Any], mem: Mem) -> bool:
    if "all" in c:
        return all(holds(x, mem) for x in c["all"])
    if "any" in c:
        return any(holds(x, mem) for x in c["any"])
    v = value(c, mem)
    ops = [k for k in OPS if k in c]
    if not ops:
        return bool(v)          # a bare read: nonzero (a bit, a flag byte)
    return all(OPS[k](v, c[k]) for k in ops)


def check_game(g: dict[str, Any]) -> None:
    """Refuse a game file the grader cannot use, before any run starts."""
    ms = g.get("milestones") or []
    if not 1 <= len(ms) <= 30 and not g.get("grader"):
        raise ValueError(f"{g.get('id')}: needs 1 to 30 milestones")
    seen: set[str] = set()
    for m in ms:
        if "id" not in m or "desc" not in m or ("when" not in m and not g.get("grader")):
            raise ValueError(f"{g.get('id')}: milestone {m}: needs id, desc and when")
        if m.get("after") and m["after"] not in seen:
            raise ValueError(f"{g.get('id')}: milestone {m['id']}: after '{m['after']}' must name an earlier milestone")
        seen.add(m["id"])
        if "when" in m:
            holds(m["when"], lambda a: 0)       # parses every condition once


class Grader:
    """Latches milestones as they are reached; `update` is called after every agent step."""

    def __init__(self, game: dict[str, Any]):
        check_game(game)
        self.game = game
        self.milestones = game["milestones"]
        self.reached: dict[str, dict[str, Any]] = {}        # id -> {step, frame, ...} when first reached
        self.fn = None
        if str(game.get("grader", "")).startswith("python:"):
            mod, fn = game["grader"][len("python:"):].rsplit(":", 1)
            self.fn = getattr(importlib.import_module(mod), fn)

    def update(self, mem: Mem, at: dict[str, Any]) -> list[str]:
        now = self.fn(mem) if self.fn else {}
        new = []
        for m in self.milestones:
            mid = m["id"]
            if mid in self.reached or (m.get("after") and m["after"] not in self.reached):
                continue
            ok = now.get(mid, False) if self.fn and "when" not in m else holds(m["when"], mem)
            if ok:
                self.reached[mid] = dict(at)
                new.append(mid)
        return new

    @property
    def score(self) -> float:
        return len(self.reached) / len(self.milestones)

    def next_milestone(self) -> dict[str, Any] | None:
        return next((m for m in self.milestones if m["id"] not in self.reached), None)
