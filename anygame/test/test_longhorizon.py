"""Long-horizon play: run memory, goals written from dialogue (with a stand-in chat model), menus read by trying
their entries from a save state, the Jev audit's verdicts, and checkpoints."""
import copy
import json
import numpy as np
from anygame.memory import RunMemory, similar
from anygame.goals import GoalBook, check, check_target
from anygame.perceive.menu import MenuTracker
from anygame.audit import Auditor


# ---- memory ---------------------------------------------------------------------------------------------
def test_memory_keeps_a_line_once_and_where_it_was_said():
    m = RunMemory()
    v = {"map": 7, "x": 32, "y": 48}
    assert m.observe(1, 10, v, "Mom: go see the", (2, 3)) is not None
    assert m.observe(2, 20, v, "Mom: go see the professor", (2, 3)) is None      # the same line, typed further
    assert m.observe(3, 30, {"map": 7, "x": None, "y": None}, "Mom: go see the profesor", None) is None   # OCR noise
    e = m.observe(4, 40, {"map": 7, "x": None, "y": None}, "Take this map with you", None)
    assert e["tile"] == [2, 3] and e["pos"] == "last known"
    assert [d["text"] for d in m.dialogue] == ["Mom: go see the professor", "Take this map with you"]
    assert list(m.places) == ["7"] and m.places["7"]["entered"] == 1
    assert similar("WORK IN PROGRESS AHEAD!", "HORK IN PROGRESS AHEAD")


# ---- goals ----------------------------------------------------------------------------------------------
class FakeChat:
    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def complete(self, messages, max_tokens=1000, temperature=0.0):
        self.seen.append(json.loads(messages[-1]["content"]))
        return self.answers.pop(0), {"total_tokens": 100}, 5


def test_conditions_are_checked_before_a_goal_is_set():
    assert check({"new_place": True}) is None
    assert check({"said": ["professor"]}) is None
    assert check({"place": 3}, {"3"}) is None and check({"place": 4}, {"3"})
    assert check({"any": [{"talks": 2}, {"screen": "choice"}]}) is None
    assert check({"ram": 0xD35E}) and check({"new_place": True, "said": ["x"]})
    assert check_target({"toward": "up"}, set(), 0) is None and check_target({"toward": "north"}, set(), 0)
    assert check_target({"line": 0}, set(), 1) is None and check_target({"line": 3}, set(), 1)


def test_a_number_goal_checks_and_holds():
    m = RunMemory()
    chat = FakeChat([json.dumps({"goal": {"instruction": "heal up", "done": {"number": {"name": "SQUIRTLE #/#", "share_at_least": 0.8}}}})])
    gb = GoalBook(m, chat)
    low = {"map": 1, "x": 0, "y": 0, "screen": "walk", "numbers": {"SQUIRTLE #/#": {"value": 4, "of": 19, "share": 0.21}}}
    assert gb.update(1, low)["instruction"] == "heal up"
    assert chat.seen[0]["numbers"] == {"SQUIRTLE #/#": "4/19"}
    gb.update(2, low)
    assert gb.goals[0]["outcome"] is None
    gb.update(3, {**low, "numbers": {"SQUIRTLE #/#": {"value": 19, "of": 19, "share": 1.0}}})
    assert gb.goals[0]["outcome"] == "reached"
    assert check({"number": {"name": "LEVEL", "at_least": 14}}, numbers={"SQUIRTLE #/#"})


