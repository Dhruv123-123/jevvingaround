"""Diagnosis before revision. The first learn loop showed the chat model one window of a lost game and asked for a pack
that excludes the last move; every gain made by hand this week came from reading the WHOLE game first (a turn taken on
a stale frame, a paragraph that contradicts the ranker, a jump timed off the wrong frame). So a loss is diagnosed
before any rewrite is asked for: the model gets the whole episode, every decision with its timing, the reads, the
rules that fired and the compiler's ranking where there is one, and names a cause with evidence ticks. Diagnoses are
kept in the bank with a loss signature, so when the same loss comes back the model is told so, and told what was
already tried for it."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any

from .pack import Pack

CATEGORIES = ("timing", "turn_order", "perception", "strategy", "instruction", "compiler", "other")
FIX_KINDS = ("rule", "read", "gate", "paragraph", "question", "compiler_option", "timing", "reflex")

# What each kind of fault looks like in the record, and the pack feature that answers it. The diagnosis names one of
# these, and the rewrite check insists on a change of the matching kind: the loop knew the features existed but not
# which fault each one answers (on Snake it diagnosed slow reactions and slowed the loop down instead of using reflex).
FAULTS: dict[str, dict[str, Any]] = {
    "late_move": {"category": "timing", "needs": {"reflex"},
                  "when": "the right move was known (the rules or an earlier answer had it) but the decider's answer landed after the "
                          "game had already moved on: the decider's latency is longer than the time to the danger",
                  "fix": "reflex: { read, lte|equals|… } on the read that says danger is one step away, so the rules act on the "
                         "decider's last answers at once; give a rule unless: where the reflex move would be wrong. "
                         "Never slow the loop (tick_hz, settle) for this: waiting longer makes a late move later."},
    "out_of_turn": {"category": "turn_order", "needs": {"gate"},
                    "when": "the agent acted while it was not its turn, or on a frame taken before the game answered its previous "
                            "move (marks or pieces that should alternate do not)",
                    "fix": "a read that says whose turn it is (a count read: our marks minus theirs) and an act_when gate on it"},
    "stale_frame": {"category": "timing", "needs": {"timing", "gate"},
                    "when": "the agent acted on a frame that did not yet show its own previous action, so it repeated or "
                            "contradicted it",
                    "fix": "settle: screen_change (or settle_ticks), or an act_when gate on a read that shows the action landed"},
    "short_sighted": {"category": "compiler", "needs": {"compiler_option"},
                      "when": "the compiler ranks the options and the agent took a well-ranked one that looked fine now but led "
                              "to a bad position a move or two later",
                      "fix": "lookahead: true on a tetris read, depth: N on a slide read (rank by the result after the next piece or move)"},
    "unsure_ranking": {"category": "compiler", "needs": {"compiler_option"},
                       "when": "the ranking is a static heuristic and fails in tactical positions where simulating the game would tell",
                       "fix": "playouts: N on a go read (win rate and margin per candidate), shown to the decider"},
    "ignores_measure": {"category": "compiler", "needs": {"compiler_option"},
                        "when": "the compiler measured a clearly better option (a playout win rate well above the first-ranked "
                                "move's) and the paragraph says to take it, but the decider kept taking the first-ranked option",
                        "fix": "rerank: playouts (rerank_margin: 0.06) on the go read, so the measured leader is ranked first and "
                               "the decider's usual first pick is it; rewording the paragraph does not move the decider"},
    "contradicting_text": {"category": "instruction", "needs": {"paragraph", "question"},
                           "when": "the play paragraph or a question tells the decider to prefer something the compiler's ranking "
                                   "does not score, so it skips the top-ranked option",
                           "fix": "rewrite the paragraph or the question so it agrees with the ranking"},
    "misread": {"category": "perception", "needs": {"read"},
                "when": "a read disagrees with what the frame shows",
                "fix": "fix the read (zone, colours, threshold, kind)"},
    "bad_choice": {"category": "strategy", "needs": set(),
                   "when": "the reads were right, nothing was late or out of turn, and the decision was simply poor",
                   "fix": "a rule that excludes the bad move, or a clearer paragraph"},
}


def faults_text() -> str:
    """The catalog as the diagnosis and the rewrite see it."""
    return "FAULT KINDS (name one) and the feature that fixes each:\n" + "\n".join(
        f"- {k} [{f['category']}]: when {f['when']}. Fix: {f['fix'].rstrip('.')}." for k, f in FAULTS.items())


def _trim(v: Any, n: int = 300) -> str:
    if isinstance(v, dict):
        v = {k: x for k, x in v.items() if not str(k).endswith("_prev")}
    s = json.dumps(v, default=str, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + "…"


def _get(values: Any, path: str | None) -> Any:
    cur = values
    for part in str(path or "").split("."):
        if part:
            cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _option_dict(v: Any) -> dict[str, str] | None:
    """The labelled options inside a read's value: the value itself when it maps short labels to text, else the first
    child that does (a tetris read's `landings`), else a ranked list turned into labels."""
    if isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()) and all(len(str(k)) <= 3 for k in v):
        return {str(k): x for k, x in v.items()}
    if isinstance(v, dict):
        for x in v.values():
            d = _option_dict(x) if isinstance(x, dict) else None
            if d:
                return d
    return None


