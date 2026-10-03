"""Learning from experience: episodes, incidents, and a revision that must replay better than the incumbent before it
is accepted. Snake boards are painted with the pack's own colours, so the reads are real. Mirrors ext/test/learn.test.mjs."""
import json
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
    del raw["read"]["head_around"]; del raw["read"]["score"]; raw["rules"] = []; raw["tests"] = []; raw.pop("tasks", None)
    raw["play"] = "Snake. Move toward the food."
    return load_pack_text(dump_pack(raw), "snake-stripped")


def full():
    raw = yaml.safe_load(snake_yaml())
    del raw["read"]["score"]; raw["tests"] = []; raw.pop("tasks", None)
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


def _stub(port):
    import subprocess, sys, time, socket
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "clm_stub.py"), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
        except OSError:
            time.sleep(0.1)
    return srv


def test_counterfactual_return_truncates_at_divergence_and_counts_only_owned_losses():
    from anygame.learn import counterfactual, counterfactual_summary, logged_policy
    inc = snake_incident()
    # the logged policy: Jev's probabilities over what the rules allowed (a '… → not X' line removes X)
    r = dict(rec(5, "left", {"right": 0.5, "left": 0.3, "up": 0.2}, rules=["head_around.right=wall → not right", "→ left"]))
    lp = logged_policy(r)
    assert "right" not in lp and abs(lp["left"] - 0.6) < 1e-6 and abs(sum(lp.values()) - 1) < 1e-9
    # a candidate identical to the incumbent walks the same path: it owns the loss with weight ~1
    same = [{"right": 0.8, "up": 0.1, "down": 0.1}, {"right": 0.8, "up": 0.1, "down": 0.1}, {"right": 0.6, "up": 0.3, "down": 0.1}]
    c1 = counterfactual(inc, same)
    assert c1["lost"] and c1["diverged_at"] is None and abs(c1["loss_weight"] - 1.0) < 1e-6
    # a candidate whose rules exclude the fatal move: ratio 0 at the fatal tick, loss not owned
    guarded = same[:2] + [{"up": 0.75, "down": 0.25}]
    c2 = counterfactual(inc, guarded)
    assert c2["loss_weight"] == 0.0 and c2["reached_end"]
    # a candidate that would have turned earlier: the logged path says nothing past that tick (truncation)
    early = [{"right": 0.8, "up": 0.1, "down": 0.1}, {"up": 0.9, "right": 0.02, "down": 0.08}, {"right": 0.6, "up": 0.3, "down": 0.1}]
    c3 = counterfactual(inc, early)
    assert c3["diverged_at"] == 12 and c3["loss_weight"] == 0.0 and len(c3["ratios"]) == 2
    # a candidate that likes the logged path more than the incumbent did is clipped at the cap
    keen = [{"right": 1.0}, {"right": 1.0}, {"right": 1.0}]
    assert counterfactual(inc, keen, cap=2.0)["loss_weight"] == 2.0
    # a failed re-query is a neutral step, never a divergence
    assert counterfactual(inc, [None, None, None])["loss_weight"] == 1.0
    s = counterfactual_summary([c1, c2, c3])
    assert s["n"] == 3 and s["incumbent_loss"] == 1.0 and abs(s["candidate_loss"] - 1 / 3) < 1e-3 and s["walks_into"] == 1 and s["diverged"] == 1 and s["ess"] == 1.0
    # a won incident contributes no loss whatever the weights
    won = incident_of(inc.decisions, "status is won", 21)
    assert counterfactual(won, same)["loss_weight"] == 0.0 and not counterfactual(won, same)["lost"]


