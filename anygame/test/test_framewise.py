"""The framewise agent: the namer on its own thread, labels on a shared board, the frame loop never waiting."""
import json
import time

import numpy as np

from anygame.framewise import Blackboard, SlowLane
from anygame.screen_agent import blocks


class SlowNamer:
    """A namer that takes `delay` seconds per screen, like the vision model."""

    def __init__(self, delay=0.05, kind="map"):
        self.cost, self.calls, self.delay, self.kind = 0.0, 0, delay, kind

    def complete(self, msgs, max_tokens=0, extra=None):
        time.sleep(self.delay)
        self.calls += 1
        self.cost += 0.001
        return json.dumps({"kind": self.kind, "where": f"room {self.calls}", "subgoal": "walk right",
                           "options": [{"do": "walk right to the wall", "presses": ["right*3"]}]}), {}, 1


def _wait(lane, s=2.0):
    t = time.time()
    while not lane.idle() and time.time() - t < s:
        time.sleep(0.005)


def test_slow_lane_labels_in_the_background_and_keeps_the_subgoal():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, size=(144, 160, 3), dtype=np.uint8)
    board, namer = Blackboard(), SlowNamer(0.1)
    got = []
    lane = SlowLane(namer, board, on_label=lambda j, lab: got.append(j))
    t0 = time.perf_counter()
    assert lane.want(blocks(img), img, goal="leave the room")
    assert time.perf_counter() - t0 < 0.02, "want() does not wait for the namer"
    assert not lane.want(blocks(img), img), "a queued screen is not queued twice"
    _wait(lane)
    j, how = board.find(blocks(img))
    assert how == "exact" and board.label(j)["subgoal"] == "walk right" and got == [j]
    lane.close()


def test_slow_lane_names_the_newest_screen_first_and_drops_old_ones():
    rng = np.random.default_rng(1)
    imgs = [rng.integers(0, 255, size=(144, 160, 3), dtype=np.uint8) for _ in range(8)]
    board, namer = Blackboard(), SlowNamer(0.05)
    lane = SlowLane(namer, board, depth=2)
    for im in imgs:
        lane.want(blocks(im), im)
    _wait(lane)
    assert board.find(blocks(imgs[-1]))[1] == "exact", "the screen on show is named"
    assert lane.dropped >= 4 and namer.calls <= 4
    lane.close()


class SlowDecider:
    """A decider that takes `delay` seconds, like Jev (~0.4 s): always the first option."""

    def __init__(self, delay=0.05):
        self.delay, self.calls = delay, 0

    def ask(self, state, questions):
        time.sleep(self.delay)
        self.calls += 1
        return {"answers": {"do": {"choice": "o1", "confidence": 0.9}, "heading": {"choice": "right"}}, "cost_usd": 1e-5}


def test_frame_loop_never_waits_on_either_model():
    from anygame.framewise import FramewiseAgent
    from test_screen_agent import GridGame
    g = GridGame()
    namer, dec = SlowNamer(0.2), SlowDecider(0.2)
    a = FramewiseAgent(g, dec, namer=namer, seed=1, patience_ms=50)
    t0 = time.perf_counter()
    for _ in range(400):
        a.step()
    took = time.perf_counter() - t0
    s = a.summary()
    a.close()
    assert s["step_ms_max"] < 100, "no step waits on a model call"
    assert namer.calls >= 1 and s["labels"] >= 1
    assert s["presses"] > 100 and took < 10


def test_memo_replays_an_answer_without_a_call_and_forgets_one_that_leads_nowhere():
    from anygame.framewise import FramewiseAgent
    from test_screen_agent import GridGame
    g = GridGame()
    namer, dec = SlowNamer(0.0), SlowDecider(0.0)
    a = FramewiseAgent(g, dec, namer=namer, seed=1, patience_ms=500, reuse=2, asks_per_screen=2)
    for _ in range(600):
        a.step()
        if a.fast.idle() and a.slow.idle():
            pass
    s = a.summary()
    a.close()
    assert s["memo_hits"] > s["decide_calls"], "repeat screens replay the memo"
    assert s["decide_calls"] <= 2 * max(1, s["labels"]), "at most asks_per_screen calls per screen and goal"
    assert any(e.get("memo_use", 0) >= 1 for e in a.advice)


def test_stub_decider_follows_the_subgoal_after_its_latency():
    from anygame.sensors import open_sensor
    s = open_sensor("stub:30")
    t0 = time.perf_counter()
    r = s.ask({"screen": {"subgoal": "leave by the door"}},
              {"do": {"type": "choice", "criteria": {"o1": "talk to mom (a)", "o2": "leave by the door (up*3)"}}})
    assert r["answers"]["do"]["choice"] == "o2" and time.perf_counter() - t0 >= 0.03 and r["cost_usd"] == 0.0


def test_screen_agent_builds_the_framewise_agent_and_step_press_presses_once():
    from anygame.framewise import FramewiseAgent
    from anygame.typed_screen import screen_agent
    from test_screen_agent import GridGame
    g = GridGame()
    a = screen_agent(g, seed=1, advisor=SlowNamer(0.0), decider="stub:1", framewise=True)
    assert isinstance(a, FramewiseAgent)
    before = a.n["presses"]
    assert a.step_press()["action"] is not None and a.n["presses"] == before + 1
    a.close()
