"""The state stream: json / json_grid reads, a device that publishes its state, and the desktop device's URL parsing.
Mirrors ext/test/state.test.mjs."""
import json
import os
import numpy as np
import pytest
from anygame.perceive.state import get_path, read_json, read_json_grid
from anygame.pack import load_pack, load_pack_text
from anygame.loop import Agent
from anygame.device.base import Device

ROOT = os.path.dirname(os.path.dirname(__file__))
STATE = {"snake": [[6, 6], [5, 6], [4, 6]], "food": [9, 2], "score": 30, "over": False, "dir": [1, 0], "nested": {"a": [{"b": "x"}]}}


def test_json_reads_paths_parse_map_and_default():
    assert get_path(STATE, "nested.a.0.b") == "x" and get_path(STATE, "nested.a.9.b") is None and get_path(STATE, "snake.0.1") == 6
    assert read_json(STATE, {"path": "score", "parse": "int"}) == (30, 1.0)
    assert read_json(STATE, {"path": "over", "map": {"true": "dead", "false": "playing"}}) == ("playing", 1.0)
    assert read_json(STATE, {"path": "missing", "default": "playing"}) == ("playing", 0.0)
    assert read_json({"over": "true"}, {"path": "over", "parse": "bool"}) == (True, 1.0)
    assert read_json({"n": "abc"}, {"path": "n", "parse": "int", "default": 0}) == (0, 0.0)


def test_json_grid_builds_the_matrix_from_coordinates():
    grid, conf = read_json_grid(STATE, {"cols": 12, "rows": 12, "symbols": {"F": {"path": "food"}, "s": {"path": "snake", "slice": [1, None]}, "H": {"path": "snake", "index": 0}}})
    assert conf == 1.0 and len(grid) == 144
    assert grid["c7r7"] == "H" and grid["c6r7"] == "s" and grid["c5r7"] == "s" and grid["c10r3"] == "F" and grid["c1r1"] == "."
    empty, conf0 = read_json_grid({}, {"cols": 3, "rows": 2, "symbols": {"H": {"path": "snake"}}})
    assert conf0 == 0.0 and set(empty.values()) == {"."}
    one, _ = read_json_grid({"p": {"col": 2, "row": 1}}, {"cols": 3, "rows": 2, "one_based": True, "symbols": {"P": {"path": "p"}}})
    assert one["c2r1"] == "P"


class StateDevice(Device):
    """A game that only tells us its state (no useful pixels) and takes keys."""
    def __init__(self, states):
        self.states, self.i, self.keys = states, 0, []

    def size(self):
        return (540, 560)

    def frame(self):
        return np.zeros((560, 540, 3), np.uint8)

    def state(self):
        s = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        return s

    def key(self, name):
        self.keys.append(name)


class RightJev:
    def ask(self, state, questions):
        return {"answers": {k: ({"type": "noul", "noul": 0.5} if q["type"] == "noul" else {"type": "choice", "choice": "right", "probabilities": {"right": 0.7, "up": 0.2, "down": 0.1}})
                            for k, q in questions.items()}, "latency_ms": 1, "input_tokens": 0, "cost_usd": 0.0}


def test_snake_state_pack_plays_from_the_stream_and_the_rules_guard_the_wall():
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    s1 = {"snake": [[6, 6], [5, 6], [4, 6]], "food": [9, 2], "score": 0, "over": False}
    s2 = {"snake": [[11, 6], [10, 6], [9, 6]], "food": [9, 2], "score": 0, "over": False}   # head at the right wall
    s3 = {"snake": [[11, 5], [11, 6], [10, 6]], "food": [9, 2], "score": 0, "over": False}
    s4 = {"snake": [[11, 4], [11, 5], [11, 6]], "food": [9, 2], "score": 0, "over": True}
    dev = StateDevice([s1, s2, s3, s4])
    ag = Agent(pack, dev, RightJev())
    r1 = ag.step()
    assert r1["support"] >= 0.99 and r1["screen"]["head"] == "c7r7" and r1["screen"]["cells"][6][6] == "H"
    assert r1["action"].startswith("key ArrowRight") or r1["choice"] == "right"
    r2 = ag.step()
    assert r2["screen"]["head"] == "c12r7" and r2["screen"]["head_around"]["right"] == "wall" and r2["screen"]["head_moving"] == "right"
    assert r2["choice"] != "right" and "ArrowRight" not in dev.keys[1:] and any("not right" in x for x in r2["rules"])
    r3 = ag.step()
    r4 = ag.step()
    assert r4["action"] == "stop" and "dead" in r4["reason"]


def test_web_device_state_expression_and_stream_file(tmp_path):
    from anygame.device.stream import StreamDevice
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"snake": [[1, 1]], "food": [2, 2], "over": False, "score": 5}))
    dev = StreamDevice(f"file:{p}", (100, 100))
    assert dev.state()["score"] == 5 and dev.frame().shape == (100, 100, 3)
    p.write_text(json.dumps({"score": 6}))
    assert dev.state()["score"] == 6
    dev.close()
    with pytest.raises(ValueError):
        StreamDevice("gopher://x")
    from anygame.device.web import WebDevice
    d = WebDevice(os.path.join(ROOT, "games", "snake.html") + "?seed=4&tick=900#state=window.__state()", (540, 560))
    try:
        st = d.state()
        assert isinstance(st, dict) and "snake" in st and "food" in st
    finally:
        d.close()


def test_screen_device_url_parsing_and_keys():
    from anygame.device.screen import parse_url
    o = parse_url("100,50,640,480?scale=0.5&monitor=2")
    assert o == {"region": {"left": 100, "top": 50, "width": 640, "height": 480}, "scale": 0.5, "monitor": 2}
    assert parse_url("")["region"] is None
    with pytest.raises(ValueError):
        parse_url("1,2,3")
    try:
        from pynput.keyboard import Key       # pynput needs a display to import its backend: no display, no key test
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no display for pynput: {e}")
    from anygame.device.screen import key_of
    assert key_of("ArrowUp") == Key.up and key_of("a") == "a" and key_of("Space") == Key.space
