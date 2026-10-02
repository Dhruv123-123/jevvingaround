"""The Go compiler: a board read becomes groups, liberties and the consequences of every move for one colour.

Same idea as `runs` for Connect Four and `tetris` for Tetris: the exact bookkeeping (which stones a move captures,
which of our groups it saves, which point would be suicide or self-atari, who is ahead) is counted here, so the
model only chooses among moves whose effects are already written down. It is stateless: a ko recapture looks legal
here, the page refuses it, and the loop stops offering a tap that changed nothing.

Read config:  { kind: go, in: <board matrix read>, us: B, them: W, empty: ".", komi: 6.5 }
Value:        { legal: [cells], good: [cells], captures: [cells], saves: [cells], self_atari: [cells],
                eyes: [cells], urgent: [cells], our_atari: [cells], their_atari: [cells], moves_left: n,
                stones: {us, them}, captured_by_move: {cell: n}, score: {us, them, lead},
                best: [top_k good cells by worth], worth: {cell: n}, estimate: {us, them, lead} }
`worth` looks one move deep: the swing in a rough area estimate (each empty point goes to the nearer colour), plus
the stones a move saves or puts in atari, minus a chain left on two liberties. `score` is exact area scoring and
only means something once the board is settled; `estimate` is the mid-game guess.
Cells are c<col>r<row> as in every grid read; r1 is the top row."""
from __future__ import annotations
import re
from typing import Any

Pt = tuple[int, int]


def _board(src: Any) -> tuple[dict[Pt, str], int, int]:
    pts: dict[Pt, str] = {}
    if isinstance(src, dict):
        for k, v in src.items():
            m = re.match(r"c(\d+)r(\d+)$", str(k))
            if m:
                pts[(int(m.group(1)), int(m.group(2)))] = str(v)
    elif isinstance(src, list):          # rows of characters, r1 first
        for r, row in enumerate(src, 1):
            for c, ch in enumerate(str(row), 1):
                pts[(c, r)] = ch
    w = max((p[0] for p in pts), default=0)
    h = max((p[1] for p in pts), default=0)
    return pts, w, h


def _nbrs(p: Pt, w: int, h: int) -> list[Pt]:
    c, r = p
    return [(c + dc, r + dr) for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 1 <= c + dc <= w and 1 <= r + dr <= h]


def group(b: dict[Pt, str], p: Pt, w: int, h: int, empty: str) -> tuple[set[Pt], set[Pt]]:
    """The chain of stones through p and its liberties."""
    col, stones, libs, todo = b[p], {p}, set(), [p]
    while todo:
        q = todo.pop()
        for n in _nbrs(q, w, h):
            v = b.get(n)
            if v == empty:
                libs.add(n)
            elif v == col and n not in stones:
                stones.add(n)
                todo.append(n)
    return stones, libs


def play(b: dict[Pt, str], p: Pt, col: str, other: str, w: int, h: int, empty: str) -> tuple[dict[Pt, str], int, int] | None:
    """The board after `col` plays at p, the stones it captured and the liberties of the placed chain; None if illegal
    (occupied or suicide)."""
    if b.get(p) != empty:
        return None
    nb = dict(b)
    nb[p] = col
    taken = 0
    for n in _nbrs(p, w, h):
        if nb.get(n) == other:
            st, lb = group(nb, n, w, h, empty)
            if not lb:
                for s in st:
                    nb[s] = empty
                taken += len(st)
    _, libs = group(nb, p, w, h, empty)
    if not libs:
        return None
    return nb, taken, len(libs)


def is_eye(b: dict[Pt, str], p: Pt, col: str, w: int, h: int, empty: str) -> bool:
    """A single empty point walled in by `col` whose diagonals are mostly `col`: filling it only hurts its owner."""
    if b.get(p) != empty or any(b.get(n) != col for n in _nbrs(p, w, h)):
        return False
    c, r = p
    diag = [(c + dc, r + dr) for dc in (-1, 1) for dr in (-1, 1)]
    on_board = [d for d in diag if 1 <= d[0] <= w and 1 <= d[1] <= h]
    bad = sum(1 for d in on_board if b.get(d) not in (col, empty))
    return bad == 0 if len(on_board) < 4 else bad <= 1


def area_score(b: dict[Pt, str], us: str, them: str, w: int, h: int, empty: str) -> tuple[int, int]:
    """Stones plus empty regions that touch only one colour (area scoring, nothing removed as dead)."""
    s = {us: 0, them: 0}
    for v in b.values():
        if v in s:
            s[v] += 1
    seen: set[Pt] = set()
    for p, v in b.items():
        if v != empty or p in seen:
            continue
        region, border, todo = {p}, set(), [p]
        while todo:
            q = todo.pop()
            for n in _nbrs(q, w, h):
                if b.get(n) == empty and n not in region:
                    region.add(n)
                    todo.append(n)
                elif b.get(n) in s:
                    border.add(b[n])
        seen |= region
        if len(border) == 1:
            s[border.pop()] += len(region)
    return s[us], s[them]


