"""Learning from experience without touching a model. The runtime cannot tighten Jev's weights, so it grows the typed
frame instead: every episode goes to a bank, a loss becomes an incident (the last decisions with their frames), the
chat model proposes a revision of the pack (derived reads, rules, questions, paragraph), and the revision is accepted
only if it REPLAYS better than the incumbent on the incident: the fatal decision must now be guarded by a rule or
visible in the typed frame, the ordinary decisions must stay allowed, and the pack must still read the screens.
Replay is deterministic and costs no model call: Jev's recorded answers are pushed through the candidate's reads and
rules. Same contract as ext/src/core/learn.ts."""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import yaml

from .pack import Pack, dump_pack, load_pack_text

LOST = re.compile(r"lost|dead|over|game_over|crash|died|stalled: playing", re.I)   # a deadlock mid-game is a failure to act: a loss
WON = re.compile(r"won|win|victory|cleared", re.I)


@dataclass
class Decision:
    rec: dict[str, Any]
    frame: np.ndarray
    state: Any = None        # the game's own state at that tick, when the device gives one


@dataclass
class Incident:
    """The fatal window of an episode, oldest first; the last decision is the one that lost."""
    reason: str
    tick: int
    decisions: list[Decision]
    at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    kind: str = "loss"       # loss: the last decision lost; success: a span that completed a task or won, to be kept allowed


