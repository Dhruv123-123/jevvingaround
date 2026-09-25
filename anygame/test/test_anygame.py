import os
import numpy as np
import cv2
import pytest
from anygame.geometry import Rect, Zone
from anygame.pack import load_pack, PackError
from anygame.perceive import read_all
from anygame.perceive.bar import read as read_bar
from anygame.perceive.color import read as read_color
from anygame.loop import Agent
from anygame.device.base import Device

ROOT = os.path.dirname(os.path.dirname(__file__))


def test_grid_cells_and_lookup():
    z = Zone("arena", Rect(0, 0, 1, 1), (6, 9))
    cells = z.cells()
    assert len(cells) == 54 and "arena.c1r1" in cells and "arena.c6r9" in cells
    assert z.cell_of(0.05, 0.05) == "arena.c1r1"
    assert z.cell_of(0.99, 0.99) == "arena.c6r9"
    hand = Zone("hand", Rect(0, 0.9, 1, 1), (4, 1))
    assert list(hand.cells()) == ["hand.1", "hand.2", "hand.3", "hand.4"]


def test_pack_loader_refuses_missing_tests(tmp_path):
    (tmp_path / "pack.yaml").write_text("game: x\nzones: {}\nread: {}\nact: [{id: wait}]\n")
    with pytest.raises(PackError, match="without tests"):
        load_pack(tmp_path)


def test_pack_loader_refuses_bad_read(tmp_path):
    (tmp_path / "f.png").write_bytes(b"")
    (tmp_path / "pack.yaml").write_text("game: x\nzones: {}\nread: { a: { kind: magic, rect: [0,0,1,1] } }\nact: [{id: wait}]\ntests: [{frame: f.png, expect: {}}]\n")
    with pytest.raises(PackError, match="kind must be"):
        load_pack(tmp_path)


def test_bar_read_fraction():
    img = np.zeros((10, 100, 3), np.uint8)
    img[:, :63] = (140, 62, 232)   # #e83e8c in BGR
    v = read_bar(img, Rect(0, 0, 1, 1), {"color": "#e83e8c", "scale": 10, "step": 1})
    assert v == 6.0


def test_color_grid_read_is_robust_to_text():
    img = np.full((220, 220, 3), (218, 228, 238), np.uint8)   # #eee4da tile everywhere (BGR)
    for cx, cy in ((55, 55), (165, 55), (55, 165), (165, 165)):   # a 2048-sized digit in every cell (~20% of the tile)
        cv2.putText(img, "2", (cx - 18, cy + 20), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (101, 110, 119), 4)
    z = Zone("b", Rect(0, 0, 1, 1), (2, 2))
    out = read_color(img, z.rect, {"options": {"0": "#cdc1b4", "2": "#eee4da", "4": "#ede0c8"}, "parse": "int", "inset": 0.2, "max_dist": 45}, z)
    assert out == {"c1r1": 2, "c2r1": 2, "c1r2": 2, "c2r2": 2}


def test_2048_pack_perception_on_fixture():
    pack = load_pack(os.path.join(ROOT, "packs", "2048"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "2048", "fixtures", "board-a.png"))
    values, _, timings = read_all(pack, frame, only={"tiles", "over"})
    assert values["tiles"]["c4r4"] == 128 and values["tiles"]["c1r1"] == 2 and values["tiles"]["c2r1"] == 0
    assert values["over"] == "playing"
    assert timings["tiles"] < 50


class FakeDevice(Device):
    def __init__(self, frames):
        self.frames, self.i, self.log = frames, 0, []

    def size(self):
        return (540, 700)

    def frame(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def swipe(self, *a, **k):
        self.log.append(("swipe", a))

    def tap(self, x, y):
        self.log.append(("tap", x, y))


class FakeJev:
    def __init__(self):
        self.seen = []

    def ask(self, state, questions):
        self.seen.append(questions["action"]["criteria"])
        first = list(questions["action"]["criteria"])[0]
        return {"answers": {"action": {"type": "choice", "choice": first, "probabilities": {}, "confidence": 1}}, "latency_ms": 1, "input_tokens": 10, "cost_usd": 0}


def test_loop_drops_noop_actions_until_screen_changes():
    pack = load_pack(os.path.join(ROOT, "packs", "2048"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "2048", "fixtures", "board-a.png"))
    dev = FakeDevice([frame, frame, frame, frame])   # the screen never changes
    jev = FakeJev()
    ag = Agent(pack, dev, jev)
    ag.step(); ag.step(); ag.step()
    # tick 1 offers all four; the chosen 'up' did nothing, so tick 2 offers three, tick 3 two
    assert [len(c) for c in jev.seen] == [4, 3, 2]
    assert "up" not in jev.seen[1] and "down" not in jev.seen[2]
    assert dev.log and dev.log[0][0] == "swipe"
