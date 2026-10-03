"""The learn loop, second version: a loss is diagnosed over the whole episode before a rewrite is asked for, a rewrite may
add reads, gates and compiler options, a new read must parse on the recorded frames, and the rewrite is judged at the
ticks the diagnosis names (by replay, or by re-asking the decider where replay is blind)."""
import json
import os
import yaml
from anygame.pack import load_pack, load_pack_text, dump_pack, PackError
from anygame.perceive import count_of
from anygame.learn import (Bank, Decision, Incident, verify_v2, improve_v2, read_check, replay2, trial_verdict, change_kinds, blind_changes, outcome)
from anygame.diagnose import diagnose, episode_digest, parse_diagnosis, signature, resolve, ranking_stats, diagnosis_text
from test_learn import snake_incident, stripped, full, rec

ROOT = os.path.dirname(os.path.dirname(__file__))


def variant(base, **edit):
    raw = yaml.safe_load(dump_pack(base.raw))
    for k, v in edit.items():
        if k == "reads":
            raw["read"].update(v)
        else:
            raw[k] = v
    return load_pack_text(dump_pack(raw), base.name)


def test_count_read_counts_a_symbol_less_another_and_loads_in_a_pack():
    cells = {"c1r1": "X", "c2r1": ".", "c1r2": "O", "c2r2": "X"}
    assert count_of(cells, {"symbol": "X"}) == 2 and count_of(cells, {"symbol": "X", "minus": "O"}) == 1
    assert count_of(["X.", "OX"], {"symbol": "O"}) == 1 and count_of(None, {"symbol": "X"}) == 0
    p = variant(stripped(), reads={"snake_len": {"kind": "count", "in": "cells", "symbol": "s"}})
    r = replay2(p, snake_incident().decisions)
    assert [v["snake_len"] for v in r["values"]] == [2, 2, 2]
    try:
        variant(stripped(), reads={"bad": {"kind": "count", "in": "nope", "symbol": "s"}})
        assert False, "a count read on a missing grid must not load"
    except PackError as e:
        assert "count needs" in str(e)


def test_act_when_may_be_a_list_and_a_gate_that_holds_back_the_fatal_move_passes():
    inc = snake_incident()
    base = stripped()
    gated = variant(base, act_when=[{"read": "status", "equals": "playing"}, {"read": "head", "not": "c12r6"}])
    r = replay2(gated, inc.decisions)
    assert r["gated"] == [False, False, True]
    v = verify_v2(gated, base, inc)
    assert v["ok"] and "gate holds the agent back" in v["why"] and v["gate_open"] > 0.5, v
    never = variant(base, act_when=[{"read": "status", "equals": "paused"}])
    v2 = verify_v2(never, base, inc)
    assert not v2["ok"] and "act_when holds on only 0%" in v2["why"]


def test_rule_guard_still_passes_and_an_unchanged_pack_fails_at_the_evidence_ticks():
    inc = snake_incident()
    v = verify_v2(full(), stripped(), inc)
    assert v["ok"] and "rules change it" in v["why"]
    same = verify_v2(stripped(), stripped(), inc, {"evidence": [{"tick": 12, "what": "x"}], "first_bad_tick": 12})
    assert not same["ok"] and "evidence tick(s) (12, 20)" in same["why"]


def test_a_new_read_must_parse_on_the_recorded_frames():
    inc = snake_incident()
    base = stripped()
    nulls = variant(base, reads={"ghost": {"kind": "locate", "in": "cells", "symbol": "Z"}}, rules=[{"if": {"read": "ghost", "equals": "c1r1"}, "exclude": ["right"]}])
    rc = read_check(nulls, base, inc.decisions)
    assert not rc["ok"] and "'ghost' is null on 100%" in rc["why"]
    v = verify_v2(nulls, base, inc)
    assert not v["ok"] and "ghost" in v["why"]
    good = variant(base, reads={"snake_len": {"kind": "count", "in": "cells", "symbol": "s"}})
    assert read_check(good, base, inc.decisions)["ok"]


class Sensor:
    """Answers `up` when the paragraph says so, else what the recording said."""
    def __init__(self):
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        c = "up" if "turn before the wall" in state["how_to_play"] else "right"
        return {"answers": {"action": {"type": "choice", "choice": c, "probabilities": {c: 1.0}}}, "cost_usd": 0.0001}


