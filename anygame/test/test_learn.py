"""Learning from experience: episodes, incidents, and a revision that must replay better than the incumbent before it
is accepted. Snake boards are painted with the pack's own colours, so the reads are real. Mirrors ext/test/learn.test.mjs."""
import os
import numpy as np
import yaml
import pytest
from anygame.pack import load_pack, load_pack_text, dump_pack
from anygame.learn import (outcome, better_episode, median_episode, answers_of, incident_of, replay, verify_revision, improve,
                           incident_digest, Bank, Decision)

ROOT = os.path.dirname(os.path.dirname(__file__))
W, H = 540, 560


def _bgr(h):
    return (int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16))


def board(cells: dict[str, str]) -> np.ndarray:
    """A Snake screen: the board cells from {c<col>r<row>: symbol}, the status band blue."""
    f = np.full((H, W, 3), _bgr("#0b1020"), np.uint8)
    rect, grid = (0.0352, 0.0857, 0.9648, 0.9821), 12
    x0, y0 = rect[0] * W, rect[1] * H
    cw, rh = (rect[2] - rect[0]) * W / grid, (rect[3] - rect[1]) * H / grid
    colour = {".": "#1f2937", "s": "#4ade80", "H": "#16a34a", "F": "#ef4444"}
    for r in range(1, grid + 1):
        for c in range(1, grid + 1):
            sym = cells.get(f"c{c}r{r}", ".")
            f[round(y0 + (r - 1) * rh):round(y0 + r * rh), round(x0 + (c - 1) * cw):round(x0 + c * cw)] = _bgr(colour[sym])
    f[round(0.0125 * H):round(0.059 * H), round(0.752 * W):round(0.974 * W)] = _bgr("#3b82f6")
    return f


def rec(tick, choice, probs, **extra):
    return {"tick": tick, "screen": {}, "action": choice, "choice": choice, "action_probs": probs, "nouls": {"head_will_hit_something_if_straight": 0.2}, "rules": [], "jev_ms": 200, **extra}


def snake_incident():
    """Three decisions moving right along row 6; the third is at the right wall and still chooses right."""
    frames = [board({"c6r6": "H", "c5r6": "s", "c4r6": "s", "c9r6": "F"}), board({"c7r6": "H", "c6r6": "s", "c5r6": "s", "c9r6": "F"}),
              board({"c12r6": "H", "c11r6": "s", "c10r6": "s", "c3r3": "F"})]
    recs = [rec(10, "right", {"right": 0.8, "up": 0.1, "down": 0.1}), rec(12, "right", {"right": 0.8, "up": 0.1, "down": 0.1}), rec(20, "right", {"right": 0.6, "up": 0.3, "down": 0.1})]
    return incident_of([Decision(r, f) for r, f in zip(recs, frames)], "status is dead", 21)


def snake_yaml():
    return open(os.path.join(ROOT, "packs", "snake", "pack.yaml")).read()


def stripped():
    """The Snake pack without its guard: no around read, no rules, no OCR score (keeps the test fast)."""
    raw = yaml.safe_load(snake_yaml())
    del raw["read"]["head_around"]; del raw["read"]["score"]; raw["rules"] = []; raw["tests"] = []
    raw["play"] = "Snake. Move toward the food."
    return load_pack_text(dump_pack(raw), "snake-stripped")


def full():
    raw = yaml.safe_load(snake_yaml())
    del raw["read"]["score"]; raw["tests"] = []
    return load_pack_text(dump_pack(raw), "snake")


