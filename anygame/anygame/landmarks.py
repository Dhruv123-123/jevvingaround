"""Who and what was heard where: the names the game said at each place, so a line that sends the player back ("take
this to PROF.OAK", "come home", "let's talk inside") can be turned into a place the run has been. Nothing here knows
a game.

A name is a word the game writes with a capital and never in lower case (OAK, MOM, Tom, PALLET): a word that is also
written in lower case somewhere is an ordinary word at the start of a sentence. A line that starts with the name and a
mark (a speaker's tag, "OAK: ...", read as "OAK? ..." by a reader that does not know the colon) counts three times:
that name speaks there.

A name's place is where it was said most, counted once per distinct line; a name said about as often everywhere
(the game's title, the player's own name) has no place. Places are those of the world memory (dialogue entries carry
the place id they were said in); merged places count as one through `canonical`.

    marks = Landmarks()
    marks.update(memory.dialogue, canonical=book.canonical)
    marks.where("oak")          # the place OAK speaks or is spoken of most, or None
    marks.heard_at(place)       # the names whose place this is, most heard first (for the goal writer's places list)
    marks.find(text)            # places the names in a line belong to, in the order named
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable

WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
TAG = re.compile(r"^\s*([^\W\d_]{2,})\s*[:?!>]", re.UNICODE)


class Landmarks:
    def __init__(self, share: float = 0.5, min_count: int = 2):
        self.share = share            # a name's place holds at least this share of where it was heard
        self.min_count = min_count    # and was heard there at least this often
        self.at: dict[str, Counter] = defaultdict(Counter)      # name → place → weight
        self.lower: set[str] = set()                            # words seen written in lower case
        self.capital: Counter = Counter()
        self._seen: set[tuple[Any, str]] = set()

    def update(self, dialogue: Iterable[dict[str, Any]], canonical: Callable[[Any], Any] | None = None) -> None:
        """Read lines not read yet: {"map": place, "text": ...} entries of the world memory's dialogue log."""
        for d in dialogue:
            text, place = str(d.get("text") or ""), d.get("map")
            if place is None or not text.strip():
                continue
            key = (place, " ".join(text.split()))
            if key in self._seen:
                continue
            self._seen.add(key)
            self._line(text, place)
        if canonical is not None:
            for n, c in self.at.items():
                merged: Counter = Counter()
                for p, w in c.items():
                    merged[_canon(canonical, p)] += w
                self.at[n] = merged

    def _line(self, text: str, place: Any) -> None:
        tag = TAG.match(text)
        speaker = tag.group(1).lower() if tag and tag.group(1)[0].isupper() else None
        named: set[str] = set()
        for w in WORD.findall(text):
            lw = w.lower()
            if w[0].isupper():
                self.capital[lw] += 1
                named.add(lw)
            else:
                self.lower.add(lw)
        for lw in named:
            self.at[lw][place] += 3 if lw == speaker else 1

    def names(self) -> list[str]:
        return [n for n in self.at if n not in self.lower]

    def where(self, name: str) -> Any:
        n = name.lower()
        if n in self.lower or n not in self.at:
            return None
        c = self.at[n]
        place, w = c.most_common(1)[0]
        if w < self.min_count or w < self.share * sum(c.values()):
            return None
        return place

    def heard_at(self, place: Any, k: int = 4) -> list[str]:
        out = [(self.at[n][place], n) for n in self.names() if self.where(n) == place]
        return [n for _, n in sorted(out, key=lambda t: (-t[0], t[1]))[:k]]

    def find(self, text: str) -> list[tuple[str, Any]]:
        """The names in a line that have a place, with it, in the order they appear."""
        out, seen = [], set()
        for w in WORD.findall(text or ""):
            lw = w.lower()
            if lw in seen:
                continue
            seen.add(lw)
            p = self.where(lw)
            if p is not None and w[0].isupper():
                out.append((lw, p))
        return out


def _canon(canonical: Callable[[Any], Any], p: Any) -> Any:
    try:
        return canonical(p)
    except (TypeError, IndexError, KeyError):
        return p


class Errand:
    """Out and back: the game named someone or somewhere the run has been, the run goes there, hears what is said
    there, and comes back to where it was sent from (a road that was closed, a counter that asked for something).

    Made when the way on stalls (anygame/stuck.py raised on a walking screen) and a line said where the player is
    now names a place the run knows that is not here:

        e = errand_from(marks, memory.dialogue, here=place, since=tick)
        if e: goalbook.impose(e.goal(), tick, values, source="errand")
        ... when that goal is reached:  g = e.next();  if g: goalbook.impose(g, ...)
    """

    def __init__(self, origin: Any, place: Any, name: str, line: str):
        self.origin, self.place, self.name, self.line = origin, place, name, line
        self.step = 0

    def goal(self) -> dict[str, Any] | None:
        said = self.line[:80]
        steps = [
            {"id": "errand_go", "instruction": f"go back to {self.name.upper()} (place {self.place}): the game said \"{said}\"",
             "done": {"place": self.place}, "target": {"place": self.place}},
            {"id": "errand_talk", "instruction": f"find {self.name.upper()} here and talk (press A facing them)",
             "done": {"talks": 2}},
            {"id": "errand_return", "instruction": f"return to place {self.origin}, where the way on was closed",
             "done": {"place": self.origin}, "target": {"place": self.origin}},
        ]
        return steps[self.step] if self.step < len(steps) else None

    def next(self) -> dict[str, Any] | None:
        self.step += 1
        return self.goal()


def errand_from(marks: Landmarks, dialogue: list[dict[str, Any]], here: Any, since: int = 0,
                lines: int = 6) -> Errand | None:
    """An errand from the last lines said here since `since` (a tick): the first name in them, latest line first,
    whose place is known and is not here."""
    recent = [d for d in dialogue[-40:] if d.get("map") == here and int(d.get("tick") or 0) >= since][-lines:]
    for d in reversed(recent):
        for name, place in marks.find(d.get("text") or ""):
            if place != here:
                return Errand(here, place, name, d.get("text") or "")
    return None
