"""The Jev audit: at each decision, did Jev's pick do better than the top-ranked pick? Measured, not argued.

At every decision the decider (Jev) makes, the auditor works out what the offline stand-in would have done (the
first option of every question: the compiler's ranking with no judgment) with the pack's rules applied to both.
When the two agree the decision is logged as `agree`: the ranking alone would have made it. When they differ, the
emulator is the forward model: from a save state the auditor plays Jev's pick, then `horizon` more decisions with
the stand-in, and measures; puts everything back; plays the top pick the same way and measures; puts everything back
again. Then the real run goes on with Jev's pick. The game, the agent's memory and discovery are restored exactly,
so the audit changes nothing but wall time.

What is measured after each branch (both game-agnostic and graded):

  progress   the grader's milestones (state the agent never sees; for measuring only)
  novelty    tiles walked + 10 x places entered + 3 x dialogue lines + 2 x things inspected + 20 x goals reached

A branch is better when it reaches more milestones, else more novelty (a margin of `min_gap` counts as a tie).
The share of decisions where Jev's pick helped, hurt or made no difference is what sets Jev's job.

    anygame play <pack> --sensor jev --audit 20      # horizon of 20 decisions per branch
"""
from __future__ import annotations
import copy
import time
from typing import Any

# agent attributes shared, not copied, by a branch: the device and the outside world (files, models, servers)
SHARED = ("device", "jev", "log", "hud", "pool", "ask_pool", "inflight", "pack", "base", "fallback", "on_record", "on_goal",
          "on_task", "on_pack_change", "auditor", "record_dir")


def novelty(agent) -> float:
    n = 0.0
    for w in agent.worlds.values():
        if hasattr(w, "visited"):
            n += sum(len(v) for v in w.visited.values()) + 10 * len(w.visited) + 2 * len(w.inspected)
    if getattr(agent, "memory", None) is not None:
        n += 3 * len(agent.memory.dialogue)
    gb = getattr(agent, "goalbook", None)
    if gb is not None:
        n += 20 * sum(1 for g in gb.goals if g.get("outcome") == "reached")
    return n


def _pick(qs: dict, answers: dict, choice: str) -> str | None:
    for k in (f"{choice}__option", f"{choice}__cell", f"{choice}__target", f"{choice}__slot"):
        if k in answers:
            return answers[k].get("choice")
    return None


