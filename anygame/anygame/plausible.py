"""Plausibility checks: invariants a pack declares over its reads, judged every tick against the last reading the
runtime accepted. A wrong read is otherwise invisible: the decider acts on it, replay agrees with it, and the
learning loop blames the play. A tick whose reads break an invariant is read again from a fresh frame; if the
reads still break it, the tick is flagged and nothing is done on it; if it persists, the episode ends with the
broken invariant as its reason, so the revision is pointed at the read and not at the play.

    plausible:
      - { read: board, sticky: [X, O] }                 # a placed mark never changes or disappears (a reset to all-empty is fine)
      - { read: board, max_changes: 2 }                 # at most N cells change between two readings
      - { read: board, count: [X, O], diff: [0, 1] }    # count(X) - count(O) stays within [lo, hi]
      - { when: { line: board, symbols: [X, O], length: 3 }, require: { read: status, in: [we_won, we_lost, draw] } }
      - { when: { read: status, equals: our_turn }, read: board, count: [X, O], diff: [0, 0] }

`when` and `require` take a read condition ({read, equals|in|not|gte|lte}) or a line condition (some symbol has
`length` in a row, column or diagonal of a grid read). Every check may carry `when`."""
from __future__ import annotations
import re
from typing import Any

ASSERTIONS = ("sticky", "max_changes", "count", "require")
_CELL = re.compile(r"c(\d+)r(\d+)$")


