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


def outcome(recs: list[dict[str, Any]], n: int, version: int, score_read: str | None = None) -> dict[str, Any]:
    """The outcome of an episode from its records: the last record's reason, the score read if the pack names one."""
    last = recs[-1] if recs else {}
    reason = str(last.get("reason") or ("stop" if last.get("action") == "stop" else "tick cap"))
    dec = [r for r in recs if "jev_ms" in r]
    s = (last.get("screen") or {}).get(score_read) if score_read else None
    return {"n": n, "ticks": len(recs), "decisions": len(dec), "reason": reason, "score": s if isinstance(s, (int, float)) else None,
            "won": bool(WON.search(reason)) and not LOST.search(reason), "lost": bool(LOST.search(reason)),
            "cost_usd": round(float(last.get("total_cost_usd") or 0), 6), "version": version, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _key(e: dict[str, Any]):
    return (1 if e.get("won") else 0, 0 if e.get("lost") else 1, e.get("ticks", 0) if e.get("lost") else 0, e.get("score") or 0)


def better_episode(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    """Is episode b better than a? won > not lost > longer when lost > higher score."""
    return True if a is None else _key(b) > _key(a)


def median_episode(eps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The median episode by the same order: what a candidate has to beat to stay."""
    if not eps:
        return None
    return sorted(eps, key=_key)[len(eps) // 2]


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


def requery(sensor, pack: Pack, inc: Incident, log=lambda m: None) -> dict[str, Any]:
    """Ask the frozen decider again, offline, on the incident's banked states, with THIS pack's typed frame, paragraph
    and questions, then run this pack's rules on the fresh answers. The decider cannot be trained, but it can be
    re-asked: this scores a revision by what it would decide now, not only by replaying what it decided then.
    Returns {choices, probs, fatal_avoided, agreement (fraction of ordinary ticks where the fresh choice equals the
    recorded one), cost_usd}."""
    from .loop import Agent
    from .device.base import Device

    class _Still(Device):
        def size(self):
            return pack.size

    ag = Agent(pack, _Still(), None)
    choices, probs, cost = [], [], 0.0
    try:
        for k, d in enumerate(inc.decisions):
            v, _, _ = ag.observe(d.frame, pack, want_conf=True, state=d.state)
            ag.last_values = v
            st = {"game": pack.name, "tick": d.rec.get("tick", k), "how_to_play": pack.play, "screen": v,
                  "recent_actions": [x.rec.get("action") for x in inc.decisions[max(0, k - 6):k]], "last_action_changed_screen": True, "actions_that_did_nothing_since_last_change": []}
            try:
                res = sensor.ask(st, ag.questions(v))
            except Exception as e:  # noqa: BLE001
                log(f"requery: sensor failed at tick {d.rec.get('tick')}: {str(e)[:80]}")
                choices.append(None); probs.append(None)
                continue
            answers = res["answers"]
            ag._apply_rules(answers, v)
            choices.append((answers.get("action") or {}).get("choice"))
            probs.append((answers.get("action") or {}).get("probabilities"))
            cost += float(res.get("cost_usd") or 0.0)
    finally:
        if ag.pool is not None:
            ag.pool.shutdown(wait=False)
    n = len(inc.decisions) - 1
    fatal = inc.decisions[n].rec.get("choice")
    ordinary = [k for k in range(n) if choices[k] is not None]
    agreement = (sum(1 for k in ordinary if choices[k] == inc.decisions[k].rec.get("choice")) / len(ordinary)) if ordinary else 1.0
    return {"choices": choices, "probs": probs, "fatal_avoided": choices[n] is not None and choices[n] != fatal, "agreement": agreement, "cost_usd": round(cost, 6)}


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
            consumed = any(qid == (r.get("if") or {}).get("noul") for r in pack.rules)
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
        read = (r.get("if") or {}).get("read")
        if isinstance(read, str) and (candidate.reads.get(read) or {}).get("kind") == "locate" and ("equals" in r["if"] or "in" in r["if"]):
            return read
    return ""


def verify_revision(candidate: Pack, incumbent: Pack, inc: Incident, threshold: float = 0.7, max_overblock: float = 0.34,
                    others: list[Incident] | None = None) -> dict[str, Any]:
    """Does the candidate handle the incident better than the incumbent, by replay alone? `others` are earlier incidents:
    the candidate must not block their ordinary decisions either (a rule that fits one loss and breaks the rest is out)."""
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
    overblocked = changed / total if total else 0.0
    if overblocked > max_overblock:
        return {"ok": False, "why": f"blocks {changed} of {total} ordinary decisions too", "guarded": guarded, "distinguished": distinguished, "overblocked": overblocked, "support": support}
    if not guarded and not distinguished:
        return {"ok": False, "why": "the fatal decision is neither excluded by a rule nor visible in the typed frame", "guarded": False, "distinguished": [], "overblocked": overblocked, "support": support}
    why = f"rule now excludes {fatal} at the fatal tick" if guarded else "typed frame now separates the fatal tick: " + ", ".join(distinguished[:4])
    return {"ok": True, "why": why, "guarded": guarded, "distinguished": distinguished, "overblocked": overblocked, "support": support}


FEATURES = ["guarded", "distinguished", "overblocked", "support", "rules_added", "reads_added", "questions_added", "play_changed", "requery_avoided", "requery_agreement"]


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
        "requery_avoided": 0.0, "requery_agreement": 0.0,      # filled in when the decider was re-asked
    }


class Calibrator:
    """Learns, from revisions that were kept or reverted on trial, which revisions to let through. A small logistic
    model on the revision features, fitted whenever there are enough labelled examples; until then it defers to the
    fixed verifier. This is the loop learning to judge: the one thing a fixed judge never does."""

    def __init__(self, history: list[dict[str, Any]], min_labelled: int = 6, floor: float = 0.35):
        self.rows = [h for h in history if h.get("kept") is not None and h.get("features")]
        self.min_labelled, self.floor = min_labelled, floor
        self.w: np.ndarray | None = None
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None
        if len(self.rows) >= min_labelled and len({bool(h["kept"]) for h in self.rows}) == 2:
            self._fit()

    def _fit(self) -> None:
        X = np.array([[float(h["features"].get(f, 0.0)) for f in FEATURES] for h in self.rows], dtype=float)
        y = np.array([1.0 if h["kept"] else 0.0 for h in self.rows])
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-6
        Z = np.hstack([(X - self.mu) / self.sd, np.ones((len(X), 1))])
        w = np.zeros(Z.shape[1])
        for _ in range(400):                      # gradient descent with a little L2: tiny data, no surprises
            p = 1 / (1 + np.exp(-Z @ w))
            w -= 0.5 * (Z.T @ (p - y) / len(y) + 0.01 * np.r_[w[:-1], 0.0])
        self.w = w

    @property
    def active(self) -> bool:
        return self.w is not None

    def p_keep(self, features: dict[str, float]) -> float | None:
        if not self.active:
            return None
        z = np.r_[(np.array([float(features.get(f, 0.0)) for f in FEATURES]) - self.mu) / self.sd, 1.0]
        return float(1 / (1 + np.exp(-z @ self.w)))

    def judge(self, features: dict[str, float]) -> tuple[bool, str]:
        p = self.p_keep(features)
        if p is None:
            return True, f"calibrator idle ({len(self.rows)} labelled revisions, needs {self.min_labelled} with both outcomes)"
        return p >= self.floor, f"calibrated keep probability {p:.2f} from {len(self.rows)} trials"


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
    "<dir>_free, <dir>_space, runs, history). "
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
    "- history: put `history: 1` on a read → <id>_prev; on a locate also <id>_moving and <id>_reverse\n"
    "- rule: { if: { read: <id or id.path>, equals|in|not|gte|lte: v }, exclude: [<action id or $read>] } or { if: { noul: <question id>, gte|lte: p }, set: { <action>__cell: <choice question id> } }; avoid/only: { <action>__cell: <read id> }\n"
    "- question: { id, type: noul|choice|score, instructions, criteria: { <option>: <meaning> } }\n"
    "No other keys. YAML with a duplicated key does not load.")


def improve(chat, pack: Pack, inc: Incident, episodes: list[dict[str, Any]] | None = None, log=lambda m: None, threshold: float | None = None,
            rounds: int = 2, keep_rejected: Path | None = None, others: list[Incident] | None = None,
            hints: str = "", calibrator: "Calibrator | None" = None, sensor=None, min_agreement: float = 0.5) -> dict[str, Any]:
    """A revision: incident → chat model → candidate → replay verdict → the calibrator's verdict (when it has learned
    from enough trials), with one repair round when the candidate does not load or is rejected.
    Returns {pack|None, verdict, yaml, features}."""
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
                v = verify_revision(cand, pack, inc, thr, others=others)
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
                    if problem is None and calibrator is not None:
                        ok, why = calibrator.judge(feats)
                        v["calibration"] = why
                        if not ok:
                            problem = f"revisions shaped like this were reverted on trial before ({why}); change the approach"
            except Exception as e:  # noqa: BLE001
                problem = f"it does not load: {str(e)[:200]}"
        if problem is None and cand is not None and v is not None:
            log(f"learn: accepted (round {rnd}): {v['why']}" + (f" · {v['calibration']}" if v.get("calibration") else ""))
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
        (d / "incident.json").write_text(json.dumps({"reason": inc.reason, "tick": inc.tick, "at": inc.at, "recs": [dec.rec for dec in inc.decisions],
                                                     "states": [dec.state for dec in inc.decisions]}, indent=1, default=str))
        old = sorted(self.path.glob("incident-*"), key=lambda p: int(p.name.split("-")[1]))
        for p in old[:-self.max_incidents]:
            for f in p.iterdir():
                f.unlink()
            p.rmdir()
        return d

    def incidents(self) -> list[Incident]:
        """The banked incidents, oldest first, with their frames."""
        return [self.load_incident(d) for d in sorted(self.path.glob("incident-*"), key=lambda p: int(p.name.split("-")[1])) if (d / "incident.json").exists()]

    def load_incident(self, d: Path) -> Incident:
        j = json.loads((d / "incident.json").read_text())
        states = j.get("states") or [None] * len(j["recs"])
        decs = [Decision(r, cv2.imread(str(d / f"{k}.png")), states[k]) for k, r in enumerate(j["recs"])]
        return Incident(j["reason"], j["tick"], decs, j.get("at", ""))

    def save_version(self, version: int, yaml_text: str) -> None:
        (self.path / f"pack.v{version}.yaml").write_text(yaml_text)

    def of_version(self, v: int) -> list[dict[str, Any]]:
        return [e for e in self.episodes if e.get("version") == v]
