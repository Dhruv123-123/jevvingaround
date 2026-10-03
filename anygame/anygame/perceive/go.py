"""The Go compiler: a board read becomes groups, liberties and the consequences of every move for one colour.

Same idea as `runs` for Connect Four and `tetris` for Tetris: the exact bookkeeping (which stones a move captures,
which of our groups it saves, which point would be suicide or self-atari, who is ahead) is counted here, so the
model only chooses among moves whose effects are already written down. It is stateless: a ko recapture looks legal
here, the page refuses it, and the loop stops offering a tap that changed nothing.

Read config:  { kind: go, in: <board matrix read>, us: B, them: W, empty: ".", komi: 6.5 }
Value:        { legal: [cells], good: [cells], captures: [cells], saves: [cells], self_atari: [cells], doomed: [cells],
                danger: [cells],
                eyes: [cells], urgent: [cells], our_atari: [cells], their_atari: [cells], moves_left: n,
                stones: {us, them}, captured_by_move: {cell: n}, score: {us, them, lead},
                best: [top_k good cells by worth], worth: {cell: n}, estimate: {us, them, lead},
                playouts: {cell: {win, margin}} }   (only with `playouts: n` in the config)
`worth` looks one move deep for area: the swing in a rough area estimate (each empty point goes to the nearer colour),
plus the stones a move saves; and reads ataris deeper (ladders and short chases, `_attack`): a move whose chain
white can then chase down is `doomed` and heavily penalised, a move that gets a `danger` chain away earns its
stones, an atari white cannot escape earns twice the stones and one it can escape a little. `score` is exact area scoring and
only means something once the board is settled; `estimate` is the mid-game guess.
`playouts` (opt-in, `playouts: n`): each `best` move and each capture or save is played out n times to the end by
both sides moving at random (never filling an own eye, never suicide, the same policy as the page's `ai=mc` white),
and gets our win rate, mean final margin after komi and the games played (`n`). `playouts_top: k` with
`playouts_top_n: m` plays the k best of that first pass on to m games each. Seeded from the board, so the same board
reads the same.
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


def _respond(b: dict[Pt, str], p: Pt, att: str, dfn: str, w: int, h: int, empty: str, depth: int) -> bool:
    """The chain at p is in atari and its owner moves: can it get away? It extends at its liberty or captures an
    attacking chain that is itself in atari; three liberties is safe, two means the attacker reads on."""
    st, lb = group(b, p, w, h, empty)
    moves = set(lb)
    for s_ in st:
        for n in _nbrs(s_, w, h):
            if b.get(n) == att:
                _, alb = group(b, n, w, h, empty)
                if len(alb) == 1:
                    moves |= alb
    for m in moves:
        res = play(b, m, dfn, att, w, h, empty)
        if res is None:
            continue
        nb = res[0]
        libs = len(group(nb, p, w, h, empty)[1])
        if libs >= 3 or (libs == 2 and not _attack(nb, p, att, dfn, w, h, empty, depth - 1)):
            return True
    return False


def _attack(b: dict[Pt, str], p: Pt, att: str, dfn: str, w: int, h: int, empty: str, depth: int = 12) -> bool:
    """The attacker moves: can it capture the chain at p however its owner answers? Reads ataris only (ladders and
    short chases), `depth` moves deep; a chain with three liberties counts as safe."""
    if b.get(p) != dfn:
        return False
    _, lb = group(b, p, w, h, empty)
    if len(lb) == 1:
        return True
    if len(lb) >= 3 or depth <= 0:
        return False
    for lib in lb:
        res = play(b, lib, att, dfn, w, h, empty)
        if res is not None and not _respond(res[0], p, att, dfn, w, h, empty, depth):
            return True
    return False


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


# ---- random playouts: a flat 1-D board (0 empty, 1 us, 2 them), fast enough for a few hundred games per read -------
def _geometry(w: int, h: int) -> tuple[list[list[int]], list[list[int]]]:
    nb = [[(r + dr) * w + c + dc for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= c + dc < w and 0 <= r + dr < h]
          for r in range(h) for c in range(w)]
    dg = [[(r + dr) * w + c + dc for dc in (-1, 1) for dr in (-1, 1) if 0 <= c + dc < w and 0 <= r + dr < h]
          for r in range(h) for c in range(w)]
    return nb, dg


def _has_lib(g: list[int], i: int, nb: list[list[int]]) -> bool:
    c, seen, todo = g[i], {i}, [i]
    while todo:
        for n in nb[todo.pop()]:
            v = g[n]
            if v == 0:
                return True
            if v == c and n not in seen:
                seen.add(n)
                todo.append(n)
    return False


def _chain(g: list[int], i: int, nb: list[list[int]]) -> set[int]:
    c, seen, todo = g[i], {i}, [i]
    while todo:
        for n in nb[todo.pop()]:
            if g[n] == c and n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def _playout(g: list[int], p: int, rng: Any, nb: list[list[int]], dg: list[list[int]]) -> int:
    """Play random moves to the end (two passes or 150 moves) from g with p to move; our (1) area minus theirs."""
    g = list(g)
    empt = [i for i, v in enumerate(g) if v == 0]
    passes = n = 0
    while passes < 2 and n < 150:
        moved, k = False, len(empt)
        while k > 0:
            j = int(rng.random() * k)
            i = empt[j]
            empt[j], empt[k - 1] = empt[k - 1], empt[j]
            k -= 1
            if all(g[m] == p for m in nb[i]):          # an own eye: never filled
                d = dg[i]
                bad = sum(1 for x in d if g[x] == 3 - p)
                if (bad == 0) if len(d) < 4 else (bad <= 1):
                    continue
            g[i] = p
            caps: list[int] = []
            for m in nb[i]:
                if g[m] == 3 - p and not _has_lib(g, m, nb):
                    caps.extend(_chain(g, m, nb))
            for s_ in caps:
                g[s_] = 0
            if not caps and not _has_lib(g, i, nb):   # suicide
                g[i] = 0
                continue
            empt[k] = empt[-1]
            empt.pop()
            empt.extend(caps)
            moved = True
            break
        passes = 0 if moved else passes + 1
        n += 1
        p = 3 - p
    s = [0, 0, 0]
    for i, v in enumerate(g):
        if v:
            s[v] += 1
        else:
            o = {g[m] for m in nb[i]}
            if len(o) == 1 and 0 not in o:
                s[o.pop()] += 1
    return s[1] - s[2]


_PLAYOUT_CACHE: dict[str, dict[str, list[float]]] = {}


def playouts(b: dict[Pt, str], cands: list[Pt], us: str, them: str, w: int, h: int, empty: str, komi: float,
             n: int, top: int = 0, top_n: int = 0) -> dict[str, dict[str, float]]:
    """For each candidate move of ours: n random games from the board after it (white to move), our win rate and mean
    margin after komi. With `top`, the `top` best by that first pass are played on to `top_n` games each, so the
    close contenders separate. Cached per board, and seeded from it, so a board that has not changed costs nothing."""
    import random
    flat = [1 if b.get((c, r)) == us else 2 if b.get((c, r)) == them else 0 for r in range(1, h + 1) for c in range(1, w + 1)]
    key = f"{w}x{h}:{komi}:" + "".join(map(str, flat))
    runs = _PLAYOUT_CACHE.setdefault(key, {})
    if len(_PLAYOUT_CACHE) > 64:
        _PLAYOUT_CACHE.clear()
        _PLAYOUT_CACHE[key] = runs
    geo: list[Any] = []
    starts: dict[str, list[int] | None] = {}

    def more(p: Pt, upto: int) -> None:
        k = cell(p)
        got = runs.setdefault(k, [])
        if len(got) >= upto:
            return
        if k not in starts:
            res = play(b, p, us, them, w, h, empty)
            starts[k] = None if res is None else [1 if res[0].get((c, r)) == us else 2 if res[0].get((c, r)) == them else 0
                                                    for r in range(1, h + 1) for c in range(1, w + 1)]
        if starts[k] is None:
            return
        if not geo:
            geo.extend(_geometry(w, h))
        rng = random.Random(f"{key}{k}{len(got)}")      # seeded by the games it already has: same board, same games
        got.extend(_playout(starts[k], 2, rng, geo[0], geo[1]) - komi for _ in range(upto - len(got)))

    def summary(k: str) -> dict[str, float]:
        m = runs[k]
        return {"win": round(sum(1 for x in m if x > 0) / len(m), 2), "margin": round(sum(m) / len(m), 1), "n": len(m)}

    for p in cands:
        more(p, n)
    done = [p for p in cands if runs.get(cell(p))]
    if top and top_n > n:
        lead = sorted(done, key=lambda p: (-summary(cell(p))["win"], -summary(cell(p))["margin"]))[:top]
        for p in lead:
            more(p, top_n)
    return {cell(p): summary(cell(p)) for p in done}


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
    # chains white can capture by moving first (a ladder or a chase): ours on two liberties that do not get away
    danger: set[Pt] = set()
    chased: list[tuple[Pt, set[Pt]]] = []      # (a stone of the chain, the chain), one per chain
    seen = set()
    for p in order:
        if b[p] == us and p not in seen:
            st, lb = group(b, p, w, h, empty)
            seen |= st
            if len(lb) == 2 and _attack(b, p, them, us, w, h, empty):
                danger |= st
                chased.append((p, st))
    legal, good, captures, saves, self_atari, eyes, doomed = [], [], [], [], [], [], []
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
        # two moves deep: the chain through p ends on two liberties and white can still chase it down
        dies = libs == 2 and _attack(nb, p, them, us, w, h, empty)
        # a save: one of our chains in atari touches p and the chain through p gets away
        if libs >= 2 and not dies and any(n in our_atari for n in _nbrs(p, w, h)):
            saves.append(cell(p))
        eye = is_eye(b, p, us, w, h, empty)
        if eye:
            eyes.append(cell(p))
        sa = libs == 1 and not taken
        if sa:
            self_atari.append(cell(p))
        if dies and not taken and not sa:
            doomed.append(cell(p))
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
            mine = group(nb, p, w, h, empty)[0]
            if dies:
                v -= 2 * len(mine) + 5        # the stones it leaves to a ladder, and the move itself wasted
            # a chain white could have chased down that this move gets away
            # (only a move touching the chain, or one that captures, can change how the chase goes)
            for q, st3 in chased:
                if (taken or any(n in st3 for n in _nbrs(p, w, h))) and not _attack(nb, q, them, us, w, h, empty):
                    v += 2 * len(st3) + 4
            hit: set[Pt] = set()
            for n in _nbrs(p, w, h):
                if nb.get(n) == them and n not in hit:
                    st2, lb2 = group(nb, n, w, h, empty)
                    hit |= st2
                    if len(lb2) == 1 and not dies:
                        # an atari that white cannot escape is worth the stones; one it can run from, a little
                        v += 2 * len(st2) if not _respond(nb, n, us, them, w, h, empty, 12) else 0.5 * len(st2)
            worth[cell(p)] = round(v, 1)
    su, st_ = area_score(b, us, them, w, h, empty)
    top_k = int(r.get("top_k", 6))
    best = sorted(worth, key=lambda k: -worth[k])[:top_k]
    extra: dict[str, Any] = {}
    n_po = int(r.get("playouts", 0))
    if n_po > 0:
        pts = {cell(p): p for p in order}
        cands = list(dict.fromkeys(best + captures + saves))
        extra["playouts"] = playouts(b, [pts[c] for c in cands], us, them, w, h, empty, komi, n_po,
                                     int(r.get("playouts_top", 0)), int(r.get("playouts_top_n", 0)))
    return {
        **extra,
        "legal": legal, "good": good, "captures": captures, "saves": saves, "self_atari": self_atari, "eyes": eyes,
        "urgent": captures + [c for c in saves if c not in captures],
        "our_atari": [cell(p) for p in sorted(our_atari, key=lambda p: (p[1], p[0]))],
        "danger": [cell(p) for p in sorted(danger, key=lambda p: (p[1], p[0]))], "doomed": doomed,
        "their_atari": [cell(p) for p in sorted(their_atari, key=lambda p: (p[1], p[0]))],
        "moves_left": len(good), "captured_by_move": taken_by,
        "best": best, "worth": {k: worth[k] for k in best},
        "estimate": {"us": eu0, "them": et0 + komi, "lead": eu0 - et0 - komi},
        "stones": {"us": sum(1 for v in b.values() if v == us), "them": sum(1 for v in b.values() if v == them)},
        "score": {"us": su, "them": st_ + komi, "lead": su - st_ - komi},
    }
