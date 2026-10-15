"""The typed-decider screen agent: labels cached by screen hash, the decider's pick turned into presses."""
import json

import numpy as np

from anygame.screen_agent import blocks
from anygame.typed_screen import LabelCache, TypedScreenAgent, parse_label
from test_screen_agent import GridGame


class FakeNamer:
    def __init__(self):
        self.cost, self.calls = 0.0, 0

    def complete(self, msgs, max_tokens=0, extra=None):
        self.calls += 1
        self.cost += 0.001
        return json.dumps({"kind": "map", "where": "a walled room", "see": ["walls all round"],
                           "options": [{"do": "walk right to the wall", "presses": ["right*3"]}]}), {}, 1


class FakeDecider:
    def __init__(self):
        self.states = []

    def ask(self, state, questions):
        self.states.append((state, questions))
        return {"answers": {"do": {"choice": "o1", "confidence": 0.9}, "heading": {"choice": "right"}}, "cost_usd": 1e-5}


def test_parse_label_keeps_presses_and_kind():
    lab = parse_label('{"kind": "BATTLE", "where": "x", "options": [{"do": "fight", "presses": ["a", "down*2", "zz"]}]}')
    assert lab["kind"] == "battle" and lab["options"][0]["presses"] == ["a", "down", "down"]


def test_cache_matches_exact_near_and_scrolled():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, size=(144, 160, 3), dtype=np.uint8)
    c = LabelCache()
    b = blocks(img)
    assert c.find(b) == (None, "new")
    c.add(b, {"kind": "map"})
    assert c.find(b) == (0, "exact")
    moved = np.roll(img, 8, axis=1)           # the view scrolled one block
    assert c.find(blocks(moved)) == (0, "scroll")
    other = rng.integers(0, 255, size=(144, 160, 3), dtype=np.uint8)
    assert c.find(blocks(other))[1] == "new"


def test_agent_labels_once_and_plays_the_decider_pick():
    g = GridGame()
    namer, dec = FakeNamer(), FakeDecider()
    a = TypedScreenAgent(g, dec, namer=namer, seed=1, stuck=3, every=10)
    for _ in range(200):
        a.step()
    assert dec.states, "the decider was asked"
    assert namer.calls < len(dec.states), "repeat screens reuse their label"
    state, qs = dec.states[-1]
    assert "o1" in qs["do"]["criteria"] and "walk_up" in qs["do"]["criteria"] and "explore" in qs["do"]["criteria"]
    assert a.advice[-1]["pick"] == "o1" and a.summary()["decide_calls"] == len(dec.states)
