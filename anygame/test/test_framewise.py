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