def test_episodes_outcome_ordering_and_bank(tmp_path):
    lost_short = outcome([rec(1, "up", {}), {"tick": 2, "action": "stop", "reason": "status is dead", "screen": {"score": 30}, "total_cost_usd": 0.001}], 1, 1, "score")
    lost_long = outcome([rec(i + 1, "up", {}) for i in range(40)] + [{"tick": 41, "action": "stop", "reason": "status is dead", "screen": {"score": 90}}], 2, 1, "score")
    survived = outcome([rec(i + 1, "up", {}) for i in range(10)], 3, 2, "score")
    won = outcome([{"tick": 1, "action": "stop", "reason": "status is won", "screen": {}}], 4, 2)
    assert lost_short["lost"] and lost_short["score"] == 30 and not lost_short["won"]
    assert won["won"] and not won["lost"]
    assert better_episode(lost_short, lost_long) and not better_episode(lost_long, lost_short)
    assert better_episode(lost_long, survived) and better_episode(survived, won)
    assert median_episode([lost_short, lost_long, survived])["n"] == 2
    bank = Bank(tmp_path / "bank", max_incidents=2)
    for e in (lost_short, lost_long, survived, won):
        bank.add_episode(e)
    for _ in range(3):
        bank.add_incident(snake_incident())
    assert len(Bank(tmp_path / "bank").episodes) == 4 and len(list((tmp_path / "bank").glob("incident-*"))) == 2
    inc = bank.load_incident(tmp_path / "bank" / "incident-3")
    assert inc.reason == "status is dead" and len(inc.decisions) == 3 and inc.decisions[2].frame.shape == (H, W, 3)


def test_replay_pushes_recorded_answers_through_reads_and_rules():
    inc = snake_incident()
    a = answers_of(inc.decisions[2].rec)
    assert a["action"]["choice"] == "right" and a["head_will_hit_something_if_straight"]["noul"] == 0.2
    r = replay(full(), inc)
    assert all(s >= 0.9 for s in r["support"]), r["support"]
    assert r["values"][2]["head"] == "c12r6" and r["values"][2]["head_around"]["right"] == "wall" and r["values"][2]["head_moving"] == "right"
    assert r["choices"][:2] == ["right", "right"] and r["choices"][2] != "right"
    assert any("not right" in x for x in r["applied"][2]), r["applied"][2]


def test_verify_accepts_guarded_or_visible_and_rejects_unchanged_blunt_and_blind():
    inc = snake_incident()
    incumbent = stripped()
    v = verify_revision(full(), incumbent, inc)
    assert v["ok"] and v["guarded"] and any(k.startswith("head_around") for k in v["distinguished"]) and v["overblocked"] == 0
    same = verify_revision(stripped(), incumbent, inc)
    assert not same["ok"] and "neither" in same["why"]
    raw = yaml.safe_load(dump_pack(incumbent.raw)); raw["rules"] = [{"if": {"read": "status", "equals": "playing"}, "exclude": ["right"]}]
    blunt = verify_revision(load_pack_text(dump_pack(raw), "blunt"), incumbent, inc)
    assert not blunt["ok"] and "blocks 2 of 2" in blunt["why"]
    raw2 = yaml.safe_load(dump_pack(full().raw)); raw2["read"]["cells"]["options"] = {".": "#ffffff", "s": "#ff00ff", "H": "#00ffff", "F": "#ffff00"}
    blind = verify_revision(load_pack_text(dump_pack(raw2), "blind"), incumbent, inc)
    assert not blind["ok"] and "reads the incident screens worse" in blind["why"]
    raw3 = yaml.safe_load(dump_pack(incumbent.raw)); raw3["read"]["head_around"] = {"kind": "around", "of": "head", "in": "cells", "free": [".", "F"]}
    visible = verify_revision(load_pack_text(dump_pack(raw3), "visible"), incumbent, inc)
    assert visible["ok"] and not visible["guarded"] and "head_around.right" in visible["distinguished"]


def test_improve_takes_the_revision_only_when_it_replays_better():
    inc = snake_incident()
    incumbent = stripped()
    digest = incident_digest(inc, [outcome([{"tick": 3, "action": "stop", "reason": "status is dead", "screen": {}}], 1, 1)])
    assert "FATAL tick 20" in digest and "EPISODES so far" in digest
    asked = []

    class Stub:
        model = "stub"
        def __init__(self, text): self.text = text
        def complete(self, messages, max_tokens=0, temperature=0.0):
            asked.append(messages[0]["content"]); return self.text, {}, 1

    good = improve(Stub("```yaml\n" + dump_pack(full().raw) + "\n```"), incumbent, inc)
    assert good["pack"] is not None and good["verdict"]["ok"]
    assert any(p["type"] == "image_url" for p in asked[0]) and "grow the TYPED FRAME" in asked[0][0]["text"]
    bad = improve(Stub("```yaml\n" + dump_pack(incumbent.raw) + "\n```"), incumbent, inc)
    assert bad["pack"] is None and not bad["verdict"]["ok"]
    none = improve(Stub("no yaml here"), incumbent, inc)
    assert none["pack"] is None and none["verdict"] is None


