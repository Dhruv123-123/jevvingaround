"""Game packs: one YAML that says what is on the screen, how to read it, what the moves are, and how to play."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
from .geometry import Rect, Zone

READ_KINDS = {"bar", "templates", "ocr", "vocab", "blobs", "color", "locate", "runs", "around", "tetris", "json", "json_grid", "predict", "margin", "go", "slide", "head", "gap"}
QUESTION_TYPES = {"noul", "choice", "score"}


class PackError(ValueError):
    pass


@dataclass
class Action:
    id: str
    kind: str                       # tap | swipe | key | wait | play  (play = pick a slot then a target cell)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pack:
    name: str
    path: Path
    orientation: str
    size: tuple[int, int]           # logical frame size the pack was authored against (w, h)
    zones: dict[str, Zone]
    reads: dict[str, dict[str, Any]]
    actions: list[Action]
    tick_hz: float
    play: str
    questions: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    raw: dict[str, Any]
    tasks: list[dict[str, Any]] = field(default_factory=list)       # goals with a verifier over the reads (see TASK_KEYS)
    modes: dict[str, "Pack"] = field(default_factory=dict)          # sub-packs for other screens, each with a `when`
    fingerprints: dict[str, str] = field(default_factory=dict)      # screen name → base64 fingerprint

    def zone(self, name: str) -> Zone:
        if name not in self.zones:
            raise PackError(f"{self.path}: unknown zone '{name}'")
        return self.zones[name]

    def assets_dir(self) -> Path:
        return self.path.parent

    def action(self, id: str) -> Action:
        for a in self.actions:
            if a.id == id:
                return a
        raise PackError(f"{self.path}: unknown action '{id}'")


MODE_KEYS = ("zones", "read", "act", "play", "questions", "rules", "act_when", "stop_when", "settle", "tick_hz", "reflex", "plausible", "ask", "ask_when")
TASK_CATEGORIES = ("navigate", "collect", "score", "survive", "clear", "build", "avoid", "other")


def _cond_ok(c: Any) -> bool:
    return isinstance(c, dict) and "read" in c and any(k in c for k in ("equals", "in", "not", "gte", "lte", "contains"))


# Bounds on a task's tick budget. Any pack: limit_ticks and hold_ticks are whole numbers of at least 1, and the
# condition must hold for no longer than the attempt lasts. Proposed by the setter (a model guessing at the game):
# limit_ticks is clamped to [SETTER_LIMIT_MIN, SETTER_LIMIT_MAX]. At about 3 decisions a second the floor is a few
# seconds of play, less than any task worth practising needs (the setter once proposed 5); the ceiling is a long
# game, past which a task is "play the game" and one attempt eats the episode.
TASK_LIMIT_MAX = 20000
SETTER_LIMIT_MIN, SETTER_LIMIT_MAX = 20, 2000


def _whole(v: Any) -> int | None:
    """v as a whole number, or None (bools, fractions, text and non-finite values are not tick counts)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v == v and abs(v) != float("inf") and float(v).is_integer() else None


def _labels(r: dict[str, Any], zones: dict[str, Zone] | None) -> set[Any] | None:
    """The values a read can take when they are a closed set: a colour read on one rect (or a zone without a grid)
    with named options gives one of the names or its `otherwise`. None when the read's values are open (numbers,
    cells, grids, parsed text) or its zone is not known here."""
    if r.get("kind") != "color" or not isinstance(r.get("options"), dict) or r.get("parse") or r.get("as"):
        return None
    if "zone" in r and (zones is None or r["zone"] not in zones or zones[r["zone"]].grid):
        return None
    return set(r["options"]) | {r.get("otherwise", "unknown")}