def test_holdout_check_order_audit_and_the_gates_against_the_stub(tmp_path):
    from anygame.sensors import open_sensor
    from anygame.learn import holdout_check, audit_order, order_text, counterfactual_return, Bank, action_orders
    srv = _stub(8792)
    try:
        s = open_sensor("clm:http://127.0.0.1:8792", timeout=2.0)
        inc = snake_incident()
        # the bank keeps held-out ordinary ticks with their frames, newest first, capped
        bank = Bank(tmp_path / "bank")
        bank.add_holdout(inc.decisions[:2], max_holdout=3)
        bank.add_holdout(inc.decisions[:2], max_holdout=3)
        ho = Bank(tmp_path / "bank").holdout()
        assert len(ho) == 3 and ho[-1].rec["tick"] == 12 and ho[0].frame.shape == inc.decisions[0].frame.shape
        # the stub picks the first option named in the state text; with the full pack the rules shape the final choice
        h = holdout_check(s, full(), ho)
        assert h["n"] == 3 and 0.0 <= h["agreement"] <= 1.0 and all({"tick", "was", "now"} <= set(f) for f in h["flips"])
        assert holdout_check(s, full(), [])["n"] == 0
        # the order A/B: four distinct orders, each measured on the same banked decisions, best (fewest unsafe picks) first
        orders = action_orders(full())
        assert len(orders) == 4 and {n for n, _ in orders} == {"as authored", "reversed", "alphabetical", "shuffled"}
        res = audit_order(s, full(), inc.decisions, fatal={20})
        assert len(res) == 4 and all(0 <= o["unsafe"] <= 1 and 0 <= o["first_pick"] <= 1 and o["n"] == 3 and o["fatal_repeated"] is not None for o in res)
        assert res == sorted(res, key=lambda o: (o["unsafe"], o["fatal_repeated"] or 0.0, -o["agreement"]))
        assert isinstance(order_text(res), str)
        # the counterfactual over several banked incidents, the first one's re-query reused
        inc2 = incident_of(inc.decisions, "status is dead", 40)
        cf = counterfactual_return(s, full(), [inc, inc2], requeried={0: [{"right": 1.0}] * 3})
        assert cf["n"] == 2 and cf["per_incident"][0]["loss_weight"] >= 1.0 and cf["per_incident"][1]["loss_weight"] == 0.0 and cf["cost_usd"] >= 0
        # improve with the sensor: the gates are reported in the verdict, and a drifting revision is refused
        class _Chat:
            model = "fake"
            def __init__(self, text): self.text = text
            def complete(self, messages, **kw): return (self.text, 0.0)
        log = []
        # (the stub disagrees with the recorded choices by design, so both agreement floors are off for the accepting call)
        out = improve(_Chat("```yaml\n" + dump_pack(full().raw) + "\n```"), stripped(), inc, log=log.append, sensor=s, rounds=1, holdout=ho, others=[inc2], min_agreement=0.0, min_holdout=0.0)
        assert out["pack"] is not None and out["verdict"]["counterfactual"]["n"] == 2 and "holdout" in out["verdict"] and out["features"]["cf_loss"] < 1.0 and 0 <= out["features"]["holdout_agreement"] <= 1
        out2 = improve(_Chat("```yaml\n" + dump_pack(full().raw) + "\n```"), stripped(), inc, log=log.append, sensor=s, rounds=1, holdout=ho, min_agreement=0.0, min_holdout=1.01)
        assert out2["pack"] is None and any("held-out" in m for m in log)
    finally:
        srv.terminate()


def test_order_only_revision_needs_a_sensor_and_the_feature_marks_it():
    from anygame.learn import revision_features
    inc = snake_incident()
    base = full()
    raw = yaml.safe_load(dump_pack(base.raw)); raw["act"] = list(reversed(raw["act"]))
    reordered = load_pack_text(dump_pack(raw), "snake")
    assert not verify_revision(reordered, base, inc)["ok"]
    v = verify_revision(reordered, base, inc, allow_order=True)
    assert v["ok"] and v.get("order_changed") and not v["guarded"]
    assert revision_features(v, reordered, base)["order_changed"] == 1.0 and revision_features(v, base, base)["order_changed"] == 0.0


def test_conformal_floor_vetoes_only_what_the_kept_revisions_justify():
    from anygame.learn import Calibrator
    good = lambda i: {"guarded": 1.0, "distinguished": 2.0, "overblocked": 0.0, "support": 1.0, "rules_added": 1.0, "reads_added": 1.0, "requery_avoided": 1.0, "requery_agreement": 0.9, "holdout_agreement": 0.9 - i * 0.01}
    bad = lambda i: {"guarded": 0.0, "distinguished": 0.0, "overblocked": 0.3 + i * 0.02, "support": 0.8, "rules_added": 3.0, "reads_added": 0.0, "requery_avoided": 0.0, "requery_agreement": 0.5, "holdout_agreement": 0.5}
    rows = [{"features": good(i), "kept": True} for i in range(5)] + [{"features": bad(i), "kept": False} for i in range(5)]
    c = Calibrator(rows)
    assert c.active and c.conformal is not None and c.n_kept == 5
    # k = floor(0.25 * 6) = 1: the floor is the smallest leave-one-out score among the kept rows, so each kept row clears it
    loo = [Calibrator._p(r["features"], *Calibrator._fit(rows[:i] + rows[i + 1:])) for i, r in enumerate(rows) if r["kept"]]
    assert abs(c.floor - min(min(loo), 0.9)) < 1e-9 and 0 < c.floor < 1
    ok, why = c.judge(good(9)); assert ok and "conformal floor" in why
    ok, why = c.judge(bad(9)); assert not ok
    # with two kept rows the floor is 0: nothing is vetoed, the trial decides
    few = rows[:2] + rows[5:]
    c2 = Calibrator(few)
    assert c2.active and c2.floor == 0.0 and c2.judge(bad(9))[0] and "no floor yet" in c2.judge(bad(9))[1]
    # alpha=None keeps the fixed floor
    c3 = Calibrator(rows, alpha=None)
    assert c3.conformal is None and c3.floor == 0.35