def test_calibrator_learns_from_the_trial_record_and_rejects_what_reverted_before():
    from anygame.learn import Calibrator, revision_features, FEATURES
    # a history: revisions that block ordinary decisions were reverted on trial, tight ones were kept
    hist = []
    for k in range(5):
        hist.append({"version": k, "features": {"guarded": 1, "distinguished": 0, "overblocked": 0.25 + 0.02 * k, "support": 1.0, "rules_added": 1, "reads_added": 0, "questions_added": 0, "play_changed": 0}, "kept": False})
        hist.append({"version": 10 + k, "features": {"guarded": 1, "distinguished": 1, "overblocked": 0.0, "support": 1.0, "rules_added": 1, "reads_added": 1, "questions_added": 0, "play_changed": 0}, "kept": True})
    idle = Calibrator(hist[:3])
    assert not idle.active and idle.judge(hist[0]["features"])[0] is True
    cal = Calibrator(hist)
    assert cal.active
    loose = dict(hist[0]["features"], overblocked=0.3)
    tight = dict(hist[1]["features"])
    assert cal.p_keep(tight) > 0.6 and cal.p_keep(loose) < 0.35
    assert cal.judge(tight)[0] and not cal.judge(loose)[0]
    # features of a real revision: the full snake pack against the stripped one
    inc = snake_incident()
    from anygame.learn import verify_revision
    v = verify_revision(full(), stripped(), inc)
    f = revision_features(v, full(), stripped())
    assert set(f) == set(FEATURES) and f["guarded"] == 1 and f["rules_added"] >= 10 and f["reads_added"] == 1 and f["play_changed"] == 1


def test_lessons_and_hints_and_the_bank_trial_record(tmp_path):
    from anygame.learn import lessons_of, hints_text, Bank
    ls = lessons_of(full(), stripped(), "status is dead")
    assert any(l["kind"] == "rule" for l in ls) and any(l["kind"] == "read" and "head_around" in l["yaml"] for l in ls)
    txt = hints_text(ls, {"color", "locate", "around"})
    assert "PATTERNS THAT SURVIVED" in txt and "around" in txt
    assert hints_text(ls, {"bar", "ocr"}).count("kind: around") == 0    # a read on a kind this pack lacks is left out
    assert hints_text([]) == ""
    bank = Bank(tmp_path / "bank")
    bank.add_revision(2, {"guarded": 1, "overblocked": 0.0}, "rule now excludes right")
    assert bank.revisions[-1]["kept"] is None and not bank.calibrator().active
    bank.record_trial(2, True, kept_pack=full(), before=stripped(), reason="status is dead")
    assert bank.revisions[-1]["kept"] is True and len(bank.lessons) >= 2
    again = Bank(tmp_path / "bank")
    assert again.revisions[-1]["kept"] is True and len(again.lessons) == len(bank.lessons)


def test_clm_sensor_speaks_the_systemone_protocol_against_the_stub():
    import subprocess, sys, time, socket
    from anygame.sensors import open_sensor
    port = 8790
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "clm_stub.py"), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError:
                time.sleep(0.1)
        s = open_sensor(f"clm:http://127.0.0.1:{port}", timeout=2.0)
        res = s.ask({"screen": {"head_around": {"right": "wall"}, "food": "up"}}, {
            "action": {"type": "choice", "instructions": "which way", "criteria": {"up": "toward food", "right": "into the wall", "keep": "straight"}},
            "danger": {"type": "noul", "instructions": "is death near?", "criteria": {"true": "yes", "false": "no"}}})
        assert res["answers"]["action"]["choice"] == "up" and abs(sum(res["answers"]["action"]["probabilities"].values()) - 1) < 1e-6
        assert res["answers"]["danger"]["type"] == "noul" and res["server_ms"] is not None and res["latency_ms"] < 2000
        # the loop runs on it: the state-driven snake pack, three ticks, rules still guard the wall
        pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
        s1 = {"snake": [[6, 6], [5, 6], [4, 6]], "food": [9, 2], "score": 0, "over": False}
        s2 = {"snake": [[11, 6], [10, 6], [9, 6]], "food": [9, 2], "score": 0, "over": False}
        from test_state import StateDevice
        from anygame.loop import Agent
        dev = StateDevice([s1, s2, s2])
        ag = Agent(pack, dev, s)
        r1, r2 = ag.step(), ag.step()
        assert r1["jev_ms"] is not None and r2["screen"]["head"] == "c12r7" and r2["choice"] != "right"
    finally:
        srv.terminate()