def _impossible(conds: list[dict[str, Any]], reads: dict[str, Any], zones: dict[str, Zone] | None = None) -> str:
    """Why these conditions (all must hold) can never hold together, or '': a threshold that is not a number, an
    empty `in`, a label a closed read never gives, a threshold on a read that gives labels, or gte above lte."""
    lo: dict[str, float] = {}
    hi: dict[str, float] = {}
    for c in conds:
        rid = str(c["read"])
        labels = _labels(reads.get(rid) or {}, zones) if rid in reads else None
        for op in ("gte", "lte"):
            if op in c:
                if isinstance(c[op], bool) or not isinstance(c[op], (int, float)):
                    return f"{rid} {op} {c[op]!r}: a threshold must be a number"
                if labels is not None:
                    return f"{rid} gives one of {sorted(map(str, labels))}, never a number to compare with {op}"
                if op == "gte":
                    lo[rid] = max(lo.get(rid, float("-inf")), c[op])
                else:
                    hi[rid] = min(hi.get(rid, float("inf")), c[op])
        if "in" in c and (not isinstance(c["in"], list) or not c["in"]):
            return f"{rid} in {c['in']!r}: `in` takes a non-empty list"
        if labels is not None:
            want = [c["equals"]] if "equals" in c else (c["in"] if "in" in c else [])
            bad = [v for v in want if not any(v == lab for lab in labels)]
            if bad and len(bad) == len(want):
                return f"{rid} never reads {bad[0]!r}: it gives one of {sorted(map(str, labels))}"
    for rid in lo:
        if rid in hi and lo[rid] > hi[rid]:
            return f"{rid} cannot be at least {lo[rid]:g} and at most {hi[rid]:g}"
    return ""


def check_tasks(tasks: Any, reads: dict[str, Any], where: str = "pack", clamp: tuple[int, int] | None = None,
                zones: dict[str, Zone] | None = None) -> list[dict[str, Any]]:
    """Tasks are goals the runtime can verify from the reads: `done` (one condition or a list that must all hold)
    marks completion once it has held `hold_ticks` ticks; `when` says when the task is available; `limit_ticks`
    bounds the attempt. Returns the tasks with their defaults filled, or raises PackError. A task that can never
    complete (a limit under 1, a hold longer than the limit, a done no read can make true) is refused; `clamp`
    (lo, hi) pulls limit_ticks into that range first, as the setter does for its proposals."""
    out = []
    seen: set[str] = set()
    for t in tasks or []:
        if not isinstance(t, dict) or not t.get("id") or not t.get("instruction") or "done" not in t:
            raise PackError(f"{where}: every task needs id, instruction and done: {{read, equals|in|not|gte|lte}} (or a list of them)")
        tid = str(t["id"])
        if tid in seen:
            raise PackError(f"{where}: task '{tid}' is listed twice")
        seen.add(tid)
        conds = t["done"] if isinstance(t["done"], list) else [t["done"]]
        if not conds:
            raise PackError(f"{where}: task '{tid}': done is an empty list")
        for c in conds + ([t["when"]] if t.get("when") else []):
            if not _cond_ok(c):
                raise PackError(f"{where}: task '{tid}': a condition is {{read: <id or id.path>, equals|in|not|gte|lte: v}}")
            if str(c["read"]).split(".")[0] not in reads:
                raise PackError(f"{where}: task '{tid}': unknown read '{c['read']}'")
        why = _impossible(conds, reads, zones) or (_impossible([t["when"]], reads, zones) if t.get("when") else "")
        if why:
            raise PackError(f"{where}: task '{tid}' can never be done: {why}")
        limit, hold = _whole(t.get("limit_ticks", 150)), _whole(t.get("hold_ticks", 1))
        if limit is None or hold is None:
            raise PackError(f"{where}: task '{tid}': limit_ticks and hold_ticks are whole numbers of ticks")
        if clamp and limit >= 1:
            limit = max(clamp[0], min(clamp[1], limit))
        if not 1 <= limit <= TASK_LIMIT_MAX:
            raise PackError(f"{where}: task '{tid}': limit_ticks {limit} is outside 1..{TASK_LIMIT_MAX}")
        if not 1 <= hold <= limit:
            raise PackError(f"{where}: task '{tid}': hold_ticks {hold} must be between 1 and limit_ticks ({limit}), or the task can never be done")
        cat = str(t.get("category") or "other")
        out.append({**t, "id": tid, "done": conds, "hold_ticks": hold, "limit_ticks": limit,
                    "category": cat if cat in TASK_CATEGORIES else "other"})
    return out


