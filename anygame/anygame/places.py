"""Which place the player is in, from the discovered map signature and position. Nothing here knows a game.

The world memory keys every tile by place. A place used to be "the map signature, unless the signature changed on a
one-tile step, and then forever the place it changed from". Replayed against the grader's map on the Pokemon runs, that
names 5 maps (two house floors, the town, the lab, Route 1) as 2 places, and a quarter of the ticks sit in a place that
is mostly another map (docs/places.md). Two things a game does break it:

  - Maps that join without a door. Walking off the top of a town onto a route changes no byte the signature is made of,
    and the position jumps from the top row to the bottom row of the next map. Read as one place, the route's tiles
    land on top of the town's.
  - A signature that changes on an ordinary step: a byte that also changes with scenery, or the map byte written a few
    steps after the join. Keeping that as a permanent alias of wherever it first appeared merges the two maps for good.

The rules here:

  - A step that lands on the far side, moving the wrong way by more than `far` tiles and by more than the presses
    explain (pressed up, row went from 0 to 35), is a join: the place on that side of this one. Joins are remembered
    both ways, so walking back down lands in the town again. A jump wider than any map is a misread, not a join.
  - A new name with a jump the walk cannot explain is a door: to the place last left with that name, if it has been
    seen near here, else a new place.
  - A new name on an ordinary step (stairs that land on the next tile look exactly like this) is a door on trial. If
    the old name comes back on the same tile later, it was a door and stays one. If it comes back anywhere else, it was
    one place under two names, and the two are merged (a "merge" event; canonical() maps old ids).
  - A game can write the new name on the read after the step (delayed writes); a new name on the read right after a
    walk, standing, counts as that walk's.
  - A new name while standing, with no walk before it, is the same place.

    book = PlaceBook()
    place = book.see(signature, x, y, moves=["up", "up"], walking=True)    # moves: directions pressed since the last read
"""
from __future__ import annotations
from typing import Any, Hashable

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


class Place:
    def __init__(self, pid: int, sig: Hashable):
        self.id = pid
        self.sigs: set[Hashable] = {sig}
        self.tiles: set[tuple[int, int]] = set()
        self.left_at = -1                       # read count when the player last left it
        self.trial: dict[str, Any] | None = None  # entered by a new name on an ordinary step: may be folded back
        self.merged_into: int | None = None

    def near(self, x: int, y: int, slack: int = 2) -> bool:
        if (x, y) in self.tiles:
            return True
        return any(abs(x - a) + abs(y - b) <= slack for a, b in self.tiles)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "sigs": sorted(map(str, self.sigs)), "tiles": len(self.tiles)}


