"""Perception is layered: pixels (bars, colours, blobs) and templates are exact and cost ~1 ms; OCR reads numbers;
only genuinely dynamic objects go to an open-vocabulary detector. A read returns a value for the state and, where
it makes sense, boxes for the HUD."""
from __future__ import annotations
from typing import Any
import numpy as np
from ..geometry import Rect
from ..pack import Pack
from . import bar, blobs, color, ocr, template


def rect_for(pack: Pack, r: dict[str, Any]) -> Rect:
    return pack.zone(r["zone"]).rect if "zone" in r else Rect.parse(r["rect"])


CONF: dict[int, dict[str, float]] = {}   # per-call confidences, keyed by id(values): read_all fills, the loop collects


def read_all(pack: Pack, frame: np.ndarray, only: set[str] | None = None, tick: int = 0, previous: dict[str, Any] | None = None,
             pool=None, pending: dict[str, Any] | None = None, conf: dict[str, float] | None = None, state: Any = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
    """Returns (values, detections, timings_ms). A read with `every: N` is refreshed every N ticks and otherwise carried
    over. Given a thread `pool`, such a slow read (OCR, a detector) runs in the background and the loop keeps its last
    value until the new one is ready, so a 1 s OCR never stalls a 300 ms decision loop."""
    import time
    values: dict[str, Any] = {}
    dets: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    for rid, r in pack.reads.items():
        if only is not None and rid not in only:
            continue
        every = int(r.get("every", 1))
        if every > 1 and pool is not None and pending is not None:
            fut = pending.get(rid)
            have_prev = previous is not None and rid in previous
            if fut is not None and fut.done():
                v, _d, _t = fut.result()
                values[rid] = v.get(rid)
                timings[rid] = -1.0   # finished in the background
                del pending[rid]
                continue
            if fut is None and (tick % every == 1 or not have_prev):
                fut = pool.submit(_read_one, pack, frame, rid, tick)
                pending[rid] = fut
            # never wait: the first OCR of a run can take seconds (the model loads on the first real frame), and a
            # real-time game does not pause for it; until the value arrives the read is its `otherwise` (or null)
            values[rid] = previous[rid] if have_prev else r.get("otherwise")
            continue
        if every > 1 and tick % every != 1 and previous is not None and rid in previous:
            values[rid] = previous[rid]
            continue
        t0 = time.perf_counter()
        kind = r["kind"]
        if kind in ("json", "json_grid"):
            # the game's own state, not its pixels
            from .state import read_json, read_json_grid
            v, c = (read_json if kind == "json" else read_json_grid)(state, r)
            values[rid] = v
            if conf is not None:
                conf[rid] = c
            timings[rid] = 0.0
            continue
        if kind == "locate":
            src = values.get(r["in"], {})
            cells = [k for k, v in (src.items() if isinstance(src, dict) else []) if str(v) == str(r["symbol"])]
            if "row" in r:
                cells = [c for c in cells if c.endswith(f"r{r['row']}")]
            if "col" in r:
                cells = [c for c in cells if c.startswith(f"c{r['col']}r") or c == f"c{r['col']}"]
            values[rid] = cells if r.get("many") else (cells[0] if cells else None)
            if conf is not None and not r.get("many"):
                conf[rid] = 1.0 if cells else 0.0
            timings[rid] = 0.0
            continue
        if kind in ("around", "tetris", "predict", "margin", "slide"):
            continue  # derived in the loop (needs direction / history / per-run tracker state)
        if kind == "runs":
            values[rid] = runs_of(values.get(r["in"], {}), r)
            timings[rid] = 0.0
            continue
        if kind == "go":
            from . import go
            values[rid] = go.read(values.get(r["in"]), r)
            timings[rid] = 0.0
            continue
        zone = pack.zone(r["zone"]) if "zone" in r else None
        rect = rect_for(pack, r)
        if kind == "bar":
            values[rid] = bar.read(frame, rect, r)
            if conf is not None:
                conf[rid] = 1.0
        elif kind == "color":
            hit = [0, 0]
            values[rid] = color.read(frame, rect, r, zone, hit)
            if conf is not None and hit[0]:
                conf[rid] = hit[1] / hit[0]
        elif kind == "ocr":
            values[rid] = ocr.read(frame, rect, zone, r)
        elif kind == "templates":
            v, d = template.read(frame, rect, zone, r, pack.assets_dir())
            values[rid] = v
            dets += d
        elif kind == "blobs":
            v, d = blobs.read(frame, rect, zone, r)
            values[rid] = v
            dets += d
        elif kind == "vocab":
            from . import vocab
            v, d = vocab.read(frame, rect, zone, r)
            values[rid] = v
            dets += d
        timings[rid] = round((time.perf_counter() - t0) * 1000, 1)
    return values, dets, timings


def _read_one(pack: Pack, frame: np.ndarray, rid: str, tick: int) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
    return read_all(pack, frame, {rid}, tick, None)


def runs_of(src: Any, r: dict[str, Any]) -> list[str]:
    """Cells (c<col>r<row>) whose `empty` value would complete `length` of `symbol` in a straight line
    (row, column or either diagonal) through them. With gravity: down only the lowest empty cell of each
    column counts, i.e. the one a dropped piece lands on. Counting is exact here so the model never has to."""
    import re as _re
    if not isinstance(src, dict):
        return []
    cells: dict[tuple[int, int], str] = {}
    for k, v in src.items():
        m = _re.match(r"c(\d+)r(\d+)$", k)
        if m:
            cells[(int(m.group(1)), int(m.group(2)))] = str(v)
    sym, empty, need = str(r["symbol"]), str(r.get("empty", ".")), int(r.get("length", 4))
    rows = max((rc[1] for rc in cells), default=0)

    def completes(c: int, rw: int) -> bool:
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            n = 1
            for sgn in (1, -1):
                cc, rr = c + sgn * dc, rw + sgn * dr
                while cells.get((cc, rr)) == sym:
                    n += 1
                    cc, rr = cc + sgn * dc, rr + sgn * dr
            if n >= need:
                return True
        return False

    out = []
    for (c, rw), v in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if v != empty:
            continue
        landing = not (r.get("gravity") == "down" and rw < rows and cells.get((c, rw + 1)) == empty)
        if r.get("mode") == "hands":
            # cells where a drop LANDS such that the cell above it completes the line for `symbol`:
            # play there and you hand the opponent the win on top of your piece
            if landing and rw > 1 and cells.get((c, rw - 1)) == empty and completes(c, rw - 1):
                out.append(f"c{c}r{rw}")
            continue
        if r.get("gravity") == "down" and not landing:
            continue
        if completes(c, rw):
            out.append(f"c{c}r{rw}")
    return out


def around_of(cell: Any, src: Any, moving: str | None, r: dict[str, Any]) -> dict[str, Any] | None:
    """What sits next to a located cell: {up, down, left, right} → the grid symbol there, or 'wall' past the
    edge; plus 'ahead' (the cell in the direction of travel) when a direction is known."""
    import re as _re
    m = _re.match(r"c(\d+)r(\d+)$", str(cell or ""))
    if not m or not isinstance(src, dict):
        return None
    c, rw = int(m.group(1)), int(m.group(2))
    out: dict[str, Any] = {}
    free = set(str(x) for x in (r.get("free") or ["."]))
    for name, (dc, dr) in (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
        out[name] = str(src.get(f"c{c + dc}r{rw + dr}", "wall"))
        n, cc, rr = 0, c + dc, rw + dr
        while str(src.get(f"c{cc}r{rr}", "wall")) in free:
            n, cc, rr = n + 1, cc + dc, rr + dr
        out[f"{name}_free"] = n   # how many cells you could travel that way before hitting something
        out[f"{name}_space"] = _space(src, (c + dc, rw + dr), free)   # how many cells are reachable from there (flood fill)
    if moving in out:
        out["ahead"], out["ahead_free"], out["ahead_space"] = out[moving], out[f"{moving}_free"], out[f"{moving}_space"]
    return out


def _space(src: dict[str, Any], start: tuple[int, int], free: set[str], blocked: set[tuple[int, int]] = frozenset()) -> int:
    if start in blocked or str(src.get(f"c{start[0]}r{start[1]}", "wall")) not in free:
        return 0
    seen, todo = {start}, [start]
    while todo:
        c, rw = todo.pop()
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (c + dc, rw + dr)
            if nxt not in seen and nxt not in blocked and str(src.get(f"c{nxt[0]}r{nxt[1]}", "wall")) in free:
                seen.add(nxt)
                todo.append(nxt)
    return len(seen)


DIRS = (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0)))