def outcome(recs: list[dict[str, Any]], n: int, version: int, score_read: str | None = None) -> dict[str, Any]:
    """The outcome of an episode from its records: the last record's reason, the score read if the pack names one."""
    last = recs[-1] if recs else {}
    reason = str(last.get("reason") or ("stop" if last.get("action") == "stop" else "tick cap"))
    dec = [r for r in recs if "jev_ms" in r]
    s = None
    if score_read:
        # a dotted path into the typed frame (piece.lines_cleared), the last value read: the last record is often
        # the game-over screen, where the read is gone (not the largest: one OCR misread would be the score)
        seen = [_get_path(r.get("screen") or {}, score_read) for r in recs]
        nums = [x for x in seen if isinstance(x, (int, float)) and not isinstance(x, bool)]
        s = nums[-1] if nums else None
    return {"n": n, "ticks": len(recs), "decisions": len(dec), "reason": reason, "score": s if isinstance(s, (int, float)) else None,
            "won": bool(WON.search(reason)) and not LOST.search(reason), "lost": bool(LOST.search(reason)),
            "tasks_done": sum(1 for r in recs if r.get("task_done")), "tasks_failed": sum(1 for r in recs if r.get("task_failed")),
            "cost_usd": round(max([float(r.get("total_cost_usd") or 0) for r in recs] + [0.0]), 6), "version": version, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _key(e: dict[str, Any]):
    return (1 if e.get("won") else 0, e.get("tasks_done") or 0, 0 if e.get("lost") else 1, e.get("ticks", 0) if e.get("lost") else 0, e.get("score") or 0)


def better_episode(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    """Is episode b better than a? won > more tasks done > not lost > longer when lost > higher score."""
    return True if a is None else _key(b) > _key(a)


def median_episode(eps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The median episode by the same order: what a candidate has to beat to stay."""
    if not eps:
        return None
    return sorted(eps, key=_key)[len(eps) // 2]


def _value(e: dict[str, Any]) -> int:
    return 1 if e.get("won") else -1 if e.get("lost") else 0


def trial_verdict(trial: list[dict[str, Any]], incumbent: list[dict[str, Any]]) -> tuple[bool, str]:
    """Does a rewrite on trial stay? Its episodes against the incumbent's: by mean outcome (won 1, ended 0, lost -1)
    when either side has a win or a loss, ties broken (and outcome-less games judged) by the median episode order.
    Kept unless it plays worse."""
    if not trial:
        return True, "no trial episodes"
    if not incumbent:
        return True, "no incumbent episodes to compare with"
    mt, mi = sum(map(_value, trial)) / len(trial), sum(map(_value, incumbent)) / len(incumbent)
    if (any(_value(e) for e in trial) or any(_value(e) for e in incumbent)) and abs(mt - mi) > 1e-9:
        return mt > mi, f"mean outcome {mt:+.2f} over {len(trial)} vs {mi:+.2f} over {len(incumbent)}"
    if all(e.get("score") is not None for e in trial + incumbent):
        # a score says more than how long a lost game lasted (a gate that waits more makes games longer, not better)
        st, si = sorted(e["score"] for e in trial)[len(trial) // 2], sorted(e["score"] for e in incumbent)[len(incumbent) // 2]
        return st >= si, f"median score {st} over {len(trial)} vs {si} over {len(incumbent)} (outcome {mt:+.2f} vs {mi:+.2f})"
    rt, ri = median_episode(trial), median_episode(incumbent)
    worse = better_episode(rt, ri) and not better_episode(ri, rt)
    return not worse, f"median episode {rt['ticks']} ticks{' score ' + str(rt.get('score')) if rt.get('score') is not None else ''} vs {ri['ticks']}{' score ' + str(ri.get('score')) if ri.get('score') is not None else ''} (outcome {mt:+.2f} vs {mi:+.2f})"


def answers_of(rec: dict[str, Any]) -> dict[str, Any]:
    """Jev's answers, rebuilt from a record: enough for the rules to run again."""
    out: dict[str, Any] = {}
    if rec.get("action_probs") or rec.get("choice"):
        out["action"] = {"type": "choice", "choice": rec.get("choice"), "probabilities": rec.get("action_probs") or ({rec["choice"]: 1.0} if rec.get("choice") else {})}
    for k, v in (rec.get("nouls") or {}).items():
        out[k] = {"type": "noul", "noul": v}
    for k, v in (rec.get("choices") or {}).items():
        out[k] = {"type": "choice", "choice": v}
    return out


def incident_of(decisions: list[Decision], reason: str, tick: int, window: int = 10) -> Incident:
    """Cut the fatal window out of an episode: the last `window` decisions before the end, with their frames."""
    return Incident(reason, tick, decisions[-window:])


def replay(pack: Pack, inc: Incident) -> dict[str, list]:
    """Push the incident through a pack: the presented values, the support, and what the rules would do to the recorded answers."""
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    ag = Agent(pack, _Still(), None)
    values, choices, applied, support = [], [], [], []
    try:
        for d in inc.decisions:
            v, _, _ = ag.observe(d.frame, pack, want_conf=True, state=d.state)
            ag.last_values = v
            a = answers_of(d.rec)
            ap = ag._apply_rules(a, v)
            values.append(v); applied.append(ap); choices.append((a.get("action") or {}).get("choice") or "wait"); support.append(ag.support(ag.last_conf, v, pack))
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    return {"values": values, "choices": choices, "applied": applied, "support": support}


def _reask(sensor, pack: Pack, decisions: list[Decision], log=lambda m: None, actions: list | None = None) -> dict[str, Any]:
    """The frozen decider asked again, offline, on banked decisions, with THIS pack's typed frame, paragraph and
    questions (and, if given, its actions listed in `actions` order). Per decision: the raw choice, the choice after
    this pack's rules, the effective distribution (the decider's probabilities renormalised over what the rules
    allow) and the excluded set. None where the sensor failed."""
    import dataclasses
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    pk = dataclasses.replace(pack, actions=list(actions)) if actions is not None else pack
    ag = Agent(pk, _Still(), None)
    raw, choices, probs, excluded, cost = [], [], [], [], 0.0
    try:
        for k, d in enumerate(decisions):
            v, _, _ = ag.observe(d.frame, pk, want_conf=True, state=d.state)
            ag.last_values = v
            st = {"game": pk.name, "tick": d.rec.get("tick", k), "how_to_play": pk.play, "screen": v,
                  "recent_actions": [x.rec.get("action") for x in decisions[max(0, k - 6):k]], "last_action_changed_screen": True, "actions_that_did_nothing_since_last_change": []}
            try:
                res = sensor.ask(st, ag.questions(v))
            except Exception as e:  # noqa: BLE001
                log(f"requery: sensor failed at tick {d.rec.get('tick')}: {str(e)[:80]}")
                raw.append(None); choices.append(None); probs.append(None); excluded.append(set())
                continue
            answers = res["answers"]
            act = answers.get("action") or {}
            raw.append(act.get("choice"))
            exc = ag._excluded(answers, v)
            ag._apply_rules(answers, v)
            act = answers.get("action") or {}
            choices.append(act.get("choice"))
            probs.append(_renorm(act.get("probabilities") or ({act["choice"]: 1.0} if act.get("choice") else {}), exc))
            excluded.append(exc)
            cost += float(res.get("cost_usd") or 0.0)
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    return {"raw": raw, "choices": choices, "probs": probs, "excluded": excluded, "cost_usd": round(cost, 6)}


def _renorm(probs: dict[str, Any], excluded: set[str]) -> dict[str, float]:
    """A decider's probabilities restricted to what the rules allow: the policy that actually acts."""
    keep = {k: max(0.0, float(v or 0.0)) for k, v in probs.items() if k not in excluded}
    if not keep:
        keep = {k: 1.0 for k in probs if k not in excluded} or {k: max(0.0, float(v or 0.0)) for k, v in probs.items()}
    z = sum(keep.values())
    return {k: (v / z if z > 0 else 1.0 / len(keep)) for k, v in keep.items()}


def logged_policy(rec: dict[str, Any]) -> dict[str, float]:
    """The incumbent's action distribution at a banked tick, from the record: Jev's probabilities renormalised over
    the actions its rules left (the rules log every exclusion as '… → not X')."""
    exc = {m.group(1) for s in (rec.get("rules") or []) for m in [re.search(r" → not (.+)$", str(s))] if m}
    probs = rec.get("action_probs") or ({rec["choice"]: 1.0} if rec.get("choice") else {})
    return _renorm(probs, exc)


def requery(sensor, pack: Pack, inc: Incident, log=lambda m: None) -> dict[str, Any]:
    """Ask the frozen decider again, offline, on the incident's banked states under this pack. The decider cannot be
    trained, but it can be re-asked: this scores a revision by what it would decide now, not only by replaying what
    it decided then. Returns {choices, probs, fatal_avoided, agreement (fraction of ordinary ticks where the fresh
    choice equals the recorded one), cost_usd}."""
    r = _reask(sensor, pack, inc.decisions, log)
    n = len(inc.decisions) - 1
    fatal = inc.decisions[n].rec.get("choice")
    ordinary = [k for k in range(n) if r["choices"][k] is not None]
    agreement = (sum(1 for k in ordinary if r["choices"][k] == inc.decisions[k].rec.get("choice")) / len(ordinary)) if ordinary else 1.0
    return {"choices": r["choices"], "probs": r["probs"], "fatal_avoided": r["choices"][n] is not None and r["choices"][n] != fatal, "agreement": agreement, "cost_usd": r["cost_usd"]}


def counterfactual(inc: Incident, cand_probs: list[dict[str, float] | None], cap: float = 5.0, eps: float = 0.05) -> dict[str, Any]:
    """The candidate's return on one banked incident by per-decision importance sampling, with the divergence as the
    truncation horizon. The logged policy's probability of each logged action comes from the record; the candidate's
    from re-query under its frame and rules. The weight walks the logged path tick by tick (product of the ratios,
    clipped at `cap`); at the first tick where the candidate would almost surely not have taken the logged action
    (probability under `eps`) the logged trajectory stops saying anything about it, so the walk is cut there and the
    loss at the end is not attributed. A guarded fatal tick has ratio 0 and ends the same way. `loss_weight` is how
    much of this loss the candidate still owns: 1 means it would walk the same path, 0 that it leaves it."""
    T = len(inc.decisions) - 1
    lost = bool(LOST.search(str(inc.reason or "")))
    w, diverged, ratios = 1.0, None, []
    for t in range(T + 1):
        rec = inc.decisions[t].rec
        a = rec.get("choice")
        pi = logged_policy(rec).get(a, 0.0)
        pc_dist = cand_probs[t] if t < len(cand_probs) else None
        if pc_dist is None:                   # the sensor failed there: a neutral step
            ratios.append(1.0)
            continue
        pc = float(pc_dist.get(a, 0.0))
        ratio = pc / max(pi, 1e-6)
        ratios.append(round(min(ratio, cap), 3))
        if pc < eps and t < T:
            diverged, w = rec.get("tick", t), 0.0
            break
        w = min(cap, w * ratio)
    return {"loss_weight": round(w if lost else 0.0, 4), "lost": lost, "diverged_at": diverged, "ratios": ratios, "reached_end": diverged is None}


def counterfactual_summary(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Over all banked incidents: the candidate's estimated losses against the incumbent's logged ones, and how
    many logged trajectories still inform the estimate (effective sample size over the weights)."""
    n = len(parts)
    if not n:
        return {"n": 0, "candidate_loss": 0.0, "incumbent_loss": 0.0, "ess": 0.0, "diverged": 0, "walks_into": 0}
    ws = [p["loss_weight"] for p in parts]
    ess = (sum(ws) ** 2 / sum(w * w for w in ws)) if any(ws) else 0.0
    return {"n": n, "candidate_loss": round(sum(ws) / n, 3), "incumbent_loss": round(sum(1 for p in parts if p["lost"]) / n, 3), "ess": round(ess, 2),
            "diverged": sum(1 for p in parts if p["diverged_at"] is not None), "walks_into": sum(1 for p in parts if p["lost"] and p["loss_weight"] >= 0.5)}


def counterfactual_return(sensor, pack: Pack, incidents: list[Incident], log=lambda m: None, requeried: dict[int, list] | None = None) -> dict[str, Any]:
    """Re-ask the decider on every banked incident under `pack` and estimate its return there. `requeried` maps an
    incident's index to candidate probabilities already obtained (so the fatal incident is not asked twice)."""
    parts, cost = [], 0.0
    for i, inc in enumerate(incidents):
        if not inc.decisions or inc.decisions[-1].rec.get("never_acted"):
            continue
        probs = (requeried or {}).get(i)
        if probs is None:
            r = _reask(sensor, pack, inc.decisions, log)
            probs, cost = r["probs"], cost + r["cost_usd"]
        parts.append({"tick": inc.tick, "reason": inc.reason, **counterfactual(inc, probs)})
    out = counterfactual_summary(parts)
    out["per_incident"], out["cost_usd"] = parts, round(cost, 6)
    return out


def holdout_check(sensor, pack: Pack, decisions: list[Decision], log=lambda m: None) -> dict[str, Any]:
    """The decider re-asked on held-out ORDINARY ticks (banked from episodes, outside any fatal window) under the
    candidate: the fraction where it still makes the recorded choice. A revision that fits the loss by changing what
    the decider does everywhere else is drift, not learning; this is the check the incident alone cannot give."""
    if not decisions:
        return {"n": 0, "agreement": 1.0, "flips": [], "cost_usd": 0.0}
    r = _reask(sensor, pack, decisions, log)
    asked = [k for k, c in enumerate(r["choices"]) if c is not None]
    flips = [{"tick": decisions[k].rec.get("tick"), "was": decisions[k].rec.get("choice"), "now": r["choices"][k]} for k in asked if r["choices"][k] != decisions[k].rec.get("choice")]
    return {"n": len(asked), "agreement": round(1 - len(flips) / len(asked), 3) if asked else 1.0, "flips": flips, "cost_usd": r["cost_usd"]}


def action_orders(pack: Pack, seed: int = 1) -> list[tuple[str, list]]:
    """The orders to A/B: as authored, reversed, alphabetical, and one shuffle."""
    import random
    acts = list(pack.actions)
    sh = list(acts)
    random.Random(seed).shuffle(sh)
    cands = [("as authored", acts), ("reversed", list(reversed(acts))), ("alphabetical", sorted(acts, key=lambda a: a.id)), ("shuffled", sh)]
    seen, out = set(), []
    for name, o in cands:
        key = tuple(a.id for a in o)
        if key not in seen:
            seen.add(key); out.append((name, o))
    return out


def audit_order(sensor, pack: Pack, decisions: list[Decision], log=lambda m: None, orders: list[tuple[str, list]] | None = None, fatal: set[int] | None = None) -> list[dict[str, Any]]:
    """Option-order A/B on banked states: the same decider, the same frames, the actions listed in different orders.
    Per order: how often the raw choice is the first option listed (position bias; 1/k is no bias), how often it is
    an action the rules exclude (the rules are the exact oracle here), how often the choice after the rules agrees
    with the recorded one, and how often the fatal choice is repeated on fatal ticks. Sorted best first."""
    out = []
    for name, acts in (orders or action_orders(pack)):
        r = _reask(sensor, pack, decisions, log, actions=acts)
        asked = [k for k, c in enumerate(r["raw"]) if c is not None]
        if not asked:
            continue
        first = sum(1 for k in asked if r["raw"][k] == acts[0].id) / len(asked)
        unsafe = sum(1 for k in asked if r["raw"][k] in r["excluded"][k]) / len(asked)
        agree = sum(1 for k in asked if r["choices"][k] == decisions[k].rec.get("choice")) / len(asked)
        ft = [k for k in asked if decisions[k].rec.get("tick") in (fatal or set())]
        rep = (sum(1 for k in ft if r["raw"][k] == decisions[k].rec.get("choice")) / len(ft)) if ft else None
        out.append({"name": name, "order": [a.id for a in acts], "n": len(asked), "first_pick": round(first, 3), "unsafe": round(unsafe, 3), "agreement": round(agree, 3),
                    "fatal_repeated": None if rep is None else round(rep, 3), "cost_usd": r["cost_usd"]})
    out.sort(key=lambda o: (o["unsafe"], o["fatal_repeated"] or 0.0, -o["agreement"]))
    return out


def order_text(res: list[dict[str, Any]]) -> str:
    """The A/B as a prompt section, when the order matters."""
    if len(res) < 2:
        return ""
    k = max(1, len(res[0]["order"]))
    best, authored = res[0], next((o for o in res if o["name"] == "as authored"), res[-1])
    if best is authored or best["unsafe"] >= authored["unsafe"]:
        return ""
    return (f"ACTION ORDER (the decider re-asked on {best['n']} banked decisions with the actions listed in different orders; it picks a rule-excluded action "
            f"{int(authored['unsafe'] * 100)}% of the time as authored {authored['order']} and {int(best['unsafe'] * 100)}% listed as {best['order']}; the first option listed is picked "
            f"{int(authored['first_pick'] * 100)}% of the time, {int(100 / k)}% would be no position bias). You may reorder `act` to the better order; the ids and kinds stay the same.")


def audit_questions(pack: Pack, decisions: list[Decision]) -> dict[str, dict[str, Any]]:
    """Value of information of every noul question: on each banked decision, force the answer to 0 and to 1 and run the
    rules; a question whose forced answers never change the action is not earning its place (it costs batch accuracy
    and buys nothing), and one that changes it often is doing policy work the rules could do explicitly."""
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    ag = Agent(pack, _Still(), None)
    out: dict[str, dict[str, Any]] = {}
    try:
        nouls = [q["id"] for q in pack.questions if q.get("type") == "noul"]
        for qid in nouls:
            flips, n = 0, 0
            for d in decisions:
                v, _, _ = ag.observe(d.frame, pack, want_conf=True, state=d.state)
                ag.last_values = v
                base = answers_of(d.rec)
                if qid not in base:
                    continue
                n += 1
                got = set()
                for forced in (0.0, 1.0):
                    a = json.loads(json.dumps(base))
                    a[qid] = {"type": "noul", "noul": forced}
                    ag._apply_rules(a, v)
                    got.add((a.get("action") or {}).get("choice"))
                if len(got) > 1:
                    flips += 1
            consumed = any(qid == c.get("noul") for r in pack.rules for c in _conds(r))
            out[qid] = {"decisions": n, "changes_action": flips, "voi": (flips / n) if n else 0.0, "consumed_by_a_rule": consumed,
                        "verdict": "no rule reads it: it cannot change the action" if not consumed else ("never changes the action" if n and not flips else "earns its place")}
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    return out


def _mi(xs: list[Any], ys: list[Any]) -> float:
    """Mutual information in bits between two discrete sequences (plug-in estimate)."""
    import math
    from collections import Counter
    n = len(xs)
    if n == 0:
        return 0.0
    cx, cy, cxy = Counter(xs), Counter(ys), Counter(zip(xs, ys))
    return sum((c / n) * math.log2((c / n) / ((cx[x] / n) * (cy[y] / n))) for (x, y), c in cxy.items())


def _bin(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return "0" if v == 0 else "1" if v == 1 else "2-3" if v <= 3 else "4-8" if v <= 8 else "9+"
    if isinstance(v, (list, dict)):
        return f"len{min(len(v), 5)}"
    return str(v)[:24]


def relevance(records: list[dict[str, Any]], k: int = 4) -> list[dict[str, Any]]:
    """Which reads matter, and to whom. For every scalar path in the typed frame: its mutual information with
    loss-within-k-ticks (danger) and with the decider's choice (attention). A read high on danger and low on
    attention is one the decider ignores: promote it to a rule or a question. Uses whole-episode records, which
    the learn command logs per episode."""
    dec = [r for r in records if "jev_ms" in r and isinstance(r.get("screen"), dict)]
    if len(dec) < 8:
        return []
    last = records[-1]
    lost = bool(LOST.search(str(last.get("reason") or "")))
    ticks = [r.get("tick", i) for i, r in enumerate(dec)]
    end_tick = last.get("tick", ticks[-1])
    danger = [1 if (lost and end_tick - t <= k) else 0 for t in ticks]
    choice = [str(r.get("choice")) for r in dec]
    paths: dict[str, list[Any]] = {}
    for r in dec:
        flat = _flat({kk: vv for kk, vv in r["screen"].items() if not str(kk).endswith("_prev")})
        for kk, vv in flat.items():
            paths.setdefault(kk, []).append(vv)
    out = []
    for path, vals in paths.items():
        if len(vals) != len(dec):
            continue
        xs = [_bin(json.loads(v) if isinstance(v, str) and v[:1] in "[{\"0123456789tfn-" else v) for v in vals]
        if len(set(xs)) < 2:
            continue
        d, a = _mi(xs, danger), _mi(xs, choice)
        out.append({"read": path, "danger": round(d, 3), "attention": round(a, 3), "gap": round(d - a, 3), "distinct": len(set(xs))})
    out.sort(key=lambda o: -o["gap"])
    return out


def relevance_text(rel: list[dict[str, Any]], limit: int = 8) -> str:
    """The audit as a prompt section: the reads that predict the loss and that the decider does not act on."""
    top = [o for o in rel if o["danger"] > 0.05][:limit]
    if not top:
        return ""
    return "READS THAT PREDICT THE LOSS (mutual information with loss-within-4-ticks, and with the decider's choice; a large gap means the decider ignores it: put it in a rule):\n" + "\n".join(
        f"- {o['read']}: danger {o['danger']:.2f}, attention {o['attention']:.2f}" for o in top)


def _get_path(values: dict[str, Any], path: str | None) -> Any:
    cur: Any = values
    for part in str(path or "").split("."):
        if not part:
            continue
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _flat(v: dict[str, Any], prefix: str = "") -> dict[str, str]:
    o: dict[str, str] = {}
    for k, x in v.items():
        if str(k).endswith("_prev"):
            continue
        if isinstance(x, dict):
            o.update(_flat(x, f"{prefix}{k}."))
        else:
            o[f"{prefix}{k}"] = json.dumps(x, sort_keys=True, default=str)
    return o


def separators(values: list[dict[str, Any]]) -> list[str]:
    """The keys of the typed frame that separate the fatal tick from every healthy tick under this pack."""
    if len(values) < 2:
        return []
    ff, hh = _flat(values[-1]), [_flat(h) for h in values[:-1]]
    return [k for k, v in ff.items() if all(h.get(k) != v for h in hh)]


def cell_rule(candidate: Pack, incumbent: Pack) -> str:
    """A rule the candidate adds that tests a located read for an exact cell (equals/in on a locate read), or ''."""
    old = {json.dumps(r, sort_keys=True) for r in incumbent.rules}
    for r in candidate.rules:
        if json.dumps(r, sort_keys=True) in old:
            continue
        for c in _conds(r):
            read = c.get("read")
            if isinstance(read, str) and (candidate.reads.get(read) or {}).get("kind") == "locate" and ("equals" in c or "in" in c):
                return read
    return ""


def _conds(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """A rule's `if` as a list of conditions (it may be one condition or a list that must all hold)."""
    c = rule.get("if") or {}
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else [c] if isinstance(c, dict) else []


def verify_revision(candidate: Pack, incumbent: Pack, inc: Incident, threshold: float = 0.7, max_overblock: float = 0.34,
                    others: list[Incident] | None = None, allow_order: bool = False, successes: list[Incident] | None = None) -> dict[str, Any]:
    """Does the candidate handle the incident better than the incumbent, by replay alone? `others` are earlier losses:
    the candidate must not block their ordinary decisions either (a rule that fits one loss and breaks the rest is out).
    `successes` are banked spans that completed a task or won: every choice in them must stay allowed, the positive
    half of the record that SIMA trains on and a loss-only loop never sees."""
    if not inc.decisions:
        return {"ok": False, "why": "no decisions to replay", "guarded": False, "distinguished": [], "overblocked": 0.0, "support": 0.0}
    if inc.decisions[-1].rec.get("never_acted"):
        # the pack never made a move on this screen (its gate never opened, or every action was excluded): the revision
        # is good if it would act here and still reads the screen
        from .loop import Agent
        c = replay(candidate, inc)
        v = c["values"][-1]
        gate = candidate.raw.get("act_when")
        opens = gate is None or Agent._cond(gate, v)
        if not opens:
            return {"ok": False, "why": f"act_when still does not hold on the stalled screen ({gate.get('read')} = {_get_path(v, gate.get('read'))})", "guarded": False, "distinguished": [], "overblocked": 0.0, "support": min(c["support"])}
        if min(c["support"]) < threshold:
            return {"ok": False, "why": f"reads the stalled screen badly (support {min(c['support']):.2f})", "guarded": False, "distinguished": [], "overblocked": 0.0, "support": min(c["support"])}
        return {"ok": True, "why": "the pack would act on the screen it stalled on", "guarded": True, "distinguished": [], "overblocked": 0.0, "support": min(c["support"])}
    narrow = cell_rule(candidate, incumbent)
    if narrow:
        return {"ok": False, "why": f"rule on {narrow} tests the exact cell of a located read; it would fire only there", "guarded": False, "distinguished": [], "overblocked": 0.0, "support": 0.0}
    c, i = replay(candidate, inc), replay(incumbent, inc)
    support = min(c["support"])
    # the candidate must read every incident frame at least as well as the incumbent did (or above the threshold)
    worse = next((k for k, s in enumerate(c["support"]) if s < min(threshold, i["support"][k] - 0.05)), None)
    if worse is not None:
        return {"ok": False, "why": f"reads the incident screens worse (support {c['support'][worse]:.2f} vs {i['support'][worse]:.2f} at tick {inc.decisions[worse].rec.get('tick')})",
                "guarded": False, "distinguished": [], "overblocked": 0.0, "support": support}
    n = len(inc.decisions) - 1
    fatal = inc.decisions[n].rec.get("choice") or "wait"
    guarded = c["choices"][n] != fatal and i["choices"][n] == fatal
    sep_i = set(separators(i["values"]))
    distinguished = [k for k in separators(c["values"]) if k not in sep_i]
    changed = sum(1 for k in range(n) if c["choices"][k] != inc.decisions[k].rec.get("choice") and i["choices"][k] == inc.decisions[k].rec.get("choice"))
    total = n
    for o in others or []:
        if not o.decisions:
            continue
        oc, oi = replay(candidate, o), replay(incumbent, o)
        m = len(o.decisions) - 1
        changed += sum(1 for k in range(m) if oc["choices"][k] != o.decisions[k].rec.get("choice") and oi["choices"][k] == o.decisions[k].rec.get("choice"))
        total += m
    broke = 0
    for o in successes or []:
        if not o.decisions:
            continue
        oc, oi = replay(candidate, o), replay(incumbent, o)
        b = sum(1 for k in range(len(o.decisions)) if oc["choices"][k] != o.decisions[k].rec.get("choice") and oi["choices"][k] == o.decisions[k].rec.get("choice"))
        broke += b
        changed += b
        total += len(o.decisions)
    overblocked = changed / total if total else 0.0
    if broke:
        return {"ok": False, "why": f"blocks {broke} of the choices in a span that completed a task or won ({changed} of {total} ordinary decisions in all)", "guarded": guarded, "distinguished": distinguished, "overblocked": overblocked, "support": support}
    if overblocked > max_overblock:
        return {"ok": False, "why": f"blocks {changed} of {total} ordinary decisions too", "guarded": guarded, "distinguished": distinguished, "overblocked": overblocked, "support": support}
    if not guarded and not distinguished:
        if allow_order and [a.id for a in candidate.actions] != [a.id for a in incumbent.actions] and {a.id for a in candidate.actions} == {a.id for a in incumbent.actions}:
            # replay cannot see an order change (the recorded answers were given under the old order); only re-query can
            return {"ok": True, "why": "the actions are listed in a new order; only re-asking the decider can judge it", "guarded": False, "distinguished": [], "overblocked": overblocked, "support": support, "order_changed": True}
        return {"ok": False, "why": "the fatal decision is neither excluded by a rule nor visible in the typed frame", "guarded": False, "distinguished": [], "overblocked": overblocked, "support": support}
    why = f"rule now excludes {fatal} at the fatal tick" if guarded else "typed frame now separates the fatal tick: " + ", ".join(distinguished[:4])
    return {"ok": True, "why": why, "guarded": guarded, "distinguished": distinguished, "overblocked": overblocked, "support": support}


FEATURES = ["guarded", "distinguished", "overblocked", "support", "rules_added", "reads_added", "questions_added", "play_changed", "requery_avoided", "requery_agreement", "cf_loss", "holdout_agreement", "order_changed"]


def revision_features(verdict: dict[str, Any], candidate: Pack, incumbent: Pack) -> dict[str, float]:
    """What a revision looks like before it plays: the replay verdict plus how much it changed. The trial record labels
    these (kept or reverted), and the calibrator learns which shapes of revision survive."""
    old_rules = {json.dumps(r, sort_keys=True) for r in incumbent.rules}
    return {
        "guarded": 1.0 if verdict.get("guarded") else 0.0,
        "distinguished": float(len(verdict.get("distinguished") or [])),
        "overblocked": float(verdict.get("overblocked") or 0.0),
        "support": float(verdict.get("support") or 0.0),
        "rules_added": float(sum(1 for r in candidate.rules if json.dumps(r, sort_keys=True) not in old_rules)),
        "reads_added": float(len(set(candidate.reads) - set(incumbent.reads))),
        "questions_added": float(max(0, len(candidate.questions) - len(incumbent.questions))),
        "play_changed": 1.0 if candidate.play.strip() != incumbent.play.strip() else 0.0,
        "requery_avoided": 0.0, "requery_agreement": 0.0, "cf_loss": 0.0, "holdout_agreement": 1.0,      # filled in when the decider was re-asked
        "order_changed": 1.0 if [a.id for a in candidate.actions] != [a.id for a in incumbent.actions] else 0.0,
    }


class Calibrator:
    """Learns, from revisions that were kept or reverted on trial, which revisions to let through. A small logistic
    model on the revision features, fitted whenever there are enough labelled examples; until then it defers to the
    fixed verifier. This is the loop learning to judge: the one thing a fixed judge never does.

    The floor it vetoes under is set conformally, not by hand: every kept revision is scored by a model fitted
    without it (leave-one-out), and the floor is the ⌊α(n_kept+1)⌋-th smallest of those scores (capped at `max_floor`), so a future
    revision as good as the kept ones is refused with probability at most α. With fewer than ⌈1/α⌉-1 kept
    revisions no floor is justified and the calibrator abstains (the trial decides), which is the honest answer
    to a few labels; `floor` is only the fallback when α is None."""

    def __init__(self, history: list[dict[str, Any]], min_labelled: int = 6, floor: float = 0.35, alpha: float | None = 0.25, max_floor: float = 0.9):
        self.rows = [h for h in history if h.get("kept") is not None and h.get("features")]
        self.min_labelled, self.fixed_floor, self.alpha, self.max_floor = min_labelled, floor, alpha, max_floor
        self.w: np.ndarray | None = None
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None
        self.conformal: float | None = None
        self.n_kept = sum(1 for h in self.rows if h["kept"])
        if len(self.rows) >= min_labelled and len({bool(h["kept"]) for h in self.rows}) == 2:
            self.w, self.mu, self.sd = self._fit(self.rows)
            if alpha is not None:
                self.conformal = self._conformal_floor()

    @staticmethod
    def _fit(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        X = np.array([[float(h["features"].get(f, 0.0)) for f in FEATURES] for h in rows], dtype=float)
        y = np.array([1.0 if h["kept"] else 0.0 for h in rows])
        mu, sd = X.mean(0), X.std(0) + 1e-6
        Z = np.hstack([(X - mu) / sd, np.ones((len(X), 1))])
        w = np.zeros(Z.shape[1])
        for _ in range(400):                      # gradient descent with a little L2: tiny data, no surprises
            p = 1 / (1 + np.exp(-Z @ w))
            w -= 0.5 * (Z.T @ (p - y) / len(y) + 0.01 * np.r_[w[:-1], 0.0])
        return w, mu, sd

    @staticmethod
    def _p(features: dict[str, float], w: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> float:
        z = np.r_[(np.array([float(features.get(f, 0.0)) for f in FEATURES]) - mu) / sd, 1.0]
        return float(1 / (1 + np.exp(-z @ w)))

    def _conformal_floor(self) -> float:
        kept = [i for i, h in enumerate(self.rows) if h["kept"]]
        k = int(self.alpha * (len(kept) + 1))
        if k < 1:
            return 0.0
        scores = []
        for i in kept:
            rest = self.rows[:i] + self.rows[i + 1:]
            if len({bool(h["kept"]) for h in rest}) < 2:
                continue
            w, mu, sd = self._fit(rest)
            scores.append(self._p(self.rows[i]["features"], w, mu, sd))
        # capped: on separable records the logistic model is overconfident and the leave-one-out scores crowd near 1;
        # lowering the floor only ever refuses fewer revisions, so the guarantee (at most α good ones refused) stands
        return min(sorted(scores)[k - 1], self.max_floor) if len(scores) >= k else 0.0

    @property
    def floor(self) -> float:
        return self.conformal if self.conformal is not None else self.fixed_floor

    @property
    def active(self) -> bool:
        return self.w is not None

    def p_keep(self, features: dict[str, float]) -> float | None:
        if not self.active:
            return None
        return self._p(features, self.w, self.mu, self.sd)

    def judge(self, features: dict[str, float]) -> tuple[bool, str]:
        p = self.p_keep(features)
        if p is None:
            return True, f"calibrator idle ({len(self.rows)} labelled revisions, needs {self.min_labelled} with both outcomes)"
        how = (f"conformal floor {self.floor:.2f} from {self.n_kept} kept, α={self.alpha}" if self.conformal is not None and self.floor > 0
               else f"no floor yet: {self.n_kept} kept revisions justify no veto at α={self.alpha}" if self.conformal is not None else f"floor {self.floor:.2f}")
        return p >= self.floor, f"calibrated keep probability {p:.2f} from {len(self.rows)} trials; {how}"


def _trim(v: Any, n: int = 420) -> str:
    if isinstance(v, dict):
        v = {k: x for k, x in v.items() if not str(k).endswith("_prev")}
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + "…"


def incident_digest(inc: Incident, episodes: list[dict[str, Any]] | None = None) -> str:
    """The incident as the chat model sees it: every decision with its typed frame, Jev's beliefs and what the rules did."""
    if inc.decisions and inc.decisions[-1].rec.get("never_acted"):
        r = inc.decisions[-1].rec
        return (f"STALL: {inc.reason}. The pack never made a move: for {inc.tick} ticks the screen did not change and no action was taken "
                f"(last reason: {r.get('reason')}). Its reads returned screen={_trim(r.get('screen'))}. Look at the frame: if the game is waiting "
                f"for us, a read behind act_when or a colour option is wrong (measure the real colours), or every action is excluded by a rule.")
    lines = [f"LOSS: {inc.reason} at tick {inc.tick}. The last {len(inc.decisions)} decisions before it, oldest first; the LAST one is the fatal decision:"]
    if "implausible read" in str(inc.reason):
        lines.insert(0, "The episode ended on an IMPLAUSIBLE READ: the reads broke a `plausible` check tick after tick, so a read "
                        "is wrong on that screen (a colour option missing or mis-measured, a state with no label). Fix the read; "
                        "do not loosen the check unless the game really allows that state.")
    for k, d in enumerate(inc.decisions):
        r = d.rec
        lines.append(f"{'FATAL ' if k == len(inc.decisions) - 1 else ''}tick {r.get('tick')}: screen={_trim(r.get('screen'))} → {r.get('action')} probs={_trim(r.get('action_probs'))} beliefs={_trim(r.get('nouls'))} rules={_trim(r.get('rules'))}")
    if episodes:
        lines.append("\nEPISODES so far (newest last): " + "; ".join(
            f"#{e['n']} v{e['version']} {'won' if e.get('won') else 'lost' if e.get('lost') else 'ended'} after {e['ticks']} ticks" + (f" score {e['score']}" if e.get("score") is not None else "") + f" ({str(e['reason'])[:40]})" for e in episodes[-10:]))
    return "\n".join(lines)


REVISION_RULES = (
    "Revise the pack so this loss cannot happen again, without a model being trained: grow the TYPED FRAME. You may add or "
    "change derived reads (locate, runs, around, history on a read), questions, rules (exclude/set with if: {read…} or {noul…}), "
    "act_when/settle/stop_when and the play paragraph. You may ADD options to a colour read (a new symbol for something the frame "
    "shows that the typed frame is blind to, e.g. the player, an enemy, a gap, with its measured hex colour) and put locate/around/runs "
    "reads on it: that is how the typed frame gains a pattern it lacked. Do not remove or re-colour existing options, do not change zones, "
    "and never remove a rule that fired correctly. The fatal decision must become impossible "
    "(a rule excludes it from the values the reads had at that tick) or visible (a new read separates that tick from the ordinary ones), "
    "and the ordinary decisions in the window must stay allowed. Every rule must only name reads that exist. A rule must "
    "generalise: never test the exact cell of a located read (it would fire only there); test relations instead (around, "
    "<dir>_free, <dir>_space, margin, runs, history). A `margin` read gives the room left after each move with the decision latency "
    "compensated (the game advances while the decider thinks), and a rule on it is the strongest guard against moving into a pocket. "
    "You may also reorder `act` (same ids, same kinds): the decider is sensitive to the order options are listed in. "
    "Return the whole pack.yaml in one fenced yaml block.")

def lessons_of(kept: Pack, before: Pack, reason: str = "") -> list[dict[str, Any]]:
    """The rules and reads a kept revision added: snippets that survived replay and a trial, worth showing the model
    the next time this or a similar game loses. They live in the pack under `lessons:` and travel with it into the pool."""
    old_rules = {json.dumps(r, sort_keys=True) for r in before.rules}
    out: list[dict[str, Any]] = []
    for r in kept.rules:
        if json.dumps(r, sort_keys=True) not in old_rules:
            out.append({"kind": "rule", "yaml": yaml.safe_dump(r, default_flow_style=True, width=200).strip(), "reason": reason[:80]})
    for rid in set(kept.reads) - set(before.reads):
        out.append({"kind": "read", "yaml": yaml.safe_dump({rid: kept.reads[rid]}, default_flow_style=True, width=200).strip(), "reason": reason[:80]})
    return out


def hints_text(lessons: list[dict[str, Any]], read_kinds: set[str] | None = None, limit: int = 12) -> str:
    """Lessons as a prompt section: only those built on read kinds this pack has (a grid game's around-rules mean
    nothing to a bar-and-OCR game)."""
    keep = []
    for l in lessons:
        y = str(l.get("yaml", ""))
        if read_kinds and l.get("kind") == "read" and not any(f"kind: {k}" in y for k in read_kinds):
            continue
        keep.append(f"- {l.get('kind')}: {y}" + (f"   # after: {l['reason']}" if l.get("reason") else ""))
    if not keep:
        return ""
    return "PATTERNS THAT SURVIVED TRIAL on this or similar games (reuse the shape, adapt the read names):\n" + "\n".join(keep[:limit])


PACK_SCHEMA_HINT = (
    "Exact syntax (anything else fails to load):\n"
    "- locate: { kind: locate, in: <matrix read id>, symbol: \"<char>\", many: true|false, row: N, col: N } → a cell \"c<col>r<row>\" (a list with many)\n"
    "- runs: { kind: runs, in: <matrix read id>, symbol: \"<char>\", length: N, gravity: down } → the empty cells that would complete N in a line\n"
    "- around: { kind: around, of: <locate read id>, in: <matrix read id>, free: [\"<char>\", …] } → { up, down, left, right, ahead, <dir>_free, <dir>_space }\n"
    "- margin: { kind: margin, of: <locate read id>, in: <matrix read id>, free: [\"<char>\", …], lag: 1, alpha: 0.5 } → { now, up, down, left, right (room reachable after that move, 0 = death), <dir>_ok, safe: [dirs], best }; numeric form { kind: margin, of: <number read id>, lower: 0, upper: 100 } → distance to the nearest bound\n"
    "- history: put `history: 1` on a read → <id>_prev; on a locate also <id>_moving and <id>_reverse\n"
    "- rule: { if: { read: <id or id.path>, equals|in|not|gte|lte: v }, exclude: [<action id or $read>] } or { if: { noul: <question id>, gte|lte: p }, set: { <action>__cell: <choice question id> } }; avoid/only: { <action>__cell: <read id> }\n"
    "- question: { id, type: noul|choice|score, instructions, criteria: { <option>: <meaning> } }\n"
    "- plausible (top level, a list): { read: <grid read>, sticky: [<char>, …] } | { read: <grid read>, max_changes: N } | { read: <grid read>, count: [A, B], diff: [lo, hi] } | { require: <condition> }; each may carry when: <condition>; a condition is { read, equals|in|not|gte|lte } or { line: <grid read>, symbols: [<char>, …], length: N }\n"
    "No other keys. YAML with a duplicated key does not load.")


def improve(chat, pack: Pack, inc: Incident, episodes: list[dict[str, Any]] | None = None, log=lambda m: None, threshold: float | None = None,
            rounds: int = 2, keep_rejected: Path | None = None, others: list[Incident] | None = None,
            hints: str = "", calibrator: "Calibrator | None" = None, sensor=None, min_agreement: float = 0.5,
            holdout: list[Decision] | None = None, min_holdout: float = 0.6, successes: list[Incident] | None = None) -> dict[str, Any]:
    """A revision: incident → chat model → candidate → replay verdict → the decider re-asked (when a sensor is given:
    on the incident, on every earlier incident for the counterfactual return, and on the held-out ordinary ticks) →
    the calibrator's verdict (when it has learned from enough trials), with one repair round when the candidate does
    not load or is rejected. Returns {pack|None, verdict, yaml, features}."""
    from .author import _b64, extract_yaml
    parts: list[dict[str, Any]] = [{"type": "text", "text": REVISION_RULES + "\n\n" + PACK_SCHEMA_HINT + ("\n\n" + hints if hints else "") + "\n\n" + incident_digest(inc, episodes) + "\n\n```yaml\n" + dump_pack(pack.raw) + "\n```"}]
    n = len(inc.decisions)
    for k in ([n - 2, n - 1] if n > 1 else [n - 1]):
        parts.append({"type": "text", "text": f"{'the fatal' if k == n - 1 else 'the previous'} decision's frame (tick {inc.decisions[k].rec.get('tick')}):"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(inc.decisions[k].frame)}})
    thr = threshold if threshold is not None else float(pack.raw.get("support_threshold", 0.7))
    messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    last_yaml, last_verdict, feats = None, None, None
    log(f"learn: asking {chat.model} about the loss at tick {inc.tick} …")
    for rnd in range(1, rounds + 1):
        text = chat.complete(messages, max_tokens=12000, temperature=0.2)[0]
        y = extract_yaml(text)
        problem, cand, v, feats = None, None, None, None
        if not y:
            problem = "there was no ```yaml block"
        else:
            last_yaml = y
            try:
                cand = load_pack_text(y, pack.name)
                cand.raw["fingerprints"] = {**(pack.raw.get("fingerprints") or {}), **(cand.raw.get("fingerprints") or {})}
                if "modes" not in cand.raw and pack.raw.get("modes"):
                    cand.raw["modes"] = pack.raw["modes"]
                cand = load_pack_text(dump_pack(cand.raw), pack.name)
                v = verify_revision(cand, pack, inc, thr, others=others, allow_order=sensor is not None, successes=successes)
                last_verdict = v
                if not v["ok"]:
                    problem = f"replaying the loss through it: {v['why']}"
                else:
                    feats = revision_features(v, cand, pack)
                    if sensor is not None:
                        # the decider itself, re-asked on the banked states under the candidate frame
                        rq = requery(sensor, cand, inc, log)
                        v["requery"] = {"fatal_avoided": rq["fatal_avoided"], "agreement": round(rq["agreement"], 2), "cost_usd": rq["cost_usd"]}
                        feats["requery_avoided"] = 1.0 if rq["fatal_avoided"] else 0.0
                        feats["requery_agreement"] = rq["agreement"]
                        if not rq["fatal_avoided"] and not v.get("guarded"):
                            problem = f"re-asked on the fatal state with this frame, the decider still picks {inc.decisions[-1].rec.get('choice')}; a rule must guard it or the frame must show why"
                        elif rq["agreement"] < min_agreement:
                            problem = f"with this frame the decider changes its mind on {int((1 - rq['agreement']) * 100)}% of the ordinary decisions too; the frame drifted"
                        if problem is None:
                            # the counterfactual return over every banked loss: the candidate must leave more of them than the incumbent did
                            all_inc = [inc] + [o for o in (others or []) if o.decisions]
                            cf = counterfactual_return(sensor, cand, all_inc, log, requeried={0: rq["probs"]})
                            v["counterfactual"] = {k: cf[k] for k in ("n", "candidate_loss", "incumbent_loss", "ess", "diverged", "walks_into")}
                            feats["cf_loss"] = cf["candidate_loss"] / max(cf["incumbent_loss"], 1e-6) if cf["n"] else 0.0
                            if cf["n"] and cf["incumbent_loss"] > 0 and cf["candidate_loss"] >= cf["incumbent_loss"]:
                                problem = f"re-asked on all {cf['n']} banked losses, the decider would walk the same path into {cf['walks_into']} of them (estimated loss {cf['candidate_loss']:.2f} vs {cf['incumbent_loss']:.2f} logged)"
                        if problem is None and holdout:
                            ho = holdout_check(sensor, cand, holdout, log)
                            v["holdout"] = {"n": ho["n"], "agreement": ho["agreement"]}
                            feats["holdout_agreement"] = ho["agreement"]
                            if ho["n"] and ho["agreement"] < min_holdout:
                                ex = "; ".join(f"tick {f['tick']}: {f['was']} → {f['now']}" for f in ho["flips"][:3])
                                problem = f"on {ho['n']} held-out ordinary ticks (no loss near them) the decider changes its choice {int((1 - ho['agreement']) * 100)}% of the time under this frame ({ex}); the revision fits the loss by drifting everywhere else"
                    if problem is None and calibrator is not None:
                        ok, why = calibrator.judge(feats)
                        v["calibration"] = why
                        if not ok:
                            problem = f"revisions shaped like this were reverted on trial before ({why}); change the approach"
            except Exception as e:  # noqa: BLE001
                problem = f"it does not load: {str(e)[:200]}"
        if problem is None and cand is not None and v is not None:
            extra = "".join([f" · counterfactual: leaves {v['counterfactual']['n'] - v['counterfactual']['walks_into']} of {v['counterfactual']['n']} banked losses" if v.get("counterfactual") else "",
                             f" · holdout agreement {v['holdout']['agreement']:.2f} on {v['holdout']['n']}" if v.get("holdout") else "", f" · {v['calibration']}" if v.get("calibration") else ""])
            log(f"learn: accepted (round {rnd}): {v['why']}{extra}")
            return {"pack": cand, "verdict": v, "yaml": y, "features": feats}
        log(f"learn: round {rnd} rejected: {problem}")
        if keep_rejected is not None and y:
            keep_rejected.mkdir(parents=True, exist_ok=True)
            (keep_rejected / f"rejected-{time.strftime('%H%M%S')}-{rnd}.yaml").write_text(y)
        messages = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": f"That revision was rejected: {problem}.\n{PACK_SCHEMA_HINT}\nReturn the whole corrected pack.yaml in one fenced yaml block."}]
    return {"pack": None, "verdict": last_verdict, "yaml": last_yaml, "features": None}


class Bank:
    """What the runtime remembers about a pack across episodes, on disk: episodes.jsonl, the last incidents with their
    frames, and the pack versions that played."""

    def __init__(self, path: str | Path, max_incidents: int = 4):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.max_incidents = max_incidents
        ep = self.path / "episodes.jsonl"
        self.episodes: list[dict[str, Any]] = [json.loads(l) for l in ep.read_text().splitlines() if l.strip()] if ep.exists() else []
        self.version = max([e.get("version", 1) for e in self.episodes] + [1])
        rv = self.path / "revisions.jsonl"
        self.revisions: list[dict[str, Any]] = [json.loads(l) for l in rv.read_text().splitlines() if l.strip()] if rv.exists() else []
        ls = self.path / "lessons.jsonl"
        self.lessons: list[dict[str, Any]] = [json.loads(l) for l in ls.read_text().splitlines() if l.strip()] if ls.exists() else []
        dg = self.path / "diagnoses.jsonl"
        self.diagnoses: list[dict[str, Any]] = [json.loads(l) for l in dg.read_text().splitlines() if l.strip()] if dg.exists() else []
        tk = self.path / "tasks.jsonl"
        self.task_results: list[dict[str, Any]] = [json.loads(l) for l in tk.read_text().splitlines() if l.strip()] if tk.exists() else []

    def _rewrite(self, name: str, rows: list[dict[str, Any]]) -> None:
        (self.path / name).write_text("".join(json.dumps(r) + "\n" for r in rows))

    def add_revision(self, version: int, features: dict[str, float] | None, why: str) -> None:
        """A revision accepted by replay goes on trial: recorded now, labelled when the trial episode ends."""
        self.revisions.append({"version": version, "features": features or {}, "why": why[:120], "kept": None, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        self._rewrite("revisions.jsonl", self.revisions)

    def record_trial(self, version: int, kept: bool, kept_pack: Pack | None = None, before: Pack | None = None, reason: str = "") -> None:
        """The trial's verdict labels the revision; a kept revision's new rules and reads become lessons."""
        for r in reversed(self.revisions):
            if r.get("version") == version and r.get("kept") is None:
                r["kept"] = bool(kept)
                break
        self._rewrite("revisions.jsonl", self.revisions)
        if kept and kept_pack is not None and before is not None:
            new = lessons_of(kept_pack, before, reason)
            if new:
                self.lessons.extend(new)
                self._rewrite("lessons.jsonl", self.lessons)

    def add_diagnosis(self, d: dict[str, Any]) -> None:
        """A diagnosed loss, with what was tried for it; the next diagnosis is told about it."""
        self.diagnoses.append(d)
        self._rewrite("diagnoses.jsonl", self.diagnoses)

    def label_diagnosis(self, version: int, outcome_: str, why: str = "") -> None:
        """A rewrite's trial verdict, written back onto the attempt that produced it."""
        for d in reversed(self.diagnoses):
            for t in d.get("tried") or []:
                if t.get("version") == version and t.get("outcome") == "on trial":
                    t["outcome"], t["why"] = outcome_, why[:160]
                    self._rewrite("diagnoses.jsonl", self.diagnoses)
                    return

    def episode_records(self, inc: Incident) -> list[dict[str, Any]]:
        """The whole episode an incident was cut from, from the episode logs the learn command writes (matched on the
        fatal decision's frame time); the incident's own decisions when no log has it."""
        last = inc.decisions[-1].rec if inc.decisions else {}
        for f in sorted(self.path.glob("episode-*.jsonl"), key=lambda p: -p.stat().st_mtime):
            try:
                recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
            except (OSError, json.JSONDecodeError):
                continue
            if any(r.get("tick") == last.get("tick") and r.get("t") == last.get("t") for r in recs):
                return recs
        return [d.rec for d in inc.decisions]

    def calibrator(self) -> "Calibrator":
        return Calibrator(self.revisions)

    def add_episode(self, e: dict[str, Any]) -> None:
        self.episodes.append(e)
        with open(self.path / "episodes.jsonl", "a") as f:
            f.write(json.dumps(e) + "\n")

    def add_incident(self, inc: Incident) -> Path:
        n = max([int(q.name.split("-")[1]) for q in self.path.glob("incident-*")] + [0]) + 1
        d = self.path / f"incident-{n}"
        d.mkdir()
        for k, dec in enumerate(inc.decisions):
            cv2.imwrite(str(d / f"{k}.png"), dec.frame)
        (d / "incident.json").write_text(json.dumps({"reason": inc.reason, "tick": inc.tick, "at": inc.at, "kind": inc.kind, "recs": [dec.rec for dec in inc.decisions],
                                                     "states": [dec.state for dec in inc.decisions]}, indent=1, default=str))
        # the newest max_incidents of each kind stay: losses and successes are both the record
        for kind in ("loss", "success"):
            old = [p for p in sorted(self.path.glob("incident-*"), key=lambda p: int(p.name.split("-")[1])) if (p / "incident.json").exists() and json.loads((p / "incident.json").read_text()).get("kind", "loss") == kind]
            for p in old[:-self.max_incidents]:
                for f in p.iterdir():
                    f.unlink()
                p.rmdir()
        return d

    def add_task_result(self, ev: dict[str, Any], version: int, episode: int) -> None:
        """A task completed or failed: the per-category record the setter steers by and the suite reports."""
        row = {**ev, "version": version, "episode": episode, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.task_results.append(row)
        with open(self.path / "tasks.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def add_lessons(self, new: list[dict[str, Any]]) -> None:
        if new:
            self.lessons.extend(new)
            self._rewrite("lessons.jsonl", self.lessons)

    def add_holdout(self, decisions: list[Decision], max_holdout: int = 24) -> None:
        """Ordinary ticks, sampled from an episode outside any fatal window: the held-out set a revision is re-asked
        on, so a fix for one loss is also checked for drift where nothing was wrong. Keeps the newest `max_holdout`."""
        if not decisions:
            return
        d = self.path / "holdout"
        d.mkdir(exist_ok=True)
        meta = json.loads((d / "holdout.json").read_text()) if (d / "holdout.json").exists() else {"items": []}
        n0 = max([int(it["file"][1:-4]) for it in meta["items"]] + [0]) + 1
        for k, dec in enumerate(decisions):
            cv2.imwrite(str(d / f"h{n0 + k}.png"), dec.frame)
            meta["items"].append({"file": f"h{n0 + k}.png", "rec": dec.rec, "state": dec.state})
        for it in meta["items"][:-max_holdout]:
            (d / it["file"]).unlink(missing_ok=True)
        meta["items"] = meta["items"][-max_holdout:]
        (d / "holdout.json").write_text(json.dumps(meta, default=str))

    def holdout(self) -> list[Decision]:
        d = self.path / "holdout"
        if not (d / "holdout.json").exists():
            return []
        meta = json.loads((d / "holdout.json").read_text())
        return [Decision(it["rec"], cv2.imread(str(d / it["file"])), it.get("state")) for it in meta["items"] if (d / it["file"]).exists()]

    def incidents(self, kind: str | None = "loss") -> list[Incident]:
        """The banked incidents of a kind (loss by default; success; None for all), oldest first, with their frames."""
        out = [self.load_incident(d) for d in sorted(self.path.glob("incident-*"), key=lambda p: int(p.name.split("-")[1])) if (d / "incident.json").exists()]
        return [i for i in out if kind is None or i.kind == kind]

    def successes(self) -> list[Incident]:
        return self.incidents("success")

    def load_incident(self, d: Path) -> Incident:
        j = json.loads((d / "incident.json").read_text())
        states = j.get("states") or [None] * len(j["recs"])
        decs = [Decision(r, cv2.imread(str(d / f"{k}.png")), states[k]) for k, r in enumerate(j["recs"])]
        return Incident(j["reason"], j["tick"], decs, j.get("at", ""), j.get("kind", "loss"))

    def save_version(self, version: int, yaml_text: str) -> None:
        (self.path / f"pack.v{version}.yaml").write_text(yaml_text)

    def of_version(self, v: int) -> list[dict[str, Any]]:
        return [e for e in self.episodes if e.get("version") == v]


# ---------------------------------------------------------------------------------------------------------------- v2
# The loop as the hand-made fixes needed it: diagnose the whole episode first, let a rewrite add reads, gates and
# compiler features (not only rules), check a new read on the frames already recorded, and judge the rewrite at the
# ticks the diagnosis names, by replay where replay can see the change and by re-asking the decider where it cannot.

FEATURES_HINT = (
    "Beyond rules, a rewrite may change how the loop around the decider works. All of these exist; use the one the diagnosis calls for:\n"
    "- count: { kind: count, in: <grid read id>, symbol: \"<char>\", minus: \"<char>\" } → an integer: cells holding symbol, less cells holding minus. "
    "In a game whose marks alternate and where we move first, `{ kind: count, in: cells, symbol: X, minus: O }` is 0 exactly when it is our turn.\n"
    "- act_when: one condition or a LIST of conditions that must all hold; the agent waits (no decision, no action) while one fails. "
    "A turn gate goes here, next to any menu check: act_when: [ { read: mode, equals: \"1P\" }, { read: turn, equals: 0 } ].\n"
    "- settle: screen_change waits for the screen to change after an action; settle_ticks: N caps that wait. tick_hz: decisions per second.\n"
    "- reflex: { read, equals|in|not|gte|lte } (or a list): when it holds the rules act on the decider's last answers without waiting for a new one "
    "(a move that must land before the decider can answer). A rule may carry unless: { read, … } (or a list): it does not apply when one holds.\n"
    "- tetris read options: lookahead: true ranks each landing by the best result after the preview piece too; top_k: N landings offered.\n"
    "- go read options: playouts: N random playouts per candidate (win rate and margin on each), playouts_top: M, playouts_top_n: K.\n"
    "- slide read (2048) option depth: N; a question may take criteria_from: <read> to offer that read's ranked list as its options.\n"
    "- the play paragraph and the questions: what the decider is told. If the compiler ranks the options, the paragraph must not tell "
    "the decider to prefer something the ranking does not score.")

REVISION_RULES_V2 = (
    "Revise the pack so the DIAGNOSED cause cannot recur, without a model being trained. Fix the cause the diagnosis names, "
    "with the kind of change that addresses it: a turn or timing fault needs a read and a gate (act_when) or a timing setting, "
    "not a strategy rule; an instruction that contradicts the ranking needs the paragraph or question rewritten; a missing "
    "compiler feature needs that option turned on; a wrong read needs the read fixed. Keep everything that is not part of the "
    "fix as it is. Do not remove or re-colour existing options, do not change zones, never remove a rule that fired correctly, "
    "and every rule and gate must only name reads that exist. A rule must generalise: never test the exact cell of a located read. "
    "The change will be checked on the recorded frames: at the evidence ticks the pack must now act differently (a rule "
    "excludes the move, the gate holds the agent back, the ranking changes, or the decider re-asked under the new paragraph "
    "answers differently), the other recorded decisions must stay allowed, and every new read must parse on every recorded "
    "frame. Then it plays a real game and stays only if it plays no worse. Return the whole pack.yaml in one fenced yaml block.")


def shown_pack(pack: Pack) -> str:
    """The pack as the chat model sees it: without screen fingerprints and lessons, which it must not edit and which
    only make the prompt and the answer longer (a long answer timed out at the gateway on Tetris). Both are merged
    back into every candidate."""
    return dump_pack({k: v for k, v in pack.raw.items() if k not in ("fingerprints", "lessons")})


def _gate_ok(pack: Pack, values: dict[str, Any]) -> bool:
    from .loop import Agent
    g = pack.raw.get("act_when")
    return not g or all(Agent._cond(c, values) for c in (g if isinstance(g, list) else [g]))


def _sigs(pack: Pack, ag, answers: dict[str, Any], values: dict[str, Any]) -> tuple[str, str]:
    """A decision as (label, resolved): the action and its parameter choices after the rules, a choice the questions
    no longer offer marked blocked; resolved also says what each label means on this frame (landing `a` = `rot0 col3`)."""
    from .diagnose import resolve
    act = (answers.get("action") or {}).get("choice") or "wait"
    offered = ag.questions(values)
    lab, res = [act], [act]
    for k in sorted(answers):
        if "__" not in k or not k.startswith(f"{act}__"):
            continue
        c = (answers[k] or {}).get("choice")
        crit = (offered.get(k) or {}).get("criteria")
        c = c if crit is None or c in crit else "!blocked"
        lab.append(f"{k}={c}")
        res.append(f"{k}={resolve(pack, values, k, c) if c != '!blocked' else c}")
    return " ".join(lab), " ".join(res)


def replay2(pack: Pack, decisions: list[Decision], recorded: set[str] | None = None) -> dict[str, list]:
    """Push recorded decisions through a pack: the typed frame, whether its gate lets the agent act, the support, and
    the decision after its rules, as labels and as what the labels mean on each frame. `recorded`: reads whose
    definition did not change, taken from the record instead of re-read. A read that tracks the game across frames
    (a piece's phase, a head's direction) cannot be rebuilt from the decision frames alone; the record has it."""
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    ag = Agent(pack, _Still(), None)
    out: dict[str, list] = {"values": [], "gated": [], "label": [], "resolved": [], "support": []}
    try:
        for d in decisions:
            v, _, _ = ag.observe(d.frame, pack, want_conf=True, state=d.state)
            scr = d.rec.get("screen") or {}
            if recorded:
                v = {**v, **{k: scr[k] for k in recorded if k in scr}}
            ag.last_values = v
            a = answers_of(d.rec)
            ag._apply_rules(a, v)
            lab, res = _sigs(pack, ag, a, v)
            out["values"].append(v); out["gated"].append(not _gate_ok(pack, v)); out["label"].append(lab); out["resolved"].append(res)
            out["support"].append(ag.support(ag.last_conf, v, pack))
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    return out


def _reask2(sensor, pack: Pack, decisions: list[Decision], log=lambda m: None) -> list[tuple[str, str] | None]:
    """The decider re-asked under this pack (its typed frame, paragraph and questions) on recorded frames; per decision
    the (label, resolved) decision after the rules, None where the gate holds it back or the sensor failed."""
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    ag = Agent(pack, _Still(), None)
    out: list[tuple[str, str] | None] = []
    cost = 0.0
    try:
        for k, d in enumerate(decisions):
            v, _, _ = ag.observe(d.frame, pack, want_conf=True, state=d.state)
            ag.last_values = v
            if not _gate_ok(pack, v):
                out.append(None)
                continue
            pv = ag._present(v, pack)
            st = {"game": pack.name, "tick": d.rec.get("tick", k), "how_to_play": pack.play, "screen": pv,
                  "recent_actions": [x.rec.get("action") for x in decisions[max(0, k - 6):k]], "last_action_changed_screen": True, "actions_that_did_nothing_since_last_change": []}
            try:
                res = sensor.ask(st, ag.questions(v))
            except Exception as e:  # noqa: BLE001
                log(f"reask: sensor failed at tick {d.rec.get('tick')}: {str(e)[:80]}")
                out.append(None)
                continue
            a = res["answers"]
            ag._apply_rules(a, v)
            out.append(_sigs(pack, ag, a, v))
            cost += float(res.get("cost_usd") or 0.0)
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    log(f"reask: {len(decisions)} recorded decisions re-asked under the candidate, ${cost:.5f}")
    return out


def changed_reads(candidate: Pack, incumbent: Pack) -> list[str]:
    """Reads the candidate adds or defines differently."""
    return [rid for rid, r in candidate.reads.items() if json.dumps(r, sort_keys=True, default=str) != json.dumps(incumbent.reads.get(rid), sort_keys=True, default=str)]


def read_check(candidate: Pack, incumbent: Pack, decisions: list[Decision], min_ok: float = 0.9) -> dict[str, Any]:
    """Every new or changed read must parse on the frames already recorded: no error, a value (not null) on at least
    `min_ok` of them, and, where the read existed before and the definition only changed, the values are reported
    beside the old ones. A read that is null or throws on recorded frames would gate or rule on nothing."""
    rids = changed_reads(candidate, incumbent)
    if not rids or not decisions:
        return {"ok": True, "reads": {}, "why": "no new reads"}
    try:
        r = replay2(candidate, decisions)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reads": {}, "why": f"the candidate's reads fail on a recorded frame: {str(e)[:160]}"}
    rep: dict[str, Any] = {}
    for rid in rids:
        vals = [v.get(rid) for v in r["values"]]
        ok = sum(1 for x in vals if x is not None) / len(vals)
        rep[rid] = {"non_null": round(ok, 3), "distinct": len({json.dumps(x, sort_keys=True, default=str) for x in vals}), "sample": [x for x in vals[:6]]}
        if ok < min_ok:
            return {"ok": False, "reads": rep, "why": f"new read '{rid}' is null on {int((1 - ok) * 100)}% of the {len(vals)} recorded frames"}
    return {"ok": True, "reads": rep, "why": f"{len(rids)} new or changed read(s) parse on {len(decisions)} recorded frames"}


class _Refused(Exception):
    """A candidate refused before it is checked on the frames."""


REPLAY_BLIND_KEYS = ("play", "questions", "tick_hz", "settle", "settle_ticks", "reflex", "ask", "ask_when", "budget_ms", "frames")


def blind_changes(candidate: Pack, incumbent: Pack) -> list[str]:
    """What the candidate changes that replaying recorded answers cannot show: what the decider is told, and timing."""
    return [k for k in REPLAY_BLIND_KEYS if json.dumps(candidate.raw.get(k), sort_keys=True, default=str) != json.dumps(incumbent.raw.get(k), sort_keys=True, default=str)]


def evidence_decisions(inc: Incident, diag: dict[str, Any] | None) -> list[int]:
    """Indices in the incident of the decisions the diagnosis names (the fatal one always among them)."""
    want = {int(e["tick"]) for e in (diag or {}).get("evidence") or [] if isinstance(e.get("tick"), (int, float))}
    if (diag or {}).get("first_bad_tick") is not None:
        want.add(int(diag["first_bad_tick"]))
    idx = [k for k, d in enumerate(inc.decisions) if d.rec.get("tick") in want]
    n = len(inc.decisions) - 1
    return sorted(set(idx) | {n})


def verify_v2(candidate: Pack, incumbent: Pack, inc: Incident, diag: dict[str, Any] | None = None, threshold: float = 0.7, max_overblock: float = 0.34,
              others: list[Incident] | None = None, successes: list[Incident] | None = None, holdout: list[Decision] | None = None,
              sensor=None, min_gate_open: float = 0.2, log=lambda m: None) -> dict[str, Any]:
    """The checks a rewrite passes before it may play: (1) new reads parse on every recorded frame; (2) it reads the
    incident screens as well as the incumbent; (3) at the evidence ticks the diagnosis names it acts differently: a rule
    changes the decision, the gate holds the agent back, the ranking changes what a label means, a new read makes the
    tick visible, or (for what replay cannot show: the paragraph, the questions, timing) the decider re-asked under it
    answers differently; (4) the ordinary decisions stay allowed, here, in earlier losses and in every banked win or
    completed task (a tick the new gate merely defers is not a blocked move, provided the gate opens on at least
    `min_gate_open` of all recorded frames). Returns {ok, why, …}."""
    if not inc.decisions:
        return {"ok": False, "why": "no decisions to replay"}
    every = list(inc.decisions) + [d for o in (others or []) for d in o.decisions] + [d for s in (successes or []) for d in s.decisions] + list(holdout or [])
    rc = read_check(candidate, incumbent, every)
    if not rc["ok"]:
        return {"ok": False, "why": rc["why"], "reads": rc["reads"]}
    same = {rid for rid in incumbent.reads if rid not in changed_reads(candidate, incumbent)}
    c, i = replay2(candidate, inc.decisions, same), replay2(incumbent, inc.decisions, same)
    worse = next((k for k, s in enumerate(c["support"]) if s < min(threshold, i["support"][k] - 0.05)), None)
    if worse is not None:
        return {"ok": False, "why": f"reads the incident screens worse (support {c['support'][worse]:.2f} vs {i['support'][worse]:.2f} at tick {inc.decisions[worse].rec.get('tick')})", "reads": rc["reads"]}
    # the gate must still open: a gate that never opens "guards" every loss by never playing
    open_all = replay2(candidate, every, same)["gated"] if candidate.raw.get("act_when") != incumbent.raw.get("act_when") else []
    gate_open = (1 - sum(open_all) / len(open_all)) if open_all else 1.0
    if open_all and gate_open < min_gate_open:
        return {"ok": False, "why": f"its act_when holds on only {int(gate_open * 100)}% of the {len(open_all)} recorded frames; the agent would hardly play", "reads": rc["reads"]}
    ev = evidence_decisions(inc, diag)
    how: dict[int, str] = {}
    for k in ev:
        if c["gated"][k] and not i["gated"][k]:
            how[k] = "the gate holds the agent back"
        elif c["label"][k] != i["label"][k]:
            how[k] = f"the rules change it ({i['label'][k]} → {c['label'][k]})"
        elif c["resolved"][k] != i["resolved"][k]:
            how[k] = f"the same label means another move now ({i['resolved'][k]} → {c['resolved'][k]})"
    sep_i = set(separators([i["values"][k] for k in range(len(inc.decisions)) if k not in ev] + [i["values"][ev[-1]]]))
    cosmetic = {rid for rid in changed_reads(candidate, incumbent) if rid in incumbent.reads
                and {k: v for k, v in candidate.reads[rid].items() if k != "as"} == {k: v for k, v in incumbent.reads[rid].items() if k != "as"}}
    visible = [k for k in separators([c["values"][k] for k in range(len(inc.decisions)) if k not in ev] + [c["values"][ev[-1]]]) if k not in sep_i and k.split(".")[0] not in cosmetic]
    blind = blind_changes(candidate, incumbent)
    reasked = None
    unjudged: set[int] = set()
    told = [k for k in blind if k in ("play", "questions")]
    if len(how) * 2 < len(ev) and told and sensor is not None:
        # replay cannot see a new paragraph or new questions: ask the decider itself on the evidence frames (not for
        # timing alone: what the decider is told is unchanged, so a different answer would only be its own noise)
        todo = [k for k in ev if k not in how]
        ans = _reask2(sensor, candidate, [inc.decisions[k] for k in todo], log)
        reasked = {}
        for k, a in zip(todo, ans):
            if a is None:
                unjudged.add(k)            # the decider could not be asked there (the gate holds, the sensor failed)
                continue
            was = i["resolved"][k]
            reasked[inc.decisions[k].rec.get("tick")] = {"was": was, "now": a[1]}
            if a[1] != was:
                how[k] = f"re-asked under the new pack the decider answers {a[1]} (was {was})"
    judged = [k for k in ev if k not in unjudged]
    acted = bool(how) and (len(how) * 2 >= len(judged) or (len(ev) - 1) in how)
    timing_only = blind and set(blind) <= {"tick_hz", "settle", "settle_ticks", "budget_ms", "frames"}
    if not acted and not visible and not timing_only:
        return {"ok": False, "why": f"at the {len(ev)} evidence tick(s) ({', '.join(str(inc.decisions[k].rec.get('tick')) for k in ev)}) it acts exactly as before"
                + (f" (re-asked: {json.dumps(reasked)[:200]})" if reasked else "") + ("" if blind or sensor is not None else "; replay cannot see a paragraph change without a decider to re-ask"),
                "reads": rc["reads"], "evidence": ev}
    # ordinary decisions: changed only by blocking (rules or a gate that never reopens), never by a re-ranking
    deferral_ok = gate_open >= min_gate_open

    def blocked(cand: dict[str, list], inc_: dict[str, list], decs: list[Decision], skip: set[int]) -> tuple[int, int]:
        n = 0
        for k in range(len(decs)):
            if k in skip:
                continue
            if cand["gated"][k] and not inc_["gated"][k]:
                n += 0 if deferral_ok else 1
            elif cand["label"][k] != inc_["label"][k]:
                n += 1
        return n, len(decs) - len(skip)

    changed, total = blocked(c, i, inc.decisions, set(ev))
    for o in others or []:
        if o.decisions:
            a, b = blocked(replay2(candidate, o.decisions, same), replay2(incumbent, o.decisions, same), o.decisions, {len(o.decisions) - 1})
            changed, total = changed + a, total + b
    broke = 0
    for s in successes or []:
        if s.decisions:
            a, b = blocked(replay2(candidate, s.decisions, same), replay2(incumbent, s.decisions, same), s.decisions, set())
            broke += a; changed, total = changed + a, total + b
    overblocked = changed / total if total else 0.0
    if broke:
        return {"ok": False, "why": f"blocks {broke} of the choices in a span that completed a task or won", "overblocked": overblocked, "reads": rc["reads"], "evidence": ev}
    if overblocked > max_overblock:
        return {"ok": False, "why": f"blocks {changed} of {total} ordinary decisions too", "overblocked": overblocked, "reads": rc["reads"], "evidence": ev}
    why = ("; ".join(f"tick {inc.decisions[k].rec.get('tick')}: {h}" for k, h in sorted(how.items()))
           or (f"typed frame now separates the evidence ticks: {', '.join(visible[:4])}" if visible else f"a timing change ({', '.join(blind)}); only play can judge it"))
    return {"ok": True, "why": why, "guarded": bool(how), "distinguished": visible, "overblocked": overblocked, "support": min(c["support"]), "reads": rc["reads"],
            "evidence": ev, "gate_open": round(gate_open, 3), "blind": blind, "reasked": reasked}


def improve_v2(chat, pack: Pack, inc: Incident, diag: dict[str, Any], recs: list[dict[str, Any]], history: list[dict[str, Any]] | None = None, log=lambda m: None,
               threshold: float | None = None, rounds: int = 2, keep_rejected: Path | None = None, others: list[Incident] | None = None, hints: str = "",
               calibrator: "Calibrator | None" = None, sensor=None, holdout: list[Decision] | None = None, min_holdout: float = 0.6,
               successes: list[Incident] | None = None) -> dict[str, Any]:
    """diagnosis → chat model → candidate → verify_v2 → held-out drift (when a sensor is given) → calibrator, with one
    repair round. Returns {pack|None, verdict, yaml, features, attempts: [{round, fix_kinds, outcome, why}]}."""
    from .author import _b64, extract_yaml
    from .diagnose import diagnosis_text, episode_digest
    text = (REVISION_RULES_V2 + "\n\n" + diagnosis_text(diag, history) + "\n\n" + PACK_SCHEMA_HINT + "\n" + FEATURES_HINT + ("\n\n" + hints if hints else "")
            + "\n\n" + episode_digest(pack, recs, max_chars=14000) + "\n\n```yaml\n" + shown_pack(pack) + "\n```")
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    n = len(inc.decisions)
    for k in ([n - 2, n - 1] if n > 1 else [n - 1]):
        parts.append({"type": "text", "text": f"{'the fatal' if k == n - 1 else 'the previous'} decision's frame (tick {inc.decisions[k].rec.get('tick')}):"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(inc.decisions[k].frame)}})
    thr = threshold if threshold is not None else float(pack.raw.get("support_threshold", 0.7))
    messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    last_yaml, last_verdict, attempts = None, None, []
    log(f"learn: asking {chat.model} for a rewrite that fixes {diag.get('cause_id')} …")
    for rnd in range(1, rounds + 1):
        text_out = chat.complete(messages, max_tokens=12000, temperature=0.2)[0]
        y = extract_yaml(text_out)
        problem, cand, v, feats, kinds = None, None, None, None, []
        if not y:
            problem = "there was no ```yaml block"
        else:
            last_yaml = y
            try:
                cand = load_pack_text(y, pack.name)
                cand.raw["fingerprints"] = {**(pack.raw.get("fingerprints") or {}), **(cand.raw.get("fingerprints") or {})}
                if "modes" not in cand.raw and pack.raw.get("modes"):
                    cand.raw["modes"] = pack.raw["modes"]
                if "lessons" not in cand.raw and pack.raw.get("lessons"):
                    cand.raw["lessons"] = pack.raw["lessons"]
                if "tests" not in cand.raw and pack.raw.get("tests"):
                    cand.raw["tests"] = pack.raw["tests"]
                cand = load_pack_text(dump_pack(cand.raw), pack.name)
                kinds = change_kinds(cand, pack)
                miss = fits_diagnosis(kinds, diag)
                if miss:
                    raise _Refused(miss)
                v = verify_v2(cand, pack, inc, diag, thr, others=others, successes=successes, holdout=holdout, sensor=sensor, log=log)
                last_verdict = v
                if not v["ok"]:
                    problem = f"checking it on the recorded frames: {v['why']}"
                else:
                    feats = revision_features(v, cand, pack)
                    if sensor is not None and holdout and not set(kinds) <= {"gate", "timing"}:
                        # a gate or a timing change does not change what the decider is told, so re-asking it can
                        # only measure its own noise (Snake: 80% of keep/turn answers flip on a second asking)
                        ho = holdout_check(sensor, cand, holdout, log)
                        v["holdout"] = {"n": ho["n"], "agreement": ho["agreement"]}
                        feats["holdout_agreement"] = ho["agreement"]
                        if ho["n"] and ho["agreement"] < min_holdout:
                            ex = "; ".join(f"tick {f['tick']}: {f['was']} → {f['now']}" for f in ho["flips"][:3])
                            problem = f"on {ho['n']} held-out ordinary ticks the decider changes its choice {int((1 - ho['agreement']) * 100)}% of the time under it ({ex}); it drifts everywhere else"
                    if problem is None and calibrator is not None:
                        ok, why = calibrator.judge(feats)
                        v["calibration"] = why
                        if not ok:
                            problem = f"revisions shaped like this were reverted on trial before ({why}); change the approach"
            except _Refused as e:
                problem = str(e)
            except Exception as e:  # noqa: BLE001
                problem = f"it does not load: {str(e)[:200]}"
        attempts.append({"round": rnd, "fix_kinds": kinds, "outcome": "accepted" if problem is None and cand is not None else "rejected", "why": (v or {}).get("why") if problem is None else problem})
        if problem is None and cand is not None and v is not None:
            log(f"learn: accepted (round {rnd}, changes {', '.join(kinds) or 'none'}): {v['why']}" + (f" · holdout agreement {v['holdout']['agreement']:.2f}" if v.get("holdout") else ""))
            return {"pack": cand, "verdict": v, "yaml": y, "features": feats, "attempts": attempts}
        log(f"learn: round {rnd} rejected ({', '.join(kinds) or 'no change'}): {problem}")
        if keep_rejected is not None and y:
            keep_rejected.mkdir(parents=True, exist_ok=True)
            (keep_rejected / f"rejected-{time.strftime('%H%M%S')}-{rnd}.yaml").write_text(y)
        messages = messages + [{"role": "assistant", "content": text_out}, {"role": "user", "content": f"That revision was rejected: {problem}.\n{PACK_SCHEMA_HINT}\n{FEATURES_HINT}\nReturn the whole corrected pack.yaml in one fenced yaml block."}]
    return {"pack": None, "verdict": last_verdict, "yaml": last_yaml, "features": None, "attempts": attempts}


FITS = {"timing": {"gate", "timing", "read"}, "turn_order": {"gate", "timing", "read"}, "perception": {"read"},
        "instruction": {"paragraph", "question"}, "compiler": {"compiler_option", "read"}}


def fits_diagnosis(kinds: list[str], diag: dict[str, Any] | None) -> str:
    """'' when the rewrite makes a kind of change that can address the diagnosed cause, else why not. A strategy (or
    unknown) cause takes any change; a turn-order cause is not fixed by a strategy rule, which is what the first loop
    proposed eight times over."""
    cat = (diag or {}).get("category")
    need = FITS.get(str(cat))
    if not need or set(kinds) & need:
        return ""
    return f"the diagnosis is a {cat} fault, which needs a {' or '.join(sorted(need))} change; this rewrite only changes {', '.join(kinds) or 'nothing'}"


def change_kinds(candidate: Pack, incumbent: Pack) -> list[str]:
    """What kind of change a rewrite is, in the diagnosis's terms."""
    out = []
    if json.dumps(candidate.rules, sort_keys=True) != json.dumps(incumbent.rules, sort_keys=True):
        out.append("rule")
    ch = changed_reads(candidate, incumbent)
    derived_opts = [r for r in ch if r in incumbent.reads and incumbent.reads[r].get("kind") in ("tetris", "go", "slide", "margin")]
    if derived_opts:
        out.append("compiler_option")
    if set(ch) - set(derived_opts):
        out.append("read")
    if json.dumps(candidate.raw.get("act_when"), sort_keys=True) != json.dumps(incumbent.raw.get("act_when"), sort_keys=True):
        out.append("gate")
    if candidate.play.strip() != incumbent.play.strip():
        out.append("paragraph")
    if json.dumps(candidate.questions, sort_keys=True) != json.dumps(incumbent.questions, sort_keys=True):
        out.append("question")
    if any(json.dumps(candidate.raw.get(k), sort_keys=True) != json.dumps(incumbent.raw.get(k), sort_keys=True) for k in ("tick_hz", "settle", "settle_ticks", "reflex", "ask", "ask_when", "budget_ms", "frames")):
        out.append("timing")
    return out