def options_of(pack: Pack, values: dict[str, Any], param: str) -> dict[str, str] | None:
    """The options a parameter question chooses among, ranked as the compiler gave them (first = its best), when the
    choice comes from a read: a macro action's `options: <read>` or a question's `criteria_from: <read>`."""
    act_id = param.split("__")[0]
    src = None
    for a in pack.actions:
        if a.id == act_id and a.params.get("options"):
            src = a.params["options"]
    for q in pack.questions:
        if q.get("id") == param and q.get("criteria_from"):
            src = q["criteria_from"]
    if not src:
        return None
    v = _get(values, src)
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
        return {chr(97 + i): x for i, x in enumerate(v)}
    return _option_dict(v)


def resolve(pack: Pack, values: dict[str, Any], param: str, label: Any) -> str:
    """What a parameter choice means on this frame: a landing label `a` becomes `rot0 col3`. A cell stays a cell."""
    opts = options_of(pack, values, param)
    if opts and str(label) in opts:
        return str(opts[str(label)]).split(":")[0].strip()[:40]
    return str(label)


def ranking_stats(pack: Pack, recs: list[dict[str, Any]], limit: int = 8) -> str:
    """How often the decider took the compiler's first-ranked option, with examples of when it did not."""
    taken, dev = {}, []
    for r in recs:
        for param, label in (r.get("choices") or {}).items():
            opts = options_of(pack, r.get("screen") or {}, param)
            if not opts:
                continue
            first = next(iter(opts))
            t = taken.setdefault(param, [0, 0])
            t[1] += 1
            if str(label) == first:
                t[0] += 1
            elif len(dev) < limit:
                dev.append(f"  tick {r.get('tick')}: took {label} ({str(opts.get(str(label), '?'))[:90]}) over {first} ({str(opts[first])[:90]})")
    if not taken:
        return ""
    head = "; ".join(f"{p}: took the first-ranked option on {a} of {n} decisions" for p, (a, n) in taken.items())
    return "RANKING: " + head + ("\n" + "\n".join(dev) if dev else "")


def signature(recs: list[dict[str, Any]], k: int = 6) -> str:
    """A loss's mechanical signature: how it ended and the last k decisions (action and parameter choices). The same
    game lost the same way twice has the same signature."""
    dec = [r for r in recs if r.get("choice")]
    last = recs[-1] if recs else {}
    reason = re.sub(r"\d+", "#", str(last.get("reason") or ""))[:40]
    seq = "|".join(f"{r.get('choice')}:{','.join(str(v) for _, v in sorted((r.get('choices') or {}).items()))}" for r in dec[-k:])
    return hashlib.sha1(f"{reason}/{seq}".encode()).hexdigest()[:10]


