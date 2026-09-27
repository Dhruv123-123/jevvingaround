"""The play loop: frame → reads → state → Jev → action → device, at tick_hz. One audit line per tick."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from .device.base import Device
from .geometry import Zone
from .jev import Jev
from .pack import Action, Pack
from .perceive import read_all, around_of


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
    def __init__(self, pack: Pack, device: Device, jev: Jev | None, hud=None, log_path: str | None = None, max_ticks: int | None = None, record_dir: str | None = None):
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
        # slow reads (OCR, detectors) run in a forked worker process: a thread starves next to onnxruntime and
        # the browser, a process does not, and the loop only ever waits on the first value
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("fork")) if any(int(r.get("every", 1)) > 1 for r in self.pack.reads.values()) else None
        self.pending: dict[str, Any] = {}
        self.tick = 0
        self.total_cost = 0.0
        self.last_hash = None
        self.last_values: dict[str, Any] | None = None
        self.noops: list[str] = []           # executed actions ("drop→c4", "up") that changed nothing since the last change
        self.prev_distinct: dict[str, Any] = {}   # last value of each history read that differed from the current one

    # ---- questions -------------------------------------------------------------------------------
    def questions(self, values: dict[str, Any]) -> dict[str, dict]:
        qs: dict[str, dict] = {}
        for q in self.pack.questions:
            qs[q["id"]] = {"type": q["type"], "instructions": q["instructions"], "criteria": q["criteria"]}
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
        for n in self.noops:
            if "→" not in n:
                continue
            aid, val = n.split("→", 1)
            for pq in (f"{aid}__cell", f"{aid}__target", f"{aid}__slot"):
                if pq in qs:
                    c = {k: v for k, v in qs[pq]["criteria"].items() if k != val}
                    if c:
                        qs[pq] = {**qs[pq], "criteria": c}
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
            if a.kind == "tap" and a.params.get("zone") and self.pack.zone(a.params["zone"]).grid and f"{a.id}__cell" not in qs:
                cells = self.pack.zone(a.params["zone"]).cells()
                qs[f"{a.id}__cell"] = {"type": "choice", "instructions": f"If the action is {a.id}, which cell of {a.params['zone']}?", "criteria": {k.split('.', 1)[1]: None for k in list(cells)[:255]}}
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
            self.device.key(p["key"])
            return f"key {p['key']}"
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

    # ---- one tick --------------------------------------------------------------------------------
    def step(self) -> dict[str, Any]:
        self.tick += 1
        t0 = time.perf_counter()
        frame = self.device.frame()
        values, dets, timings = read_all(self.pack, frame, tick=self.tick, previous=self.last_values, pool=self.pool, pending=self.pending)
        t_perc = (time.perf_counter() - t0) * 1000
        raw_values = values
        values = self._present(values)
        # `history: 1` on a read exposes the last DISTINCT value as <id>_prev (two ticks can see the same frame),
        # and a tracked `locate` read also gets <id>_moving: up/down/left/right from the cell names
        for rid, r in self.pack.reads.items():
            if not r.get("history"):
                continue
            cur = values.get(rid)
            if self.last_values is not None and rid in self.last_values and self.last_values[rid] != cur:
                self.prev_distinct[rid] = self.last_values[rid]
            if rid in self.prev_distinct:
                values[f"{rid}_prev"] = self.prev_distinct[rid]
                if r.get("kind") == "locate" and isinstance(cur, str) and isinstance(self.prev_distinct[rid], str):
                    values[f"{rid}_moving"] = _direction(self.prev_distinct[rid], cur)
                    values[f"{rid}_reverse"] = {"up": "down", "down": "up", "left": "right", "right": "left"}.get(values[f"{rid}_moving"], "none")
        for rid, r in self.pack.reads.items():
            if r.get("kind") == "around":
                values[rid] = around_of(values.get(r["of"]), raw_values.get(r["in"]), values.get(f"{r['of']}_moving"), r)
        h = stable_hash({k: v for k, v in values.items() if not k.endswith("_prev")})
        changed = h != self.last_hash
        if changed:
            self.noops = []
        elif self.history and self.history[-1].get("key") and self.history[-1]["key"] not in self.noops:
            self.noops.append(self.history[-1]["key"])
        state = {"game": self.pack.name, "tick": self.tick, "how_to_play": self.pack.play, "screen": values,
                 "recent_actions": [h_["action"] for h_ in self.history[-6:]],
                 "last_action_changed_screen": changed if self.history else None,
                 "actions_that_did_nothing_since_last_change": list(self.noops)}
        self.last_values = values
        rec: dict[str, Any] = {"tick": self.tick, "t": round(t0, 3), "hash": h, "perception_ms": round(t_perc), "timings_ms": timings, "screen": values}
        stop = self.pack.raw.get("stop_when")
        if stop and self._cond(stop, values):
            rec["action"] = "stop"
            rec["reason"] = f"{stop['read']} is {values.get(stop['read'])}"
            self._emit(rec, frame, dets, None)
            return rec
        gate = self.pack.raw.get("act_when")
        if gate and not self._cond(gate, values):
            rec["action"] = "wait"
            rec["reason"] = f"{gate['read']} is {values.get(gate['read'])}"
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
        if not changed and self.history and self.history[-1]["action"] == "wait":
            rec["action"] = "wait"
            rec["reason"] = "screen unchanged"
            self.last_hash = h
            self._emit(rec, frame, dets, None)
            return rec
        qs = self.questions(values)
        try:
            res = self.jev.ask(state, qs)
        except Exception as e:  # noqa: BLE001 — a failed call costs one tick, not the game
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
        done = self.act(action, answers)
        self.total_cost += res["cost_usd"]
        rec.update({"action": done, "choice": choice, "rules": applied, "acted_after_ms": round((time.perf_counter() - t0) * 1000), "action_probs": answers.get("action", {}).get("probabilities"),
                    "nouls": {k: round(v["noul"], 2) for k, v in answers.items() if v.get("type") == "noul"},
                    "choices": {k: v.get("choice") for k, v in answers.items() if v.get("type") == "choice" and k != "action"},
                    "jev_ms": res["latency_ms"], "tokens": res["input_tokens"], "cost_usd": round(res["cost_usd"], 7), "total_cost_usd": round(self.total_cost, 6)})
        self.last_hash = h
        param = next((answers[k]["choice"] for k in (f"{choice}__cell", f"{choice}__target", f"{choice}__slot") if k in answers), None)
        self.history.append({"tick": self.tick, "action": done, "choice": choice, "key": f"{choice}→{param}" if param else choice})
        self._emit(rec, frame, dets, answers)
        return rec

    def _apply_rules(self, answers: dict[str, Any], values: dict[str, Any]) -> list[str]:
        """Pack rules turn beliefs (or compiled reads) into policy inside the same tick.
           if: {noul: q, gte|lte: p} or {read: id[.path], equals|in|not: v}
           exclude: [actions]  ("$read" = that read's value)  → the choice becomes the best remaining action by probability
           set: {param_question: source_question}              → copy a choice into a parameter question."""
        applied: list[str] = []
        excluded: set[str] = set()
        for rl in self.pack.rules:
            c = rl["if"]
            if "noul" in c:
                a = answers.get(c["noul"])
                if not a or a.get("type") != "noul":
                    continue
                p = a["noul"]
                hit = (p >= c["gte"]) if "gte" in c else (p <= c["lte"])
                why = f"{c['noul']}={p:.2f}"
            else:
                hit = self._cond(c, values)
                why = f"{c['read']}={_get(values, c['read'])}"
            if not hit:
                continue
            for x in rl.get("exclude") or []:
                v = _get(values, x[1:]) if isinstance(x, str) and x.startswith("$") else x
                if v is not None and v != "none":
                    excluded.add(str(v))
                    applied.append(f"{why} → not {v}")
            for target, source in (rl.get("set") or {}).items():
                src = answers.get(source)
                if src and src.get("type") == "choice" and src.get("choice") not in (None, "none") and target in answers:
                    if answers[target].get("choice") != src["choice"]:
                        answers[target] = {**answers[target], "choice": src["choice"]}
                        applied.append(f"{why} → {target} = {source} ({src['choice']})")
        act = answers.get("action")
        if excluded and act and act.get("choice") in excluded:
            probs = {k: v for k, v in (act.get("probabilities") or {}).items() if k not in excluded}
            if probs:
                best = max(probs, key=probs.get)
                answers["action"] = {**act, "choice": best}
                applied.append(f"→ {best}")
        return applied

    @staticmethod
    def _cond(c: dict[str, Any], values: dict[str, Any]) -> bool:
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

    def _present(self, values: dict[str, Any]) -> dict[str, Any]:
        """Grid reads marked `as: matrix` become rows of characters (top to bottom): models read that far better."""
        out = dict(values)
        for rid, r in self.pack.reads.items():
            if r.get("as") == "matrix" and isinstance(values.get(rid), dict) and "zone" in r:
                z = self.pack.zone(r["zone"])
                if z.grid:
                    cols, rows = z.grid
                    v = values[rid]
                    out[rid] = ["".join(str(v.get(f"c{c}r{rr}", "?"))[:1] for c in range(1, cols + 1)) for rr in range(1, rows + 1)]
        return out

    def _emit(self, rec, frame, dets, answers):
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

    def run(self):
        period = 1.0 / self.pack.tick_hz
        try:
            while True:
                t = time.perf_counter()
                rec = self.step()
                if rec.get("action") == "stop" or (self.max_ticks and self.tick >= self.max_ticks):
                    return rec
                if getattr(self.device, "exhausted", False):
                    return rec
                dt = time.perf_counter() - t
                if dt < period:
                    time.sleep(period - dt)
        finally:
            self.close()
