"""Game packs: one YAML that says what is on the screen, how to read it, what the moves are, and how to play."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
from .geometry import Rect, Zone

READ_KINDS = {"bar", "templates", "ocr", "vocab", "blobs", "color", "locate", "runs", "around", "tetris", "json", "json_grid", "predict", "margin"}
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


MODE_KEYS = ("zones", "read", "act", "play", "questions", "rules", "act_when", "stop_when", "settle", "tick_hz", "plausible")
TASK_CATEGORIES = ("navigate", "collect", "score", "survive", "clear", "build", "avoid", "other")


def _cond_ok(c: Any) -> bool:
    return isinstance(c, dict) and "read" in c and any(k in c for k in ("equals", "in", "not", "gte", "lte"))


def check_tasks(tasks: Any, reads: dict[str, Any], where: str = "pack") -> list[dict[str, Any]]:
    """Tasks are goals the runtime can verify from the reads: `done` (one condition or a list that must all hold)
    marks completion once it has held `hold_ticks` ticks; `when` says when the task is available; `limit_ticks`
    bounds the attempt. Returns the tasks with their defaults filled, or raises PackError."""
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
        for c in conds + ([t["when"]] if t.get("when") else []):
            if not _cond_ok(c):
                raise PackError(f"{where}: task '{tid}': a condition is {{read: <id or id.path>, equals|in|not|gte|lte: v}}")
            if str(c["read"]).split(".")[0] not in reads:
                raise PackError(f"{where}: task '{tid}': unknown read '{c['read']}'")
        cat = str(t.get("category") or "other")
        out.append({**t, "id": tid, "done": conds, "hold_ticks": int(t.get("hold_ticks", 1)), "limit_ticks": int(t.get("limit_ticks", 150)),
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
        elif r.get("kind") == "tetris":
            if r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': tetris needs 'in' (the board grid read), optionally next_in (the preview grid read)")
        elif r.get("kind") == "around":
            if r.get("of") not in reads or r.get("in") not in reads:
                raise PackError(f"{p}: read '{rid}': around needs 'of' (a locate read id) and 'in' (a grid read id)")
        elif r.get("kind") == "margin":
            if r.get("of") not in reads or ("in" in r and r["in"] not in reads) or ("in" not in r and "lower" not in r and "upper" not in r):
                raise PackError(f"{p}: read '{rid}': margin needs 'of' (a locate read) and 'in' (a grid read), or 'of' (a number read) with lower and/or upper")
        elif r.get("kind") == "predict":
            if r.get("of") not in reads or not reads[r["of"]].get("history"):
                raise PackError(f"{p}: read '{rid}': predict needs 'of' (a locate read with history: 1)")
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
    for rl in rules:
        cond = rl.get("if") or {}
        ok_noul = "noul" in cond and any(k in cond for k in ("gte", "lte"))
        ok_read = "read" in cond and any(k in cond for k in ("equals", "in", "not", "gte", "lte"))
        if not (ok_noul or ok_read):
            raise PackError(f"{p}: rule needs if: {{noul, gte|lte}} or if: {{read, equals|in|not|gte|lte}}")
        if not any(k in rl for k in ("exclude", "set", "avoid", "only")):
            raise PackError(f"{p}: rule needs 'exclude: [actions]', 'set: {{param_question: from_question}}', 'avoid: {{param_question: read}}' or 'only: {{param_question: read}}'")
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
    tasks = check_tasks(raw.get("tasks"), reads, str(p))
    fingerprints = dict(raw.get("fingerprints") or {})
    for mn, m in (raw.get("modes") or {}).items():
        if isinstance(m.get("when"), dict) and m["when"].get("fingerprint"):
            fingerprints[mn] = m["when"]["fingerprint"]
    return Pack(
        name=raw["game"], path=p, orientation=screen.get("orientation", "portrait"), size=(int(size[0]), int(size[1])),
        zones=zones, reads=reads, actions=actions, tick_hz=float(raw.get("tick_hz", 3)), play=(raw.get("play") or "").strip(),
        questions=questions, rules=rules, tests=tests, raw=raw, modes=modes, fingerprints=fingerprints, tasks=tasks,
    )