def test_margin_read_and_the_per_tick_budget():
    from anygame.perceive import margin_of, margin_num
    from anygame.learn import replay
    cells = {f"c{c}r{r}": "." for c in range(1, 7) for r in range(1, 7)}
    # a pocket: the head at c2r1 with the body walling off the top-left corner except one cell
    for k in ("c1r2", "c2r2", "c3r2", "c3r1"):
        cells[k] = "s"
    cells["c2r1"] = "H"
    m = margin_of("c2r1", cells, {"free": [".", "F"], "lag": 0})
    assert m["left"] == 1 and m["right"] == 0 and m["up"] == 0 and m["down"] == 0 and m["now"] == 1 and m["safe"] == ["left"] and m["best"] == "left"
    # open board: with lag 1 the mover advances a cell while we think; the reachable room is the board minus the path
    cells2 = {f"c{c}r{r}": "." for c in range(1, 7) for r in range(1, 7)}
    cells2["c3r3"] = "H"
    m2 = margin_of("c3r3", cells2, {"free": ["."], "lag": 1})
    assert m2["now"] == 35 and m2["right"] == 34 and m2["right_ok"] and set(m2["safe"]) == {"up", "down", "left", "right"}
    # with lag 2 going up runs into the wall on the way: death that way, not ok
    m3 = margin_of("c3r3", cells2, {"free": ["."], "lag": 2})
    assert m3["up"] == 0 and not m3["up_ok"] and m3["down"] > 0
    assert margin_of(None, cells2, {}) is None and margin_num(7, {"lower": 0, "upper": 10}) == 3 and margin_num("x", {"lower": 0}) is None
    # in a pack: a rule on the margin excludes the move into the pocket at replay time
    raw = yaml.safe_load(dump_pack(full().raw))
    raw["read"]["room"] = {"kind": "margin", "of": "head", "in": "cells", "free": [".", "F"], "lag": 1}
    raw["rules"].append({"if": {"read": "room.right_ok", "equals": False}, "exclude": ["right"]})
    pk = load_pack_text(dump_pack(raw), "snake")
    r = replay(pk, snake_incident())
    assert r["values"][2]["room"]["right"] == 0 and r["choices"][2] != "right"
    with pytest.raises(Exception):
        raw2 = yaml.safe_load(dump_pack(full().raw)); raw2["read"]["bad"] = {"kind": "margin", "of": "head"}; load_pack_text(dump_pack(raw2), "x")
    # the budget: a sensor that reports 500 ms is skipped when perception + expected latency exceeds budget_ms, at most
    # budget_skip_max ticks in a row, and the rules act on its last answers meanwhile
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from test_state import StateDevice
    class Slow:
        model = "slow"
        def __init__(self): self.calls = 0
        def ask(self, state, qs):
            self.calls += 1
            crit = list(qs["action"]["criteria"])
            return {"answers": {"action": {"type": "choice", "choice": "right", "probabilities": {c: (0.9 if c == "right" else 0.1 / (len(crit) - 1)) for c in crit}}}, "latency_ms": 500, "input_tokens": 10, "cost_usd": 0.0}
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    pack.raw["budget_ms"], pack.raw["budget_skip_max"] = 100, 2
    states = [{"snake": [[3 + i, 6], [2 + i, 6], [1 + i, 6]], "food": [9, 2], "score": 0, "over": False} for i in range(6)]
    slow = Slow()
    ag = Agent(pack, StateDevice(states), slow)
    recs = [ag.step() for _ in range(6)]
    skipped = [r.get("skipped") == "budget" for r in recs]
    assert slow.calls == 2 and skipped == [False, True, True, False, True, True] and ag.skipped_budget == 4
    assert all(r["choice"] for r in recs) and all("rules on last answers" in r["sensor"] for r in recs if r.get("skipped"))


