"""The play loop: frame → reads → state → Jev → action → device, at tick_hz. One audit line per tick."""
from __future__ import annotations
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from .device.base import Device
from .geometry import Zone
from .jev import Jev
from .pack import Action, Pack
from .perceive import read_all, around_of, margin_of, margin_num
from .fingerprint import Index as FpIndex, fingerprint, to_b64
from .pack import dump_pack, load_pack_text
from .plausible import violations


def copy_answers(answers: dict[str, Any]) -> dict[str, Any]:
    import copy
    return copy.deepcopy(answers)


def _get(values: dict[str, Any], path: str) -> Any:
    """values['head_around.ahead'] style lookup: dotted path into nested dicts."""
    cur: Any = values
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _predict(cur: Any, prev: Any, steps: int = 1) -> str | None:
    """c<col>r<row> moved by (cur - prev) * steps; None when either is missing or not a cell."""
    import re as _re
    m1 = _re.fullmatch(r"c(\d+)r(\d+)", str(cur or "")); m0 = _re.fullmatch(r"c(\d+)r(\d+)", str(prev or ""))
    if not m1 or not m0:
        return None
    c1, r1, c0, r0 = int(m1.group(1)), int(m1.group(2)), int(m0.group(1)), int(m0.group(2))
    return f"c{c1 + (c1 - c0) * steps}r{r1 + (r1 - r0) * steps}"


def _direction(prev: str, cur: str) -> str:
    """'c3r5' → 'c3r4' is 'up'. Works on c<n>r<m> cell names; anything else is 'none'."""
    import re
    m0, m1 = re.match(r"c(\d+)r(\d+)", prev or ""), re.match(r"c(\d+)r(\d+)", cur or "")
    if not m0 or not m1:
        return "none"
    dc, dr = int(m1.group(1)) - int(m0.group(1)), int(m1.group(2)) - int(m0.group(2))
    if abs(dc) > abs(dr):
        return "right" if dc > 0 else "left"
    if dr:
        return "down" if dr > 0 else "up"
    return "none"


