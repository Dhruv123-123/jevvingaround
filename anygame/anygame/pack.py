"""Game packs: one YAML that says what is on the screen, how to read it, what the moves are, and how to play."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
from .geometry import Rect, Zone

READ_KINDS = {"bar", "templates", "ocr", "vocab", "blobs", "color"}
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
    tests: list[dict[str, Any]]
    raw: dict[str, Any]

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


def load_pack(path: str | os.PathLike) -> Pack:
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
    for name, z in (raw.get("zones") or {}).items():
        grid = tuple(z["grid"]) if z.get("grid") else None
        zones[name] = Zone(name, Rect.parse(z["rect"]), grid)
    reads = raw.get("read") or {}
    for rid, r in reads.items():
        if r.get("kind") not in READ_KINDS:
            raise PackError(f"{p}: read '{rid}': kind must be one of {sorted(READ_KINDS)}")
        if "zone" in r and r["zone"] not in zones:
            raise PackError(f"{p}: read '{rid}': unknown zone '{r['zone']}'")
        if "zone" not in r and "rect" not in r:
            raise PackError(f"{p}: read '{rid}': needs zone or rect")
    actions: list[Action] = []
    for a in raw.get("act") or []:
        if "id" not in a:
            raise PackError(f"{p}: every action needs an id")
        kind = a.get("kind") or ("wait" if a["id"] == "wait" else "tap")
        actions.append(Action(a["id"], kind, {k: v for k, v in a.items() if k not in ("id", "kind")}))
    if not actions:
        raise PackError(f"{p}: 'act' must list at least one action")
    questions = raw.get("questions") or []
    for q in questions:
        if q.get("type") not in QUESTION_TYPES or "id" not in q or "instructions" not in q:
            raise PackError(f"{p}: question {q.get('id')}: needs id, type (noul|choice|score), instructions")
    tests = raw.get("tests") or []
    if not tests:
        raise PackError(f"{p}: a pack without tests is refused; add at least one frame under 'tests'")
    for t in tests:
        if "frame" not in t or "expect" not in t:
            raise PackError(f"{p}: every test needs 'frame' and 'expect'")
        if not (p.parent / t["frame"]).exists():
            raise PackError(f"{p}: test frame not found: {t['frame']}")
    return Pack(
        name=raw["game"], path=p, orientation=screen.get("orientation", "portrait"), size=(int(size[0]), int(size[1])),
        zones=zones, reads=reads, actions=actions, tick_hz=float(raw.get("tick_hz", 3)), play=(raw.get("play") or "").strip(),
        questions=questions, tests=tests, raw=raw,
    )