def grid_of(v: Any) -> dict[tuple[int, int], str] | None:
    """A grid read as {(col, row): symbol}, from either form the loop holds: {c<col>r<row>: v} or rows of characters."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            m = _CELL.match(str(k))
            if m:
                out[(int(m.group(1)), int(m.group(2)))] = str(x)
        return out or None
    if isinstance(v, list) and v and all(isinstance(r, str) for r in v):
        return {(c + 1, r + 1): ch for r, row in enumerate(v) for c, ch in enumerate(row)}
    return None


def _empty_of(pack_reads: dict[str, Any], rid: str, chk: dict[str, Any]) -> str:
    r = pack_reads.get(rid) or {}
    return str(chk.get("empty", r.get("otherwise", ".")))


def _get(values: dict[str, Any], path: str) -> Any:
    cur: Any = values
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _line(g: dict[tuple[int, int], str], symbols: list[str], length: int) -> str | None:
    """The first symbol with `length` in a straight line, or None."""
    for (c, r), s in g.items():
        if s not in symbols:
            continue
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            if all(g.get((c + k * dc, r + k * dr)) == s for k in range(length)):
                return s
    return None


def cond(c: dict[str, Any], values: dict[str, Any]) -> bool:
    if "line" in c:
        g = grid_of(values.get(c["line"]))
        return bool(g) and _line(g, [str(s) for s in c.get("symbols") or []], int(c.get("length", 3))) is not None
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


def _cond_ok(c: Any, reads: dict[str, Any]) -> str | None:
    if not isinstance(c, dict):
        return "a condition is {read, equals|in|not|gte|lte} or {line: <grid read>, symbols, length}"
    if "line" in c:
        if c["line"] not in reads:
            return f"unknown read '{c['line']}'"
        if not isinstance(c.get("symbols"), list) or not c["symbols"]:
            return "a line condition needs symbols: [<char>, ...]"
        return None
    if "read" not in c or not any(k in c for k in ("equals", "in", "not", "gte", "lte")):
        return "a condition is {read, equals|in|not|gte|lte} or {line: <grid read>, symbols, length}"
    if str(c["read"]).split(".")[0] not in reads:
        return f"unknown read '{c['read']}'"
    return None


def check_spec(spec: Any, reads: dict[str, Any]) -> str | None:
    """None when the `plausible` list is well formed, else what is wrong with it (the loader raises it)."""
    if spec is None:
        return None
    if not isinstance(spec, list):
        return "plausible must be a list of checks"
    for i, chk in enumerate(spec):
        where = f"plausible[{i}]"
        if not isinstance(chk, dict):
            return f"{where}: a check is a mapping"
        kinds = [k for k in ASSERTIONS if k in chk]
        if len(kinds) != 1:
            return f"{where}: needs exactly one of {', '.join(ASSERTIONS)}"
        if "when" in chk:
            bad = _cond_ok(chk["when"], reads)
            if bad:
                return f"{where}: when: {bad}"
        if kinds[0] == "require":
            bad = _cond_ok(chk["require"], reads)
            if bad:
                return f"{where}: require: {bad}"
            continue
        if chk.get("read") not in reads:
            return f"{where}: {kinds[0]} needs read: <a grid read id>"
        if kinds[0] == "sticky" and not (isinstance(chk["sticky"], list) and chk["sticky"]):
            return f"{where}: sticky needs a list of symbols"
        if kinds[0] == "max_changes" and not isinstance(chk["max_changes"], int):
            return f"{where}: max_changes needs a whole number"
        if kinds[0] == "count":
            if not (isinstance(chk["count"], list) and len(chk["count"]) == 2):
                return f"{where}: count needs two symbols, [A, B]"
            d = chk.get("diff")
            if not (isinstance(d, list) and len(d) == 2 and all(isinstance(x, int) for x in d)):
                return f"{where}: count needs diff: [lo, hi], the allowed range of count(A) - count(B)"
    return None


def violations(spec: list[dict[str, Any]] | None, values: dict[str, Any], prev: dict[str, Any] | None,
               reads: dict[str, Any] | None = None) -> list[str]:
    """What this reading breaks, one line per broken check, judged against `prev` (the last accepted reading)."""
    out: list[str] = []
    reads = reads or {}
    for chk in spec or []:
        if "when" in chk and not cond(chk["when"], values):
            continue
        if "require" in chk:
            if not cond(chk["require"], values):
                c = chk["require"]
                got = _get(values, c["read"]) if "read" in c else None
                why = f"{c['read']} is {got!r}" if "read" in c else f"no line on {c['line']}"
                out.append(f"{why} but {_describe(chk.get('when'))} (require {_describe(c)})")
            continue
        rid = chk["read"]
        g = grid_of(values.get(rid))
        if g is None:
            continue
        empty = _empty_of(reads, rid, chk)
        if "count" in chk:
            a, b = (str(s) for s in chk["count"])
            lo, hi = chk["diff"]
            d = sum(1 for s in g.values() if s == a) - sum(1 for s in g.values() if s == b)
            if not lo <= d <= hi:
                out.append(f"{rid}: count({a}) - count({b}) is {d}, outside [{lo}, {hi}]" + (f" while {_describe(chk['when'])}" if "when" in chk else ""))
            continue
        p = grid_of((prev or {}).get(rid))
        if p is None or all(s == empty for s in g.values()):
            continue        # nothing to compare with, or a restart: a cleared board may follow anything
        if "sticky" in chk:
            keep = {str(s) for s in chk["sticky"]}
            lost = sorted((c, r) for (c, r), s in p.items() if s in keep and g.get((c, r)) != s)
            if lost:
                cells = ", ".join(f"c{c}r{r} {p[(c, r)]}→{g.get((c, r))}" for c, r in lost[:4])
                out.append(f"{rid}: a placed {'/'.join(sorted(keep))} changed ({cells})")
        elif "max_changes" in chk:
            n = sum(1 for k, s in g.items() if p.get(k) != s)
            if n > int(chk["max_changes"]):
                out.append(f"{rid}: {n} cells changed in one tick (at most {chk['max_changes']})")
    return out


def _describe(c: dict[str, Any] | None) -> str:
    if not c:
        return ""
    if "line" in c:
        return f"{c['line']} has {c.get('length', 3)} in a line"
    for k in ("equals", "in", "not", "gte", "lte"):
        if k in c:
            return f"{c['read']} {k} {c[k]!r}"
    return str(c)