def stable_hash(v: Any) -> str:
    return hashlib.sha1(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


class Agent:
    def __init__(self, pack: Pack, device: Device, jev: Jev | None, hud=None, log_path: str | None = None, max_ticks: int | None = None, record_dir: str | None = None,
                 background: bool = True):
        self.pack, self.device, self.jev, self.hud = pack, device, jev, hud
        self.max_ticks = max_ticks
        self.record_dir = Path(record_dir) if record_dir else None
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
        self.errors = 0
        self.history: list[dict[str, Any]] = []
        self.log = open(log_path, "w") if log_path else None
        self.settling = 0
        self.last_answers: dict[str, Any] | None = None
        self.trackers: dict[str, Any] = {}
        self.pressed_at: dict[str, float] = {}      # action id → when its key last went down (for again_ms)
        self.locked: tuple[str, float] | None = None   # (action id, until): no other key before then (lock_ms)
        if hasattr(device, "use_pack"):
            device.use_pack(pack.raw, str(pack.path.parent))    # an emulator's RAM map, clock and discovery come from the pack
        # the long-horizon layer: world memory survives mode changes (a dialogue, a battle), goals are sticky
        self.worlds: dict[str, Any] = {}
        self.goals_done: set[str] = set()
        self.quest: dict[str, Any] | None = None       # the current goal
        self.goal_log: list[dict[str, Any]] = []       # {id, tick, frames}: when each goal was reached
        self.remembered: dict[str, list[str]] = {}    # `remember:` reads → their last distinct values (what was said)
        self.last_fp = None
        self.auto_ticks = 0                            # ticks a routine screen was handled by an auto rule, no decider
        # run memory (dialogue with where it was said, places), goals written from it, and the per-decision audit of
        # the decider against the top-ranked pick (anygame/memory.py, goals.py, audit.py): set up by the caller
        self.memory = None
        self.goalbook = None
        self.auditor = None
        if pack.raw.get("goals_from") == "dialogue":
            from .memory import RunMemory
            from .goals import GoalBook
            self.memory = RunMemory()
            self.goalbook = GoalBook(self.memory, None, pack.raw.get("goals_cfg"))
        if pack.raw.get("frames") == "stream" and hasattr(device, "stream"):
            device.stream()             # frames from the browser's screencast: ~10 ms a frame instead of a 40 ms screenshot
        # the hybrid: which screen is this, does the pack understand it, and who decides when it does not
        self.base = pack
        self.mode = "main"
        self.fps = FpIndex()
        self.fallback = None
        self.goal = ""
        self.miss_ticks = 0
        self.fallback_calls = 0
        self.on_pack_change = None
        self.on_record = None            # (rec, frame) after every tick: the learning loop keeps the decisions and their frames
        self.last_support = 1.0
        # tasks: goals with a verifier over the reads; the active one goes to the decider as `task`, and its
        # completion or failure is an event the learning loop banks (a success span) and scores (per category)
        self.task: dict[str, Any] | None = None
        self.task_started = 0
        self.task_held = 0
        self.task_log: list[dict[str, Any]] = []       # this run's task events: {id, category, outcome, ticks, tick}
        self.task_order: list[str] | None = None       # a setter's preference (ids first to try); pack order otherwise
        self.on_task = None                            # (event) when a task completes or fails
        self.sensor_ewma_ms = 0.0        # what the decider has been taking lately: the per-tick budget is judged against it
        self.budget_skips = 0            # consecutive ticks the decider was skipped for the budget
        self.skipped_budget = 0          # over the run
        self.skipped_reflex = 0          # ticks the pack's reflex condition acted on the last answers without the decider
        self.inflight = None             # ask: async — the decider call running beside the loop, if any
        self.asked_async = 0             # calls started that way, over the run
        self.ask_pool = None
        self._load_fingerprints()
        # slow reads (OCR, detectors) run in a forked worker process: a thread starves next to onnxruntime and
        # the browser, a process does not, and the loop only ever waits on the first value
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        # background=False (eval, the author's check): every read runs on every frame, so a test never sees a slow read's null
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("fork")) if background and any(int(r.get("every", 1)) > 1 for r in self.pack.reads.values()) else None
        self.pending: dict[str, Any] = {}
        if self.pool is not None:
            # warm the worker (fork + OCR model load, ~2 s) before the first tick, so a real-time game does not run
            # unattended while the first slow read blocks
            import numpy as _np
            from .perceive import _read_one
            slow = next(rid for rid, r in self.pack.reads.items() if int(r.get("every", 1)) > 1)
            try:
                self.pool.submit(_read_one, self.pack, _np.zeros((self.pack.size[1], self.pack.size[0], 3), _np.uint8), slow, 1).result(timeout=60)
            except Exception:  # noqa: BLE001
                pass
        self.tick = 0
        self.total_cost = 0.0
        self.last_hash = None
        self.last_values: dict[str, Any] | None = None
        self.noops: list[str] = []           # executed actions ("drop→c4", "up") that changed nothing since the last change
        self.prev_distinct: dict[str, Any] = {}   # last value of each history read that differed from the current one
        self.accepted: dict[str, Any] | None = None   # the last reading that passed the pack's plausibility checks
        self.implausible_ticks = 0           # consecutive ticks whose reads broke a check even after re-reading
        self.implausible_total = 0
        self.rereads = 0                     # fresh frames taken because a reading broke a check

    # ---- questions -------------------------------------------------------------------------------
    def questions(self, values: dict[str, Any]) -> dict[str, dict]:
        qs: dict[str, dict] = {}
        for q in self.pack.questions:
            qs[q["id"]] = {"type": q["type"], "instructions": q["instructions"], "criteria": q["criteria"]}
            # `criteria_from: <read>`: a compiled read that ranks and annotates the options replaces the fixed ones
            # (2048's swipes, best first, each with its consequences; a swipe that would not move is not offered)
            ranked = _get(values, q["criteria_from"]) if q.get("criteria_from") else None
            if isinstance(ranked, dict) and ranked:
                qs[q["id"]]["criteria"] = dict(ranked)
        if "action" not in qs:
            qs["action"] = {"type": "choice", "instructions": "Which action now? Follow the play notes in the state.",
                            "criteria": {a.id: (a.params.get("description") or None) for a in self.pack.actions}}
        # System 0: an action that changed nothing is not offered again until the screen changes.
        # A parameterised action ("drop→c4") loses that parameter value; the bare action stays if other values remain.
        crit = qs["action"]["criteria"]
        bare = {n for n in self.noops if "→" not in n}
        left = {k: v for k, v in crit.items() if k not in bare}
        if 1 <= len(left) < len(crit):
            qs["action"] = {**qs["action"], "criteria": left}
        # parameter questions for actions that need a slot and/or a target cell; all asked in the same call.
        # A pack may define its own `<action>__cell` / `__slot` / `__target` question to add instructions.
        for a in self.pack.actions:
            if a.kind == "play":
                slot_read = a.params.get("slot")            # e.g. "hand" → the templates read named hand
                hand = values.get(slot_read) if slot_read else None
                if isinstance(hand, dict):
                    opts = {f"{k}:{v}": None for k, v in hand.items() if v}
                    if opts:
                        qs[f"{a.id}__slot"] = {"type": "choice", "instructions": f"If the action is {a.id}, which slot (slot:card) to use?", "criteria": opts}
                target_zone = a.params.get("target")
                if target_zone:
                    cells = self.pack.zone(target_zone).cells()
                    qs[f"{a.id}__target"] = {"type": "choice", "instructions": f"If the action is {a.id}, which cell of {target_zone} to target? Cells are c<col>r<row>; row 1 is the top of the zone.",
                                             "criteria": {k.split('.', 1)[1]: None for k in list(cells)[:255]}}
            if a.kind == "macro":
                opts = _get(values, a.params["options"]) or {}
                landings = opts.get("landings") if isinstance(opts, dict) else None
                if landings:
                    qs[f"{a.id}__option"] = {"type": "choice", "instructions": f"If the action is {a.id}, which option? Each is a computed landing with its consequences.",
                                             "criteria": dict(landings)}
            if a.kind == "tap" and a.params.get("zone") and self.pack.zone(a.params["zone"]).grid and f"{a.id}__cell" not in qs:
                cells = self.pack.zone(a.params["zone"]).cells()
                qs[f"{a.id}__cell"] = {"type": "choice", "instructions": f"If the action is {a.id}, which cell of {a.params['zone']}?", "criteria": {k.split('.', 1)[1]: None for k in list(cells)[:255]}}
        # after the parameter questions exist: a tap on a cell of a grid zone is asked through a question built just
        # above, and a refused move (a Go ko, a full column) must leave it too, or the model picks it again every tick
        for n in self.noops:
            if "→" not in n:
                continue
            aid, val = n.split("→", 1)
            for pq in (f"{aid}__cell", f"{aid}__target", f"{aid}__slot", f"{aid}__option"):
                if pq in qs:
                    c = {k: v for k, v in qs[pq]["criteria"].items() if k != val}
                    if c:
                        qs[pq] = {**qs[pq], "criteria": c}
                    elif pq.endswith("__option") and len(qs["action"]["criteria"]) > 1:
                        # every option of this action changed nothing: the action itself is not offered until the
                        # screen changes (a title screen where walking does nothing and only a button will)
                        qs["action"] = {**qs["action"], "criteria": {k: v for k, v in qs["action"]["criteria"].items() if k != aid}}
        for rl in self.pack.rules:
            for pq, read in (rl.get("only") or {}).items():
                cells = _get(values, read) or []
                cells = cells if isinstance(cells, list) else [cells]
                if pq in qs:
                    keep = {k: v for k, v in qs[pq]["criteria"].items() if any(str(x) == k or str(x).startswith(k + "r") for x in cells)}
                    if keep:
                        qs[pq] = {**qs[pq], "criteria": keep}
            for pq, read in (rl.get("avoid") or {}).items():
                cells = _get(values, read) or []
                cells = cells if isinstance(cells, list) else [cells]
                if pq in qs:
                    keep = {k: v for k, v in qs[pq]["criteria"].items() if not any(str(x) == k or str(x).startswith(k + "r") for x in cells)}
                    if keep and len(keep) < len(qs[pq]["criteria"]):
                        qs[pq] = {**qs[pq], "criteria": keep}
        return qs

    # ---- acting ----------------------------------------------------------------------------------
    def _center(self, zone_or_cell: str) -> tuple[int, int]:
        w, h = self.device.size()
        if "." in zone_or_cell and zone_or_cell.split(".", 1)[0] in self.pack.zones:
            zname, cell = zone_or_cell.split(".", 1)
            r = self.pack.zone(zname).cells()[zone_or_cell]
        else:
            r = self.pack.zone(zone_or_cell).rect
        cx, cy = r.center()
        return int(cx * w), int(cy * h)

    def act(self, a: Action, answers: dict[str, Any]) -> str:
        w, h = self.device.size()
        p = a.params
        if a.kind == "wait":
            return "wait"
        if a.kind == "key":
            now = time.perf_counter()
            if self.locked and self.locked[0] != a.id and now < self.locked[1]:
                # another key went down a moment ago and the screen may not show it yet: a dino one frame after its
                # jump key still reads as on the ground, and a duck pressed then is a fast drop out of the jump
                return f"wait: {self.locked[0]} locks keys for {round((self.locked[1] - now) * 1000)} ms"
            again = p.get("again_ms")
            if again:
                # not pressed again this soon: at a high frame rate the screen may not show the last press yet (a
                # dino still on the ground one frame after its jump key), and a second press would cut the first short
                last = self.pressed_at.get(a.id)
                if last is not None and now - last < float(again) / 1000:
                    return f"wait: {a.id} pressed {round((now - last) * 1000)} ms ago"
                self.pressed_at[a.id] = now
            if p.get("lock_ms"):
                self.locked = (a.id, now + float(p["lock_ms"]) / 1000)
            hold = int(p.get("hold_ms", 0) or 0)
            if hold and p.get("release") == "later":
                # held without stopping the loop: let go on the first frame after hold_ms (a device that cannot
                # do that holds it in place)
                try:
                    if p.get("repeat") == "hold":      # pressed again while held: keep holding
                        self.device.key(p["key"], hold, block=False, extend=True)
                    else:
                        self.device.key(p["key"], hold, block=False)
                    return f"key {p['key']} down, up after {hold} ms"
                except TypeError:
                    pass
            if hold:
                self.device.key(p["key"], hold)
                return f"key {p['key']} held {hold} ms"
            self.device.key(p["key"])
            return f"key {p['key']}"
        if a.kind == "chunk":
            # a short input sequence as one decision (what a demonstration's recurring key runs become)
            keys = [str(k) for k in (p.get("keys") or [])]
            hold = int(p.get("hold_ms", 0) or 0)
            for k in keys:
                self.device.key(k, hold) if hold else self.device.key(k)
                time.sleep(float(p.get("key_ms", 40)) / 1000)
            return f"chunk {' '.join(keys)}"
        if a.kind == "mouse_move":
            try:
                self.device.mouse_move(int(p.get("dx", 0)), int(p.get("dy", 0)))
            except NotImplementedError as e:
                return f"mouse_move unsupported: {e}"
            return f"mouse_move {p.get('dx', 0)},{p.get('dy', 0)}"
        if a.kind == "macro":
            label = answers.get(f"{a.id}__option", {}).get("choice")
            tracker = self.trackers.get(p["options"].split(".")[0])
            if tracker is not None and label and hasattr(tracker, "run"):
                # the tracker plays its own plan, one step at a time, looking after each (a path through a world)
                probe = next((r for r in self.pack.reads.values() if r.get("kind") == "probe"), None)
                classify = (lambda: self._probe(probe)) if probe is not None else None
                return tracker.run(self.device, label, self._look, classify=classify)
            keys = tracker.macros.get(label) if (tracker and label) else None
            if not keys:
                return f"{a.id} (no option)"
            for k in keys:
                self.device.key(k)
                time.sleep(float(p.get("key_ms", 40)) / 1000)
            tracker.predict(label)
            return f"{a.id} {label}: {' '.join(keys)}"
        if a.kind == "tap":
            cell = answers.get(f"{a.id}__cell", {}).get("choice") if f"{a.id}__cell" in answers else None
            x, y = self._center(f"{p['zone']}.{cell}" if cell else p.get("zone") or p["at"]) if (cell or "zone" in p) else (int(p["at"][0] * w), int(p["at"][1] * h))
            self.device.tap(x, y)
            return f"tap {p.get('zone', '')}{'.' + cell if cell else ''} ({x},{y})"
        if a.kind == "swipe":
            zone = self.pack.zone(p["zone"]) if "zone" in p else None
            r = zone.rect if zone else None
            cx, cy = r.center() if r else (0.5, 0.5)
            d = float(p.get("distance", 0.3))
            dx, dy = {"up": (0, -d), "down": (0, d), "left": (-d, 0), "right": (d, 0)}[p["dir"]]
            x0, y0, x1, y1 = int(cx * w), int(cy * h), int((cx + dx) * w), int((cy + dy) * h)
            self.device.swipe(x0, y0, x1, y1, int(p.get("ms", 120)))
            return f"swipe {p['dir']}"
        if a.kind == "play":
            slot = answers.get(f"{a.id}__slot", {}).get("choice")
            target = answers.get(f"{a.id}__target", {}).get("choice")
            if not slot or not target:
                return "play (no slot/target)"
            slot_cell = slot.split(":", 1)[0]
            sx, sy = self._center(f"{p['slot']}.{slot_cell}")
            tx, ty = self._center(f"{p['target']}.{target}")
            if p.get("gesture", "tap-tap") == "drag":
                self.device.swipe(sx, sy, tx, ty, int(p.get("ms", 250)))
            else:
                self.device.tap(sx, sy)
                time.sleep(float(p.get("pause", 0.15)))
                self.device.tap(tx, ty)
            return f"play {slot} → {target}"
        return f"unknown kind {a.kind}"

    # ---- the hybrid ------------------------------------------------------------------------------
    def _load_fingerprints(self) -> None:
        self.fps = FpIndex()
        for name, b64 in self.base.fingerprints.items():
            try:
                self.fps.add(name, b64)
            except Exception:  # noqa: BLE001
                pass

    def swap_pack(self, pack) -> None:
        """Replace the pack while playing: the paragraph is the weights, and now the reads and modes are too."""
        self.base = pack
        self.pack = pack.modes[self.mode] if self.mode != "main" and self.mode in pack.modes else pack
        self.trackers = {}
        self.last_answers = None
        self._load_fingerprints()

    def classify(self, base_values: dict[str, Any], fp) -> tuple[str, str | None]:
        for name, m in self.base.modes.items():
            w = m.raw.get("when") or {}
            if "read" in w and self._cond(w, base_values):
                return name, name
        k = self.fps.known(fp)
        if k:
            return (k[0] if k[0] in self.base.modes else "main"), k[0]
        return "main", None

    def support(self, conf: dict[str, float], values: dict[str, Any], pack=None) -> float:
        pack = pack or self.pack
        c = dict(conf)
        for rid, r in pack.reads.items():
            if r.get("kind") == "tetris" and isinstance(values.get(rid), dict):
                c[rid] = 0.4 if values[rid].get("phase") == "none" else 1.0
        own = pack.raw.get("own_reads") or []
        if own and any(k in c for k in own):
            c = {k: v for k, v in c.items() if k in own}
        return sum(c.values()) / len(c) if c else 1.0

    def act_fallback(self, now: dict[str, Any]) -> str:
        if now.get("action"):
            a = next((x for x in self.pack.actions if x.id == now["action"]), None) or next((x for x in self.base.actions if x.id == now["action"]), None)
            if a:
                answers = {f"{a.id}__cell": {"type": "choice", "choice": now["cell"]}} if now.get("cell") else {}
                return "fallback " + self.act(a, answers)
        if now.get("kind") == "key" and now.get("key"):
            self.device.key(now["key"])
            return f"fallback key {now['key']}"
        if now.get("kind") == "tap" and now.get("at"):
            x, y = int(now["at"][0]), int(now["at"][1])
            self.device.tap(x, y)
            return f"fallback tap ({x},{y})"
        return "fallback wait"

    def merge_mode(self, name: str, mode: dict[str, Any], expect: dict[str, Any], frame, fp) -> bool:
        """A mode the VLM defined becomes part of the pack only if its reads return what it said they would on this frame."""
        import copy
        try:
            raw = copy.deepcopy(self.base.raw)
            raw["modes"] = {**(raw.get("modes") or {}), name: {**mode, "when": {"fingerprint": to_b64(fp)}}}
            cand = load_pack_text(dump_pack(raw), f"{self.base.name}+{name}")
            mp = cand.modes[name]
            probe = Agent(mp, self.device, None)
            values, conf = probe.observe(frame, mp, want_conf=True, state=getattr(self, "last_state", None))[0], probe.last_conf
            misses = [(k, v, values.get(k)) for k, v in expect.items() if json.dumps(values.get(k), sort_keys=True, default=str) != json.dumps(v, sort_keys=True, default=str)]
            sup = probe.support(conf, values, mp)
            if misses or sup < float(self.base.raw.get("support_threshold", 0.7)):
                why = "; ".join(f"{k} expected {v!r} got {g!r}" for k, v, g in misses) or f"support {sup:.2f}"
                if self.on_pack_change:
                    self.on_pack_change(dump_pack(self.base.raw), f"mode {name} rejected: {why}")
                return False
            self.swap_pack(cand)
            if self.on_pack_change:
                self.on_pack_change(dump_pack(cand.raw), f"learned mode {name}")
            return True
        except Exception as e:  # noqa: BLE001
            if self.on_pack_change:
                self.on_pack_change(dump_pack(self.base.raw), f"mode {name} invalid: {str(e)[:120]}")
            return False

    def observe(self, frame, pack=None, want_conf: bool = False, state: Any = None, wait: bool = False) -> tuple[dict[str, Any], list, dict[str, float]]:
        """Frame → the state the model sees: the pack's reads, presented, plus history (<id>_prev/_moving/_reverse)
        and the derived reads computed here because they need per-run state (around, tetris). `wait`: a still frame,
        so slow reads are waited for instead of left at `otherwise`."""
        pack = pack or self.pack
        t_frame = time.perf_counter()
        conf: dict[str, float] = {}
        values, dets, timings = read_all(pack, frame, tick=self.tick, previous=self.last_values, pool=self.pool, pending=self.pending, conf=conf, state=state, wait=wait)
        self.last_conf = conf
        raw_values = values
        values = self._present(values, pack)
        for rid, r in pack.reads.items():
            if r.get("kind") == "head":
                # the moving end of a body drawn in one colour: the cell that newly took the symbol and has one
                # neighbour of it (a page that draws head and body alike, like most real snakes)
                values[rid] = self._head(rid, raw_values.get(r["in"]), str(r.get("symbol", "s")))
        for rid, r in pack.reads.items():
            if not r.get("history"):
                continue
            cur = values.get(rid)
            if self.last_values is not None and rid in self.last_values and self.last_values[rid] != cur:
                self.prev_distinct[rid] = self.last_values[rid]
            if rid in self.prev_distinct:
                values[f"{rid}_prev"] = self.prev_distinct[rid]
                if r.get("kind") in ("locate", "head") and isinstance(cur, str) and isinstance(self.prev_distinct[rid], str):
                    values[f"{rid}_moving"] = _direction(self.prev_distinct[rid], cur)
                    values[f"{rid}_reverse"] = {"up": "down", "down": "up", "left": "right", "right": "left"}.get(values[f"{rid}_moving"], "none")
        if self.base.raw.get("goals"):
            self._goals_update(values)
        probes = [rid for rid, r in pack.reads.items() if r.get("kind") == "probe"]
        for rid in probes:
            values[rid] = self._probe(pack.reads[rid], values)
        if probes:
            # reads gated on what the probe found (OCR of text only when there is text) are read now
            for rid, r in pack.reads.items():
                w = r.get("when")
                if w and any(c.get("read") in probes for c in (w if isinstance(w, list) else [w])):
                    v, _, _ = read_all(pack, frame, only={rid}, tick=self.tick, state=state, given=values)
                    values[rid] = v.get(rid)
        if self.memory is not None and pack is self.base:
            w = next((t for t in self.worlds.values() if hasattr(t, "tile_of")), None)
            t = w.tile_of(values) if w is not None else None
            placed = {**values, "map": t[0]} if t else values      # the place as the world memory names it
            self.memory.observe(self.tick, getattr(self.device, "frames", None), placed,
                                values.get(self.base.raw.get("dialogue_read", "text")), (t[1], t[2]) if t else None)
            if self.goalbook is not None:
                self.quest = self.goalbook.update(self.tick, placed, w)
        for rid, r in pack.reads.items():
            if r.get("kind") == "menu":
                if rid not in self.worlds:
                    from .perceive.menu import MenuTracker
                    self.worlds[rid] = MenuTracker(r)
                self.trackers[rid] = self.worlds[rid]
                if r.get("when") and not self._task_ok(r["when"], values):
                    self.worlds[rid].see(self.device.screen(), values.get("text"))   # where a choice may lead back to
                    values[rid] = None
                    continue
                pos = [str(x) for x in (r.get("pos") or [])]
                look_pos = (lambda: tuple(_get(self.device.state() or {}, p_) for p_ in pos)) if pos else None
                values[rid] = self.worlds[rid].read(self.device, self.device.screen(), look_pos)
            if r.get("kind") == "world":
                if rid not in self.worlds:
                    from .perceive.world import WorldTracker
                    self.worlds[rid] = WorldTracker(r)
                self.trackers[rid] = self.worlds[rid]
                tgt = dict((self.quest or {}).get("target") or {}) or None
                if tgt is not None:
                    tgt.setdefault("label", self.quest["id"])
                values[rid] = self.worlds[rid].read(values, tgt)
        for rid, r in pack.reads.items():
            if r.get("kind") == "predict":
                # where a located thing will be when the action lands: its cell shifted by its last displacement,
                # `steps` ticks ahead (the Smith predictor's idea, one cell at a time); null until it has moved
                values[rid] = _predict(values.get(r["of"]), values.get(f"{r['of']}_prev"), int(r.get("steps", 1)))
            if r.get("kind") == "around":
                values[rid] = around_of(values.get(r["of"]), raw_values.get(r["in"]), values.get(f"{r['of']}_moving"), r)
            elif r.get("kind") == "margin":
                # the barrier after each move with the decision latency compensated (a discrete control barrier function)
                values[rid] = margin_of(values.get(r["of"]), raw_values.get(r["in"]), r) if "in" in r else margin_num(values.get(r["of"]), r)
            elif r.get("kind") == "gap":
                # distance to the next obstacle in a runner, its closing speed and time to contact
                if rid not in self.trackers:
                    from .perceive import GapTracker
                    self.trackers[rid] = GapTracker(r)
                values[rid] = self.trackers[rid].read(raw_values.get(r["in"]), t_frame)
            elif r.get("kind") == "tetris":
                if rid not in self.trackers:
                    from .perceive.tetris import TetrisTracker
                    self.trackers[rid] = TetrisTracker(r)
                values[rid] = self.trackers[rid].read(raw_values.get(r["in"]), raw_values.get(r["next_in"]) if r.get("next_in") else None)
            elif r.get("kind") == "slide":
                from .perceive.slide import slide_of
                values[rid] = slide_of(raw_values.get(r["in"]), r)
        return values, dets, timings

    def _head(self, rid: str, grid: Any, sym: str) -> str | None:
        import re as _re
        if not isinstance(grid, dict):
            return None
        cells = {(int(m.group(1)), int(m.group(2))) for k, v in grid.items() if str(v) == sym and (m := _re.match(r"c(\d+)r(\d+)$", k))}
        prev_cells, prev_head = self.trackers.get(rid, (None, None))
        head = prev_head
        if prev_cells is not None:
            new = cells - prev_cells
            ends = [c for c in new if sum((c[0] + dc, c[1] + dr) in cells for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))) <= 1]
            if len(ends) == 1:
                head = ends[0]
            elif len(new) == 1:
                head = next(iter(new))
            elif len(ends) > 1 and prev_head is not None:
                # it moved its whole length since the last look: the head is the end farther from where it was
                head = max(ends, key=lambda c: abs(c[0] - prev_head[0]) + abs(c[1] - prev_head[1]))
        if head is not None and head not in cells:
            head = None
        self.trackers[rid] = (cells, head)
        return f"c{head[0]}r{head[1]}" if head else None

    # ---- one tick --------------------------------------------------------------------------------
    def step(self) -> dict[str, Any]:
        self.tick += 1
        t0 = time.perf_counter()
        if self.hud is not None and hasattr(self.hud, "take_edits"):
            edit = self.hud.take_edits()
            if edit:
                # the paragraph is the weights: swap it live, no restart
                self.pack.play = edit["play"] or self.pack.play
                self.pack.rules = edit["rules"]
                self.last_answers = None
        frame = self.device.frame()
        state = self.device.state() if hasattr(self.device, "state") else None   # a game that tells us its state
        self.last_state = state
        fp = fingerprint(frame)
        values, dets, timings = self.observe(frame, self.base, state=state)
        cls_mode, known = self.classify(values, fp)
        if cls_mode != self.mode:
            self.mode, self.trackers, self.last_answers, self.noops = cls_mode, {}, None, []
        self.pack = self.base if self.mode == "main" else self.base.modes[self.mode]
        if self.mode != "main":
            values, dets, timings = self.observe(frame, self.pack, state=state)
        support = self.support(self.last_conf, values, self.pack)
        self.last_support = support
        supported = support >= float(self.base.raw.get("support_threshold", 0.7))
        if supported and not known:
            self.fps.add(self.mode, fp)          # a screen the pack reads well is a known screen from now on
        t_perc = (time.perf_counter() - t0) * 1000
        h = stable_hash({k: v for k, v in values.items() if not k.endswith("_prev")})
        changed = h != self.last_hash
        if self.pack.raw.get("change") == "screen" and self.last_fp is not None:
            # the reads do not see everything (a title screen, a menu): a frame that looks different is a change too
            from .fingerprint import distance as _fpd
            changed = changed or _fpd(fp, self.last_fp) > float(self.pack.raw.get("change_min", 3))
        self.last_fp = fp
        if changed:
            self.noops = []
        elif self.history and self.history[-1].get("key") and self.history[-1]["key"] not in self.noops:
            self.noops.append(self.history[-1]["key"])
        state = {"game": self.pack.name, "tick": self.tick, "how_to_play": self.pack.play, "screen": values,
                 "recent_actions": [h_["action"] for h_ in self.history[-6:]],
                 "last_action_changed_screen": changed if self.history else None,
                 "actions_that_did_nothing_since_last_change": list(self.noops)}
        self.last_values = values
        rec: dict[str, Any] = {"tick": self.tick, "t": round(t0, 3), "hash": h, "perception_ms": round(t_perc), "timings_ms": timings, "screen": values,
                               "mode": self.mode, "support": round(support, 2), "known": known}
        if self.last_state is not None and os.environ.get("ANYGAME_LOG_TRUTH"):
            rec["truth"] = self.last_state   # the page's own state beside the pixel reads, to check perception offline
        for rid in self.base.raw.get("remember") or []:
            # what the game said: the last few distinct readings of a text read, a line typed out letter by letter
            # kept once (the longer reading replaces the prefix it grew from)
            v = values.get(rid)
            mem = self.remembered.setdefault(rid, [])
            if isinstance(v, str) and v.strip():
                v = v.strip()
                if mem and (v.startswith(mem[-1]) or mem[-1].startswith(v)):
                    mem[-1] = max(v, mem[-1], key=len)
                elif v not in mem[-3:]:
                    mem.append(v)
                del mem[: -int(self.base.raw.get("remember_lines", 6))]
            if mem:
                state[f"recent_{rid}"] = list(mem)
        if self.quest is not None:
            state["goal"] = self.quest["instruction"]
            rec["goal"] = self.quest["id"]
        if self.mode == "main" and self.base.tasks:
            self._tasks_tick(values, rec)
            if self.task is not None:
                state["task"] = self.task["instruction"]
        if getattr(self.device, "paused", False):
            # a person is using the keyboard or mouse: read, show, do not act
            rec["action"] = "wait"
            rec["reason"] = "paused: a person is using the input"
            rec["guard"] = self.device.guard_status() if hasattr(self.device, "guard_status") else {"paused": True}
            self.last_hash = h
            self._emit(rec, frame, dets, None)
            return rec
        # the hybrid: a screen the pack cannot read goes to the VLM, which acts now and may define a mode
        if not supported and not known:
            self.miss_ticks += 1
            if self.fallback is not None and self.miss_ticks >= int(self.base.raw.get("miss_ticks", 2)):
                d = self.fallback.decide(frame, self.pack, self.goal or self.base.play[:300], [x["action"] for x in self.history[-6:]])
                rec["fallback"] = f"{'memo' if d.get('memo') else 'vlm'} {d['screen']}{' ' + d['name'] if d.get('name') else ''}: {json.dumps(d['now'])}{' — ' + d['note'] if d.get('note') else ''}"
                if not d.get("memo"):
                    self.fallback_calls += 1
                rec["action"] = self.act_fallback(d["now"])
                rec["reason"] = f"unsupported screen (support {rec['support']}) → fallback"
                if d["screen"] == "mode" and d.get("mode") and d.get("name"):
                    self.merge_mode(d["name"], d["mode"], d.get("expect") or {}, frame, fp)
                elif d["screen"] == "transient" and d.get("name"):
                    self.fps.add(f"transient:{d['name']}", fp)
                    self.base.fingerprints[f"transient:{d['name']}"] = to_b64(fp)
                    self.base.raw["fingerprints"] = self.base.fingerprints
                    if self.on_pack_change:
                        self.on_pack_change(dump_pack(self.base.raw), f"learned transient screen {d['name']}")
                self.history.append({"tick": self.tick, "action": rec["action"], "choice": "fallback", "key": "fallback"})
                self.miss_ticks = 0
                self.last_hash = h
                self._emit(rec, frame, dets, None)
                return rec
            if self.fallback is not None:
                rec["action"] = "wait"
                rec["reason"] = f"unsupported screen (support {rec['support']}), {self.miss_ticks} tick(s)"
                self.last_hash = h
                self._emit(rec, frame, dets, None)
                return rec
        else:
            self.miss_ticks = 0
        if known and str(known).startswith("transient:") and self.fallback is not None:
            d = self.fallback.recall(fp)
            if d:
                rec["action"] = self.act_fallback(d["now"])
                rec["fallback"] = f"memo transient: {json.dumps(d['now'])}"
                rec["reason"] = "known transient screen"
                self.last_hash = h
                self._emit(rec, frame, dets, None)
                return rec
        spec = self.pack.raw.get("plausible")
        if spec:
            # a reading that cannot follow the last accepted one is a wrong read, not a move: look again, and if it
            # still does not add up, do nothing on it; if it persists, end the episode with the broken check as the reason
            bad = violations(spec, values, self.accepted, self.pack.reads)
            tries = 0
            while bad and tries < int(self.pack.raw.get("plausible_retries", 2)) and getattr(self.device, "rereadable", True):
                tries += 1
                frame = self.device.frame()
                dstate = self.device.state() if hasattr(self.device, "state") else None
                self.last_state = dstate
                values, dets, timings = self.observe(frame, self.pack, state=dstate)
                bad = violations(spec, values, self.accepted, self.pack.reads)
            if tries:
                self.rereads += tries
                rec["reread"] = tries
                h = stable_hash({k: v for k, v in values.items() if not k.endswith("_prev")})
                changed = h != self.last_hash
                rec["screen"], rec["hash"], state["screen"] = values, h, values
                state["last_action_changed_screen"] = changed if self.history else None
                self.last_values = values
            if bad:
                self.implausible_ticks += 1
                self.implausible_total += 1
                rec["implausible"] = bad
                limit = int(self.pack.raw.get("plausible_ticks", 6))
                if self.implausible_ticks >= limit:
                    rec["action"] = "stop"
                    rec["reason"] = f"stalled: implausible read for {self.implausible_ticks} ticks: {bad[0]}"
                else:
                    rec["action"] = "wait"
                    rec["reason"] = f"implausible read: {bad[0]}"
                self.last_hash = h
                self._emit(rec, frame, dets, None)
                return rec
            self.implausible_ticks = 0
            self.accepted = values
        stop = self.pack.raw.get("stop_when")
        if stop and self._cond(stop, values):
            rec["action"] = "stop"
            rec["reason"] = f"{stop['read']} is {_get(values, stop['read'])}"
            self._emit(rec, frame, dets, None)
            return rec
        for rl in self.base.raw.get("auto") or []:
            if self._task_ok(rl["if"], values):
                # a routine screen (text to page through, a transition): handled without asking the decider
                if "key" in rl:
                    self.device.key(rl["key"], int(rl.get("hold_ms", 0) or 0))
                    rec["action"] = f"auto: key {rl['key']}"
                else:
                    if hasattr(self.device, "wait"):
                        self.device.wait(int(rl["wait"]))
                    else:
                        time.sleep(int(rl["wait"]) / 60)
                    rec["action"] = f"auto: wait {rl['wait']}"
                rec["reason"] = rl.get("why") or "auto: " + ", ".join(f"{c['read']}={_get(values, c['read'])}" for c in (rl["if"] if isinstance(rl["if"], list) else [rl["if"]]))
                self.auto_ticks += 1
                self.last_hash = h
                self.history.append({"tick": self.tick, "action": rec["action"], "choice": "auto", "key": "auto"})
                self._emit(rec, frame, dets, None)
                return rec
        gate = self.pack.raw.get("act_when")
        if gate and not self._cond(gate, values):
            rec["action"] = "wait"
            rec["reason"] = f"{gate['read']} is {_get(values, gate['read'])}"
            self.last_hash = h
            self._emit(rec, frame, dets, None)
            return rec
        if self.jev is None:
            rec["action"] = "wait"
            self._emit(rec, frame, dets, None)
            return rec
        settle = self.pack.raw.get("settle")
        if (settle and not changed and self.history and self.history[-1]["action"] not in ("wait", "keep")
                and self.settling < int(self.pack.raw.get("settle_ticks", 3))):
            # the last action has not shown on screen yet; deciding again now would read a stale state
            self.settling += 1
            rec["action"] = "wait"
            rec["reason"] = f"settling ({self.history[-1]['action']})"
            self._emit(rec, frame, dets, None)
            return rec
        if changed:
            self.settling = 0
        if not changed and self.history and self.history[-1]["action"] == "wait" and getattr(self.device, "clock", "wall") != "game":
            rec["action"] = "wait"
            rec["reason"] = "screen unchanged"
            self.last_hash = h
            self._emit(rec, frame, dets, None)
            return rec
        qs = self.questions(values)
        budget = float(self.pack.raw.get("budget_ms") or 0)
        expected = t_perc + self.sensor_ewma_ms
        reflex = self.pack.raw.get("reflex")
        ask_async = self.pack.raw.get("ask") == "async" and self.pack.rules
        fresh = None
        if ask_async and self.inflight is not None and self.inflight.done():
            # the decider's answer to an earlier frame has come back: it becomes the policy from this frame on
            try:
                fresh = self.inflight.result()
                lat = float(fresh.get("latency_ms") or 0)
                self.sensor_ewma_ms = lat if not self.sensor_ewma_ms else 0.7 * self.sensor_ewma_ms + 0.3 * lat
            except Exception as ex:  # noqa: BLE001
                self.errors += 1
                rec["sensor_error"] = str(ex)[:120]
            self.inflight = None
        if ask_async and self.last_answers and self.inflight is None and fresh is None:
            ask_when = self.pack.raw.get("ask_when")
            if not ask_when or self._task_ok(ask_when, values):
                # ask without waiting: the loop keeps reading frames and acting on the last answers while the call
                # runs (a fast game moves on during a 400 ms call, and a blocked loop sees none of it)
                if self.ask_pool is None:
                    from concurrent.futures import ThreadPoolExecutor
                    self.ask_pool = ThreadPoolExecutor(max_workers=1)
                self.inflight = self.ask_pool.submit(self.jev.ask, state, qs)
                self.asked_async += 1
                rec["asked"] = "async"
        if fresh is not None:
            res = fresh
            e = None
        elif reflex and self.last_answers and self.pack.rules and self._task_ok(reflex, values):
            # a reflex: the fresh frame already needs a move before the decider could answer (Snake, a turn into a
            # wall that needs a second turn on the very next step). The rules act on the decider's last answers, its
            # ranking of the moves, at perception speed; the decider is asked again on the next frame
            import copy
            self.skipped_reflex += 1
            res = {"answers": copy.deepcopy(self.last_answers), "latency_ms": 0, "input_tokens": 0, "cost_usd": 0.0}
            rec["sensor"] = "reflex: " + ", ".join(f"{c['read']}={_get(values, c['read'])}" for c in (reflex if isinstance(reflex, list) else [reflex])) + " → rules on last answers"
            rec["skipped"] = "reflex"
            e = None
        elif ask_async and self.last_answers:
            # no fresh answer this frame: the rules act on the last ones (a call may be running beside the loop)
            import copy
            res = {"answers": copy.deepcopy(self.last_answers), "latency_ms": 0, "input_tokens": 0, "cost_usd": 0.0}
            rec["sensor"] = "async: rules on last answers" + (" (call in flight)" if self.inflight is not None else "")
            rec["skipped"] = "async"
            e = None
        elif (budget and self.last_answers and self.pack.rules and expected > budget
                and self.budget_skips < int(self.pack.raw.get("budget_skip_max", 2))):
            # the tick cannot afford the decider: the rules act on its last answers (the post-posed shield), at most
            # budget_skip_max ticks in a row so a slow decider is never starved out of the loop
            import copy
            self.budget_skips += 1
            self.skipped_budget += 1
            res = {"answers": copy.deepcopy(self.last_answers), "latency_ms": 0, "input_tokens": 0, "cost_usd": 0.0}
            rec["sensor"] = f"budget: skipped the decider (perception {t_perc:.0f} ms + expected {self.sensor_ewma_ms:.0f} ms > {budget:.0f} ms) → rules on last answers"
            rec["skipped"] = "budget"
            e = None
        else:
            e = None
            self.budget_skips = 0
            try:
                res = self.jev.ask(state, qs)
                lat = float(res.get("latency_ms") or 0)
                self.sensor_ewma_ms = lat if not self.sensor_ewma_ms else 0.7 * self.sensor_ewma_ms + 0.3 * lat
            except Exception as ex:  # noqa: BLE001
                e = ex
        if e is not None:  # a failed call costs one tick, not the game
            self.errors += 1
            if self.pack.rules and self.last_answers:
                # the model is late: replay its last answers through the pack's rules so a safe move still goes out
                import copy
                res = {"answers": copy.deepcopy(self.last_answers), "latency_ms": 0, "input_tokens": 0, "cost_usd": 0.0}
                rec["sensor"] = f"error → rules on last answers: {str(e)[:80]}"
            else:
                rec["action"] = "wait"
                rec["reason"] = f"sensor error: {str(e)[:120]}"
                self.last_hash = h
                self._emit(rec, frame, dets, None)
                return rec
        answers = res["answers"]
        if "sensor" not in rec:
            self.last_answers = copy_answers(answers)
        applied = self._apply_rules(answers, values)
        choice = answers.get("action", {}).get("choice", "wait")
        try:
            action = self.pack.action(choice)
        except Exception:
            action = Action("wait", "wait")
        if self.auditor is not None and "sensor" not in rec:
            # Jev's pick against the top-ranked one, both played forward from this moment: did the pick matter
            rec["audit"] = self.auditor.check(self, qs, answers, values)
        done = self.act(action, answers)
        if getattr(self.device, "coach", False):
            done = "suggest: " + done            # coach mode: shown, never performed
        g = self.device.guard_status() if hasattr(self.device, "guard_status") else None
        if g and (g.get("dropped") or g.get("human_events")):
            rec["guard"] = g
        self.total_cost += res["cost_usd"]
        rec.update({"action": done, "choice": choice, "rules": applied, "acted_after_ms": round((time.perf_counter() - t0) * 1000), "action_probs": answers.get("action", {}).get("probabilities"),
                    "nouls": {k: round(v["noul"], 2) for k, v in answers.items() if v.get("type") == "noul"},
                    "choices": {k: v.get("choice") for k, v in answers.items() if v.get("type") == "choice" and k != "action"},
                    "jev_ms": res["latency_ms"], "tokens": res["input_tokens"], "cost_usd": round(res["cost_usd"], 7), "total_cost_usd": round(self.total_cost, 6)})
        # the compiler's top pick next to the decider's, so the decider's contribution can be measured (and replayed
        # from a save state both ways)
        top = {k: next(iter(q["criteria"]), None) for k, q in qs.items() if q.get("type") == "choice" and q.get("criteria")}
        if top and "sensor" not in rec:
            rec["top"] = top
            rec["top_agrees"] = all(answers.get(k, {}).get("choice") == v for k, v in top.items())
            self.top_asked = getattr(self, "top_asked", 0) + 1
            self.top_agreed = getattr(self, "top_agreed", 0) + rec["top_agrees"]
        self.last_hash = h
        param = next((answers[k]["choice"] for k in (f"{choice}__cell", f"{choice}__target", f"{choice}__slot", f"{choice}__option") if k in answers), None)
        self.history.append({"tick": self.tick, "action": done, "choice": choice, "key": f"{choice}→{param}" if param else choice})
        self._emit(rec, frame, dets, answers)
        return rec

    def _look(self) -> dict[str, Any]:
        """The pack's reads on the current screen and state, without advancing a game that waits for us and without
        touching per-run history: what a multi-step plan checks between its steps."""
        frame = self.device.screen() if hasattr(self.device, "screen") else self.device.frame()
        st = self.device.state() if hasattr(self.device, "state") else None
        values, _, _ = read_all(self.pack, frame, tick=self.tick, previous=self.last_values, state=st)
        return self._present(values, self.pack)

    def _probe(self, r: dict[str, Any], values: dict[str, Any] | None = None) -> str | None:
        """What kind of screen is this, found by trying, with no knowledge of the game: branch from a save state and
        play each of wait, A and the four directions for the same number of frames, then put the game back.

          walk    a direction moved the player's position (`pos`: state paths of the discovered x and y)
          choice  no position moved, but a direction changed the screen: a cursor or a selection, a choice to make
          text    no direction did anything, A did: something to page through
          none    nothing responds (a cutscene, a transition): wait

        A blinking arrow or scrolling clouds are the same in every branch, so only what an input caused differs.
        `when_any`: only probe on screens where one of these holds (else `otherwise`)."""
        conds = r.get("when_any")
        if conds and values is not None and not any(self._cond(c, values) for c in conds):
            return r.get("otherwise")
        if not hasattr(self.device, "branch"):
            return None
        import numpy as _np
        dirs = list(r.get("keys") or ["down", "up", "left", "right"])
        buttons = list(r.get("buttons") or ["a", "start", "b"])
        # directions are held long enough to walk a step: a tap only turns the player in some games (Pokemon)
        hold = int(r.get("hold", 16))
        res = self.device.branch({"wait": [], **{k: [k] for k in buttons}, **{k: [f"{k}:{hold}"] for k in dirs}}, frames=int(r.get("frames", 48)))
        disc = getattr(self.device, "discoverer", None)
        if disc is not None and res["wait"].get("ram") is not None:
            # each direction against waiting, from the same moment: what the press changed and nothing else, which is
            # what finding the position needs (a timer or an animation changes in both and cancels out)
            for k in dirs:
                disc.press(k, res["wait"]["ram"], res[k]["ram"], full=False)
        base = res["wait"]["screen"].astype(_np.int16)
        thr = float(r.get("min_change", 0.05))   # the emulator is deterministic: a few letters more is a real difference
        differs = {k: float(_np.abs(v["screen"].astype(_np.int16) - base).mean()) > thr for k, v in res.items() if k != "wait"}
        pos = [str(x) for x in (r.get("pos") or [])]
        def at(k):
            st = res[k]["state"] or {}
            return tuple(_get(st, p_) for p_ in pos)
        moved = [k for k in dirs if pos and None not in at("wait") and at(k) != at("wait")]
        self.last_probe = {"moved": moved, "changed": [k for k, v in differs.items() if v]}
        if moved:
            return "walk"
        if any(differs[k] for k in dirs):
            return "choice"
        if differs["a"]:
            return "text"
        if any(differs.get(k) for k in buttons):
            return "button"             # only START or B does something: a choice of button
        return "none"

    last_probe: dict[str, Any] = {}

    def _goals_update(self, values: dict[str, Any]) -> None:
        """Goals are an ordered list of milestones, each done when its condition holds; once done, done for good.
        The current goal is the first not done whose `when` holds: it goes to the decider and to the navigator."""
        for g in self.base.raw.get("goals") or []:
            if g["id"] not in self.goals_done and g.get("done") and self._task_ok(g["done"], values):
                self.goals_done.add(g["id"])
                self.goal_log.append({"id": g["id"], "tick": self.tick, "frames": getattr(self.device, "frames", None)})
                if self.on_goal is not None:
                    self.on_goal(g, self)
        self.quest = next((g for g in self.base.raw.get("goals") or [] if g["id"] not in self.goals_done
                           and (not g.get("when") or self._task_ok(g["when"], values))), None)

    on_goal = None                  # (goal, agent) when a goal is reached: a run saves its state there

    def _apply_rules(self, answers: dict[str, Any], values: dict[str, Any]) -> list[str]:
        """Pack rules turn beliefs (or compiled reads) into policy inside the same tick.
           if: {noul: q, gte|lte: p} or {read: id[.path], equals|in|not: v}
           exclude: [actions]  ("$read" = that read's value)  → the choice becomes the best remaining action by probability
           set: {param_question: source_question}              → copy a choice into a parameter question."""
        applied: list[str] = []
        excluded: set[str] = set()
        offered = None                      # the questions as asked this tick, built on the first set: rule
        for rl, why in self._hits(answers, values):
            for x in rl.get("exclude") or []:
                v = _get(values, x[1:]) if isinstance(x, str) and x.startswith("$") else x
                if v is not None and v != "none":
                    excluded.add(str(v))
                    applied.append(f"{why} → not {v}")
            for target, source in (rl.get("set") or {}).items():
                src = answers.get(source)
                if src and src.get("type") == "choice" and src.get("choice") not in (None, "none") and target in answers:
                    if offered is None:
                        offered = self.questions(values)
                    allowed = (offered.get(target) or {}).get("criteria")
                    if allowed is not None and src["choice"] not in allowed:
                        # a value the question did not offer (it changed nothing last time, or an avoid/only rule
                        # dropped it) is not forced back in by a belief: a wrong one tapped a full column to the cap
                        applied.append(f"{why} → {target} = {source} ({src['choice']}) skipped: not offered")
                        continue
                    if answers[target].get("choice") != src["choice"]:
                        answers[target] = {**answers[target], "choice": src["choice"]}
                        applied.append(f"{why} → {target} = {source} ({src['choice']})")
        act = answers.get("action")
        if excluded and act and act.get("choice") in excluded:
            probs = {k: v for k, v in (act.get("probabilities") or {}).items() if k not in excluded}
            allowed = [a.id for a in self.pack.actions if a.id not in excluded]
            if probs:
                best = max(probs, key=probs.get)
                answers["action"] = {**act, "choice": best}
                applied.append(f"→ {best}")
            elif len(allowed) == 1:
                # the decider's answer (often a stale one, under budget_ms) never offered the one action the rules
                # leave: take it, the rules have decided
                answers["action"] = {**act, "choice": allowed[0]}
                applied.append(f"→ {allowed[0]} (the only action the rules allow)")
            else:
                # the rules are infeasible here: every action is excluded. The choice stands, and the record says so,
                # because a trap that closed ticks ago is an incident for the reads that should have seen it coming
                applied.append(f"→ every action excluded; {act.get('choice')} stands")
        return applied

    # ---- tasks ---------------------------------------------------------------------------------
    def _task_ok(self, conds: Any, values: dict[str, Any]) -> bool:
        return all(self._cond(c, values) for c in (conds if isinstance(conds, list) else [conds]))

    def _pick_task(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """The next task: in the setter's order (else the pack's), one whose `when` holds, least attempted first."""
        tried = {e["id"]: 0 for e in self.task_log}
        for e in self.task_log:
            tried[e["id"]] += 1
        order = {tid: k for k, tid in enumerate(self.task_order or [t["id"] for t in self.base.tasks])}
        failed = {e["id"]: 0 for e in self.task_log}
        for e in self.task_log:
            if e["outcome"] == "failed":
                failed[e["id"]] += 1
        cap = int(self.base.raw.get("task_attempts", 2))      # a task that keeps failing this run waits for the next one
        cands = [t for t in self.base.tasks if (not t.get("when") or self._task_ok(t["when"], values)) and not self._task_ok(t["done"], values) and failed.get(t["id"], 0) < cap]
        cands.sort(key=lambda t: (tried.get(t["id"], 0), order.get(t["id"], len(order))))
        return cands[0] if cands else None

    def _finish_task(self, outcome: str, rec: dict[str, Any]) -> None:
        t = self.task
        ev = {"id": t["id"], "category": t.get("category", "other"), "outcome": outcome, "ticks": self.tick - self.task_started, "tick": self.tick, "limit_ticks": t["limit_ticks"]}
        self.task_log.append(ev)
        rec["task_" + outcome] = t["id"]
        self.task, self.task_held = None, 0
        if self.on_task is not None:
            self.on_task(ev)

    def _tasks_tick(self, values: dict[str, Any], rec: dict[str, Any]) -> None:
        if self.task is None:
            self.task = self._pick_task(values)
            if self.task is not None:
                self.task_started, self.task_held = self.tick, 0
                rec["task_started"] = self.task["id"]
        if self.task is None:
            return
        rec["task"] = self.task["id"]
        if self._task_ok(self.task["done"], values):
            self.task_held += 1
            if self.task_held >= int(self.task.get("hold_ticks", 1)):
                self._finish_task("done", rec)
                return
        else:
            self.task_held = 0
        if self.tick - self.task_started >= int(self.task.get("limit_ticks", 150)):
            self._finish_task("failed", rec)

    def _hits(self, answers: dict[str, Any], values: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
        """The rules whose condition holds on these answers and values, with why."""
        out = []
        for rl in self.pack.rules:
            hit, whys = True, []
            for c in (rl["if"] if isinstance(rl["if"], list) else [rl["if"]]):     # a list: all must hold
                if "noul" in c:
                    a = answers.get(c["noul"])
                    if not a or a.get("type") != "noul":
                        hit = False
                        break
                    p = a["noul"]
                    hit = (p >= c["gte"]) if "gte" in c else (p <= c["lte"])
                    whys.append(f"{c['noul']}={p:.2f}")
                else:
                    hit = self._cond(c, values)
                    whys.append(f"{c['read']}={_get(values, c['read'])}")
                if not hit:
                    break
            why = ", ".join(whys)
            u = rl.get("unless")
            if hit and u and any(self._cond(x, values) for x in (u if isinstance(u, list) else [u])):
                continue        # the exception: e.g. the cell the rule guards against is the food itself
            if hit:
                out.append((rl, why))
        return out

    def _excluded(self, answers: dict[str, Any], values: dict[str, Any]) -> set[str]:
        """The actions the rules exclude here: the complement of what the decider is allowed to pick."""
        exc: set[str] = set()
        for rl, _ in self._hits(answers, values):
            for x in rl.get("exclude") or []:
                v = _get(values, x[1:]) if isinstance(x, str) and x.startswith("$") else x
                if v is not None and v != "none":
                    exc.add(str(v))
        return exc

    @staticmethod
    def _cond(c: dict[str, Any], values: dict[str, Any]) -> bool:
        v = _get(values, c["read"])
        if "equals" in c:
            return v == c["equals"]
        if "in" in c:
            return v in c["in"]
        if "not" in c:
            return v != c["not"]
        if "contains" in c:
            # a list read holds the item, or a comma-joined read (a gap read's rows: "chest,low") names it
            items = v if isinstance(v, (list, tuple)) else str(v or "").split(",")
            return c["contains"] in items
        try:
            if "gte" in c:
                return float(v) >= float(c["gte"])
            if "lte" in c:
                return float(v) <= float(c["lte"])
        except (TypeError, ValueError):
            return False
        return False

    def _present(self, values: dict[str, Any], pack=None) -> dict[str, Any]:
        """Grid reads marked `as: matrix` become rows of characters (top to bottom): models read that far better."""
        pack = pack or self.pack
        out = dict(values)
        for rid, r in pack.reads.items():
            if r.get("as") == "matrix" and isinstance(values.get(rid), dict) and "zone" in r:
                z = pack.zone(r["zone"])
                if z.grid:
                    cols, rows = z.grid
                    v = values[rid]
                    out[rid] = ["".join(str(v.get(f"c{c}r{rr}", "?"))[:1] for c in range(1, cols + 1)) for rr in range(1, rows + 1)]
        return out

    def _emit(self, rec, frame, dets, answers):
        if self.on_record is not None:
            self.on_record(rec, frame)
        if self.log:
            self.log.write(json.dumps(rec) + "\n")
            self.log.flush()
        if self.hud:
            self.hud.update(frame, dets, rec, answers, self.pack)
        if self.record_dir is not None:
            import cv2
            img = self.hud.last_annotated if self.hud is not None and getattr(self.hud, "last_annotated", None) is not None else frame
            cv2.imwrite(str(self.record_dir / f"{self.tick:05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
        if self.log:
            self.log.close()
            self.log = None

    stall_ticks: int = 0            # >0: a run ends after this many consecutive unchanged screens (the game is over and the pack has no stop_when for it)

    def run(self):
        period = 1.0 / self.pack.tick_hz
        unchanged, last_hash = 0, None
        try:
            while True:
                t = time.perf_counter()
                rec = self.step()
                if rec.get("action") == "stop" or (self.max_ticks and self.tick >= self.max_ticks):
                    return rec
                # a stall is the same screen tick after tick with nothing decided: the game ended and the pack has no
                # read for it, or a gate (act_when) never opens because a read is wrong
                unchanged = unchanged + 1 if (rec.get("hash") == last_hash and "jev_ms" not in rec) else 0
                last_hash = rec.get("hash")
                if self.stall_ticks and unchanged >= self.stall_ticks:
                    rec["action"] = "stop"
                    rec["reason"] = f"stalled: the screen has not changed for {unchanged} ticks"
                    return rec
                if getattr(self.device, "exhausted", False):
                    return rec
                dt = time.perf_counter() - t
                if dt < period:
                    time.sleep(period - dt)
        finally:
            self.close()
