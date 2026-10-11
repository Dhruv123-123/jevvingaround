"""Choosing a fight move by what it does to the other side. Nothing here knows a game, a move, or which bar is whose.

In Pokemon the rival's and Brock's fights are lost by choosing a move that does nothing to the other side (GROWL,
TAIL WHIP) as often as one that does (TACKLE): the menu's play-outs show both, but as text ("Enemy BULBASAUR's
ATTACK fell!") that does not say which side is closer to losing. The other side's number is often not a number at
all: Pokemon shows the enemy's health only as a bar.

So the quantity is read from the screen where each choice's play-out ends (anygame/playout.py keeps that screen),
and the choices are compared with each other:

  - **Bars.** A bar is a horizontal run of one colour, one to four pixels tall, not touching the screen's left edge.
    It is known by its top row, left end and colour; its full length is the longest it has been seen.
  - **Against the siblings.** Every choice's play-out ends on the same kind of screen (the game asking again). For
    each bar on all of them, the choice that left it longest is the baseline; a choice scores how much shorter it
    left the bars than that. What every choice does alike cancels: the other side's own move, the menu box redrawn,
    the player's bar going down by the same hit. A choice that changes nothing the others do not scores 0.
  - **Whose.** A bar whose share of full matches one of the player's own shown numbers ("16/ 19") after every
    play-out of a menu, below full, and is the only bar that does, in two menus, is the player's: a choice that
    lowers it more than its siblings scores less. A bar that once did not match is never the player's.
  - **Ending.** A play-out that leaves the scene (most pixels changed) with the player's own numbers above zero,
    from a screen showing a bar some choice has lowered before, ended the fight: it scores above any hit. Leaving
    any other screen is closing a menu and scores nothing.

A choice's label is not used to remember it across turns: in Pokemon the cursor box of the move list reads the PP
("35/35"), not the move's name, and the cursor stays where it was last. Each menu is compared afresh.

    fight = Fight()
    effects = {label: fight.effect(label, playout_result) for each menu entry played out}
    order = fight.rank(effects)        # best first; [] when no choice does anything its siblings do not
    fight.say(effects[label])          # "a bar 100% → 83% (lower than after the other choices)"
"""
from __future__ import annotations
from typing import Any

import numpy as np

MIN_LEN = 8          # native pixels: shorter runs are letters and borders' corners, not bars
MAX_TALL = 4         # rows: taller runs of one colour are areas (a sky, a box's inside), not bars
SAME_SCENE = 0.25    # share of pixels that may change while the screen stays the same scene


def _grey(img: np.ndarray) -> np.ndarray:
    s = max(1, img.shape[0] // 144)
    g = img[::s, ::s]
    if g.ndim == 3:
        g = g[:, :, :3].astype(np.int16).sum(axis=2) // 3
    return g.astype(np.int16)


def bars(img: np.ndarray, known: set | dict | None = None) -> dict[tuple[int, int, int], int]:
    """{(top row, left column, grey level): length} for every bar-shaped run on a screen, at native size: one to four
    rows of one colour, with one other colour all along it above and below (a frame, a background), not touching
    the screen's left edge. A bar already `known` counts at any length; a new one from MIN_LEN pixels."""
    g = _grey(img) // 32                        # a few levels: shading inside a bar is one colour
    h, w = g.shape
    starts_known = {(k[1], k[2]) for k in (known or ())}
    runs: dict[tuple[int, int], list[tuple[int, int]]] = {}     # (x0, level) -> [(row, length)]
    for y in range(h):
        row = g[y]
        edges = np.flatnonzero(np.diff(row)) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [w]))
        for a, b in zip(starts, ends):
            if a > 0 and (b - a >= MIN_LEN or (int(a), int(row[a])) in starts_known):
                runs.setdefault((int(a), int(row[a])), []).append((y, int(b - a)))
    out: dict[tuple[int, int, int], int] = {}
    for (x0, lev), rows in runs.items():
        band: list[tuple[int, int]] = []
        for y, n in rows + [(-9, 0)]:
            if band and (y != band[-1][0] + 1 or n != band[-1][1]):
                top, bottom, n0 = band[0][0], band[-1][0], band[0][1]
                if len(band) <= MAX_TALL and _edge(g, top - 1, x0, n0, lev) and _edge(g, bottom + 1, x0, n0, lev):
                    if n0 >= MIN_LEN or (top, x0, lev) in (known or ()):
                        out[(top, x0, lev)] = n0
                band = []
            if y >= 0:
                band.append((y, n))
    return out


def _edge(g: np.ndarray, y: int, x0: int, n: int, lev: int) -> bool:
    """The row beside a bar is one other colour all along it (lines of text between are not)."""
    if y < 0 or y >= g.shape[0]:
        return False
    seg = g[y, x0:x0 + n]
    vals, counts = np.unique(seg, return_counts=True)
    i = int(np.argmax(counts))
    return vals[i] != lev and counts[i] >= 0.9 * len(seg)


def same_scene(a: np.ndarray, b: np.ndarray) -> bool:
    ga, gb = _grey(a), _grey(b)
    return ga.shape == gb.shape and float((np.abs(ga - gb) > 16).mean()) <= SAME_SCENE


def _shares(nums: list[str]) -> list[float]:
    out = []
    for n in nums or []:
        if "/" in n:
            v, _, m = n.partition("/")
            if v.isdigit() and m.isdigit() and int(m) > 0 and int(v) <= int(m):
                out.append(int(v) / int(m))
    return out