def test_tasks_in_the_pack_the_loop_tracks_them_and_successes_are_banked_and_kept_allowed(tmp_path):
    from anygame.learn import Bank, Incident, outcome
    from anygame.loop import Agent
    from anygame.pack import load_pack, check_tasks, PackError
    from anygame.tasks import task_stats, choose_order, weakest_categories, tasks_text
    from test_state import StateDevice
    # schema: done is required and must name a read; defaults are filled
    reads = {"score": {"kind": "json", "path": "score"}, "head": {"kind": "locate", "in": "x", "symbol": "H"}}
    t = check_tasks([{"id": "ten", "instruction": "reach 10", "done": {"read": "score", "gte": 10}}], reads)[0]
    assert t["done"] == [{"read": "score", "gte": 10}] and t["limit_ticks"] == 150 and t["hold_ticks"] == 1 and t["category"] == "other"
    with pytest.raises(PackError):
        check_tasks([{"id": "x", "instruction": "?", "done": {"read": "nope", "equals": 1}}], reads)
    with pytest.raises(PackError):
        check_tasks([{"id": "x", "instruction": "?"}], reads)
    # the loop: the state snake with two tasks; the score read makes the first done, the second times out
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    pack.raw["tasks"] = [{"id": "score_ten", "instruction": "eat until the score reaches 10", "done": {"read": "score", "gte": 10}, "category": "score", "limit_ticks": 20},
                         {"id": "go_right", "instruction": "move the head to column 12", "done": {"read": "head", "equals": "c12r7"}, "category": "navigate", "limit_ticks": 2}]
    from anygame.pack import load_pack_text, dump_pack
    pack = load_pack_text(dump_pack(pack.raw), "snake-state")
    assert [t["id"] for t in pack.tasks] == ["score_ten", "go_right"]
    states = [{"snake": [[3 + i, 6], [2 + i, 6], [1 + i, 6]], "food": [9, 2], "score": 0 if i < 2 else 10, "over": False} for i in range(6)]
    from anygame.sensors import RandomSensor
    events = []
    ag = Agent(pack, StateDevice(states), RandomSensor(1))
    ag.on_task = events.append
    recs = [ag.step() for _ in range(6)]
    assert recs[0]["task_started"] == "score_ten" and recs[0]["task"] == "score_ten"
    assert recs[2].get("task_done") == "score_ten" and events[0]["outcome"] == "done" and events[0]["category"] == "score" and events[0]["ticks"] == 2
    assert recs[3]["task_started"] == "go_right" and recs[5].get("task_failed") == "go_right" and events[1]["outcome"] == "failed"
    assert any(r.get("task") for r in recs) and ag.task_log[-1]["id"] == "go_right"
    # a task that failed twice this run is not retried a third time (task_attempts, default 2)
    for _ in range(4):
        ag.step()
    assert sum(1 for e in ag.task_log if e["id"] == "go_right" and e["outcome"] == "failed") == 2 and ag.task is None
    # the decider is told the task beside the play notes
    seen = []
    class Spy(RandomSensor):
        def ask(self, state, qs):
            seen.append(state.get("task")); return super().ask(state, qs)
    ag2 = Agent(pack, StateDevice(states), Spy(1)); ag2.step()
    assert seen and seen[0] == "eat until the score reaches 10"
    # outcome counts tasks; more tasks done ranks above surviving longer
    ep = outcome(recs, 1, 1, "score")
    assert ep["tasks_done"] == 1 and ep["tasks_failed"] == 1
    assert better_episode({"won": False, "lost": False, "ticks": 400, "score": 0, "tasks_done": 0}, {"won": False, "lost": True, "ticks": 50, "score": 0, "tasks_done": 1})
    # the record: stats, the setter's order prefers the weakest category, the prompt line
    bank = Bank(tmp_path / "bank")
    for ev in events:
        bank.add_task_result(ev, 1, 1)
    bank.add_task_result({**events[1], "outcome": "failed"}, 1, 2)
    st = task_stats(Bank(tmp_path / "bank").task_results)
    assert st["tasks"]["score_ten"]["rate"] == 1.0 and st["categories"]["navigate"]["rate"] == 0.0 and st["tasks"]["go_right"]["attempts"] == 3
    assert choose_order(pack.tasks, bank.task_results)[0] == "go_right" and "navigate" in weakest_categories(bank.task_results, pack.tasks)
    assert "score_ten [score] 1/1" in tasks_text(pack.tasks, bank.task_results)
    # positive incidents: a success span is banked with its kind, listed apart from losses, and a revision that
    # blocks a choice in it is refused by replay
    inc = snake_incident()
    good = Incident("done: eat_three", 30, inc.decisions[:2], kind="success")
    bank.add_incident(inc); bank.add_incident(good)
    assert len(bank.incidents()) == 1 and len(bank.successes()) == 1 and bank.successes()[0].kind == "success" and len(bank.incidents(None)) == 2
    raw = yaml.safe_load(dump_pack(full().raw)); raw["rules"].append({"if": {"read": "head_moving", "equals": "right"}, "exclude": ["right"]})   # breaks the successful 'right's
    blunt = load_pack_text(dump_pack(raw), "snake")
    v = verify_revision(blunt, stripped(), inc, successes=[good])
    assert not v["ok"] and "completed a task" in v["why"]
    assert verify_revision(full(), stripped(), inc, successes=[good])["ok"]
    # the per-kind cap keeps the newest of each kind
    b2 = Bank(tmp_path / "bank2", max_incidents=1)
    b2.add_incident(inc); b2.add_incident(good); b2.add_incident(incident_of(inc.decisions, "status is dead", 99))
    assert len(b2.incidents()) == 1 and b2.incidents()[0].tick == 99 and len(b2.successes()) == 1


