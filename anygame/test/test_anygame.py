import json
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
    # tick 1 offers all four; the chosen swipe did nothing, so tick 2 offers three, tick 3 two
    assert [len(c) for c in jev.seen] == [4, 3, 2]
    first, second = list(jev.seen[0])[0], list(jev.seen[1])[0]
    assert first not in jev.seen[1] and second not in jev.seen[2] and first not in jev.seen[2]
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


def test_a_wrong_belief_cannot_force_a_column_the_reads_rule_out():
    # 64-episode run: a decider that believed "must block in c1" tapped a full c1 until the tick cap. Now the threat
    # column comes from y_wins_at (an `only` rule), and a `set:` cannot force a value the question did not offer.
    pack = load_pack(os.path.join(ROOT, "packs", "connect4"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "threat.png"))
    jev = ChoiceJev(noul=0.9, choice={"threat_column": "c1", "win_column": "c7"})
    ag = Agent(pack, FakeDevice([frame]), jev)
    rec = ag.step()
    assert jev.seen[0]["drop__cell"] == ["c4"]
    assert rec["action"].startswith("tap columns.c4")
    assert any("skipped: not offered" in r for r in rec["rules"])


def test_stop_when_list_stops_on_the_first_condition_that_holds_and_names_it():
    # a pack can say how a game ended (won / lost / tied), which the learn loop reads as the episode's outcome
    pack = load_pack(os.path.join(ROOT, "packs", "2048"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "2048", "fixtures", "board-a.png"))
    pack.raw["stop_when"] = [{"read": "over", "equals": "over"}, {"read": "over", "in": ["playing"]}]
    rec = Agent(pack, FakeDevice([frame]), FakeJev()).step()
    assert rec["action"] == "stop" and rec["reason"] == "over is playing"
    pack.raw["stop_when"] = [{"read": "over", "equals": "over"}]
    assert Agent(pack, FakeDevice([frame]), FakeJev()).step()["action"] != "stop"


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


# ---------- authoring: the slow model writes, the runtime checks ----------

def test_accent_colour_reads_glyphs_on_flat_cells():
    from anygame.perceive.color import accent_color
    img = np.full((160, 160, 3), (55, 41, 31), np.uint8)          # #1f2937 cell background (BGR)
    assert accent_color(img) == (55, 41, 31)                      # empty cell → background
    cv2.putText(img, "X", (25, 125), cv2.FONT_HERSHEY_SIMPLEX, 4.5, (113, 113, 248), 14)   # #f87171 glyph
    assert accent_color(img) == (113, 113, 248)