def test_goal_from_dialogue_then_reached_then_the_next_one():
    m = RunMemory()
    chat = FakeChat([
        json.dumps({"why": "mom said to go outside", "goal": {"instruction": "leave the house", "done": {"new_place": True},
                                                               "target": {"toward": "down"}, "ticks": 100}}),
        json.dumps({"why": "the man asked for the key", "goal": {"instruction": "find the key", "done": {"said": ["key"]}, "target": None}}),
    ])
    gb = GoalBook(m, chat, {"min_gap": 1})
    walk = {"map": 1, "x": 16, "y": 16, "screen": "walk"}
    m.observe(1, 0, {**walk, "screen": "text"}, "Mom: go outside and play!", (1, 1))
    assert gb.update(1, {**walk, "screen": "text"}) is None         # no goal is written in the middle of a dialogue
    q = gb.update(2, walk)
    assert q == {"id": "g1", "instruction": "leave the house", "target": {"toward": "down"}}
    assert chat.seen[0]["dialogue"][0]["text"] == "Mom: go outside and play!"
    m.observe(3, 0, {**walk, "map": 2, "screen": "text"}, "I lost my key somewhere", (4, 4))
    q = gb.update(4, {**walk, "map": 2})                              # a new place: reached; the writer reads the man
    assert gb.goals[0]["outcome"] == "reached"
    assert q["instruction"] == "find the key"
    m.observe(5, 0, {**walk, "map": 2, "screen": "text"}, "You found the KEY!", (5, 5))
    q = gb.update(6, {**walk, "map": 2})
    assert gb.goals[1]["outcome"] == "reached"
    assert q["id"].startswith("explore") and gb.calls == 3 and gb.failures == 1   # no answer left: generic goal


def test_a_goal_that_does_not_check_is_refused():
    m = RunMemory()
    chat = FakeChat([json.dumps({"goal": {"instruction": "go to map 0x26", "done": {"map_id": 38}}})])
    gb = GoalBook(m, chat)
    q = gb.update(1, {"map": 1, "x": 0, "y": 0, "screen": "walk"})
    assert gb.failures == 1 and q["id"].startswith("explore")


def test_goals_survive_a_checkpoint_dump():
    m = RunMemory()
    gb = GoalBook(m, None)
    gb.update(1, {"map": 1, "x": 0, "y": 0, "screen": "walk"})
    m2, gb2 = RunMemory(), GoalBook(RunMemory(), None)
    m2.load(json.loads(json.dumps(m.dump())))
    gb2.load(json.loads(json.dumps(gb.dump())))
    assert gb2.quest() == gb.quest() and m2.places == m.places


# ---- menus ----------------------------------------------------------------------------------------------
class MenuGame:
    """A 3-entry vertical menu that wraps; entry 2 opens a text, entry 3 does nothing; B closes the menu."""
    clock = "game"

    def __init__(self):
        self.s = {"cur": 0, "open": True, "text": None}
        self.frames = 0
        self.discoverer = None
        self.real_presses = []

    def snapshot(self):
        return copy.deepcopy(self.s), self.frames

    def restore(self, snap):
        self.s, self.frames = copy.deepcopy(snap[0]), snap[1]

    def press(self, k, hold=4, after=8):
        self.frames += hold + after
        self.real_presses.append(k)
        s = self.s
        if not s["open"]:
            return
        if k == "down":
            s["cur"] = (s["cur"] + 1) % 3
        elif k == "up":
            s["cur"] = (s["cur"] - 1) % 3
        elif k == "a":
            s["text"] = {0: "NEW GAME", 1: "OPTIONS SPEED", 2: None}[s["cur"]]
        elif k == "b":
            s["open"] = False

    def wait(self, n):
        self.frames += n

    def screen(self):
        img = np.full((432, 480, 3), 240, np.uint8)
        if self.s["open"]:
            y = 60 + 60 * self.s["cur"]
            img[y:y + 30, 30:60] = 20                   # the cursor
            for i in range(3):
                img[60 + 60 * i: 60 + 60 * i + 30, 90:300] = 200   # the entries' boxes
        if self.s["text"]:
            img[330:420, :] = 0 if self.s["text"] == "NEW GAME" else 100
        return img


def test_menu_entries_found_by_trying_and_ranked(monkeypatch):
    import anygame.perceive.menu as menu
    monkeypatch.setattr(menu, "_ocr_boxes", lambda img: [])
    monkeypatch.setattr("anygame.perceive.ocr._text", lambda img, up=2.0: "", raising=False)
    g = MenuGame()
    t = MenuTracker({"depth": 4})
    v = t.read(g, g.screen())
    assert v["entries"] == 3
    assert g.s == {"cur": 0, "open": True, "text": None} and g.real_presses[-1] in ("a", "b", "down", "up", "start", "select")   # put back
    lands = list(v["landings"])
    assert lands == ["pick_1", "pick_2", "back_out"]               # entry 3 does nothing: not offered while others do
    assert t.plans["pick_2"] == ["down", "a"]
    g.real_presses.clear()
    t.run(g, "pick_2", lambda: {})
    assert g.real_presses == t.plans["pick_2"] and g.s["text"] is not None