def test_task_setter_validates_the_model_s_proposals():
    from anygame.tasks import propose_tasks
    from anygame.pack import load_pack
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    values = {"score": 0, "head": "c3r7", "status": "playing"}
    class _Chat:
        model = "fake"
        def complete(self, messages, **kw):
            assert any(isinstance(m.get("content"), list) for m in messages)
            return ('[{"id": "Score Five!", "instruction": "reach 5", "done": {"read": "score", "gte": 5}, "category": "score", "limit_ticks": 40},'
                    ' {"id": "bogus", "instruction": "?", "done": {"read": "nothing", "equals": 1}},'
                    ' {"id": "already", "instruction": "be playing", "done": {"read": "status", "equals": "playing"}},'
                    ' {"id": "list", "instruction": "two", "done": [{"read": "score", "gte": 1}, {"read": "head", "not": "c3r7"}], "category": "weird"},'
                    ' {"id": "go_there", "instruction": "reach the food cell", "done": {"read": "head", "equals": "c9r3"}}]', {}, 0)
    log = []
    new = propose_tasks(_Chat(), pack, np.zeros((560, 540, 3), np.uint8), values, [], k=5, log=log.append)
    assert [t["id"] for t in new] == ["score_five", "list"] and new[1]["category"] == "other" and len(new[1]["done"]) == 2
    assert any("bogus" in m for m in log) and any("already done" in m for m in log) and any("exact cell" in m for m in log)


def test_rater_samples_frames_parses_scores_and_calibrates_against_the_trial_order():
    from anygame.rater import sample_frames, actions_summary, rate_episode, calibrate
    frames = [(t, np.zeros((4, 4, 3), np.uint8)) for t in range(1, 101)]
    picked = sample_frames(frames, 10)
    assert len(picked) == 10 and picked[0][0] == 1 and picked[-1][0] == 100
    assert sample_frames(frames[:3], 10) == frames[:3]
    recs = [{"tick": t, "choice": "right", "action": "swipe right"} for t in range(5)] + [{"tick": 6, "choice": "up", "action": "swipe up"}]
    assert "6 actions" in actions_summary(recs) and "swipe right×5" in actions_summary(recs)
    class _Chat:
        model = "fake"; cost = 0.0
        def complete(self, messages, **kw):
            assert messages[1]["content"][0]["type"] == "text" and sum(1 for p in messages[1]["content"] if p["type"] == "image_url") == 3
            self.cost += 0.001
            return ('{"completion": 72.4, "directedness": 140, "note": "ate two, then turned into the wall"}', {}, 0)
    r = rate_episode(_Chat(), frames[:3], recs, "snake", task="first_food", outcome="status is dead")
    assert r["completion"] == 72 and r["directedness"] == 100 and r["note"].startswith("ate two") and r["cost_usd"] == 0.001
    class _Bad:
        model = "fake"
        def complete(self, messages, **kw): raise RuntimeError("down")
    assert rate_episode(_Bad(), frames[:2], recs)["completion"] is None
    # calibration: the rater agrees with the trial order on 2 of 3 strict pairs
    eps = [{"won": False, "lost": True, "ticks": 50, "score": None, "tasks_done": 0, "rating": {"completion": 10}},
           {"won": False, "lost": True, "ticks": 300, "score": None, "tasks_done": 0, "rating": {"completion": 60}},
           {"won": False, "lost": False, "ticks": 400, "score": None, "tasks_done": 0, "rating": {"completion": 40}},
           {"won": False, "lost": False, "ticks": 400, "score": 999, "tasks_done": 0}]
    c = calibrate(eps)
    assert c["rated"] == 3 and c["pairs"] == 3 and abs(c["agreement"] - 2 / 3) < 1e-3
    assert calibrate([])["agreement"] is None