def estimate(b: dict[Pt, str], us: str, them: str, w: int, h: int, empty: str, reach: int = 3) -> tuple[int, int]:
    """A rough area count mid-game: stones plus each empty point closer (Manhattan) to one colour's stones than the
    other's, within `reach`. Crude, but it rewards claiming open space and gives nothing for filling your own."""
    stones = {us: [p for p, v in b.items() if v == us], them: [p for p, v in b.items() if v == them]}
    s = {us: len(stones[us]), them: len(stones[them])}
    for p, v in b.items():
        if v != empty:
            continue
        d = {k: min((abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in pts), default=99) for k, pts in stones.items()}
        if d[us] < d[them] and d[us] <= reach:
            s[us] += 1
        elif d[them] < d[us] and d[them] <= reach:
            s[them] += 1
    return s[us], s[them]


def cell(p: Pt) -> str:
    return f"c{p[0]}r{p[1]}"


def read(src: Any, r: dict[str, Any]) -> dict[str, Any] | None:
    b, w, h = _board(src)
    if not b:
        return None
    us, them, empty = str(r.get("us", "B")), str(r.get("them", "W")), str(r.get("empty", "."))
    komi = float(r.get("komi", 0))
    order = sorted(b, key=lambda p: (p[1], p[0]))
    # chains in atari, ours and theirs
    our_atari: set[Pt] = set()
    their_atari: set[Pt] = set()
    seen: set[Pt] = set()
    for p in order:
        if b[p] in (us, them) and p not in seen:
            st, lb = group(b, p, w, h, empty)
            seen |= st
            if len(lb) == 1:
                (our_atari if b[p] == us else their_atari).update(st)
    legal, good, captures, saves, self_atari, eyes = [], [], [], [], [], []
    taken_by: dict[str, int] = {}
    worth: dict[str, float] = {}
    eu0, et0 = estimate(b, us, them, w, h, empty)
    for p in order:
        if b[p] != empty:
            continue
        res = play(b, p, us, them, w, h, empty)
        if res is None:
            continue
        nb, taken, libs = res
        legal.append(cell(p))
        if taken:
            captures.append(cell(p))
            taken_by[cell(p)] = taken
        # a save: one of our chains in atari touches p and the chain through p ends with two or more liberties
        if libs >= 2 and any(n in our_atari for n in _nbrs(p, w, h)):
            saves.append(cell(p))
        eye = is_eye(b, p, us, w, h, empty)
        if eye:
            eyes.append(cell(p))
        sa = libs == 1 and not taken
        if sa:
            self_atari.append(cell(p))
        if not eye and not sa:
            good.append(cell(p))
            # one move deep: the estimated area swing, plus what the bare count misses (a chain left on two
            # liberties can be chased, a white chain put in atari has to run or die)
            eu, et = estimate(nb, us, them, w, h, empty)
            v = (eu - eu0) - (et - et0)
            saved: set[Pt] = set()
            for n in _nbrs(p, w, h):
                if n in our_atari and n not in saved:
                    saved |= group(b, n, w, h, empty)[0]
            v += 2 * len(saved)
            if libs == 2:
                v -= len(group(nb, p, w, h, empty)[0])
            for n in _nbrs(p, w, h):
                if nb.get(n) == them:
                    st2, lb2 = group(nb, n, w, h, empty)
                    if len(lb2) == 1 and libs >= 2:
                        v += len(st2)
            worth[cell(p)] = round(v, 1)
    su, st_ = area_score(b, us, them, w, h, empty)
    top_k = int(r.get("top_k", 6))
    best = sorted(worth, key=lambda k: -worth[k])[:top_k]
    return {
        "legal": legal, "good": good, "captures": captures, "saves": saves, "self_atari": self_atari, "eyes": eyes,
        "urgent": captures + [c for c in saves if c not in captures],
        "our_atari": [cell(p) for p in sorted(our_atari, key=lambda p: (p[1], p[0]))],
        "their_atari": [cell(p) for p in sorted(their_atari, key=lambda p: (p[1], p[0]))],
        "moves_left": len(good), "captured_by_move": taken_by,
        "best": best, "worth": {k: worth[k] for k in best},
        "estimate": {"us": eu0, "them": et0 + komi, "lead": eu0 - et0 - komi},
        "stones": {"us": sum(1 for v in b.values() if v == us), "them": sum(1 for v in b.values() if v == them)},
        "score": {"us": su, "them": st_ + komi, "lead": su - st_ - komi},
    }