def test_a_pick_that_comes_straight_back_twice_is_dropped(monkeypatch):
    import anygame.perceive.menu as menu
    monkeypatch.setattr(menu, "_ocr_boxes", lambda img: [])
    g = MenuGame()
    t = MenuTracker({"depth": 4})
    for _ in range(2):
        assert "pick_1" in t.read(g, g.screen())["landings"]
        t.run(g, "pick_1", lambda: {})
        t.see(g.screen())                               # the box it opened, for a tick
        g.s = {"cur": 0, "open": True, "text": None}    # then it closes, back on the same menu
    lands = t.read(g, g.screen())["landings"]
    assert "pick_1" not in lands and "pick_2" in lands
    t2 = MenuTracker({"depth": 4})
    t2.load(json.loads(json.dumps(t.dump())))
    assert t2.loops == t.loops


# ---- the audit ------------------------------------------------------------------------------------------
class TinyDevice:
    def __init__(self):
        self.pos = 0
        self.frames = 0

    def snapshot(self):
        return (self.pos, self.frames)

    def restore(self, s):
        self.pos, self.frames = s


class TinyWorld:
    def __init__(self):
        self.visited = {0: {(0, 0)}}
        self.inspected = set()


class TinyAgent:
    """Walks right on `go→far`, stays on `go→near`; the stand-in after the pick always waits."""
    def __init__(self):
        self.device = TinyDevice()
        self.worlds = {"world": TinyWorld()}
        self.memory = None
        self.goalbook = None
        self.tick = 0
        self.last_values = {}
        self.jev = None
        self.log = None
        self.on_record = None
        self.hud = None
        self.record_dir = None

        class P:
            def action(self, c):
                from anygame.pack import Action
                return Action(c, "macro")
        self.pack = P()

    def _apply_rules(self, answers, values):
        return []

    def act(self, action, answers):
        if answers.get("go__option", {}).get("choice") == "far":
            for i in range(1, 4):
                self.worlds["world"].visited[0].add((i, 0))
        return "ok"

    def step(self):
        self.tick += 1
        return {"action": "wait"}


def test_audit_agree_and_played_out_verdicts():
    a = TinyAgent()
    qs = {"action": {"type": "choice", "criteria": {"go": "", "wait": ""}},
          "go__option": {"type": "choice", "criteria": {"near": "", "far": ""}}}
    au = Auditor(horizon=3)
    same = {"action": {"choice": "go"}, "go__option": {"choice": "near"}}
    assert au.check(a, qs, same, {})["verdict"] == "agree"
    better = {"action": {"choice": "go"}, "go__option": {"choice": "far"}}
    r = au.check(a, qs, better, {})
    assert r["verdict"] == "jev better" and r["jev_score"]["novelty"] == 3 and r["top_score"]["novelty"] == 0
    assert len(a.worlds["world"].visited[0]) == 1 and a.tick == 0      # the branches left nothing behind
    rep = au.report()
    assert rep["decisions"] == 2 and rep["agree_share"] == 0.5 and rep["jev_helped_share"] == 0.5


# ---- places and checkpoints on the grid world --------------------------------------------------------------
def test_a_signature_change_without_a_jump_is_the_same_place():
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map"})
    assert w.tile_of({"map": 11, "x": 3, "y": 3}) == (11, 3, 3)
    assert w.tile_of({"map": 99, "x": 3, "y": 4}) == (11, 3, 4)       # a byte of the signature changed mid-dialogue
    assert w.tile_of({"map": 42, "x": 9, "y": 1}) == (42, 9, 1)       # the position jumped with it: a door
    assert w.tile_of({"map": 99, "x": 9, "y": 2}) == (11, 9, 2)       # an alias stays one for the run
    assert w.tile_of({"map": 7, "x": 9, "y": 2}, stepping=True) == (7, 9, 2)   # stairs onto the same tile, while walking
    assert w.tile_of({"map": 8, "x": 9, "y": 3}, stepping=True) == (7, 9, 3)   # one plain step: scenery, not a door
    d = w.dump()
    w2 = WorldTracker({"x": "x", "y": "y", "map": "map"})
    w2.load(json.loads(json.dumps(d)))
    assert w2.alias == {99: 11, 8: 7}


