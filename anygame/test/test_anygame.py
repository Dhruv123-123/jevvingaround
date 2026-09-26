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
    assert list(hand.cells()) == ["hand.c1", "hand.c2", "hand.c3", "hand.c4"]


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


# ---------- state-compiler reads: the counting Jev must never do ----------

def test_runs_read_finds_the_cell_that_completes_four():
    from anygame.perceive import runs_of
    board = {f"c{c}r{r}": "." for c in range(1, 8) for r in range(1, 7)}
    board.update({"c3r6": "Y", "c3r5": "Y", "c3r4": "Y", "c4r6": "R", "c5r6": "R", "c6r6": "R"})
    assert runs_of(board, {"symbol": "Y", "length": 4, "gravity": "down"}) == ["c3r3"]
    assert runs_of(board, {"symbol": "R", "length": 4, "gravity": "down"}) == ["c7r6"]      # c3r6 is taken, c7r6 completes it
    board["c3r3"] = "R"                                                                      # blocked: nothing for Y now
    assert runs_of(board, {"symbol": "Y", "length": 4, "gravity": "down"}) == []
    # without gravity a floating cell counts too (tic-tac-toe, gomoku)
    assert "c7r6" in runs_of(board, {"symbol": "R", "length": 4})


def test_around_read_reports_neighbours_free_runs_and_space():
    from anygame.perceive import around_of
    cells = {f"c{c}r{r}": "." for c in range(1, 5) for r in range(1, 5)}
    cells.update({"c2r2": "H", "c2r3": "s", "c2r4": "s", "c3r2": "F"})
    a = around_of("c2r2", cells, "up", {"free": [".", "F"]})
    assert a["up"] == "." and a["down"] == "s" and a["right"] == "F" and a["left"] == "."
    assert a["up_free"] == 1 and a["down_free"] == 0 and a["right_free"] == 2 and a["left_free"] == 1
    assert a["ahead"] == "." and a["ahead_free"] == 1
    assert a["down_space"] == 0 and a["up_space"] == a["right_space"] == 16 - 3        # everything except H and the body
    assert around_of("c1r1", cells, "left", {})["left"] == "wall"
    assert around_of(None, cells, None, {}) is None


def test_connect4_pack_reads_the_threat_and_legal_columns():
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "threat.png"))
    values, _, _ = read_all(pack, frame)
    assert values["status"] == "our_turn"
    assert values["y_wins_at"] and all(c.startswith("c4") for c in values["y_wins_at"])
    assert values["r_wins_at"] == []
    assert len(values["legal"]) == 7


# ---------- rules: beliefs and compiled reads become policy in the same tick ----------

class ChoiceJev:
    """Answers every choice with the first criterion and every noul with a fixed value; records the criteria offered."""
    def __init__(self, noul=0.9, choice=None):
        self.noul, self.choice, self.seen = noul, choice, []

    def ask(self, state, questions):
        self.seen.append({k: list(q["criteria"]) for k, q in questions.items()})
        answers = {}
        for k, q in questions.items():
            if q["type"] == "noul":
                answers[k] = {"type": "noul", "noul": self.noul}
            else:
                crit = list(q["criteria"])
                pick = self.choice.get(k, crit[0]) if self.choice else crit[0]
                answers[k] = {"type": "choice", "choice": pick, "probabilities": {c: (0.5 if c == pick else 0.5 / max(1, len(crit) - 1)) for c in crit}, "confidence": 1}
        return {"answers": answers, "latency_ms": 1, "input_tokens": 10, "cost_usd": 0}


def test_rules_exclude_fatal_directions_and_pick_the_best_remaining():
    pack = load_pack(os.path.join(ROOT, "packs", "snake"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "snake", "fixtures", "start.png"))
    jev = ChoiceJev(noul=0.1, choice={"action": "keep"})
    ag = Agent(pack, FakeDevice([frame]), jev)
    rec = ag.step()
    # the fixture's head has the body on its left (it starts moving right), so 'left' is excluded by head_around
    assert any("not left" in r for r in rec["rules"])
    assert rec["choice"] in ("up", "down", "right", "keep")