class Fight:
    def __init__(self, match: float = 0.08):
        self.match = match                      # how close a bar's share must be to a number's to be that number's
        self.alike = 0.02                       # share of pixels, outside bars, two ends may differ by and be one screen
        self.full: dict[tuple[int, int, int], int] = {}     # bar → the longest it has been seen
        self.own: set[tuple[int, int, int]] = set()          # bars that moved with the player's own numbers
        self.own_votes: dict[tuple[int, int, int], int] = {}  # menus in which a bar alone followed them
        self.not_own: set[tuple[int, int, int]] = set()      # bars seen not following them
        self.hurt: set[tuple[int, int, int]] = set()         # the other side's bars a choice has lowered
        self.events: list[dict[str, Any]] = []

    # ---- every play-out -------------------------------------------------------------------------------------
    def effect(self, label: str, r: dict[str, Any]) -> dict[str, Any] | None:
        """The bars on screen where one play-out ended, as shares of their full length; None when it kept no screens."""
        a, b = r.get("screen_before"), r.get("screen_after")
        if a is None or b is None:
            return None
        ba, bb = bars(a, self.full), bars(b, self.full)
        for k, n in list(ba.items()) + list(bb.items()):
            self.full[k] = max(self.full.get(k, 0), n)
        own = _shares(r.get("numbers_after"))
        ended = not same_scene(a, b) and all(s > 0 for s in own or [1.0])
        return {"label": label, "after": {k: n / self.full[k] for k, n in bb.items()}, "own": own, "ended": ended,
                "before": set(ba),
                "screen": _grey(b)}

    # ---- what to choose ---------------------------------------------------------------------------------------
    def compare(self, effects: dict[str, dict[str, Any] | None]) -> dict[str, float]:
        """Each choice's score against its siblings: how much lower it left the other side's bars than the choice
        that left them highest, less the same for the player's own bars. What every choice does alike (the other
        side's own move, the menu box redrawn) cancels out."""
        es = {lab: e for lab, e in effects.items() if e}
        live = self._alike([e for e in es.values() if not e["ended"]])
        es = {lab: e for lab, e in es.items() if e["ended"] or any(e is x for x in live)}
        if len(es) < 2 or not live:
            return {}
        common = set.intersection(*(set(e["after"]) for e in live))
        own = [e["own"] for e in live]
        if all(own):
            fits = []
            for k in common:
                shares = [e["after"][k] for e in live]
                if all(min(abs(x - n) for n in o) <= self.match for x, o in zip(shares, own)):
                    if min(shares) < 0.95:
                        fits.append(k)
                else:
                    self.not_own.add(k)         # a bar that once did not follow the player's numbers never is theirs
            if len(fits) == 1 and fits[0] not in self.not_own:
                k = fits[0]
                self.own_votes[k] = self.own_votes.get(k, 0) + 1
                if self.own_votes[k] >= 2 and k not in self.own:
                    self.own.add(k)
                    self.events.append({"kind": "own bar", "bar": list(k)})
            self.own -= self.not_own
        base = {k: max(e["after"][k] for e in live) for k in common}
        out = {}
        for lab, e in es.items():
            if e["ended"]:
                # leaving the scene is winning only where a choice has lowered the other side's bar before (a
                # fight); in any other menu it is just closing the menu
                score = 1.0 if self.hurt & e["before"] else 0.0
            else:
                score = sum(base[k] - e["after"][k] for k in common if k not in self.own) - \
                        sum(base[k] - e["after"][k] for k in common if k in self.own)
            e["score"] = round(score, 3)
            e["moved"] = {k: (round(base[k], 2), round(e["after"][k], 2)) for k in common
                          if not e["ended"] and e["after"][k] < base[k] - 1e-9}
            out[lab] = e["score"]
            self.hurt |= {k for k in e["moved"] if k not in self.own}
        self.events.append({"kind": "compare", "scores": dict(out)})
        return out

    def _alike(self, live: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The largest group of play-outs that ended on the same screen apart from the bars' own rows; [] when no
        group is larger than the rest (two choices that ended on different screens cannot be compared by bars)."""
        if len(live) < 2:
            return live
        rows = np.zeros(live[0]["screen"].shape[0], bool)
        for e in live:
            for (top, _, _) in e["after"]:
                rows[top:top + MAX_TALL] = True
        def same(a, b):
            if a.shape != b.shape:
                return False
            d = np.abs(a.astype(np.int16) - b.astype(np.int16)) > 16
            return float(d[~rows].mean()) <= self.alike
        groups = [[e for e in live if same(e["screen"], x["screen"])] for x in live]
        best = max(groups, key=len)
        if sum(len(g) == len(best) and {id(e) for e in g} != {id(e) for e in best} for g in groups):
            return []
        return best if len(best) >= 2 else []

    def rank(self, effects: dict[str, dict[str, Any] | None]) -> list[str]:
        """Choices best first by what they did to the other side; [] when no choice did anything the others did not
        (not a fight, or nothing to tell them apart)."""
        scored = self.compare(effects)
        if not scored or max(scored.values()) - min(scored.values()) < 1e-6:
            return []
        return sorted(scored, key=lambda lab: -scored[lab])

    @staticmethod
    def say(e: dict[str, Any] | None) -> str:
        """One clause for the menu's landing text."""
        if not e:
            return ""
        if e["ended"]:
            return "it ends the encounter"
        bits = [f"a bar {s0:.0%} → {s1:.0%} (lower than after the other choices)" for s0, s1 in e.get("moved", {}).values()]
        return ", ".join(bits[:2]) if bits else "nothing the other choices do not do"

    def to_dict(self) -> dict[str, Any]:
        return {"full": [[list(k), v] for k, v in self.full.items()], "own": [list(k) for k in self.own]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fight":
        f = cls()
        f.full = {tuple(k): v for k, v in d.get("full", [])}
        f.own = {tuple(k) for k in d.get("own", [])}
        return f