def episode_digest(pack: Pack, recs: list[dict[str, Any]], max_chars: int = 22000, full_last: int = 8) -> str:
    """The whole episode for the model, oldest first: every decision with its time, the decider's latency, how long
    after the frame the action landed, the reads (all of them for the last `full_last` decisions, otherwise what changed
    since the previous decision), the decider's beliefs, the rules that fired, and runs of non-decision ticks (waits,
    gates, settling) folded into one line each."""
    if not recs:
        return "EPISODE: no records"
    t0 = float(recs[0].get("t") or 0.0)
    dec_idx = [i for i, r in enumerate(recs) if r.get("choice")]
    full_from = dec_idx[-full_last] if len(dec_idx) >= full_last else 0
    last = recs[-1]
    jms = [r["jev_ms"] for r in recs if isinstance(r.get("jev_ms"), (int, float))]
    gate = pack.raw.get("act_when")
    lines = [f"EPISODE: ended '{last.get('reason') or last.get('action')}' at tick {last.get('tick')}, {len(recs)} ticks, {len(dec_idx)} decisions, "
             f"{float(last.get('t') or t0) - t0:.1f} s. Loop: tick_hz {pack.tick_hz}, settle {pack.raw.get('settle')}, act_when {_trim(gate, 160)}, "
             f"reflex {_trim(pack.raw.get('reflex'), 120)}. Decider latency median {sorted(jms)[len(jms) // 2] if jms else 'n/a'} ms."]
    rk = ranking_stats(pack, recs)
    if rk:
        lines.append(rk)
    lines.append("Per tick (t = seconds since the episode began, when the frame was taken; jev = decider ms; acted = ms from frame to the action landing):")
    prev_screen: dict[str, Any] | None = None
    idle: list[dict[str, Any]] = []

    def flush():
        if idle:
            why = sorted({str(x.get("reason") or x.get("action"))[:50] for x in idle})
            lines.append(f"  ticks {idle[0].get('tick')}–{idle[-1].get('tick')} (t {float(idle[0].get('t') or t0) - t0:.2f}–{float(idle[-1].get('t') or t0) - t0:.2f}): "
                         f"{len(idle)}× {idle[-1].get('action')} ({'; '.join(why)[:160]})" + (f" screen={_trim(idle[-1].get('screen'), 260)}" if idle[-1].get("screen") else ""))
            idle.clear()

    for i, r in enumerate(recs):
        if not r.get("choice"):
            idle.append(r)
            continue
        flush()
        scr = r.get("screen") or {}
        if i >= full_from or prev_screen is None:
            shown = f"screen={_trim(scr, 700)}"
        else:
            ch = {k: v for k, v in scr.items() if prev_screen.get(k) != v and not str(k).endswith("_prev")}
            shown = f"changed={_trim(ch, 360)}"
        prev_screen = scr
        lines.append(f"  tick {r.get('tick')} t={float(r.get('t') or t0) - t0:.2f} jev={r.get('jev_ms')} acted={r.get('acted_after_ms')}: {r.get('action')} "
                     f"[{r.get('choice')}{' ' + _trim(r.get('choices'), 80) if r.get('choices') else ''}] probs={_trim(r.get('action_probs'), 80)} "
                     f"beliefs={_trim(r.get('nouls'), 100)} rules={_trim(r.get('rules'), 140)} {shown}" + (f" sensor={str(r.get('sensor'))[:60]}" if r.get("sensor") else ""))
    flush()
    out = "\n".join(lines)
    if len(out) > max_chars:
        keep_head = lines[:3]
        body = lines[3:]
        while body and len("\n".join(keep_head + ["  …"] + body)) > max_chars:
            body.pop(0)
        out = "\n".join(keep_head + [f"  … ({len(lines) - 3 - len(body)} earlier lines cut)"] + body)
    return out