def test_rules_set_copies_a_choice_into_the_parameter_question():
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "threat.png"))
    jev = ChoiceJev(noul=0.9, choice={"drop__cell": "c1", "threat_column": "c4", "win_column": "none"})
    ag = Agent(pack, FakeDevice([frame]), jev)
    rec = ag.step()
    assert rec["choice"] == "drop" and rec["action"].startswith("tap columns.c4")
    assert any("drop__cell = threat_column" in r for r in rec["rules"])


def test_act_when_waits_for_our_turn():
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "start.png"))
    frame_theirs = frame.copy()
    z = pack.zone("status")
    x0, y0, x1, y1 = z.rect.px(frame.shape[1], frame.shape[0])
    frame_theirs[y0:y1, x0:x1] = (11, 191, 234)     # #eabf0b-ish yellow: their turn
    jev = ChoiceJev()
    ag = Agent(pack, FakeDevice([frame_theirs, frame]), jev)
    first, second = ag.step(), ag.step()
    assert first["action"] == "wait" and first["reason"].startswith("status is")
    assert second["action"].startswith("tap")


def test_noop_with_parameter_is_excluded_per_column():
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "start.png"))
    jev = ChoiceJev(noul=0.0)
    ag = Agent(pack, FakeDevice([frame, frame, frame]), jev)
    ag.step(); ag.step()
    # the first drop went to c1 (first criterion) and changed nothing, so the second offer of drop__cell omits c1
    assert "c1" in jev.seen[0]["drop__cell"] and "c1" not in jev.seen[1]["drop__cell"]


def test_history_gives_prev_moving_and_reverse():
    from anygame.loop import _direction, _get
    assert _direction("c3r5", "c3r4") == "up" and _direction("c3r5", "c4r5") == "right" and _direction("x", "y") == "none"
    assert _get({"a": {"b": 1}}, "a.b") == 1 and _get({"a": 1}, "a.b") is None


def test_settle_waits_for_the_screen_to_change_after_an_action():
    pack = load_pack(os.path.join(ROOT, "packs", "snake"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "snake", "fixtures", "start.png"))
    jev = ChoiceJev(noul=0.1, choice={"action": "up"})
    ag = Agent(pack, FakeDevice([frame, frame, frame, frame, frame, frame]), jev)
    recs = [ag.step() for _ in range(5)]
    assert recs[0]["action"] == "swipe up"
    assert [r["action"] for r in recs[1:4]] == ["wait"] * 3 and recs[1]["reason"].startswith("settling")
    assert recs[4]["action"] != "wait" or not recs[4]["reason"].startswith("settling")   # settle_ticks caps the wait


def test_sensor_timeout_falls_back_to_rules_on_last_answers():
    pack = load_pack(os.path.join(ROOT, "packs", "snake"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "snake", "fixtures", "start.png"))

    class Flaky(ChoiceJev):
        def ask(self, state, questions):
            if len(self.seen) == 1:
                self.seen.append(None)
                raise TimeoutError("read timed out")
            return super().ask(state, questions)

    jev = Flaky(noul=0.1, choice={"action": "right"})
    frames = [frame, np.ascontiguousarray(frame[::-1]), frame]   # every screen differs so settle never waits
    ag = Agent(pack, FakeDevice(frames), jev)
    first, second = ag.step(), ag.step()
    assert first["action"] == "swipe right"
    assert second["sensor"].startswith("error → rules") and second["action"] != "wait" and ag.errors == 1


def test_runs_hands_mode_and_avoid_rule_drop_the_losing_column():
    from anygame.perceive import runs_of
    board = {f"c{c}r{r}": "." for c in range(1, 8) for r in range(1, 7)}
    board.update({"c3r3": "Y", "c4r3": "Y", "c5r3": "Y", "c6r6": "R", "c6r5": "Y", "c3r4": "R", "c3r5": "Y", "c3r6": "R",
                  "c4r4": "R", "c4r5": "R", "c4r6": "Y", "c5r4": "Y", "c5r5": "R", "c5r6": "R"})
    assert runs_of(board, {"symbol": "Y", "length": 4, "gravity": "down", "mode": "hands"}) == ["c6r4"]
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    values = {"status": "our_turn", "y_wins_if_we_drop_at": ["c6r4"]}
    qs = Agent(pack, FakeDevice([]), None).questions(values)
    assert "c6" not in qs["drop__cell"]["criteria"] and "c5" in qs["drop__cell"]["criteria"]
