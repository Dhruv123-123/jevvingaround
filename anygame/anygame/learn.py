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

from .pack import Pack, dump_pack, load_pack_text

LOST = re.compile(r"lost|dead|over|game_over|crash|died", re.I)
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


def _trim(v: Any, n: int = 420) -> str:
    if isinstance(v, dict):
        v = {k: x for k, x in v.items() if not str(k).endswith("_prev")}
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + "…"


def incident_digest(inc: Incident, episodes: list[dict[str, Any]] | None = None) -> str:
    """The incident as the chat model sees it: every decision with its typed frame, Jev's beliefs and what the rules did."""
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
            rounds: int = 2, keep_rejected: Path | None = None, others: list[Incident] | None = None) -> dict[str, Any]:
    """A revision: incident → chat model → candidate → replay verdict, with one repair round when the candidate does not
    load or the replay rejects it. Returns {pack|None, verdict, yaml}."""
    from .author import _b64, extract_yaml
    parts: list[dict[str, Any]] = [{"type": "text", "text": REVISION_RULES + "\n\n" + PACK_SCHEMA_HINT + "\n\n" + incident_digest(inc, episodes) + "\n\n```yaml\n" + dump_pack(pack.raw) + "\n```"}]
    n = len(inc.decisions)
    for k in ([n - 2, n - 1] if n > 1 else [n - 1]):
        parts.append({"type": "text", "text": f"{'the fatal' if k == n - 1 else 'the previous'} decision's frame (tick {inc.decisions[k].rec.get('tick')}):"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(inc.decisions[k].frame)}})
    thr = threshold if threshold is not None else float(pack.raw.get("support_threshold", 0.7))
    messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    last_yaml, last_verdict = None, None
    log(f"learn: asking {chat.model} about the loss at tick {inc.tick} …")
    for rnd in range(1, rounds + 1):
        text = chat.complete(messages, max_tokens=12000, temperature=0.2)[0]
        y = extract_yaml(text)
        problem, cand, v = None, None, None
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
            except Exception as e:  # noqa: BLE001
                problem = f"it does not load: {str(e)[:200]}"
        if problem is None and cand is not None and v is not None:
            log(f"learn: accepted (round {rnd}): {v['why']}")
            return {"pack": cand, "verdict": v, "yaml": y}
        log(f"learn: round {rnd} rejected: {problem}")
        if keep_rejected is not None and y:
            keep_rejected.mkdir(parents=True, exist_ok=True)
            (keep_rejected / f"rejected-{time.strftime('%H%M%S')}-{rnd}.yaml").write_text(y)
        messages = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": f"That revision was rejected: {problem}.\n{PACK_SCHEMA_HINT}\nReturn the whole corrected pack.yaml in one fenced yaml block."}]
    return {"pack": None, "verdict": last_verdict, "yaml": last_yaml}


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