def test_a_paragraph_change_is_judged_by_re_asking_the_decider_on_the_evidence_frames():
    inc = snake_incident()
    base = stripped()
    told = variant(base, play="Snake. Move toward the food; turn before the wall.")
    assert blind_changes(told, base) == ["play"] and change_kinds(told, base) == ["paragraph"]
    assert not verify_v2(told, base, inc)["ok"]                       # without a decider replay cannot see it
    s = Sensor()
    v = verify_v2(told, base, inc, sensor=s)
    assert v["ok"] and "re-asked" in v["why"] and s.calls == 1, v
    vague = variant(base, play="Snake. Move toward the food, carefully.")
    assert not verify_v2(vague, base, inc, sensor=Sensor())["ok"]


def test_a_ranking_change_moves_what_a_label_means():
    tetris = load_pack(os.path.join(ROOT, "packs", "tetris"))
    before = {"piece": {"landings": {"a": "rot0 col3: clears 0, holes +0", "b": "rot1 col8: clears 1, holes +0"}}}
    after = {"piece": {"landings": {"a": "rot1 col8: clears 1, holes +0", "b": "rot0 col3: clears 0, holes +0"}}}
    assert resolve(tetris, before, "place__option", "a") == "rot0 col3" and resolve(tetris, after, "place__option", "a") == "rot1 col8"
    recs = [{"tick": 1, "choice": "place", "choices": {"place__option": "a"}, "screen": before}, {"tick": 2, "choice": "place", "choices": {"place__option": "b"}, "screen": before}]
    st = ranking_stats(tetris, recs)
    assert "first-ranked option on 1 of 2" in st and "tick 2: took b" in st


def test_the_digest_shows_the_whole_episode_with_timing_and_the_diagnosis_repeats():
    base = stripped()
    recs = [{"tick": 1, "t": 10.0, "action": "wait", "reason": "settling (right)", "screen": {"status": "playing"}}]
    recs += [rec(k, "right", {"right": 0.8}, t=10.0 + k * 0.5, acted_after_ms=400, screen={"head": f"c{k}r6"}) for k in range(2, 14)]
    recs.append({"tick": 14, "t": 17.0, "action": "stop", "reason": "status is dead", "screen": {"status": "dead"}})
    dg = episode_digest(base, recs, full_last=3)
    assert "ended 'status is dead'" in dg and "tick 2 t=1.00 jev=200 acted=400" in dg and "changed={\"head\":\"c3r6\"}" in dg and "1× wait (settling (right))" in dg
    sig = signature(recs)
    assert sig == signature(list(recs)) and len(sig) == 10

    class Chat:
        model = "stub"
        def __init__(self): self.seen = []
        def complete(self, messages, max_tokens=0, temperature=0.0):
            self.seen.append(messages[0]["content"][0]["text"])
            return 'Here: {"cause_id": "Wall Crash", "category": "strategy", "cause": "it ran into the wall", "evidence": [{"tick": 13, "what": "head at c13r6"}], "fix_kind": "rule", "fix": "exclude right at the wall"}', {}, 1

    ch = Chat()
    d = diagnose(ch, base, recs, history=[])
    assert d["cause_id"] == "wall-crash" and d["first_bad_tick"] == 13 and d["repeats"] == 0 and "EARLIER DIAGNOSES: none" in ch.seen[0]
    hist = [{"episode": 3, "cause_id": "wall-crash", "category": "strategy", "cause": "x", "signature": sig, "tried": [{"fix_kind": "paragraph", "outcome": "rejected", "why": "acts as before"}]}]
    d2 = diagnose(ch, base, recs, history=hist)
    assert d2["repeats"] == 1 and "THIS LOSS REPEATS: episodes 3" in ch.seen[1]
    txt = diagnosis_text(d2, hist)
    assert "diagnosed 1 time(s) before" in txt and "paragraph → rejected" in txt
    assert parse_diagnosis("no json") is None and parse_diagnosis('{"cause": "c", "category": "weird"}')["category"] == "other"


