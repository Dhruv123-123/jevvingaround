"""Reads from a state stream instead of pixels. A game that publishes its state (a JSON object over a WebSocket, an
HTTP endpoint, a file it rewrites, or an expression on its own page) feeds the typed frame directly: `json` picks a
value by path, `json_grid` builds a c<col>r<row> matrix from lists of coordinates, and every derived read (locate,
runs, around, tetris) works on the result exactly as it does on a colour matrix. Same semantics as reads.ts."""
from __future__ import annotations
from typing import Any


def get_path(state: Any, path: str | None) -> Any:
    """`a.b.0.c` into nested dicts and lists; None when anything along the way is missing."""
    if path in (None, "", "."):
        return state
    cur = state
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
        if cur is None:
            return None
    return cur


def read_json(state: Any, r: dict[str, Any]) -> tuple[Any, float]:
    """{kind: json, path, parse: int|float|str|bool, map: {value: label}, default}. Returns (value, confidence)."""
    v = get_path(state, r.get("path"))
    if v is None:
        return r.get("default"), 0.0
    parse = r.get("parse")
    try:
        if parse == "int":
            v = int(float(v))
        elif parse == "float":
            v = float(v)
        elif parse == "str":
            v = str(v)
        elif parse == "bool":
            v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
    except (TypeError, ValueError):
        return r.get("default"), 0.0
    m = r.get("map")
    if isinstance(m, dict):
        key = "true" if v is True else "false" if v is False else str(v)
        v = m.get(key, m.get("otherwise", v))
    return v, 1.0


def _coords(v: Any) -> list[tuple[int, int]]:
    """A list of [x, y] pairs, a single pair, or a dict with x/y (or col/row) → list of (x, y)."""
    if v is None:
        return []
    if isinstance(v, dict):
        if "x" in v and "y" in v:
            return [(int(v["x"]), int(v["y"]))]
        if "col" in v and "row" in v:
            return [(int(v["col"]), int(v["row"]))]
        return []
    if isinstance(v, (list, tuple)):
        if len(v) == 2 and all(isinstance(a, (int, float)) for a in v):
            return [(int(v[0]), int(v[1]))]
        out: list[tuple[int, int]] = []
        for e in v:
            out += _coords(e)
        return out
    return []


def read_json_grid(state: Any, r: dict[str, Any]) -> tuple[dict[str, str], float]:
    """{kind: json_grid, cols, rows, empty: ".", one_based: false, symbols: {H: {path, index|slice}, s: {path, slice: [1, null]}, F: {path}}}.
    Each symbol names a path to a coordinate or a list of coordinates ([x, y] with x the column); `index` takes one
    element, `slice: [from, to]` a range. Later symbols overwrite earlier ones on the same cell. Returns the matrix
    and 1.0 if any symbol's path resolved, else 0.0."""
    cols, rows = int(r["cols"]), int(r["rows"])
    empty = str(r.get("empty", "."))
    off = 0 if r.get("one_based") else 1
    grid = {f"c{c}r{rw}": empty for rw in range(1, rows + 1) for c in range(1, cols + 1)}
    found = 0
    for sym, spec in (r.get("symbols") or {}).items():
        spec = spec if isinstance(spec, dict) else {"path": spec}
        v = get_path(state, spec.get("path"))
        if v is None:
            continue
        if "index" in spec and isinstance(v, list):
            try:
                v = v[int(spec["index"])]
            except IndexError:
                continue
        elif "slice" in spec and isinstance(v, list):
            a, b = spec["slice"]
            v = v[int(a or 0):(int(b) if b is not None else None)]
        pts = _coords(v)
        if pts:
            found += 1
        for x, y in pts:
            c, rw = x + off, y + off
            if 1 <= c <= cols and 1 <= rw <= rows:
                grid[f"c{c}r{rw}"] = str(sym)[:1] if r.get("chars", True) else str(sym)
    return grid, 1.0 if found else 0.0