def test_held_keys_relative_mouse_and_chunks_reach_the_device_and_the_demo_digest_finds_key_runs():
    from anygame.loop import Agent
    from anygame.pack import load_pack_text, dump_pack, load_pack, PackError
    from anygame.device.replay import ReplayDevice
    from anygame.demo import key_runs
    import tempfile, cv2
    raw = yaml.safe_load(open(os.path.join(ROOT, "packs", "snake-state", "pack.yaml")).read())
    raw["act"] = [{"id": "run", "kind": "key", "key": "ShiftLeft", "hold_ms": 120}, {"id": "combo", "kind": "chunk", "keys": ["ArrowLeft", "ArrowLeft", "Space"], "key_ms": 1},
                  {"id": "look", "kind": "mouse_move", "dx": 40, "dy": -8}, {"id": "keep", "kind": "wait"}]
    raw["rules"], raw["tasks"] = [], []
    pack = load_pack_text(dump_pack(raw), "inputs")
    d = tempfile.mkdtemp(); cv2.imwrite(os.path.join(d, "0.png"), np.zeros((560, 540, 3), np.uint8))
    dev = ReplayDevice(d)
    ag = Agent(pack, dev, None)
    assert ag.act(pack.action("run"), {}) == "key ShiftLeft held 120 ms" and dev.actions[-1] == ("key", "ShiftLeft", 120)
    assert ag.act(pack.action("combo"), {}) == "chunk ArrowLeft ArrowLeft Space" and dev.actions[-3:] == [("key", "ArrowLeft"), ("key", "ArrowLeft"), ("key", "Space")]
    assert ag.act(pack.action("look"), {}) == "mouse_move 40,-8" and dev.actions[-1] == ("mouse_move", 40, -8)
    # a device without a pointer reports it instead of crashing
    from anygame.device.base import Device
    class NoMouse(Device):
        def size(self): return (540, 560)
        def frame(self): return np.zeros((560, 540, 3), np.uint8)
        def tap(self, x, y): pass
        def swipe(self, *a): pass
        def key(self, name, hold_ms=0): pass
    assert Agent(pack, NoMouse(), None).act(pack.action("look"), {}).startswith("mouse_move unsupported")
    for bad in ({"id": "c", "kind": "chunk"}, {"id": "m", "kind": "mouse_move"}, {"id": "k", "kind": "key"}):
        with pytest.raises(PackError):
            r2 = yaml.safe_load(dump_pack(raw)); r2["act"] = [bad]; load_pack_text(dump_pack(r2), "x")
    # the digest: a repeated left-left-space within 600 ms is a chunk candidate; isolated presses are not
    ev = []
    t = 0
    for rep in range(3):
        for k in ("ArrowLeft", "ArrowLeft", "Space"):
            ev.append({"t": t, "type": "key", "key": k}); t += 150
        t += 2000
    ev.append({"t": t, "type": "key", "key": "ArrowUp"})
    runs = key_runs(ev)
    assert runs and runs[0][0] == ["ArrowLeft", "ArrowLeft", "Space"] and runs[0][1] == 3
    assert key_runs([]) == []


def test_suite_reports_tasks_done_within_the_limit_and_at_all(tmp_path, monkeypatch):
    """The suite over the state snake with a device whose seed picks how fast the score rises."""
    from anygame import cli
    from anygame.pack import load_pack, dump_pack
    import anygame.device as devmod
    from test_state import StateDevice
    raw = yaml.safe_load(open(os.path.join(ROOT, "packs", "snake-state", "pack.yaml")).read())
    raw["tasks"] = [{"id": "one", "instruction": "score 1", "done": {"read": "score", "gte": 1}, "category": "collect", "limit_ticks": 3, "reference_ticks": 2},
                    {"id": "big", "instruction": "score 9", "done": {"read": "score", "gte": 9}, "category": "score", "limit_ticks": 4}]
    raw["tests"] = [{"state": "fixtures/start.json", "expect": {"status": "playing"}}]
    pdir = tmp_path / "snake-suite"; (pdir / "fixtures").mkdir(parents=True)
    (pdir / "pack.yaml").write_text(dump_pack(raw)); (pdir / "fixtures" / "start.json").write_text(json.dumps({"snake": [[3, 6], [2, 6], [1, 6]], "food": [9, 2], "score": 0, "over": False}))
    def fake_open(url, size):
        seed = int(url.split("seed=")[1])
        # seed 1: score jumps to 1 at tick 2 and to 9 at tick 8 (past 'big's limit of 4 but held at some tick); seed 2: never scores
        states = [{"snake": [[3 + i, 6], [2 + i, 6], [1 + i, 6]], "food": [9, 2], "score": (0 if i < 1 else 1 if i < 7 else 9) if seed == 1 else 0, "over": False} for i in range(10)]
        return StateDevice(states)
    monkeypatch.setattr(devmod, "open_device", fake_open)
    import argparse
    rows = cli.cmd_suite(argparse.Namespace(packs=str(pdir), device="x://?seed={seed}", seeds="1,2", sensor="random:1", max_ticks=10, learned=False, out=str(tmp_path / "suite.jsonl")))
    by = {(r["seed"], r["task"]): r for r in rows}
    assert by[("1", "one")]["within"] and by[("1", "one")]["without"] and by[("1", "one")]["within_reference"] is True
    assert not by[("1", "big")]["within"] and by[("1", "big")]["without"]       # done after its limit: counts "at all", not "within"
    assert not by[("2", "one")]["within"] and not by[("2", "one")]["without"]
    assert len(open(tmp_path / "suite.jsonl").read().splitlines()) == 4


