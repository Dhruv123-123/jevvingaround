"""Keeping a number up: notice one falling toward a floor the game has shown to be fatal, leave the fight, and go back
to where it last refilled. Nothing here knows a game, or which number is health.

Any number shown as "value / most" (from numbers.NumberBook, on screen or bound to RAM) is tracked:

  - **Floor.** A number is assumed fatal at 0 until the game shows otherwise. The game shows it when the number gets
    near its floor and the player is then moved somewhere without walking. In Pokemon that is the blackout that
    puts Red back at home; in a roguelike it is a restart. A number that hits 0 with no move after it (a scripted
    fight that does not end the game) is marked not fatal there.
  - **Refill.** A number that comes back to near full has been refilled. The place where that happened is kept as the
    destination: where a forced move landed, else where the player was in a conversation, else where they stood.
  - **Danger.** The number is at or below `low` of its most, or within `margin` of its largest single drop from the
    floor, and it is not marked safe. Then `advice()` asks to leave: prefer a choice whose play-out returns to the
    world (`rank_exits`), and set a goal to go back to the refill place until the number is near full again.

    keep = Upkeep()
    keep.see(tick, numbers, place=pid, screen=kind, moved=forced)   # every tick
    a = keep.advice()          # None, or {"number", "why", "leave": True, "goal": {...}}
"""
from __future__ import annotations
from typing import Any

FULL = 0.9


class Track:
    def __init__(self, name: str):
        self.name = name
        self.value: int | None = None
        self.most: int | None = None
        self.biggest_drop = 0
        self.floor = 0
        self.fatal = None                       # None: assumed; True: the game showed it; False: shown not to be
        self.low_since: int | None = None       # tick it last went below full
        self.since_low: list[tuple[Any, str]] = []   # (place, what happened there) since then
        self.refill: dict[str, Any] | None = None
        self.near_floor_at: int | None = None

    def share(self) -> float | None:
        if self.value is None or not self.most:
            return None
        return self.value / self.most


class Upkeep:
    def __init__(self, low: float = 0.35, margin: float = 1.0, fatal_within: int = 40):
        self.low = low                          # share of the most that counts as low
        self.margin = margin                    # largest drops left before the floor that count as low
        self.fatal_within = fatal_within        # ticks after nearing the floor in which a forced move shows it is fatal
        self.tracks: dict[str, Track] = {}
        self.place: Any = None
        self.tick = 0
        self.events: list[dict[str, Any]] = []

    # ---- every tick -------------------------------------------------------------------------------------
    def see(self, tick: int, numbers: dict[str, dict[str, Any]] | None, place: Any = None, screen: str | None = None,
            moved: bool = False) -> None:
        """`numbers`: {name: {"value", "of"}} for whatever is known this tick (NumberBook.values); `place`: the place id;
        `screen`: the screen kind ("text" means a conversation when no number is changing); `moved`: the player was
        put somewhere without walking (a door taken by the game, a respawn), as the place book's events say."""
        self.tick = tick
        changed = place != self.place
        self.place = place
        for t in self.tracks.values():
            if t.low_since is not None and (changed or moved or screen == "text"):
                t.since_low.append((place, "moved" if moved else ("talk" if screen == "text" else "here")))
            if moved and t.near_floor_at is not None and tick - t.near_floor_at <= self.fatal_within:
                if t.fatal is not True:
                    self.events.append({"tick": tick, "kind": "fatal", "number": t.name, "floor": t.floor})
                t.fatal = True
                t.near_floor_at = None
        for name, n in (numbers or {}).items():
            v, most = n.get("value"), n.get("of")
            if not isinstance(v, int) or not isinstance(most, int) or most <= 0 or v > most:
                continue
            t = self.tracks.setdefault(name, Track(name))
            self._update(t, v, most, place)

    def _update(self, t: Track, v: int, most: int, place: Any) -> None:
        before = t.value
        if before is not None and t.most == most and v < before:
            t.biggest_drop = max(t.biggest_drop, before - v)
        if v < FULL * most and t.low_since is None:
            t.low_since = self.tick
            t.since_low = [(place, "here")]
        if v >= FULL * most and t.low_since is not None:
            t.refill = {"place": self._where(t), "tick": self.tick, "from": before, "to": v}
            self.events.append({"tick": self.tick, "kind": "refill", "number": t.name, **t.refill})
            t.low_since = None
            t.since_low = []
            t.near_floor_at = None
        if v <= t.floor + max(1, most // 10):
            t.near_floor_at = self.tick
        t.value, t.most = v, most

    @staticmethod
    def _where(t: Track) -> Any:
        """Where a refill happened: where the game moved the player, else where they talked, else where they were."""
        for kind in ("moved", "talk"):
            for p, k in reversed(t.since_low):
                if k == kind:
                    return p
        return t.since_low[-1][0] if t.since_low else None

    # ---- what to do -------------------------------------------------------------------------------------
    def danger(self, t: Track) -> str | None:
        if t.value is None or t.most is None or t.fatal is False:
            return None
        share = t.value / t.most
        left = t.value - t.floor
        if share <= self.low:
            return f"{t.name} is {t.value} of {t.most}"
        if t.biggest_drop and left <= self.margin * t.biggest_drop:
            return f"{t.name} is {t.value} of {t.most}, one bad turn from {t.floor} (it has dropped {t.biggest_drop} at once)"
        return None

    def advice(self) -> dict[str, Any] | None:
        """The number most at risk, why, and what to do about it: leave the fight and go back to where it refilled."""
        worst, why = None, None
        for t in self.tracks.values():
            w = self.danger(t)
            if w and (worst is None or (t.share() or 1) < (worst.share() or 1)):
                worst, why = t, w
        if worst is None:
            return None
        shown = {True: "the game has shown it is fatal", None: "assumed fatal"}[worst.fatal]
        goal = {"instruction": f"Get {worst.name} back up" + (" where it last refilled" if worst.refill else ""),
                "done": {"number": {"name": worst.name, "share_at_least": FULL}}, "target": None}
        if worst.refill and worst.refill.get("place") is not None:
            goal["target"] = {"place": worst.refill["place"]}
        return {"number": worst.name, "why": f"{why}; {worst.floor} is {shown}", "leave": True, "goal": goal}

    def report(self) -> dict[str, Any]:
        return {name: {"value": t.value, "of": t.most, "fatal": t.fatal, "biggest_drop": t.biggest_drop,
                       "refill": t.refill} for name, t in self.tracks.items()}


def rank_exits(outcomes: dict[str, dict[str, Any]]) -> list[str]:
    """Choices that leave an encounter, best first: those whose play-out comes back to the world (a walk screen),
    soonest. `outcomes`: {label: {"ends_on": screen kind after the play-out, "frames": how long it took}}."""
    out = [(o.get("frames") or 0, label) for label, o in outcomes.items() if o.get("ends_on") == "walk"]
    return [label for _, label in sorted(out)]
