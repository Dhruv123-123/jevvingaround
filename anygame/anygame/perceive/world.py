"""World memory and a navigator: what lets a per-tick decider play a game whose world is bigger than the screen.

A derived read, `kind: world`. It takes position reads (a map id and x, y) and keeps, for the whole run:

  visited   every tile stood on, per map
  blocked   edges (tile, direction) a step did not cross: a wall, or an NPC (seen once: forgotten after a while;
            seen three times: permanent)
  warps     edges that put the player somewhere else: a door to another map, a staircase, a spinner tile
  inspected the things already faced and pressed A at, so an "inspect" option is not offered forever

Every tick it offers the decider a few options, each a path it can walk in one go, best first:

  goal        walk toward the current goal's target (a tile on this map, or the known door chain to its map)
  door_<k>    walk through a known door to a map not yet explored
  inspect_<d> face the blocked tile next to the player and press A (a sign, a person, an item, a switch)
  explore_<d> walk to the nearest unexplored tile in that direction and on until something blocks

The option labels and what they mean (with step counts) go to the decider as a choice; `macro` actions play the
chosen one through run(), one step at a time, learning walls and doors as they happen and stopping early when a step
does not go as planned or the game leaves the overworld (a dialogue, a battle). Unknown tiles count as open, so a
plan is optimistic and a bump re-plans on the next tick. Nothing here knows which game it is: Pokemon, Aevilia and
any other tile-based game differ only in the pack's reads, `cell` and `step_hold`.

    world: { kind: world, map: map, x: x, y: y, cell: 1, step_hold: 16, after: 4, max_steps: 8, radius: 24,
             learn_when: { read: overworld, equals: true }, keys: { up: up, down: down, left: left, right: right },
             interact: a }
"""
from __future__ import annotations
import json
from collections import deque
from typing import Any, Callable

from ..heading import Heading
from ..places import PlaceBook

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPP = {"up": "down", "down": "up", "left": "right", "right": "left"}
COMPASS = {"up": "north", "down": "south", "left": "west", "right": "east"}