def merge_mode(base: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    """A mode is the base pack with these keys overridden (zones/read merged by key)."""
    out = {k: v for k, v in base.items() if k not in ("modes", "tests", "fingerprints")}
    for k in MODE_KEYS:
        if k not in mode:
            continue
        if k in ("zones", "read") and isinstance(mode[k], dict):
            out[k] = {**(base.get(k) or {}), **mode[k]}
        else:
            out[k] = mode[k]
    for k in ("act_when", "stop_when"):
        if k in mode and mode[k] is None:
            out.pop(k, None)
    return out


def dump_pack(raw: dict[str, Any]) -> str:
    return yaml.safe_dump(raw, sort_keys=False, width=120, allow_unicode=True)


def load_pack_text(text: str, name: str = "pack") -> "Pack":
    """Load a pack from YAML text (no fixtures on disk): what the loop uses for learned modes."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="anygame-pack-"))
    (d / "pack.yaml").write_text(text)
    return load_pack(d, _allow_no_tests=True)


def load_pack(path: str | os.PathLike, _allow_no_tests: bool = False) -> Pack:
    p = Path(path)
    if p.is_dir():
        p = p / "pack.yaml"
    try:
        raw = yaml.safe_load(p.read_text())
    except Exception as e:  # noqa: BLE001
        raise PackError(f"{p}: cannot read: {e}") from e
    if not isinstance(raw, dict) or "game" not in raw:
        raise PackError(f"{p}: 'game' is required")
    screen = raw.get("screen", {}) or {}
    size = tuple(screen.get("size", [540, 960]))
    zones: dict[str, Zone] = {}

    def _px(d: dict, what: str) -> None:
        # rect_px: [x0, y0, x1, y1] in pixels of screen.size → rect normalized 0..1 (authoring convenience)
        if "rect_px" in d and "rect" not in d:
            try:
                x0, y0, x1, y1 = [float(v) for v in d["rect_px"]]
            except Exception as e:  # noqa: BLE001
                raise PackError(f"{p}: {what}: rect_px must be [x0, y0, x1, y1] pixels") from e
            # an author often overshoots the frame by a few pixels: clamp to it, and refuse only an empty box
            x0, x1 = max(0.0, min(x0, size[0])), max(0.0, min(x1, size[0]))
            y0, y1 = max(0.0, min(y0, size[1])), max(0.0, min(y1, size[1]))
            if x1 <= x0 or y1 <= y0:
                raise PackError(f"{p}: {what}: rect_px {d['rect_px']} is empty or outside the {size[0]}x{size[1]} frame")
            d["rect"] = [x0 / size[0], y0 / size[1], x1 / size[0], y1 / size[1]]

    for name, z in (raw.get("zones") or {}).items():
        _px(z, f"zone '{name}'")
        if "rect" not in z:
            raise PackError(f"{p}: zone '{name}': needs rect or rect_px")
        grid = tuple(z["grid"]) if z.get("grid") else None
        try:
            zones[name] = Zone(name, Rect.parse(z["rect"]), grid)
        except ValueError as e:      # a bad rect is a pack error the author can fix, not a crash
            raise PackError(f"{p}: zone '{name}': {e}") from e
    reads = raw.get("read") or {}
    for rid, r in reads.items():
        _px(r, f"read '{rid}'")
        if r.get("kind") not in READ_KINDS:
            raise PackError(f"{p}: read '{rid}': kind must be one of {sorted(READ_KINDS)}")
        if "zone" in r and r["zone"] not in zones:
            raise PackError(f"{p}: read '{rid}': unknown zone '{r['zone']}'")
        if r.get("kind") == "locate":
            if r.get("in") not in reads or "symbol" not in r:
                raise PackError(f"{p}: read '{rid}': locate needs 'in' (a grid read id) and 'symbol'")
        elif r.get("kind") == "runs":
            if r.get("in") not in reads or "symbol" not in r:
                raise PackError(f"{p}: read '{rid}': runs needs 'in' (a grid read id), 'symbol' and optionally length/empty/gravity")
        elif r.get("kind") == "go":
            if r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': go needs 'in' (the board grid read), optionally us/them/empty/komi")
        elif r.get("kind") == "tetris":
            if r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': tetris needs 'in' (the board grid read), optionally next_in (the preview grid read)")
        elif r.get("kind") == "slide":
            if r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': slide needs 'in' (the 4x4 number grid read), optionally depth and corner")
        elif r.get("kind") == "around":
            if r.get("of") not in reads or r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': around needs 'of' (a locate read id) and 'in' (a grid read id)")
        elif r.get("kind") == "margin":
            if r.get("of") not in reads or ("in" in r and r["in"] not in reads) or ("in" not in r and "lower" not in r and "upper" not in r):
                raise PackError(f"{p}: read '{rid}': margin needs 'of' (a locate read) and 'in' (a grid read), or 'of' (a number read) with lower and/or upper")
        elif r.get("kind") == "predict":
            if r.get("of") not in reads or not reads[r["of"]].get("history"):
                raise PackError(f"{p}: read '{rid}': predict needs 'of' (a locate read with history: 1)")
        elif r.get("kind") == "head":
            if r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': head needs 'in' (a grid read) and 'symbol' (the body's symbol)")
        elif r.get("kind") == "gap":
            if r.get("in") not in reads or "symbol" not in r:
                raise PackError(f"{p}: read '{rid}': gap needs 'in' (a grid read, scanned left to right) and 'symbol' (what counts as an obstacle)")
        elif r.get("kind") == "json_grid":
            if "cols" not in r or "rows" not in r or not isinstance(r.get("symbols"), dict):
                raise PackError(f"{p}: read '{rid}': json_grid needs cols, rows and symbols: {{<char>: {{path, index|slice}}}}")
        elif r.get("kind") == "json":
            if "path" not in r:
                raise PackError(f"{p}: read '{rid}': json needs 'path' into the device's state")
        elif "zone" not in r and "rect" not in r:
            raise PackError(f"{p}: read '{rid}': needs zone or rect")
    actions: list[Action] = []
    for a in raw.get("act") or []:
        if "id" not in a:
            raise PackError(f"{p}: every action needs an id")
        kind = a.get("kind") or ("wait" if a["id"] == "wait" else "tap")
        if kind == "macro" and not a.get("options"):
            raise PackError(f"{p}: action '{a['id']}': macro needs 'options: <read id>' (a read whose value has landings + macros, e.g. a tetris read)")
        if kind == "chunk" and not (isinstance(a.get("keys"), list) and a["keys"]):
            raise PackError(f"{p}: action '{a['id']}': chunk needs 'keys: [<key>, ...]' (optionally key_ms, hold_ms)")
        if kind == "mouse_move" and ("dx" not in a and "dy" not in a):
            raise PackError(f"{p}: action '{a['id']}': mouse_move needs dx and/or dy (pixels of relative motion)")
        if kind == "key" and "key" not in a:
            raise PackError(f"{p}: action '{a['id']}': key needs 'key' (optionally hold_ms)")
        actions.append(Action(a["id"], kind, {k: v for k, v in a.items() if k not in ("id", "kind")}))
    if not actions:
        raise PackError(f"{p}: 'act' must list at least one action")
    questions = raw.get("questions") or []
    for q in questions:
        if q.get("type") not in QUESTION_TYPES or "id" not in q or "instructions" not in q:
            raise PackError(f"{p}: question {q.get('id')}: needs id, type (noul|choice|score), instructions")
    if raw.get("settle") not in (None, "screen_change"):
        raise PackError(f"{p}: settle must be 'screen_change' (wait for the screen to change after an action before deciding again)")
    rules = raw.get("rules") or []
    for c in (raw.get("reflex") if isinstance(raw.get("reflex"), list) else [raw.get("reflex")] if raw.get("reflex") else []):
        if not (isinstance(c, dict) and "read" in c and any(k in c for k in ("equals", "in", "not", "gte", "lte", "contains"))):
            raise PackError(f"{p}: reflex needs {{read, equals|in|not|gte|lte}} (or a list of them): when it holds, the rules act on the decider's last answers without asking it")
    if raw.get("ask") not in (None, "async"):
        raise PackError(f"{p}: ask: async is the only option (the decider runs beside the loop, which acts on its last answers meanwhile)")
    for c in (raw.get("ask_when") if isinstance(raw.get("ask_when"), list) else [raw.get("ask_when")] if raw.get("ask_when") else []):
        if not (isinstance(c, dict) and "read" in c and any(k in c for k in ("equals", "in", "not", "gte", "lte", "contains"))):
            raise PackError(f"{p}: ask_when needs {{read, equals|in|not|gte|lte}} (or a list of them): with ask: async, the decider is asked only when it holds")
    for rl in rules:
        conds = rl.get("if") if isinstance(rl.get("if"), list) and rl.get("if") else [rl.get("if") or {}]
        for cond in conds:
            ok_noul = isinstance(cond, dict) and "noul" in cond and any(k in cond for k in ("gte", "lte"))
            ok_read = isinstance(cond, dict) and "read" in cond and any(k in cond for k in ("equals", "in", "not", "gte", "lte", "contains"))
            if not (ok_noul or ok_read):
                raise PackError(f"{p}: rule needs if: {{noul, gte|lte}} or if: {{read, equals|in|not|gte|lte}} (or a list of them, all of which must hold)")
        u = rl.get("unless")
        if u is not None and not all(isinstance(x, dict) and "read" in x and any(k in x for k in ("equals", "in", "not", "gte", "lte", "contains")) for x in (u if isinstance(u, list) and u else [u])):
            raise PackError(f"{p}: rule 'unless' needs {{read, equals|in|not|gte|lte}} (or a list of them): the rule does not apply when one holds")
        if not any(k in rl for k in ("exclude", "set", "avoid", "only")):
            raise PackError(f"{p}: rule needs 'exclude: [actions]', 'set: {{param_question: from_question}}', 'avoid: {{param_question: read}}' or 'only: {{param_question: read}}'")
        for k in ("set", "avoid", "only"):
            if k in rl and not isinstance(rl[k], dict):
                raise PackError(f"{p}: rule {k}: must map a parameter question to a read ({k}: {{<action>__cell: <read>}}), got {rl[k]!r}"
                                + ("; to allow only some actions, exclude the others with exclude: [actions]" if k == "only" else ""))
        if "exclude" in rl and not isinstance(rl["exclude"], list):
            raise PackError(f"{p}: rule exclude: must be a list of action ids, got {rl['exclude']!r}")
    from .plausible import check_spec
    bad = check_spec(raw.get("plausible"), reads)
    if bad:
        raise PackError(f"{p}: {bad}")
    tests = raw.get("tests") or []
    if not tests and not _allow_no_tests:
        raise PackError(f"{p}: a pack without tests is refused; add at least one frame under 'tests'")
    for t in tests:
        if ("frame" not in t and "state" not in t) or "expect" not in t:
            raise PackError(f"{p}: every test needs 'frame' (a screenshot) or 'state' (a JSON file), and 'expect'")
        for key in ("frame", "state"):
            if key in t and not _allow_no_tests and not (p.parent / t[key]).exists():
                raise PackError(f"{p}: test {key} not found: {t[key]}")
    modes: dict[str, Pack] = {}
    for mn, m in (raw.get("modes") or {}).items():
        if not isinstance(m, dict) or not m.get("when"):
            raise PackError(f"{p}: mode '{mn}' needs 'when' ({{read, equals|in|not}} or {{fingerprint}})")
        merged = merge_mode(raw, m)
        merged["game"] = f"{raw['game']}/{mn}"
        mp = load_pack_text(dump_pack(merged), f"{raw['game']}/{mn}")
        mp.raw["when"] = m["when"]
        mp.raw["own_reads"] = list((m.get("read") or {}).keys())
        modes[mn] = mp
    tasks = check_tasks(raw.get("tasks"), reads, str(p), zones=zones)
    fingerprints = dict(raw.get("fingerprints") or {})
    for mn, m in (raw.get("modes") or {}).items():
        if isinstance(m.get("when"), dict) and m["when"].get("fingerprint"):
            fingerprints[mn] = m["when"]["fingerprint"]
    return Pack(
        name=raw["game"], path=p, orientation=screen.get("orientation", "portrait"), size=(int(size[0]), int(size[1])),
        zones=zones, reads=reads, actions=actions, tick_hz=float(raw.get("tick_hz", 3)), play=(raw.get("play") or "").strip(),
        questions=questions, rules=rules, tests=tests, raw=raw, modes=modes, fingerprints=fingerprints, tasks=tasks,
    )
