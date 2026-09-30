"""Learning from experience: episodes, incidents, and a revision that must replay better than the incumbent before it
is accepted. Snake boards are painted with the pack's own colours, so the reads are real. Mirrors ext/test/learn.test.mjs."""
import os
import numpy as np
import yaml
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