class Auditor:
    def __init__(self, horizon: int = 20, grader=None, max_audits: int | None = None, min_gap: float = 2.0):
        self.horizon = horizon
        self.grader = grader                   # the run's grader: copied into each branch, never read by the agent
        self.max_audits = max_audits
        self.min_gap = min_gap
        self.records: list[dict[str, Any]] = []
        self.busy = False

    def top_answers(self, qs: dict) -> dict:
        out = {}
        for k, q in qs.items():
            if q["type"] == "choice" and q.get("criteria"):
                crit = list(q["criteria"])
                out[k] = {"type": "choice", "choice": crit[0], "probabilities": {c: (1.0 if i == 0 else 0.0) for i, c in enumerate(crit)}, "confidence": 1.0}
            elif q["type"] == "noul":
                out[k] = {"type": "noul", "noul": 0.5}
            else:
                out[k] = {"type": "score", "score": 0}
        return out

    def check(self, agent, qs: dict, answers: dict, values: dict) -> dict[str, Any] | None:
        if self.busy:
            return None
        jev_choice = answers.get("action", {}).get("choice", "wait")
        top = self.top_answers(qs)
        agent._apply_rules(top, values)
        top_choice = top.get("action", {}).get("choice", "wait")
        a = (jev_choice, _pick(qs, answers, jev_choice))
        b = (top_choice, _pick(qs, top, top_choice))
        rec: dict[str, Any] = {"tick": agent.tick, "jev": "→".join(x for x in a if x), "top": "→".join(x for x in b if x),
                               "options": len((qs.get(f"{jev_choice}__option") or qs.get("action") or {}).get("criteria") or {}),
                               "screen": values.get("screen")}
        if a == b:
            rec["verdict"] = "agree"
            self.records.append(rec)
            return rec
        if self.max_audits is not None and sum(1 for r in self.records if "jev_score" in r) >= self.max_audits:
            rec["verdict"] = "differs (not played out: audit cap)"
            self.records.append(rec)
            return rec
        t0 = time.perf_counter()
        self.busy = True
        try:
            sj = self._branch(agent, answers)
            st = self._branch(agent, top)
        finally:
            self.busy = False
        rec.update({"jev_score": sj, "top_score": st, "ms": int((time.perf_counter() - t0) * 1000)})
        if sj["milestones"] != st["milestones"]:
            rec["verdict"] = "jev better" if sj["milestones"] > st["milestones"] else "top better"
        elif abs(sj["novelty"] - st["novelty"]) <= self.min_gap:
            rec["verdict"] = "same"
        else:
            rec["verdict"] = "jev better" if sj["novelty"] > st["novelty"] else "top better"
        self.records.append(rec)
        return rec

    def _branch(self, agent, answers: dict) -> dict[str, Any]:
        """Play `answers` now and `horizon` stand-in decisions after it; measure; put everything back."""
        from .sensors import TopSensor
        from .pack import Action
        dev = agent.device
        snap = dev.snapshot()
        disc = getattr(dev, "discoverer", None)
        disc_copy = copy.deepcopy(disc) if disc is not None else None
        memo: dict[int, Any] = {id(getattr(agent, k)): getattr(agent, k) for k in SHARED if hasattr(agent, k)}
        gb = getattr(agent, "goalbook", None)
        if gb is not None and gb.chat is not None:
            memo[id(gb.chat)] = gb.chat
        saved = {k: (v if k in SHARED else copy.deepcopy(v, memo)) for k, v in agent.__dict__.items()}
        g = copy.deepcopy(self.grader) if self.grader is not None else None
        n0, m0 = novelty(agent), (len(g.reached) if g is not None else 0)
        chat = gb.chat if gb is not None else None
        try:
            agent.jev, agent.log, agent.on_record, agent.hud, agent.record_dir = TopSensor(), None, None, None, None
            if gb is not None:
                gb.chat = None                  # no goal writing inside a branch: the branch measures the pick alone
            choice = answers.get("action", {}).get("choice", "wait")
            try:
                action = agent.pack.action(choice)
            except Exception:  # noqa: BLE001
                action = Action("wait", "wait")
            agent.act(action, answers)
            if g is not None:
                g.update(dev.memory, when=getattr(dev, "frames", None))
            for _ in range(self.horizon):
                r = agent.step()
                if g is not None:
                    g.update(dev.memory, when=getattr(dev, "frames", None))
                if r.get("action") == "stop":
                    break
            out = {"novelty": round(novelty(agent) - n0, 1), "milestones": (len(g.reached) - m0) if g is not None else 0,
                   "place": (agent.last_values or {}).get("map")}
        finally:
            dev.restore(snap)
            if disc is not None:
                dev.discoverer = disc_copy if disc_copy is not None else disc
            agent.__dict__.clear()
            agent.__dict__.update(saved)
            if gb is not None:
                gb.chat = chat
        return out

    # ---- the numbers ----------------------------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        n = len(self.records)
        by: dict[str, int] = {}
        for r in self.records:
            by[r["verdict"]] = by.get(r["verdict"], 0) + 1
        played = [r for r in self.records if "jev_score" in r]
        by_screen: dict[str, dict[str, int]] = {}
        for r in self.records:
            d = by_screen.setdefault(str(r.get("screen")), {})
            d[r["verdict"]] = d.get(r["verdict"], 0) + 1
        return {"decisions": n, "verdicts": by, "by_screen": by_screen,
                "agree_share": round(by.get("agree", 0) / n, 3) if n else None,
                "jev_helped_share": round(by.get("jev better", 0) / n, 3) if n else None,
                "jev_hurt_share": round(by.get("top better", 0) / n, 3) if n else None,
                "played_out": len(played), "horizon": self.horizon,
                "audit_seconds": round(sum(r.get("ms", 0) for r in played) / 1000, 1)}

    def dump(self) -> dict[str, Any]:
        return {"records": self.records}

    def load(self, d: dict[str, Any]) -> None:
        self.records = list(d.get("records") or [])
