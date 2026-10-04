"""Which way is on: a direction to explore first when no goal names one. Nothing here knows a game.

On Route 1 the run had no goal direction for most of its time (the goal writer's calls were spent, gap 7), and every
direction had unexplored tiles a few steps away. It explored south 24 times, east 19, west 15 and north 11 times,
and reached 13 of the route's 36 rows in 870 ticks.

The rule, from the place book (places.py):

  - A place entered by a join (walked off one map onto the next) is crossed the same way: entered going north,
    keep north until this place's own northern join is found. Routes in most games run from one join to the next.
  - Once that join is known, or for a place entered by a door, it is the direction that leads furthest from where
    the player came in, by the tiles seen so far. Doors sit at an edge of a building or area, and the rest of it lies
    away from them.
  - Never back the way the place was entered while the onward direction is open: going back is what a goal asks for,
    not what exploring does.

    head = Heading(book)
    d = head.toward(place_id)          # "up" / "down" / "left" / "right" / None
"""
from __future__ import annotations
from typing import Any

from .places import DIRS, OPPOSITE, PlaceBook


class Heading:
    def __init__(self, book: PlaceBook):
        self.book = book
        self.entered: dict[int, dict[str, Any]] = {}     # place → how it was first entered
        self._seen = 0

    def _update(self) -> None:
        for e in self.book.events[self._seen:]:
            if e.get("kind") in ("join", "door") and e.get("to") is not None and e["to"] not in self.entered:
                at = e.get("at")
                self.entered[e["to"]] = {"kind": e["kind"], "direction": e.get("direction"),
                                         "at": tuple(at) if at else None}
        self._seen = len(self.book.events)

    def toward(self, pid: int | None) -> str | None:
        self._update()
        if pid is None or pid >= len(self.book.places):
            return None
        pid = self.book.canonical(pid)
        how = self.entered.get(pid)
        if how is None:
            return None
        onward = self.book.neighbours(pid)
        d = how.get("direction")
        if how["kind"] == "join" and d and d not in onward:
            return d
        at = how.get("at")
        tiles = self.book.places[pid].tiles
        if at is None or len(tiles) < 2:
            return None
        back = OPPOSITE.get(d) if d else None
        best, far = None, 0
        for dd, (dx, dy) in DIRS.items():
            if dd == back or dd in onward:
                continue
            reach = max(((x - at[0]) * dx + (y - at[1]) * dy) for x, y in tiles)
            if reach > far:
                best, far = dd, reach
        return best