class PlaceBook:
    def __init__(self, far: int = 4, span: int = 128):
        self.far = far                          # tiles moved the wrong way that make a step a join
        self.span = span                        # no map is wider: a longer jump is a misread position, not a join
        self.places: list[Place] = []
        self.joins: dict[tuple[int, str], int] = {}
        self.here: Place | None = None
        self._last: tuple[Hashable, int, int] | None = None
        self.reads = 0
        self._walked = -10
        self._jumped: tuple[int, int, int] | None = None
        self.events: list[dict[str, Any]] = []  # joins, doors and renames, for the log

    # ---- places -----------------------------------------------------------------------------------------
    def _new(self, sig: Hashable) -> Place:
        p = Place(len(self.places), sig)
        self.places.append(p)
        return p

    def _move(self, to: Place, kind: str, **why) -> None:
        if self.here is not None and to is not self.here:
            self.here.left_at = self.reads
        self.events.append({"read": self.reads, "kind": kind, "from": None if self.here is None else self.here.id,
                            "to": to.id, **why})
        self.here = to

    # ---- one read ---------------------------------------------------------------------------------------
    def see(self, sig: Hashable, x: int, y: int, moves: list[str] | tuple[str, ...] = (), walking: bool = False,
            cut: bool = False, idle: bool = True) -> int:
        """The place id for this read. `moves`: the directions pressed since the last read (empty when the last action
        was not a walk); `walking`: the last action was a walk; `cut`: the screen went to a new scene on the way (a
        fade or a blank between the reads), which makes a signature change a door even on a one-tile step (stairs);
        `idle`: nothing was pressed since the last read (a wait), so a new name now belongs to the walk before it."""
        self.reads += 1
        last = self._last
        self._last = (sig, x, y)
        if self.here is None or last is None:
            self._move(self._door_to(sig, x, y), "start")
            return self._stand(x, y)
        sig0, x0, y0 = last
        dx, dy = x - x0, y - y0
        moves = [m for m in moves if m in DIRS]
        j, self._jumped = self._jumped, None
        if j is not None and j[2] == self.reads - 1 and abs(x - j[0]) + abs(y - j[1]) <= max(1, len(moves)):
            self._move(self._door_to(sig, j[0], j[1]), "door", jump="forced", forced=True)
            self.here.sigs.add(sig)
            self.here.tiles.add((j[0], j[1]))
            return self._stand(x, y)
        d = self._join_direction(dx, dy, moves)
        if d is not None:
            to = self.joins.get((self.here.id, d))
            if to is None:
                q = self._new(sig)
                self.joins[(self.here.id, d)] = q.id
                self.joins[(q.id, OPPOSITE[d])] = self.here.id
                to = q.id
            self._move(self.places[to], "join", direction=d, jump=[dx, dy])
            self.places[to].sigs.add(sig)
            return self._stand(x, y)
        stepped = walking and bool(moves) and ((dx, dy) != (0, 0) or cut)
        # a game can write the new name a little after the step that changed it (the read after a walk, standing)
        late = idle and not stepped and (dx, dy) == (0, 0) and self._walked == self.reads - 1
        if walking and moves:
            self._walked = self.reads
        trial = self.here.trial
        if trial is not None and sig != sig0 and sig in self.places[trial["from"]].sigs and \
                self._walk_explains(dx, dy, moves, walking) and not cut:
            # back to the name of the place this one was entered from, on an ordinary step
            back = self.places[trial["from"]]
            if self.reads - trial["read"] >= 3 and ((x0, y0) in trial["tiles"] or (x, y) in trial["tiles"]):
                self.here.trial = None                  # the same tile both ways: stairs or a door, kept
                self._move(back, "door", jump=[dx, dy], confirmed=True)
            else:
                self._merge(self.here, back)            # it came back somewhere else: one place, two names
            return self._stand(x, y)
        if sig != sig0 and sig not in self.here.sigs:
            if late:
                frm = self.here
                to = self._door_to(sig, x, y)
                self._move(to, "door", jump=[dx, dy], trial=True, late=True)
                if to is not frm and to.trial is None and len(to.tiles) == 0:
                    to.trial = {"from": frm.id, "read": self.reads, "tiles": {(x, y)}}
            elif not stepped and self._walk_explains(dx, dy, moves, walking):
                self.here.sigs.add(sig)                 # the name changed while standing: the same place
                self.events.append({"read": self.reads, "kind": "rename", "place": self.here.id, "sig": str(sig)})
            elif self._walk_explains(dx, dy, moves, walking) and not cut:
                # a new name on an ordinary step: stairs that land on the next tile, or a byte in the name that also
                # changes with scenery. Taken as a door on trial, folded back if the old name returns away from here
                frm = self.here
                to = self._door_to(sig, x, y)
                self._move(to, "door", jump=[dx, dy], trial=True)
                if to is not frm and to.trial is None and len(to.tiles) == 0:
                    to.trial = {"from": frm.id, "read": self.reads, "tiles": {(x0, y0), (x, y)}}
            else:
                self._move(self._door_to(sig, x, y), "door", jump=[dx, dy])
        elif sig == sig0 and not moves and abs(dx) + abs(dy) > 1 and abs(dx) + abs(dy) <= self.span \
                and not self.here.near(x, y):
            # moved with nothing pressed, same name, somewhere this place has not been: the game put the player
            # elsewhere (a respawn after losing, a scripted walk into a building), or the position was misread.
            # Taken when the next read stands there too
            self._jumped = (x, y, self.reads)
            return self.here.id
        elif sig != sig0 and not self._walk_explains(dx, dy, moves, walking):
            # back to a name this place already has, by a jump: a door to another place with that name, or a warp
            # inside this one when the place has been seen there
            if not self.here.near(x, y):
                self._move(self._door_to(sig, x, y), "door", jump=[dx, dy])
        return self._stand(x, y)

    def _merge(self, gone: Place, into: Place) -> None:
        """`gone` was `into` under another name: one place from now on. The world memory moves its tiles with the
        'merge' event (canonical() maps old ids)."""
        into.sigs |= gone.sigs
        into.tiles |= gone.tiles
        gone.merged_into = into.id
        gone.trial = None
        for k, q in list(self.joins.items()):
            if q == gone.id:
                self.joins[k] = into.id
            if k[0] == gone.id:
                self.joins.setdefault((into.id, k[1]), self.joins[k])
                del self.joins[k]
        self.events.append({"read": self.reads, "kind": "merge", "from": gone.id, "to": into.id})
        self.here = into

    def canonical(self, pid: int) -> int:
        while self.places[pid].merged_into is not None:
            pid = self.places[pid].merged_into
        return pid

    def _stand(self, x: int, y: int) -> int:
        self.here.tiles.add((x, y))
        return self.here.id

    def _join_direction(self, dx: int, dy: int, moves: list[str]) -> str | None:
        """The pressed direction a walk went the wrong way along, further than `far` and further than the presses on
        that axis can explain: it crossed onto the next map, which starts at the far side."""
        for d in reversed(moves):
            ux, uy = DIRS[d]
            along = dx * ux + dy * uy
            presses = sum(1 for m in moves if DIRS[m][0] * ux + DIRS[m][1] * uy != 0)
            if along < 0 and self.far <= -along <= self.span and -along > presses:
                return d
        return None

    @staticmethod
    def _walk_explains(dx: int, dy: int, moves: list[str], walking: bool) -> bool:
        """The position change fits the steps pressed: no further than the steps taken, in their directions."""
        if not moves:
            return (dx, dy) == (0, 0) and not walking
        if (dx, dy) == (0, 0):
            return False                                # pressed to walk, did not move, name changed: stairs
        sx = sum(DIRS[m][0] for m in moves)
        sy = sum(DIRS[m][1] for m in moves)
        if abs(dx) + abs(dy) > len(moves):
            return False
        return (dx == 0 or dx * sx > 0 or any(DIRS[m][0] * dx > 0 for m in moves)) and \
               (dy == 0 or dy * sy > 0 or any(DIRS[m][1] * dy > 0 for m in moves))

    def _door_to(self, sig: Hashable, x: int, y: int) -> Place:
        """Through a door into a place named `sig`: the one last left with that name that has been seen near here,
        else the one last left with that name if it has no tiles near anywhere else, else a new place."""
        named = [p for p in self.places if sig in p.sigs and p is not self.here and p.merged_into is None]
        near = [p for p in named if p.near(x, y)]
        if near:
            return max(near, key=lambda p: p.left_at)
        return self._new(sig)

    # ---- for the world memory and the log ---------------------------------------------------------------
    def neighbours(self, pid: int) -> dict[str, int]:
        return {d: q for (p, d), q in self.joins.items() if p == pid}

    def report(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for e in self.events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return {"places": sum(1 for p in self.places if p.merged_into is None), "joins": len(self.joins) // 2, "events": kinds}

    def to_dict(self) -> dict[str, Any]:
        return {"places": [{"sigs": list(p.sigs), "tiles": sorted(p.tiles), "left_at": p.left_at,
                            "merged_into": p.merged_into,
                            "trial": None if p.trial is None else {**p.trial, "tiles": sorted(p.trial["tiles"])}}
                           for p in self.places],
                "joins": [[p, d, q] for (p, d), q in self.joins.items()],
                "here": None if self.here is None else self.here.id, "last": self._last, "reads": self.reads}

    @classmethod
    def from_dict(cls, d: dict[str, Any], far: int = 4) -> "PlaceBook":
        b = cls(far)
        for i, p in enumerate(d.get("places") or []):
            q = Place(i, None)
            q.sigs = {_hashable(s) for s in p["sigs"]}
            q.tiles = {tuple(t) for t in p["tiles"]}
            q.left_at = p.get("left_at", -1)
            q.merged_into = p.get("merged_into")
            t = p.get("trial")
            q.trial = None if t is None else {**t, "tiles": {tuple(x) for x in t["tiles"]}}
            b.places.append(q)
        b.joins = {(p, dd): q for p, dd, q in d.get("joins") or []}
        b.here = None if d.get("here") is None else b.places[d["here"]]
        b._last = tuple(_hashable(v) for v in d["last"]) if d.get("last") else None
        b.reads = d.get("reads", 0)
        return b


def _hashable(v: Any) -> Hashable:
    return tuple(_hashable(x) for x in v) if isinstance(v, list) else v


def _grey(frame) -> "np.ndarray":
    import numpy as np
    a = np.asarray(frame)
    if a.ndim == 3:
        a = a[..., :3].astype(np.int16).sum(axis=2) // 3
    return a.astype(np.int16)


def cut_between(before, after, shifts: tuple[int, ...] = (0, 4, 8, 12, 16), match: float = 0.6) -> bool:
    """Whether the screen went to a new scene between two frames, rather than scrolling: no shift of the earlier
    frame (up to a tile of 16 pixels each way) makes most of it line up with the later one. A walking step scrolls,
    so it lines up; a door, stairs or a battle does not."""
    import numpy as np
    a, b = _grey(before), _grey(after)
    if a.shape != b.shape:
        return True
    h, w = a.shape[:2]
    best = 0.0
    for dy in sorted({s * k for s in shifts for k in (-1, 1)}):
        for dx in sorted({s * k for s in shifts for k in (-1, 1)}):
            if dx and dy:
                continue                        # a step scrolls along one axis
            ya, yb = max(0, dy), max(0, -dy)
            xa, xb = max(0, dx), max(0, -dx)
            pa = a[ya:h - yb, xa:w - xb]
            pb = b[yb:h - ya, xb:w - xa]
            if pa.size == 0:
                continue
            best = max(best, float(np.mean(np.abs(pa - pb) < 24)))
            if best >= match:
                return False
    return True