def test_reflex_acts_on_the_last_answers_when_a_fresh_answer_would_land_too_late():
    # Snake at Jev's pace: with one free cell ahead (or none, after a turn into a wall), a fresh answer lands after the
    # next step. The pack's reflex condition makes the rules act on the last answers at once.
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from test_state import StateDevice
    class Slow:
        model = "slow"
        def __init__(self): self.calls = 0
        def ask(self, state, qs):
            self.calls += 1
            p = {"keep": 0.6, "down": 0.25, "up": 0.1, "left": 0.03, "right": 0.02}
            return {"answers": {"action": {"type": "choice", "choice": "keep", "probabilities": {c: p.get(c, 0.0) for c in qs["action"]["criteria"]}}}, "latency_ms": 600, "input_tokens": 10, "cost_usd": 0.0}
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    assert pack.raw["reflex"]["read"] == "head_around.ahead_free"
    # moving right along row 6 until the head is against the right wall (x 11 of 12)
    states = [{"snake": [[8 + i, 6], [7 + i, 6], [6 + i, 6]], "food": [1, 1], "score": 0, "over": False} for i in range(4)]
    slow = Slow()
    ag = Agent(pack, StateDevice(states), slow)
    recs = [ag.step() for _ in range(4)]
    assert recs[-1]["screen"]["head_around"]["ahead"] == "wall"
    assert recs[-1]["skipped"] == "reflex" and "reflex" in recs[-1]["sensor"] and recs[-1]["choice"] == "down"
    assert slow.calls == sum(1 for r in recs if "jev_ms" in r and not r.get("skipped")) and ag.skipped_reflex == 2 and recs[-2]["skipped"] == "reflex"
    # without the reflex the same frame waits on the decider
    pack.raw.pop("reflex")
    slow2 = Slow()
    ag2 = Agent(pack, StateDevice(states), slow2)
    recs2 = [ag2.step() for _ in range(4)]
    assert not recs2[-1].get("skipped") and ag2.skipped_reflex == 0


def test_rule_unless_lets_the_snake_eat_food_in_a_corner():
    # food in the corner: one free cell ahead, then the wall. The turn-early rule would forbid going straight forever;
    # its `unless` lets the snake eat, and the reflex turns on the next frame
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from test_state import StateDevice
    class Keep:
        model = "keep"
        def ask(self, state, qs):
            p = {"keep": 0.6, "right": 0.25, "up": 0.1, "down": 0.03, "left": 0.02}
            return {"answers": {"action": {"type": "choice", "choice": "keep", "probabilities": {c: p.get(c, 0.0) for c in qs["action"]["criteria"]}}}, "latency_ms": 600, "input_tokens": 10, "cost_usd": 0.0}
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    states = [{"snake": [[0, 3 - i], [0, 4 - i], [0, 5 - i]], "food": [0, 0], "score": 0, "over": False} for i in range(3)]
    ag = Agent(pack, StateDevice(states), Keep())
    recs = [ag.step() for _ in range(3)]
    last = recs[-1]
    assert last["screen"]["head_around"]["ahead"] == "F" and last["screen"]["head_around"]["ahead_free"] == 1
    assert last["choice"] == "keep" and not any("ahead_free" in r for r in last["rules"])
    # the same spot with no food there: turn early, as before
    states2 = [{**s, "food": [5, 5]} for s in states]
    ag2 = Agent(pack, StateDevice(states2), Keep())
    recs2 = [ag2.step() for _ in range(3)]
    assert recs2[-1]["choice"] == "right"