def _get(values: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    cur: Any = values
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _cond(c: Any, values: dict[str, Any]) -> bool:
    if not c:
        return True
    if isinstance(c, list):
        return all(_cond(x, values) for x in c)
    v = _get(values, c["read"])
    if "equals" in c:
        return v == c["equals"]
    if "in" in c:
        return v in c["in"]
    if "not" in c:
        return v != c["not"]
    try:
        if "gte" in c:
            return float(v) >= float(c["gte"])
        if "lte" in c:
            return float(v) <= float(c["lte"])
    except (TypeError, ValueError):
        return False
    return False


Tile = tuple[Any, int, int]          # (map, x, y)


class WorldTracker:
    def __init__(self, r: dict[str, Any]):
        self.r = r
        self.cell = float(r.get("cell", 1)) if isinstance(r.get("cell", 1), (int, float)) else 1.0   # or a read: the discovered step
        self.max_steps = int(r.get("max_steps", 8))
        self.radius = int(r.get("radius", 24))
        self.keys = {d: (r.get("keys") or {}).get(d, d) for d in DIRS}
        self.visited: dict[Any, set[tuple[int, int]]] = {}
        self.blocked: dict[tuple, list[int]] = {}       # (map, x, y, dir) → [times seen, step when last seen]
        self.warps: dict[tuple, Tile] = {}              # (map, x, y, dir) → where it put us
        self.inspected: set[tuple] = set()
        self.walls_at: dict[Any, set[tuple[int, int]]] = {}   # tiles a step into was refused: not a place to explore
        self.moves: dict[str, dict] = {}         # label → {keys, hold, line}: inputs that do more than a step (motion.py)
        self.motion_at: set = set()               # places where what each button does was learned
        self.wants: tuple | None = None           # (goal id, words) when the goal waits for the game to tell of them
        self.chain_fn = None                      # (device, words) → what a menu-chain search did (set by the loop)
        self.chained: set = set()                 # goal ids a chain search was tried for
        self.stuck: dict[tuple, int] = {}       # (tile, plan) → times walking that plan from that tile ended back on it
        self._pending: tuple | None = None
        self.steps = 0                                  # steps tried over the run: the clock blocked edges age by
        self.here: Tile | None = None
        self.macros: dict[str, list[str]] = {}
        self.plans: dict[str, list[str]] = {}           # label → directions
        self.last_option: str | None = None
        self.goal_target: dict[str, Any] | None = None
        self.stale = 0                                  # reads since a new tile was stood on or a new thing inspected
        self.known = 0
        self.buttons_tried: set[str] = set()            # buttons tried during this stale stretch
        # which place the player is in, from the map signature and how the position moved (anygame/places.py): a
        # tile is keyed by place id, not by signature
        self.book = PlaceBook(far=int(r.get("join_far", 4)))
        self.heading = Heading(self.book)                # which way is on when no goal names one (heading.py)
        self._merged = 0                                # merge events of the book already applied
        self._moves: list[str] = []                     # directions pressed since the last position read
        self._walking = False
        self._idle = True
        self.places: set[Any] = set()

    # ---- memory ---------------------------------------------------------------------------------------
    def tile_of(self, values: dict[str, Any], stepping: bool = False, moves: tuple[str, ...] = ()) -> Tile | None:
        """The tile (place id, x, y) for a read. `moves`: directions pressed since the last read, besides those the
        tracker's own walks noted."""
        if moves:
            self._moves += [m for m in moves if m in DIRS]
            self._walking, self._idle = True, False
        if isinstance(self.r.get("cell"), str):
            c = _get(values, self.r["cell"])
            if isinstance(c, (int, float)) and c > 0:
                self.cell = float(c)
        m, x, y = (_get(values, self.r.get(k, k)) for k in ("map", "x", "y"))
        if x is None or y is None:
            return None
        try:
            t = (m if m is not None else 0, int(round(float(x) / self.cell)), int(round(float(y) / self.cell)))
        except (TypeError, ValueError):
            return None
        return self._place(t, stepping)

    def _place(self, t: Tile, stepping: bool = False) -> Tile:
        """The place for a read (signature, x, y): the place book's id, given what was pressed since the last read."""
        sig = tuple(t[0]) if isinstance(t[0], list) else t[0]
        pid = self.book.see(sig, t[1], t[2], moves=self._moves, walking=self._walking or stepping, idle=self._idle)
        self._moves, self._walking, self._idle = [], False, True
        ev = [e for e in self.book.events if e["kind"] == "merge"]
        for e in ev[self._merged:]:
            self._rekey(e["from"], e["to"])
        self._merged = len(ev)
        pid = self.book.canonical(pid)
        self.places.add(pid)
        return (pid, t[1], t[2])

    def _rekey(self, old: Any, new: Any) -> None:
        """Two places were one under two names: everything learned under the old id moves to the new one."""
        if old in self.visited:
            self.visited.setdefault(new, set()).update(self.visited.pop(old))
        if old in self.walls_at:
            self.walls_at.setdefault(new, set()).update(self.walls_at.pop(old))
        sw = lambda k: (new, *k[1:]) if k[0] == old else k
        self.blocked = {sw(k): v for k, v in self.blocked.items()}
        self.warps = {sw(k): sw(w) for k, w in self.warps.items()}
        self.inspected = {sw(k) for k in self.inspected}
        self.stuck = {(sw(k[0]), k[1]): v for k, v in self.stuck.items()}
        self.places.discard(old)
        self.places.add(new)
        if self.here is not None and self.here[0] == old:
            self.here = sw(self.here)

    def visit(self, t: Tile) -> None:
        self.visited.setdefault(t[0], set()).add((t[1], t[2]))

    def is_blocked(self, t: Tile, d: str) -> bool:
        b = self.blocked.get((t[0], t[1], t[2], d))
        if not b:
            return False
        seen, when = b
        if seen >= 3:
            return True
        # seen once or twice: maybe a person standing there; try again after a while
        return self.steps - when < int(self.r.get("forget_after", 150))

    def learn(self, before: Tile, d: str, after: Tile | None) -> str:
        """One step's outcome: 'moved', 'blocked', 'warp' or 'off' (pushed somewhere unexpected)."""
        self.steps += 1
        if after is None:
            return "off"
        dx, dy = DIRS[d]
        k = (before[0], before[1], before[2], d)
        w = self.warps.get(k)
        if w is not None and after != w:
            # a jump known from here did not happen this time: it was a misread position or a one-off push, not a
            # door or a spinner. Forgotten, so no plan routes through it again (a real one is learned again below)
            self.warps.pop(k)
        if after == before:
            seen = self.blocked.get(k, [0, 0])[0] + 1
            self.blocked[k] = [seen, self.steps]
            self.walls_at.setdefault(before[0], set()).add((before[1] + dx, before[2] + dy))
            return "blocked"
        self.visit(after)
        if after[0] != before[0] or abs(after[1] - before[1]) + abs(after[2] - before[2]) > 1:
            self.warps[(before[0], before[1], before[2], d)] = after
            return "warp"
        if (after[1] - before[1], after[2] - before[2]) == (dx, dy):
            self.blocked.pop((before[0], before[1], before[2], d), None)
            return "moved"
        return "off"

    # ---- planning -------------------------------------------------------------------------------------
    def _neighbours(self, t: Tile):
        for d, (dx, dy) in DIRS.items():
            if self.is_blocked(t, d):
                continue
            w = self.warps.get((t[0], t[1], t[2], d))
            if w is not None:
                if w[0] == t[0]:
                    yield d, w            # a spinner or a hole within the map: a known jump
                continue                  # a door to another map: not part of this map's paths
            yield d, (t[0], t[1] + dx, t[2] + dy)

    def bfs(self, start: Tile) -> dict[Tile, tuple[Tile | None, str | None, int]]:
        """Paths over this map from start; unknown tiles are open. tile → (previous tile, direction in, distance)."""
        seen: dict[Tile, tuple[Tile | None, str | None, int]] = {start: (None, None, 0)}
        q = deque([start])
        while q:
            t = q.popleft()
            dist = seen[t][2]
            if dist >= self.radius:
                continue
            for d, n in self._neighbours(t):
                if n in seen:
                    continue
                if abs(n[1] - start[1]) > self.radius or abs(n[2] - start[2]) > self.radius:
                    continue
                seen[n] = (t, d, dist + 1)
                # an unvisited tile ends a path: it may be a wall, so plans never route through two unknowns
                if (n[1], n[2]) in self.visited.get(n[0], set()):
                    q.append(n)
        return seen

    @staticmethod
    def path_to(tree, goal: Tile) -> list[str]:
        out = []
        t = goal
        while tree.get(t) and tree[t][0] is not None:
            out.append(tree[t][1])
            t = tree[t][0]
        return out[::-1]

    def _door_chain(self, start_map: Any, target_map: Any) -> list[tuple]:
        """Known doors leading from start_map to target_map, as a list of warp keys (BFS over the map graph)."""
        by_map: dict[Any, list[tuple]] = {}
        for k, w in self.warps.items():
            if w[0] != k[0]:
                by_map.setdefault(k[0], []).append(k)
        prev: dict[Any, tuple | None] = {start_map: None}
        q = deque([start_map])
        while q:
            m = q.popleft()
            if m == target_map:
                break
            for k in by_map.get(m, []):
                n = self.warps[k][0]
                if n not in prev:
                    prev[n] = k
                    q.append(n)
        if target_map not in prev:
            return []
        chain, m = [], target_map
        while prev[m] is not None:
            chain.append(prev[m])
            m = prev[m][0]
        return chain[::-1]

    def options(self, here: Tile, goal: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, list[str]]]:
        tree = self.bfs(here)
        opts: dict[str, str] = {}
        plans: dict[str, list[str]] = {}
        vis = self.visited.get(here[0], set())
        # 1. the goal
        if goal:
            gm = goal.get("map", here[0])
            tgt = None
            why = goal.get("label") or "the goal"
            if gm == here[0] and "x" not in goal and goal.get("toward"):
                goal = {**goal, "_toward": goal["toward"]}      # only a direction: explore that way first
            if gm == here[0] and "x" in goal and "y" in goal:
                tgt = (here[0], int(goal["x"]), int(goal["y"]))
                if tgt == here:
                    tgt = None
                elif tgt not in tree:
                    # not reachable over what is known: head for the reachable tile closest to it
                    tgt = min(tree, key=lambda t: abs(t[1] - goal["x"]) + abs(t[2] - goal["y"]) + 0.01 * tree[t][2])
                    if tgt == here:
                        tgt = None
            elif gm != here[0]:
                chain = self._door_chain(here[0], gm)
                if chain:
                    k = chain[0]
                    door = (k[0], k[1], k[2])
                    if door in tree:
                        p = self.path_to(tree, door) + [k[3]]
                        plans["goal"] = p
                        opts["goal"] = f"walk {len(p)} steps through the known door toward {why} ({len(chain)} door(s) away)"
                elif goal.get("toward"):
                    # a direction hint for a map not reached yet: explore that way
                    goal = {**goal, "_toward": goal["toward"]}
            if tgt is not None:
                p = self.path_to(tree, tgt)[: self.max_steps * 2]
                if p:
                    plans["goal"] = p
                    left = abs(tgt[1] - here[1]) + abs(tgt[2] - here[2])
                    opts["goal"] = f"walk {len(p)} steps toward {why} ({left} tiles away as the crow flies)"
        # 2. doors to maps not explored
        k_door = 0
        for k, w in sorted(self.warps.items(), key=lambda kv: str(kv[0])):
            if k[0] != here[0] or w[0] == here[0] or w[0] in self.visited and len(self.visited[w[0]]) > 6:
                continue
            door = (k[0], k[1], k[2])
            if door in tree and k_door < 2:
                p = self.path_to(tree, door) + [k[3]]
                lab = f"door_{k_door + 1}"
                plans[lab] = p
                opts[lab] = f"walk {len(p)} steps back through the door at ({k[1]},{k[2]}) to the little-explored map {w[0]}"
                k_door += 1
        # 3. explore, one option per direction
        toward = (goal or {}).get("_toward")
        own = toward is None
        if own:
            toward = self.heading.toward(here[0])
        explore = []
        # tiles a step into is refused now: a refusal seen once or twice expires with its block (a person who moved,
        # or a step misread while the place was misnamed), so a tile once refused is explored again later
        walls = {(k[1] + DIRS[k[3]][0], k[2] + DIRS[k[3]][1]) for k in self.blocked
                 if k[0] == here[0] and self.is_blocked((k[0], k[1], k[2]), k[3])}
        for d, (dx, dy) in DIRS.items():
            best = None
            for t, (_, _, dist) in tree.items():
                if t == here or (t[1], t[2]) in vis or (t[1], t[2]) in walls:
                    continue
                ox, oy = t[1] - here[1], t[2] - here[2]
                along = ox * dx + oy * dy
                if along <= 0 or along < abs(ox * dy + oy * dx):
                    continue          # not mostly in this direction
                if best is None or dist < best[1]:
                    best = (t, dist)
            if best is None:
                continue
            p = self.path_to(tree, best[0])
            # and on in the same direction over unknown ground, up to max_steps in all
            p = (p + [d] * self.max_steps)[: max(len(p), self.max_steps)]
            plans[f"explore_{d}"] = p
            explore.append((0 if d == toward else 1, best[1], d, len(p)))
        for _, dist, d, n in sorted(explore):
            hint = ((" (the way on)" if own else " (the goal's direction)") if d == toward else "")
            opts[f"explore_{d}"] = f"explore {COMPASS[d]}{hint}: nearest unexplored tile {dist} step(s) away, up to {n} steps"
        # 4. inspect blocked tiles not inspected yet, nearest first: people, signs and objects block the way as walls do,
        # and the only general way to find the one a quest wants is to try them
        cands = []
        for k in self.blocked:
            if k[0] != here[0] or k in self.inspected or not self.is_blocked((k[0], k[1], k[2]), k[3]):
                continue
            t = (k[0], k[1], k[2])
            if t in tree:
                # a blocked tile with open floor around it stands in the room (a person, a sign, an object); one in a
                # line of other blocked tiles is a wall. Isolated ones first.
                dx, dy = DIRS[k[3]]
                bx, by = k[1] + dx, k[2] + dy
                open_sides = sum(1 for ex, ey in DIRS.values() if (bx + ex, by + ey) in vis)
                cands.append((-open_sides, tree[t][2], k, open_sides))
        cands.sort(key=lambda c: (c[0], c[1], str(c[2])))
        for i, (_, dist, k, open_sides) in enumerate(cands[: int(self.r.get("inspect_options", 2))]):
            lab = f"inspect_{i + 1}"
            plans[lab] = self.path_to(tree, (k[0], k[1], k[2])) + [f"face:{k[3]}", "interact"]
            where = "next to you" if dist == 0 else f"{dist} step(s) away"
            what = "open floor on %d sides: likely a person or an object" % open_sides if open_sides >= 2 else "probably a wall"
            opts[lab] = f"walk to the blocked tile {COMPASS[k[3]]} of ({k[1]},{k[2]}), {where}, and press A at it ({what}; never inspected; {len(cands)} left on this map)"
        if not opts:
            # nothing new reachable: blocks seen once may have been people who moved; wander and look again
            d = list(DIRS)[(self.steps // 3) % 4]
            plans["wander"] = [d] * 3
            opts["wander"] = f"nothing unexplored or uninspected is reachable: wander {COMPASS[d]} 3 steps"
        return opts, plans

    # ---- the read -------------------------------------------------------------------------------------
    def read(self, values: dict[str, Any], goal: dict[str, Any] | None = None) -> dict[str, Any] | None:
        here = self.tile_of(values)
        if here is None:
            # the position is not known yet (still being discovered): walk blind, which is also what discovers it
            k = (self.steps // 3) % 4
            order = (list(DIRS)[k:] + list(DIRS)[:k])
            self.plans = {f"explore_{d}": [d] * 3 for d in order}
            self.macros = {k: list(v) for k, v in self.plans.items()}
            return {"here": None, "explored": None, "blocked_around": [],
                    "landings": {f"explore_{d}": f"walk {COMPASS[d]} 3 steps (where you are is not known yet)" for d in order}}
        self.here = here
        self.visit(here)
        self.goal_target = goal
        known = sum(len(v) for v in self.visited.values()) + len(self.inspected) + len(self.warps)
        self.stale = 0 if known > self.known else self.stale + 1
        if known > self.known:
            self.buttons_tried = set()
        self.known = known
        if self._pending is not None and self._pending[0] == here:
            # the last plan from this very tile ended where it started (pushed back by a script, a talk, a ledge)
            self.stuck[self._pending] = self.stuck.get(self._pending, 0) + 1
        self._pending = None
        opts, plans = self.options(here, goal)
        dead = [k for k, p in plans.items() if self.stuck.get((here, tuple(p)), 0) >= 2]
        if dead and len(dead) < len(plans):
            for k in dead:      # walked twice from here and came back here: not offered again from this tile
                plans.pop(k)
                opts.pop(k, None)
        if self.wants and self.chain_fn is not None and self.wants[0] not in self.chained and \
                self.stale >= int(self.r.get("chain_after", 12)):
            plans["search_menus"] = ["chain"]
            opts["search_menus"] = (f"nothing new for {self.stale} decisions: try chains of menu picks until the game "
                                    f"tells of {', '.join(self.wants[1][:3])}")
        for k, mv in self.moves.items():
            # a jump, a dash, a run: offered next to the walks, as what learning the buttons found it does
            plans[k] = [f"hold:{'+'.join(mv['keys'])}:{mv['hold']}"]
            opts[k] = mv["line"]
        if self.stale >= int(self.r.get("stale_after", 12)):
            # nothing new for a while: a button not tried in this stretch (a menu, a map, a mode) may be what the game
            # is waiting for. Offered first, each button once until something new turns up
            for b in [str(x) for x in (self.r.get("buttons") or ["start", "select", "b"])]:
                if b not in self.buttons_tried:
                    plans = {f"try_{b}": [f"button:{b}"], **plans}
                    opts = {f"try_{b}": f"nothing new for {self.stale} decisions: press {b.upper()} (not tried since)", **opts}
                    break
        self.plans = plans
        self.macros = {k: [str(s) for s in v] for k, v in plans.items()}
        maps = len(self.visited)
        walls = sum(1 for k in self.blocked if k[0] == here[0])
        return {"here": {"map": here[0], "x": here[1], "y": here[2]},
                "explored": {"tiles_here": len(self.visited.get(here[0], ())), "maps": maps, "doors_known": len(self.warps), "walls_here": walls},
                "blocked_around": [d for d in DIRS if self.is_blocked(here, d)],
                "landings": opts}

    def predict(self, label: str) -> None:
        self.last_option = label

    # ---- playing an option ----------------------------------------------------------------------------
    def run(self, device, label: str, look: Callable[[], dict[str, Any]], hold: int | None = None, after: int | None = None,
            classify: Callable[[], str | None] | None = None) -> str:
        """Walk the plan for `label` step by step. `look()` returns fresh read values without advancing the game.
        Learns walls and doors as it goes and stops when a step does not go as planned or the game leaves the
        situation `learn_when` names (a dialogue opened, a battle started)."""
        plan = self.plans.get(label)
        if not plan:
            return f"{label}: no plan"
        if self.here is not None:
            self._pending = (self.here, tuple(plan))
        hold = int(self.r.get("step_hold", 16)) if hold is None else hold
        after = int(self.r.get("after", 4)) if after is None else after
        interact = self.r.get("interact", "a")
        done = []
        for step in plan:
            v = look()
            here = self.tile_of(v)
            if here is None and step in DIRS:
                device.press(self.keys[step], hold=hold, after=after)      # blind: no position to learn from yet
                self._moves.append(step)
                self._walking, self._idle = True, False
                self.steps += 1
                done.append(step)
                continue
            if here is None or not _cond(self.r.get("learn_when"), v):
                done.append("stop: left the overworld")
                break
            if step.startswith("face:"):
                d = step[5:]
                self.inspected.add((here[0], here[1], here[2], d))
                device.press(self.keys[d], hold=2, after=after)   # a tap turns the player without walking
                self._idle = False
                done.append(f"face {d}")
                continue
            if step == "interact":
                device.press(interact, hold=4, after=after)
                self._idle = False
                done.append("A")
                continue
            if step == "chain":
                self.chained.add(self.wants[0] if self.wants else None)
                self._idle = False
                done.append(self.chain_fn(device, list(self.wants[1]) if self.wants else []))
                break
            if step.startswith("hold:"):
                _, ks, h = step.split(":")
                keys = ks.split("+")
                if hasattr(device, "hold_keys"):
                    device.hold_keys(keys, int(h))
                    device.release_keys(keys)
                else:
                    for k in keys:
                        device.press(k, hold=int(h), after=0)
                device.wait(int(self.r.get("settle_after_hold", 16)))
                self._moves += [k for k in keys if k in DIRS]
                self._walking, self._idle = True, False
                t2 = self.tile_of(look())
                self.steps += 1
                if t2 is not None and t2 != here:
                    self.visit(t2)
                done.append(f"{ks} held {h} → " + (f"({t2[1]},{t2[2]})" if t2 is not None else "?"))
                continue
            if step.startswith("button:"):
                b = step[7:]
                self.buttons_tried.add(b)
                device.press(b, hold=4, after=after)
                self._idle = False
                done.append(b.upper())
                continue
            device.press(self.keys[step], hold=hold, after=after)
            self._moves.append(step)
            self._walking, self._idle = True, False
            v2 = look()
            if not _cond(self.r.get("learn_when"), v2):
                # the step opened a dialogue or a battle (a trainer saw us, a sign): the step itself happened
                t2 = self.tile_of(v2)
                if t2 is not None and t2 != here:
                    self.learn(here, step, t2)
                done.append(f"{step} → stop: left the overworld")
                break
            t2 = self.tile_of(v2, stepping=True)
            if t2 == here and classify is not None:
                # it did not move: a wall, or did the step open something (a text, a choice)? Ask by trying
                kind = classify()
                if kind not in (None, "walk"):
                    done.append(f"{step} → stop: {kind} on screen")
                    break
            out = self.learn(here, step, t2)
            done.append(step if out == "moved" else f"{step} ({out})")
            if out != "moved":
                break
        self.last_option = label
        return f"{label}: " + " ".join(done)

    def learn_motion(self, device, place: Any = None) -> list[str] | None:
        """What each button does here (anygame/motion.py), once per place: inputs that move the player more than a
        step of the plain direction does (a dash, a run) or that jump become options. Returns the description."""
        if place in self.motion_at or not hasattr(device, "snapshot"):
            return None
        self.motion_at.add(place)
        from .. import motion
        try:
            m = motion.learn(device)
        except Exception:  # noqa: BLE001
            return None
        lines = motion.describe(m)
        longest = max((x["hold"] for x in m["moves"]), default=0)
        plain = {tuple(x["keys"]): x for x in m["moves"] if x["hold"] == longest and len(x["keys"]) == 1}
        for x, line in zip([x for x in m["moves"] if x["hold"] == longest], lines):
            keys = tuple(x["keys"])
            if all(k in DIRS for k in keys):
                continue
            d = next((plain[(k,)] for k in keys if k in DIRS and (k,) in plain), None)
            reach = abs(x["reach_x"]) + abs(x["reach_y"])
            base = abs(d["reach_x"]) + abs(d["reach_y"]) if d is not None else 0.0
            if x["kind"] == "jump" or (reach >= 4 and reach > 1.5 * max(base, 1.0)):
                self.moves["move_" + "_".join(keys)] = {"keys": list(keys), "hold": x["hold"], "line": f"hold {line}"}
        return lines

    # ---- persistence ----------------------------------------------------------------------------------
    def dump(self) -> dict[str, Any]:
        return {"visited": {json.dumps(m): sorted(v) for m, v in self.visited.items()},
                "blocked": [[list(k), v] for k, v in self.blocked.items()],
                "warps": [[list(k), list(w)] for k, w in self.warps.items()],
                "inspected": [list(k) for k in self.inspected], "steps": self.steps,
                "walls_at": {json.dumps(m): sorted(v) for m, v in self.walls_at.items()},
                "book": self.book.to_dict(), "merged": self._merged, "places": sorted(self.places, key=str),
                "moves": self.moves, "motion_at": sorted(self.motion_at, key=str)}

    def load(self, d: dict[str, Any]) -> None:
        self.visited = {json.loads(m): {tuple(p) for p in v} for m, v in (d.get("visited") or {}).items()}
        self.blocked = {tuple(k): list(v) for k, v in d.get("blocked") or []}
        self.warps = {tuple(k): tuple(w) for k, w in d.get("warps") or []}
        self.inspected = {tuple(k) for k in d.get("inspected") or []}
        self.steps = int(d.get("steps", 0))
        self.walls_at = {json.loads(m): {tuple(p) for p in v} for m, v in (d.get("walls_at") or {}).items()}
        if d.get("book"):
            self.book = PlaceBook.from_dict(d["book"], far=int(self.r.get("join_far", 4)))
            self.heading = Heading(self.book)
            self._merged = int(d.get("merged", 0))
        self.places = set(d.get("places") or []) | set(self.visited)
        self.moves = dict(d.get("moves") or {})
        self.motion_at = set(d.get("motion_at") or [])