def margin_of(cell: Any, src: Any, r: dict[str, Any]) -> dict[str, Any] | None:
    """The safety margin after each move, with the decision latency compensated: a discrete control barrier function
    on a grid. `now` is the room reachable from the located cell (the barrier value h(x) before acting). For each
    direction, the value is the room reachable from the cell the mover will occupy when the action has landed and
    the next decision is made: `lag` + 1 cells that way (the game advances `lag` cells while we think), 0 when any
    cell on that path is not free (death on the way). `<dir>_ok` holds when the room after the move keeps at least
    (1 - alpha) of the room now, the DCBF condition; `safe` lists the directions that hold, `best` the roomiest."""
    import re as _re
    m = _re.match(r"c(\d+)r(\d+)$", str(cell or ""))
    if not m or not isinstance(src, dict):
        return None
    c, rw = int(m.group(1)), int(m.group(2))
    free = set(str(x) for x in (r.get("free") or ["."]))
    lag, alpha = max(0, int(r.get("lag", 1))), float(r.get("alpha", 0.5))
    out: dict[str, Any] = {}
    now = 0
    for name, (dc, dr) in DIRS:
        now = max(now, _space(src, (c + dc, rw + dr), free))
    out["now"] = now
    safe: list[str] = []
    for name, (dc, dr) in DIRS:
        path = [(c + dc * i, rw + dr * i) for i in range(1, lag + 2)]
        if any(str(src.get(f"c{x}r{y}", "wall")) not in free for x, y in path):
            after = 0
        else:
            after = _space(src, path[-1], free, blocked=set(path[:-1]) | {(c, rw)})
        out[name] = after
        ok = after > 0 and after >= (1 - alpha) * now
        out[f"{name}_ok"] = ok
        if ok:
            safe.append(name)
    out["safe"] = safe
    out["best"] = max(DIRS, key=lambda d: out[d[0]])[0] if now else None
    return out


def margin_num(v: Any, r: dict[str, Any]) -> float | None:
    """The numeric form: how far a number is from the nearest of its bounds (a bar, a timer, a height)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    ds = []
    if "lower" in r:
        ds.append(x - float(r["lower"]))
    if "upper" in r:
        ds.append(float(r["upper"]) - x)
    return round(min(ds), 3) if ds else None