def test_gap_read_gives_distance_speed_and_time_to_contact():
    from anygame.perceive import GapTracker
    g = GapTracker({"in": "road", "symbol": "#", "cell_px": 10, "row_names": ["chest", "low"], "speed0": 300, "speed_range": [50, 2000]})
    def road(col, width=2, rows=(2,)):
        return {f"c{c}r{r}": ("#" if col <= c < col + width and r in rows else ".") for c in range(1, 41) for r in (1, 2)}
    assert g.read(road(99), 0.0) == {"cells": 40, "px": 400, "width_px": 0, "rows": "none", "then_px": None, "speed": 300, "ttc_ms": None, "age_ms": None, "then_ms": None}
    a = g.read(road(31), 1.0)                       # an obstacle 300 px out: speed0 until it has been watched a while
    assert (a["px"], a["width_px"], a["rows"], a["speed"], a["ttc_ms"], a["age_ms"]) == (300, 20, "low", 300, 1000, 0)
    b = g.read(road(21, rows=(1, 2)), 1.2)          # 100 px in 0.2 s: 500 px/s, measured over its whole approach
    assert (b["px"], b["rows"], b["speed"], b["ttc_ms"], b["age_ms"]) == (200, "chest,low", 500, 400, 200)
    c = g.read(road(36, rows=(1,)), 1.3)            # it went by; the next one is new (its age restarts), the speed stands
    assert (c["px"], c["rows"], c["speed"], c["age_ms"], c["then_ms"]) == (350, "chest", 500, 0, None)
    two = {**road(11), **{f"c{c}r2": "#" for c in (21, 22)}}       # a second obstacle 100 px behind the first
    d = g.read(two, 1.4)
    assert (d["px"], d["width_px"], d["then_px"], d["then_ms"]) == (100, 20, 100, 200)


def test_dino_jumps_on_the_frame_and_asks_jev_beside_the_loop():
    # The web-dino pack: the rules time the jump from the time to contact on each frame; Jev is asked once per new
    # obstacle without the loop waiting, and its ranking, filtered by the rules, is used when the obstacle arrives.
    import time
    import numpy as np
    from anygame.loop import Agent
    from anygame.pack import load_pack
    pack = load_pack(os.path.join(ROOT, "packs", "web-dino"))

    class Road:
        def __init__(self, xs):
            self.xs, self.i, self.keys = xs, -1, []
        def size(self):
            return (540, 560)
        def frame(self):
            time.sleep(0.05)
            self.i = min(self.i + 1, len(self.xs) - 1)
            f = np.full((560, 540, 3), 247, np.uint8)
            f[232:268, 56:92] = 83                                  # the dino, standing
            x = self.xs[self.i]
            if x is not None:
                f[230:266, x:x + 40] = 83                           # a wide cactus
            return f
        def key(self, name, hold_ms=0, block=True):
            self.keys.append((self.i, name, hold_ms, block))

    class SlowJev:
        model = "slow"
        def __init__(self):
            self.calls = 0
        def ask(self, state, qs):
            self.calls += 1
            time.sleep(0.3)
            wide = (state["screen"].get("next") or {}).get("width_px", 0) >= 30
            p = {"duck": 0.5, "jump": 0.3, "drop": 0.1, "keep": 0.1} if wide else {"keep": 0.7, "jump": 0.2, "duck": 0.08, "drop": 0.02}
            return {"answers": {"action": {"type": "choice", "choice": max(p, key=p.get), "probabilities": {c: p.get(c, 0.0) for c in qs["action"]["criteria"]}}},
                    "latency_ms": 300, "input_tokens": 10, "cost_usd": 0.0}

    xs = [None, None] + list(range(520, 60, -30))
    dev, jev = Road(xs), SlowJev()
    ag = Agent(pack, dev, jev)
    recs = []
    for _ in range(len(xs)):
        t = time.perf_counter()
        recs.append(ag.step())
        assert time.perf_counter() - t < 0.25 or len(recs) == 1          # only the very first call blocks the loop
        if dev.keys:
            break
    assert jev.calls == 2 and ag.asked_async == 1                   # the first frame (nothing to act on yet), then the obstacle once
    i, name, hold, block = dev.keys[0]
    jumped = recs[-1]
    assert name == "Space" and hold == 250 and block is False and jumped["choice"] == "jump"      # duck ranked first, but a cactus cannot be ducked
    assert jumped["screen"]["next"]["ttc_ms"] <= 205 and all(r["choice"] == "keep" for r in recs[:-1] if "choice" in r)