def test_tictactoe_pack_reads_board_threats_and_only_offers_empty_cells():
    pack = load_pack(os.path.join(ROOT, "packs", "tictactoe"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-4.png"))
    ag = Agent(pack, FakeDevice([frame]), None)
    values, _, _ = read_all(pack, frame)
    values = ag._present(values)
    assert values["board"] == [".X.", "XXO", "OO."] and values["o_wins_at"] == ["c3r3"]
    qs = ag.questions(values)
    assert set(qs["mark__cell"]["criteria"]) == {"c1r1", "c3r1", "c3r3"}       # `only` rule: just the empty cells
    assert pack.zone("board").rect.x0 == 20 / 540                                # rect_px normalised at load


def test_author_helpers_grid_palette_yaml_and_check():
    from pathlib import Path
    from anygame.author import palette, grid_overlay, extract_yaml, check_pack
    frame = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-2.png"))
    pal = palette(frame)
    assert pal[0]["hex"] == "#1f2937" and any(p["hex"] in ("#f36f6f", "#f87171") or p["hex"].startswith("#f") for p in pal)
    assert grid_overlay(frame).shape == frame.shape
    assert extract_yaml("text\n```yaml\ngame: x\n```\nnote") == "game: x\n" and extract_yaml("no block") is None
    ok, report = check_pack(Path(ROOT, "packs", "tictactoe"), [Path(ROOT, "packs", "tictactoe", "fixtures", "probe-2.png")])
    assert ok and "TEST fixtures/probe-2.png: ok" in report
    bad = Path(ROOT, "packs", "tictactoe")
    ok2, report2 = check_pack(Path("/nonexistent"), [])
    assert not ok2 and "PACK ERROR" in report2


# ---------- emulator device ----------

def test_2048gb_pack_reads_the_game_boy_board_by_ocr():
    pack = load_pack(os.path.join(ROOT, "packs", "2048gb"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "2048gb", "fixtures", "board-a.png"))
    values, _, _ = read_all(pack, frame, only={"tiles"})
    assert values["tiles"]["c1r3"] == 4 and values["tiles"]["c1r4"] == 4 and values["tiles"]["c2r4"] == 2 and values["tiles"]["c4r1"] == 0


def test_pyboy_device_boots_the_rom_and_takes_the_pad():
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    d = open_device("pyboy://" + os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60", None)
    try:
        assert d.size() == (480, 432)
        f = d.frame()
        assert f.shape == (432, 480, 3)
        d.key("start"); d.key("ArrowLeft"); d.swipe(100, 100, 100, 300); d.tap(1, 1)   # every input kind maps to a button
        assert d.frame().shape == (432, 480, 3)
    finally:
        d.close()


# ---------- sensors ----------

def test_random_sensor_and_llm_answer_parsing(monkeypatch):
    from anygame.sensors import open_sensor, LLMSensor
    qs = {"action": {"type": "choice", "instructions": "?", "criteria": {"a": None, "b": None}}, "risk": {"type": "noul", "instructions": "?", "criteria": {}}}
    r = open_sensor("random:1").ask({}, qs)
    assert r["answers"]["action"]["choice"] in ("a", "b") and r["answers"]["risk"]["noul"] == 0.5 and r["cost_usd"] == 0

    class Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": 'Sure: {"action": "b", "risk": 0.9}'}}], "usage": {"prompt_tokens": 50, "cost": 0.00001}}

    _chat_env(monkeypatch)
    llm = LLMSensor("some/model")
    monkeypatch.setattr(llm.chat.s, "post", lambda *a, **k: Resp())
    out = llm.ask({"screen": {}}, qs)
    assert out["answers"]["action"]["choice"] == "b" and out["answers"]["action"]["probabilities"] == {"a": 0.0, "b": 1.0}
    assert out["answers"]["risk"]["noul"] == 0.9 and out["cost_usd"] == 0.00001
    assert open_sensor("none") is None


# ---------- authoring with tuning: the model is stubbed, the runtime is real ----------

def test_author_tune_loop_plays_digests_and_keeps_a_passing_pack(monkeypatch, tmp_path):
    from anygame import author as A
    yaml_text = open(os.path.join(ROOT, "packs", "tictactoe", "pack.yaml")).read()
    calls = []

    def fake_ask(self, parts):
        calls.append([p["text"][:80] for p in parts if p.get("type") == "text"])
        body = yaml_text.split("\ntests:")[0].replace("game: tictactoe", "game: ttt-authored")
        body += "\ntests:\n  - { frame: fixtures/probe-1.png, expect: { status: our_turn, board: ['...', '...', '...'] } }\n"
        return "here you go\n```yaml\n" + body + "```\n"

    _chat_env(monkeypatch)
    monkeypatch.setattr(A.Author, "ask", fake_ask)
    out = tmp_path / "ttt"
    ok, path = A.author("web://" + os.path.join(ROOT, "games", "tictactoe.html?seed=2"), "Tic-tac-toe", out,
                        rounds=2, play_ticks=12, tune=1, sensor="random:3", log=lambda m: None)
    assert ok and (out / "pack.yaml").exists() and "ttt-authored" in (out / "pack.yaml").read_text()
    assert (out / "play-0.jsonl").exists() and (out / "play-1.jsonl").exists()
    assert len(calls) == 2 and "PLAYED" in " ".join(calls[1])          # round 1 wrote it, tune 1 saw the play digest
    digest = A.play_digest({"reason": "status is we_lost", "ticks": 7, "final_screen": {}}, out / "play-0.jsonl")
    assert digest.startswith("OUTCOME: status is we_lost") and "actions taken" in digest
    assert A._better(None, {"reason": "x"}, None) and A._better({"reason": "status is we_lost", "ticks": 5}, {"reason": "status is draw", "ticks": 9}, None)


def _chat_env(monkeypatch):
    for k in ("ANYGAME_LLM_API", "ANYGAME_AUTHOR_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANYGAME_LLM_BASE", "https://example.test/v1")
    monkeypatch.setenv("ANYGAME_LLM_KEY", "x")
    monkeypatch.setenv("ANYGAME_LLM_MODEL", "stub-model")


def test_chat_without_config_stops_and_openrouter_is_jev_only(monkeypatch):
    import pytest
    from anygame.chat import Chat
    for k in ("ANYGAME_LLM_BASE", "ANYGAME_LLM_KEY", "ANYGAME_LLM_MODEL", "ANYGAME_LLM_API", "AZURE_OPENAI_API_KEY", "ANYGAME_AUTHOR_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")          # Jev's key alone must not turn on a chat model
    with pytest.raises(SystemExit) as e:
        Chat()
    assert "ANYGAME_LLM_BASE" in str(e.value) and "ANYGAME_LLM_MODEL" in str(e.value)
    with pytest.raises(SystemExit):
        Chat(base_url="https://openrouter.ai/api/v1")        # no model named: no default model either
    for m in ("anthropic/claude-sonnet-5", "openai/gpt-5.6-luna"):    # OpenRouter is for Jev only, whatever the model
        with pytest.raises(SystemExit) as e:
            Chat(model=m, base_url="https://openrouter.ai/api/v1", api_key="k")
        assert "Jev only" in str(e.value)
    from anygame.jev import Jev
    monkeypatch.delenv("JEV_API_KEY", raising=False); monkeypatch.delenv("JEV_BASE_URL", raising=False)
    monkeypatch.setenv("JEV_MODEL", "anthropic/claude-sonnet-5")    # nor can JEV_MODEL send another model there
    with pytest.raises(RuntimeError):
        Jev()


def test_chat_routes_azure_and_openai_compatible(monkeypatch):
    from anygame.chat import Chat
    monkeypatch.setenv("ANYGAME_LLM_KEY", "k")
    monkeypatch.delenv("ANYGAME_LLM_API", raising=False)   # a configured provider would override the URL-based guess
    az = Chat(model="gpt-4o", base_url="https://myres.openai.azure.com")
    assert az.api == "azure" and az.url().startswith("https://myres.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=") and az.headers()["api-key"] == "k"
    v1 = Chat(model="gpt-4o", base_url="https://myres.openai.azure.com/openai/v1", api="azure")
    assert v1.url() == "https://myres.openai.azure.com/openai/v1/chat/completions"
    fo = Chat(model="Llama-3.3-70B", base_url="https://myres.services.ai.azure.com")
    assert fo.api == "azure-models" and "/models/chat/completions" in fo.url()
    oai = Chat(model="m", base_url="https://example.com/v1")
    assert oai.api == "openai" and oai.headers()["authorization"] == "Bearer k"
    fv1 = Chat(model="gpt-5.6-luna", base_url="https://myres.services.ai.azure.com/openai/v1/responses")   # the portal's full URL
    assert fv1.api == "azure" and fv1.url() == "https://myres.services.ai.azure.com/openai/v1/chat/completions" and fv1.headers()["api-key"] == "k"


# ---------- the Tetris compiler: candidates enumerated, consequences computed, a typed choice ----------

def test_tetris_identify_drop_settle_and_features():
    from anygame.perceive.tetris import identify, drop, settle, features, SHAPES
    assert identify({(3, 1), (4, 1), (5, 1), (4, 0)}) == ("T", 0, 3, 0)
    assert identify({(3, 1), (4, 1), (5, 1), (6, 1)})[0] == "I" and identify({(0, 0), (1, 0), (2, 0)}) is None
    stack = {(c, 19) for c in range(10) if c != 4} | {(c, 18) for c in range(10) if c not in (3, 4, 5)}
    cells, y = drop(stack, "T", 2, 3, 10, 20)
    assert cells == {(3, 18), (4, 18), (5, 18), (4, 19)}
    new, lines = settle(stack, cells, 10, 20)
    assert lines == 2 and new == set()
    f = features({(0, 19), (0, 17), (2, 19)}, 10, 20)
    assert f["heights"][0] == 3 and f["holes"] == 1 and f["max_height"] == 3 and f["well_col"] == 2


def test_tetris_tracker_ranks_landings_and_builds_macros():
    from anygame.perceive.tetris import TetrisTracker
    board = ["." * 10 for _ in range(20)]
    board[0], board[1] = "...T......", "..TTT....."
    board[18], board[19] = "###...####", "####.#####"
    t = TetrisTracker({"in": "board", "top_k": 4})
    v = t.read(board, None)
    assert v["phase"] == "spawned" and v["shape"] == "T" and v["col"] == 3 and v["stack"]["max_height"] == 2
    best = v["landings"]["a"]
    assert best.startswith("rot2 col4: clears 2") and t.macros["a"] == ["ArrowUp", "ArrowUp", "ArrowRight", "Space"]
    t.predict("a")
    # after the placement the tracker expects an empty stack; a new piece touching nothing is identified from history
    nxt = ["." * 10 for _ in range(20)]
    nxt[1] = "...IIII..."
    v2 = t.read(nxt, None)
    assert v2["last_placement"] == "ok" and v2["shape"] == "I" and v2["phase"] == "spawned" and v2["stack"]["max_height"] == 0
    # same piece one row lower is 'falling', not a new spawn
    fall = ["." * 10 for _ in range(20)]
    fall[2] = "...IIII..."
    assert t.read(fall, None)["phase"] == "falling"


def test_tetris_lookahead_ranks_by_two_pieces():
    from anygame.perceive.tetris import TetrisTracker, lookahead, features
    # a one-wide well and the next piece unknown (mean over all seven): the O never plugs the well
    board = ["." * 10 for _ in range(20)]
    board[0], board[1] = ".OO.......", ".OO......."
    for r in range(16, 20):
        board[r] = "#########."
    v = TetrisTracker({"in": "board", "lookahead": True}).read(board, None)
    assert v["shape"] == "O" and len(v["landings"]) == 6 and "holes +0" in v["landings"]["a"] and "col10" not in v["landings"]["a"]
    full = {(c, r) for c in range(10) for r in range(20)}
    assert lookahead(features(full, 10, 20), full, 0, "I", 10, 20) is None


def test_tetris_pack_reads_piece_next_and_landings_from_fixture():
    pack = load_pack(os.path.join(ROOT, "packs", "tetris"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "tetris", "fixtures", "spawn.png"))
    ag = Agent(pack, FakeDevice([frame]), None)
    values, _, _ = ag.observe(frame)
    p = values["piece"]
    assert p["shape"] == "Z" and p["next"] == "O" and p["phase"] == "spawned" and len(p["landings"]) == 6
    qs = ag.questions(values)
    assert set(qs["place__option"]["criteria"]) == set(p["landings"]) and "wait" in qs["action"]["criteria"]


# ---------- the HUD edits the paragraph live ----------

def test_hud_paragraph_edit_applies_on_the_next_tick():
    import json as _json
    import urllib.request
    from anygame.hud import Hud
    pack = load_pack(os.path.join(ROOT, "packs", "tictactoe"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-1.png"))
    hud = Hud(18765)
    try:
        ag = Agent(pack, FakeDevice([frame, frame, frame]), None, hud)
        ag.step()
        got = _json.loads(urllib.request.urlopen("http://127.0.0.1:18765/pack.json").read())
        assert "Tic-tac-toe" in got["play"] and "only:" in got["rules"]
        body = _json.dumps({"play": "Always take a corner.", "rules": "- { if: { read: status, equals: our_turn }, only: { mark__cell: empty } }\n"}).encode()
        req = urllib.request.Request("http://127.0.0.1:18765/pack.json", data=body, headers={"content-type": "application/json"}, method="POST")
        assert _json.loads(urllib.request.urlopen(req).read())["ok"]
        ag.step()
        assert ag.pack.play == "Always take a corner." and len(ag.pack.rules) == 1
        bad = urllib.request.Request("http://127.0.0.1:18765/pack.json", data=b'{"play": "x", "rules": "not: a: list"}', headers={"content-type": "application/json"}, method="POST")
        assert not _json.loads(urllib.request.urlopen(bad).read())["ok"]
    finally:
        hud.close()


def test_accent_survives_a_glyph_that_covers_most_of_the_cell():
    from anygame.perceive.color import accent_color
    img = np.full((166, 166, 3), (55, 41, 31), np.uint8)
    cv2.circle(img, (83, 83), 60, (250, 165, 96), 22)            # a thick O ring: the majority of the inset crop
    assert accent_color(img, inset=0.25) == (250, 165, 96)
    assert accent_color(np.full((166, 166, 3), (55, 41, 31), np.uint8), inset=0.25) == (55, 41, 31)


def test_author_rejects_expectations_bent_to_a_wrong_read(monkeypatch, tmp_path):
    from anygame import author as A
    (tmp_path / "pack.yaml").write_text("tests:\n  - { frame: fixtures/probe-2.png, expect: { board: ['...', '.X.', '...'] } }\n")
    exp = A.expectations(tmp_path)
    assert exp == {"fixtures/probe-2.png": {"board": ["...", ".X.", "..."]}}
    before = {"fixtures/probe-2.png": {"board": ["...", ".X.", "O.."]}}
    _chat_env(monkeypatch)
    asked = []
    monkeypatch.setattr(A.Author, "ask", lambda self, parts: (asked.append(parts), '{"1": false}')[1])
    au = A.Author()
    rejected = A.verify_changes(au, tmp_path, before, exp)
    assert len(rejected) == 1 and "the READ is wrong" in rejected[0] and asked
    assert A.verify_changes(au, tmp_path, before, before) == []      # nothing changed, nothing asked


# ---------- the hybrid: fingerprints, support, modes, the VLM fallback (stubbed) ----------

def test_fingerprints_and_support_and_modes():
    from anygame.fingerprint import fingerprint, distance, to_b64, from_b64, Index
    a = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-1.png"))
    b = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-4.png"))
    c = cv2.imread(os.path.join(ROOT, "packs", "connect4", "fixtures", "start.png"))
    fa, fb, fc = fingerprint(a), fingerprint(b), fingerprint(c)
    assert distance(fa, fb) < 25 and distance(fa, fc) > 40
    assert (from_b64(to_b64(fa)) == fa).all()
    idx = Index(); idx.add("main", fa)
    assert idx.known(fb)[0] == "main" and idx.known(fc) is None
    # support: the pack's own screen is high, a magenta screen is low and unknown
    pack = load_pack(os.path.join(ROOT, "packs", "tictactoe"))
    magenta = np.full((560, 540, 3), (200, 30, 200), np.uint8)
    ag = Agent(pack, FakeDevice([b, magenta]), ChoiceJev(noul=0.1))
    r1, r2 = ag.step(), ag.step()
    assert r1["support"] >= 0.9 and r1["mode"] == "main"
    assert r2["support"] < 0.5 and r2["known"] is None
    # modes by read condition, with their own actions, surviving a dump/load round trip
    from anygame.pack import load_pack_text, dump_pack
    raw = """
game: modal
screen: { size: [100, 100] }
zones: { status: { rect: [0, 0, 1, 0.1] } }
read: { status: { kind: color, zone: status, options: { play: "#111827", menu: "#c81e1e" }, max_dist: 60, otherwise: play } }
act: [ { id: go, kind: key, key: ArrowRight } ]
play: main screen
modes:
  menu: { when: { read: status, equals: menu }, act: [ { id: start, kind: key, key: Enter } ], play: press start }
"""
    pk = load_pack_text(raw)
    assert list(pk.modes) == ["menu"] and pk.modes["menu"].actions[0].id == "start"
    assert load_pack_text(dump_pack(pk.raw)).modes["menu"].play == "press start"
    red = np.full((100, 100, 3), (30, 30, 200), np.uint8); dark = np.full((100, 100, 3), (39, 24, 17), np.uint8)
    dev = FakeDevice([red, dark]); keys = []
    dev.key = lambda k: keys.append(k)
    ag2 = Agent(pk, dev, ChoiceJev(noul=0.1))
    s1, s2 = ag2.step(), ag2.step()
    assert s1["mode"] == "menu" and keys[0] == "Enter" and s2["mode"] == "main" and keys[1] == "ArrowRight"


def test_vlm_fallback_dismisses_transients_from_memo_and_merges_verified_modes(monkeypatch):
    from anygame.fallback import VLMFallback
    from anygame.fingerprint import fingerprint
    pack = load_pack(os.path.join(ROOT, "packs", "tictactoe"))
    good = cv2.imread(os.path.join(ROOT, "packs", "tictactoe", "fixtures", "probe-2.png"))
    magenta = np.full((560, 540, 3), (200, 30, 200), np.uint8)
    dev = FakeDevice([magenta, magenta, magenta, good]); keys = []
    dev.key = lambda k: keys.append(k)
    ag = Agent(pack, dev, ChoiceJev(noul=0.1))
    calls = []

    class StubChat:
        model = "stub"; cost = 0.0
        def complete(self, messages, max_tokens=1000, temperature=0.0):
            calls.append(messages)
            return json.dumps({"now": {"kind": "key", "key": "Enter"}, "screen": "transient", "name": "start_prompt", "note": "a start card"}), {}, 1
    ag.fallback = VLMFallback(StubChat())
    changes = []
    ag.on_pack_change = lambda y, why: changes.append(why)
    r1 = ag.step(); assert r1["action"] == "wait" and "unsupported" in r1["reason"]
    r2 = ag.step(); assert len(calls) == 1 and keys == ["Enter"] and r2["fallback"].startswith("vlm transient start_prompt")
    assert any("learned transient screen start_prompt" in c for c in changes)
    r3 = ag.step(); assert len(calls) == 1 and keys == ["Enter", "Enter"] and r3["fallback"].startswith("memo")
    r4 = ag.step(); assert r4["mode"] == "main" and r4["support"] >= 0.9 and r4["choice"] == "mark"
    # a mode definition is merged when it reads the frame as it claims, rejected when it lies
    ag2 = Agent(load_pack(os.path.join(ROOT, "packs", "tictactoe")), FakeDevice([magenta]), None)
    log = []; ag2.on_pack_change = lambda y, why: log.append(why)
    mode = {"zones": {"banner": {"rect_px": [0, 0, 540, 560]}}, "read": {"banner": {"kind": "color", "zone": "banner", "options": {"magenta": "#c81ec8", "other": "#111827"}, "max_dist": 60, "otherwise": "other"}},
            "act": [{"id": "dismiss", "kind": "key", "key": "Enter"}], "play": "press dismiss", "questions": [], "rules": [], "stop_when": None, "act_when": None}
    assert ag2.merge_mode("magenta_card", mode, {"banner": "magenta"}, magenta, fingerprint(magenta)) is True
    assert "magenta_card" in ag2.base.modes and "learned mode magenta_card" in log
    assert ag2.merge_mode("liar", mode, {"banner": "other"}, magenta, fingerprint(magenta)) is False


def test_demonstration_digest_and_author_from_demo(monkeypatch, tmp_path):
    from anygame.demo import load_demo, digest
    from anygame import author as A
    d = tmp_path / "demo"; d.mkdir()
    a = np.full((200, 200, 3), (39, 24, 17), np.uint8); b = a.copy(); b[100:150, :] = (255, 255, 255)
    cv2.imwrite(str(d / "00001.png"), a); cv2.imwrite(str(d / "00002.png"), b); cv2.imwrite(str(d / "00003.png"), a)
    events = [{"t": 0, "type": "frame", "file": "00001.png"}, {"t": 100, "type": "click", "x": 50, "y": 50},
              {"t": 300, "type": "frame", "file": "00002.png"}, {"t": 400, "type": "click", "x": 55, "y": 48, "intent": "take the centre"},
              {"t": 500, "type": "key", "key": "ArrowLeft"}, {"t": 600, "type": "frame", "file": "00003.png"}]
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (d / "meta.json").write_text(json.dumps({"source": "explorer"}))
    demo = load_demo(d)
    dg = digest(demo)
    assert dg["keys"] == {"ArrowLeft": 1} and dg["clicks"][0]["n"] == 2 and dg["intents"] == ["take the centre"]
    assert any(y == 4 for _, _, y in dg["hot"]) and dg["text"].startswith("DEMONSTRATION (explorer)")
    # the author takes the demonstration's frames as its fixtures and mentions it to the model
    seen = []
    yaml_text = open(os.path.join(ROOT, "packs", "tictactoe", "pack.yaml")).read().split("\ntests:")[0]
    def fake_ask(self, parts):
        seen.append(" ".join(p.get("text", "") for p in parts if p.get("type") == "text"))
        return "```yaml\n" + yaml_text + "\ntests:\n  - { frame: fixtures/probe-1.png, expect: {} }\n```"
    _chat_env(monkeypatch)
    monkeypatch.setattr(A.Author, "ask", fake_ask)
    out = tmp_path / "out"
    ok, _ = A.author("web://unused", "x", out, rounds=1, log=lambda m: None, demo=d, size=(200, 200))
    assert (out / "fixtures" / "probe-1.png").exists() and "DEMONSTRATION (explorer)" in seen[0] and "Use the demonstration" in seen[0]


def test_go_read_counts_captures_saves_and_eyes():
    from anygame.perceive import go
    mid = ["BBW......", "B.W......", ".BBW.....", "..W......", ".....B...", "....WW...", "...B.....", "....B...W", ".WBW....B"]
    v = go.read(mid, {"us": "B", "them": "W", "komi": 6.5})
    assert v["saves"] == ["c3r8", "c8r9"] and v["our_atari"] == ["c3r9", "c9r9"]
    assert v["self_atari"] == ["c1r9"] and "c1r9" not in v["good"]
    cap = [".........", ".........", "..W......", "....B....", "...BWB...", ".........", "..W......", ".........", "........."]
    v = go.read(cap, {})
    assert v["captures"] == ["c5r6"] and v["captured_by_move"] == {"c5r6": 1} and v["urgent"] == ["c5r6"]
    # c1r1 walled in by black is an eye: legal, never offered as good; suicide for white is not black's business
    eye = [".B.......", "B........"] + ["........."] * 7
    v = go.read(eye, {})
    assert v["eyes"] == ["c1r1"] and "c1r1" in v["legal"] and "c1r1" not in v["good"]
    assert v["score"]["us"] == 81 and v["score"]["lead"] == 81    # area scoring: every empty region touches black only


def test_a_refused_grid_tap_is_not_offered_again():
    # a Go ko recapture is legal to the stateless compiler; the page refuses it, and the loop must stop offering it
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from anygame.perceive import go
    board = [".BW......", "BW.W.....", ".BW......"] + ["........."] * 6
    vals = {"board": board, "status": "our_turn", "go": go.read(board, {})}
    a = object.__new__(Agent)
    a.pack, a.noops = load_pack(os.path.join(os.path.dirname(__file__), "..", "packs", "go")), []
    first = list(a.questions(vals)["place__cell"]["criteria"])
    a.noops = [f"place→{first[0]}"]
    assert first[0] not in a.questions(vals)["place__cell"]["criteria"]


def test_go_read_sees_a_ladder():
    from anygame.perceive import go
    v = go.read([".........", "..WW.....", ".WB......"] + ["........."] * 6, {})
    assert v["danger"] == ["c3r3"]           # white ataris at c3r4 and chases it to the edge
    mid = ["BBW..B...", "B.W..W...", ".BBW..B..", "..W...W..", ".....B...", "....WW..B", "...B...W.", "....B...W", ".WBW....B"]
    v = go.read(mid, {"komi": 6.5})
    assert "c9r7" in v["doomed"] and "c9r7" not in v["best"]


def test_slide_compiler_ranks_only_moving_swipes_and_offers_them_as_the_action():
    from anygame.perceive.slide import rank, move
    g = (0, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0)
    r = rank(g)
    assert r["best"] == r["legal"][0] and set(r["legal"]) == {"up", "down", "left", "right"}
    assert list(r["ranked"])[0] == r["best"] and r["ranked"][r["best"]].startswith("#1 best")
    full = (4, 8, 2, 4, 2, 4, 8, 32, 4, 2, 32, 8, 8, 16, 64, 256)
    assert rank(full)["legal"] == [] and rank(full)["best"] == "none"
    # a swipe that does not move the board is never offered
    blocked = (2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 0, 0, 0, 0)
    assert "down" not in rank(blocked)["legal"] or move(blocked, "down")[0] != blocked
    assert all(move(blocked, d)[0] != blocked for d in rank(blocked)["legal"])
    # the pack's action question takes its options from the compiled read
    pack = load_pack(os.path.join(ROOT, "packs", "2048"))
    frame = cv2.imread(os.path.join(ROOT, "packs", "2048", "fixtures", "board-a.png"))
    jev = FakeJev()
    Agent(pack, FakeDevice([frame]), jev).step()
    assert list(jev.seen[0])[0] == "left" and jev.seen[0]["left"].startswith("#1 best")


def test_go_playouts_score_the_candidates_the_same_way_every_time():
    from anygame.perceive import go
    # white's big chain in the middle is in atari: taking it wins the random games, the other moves mostly do not
    board = [".........", "...BBB...", "..BWWWB..", "..BWWWB..", "..BWW.B..", "...BBB...", "........."] + ["........."] * 2
    v = go.read(board, {"komi": 6.5, "playouts": 32})
    assert "playouts" not in go.read(board, {"komi": 6.5})          # opt-in
    po = v["playouts"]
    assert set(po) == set(v["best"]) | set(v["captures"]) and v["captures"] == ["c6r5"]
    assert po["c6r5"]["win"] >= 0.9 and all(0 <= x["win"] <= 1 for x in po.values())
    go._PLAYOUT_CACHE.clear()
    assert go.read(board, {"komi": 6.5, "playouts": 32})["playouts"] == po    # seeded from the board


def test_go_rerank_puts_the_playout_leader_first_past_the_margin():
    from anygame.perceive import go
    po = {"a": {"win": 0.50, "margin": 1.0, "n": 160}, "b": {"win": 0.55, "margin": 2.0, "n": 160},
          "c": {"win": 0.58, "margin": 3.0, "n": 160}, "d": {"win": 0.90, "margin": 9.0, "n": 32}}
    good = {"a", "b", "c", "d"}
    extra: dict = {}
    # c beats the worth top a by 0.08: it goes first; d's 32-game 0.90 is a guess and never leads
    assert go.rerank(["a", "b", "c", "d"], po, good, 0.06, extra) == ["c", "a", "b", "d"]
    assert extra["reranked"] == {"from": "a", "to": "c", "gap": 0.08}
    # below the margin, best stays in worth order and says nothing
    extra = {}
    assert go.rerank(["a", "b", "c", "d"], po, good, 0.10, extra) == ["a", "b", "c", "d"] and "reranked" not in extra
    # a move that is not good (an own eye, a self-atari) never leads; a capture outside best can
    extra = {}
    assert go.rerank(["a", "b"], po, {"a", "b", "d"}, 0.04, extra) == ["b", "a"]
    po["e"] = {"win": 0.70, "margin": 5.0, "n": 160}
    assert go.rerank(["a", "b"], po, {"a", "b", "e"}, 0.06, {}) == ["e", "a", "b"]
    # the worth top already leads, or has no playouts: unchanged
    assert go.rerank(["e", "a"], po, good | {"e"}, 0.06, {}) == ["e", "a"]
    assert go.rerank(["z", "a"], po, good, 0.06, {}) == ["z", "a"]


def test_go_read_reranks_best_only_when_asked(monkeypatch):
    from anygame.perceive import go
    board = ["........."] * 9
    plain = go.read(board, {"komi": 6.5, "playouts": 8})
    top, low = plain["best"][0], plain["best"][-1]
    fake = {k: {"win": 0.5, "margin": 0.0, "n": 160} for k in plain["best"]}
    fake[low] = {"win": 0.7, "margin": 4.0, "n": 160}
    monkeypatch.setattr(go, "playouts", lambda *a, **k: dict(fake))
    assert go.read(board, {"komi": 6.5, "playouts": 8})["best"] == plain["best"]           # opt-in
    v = go.read(board, {"komi": 6.5, "playouts": 8, "rerank": "playouts"})
    assert v["best"][0] == low and v["reranked"] == {"from": top, "to": low, "gap": 0.2}
    assert list(v["worth"]) == v["best"] and sorted(v["best"]) == sorted(plain["best"])
    assert go.read(board, {"komi": 6.5, "playouts": 8, "rerank": "playouts", "rerank_margin": 0.25})["best"] == plain["best"]


def test_go_pack_turns_the_rerank_on():
    import yaml
    r = yaml.safe_load(open(os.path.join(ROOT, "packs", "go", "pack.yaml")))["read"]["go"]
    assert r["rerank"] == "playouts" and r["rerank_margin"] == 0.06 and r["playouts_top_n"] == 160


def test_go_playouts_spend_more_games_on_the_leaders():
    from anygame.perceive import go
    v = go.read(["........."] * 9, {"komi": 6.5, "playouts": 8, "playouts_top": 2, "playouts_top_n": 24})
    ns = sorted(x["n"] for x in v["playouts"].values())
    assert ns[-2:] == [24, 24] and set(ns[:-2]) == {8}


def test_clm_stub_takes_the_top_of_a_ranked_read_when_told(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("clm_stub", os.path.join(ROOT, "test", "clm_stub.py"))
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    state = {"screen": {"go": {"best": ["c5r5", "c3r3", "c7r7"]}}}
    q = {"place__cell": {"type": "choice", "criteria": {"c3r3": None, "c5r5": None, "c7r7": None}}}
    assert stub.answer(state, q)["place__cell"]["choice"] == "c3r3"          # board order: top-left first
    monkeypatch.setattr(stub, "RANK", "screen.go.best")
    assert stub.answer(state, q)["place__cell"]["choice"] == "c5r5"          # the compiler's top pick
    q2 = {"place__cell": {"type": "choice", "criteria": {"c3r3": None, "c7r7": None}}}
    assert stub.answer(state, q2)["place__cell"]["choice"] == "c3r3"         # the top was not offered: next ranked