def history_text(history: list[dict[str, Any]], sig: str) -> str:
    """Earlier diagnoses, with what was tried for each cause and how it went; flags this loss as a repeat."""
    if not history:
        return "EARLIER DIAGNOSES: none (this is the first loss diagnosed for this pack)."
    same = [h for h in history if h.get("signature") == sig]
    lines = ["EARLIER DIAGNOSES (oldest first; reuse a cause_id when this loss has the same cause):"]
    for h in history[-12:]:
        tried = "; ".join(f"{t.get('fix_kind')}: {t.get('outcome')}" + (f" ({str(t.get('why'))[:90]})" if t.get("why") else "") for t in h.get("tried") or []) or "nothing tried"
        lines.append(f"- episode {h.get('episode')}: {h.get('cause_id')} [{h.get('fault') or h.get('category')}] {str(h.get('cause'))[:160]} → {tried}")
    if same:
        lines.append(f"THIS LOSS REPEATS: episodes {', '.join(str(h.get('episode')) for h in same)} ended with the same last decisions (signature {sig}).")
    return "\n".join(lines)


DIAGNOSE_RULES = (
    "You are diagnosing why an agent lost a game, BEFORE anyone changes its pack. The agent is a fixed decision model "
    "(it cannot be trained) that answers questions about a typed frame: the pack's reads computed from each screenshot. "
    "The loop around it is the pack: reads, rules, act_when (a gate: the agent only acts while it holds), settle, tick_hz, "
    "a play paragraph, questions, and compiler features that rank or time moves. Read the WHOLE episode: the fatal move "
    "is often fine and the fault is earlier. Check, in this order: (1) timing and turn order: did the agent act on a frame "
    "taken before the game had answered its previous move (marks or pieces that should alternate do not; a move landed "
    "while it was not the agent's turn; an action seemed to be ignored), or did the decider's answer land too late (its "
    "latency is longer than the time to the danger, though the right move was clear)? (2) perception: does a read disagree with the "
    "frames? (3) instruction: does the play paragraph or a question tell the agent something that contradicts the "
    "compiler's ranking or the rules (look at how often it took the first-ranked option and why it skipped it)? "
    "(4) compiler: would a feature the pack does not use (lookahead, a count read, a reflex, playouts) have changed the "
    "outcome? (5) strategy: was a decision bad given correct reads? Name ONE cause, with the ticks that show it. "
    "If the loss repeats and the cause you would name was already diagnosed and its fixes were rejected, or kept without "
    "the score improving, that cause is not what loses the game: name the next one on the list instead.\n"
    + "\n" + faults_text() + "\n"
    "Answer with one JSON object, no prose around it:\n"
    '{"cause_id": "<short-kebab-id, reuse an earlier one if this is the same cause>", "fault": "<' + "|".join(FAULTS) + '>", "category": "<' + "|".join(CATEGORIES) + '>", '
    '"cause": "<one sentence>", "evidence": [{"tick": <n>, "what": "<what the record shows at that tick>"}], '
    '"first_bad_tick": <n>, "fix_kind": "<' + "|".join(FIX_KINDS) + '>", "fix": "<one sentence: the change to the pack>"}')