def test_requery_asks_the_decider_again_with_the_candidate_frame():
    import subprocess, sys, time, socket
    from anygame.sensors import open_sensor
    from anygame.learn import requery
    port = 8791
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "clm_stub.py"), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError:
                time.sleep(0.1)
        s = open_sensor(f"clm:http://127.0.0.1:{port}", timeout=2.0)
        inc = snake_incident()
        # the stub picks the first option named in the state text: with the stripped pack the frame has no "wall"/"up"
        # cue, so it keeps choosing the first option; with the full pack the rules exclude "right" at the wall
        r_full = requery(s, full(), inc)
        assert len(r_full["choices"]) == 3 and r_full["fatal_avoided"] and r_full["choices"][2] != "right"
        assert 0.0 <= r_full["agreement"] <= 1.0 and r_full["cost_usd"] >= 0
    finally:
        srv.terminate()


def test_question_audit_and_relevance_and_predict_read():
    from anygame.learn import audit_questions, relevance, relevance_text
    inc = snake_incident()
    aud = audit_questions(full(), inc.decisions)
    assert "head_will_hit_something_if_straight" in aud and aud["head_will_hit_something_if_straight"]["consumed_by_a_rule"] is False
    assert aud["head_will_hit_something_if_straight"]["verdict"].startswith("no rule reads it")
    # a pack whose rule consumes the noul: forcing it changes the action on the healthy ticks
    raw = yaml.safe_load(dump_pack(full().raw)); raw["rules"].append({"if": {"noul": "head_will_hit_something_if_straight", "gte": 0.5}, "exclude": ["keep", "$head_moving"]})
    aud2 = audit_questions(load_pack_text(dump_pack(raw), "snake"), inc.decisions)
    assert aud2["head_will_hit_something_if_straight"]["consumed_by_a_rule"] and aud2["head_will_hit_something_if_straight"]["changes_action"] >= 1
    # relevance: a read that tracks the coming loss and that the decider never acts on scores a large gap
    recs = []
    for t in range(1, 31):
        near = t >= 27
        recs.append({"tick": t, "jev_ms": 100, "choice": "right", "screen": {"wall_ahead": near, "food": "c3r3", "noise": t % 2}})
    recs.append({"tick": 31, "action": "stop", "reason": "status is dead", "screen": {}})
    rel = relevance(recs)
    top = rel[0]
    assert top["read"] == "wall_ahead" and top["danger"] > 0.3 and top["attention"] == 0.0
    assert "wall_ahead" in relevance_text(rel) and relevance([]) == []
    # predict: the head's next cell from its last displacement
    from anygame.loop import _predict
    assert _predict("c7r7", "c6r7") == "c8r7" and _predict("c7r7", "c7r8", 2) == "c7r5" and _predict("c7r7", None) is None
    raw3 = yaml.safe_load(dump_pack(full().raw)); raw3["read"]["head_next"] = {"kind": "predict", "of": "head"}
    pk = load_pack_text(dump_pack(raw3), "snake")
    from anygame.learn import replay
    r = replay(pk, inc)
    assert r["values"][1]["head_next"] == "c8r6" and r["values"][0].get("head_next") is None
    with pytest.raises(Exception):
        raw4 = yaml.safe_load(dump_pack(full().raw)); raw4["read"]["food_next"] = {"kind": "predict", "of": "food"}; load_pack_text(dump_pack(raw4), "x")
