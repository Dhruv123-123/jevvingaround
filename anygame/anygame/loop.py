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
from .perceive import read_all


def stable_hash(v: Any) -> str:
    return hashlib.sha1(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


class Agent:
    def __init__(self, pack: Pack, device: Device, jev: Jev | None, hud=None, log_path: str | None = None, max_ticks: int | None = None):
        self.pack, self.device, self.jev, self.hud = pack, device, jev, hud
        self.max_ticks = max_ticks
        self.history: list[dict[str, Any]] = []
        self.log = open(log_path, "a") if log_path else None
        self.tick = 0
        self.total_cost = 0.0
        self.last_hash = None
        self.last_values: dict[str, Any] | None = None
        self.noops: list[str] = []           # actions that did not change the screen since the last change

    # ---- questions -------------------------------------------------------------------------------
    def questions(self, values: dict[str, Any]) -> dict[str, dict]:
        qs: dict[str, dict] = {}
        for q in self.pack.questions:
            qs[q["id"]] = {"type": q["type"], "instructions": q["instructions"], "criteria": q["criteria"]}
        if "action" not in qs:
            qs["action"] = {"type": "choice", "instructions": "Which action now? Follow the play notes in the state.",
                            "criteria": {a.id: (a.params.get("description") or None) for a in self.pack.actions}}
        # System 0: an action that changed nothing is not offered again until the screen changes
        crit = qs["action"]["criteria"]
        left = {k: v for k, v in crit.items() if k not in self.noops}
        if len(left) >= 1 and len(left) < len(crit):
            qs["action"] = {**qs["action"], "criteria": left}
        # parameter questions for actions that need a slot and/or a target cell; all asked in the same call
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
            if a.kind == "tap" and a.params.get("zone") and self.pack.zone(a.params["zone"]).grid:
                cells = self.pack.zone(a.params["zone"]).cells()
                qs[f"{a.id}__cell"] = {"type": "choice", "instructions": f"If the action is {a.id}, which cell of {a.params['zone']}?", "criteria": {k.split('.', 1)[1]: None for k in list(cells)[:255]}}
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
        values, dets, timings = read_all(self.pack, frame, tick=self.tick, previous=self.last_values)
        t_perc = (time.perf_counter() - t0) * 1000
        h = stable_hash(values)
        changed = h != self.last_hash
        if changed:
            self.noops = []
        elif self.history and self.history[-1].get("choice") and self.history[-1]["choice"] not in self.noops:
            self.noops.append(self.history[-1]["choice"])
        state = {"game": self.pack.name, "tick": self.tick, "how_to_play": self.pack.play, "screen": values,
                 "recent_actions": [h_["action"] for h_ in self.history[-6:]],
                 "last_action_changed_screen": changed if self.history else None,
                 "actions_that_did_nothing_since_last_change": list(self.noops)}
        self.last_values = values
        rec: dict[str, Any] = {"tick": self.tick, "hash": h, "perception_ms": round(t_perc), "timings_ms": timings, "screen": values}
        stop = self.pack.raw.get("stop_when")
        if stop and values.get(stop["read"]) == stop["equals"]:
            rec["action"] = "stop"
            rec["reason"] = f"{stop['read']} == {stop['equals']}"
            self._emit(rec, frame, dets, None)
            return rec
        if self.jev is None:
            rec["action"] = "wait"
            self._emit(rec, frame, dets, None)
            return rec
        if not changed and self.history and self.history[-1]["action"] == "wait":
            rec["action"] = "wait"
            rec["reason"] = "screen unchanged"
            self.last_hash = h
            self._emit(rec, frame, dets, None)
            return rec
        qs = self.questions(values)
        res = self.jev.ask(state, qs)
        answers = res["answers"]
        choice = answers.get("action", {}).get("choice", "wait")
        try:
            action = self.pack.action(choice)
        except Exception:
            action = Action("wait", "wait")
        done = self.act(action, answers)
        self.total_cost += res["cost_usd"]
        rec.update({"action": done, "choice": choice, "action_probs": answers.get("action", {}).get("probabilities"),
                    "nouls": {k: round(v["noul"], 2) for k, v in answers.items() if v.get("type") == "noul"},
                    "jev_ms": res["latency_ms"], "tokens": res["input_tokens"], "cost_usd": round(res["cost_usd"], 7), "total_cost_usd": round(self.total_cost, 6)})
        self.last_hash = h
        self.history.append({"tick": self.tick, "action": done, "choice": choice})
        self._emit(rec, frame, dets, answers)
        return rec

    def _emit(self, rec, frame, dets, answers):
        if self.log:
            self.log.write(json.dumps(rec) + "\n")
            self.log.flush()
        if self.hud:
            self.hud.update(frame, dets, rec, answers, self.pack)

    def run(self):
        period = 1.0 / self.pack.tick_hz
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
