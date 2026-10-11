"""When the goal writer is worth a call, and what it needs to see. Nothing here knows a game.

Measured on the Pokemon and Aevilia runs (412 writer calls, docs/goal-budget.md): a third of the calls kept the goal
they had, and most of the rest rewrote it as itself or as the generic "enter a new place". Two things caused them:

  - a goal reached or given up with nothing new said since the last call. The writer then has nothing new to go on,
    and wrote the same goal or the generic one 32 times out of 36;
  - "new" text that was not new: the START menu, the save screen, a box typing out, read again with OCR's variations.
    Those calls kept the goal.

So the writer is asked only when the game has said something it has not said before, when a goal ends after the
writer kept it over news (the news may be for the next goal), or once after a goal is given up (it may know another
way). Otherwise a goal that ends is followed by the generic goal, for free. Calls come from a
budget that grows with game time instead of a fixed number per run, so a 16-hour game is not cut off at 60 calls and
an hour of menus cannot spend them all.

    gate = GoalGate()
    gate.see(text, screen)                   # every tick: what the game shows, and the screen kind
    ok, why = gate.ask(tick, frames, need=no_goal, ended=last_outcome)
    if ok: ...call the writer with compact(dialogue)...; gate.called(tick, frames)
"""
from __future__ import annotations
import re
from typing import Any

WORD = re.compile(r"[a-z]{2,}")
MENU_SCREENS = ("choice", "button", "menu")


def words(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


class GoalGate:
    def __init__(self, per_hour: float = 20.0, burst: int = 16, min_gap: int = 12, min_new: int = 3,
                 novelty: float = 0.5, fps: float = 60.0):
        self.per_hour = per_hour            # calls earned per hour of game time
        self.burst = burst                  # calls available at the start
        self.min_gap = min_gap              # ticks between calls
        self.min_new = min_new              # words never seen before that make a line news
        self.novelty = novelty              # and the share of the line's words they must be
        self.fps = fps
        self.seen: set[str] = set()
        self.news: list[str] = []           # lines that are news since the last call
        self.calls = 0
        self.last_tick = -10**9
        self.asked_after_give_up = False
        self.held_news = False              # news the writer saw but kept the goal over
        self.skipped: dict[str, int] = {}

    # ---- what the game shows ---------------------------------------------------------------------------
    def see(self, text: str, screen: str | None = None) -> bool:
        """Note what the screen says. Returns True when it is news: a line of text (not a menu) with words the run
        has not seen before, enough of them to be more than a misread of a line already seen."""
        ws = words(text)
        if not ws:
            return False
        new = [w for w in ws if w not in self.seen]
        self.seen.update(ws)
        if screen in MENU_SCREENS:
            return False
        if len(new) >= self.min_new and len(new) >= self.novelty * len(ws):
            self.news.append(text)
            return True
        return False

    # ---- the budget ------------------------------------------------------------------------------------
    def allowance(self, frames: int) -> float:
        return self.burst + self.per_hour * frames / (self.fps * 3600)

    def ask(self, tick: int, frames: int, *, need: bool, ended: str | None = None) -> tuple[bool, str]:
        """Whether to call the writer now. `need`: there is no current goal. `ended`: how the last goal ended
        ("reached", "given up", ...). Returns (call?, why)."""
        def no(why):
            self.skipped[why] = self.skipped.get(why, 0) + 1
            return False, why
        if tick - self.last_tick < self.min_gap:
            return no("too soon")
        if self.calls + 1 > self.allowance(frames):
            return no("over budget")
        if self.news:
            return True, "the game said something new"
        if need and self.held_news:
            self.held_news = False
            return True, "the goal ended, and the writer kept it the last time the game said something new"
        if need and ended == "given up" and not self.asked_after_give_up:
            self.asked_after_give_up = True
            return True, "a goal was given up: ask once for another way"
        return no("nothing new since the last call" if need else "no news")

    def called(self, tick: int, frames: int, result: str | None = None) -> None:
        """A call was made. `result` "kept" with news pending: what the game said may matter once this goal ends."""
        self.held_news = bool(self.news) and result == "kept"
        self.calls += 1
        self.last_tick = tick
        self.news = []
        self.asked_after_give_up = False

    def report(self) -> dict[str, Any]:
        return {"calls": self.calls, "skipped": dict(self.skipped)}


def compact(dialogue: list[dict[str, Any]], keep: int = 25) -> list[dict[str, Any]]:
    """The dialogue the writer needs: the last `keep` lines once a box typing out is folded into the line it became,
    and a line seen again (a menu reopened, a sign reread, the same line misread a little differently: half its words
    shared) kept only where it was last seen. Each kept line keeps its
    index `i` into the full log, so a target {line: i} still points at it."""
    out: list[dict[str, Any]] = []
    later: list[set[str]] = []
    items = list(enumerate(dialogue))
    for idx in range(len(items) - 1, -1, -1):
        i, d = items[idx]
        ws = words(d.get("text", ""))
        if not ws:
            continue
        key = " ".join(ws)
        nxt = " ".join(words(items[idx + 1][1].get("text", ""))) if idx + 1 < len(items) else ""
        if nxt.startswith(key) and nxt != key:
            continue                        # the same box, further typed out, comes next
        w = set(ws)
        if any(len(w & k) >= max(1, 0.5 * len(w | k)) for k in later):
            continue                        # read again, or misread a little differently: keep the last reading
        later.append(w)
        out.append({"i": i, **d})
        if len(out) >= keep:
            break
    return out[::-1]