def parse_diagnosis(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not d.get("cause"):
        return None
    d["fault"] = d.get("fault") if d.get("fault") in FAULTS else None
    d["category"] = d.get("category") if d.get("category") in CATEGORIES else (FAULTS[d["fault"]]["category"] if d["fault"] else "other")
    d["fix_kind"] = d.get("fix_kind") if d.get("fix_kind") in FIX_KINDS else "rule"
    d["cause_id"] = re.sub(r"[^a-z0-9-]+", "-", str(d.get("cause_id") or d["category"]).lower()).strip("-")[:48] or d["category"]
    ev = []
    for e in d.get("evidence") or []:
        if isinstance(e, dict) and isinstance(e.get("tick"), (int, float)):
            ev.append({"tick": int(e["tick"]), "what": str(e.get("what", ""))[:200]})
    d["evidence"] = ev
    if not isinstance(d.get("first_bad_tick"), (int, float)):
        d["first_bad_tick"] = ev[0]["tick"] if ev else None
    return d


def diagnose(chat, pack: Pack, recs: list[dict[str, Any]], frames: list[tuple[int, Any]] | None = None, history: list[dict[str, Any]] | None = None,
             log=lambda m: None) -> dict[str, Any]:
    """One chat call: the whole episode in, a named cause with evidence ticks out. `frames` are (tick, image) pairs to
    show (the last decisions'). Falls back to a cause naming the fatal tick when the answer does not parse."""
    from .author import _b64
    from .pack import dump_pack
    sig = signature(recs)
    text = (DIAGNOSE_RULES + "\n\n" + history_text(history or [], sig) + "\n\n" + episode_digest(pack, recs) + "\n\nTHE PACK:\n```yaml\n" + dump_pack({k: v for k, v in pack.raw.items() if k not in ("fingerprints", "lessons")}) + "\n```")
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for tick, img in (frames or [])[-3:]:
        parts.append({"type": "text", "text": f"frame at tick {tick}:"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(img)}})
    log(f"diagnose: asking {chat.model} about the whole episode ({len(recs)} ticks, signature {sig}) …")
    d = None
    try:
        out = chat.complete([{"role": "user", "content": parts}], max_tokens=4000, temperature=0.2)[0]
        d = parse_diagnosis(out)
    except Exception as e:  # noqa: BLE001
        log(f"diagnose: {str(e)[:120]}")
    if d is None:
        last = next((r for r in reversed(recs) if r.get("choice")), recs[-1] if recs else {})
        d = {"cause_id": "unknown", "category": "other", "cause": "no diagnosis parsed; the fatal decision is the only evidence", "evidence": [{"tick": int(last.get("tick") or 0), "what": "the fatal decision"}],
             "first_bad_tick": last.get("tick"), "fix_kind": "rule", "fix": "", "parsed": False}
    d["signature"] = sig
    d["repeats"] = sum(1 for h in (history or []) if h.get("signature") == sig or h.get("cause_id") == d["cause_id"])
    log(f"diagnose: {d['cause_id']} [{d['category']}{'/' + d['fault'] if d.get('fault') else ''}] {d['cause'][:160]} · evidence ticks {[e['tick'] for e in d['evidence']]} · fix {d['fix_kind']}: {str(d.get('fix'))[:120]}"
        + (f" · seen {d['repeats']}× before" if d["repeats"] else ""))
    return d


def diagnosis_text(d: dict[str, Any], history: list[dict[str, Any]] | None = None) -> str:
    """The diagnosis as the revision prompt's first section, with what was tried before for the same cause."""
    f = FAULTS.get(str(d.get("fault")))
    lines = [f"DIAGNOSIS (from reading the whole episode): cause {d['cause_id']} [{d['category']}]: {d['cause']}"
             + (f"\nFault kind: {d['fault']}. The feature that fixes it: {f['fix']}" + (f" The rewrite must make a {' or '.join(sorted(f['needs']))} change." if f["needs"] else "") if f else ""),
             "Evidence: " + "; ".join(f"tick {e['tick']}: {e['what']}" for e in d.get("evidence") or []),
             f"Proposed fix ({d.get('fix_kind')}): {d.get('fix')}"]
    before = [t for h in (history or []) if h.get("cause_id") == d["cause_id"] or h.get("signature") == d.get("signature") for t in (h.get("tried") or [])]
    if before:
        lines.append(f"This cause has been diagnosed {d.get('repeats', 0)} time(s) before. Already tried for it: "
                     + "; ".join(f"{t.get('fix_kind')} → {t.get('outcome')}" + (f" ({str(t.get('why'))[:100]})" if t.get("why") else "") for t in before[-6:])
                     + ". Do not repeat a change that was rejected or reverted; try a different kind of change.")
    return "\n".join(lines)