def test_checkpoint_resumes_the_run(tmp_path):
    import pickle
    from test_world import GridGame, PACK
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from anygame.memory import save_checkpoint, load_checkpoint
    from anygame.sensors import open_sensor

    class SavingGrid(GridGame):
        def save_state(self, path):
            with open(path, "wb") as f:
                pickle.dump(self.__dict__, f)

        def load_state(self, path):
            with open(path, "rb") as f:
                self.__dict__.update(pickle.load(f))

    text = PACK.replace("goals:", "goals_from: dialogue\ngoals_old:")
    (tmp_path / "pack.yaml").write_text(text)
    (tmp_path / "s.json").write_text('{"map": 0, "x": 2, "y": 3}')
    pack = load_pack(tmp_path)
    g = SavingGrid()
    a = Agent(pack, g, open_sensor("top"), None, max_ticks=40, background=False)
    a.run()
    assert a.goalbook.current is not None and a.memory.places
    save_checkpoint(a, str(tmp_path / "ck"))
    g2 = SavingGrid()
    b = Agent(pack, g2, open_sensor("top"), None, max_ticks=60, background=False)
    load_checkpoint(b, str(tmp_path / "ck"))
    assert (g2.map, g2.x, g2.y) == (g.map, g.x, g.y) and b.tick == a.tick
    assert b.worlds["world"].visited == a.worlds["world"].visited
    assert b.memory.places == a.memory.places and b.goalbook.quest() == a.goalbook.quest()
    b.run()
    assert b.tick == 60


def test_the_generic_game_boy_pack_loads():
    import os
    from anygame.pack import load_pack
    pack = load_pack(os.path.join(os.path.dirname(__file__), "..", "packs", "gameboy"))
    assert pack.reads["text"]["kind"] == "tiletext" and pack.reads["menu"]["text"] == "tiletext"


def test_a_walk_that_ends_back_on_its_tile_twice_is_dropped():
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map"})
    v = {"map": 1, "x": 4, "y": 5}
    lands = w.read(v)["landings"]
    lab = next(k for k in lands if k.startswith("explore_"))
    for _ in range(2):
        w._pending = (w.here, tuple(w.plans[lab]))     # walked it (a script pushed the player back)...
        lands = w.read(v)["landings"]                 # ...and the next decision is on the same tile
    assert lab not in lands and lands


def test_a_pick_that_comes_back_through_another_screen_twice_is_dropped(monkeypatch):
    import anygame.perceive.menu as menu
    monkeypatch.setattr(menu, "_ocr_boxes", lambda img: [])
    g = MenuGame()
    t = MenuTracker({"depth": 4})
    for _ in range(2):
        t.read(g, g.screen())
        t.run(g, "pick_1", lambda: {})
        t.see(g.screen())                      # a card it opened, for a tick
        g.s = {"cur": 0, "open": False, "text": "CARD"}
        t.read(g, g.screen())                  # read as a screen of its own (one entry: A dismisses it)
        g.s = {"cur": 0, "open": True, "text": None}
    lands = t.read(g, g.screen())["landings"]
    assert "pick_1" not in lands and "pick_2" in lands


def test_a_checkpoint_keeps_the_glyphs_learned(tmp_path):
    """A resumed run reads the text it had learned to read, without asking the labeller again."""
    from anygame.perceive import tiletext
    from anygame.memory import _glyph_books
    saved = dict(tiletext._BOOKS)
    try:
        tiletext._BOOKS.clear()
        bk = tiletext._BOOKS[""] = tiletext.GlyphBook()
        bk.labels.update({"k1": "A", "k2": "B"})
        d = json.loads(json.dumps(_glyph_books()))
        tiletext._BOOKS.clear()                           # a new process
        tiletext.restore_books(d)
        assert tiletext._BOOKS[""].labels == {"k1": "A", "k2": "B"}
        assert tiletext.reader({"kind": "tiletext"}).book is tiletext._BOOKS[""]
    finally:
        tiletext._BOOKS.clear()
        tiletext._BOOKS.update(saved)