def test_improve_v2_accepts_a_fix_of_the_diagnosed_kind_and_records_its_attempts():
    inc = snake_incident()
    base = stripped()
    asked = []

    class Chat:
        model = "stub"
        def __init__(self, ys): self.ys = list(ys)
        def complete(self, messages, max_tokens=0, temperature=0.0):
            asked.append(messages[-1]["content"])
            return "```yaml\n" + self.ys.pop(0) + "\n```", {}, 1

    diag = {"cause_id": "wall", "category": "strategy", "cause": "ran into the wall", "evidence": [{"tick": 20, "what": "x"}], "first_bad_tick": 20, "fix_kind": "rule", "fix": "guard"}
    recs = [d.rec for d in inc.decisions]
    res = improve_v2(Chat([dump_pack(base.raw), dump_pack(full().raw)]), base, inc, diag, recs)
    assert res["pack"] is not None and [a["outcome"] for a in res["attempts"]] == ["rejected", "accepted"]
    assert "DIAGNOSIS" in asked[0][0]["text"] and "kind: count" in asked[0][0]["text"] and "acts exactly as before" in asked[1]
    assert "rule" in res["attempts"][1]["fix_kinds"] and "read" in res["attempts"][1]["fix_kinds"]


def test_trial_verdict_by_outcome_then_by_the_median_episode(tmp_path):
    w = {"won": True, "lost": False, "ticks": 7, "tasks_done": 0, "score": None}
    t = {"won": False, "lost": False, "ticks": 9, "tasks_done": 0, "score": None}
    l = {"won": False, "lost": True, "ticks": 5, "tasks_done": 2, "score": None}
    assert trial_verdict([t, t, w], [t, t, l])[0] and not trial_verdict([l, t, t], [t, t, t])[0]
    ok, why = trial_verdict([dict(l, ticks=90)], [dict(l, ticks=40)])
    assert ok and "median episode 90 ticks" in why
    assert not trial_verdict([dict(l, ticks=30)], [dict(l, ticks=40)])[0]
    bank = Bank(tmp_path / "bank")
    inc = snake_incident()
    (tmp_path / "bank" / "episode-1.jsonl").write_text("".join(json.dumps(d.rec) + "\n" for d in inc.decisions) + json.dumps({"tick": 21, "action": "stop"}) + "\n")
    assert len(bank.episode_records(inc)) == 4
    bank.add_diagnosis({"cause_id": "c", "tried": [{"fix_kind": "gate", "outcome": "on trial", "version": 2}]})
    bank.label_diagnosis(2, "kept", "mean outcome +0.33")
    assert Bank(tmp_path / "bank").diagnoses[0]["tried"][0]["outcome"] == "kept"


def test_a_rewrite_must_make_the_kind_of_change_the_diagnosis_calls_for():
    from anygame.learn import fits_diagnosis
    assert fits_diagnosis(["rule"], {"category": "turn_order"}).startswith("the diagnosis is a turn_order fault")
    assert fits_diagnosis(["read", "gate"], {"category": "turn_order"}) == "" and fits_diagnosis(["rule"], {"category": "strategy"}) == ""
    assert fits_diagnosis(["rule"], {"category": "instruction"}) and not fits_diagnosis(["paragraph"], {"category": "instruction"})
    inc = snake_incident()

    class Chat:
        model = "stub"
        def complete(self, messages, max_tokens=0, temperature=0.0):
            return "```yaml\n" + dump_pack(variant(stripped(), rules=[{"if": {"read": "status", "equals": "dead"}, "exclude": ["right"]}]).raw) + "\n```", {}, 1

    res = improve_v2(Chat(), stripped(), inc, {"cause_id": "told", "category": "instruction", "cause": "the paragraph misleads", "evidence": [], "fix_kind": "paragraph", "fix": "reword"}, [d.rec for d in inc.decisions], rounds=1)
    assert res["pack"] is None and "instruction fault" in res["attempts"][0]["why"]


def test_a_score_read_decides_the_trial_before_how_long_a_lost_game_lasted():
    l = {"won": False, "lost": True, "tasks_done": 0}
    keep, why = trial_verdict([dict(l, ticks=187, score=11)], [dict(l, ticks=72, score=15), dict(l, ticks=71, score=15)])
    assert not keep and "median score 11" in why
    recs = [{"tick": 1, "screen": {"piece": {"lines_cleared": 4}}}, {"tick": 2, "screen": {"piece": {"lines_cleared": 9}}}, {"tick": 3, "action": "stop", "reason": "status is over", "screen": {"piece": "none"}}]
    assert outcome(recs, 1, 1, "piece.lines_cleared")["score"] == 9
