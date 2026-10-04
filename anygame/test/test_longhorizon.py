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
def test_places_come_from_the_place_book_and_survive_a_checkpoint():
    """Tiles are keyed by place id (anygame/places.py): a new name while standing is the same place, a jump with a new
    name is a door, a walk off the far side is a join; a merge moves what was learned to the surviving id."""
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map"})
    town = w.tile_of({"map": 11, "x": 3, "y": 3})[0]
    assert w.tile_of({"map": 99, "x": 3, "y": 3})[0] == town          # a byte of the signature changed mid-dialogue
    w._moves, w._walking = ["up"], True
    assert w.tile_of({"map": 42, "x": 9, "y": 9})[0] != town          # the position jumped with it: a door
    w._moves, w._walking = ["down"], True
    assert w.tile_of({"map": 11, "x": 3, "y": 4})[0] == town          # back out to the town
    w._moves, w._walking = ["up"] * 4, True
    w.tile_of({"map": 11, "x": 3, "y": 0})
    w._moves, w._walking = ["up"], True
    route = w.tile_of({"map": 11, "x": 3, "y": 35})[0]                # off the top, onto the bottom row: a join
    assert route != town
    w.visit((route, 3, 35))
    w._rekey(route, town)
    assert (3, 35) in w.visited[town] and route not in w.visited
    d = w.dump()
    w2 = WorldTracker({"x": "x", "y": "y", "map": "map"})
    w2.load(json.loads(json.dumps(d)))
    assert w2.book.to_dict()["joins"] == w.book.to_dict()["joins"]


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


def test_a_jump_that_does_not_happen_again_is_forgotten():
    """A within-map jump learned from a misread position is dropped the first time walking that edge does not jump."""
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"kind": "world", "pos": ["x", "y"]})
    assert w.learn((0, 3, 3), "left", (0, 9, 9)) == "warp"
    assert (0, 3, 3, "left") in w.warps
    assert w.learn((0, 3, 3), "left", (0, 2, 3)) == "moved"
    assert (0, 3, 3, "left") not in w.warps
    w.learn((0, 3, 3), "up", (0, 9, 9))
    w.learn((0, 3, 3), "up", (0, 3, 3))           # bumped: not a jump either
    assert (0, 3, 3, "up") not in w.warps


def test_the_writer_is_not_asked_again_without_news():
    """A goal reached with nothing new said since: the generic goal follows, for free. A new line asks again."""
    m = RunMemory()
    chat = FakeChat([json.dumps({"goal": {"instruction": "leave the house", "done": {"new_place": True}}}),
                     json.dumps({"goal": {"instruction": "find the old man", "done": {"talks": 1}}})])
    gb = GoalBook(m, chat, {"min_gap": 1})
    walk = {"map": 1, "x": 0, "y": 0, "screen": "walk"}
    m.observe(1, 0, {**walk, "screen": "text"}, "Mom: go outside and play!", (0, 0))
    assert gb.update(2, walk)["instruction"] == "leave the house"
    m.observe(3, 0, {**walk, "map": 2}, None)
    q = gb.update(4, {**walk, "map": 2})
    assert q["id"].startswith("explore") and gb.calls == 1
    m.observe(5, 0, {**walk, "map": 2, "screen": "text"}, "An old man waits by the river north of town", (0, 0))
    assert gb.update(6, {**walk, "map": 2})["instruction"] == "find the old man" and gb.calls == 2


def test_a_button_that_jumps_becomes_an_option(monkeypatch):
    """Learning the buttons: an input that jumps or goes further than the plain direction is offered as a plan."""
    from anygame import motion
    from anygame.perceive.world import WorldTracker
    mv = lambda keys, kind="move", rx=0.0, ry=0.0: {"keys": keys, "hold": 32, "kind": kind, "reach_x": rx, "reach_y": ry,
                                                    "dx": rx, "dy": ry, "dx_held": rx, "air_samples": 6}
    m = {"moves": [mv(["right"], rx=16), mv(["b"], "jump", ry=-45), mv(["right", "a"], rx=40), mv(["right", "b"], rx=16)],
         "every": 2}
    monkeypatch.setattr(motion, "learn", lambda device: m)
    class Dev:
        def snapshot(self): return None
    w = WorldTracker({"kind": "world", "pos": ["x", "y"]})
    assert w.learn_motion(Dev(), 0)
    assert set(w.moves) == {"move_b", "move_right_a"}
    assert w.learn_motion(Dev(), 0) is None                     # once per place
    out = w.read({"map": 0, "x": 1, "y": 1})
    assert w.plans["move_b"] == ["hold:b:32"] and "jumps" in out["landings"]["move_b"]


def test_a_stalled_said_goal_offers_a_menu_chain_search_once():
    """A goal waiting for the game to tell of something, with the walk stalled: one menu-chain search is offered."""
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map", "chain_after": 2})
    calls = []
    w.chain_fn = lambda dev, words: calls.append(words) or "played start > a: Got POTION"
    w.wants = ("g7", ["POTION"])
    w.read({"map": 0, "x": 1, "y": 1})                  # the first read is news: the tile is new
    w.stale = 5
    out = w.read({"map": 0, "x": 1, "y": 1})
    assert "search_menus" in out["landings"]
    r = w.run(object(), "search_menus", lambda: {"map": 0, "x": 1, "y": 1})
    assert calls == [["POTION"]] and "Got POTION" in r
    w.stale = 5
    assert "search_menus" not in w.read({"map": 0, "x": 1, "y": 1})["landings"]


def test_places_come_from_the_place_book():
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map"})
    home = w.tile_of({"map": 11, "x": 3, "y": 3})[0]
    assert w.tile_of({"map": 99, "x": 3, "y": 3})[0] == home          # a byte of the signature changed mid-dialogue
    door = w.tile_of({"map": 42, "x": 9, "y": 1})[0]
    assert door != home                                                 # the position jumped with it: a door
    stairs = w.tile_of({"map": 7, "x": 9, "y": 1}, stepping=True, moves=("down",))[0]
    assert stairs not in (home, door)                                   # stairs onto the same tile, while walking
    w.tile_of({"map": 7, "x": 9, "y": 0}, stepping=True, moves=("up",))
    route = w.tile_of({"map": 7, "x": 9, "y": 35}, stepping=True, moves=("up",))[0]
    assert route != stairs                                              # off the top row onto the next map, no door
    assert w.book.neighbours(stairs) == {"up": route}
    d = w.dump()
    w2 = WorldTracker({"x": "x", "y": "y", "map": "map"})
    w2.load(json.loads(json.dumps(d)))
    assert w2.book.joins == w.book.joins and w2.tile_of({"map": 7, "x": 9, "y": 34}, stepping=True, moves=("up",))[0] == route


def test_upkeep_advice_becomes_the_goal_and_menus_put_exits_first(monkeypatch):
    """A number low: the goal book takes the upkeep goal once; a menu with leave set ranks the entry that gets back to
    the world first."""
    m = RunMemory()
    gb = GoalBook(m, None)
    walk = {"map": 1, "x": 0, "y": 0, "screen": "walk"}
    goal = {"instruction": "Get HP back up", "done": {"number": {"name": "HP", "share_at_least": 0.9}}, "target": None}
    assert gb.impose(goal, 5, walk) and gb.current["source"] == "upkeep"
    assert not gb.impose(goal, 6, walk)
    other = {**goal, "done": {"number": {"name": "HP (2)", "share_at_least": 0.9}}}
    assert not gb.impose(other, 7, walk) and len(gb.goals) == 1          # not a new goal every tick
    tr = MenuTracker({"kind": "menu"})
    tr.leave = True
    from anygame.upkeep import rank_exits
    entries = {"pick_1": {"ends_on": "choice", "frames": 10}, "pick_2": {"ends_on": "walk", "frames": 300}}
    assert rank_exits(entries) == ["pick_2"]


def test_a_walk_pushed_back_after_a_talk_counts_as_stuck():
    """The pushback comes after the text: reads during the talk do not clear the plan, so it is dropped after two."""
    from anygame.perceive.world import WorldTracker
    w = WorldTracker({"x": "x", "y": "y", "map": "map"})
    w.read({"map": 0, "x": 5, "y": 5, "screen": "walk"})
    w.visited[0] |= {(4, 5), (6, 5), (5, 4)}
    for _ in range(2):
        w.read({"map": 0, "x": 5, "y": 5, "screen": "walk"})
        w._pending = (w.here, ("down", "down"))
        w.read({"map": 0, "x": 5, "y": 6, "screen": "text"})      # stepped once, then the talk
    w.read({"map": 0, "x": 5, "y": 5, "screen": "walk"})          # pushed back
    assert w.stuck.get((w.here, ("down", "down"))) == 2


class GridMenu(MenuGame):
    """A 2 x 2 battle menu (FIGHT PKMN / ITEM RUN): the cursor moves on both axes and stops at the edges."""

    def __init__(self):
        super().__init__()
        self.s = {"r": 0, "c": 0, "open": True, "text": None}

    def press(self, k, hold=4, after=8):
        self.frames += hold + after
        self.real_presses.append(k)
        s = self.s
        if k in ("down", "up"):
            s["r"] = 1 if k == "down" else 0
        elif k in ("right", "left"):
            s["c"] = 1 if k == "right" else 0
        elif k == "a":
            s["text"] = ["FIGHT", "PKMN", "ITEM", "RUN"][s["r"] * 2 + s["c"]]

    def screen(self):
        img = np.full((432, 480, 3), 240, np.uint8)
        y, x = 60 + 120 * self.s["r"], 30 + 220 * self.s["c"]
        img[y:y + 30, x:x + 30] = 20
        if self.s["text"]:
            img[330:420, :] = {"FIGHT": 0, "PKMN": 60, "ITEM": 120, "RUN": 180}[self.s["text"]]
        return img


def test_a_grid_menu_reaches_its_corner(monkeypatch):
    """RUN sits down and right of FIGHT: an entry reached on one axis is tried along the other too."""
    import anygame.perceive.menu as menu
    monkeypatch.setattr(menu, "_ocr_boxes", lambda img: [])
    monkeypatch.setattr("anygame.perceive.ocr._text", lambda img, up=2.0: "", raising=False)
    g = GridMenu()
    t = MenuTracker({"depth": 3})
    t.read(g, g.screen())
    assert ["down", "right", "a"] in t.plans.values()


def test_upkeep_need_without_a_refill_place_asks_the_writer_how():
    """Upkeep knows HP must go back up but not where: the writer says how (talk to someone at home), the done
    condition stays upkeep's, and the goal keeps upkeep as its source so upkeep does not set it again."""
    m = RunMemory()
    m.places = {"3": {"first_tick": 1, "entered": 2}}
    ans = json.dumps({"why": "mom offered rest", "goal": {"instruction": "Talk to Mom at home",
                      "done": {"talks": 1}, "target": {"place": 3}, "ticks": 200}})
    chat = FakeChat([ans])
    gb = GoalBook(m, chat)
    walk = {"map": 1, "x": 0, "y": 0, "screen": "walk"}           # HP is not on a walking screen
    goal = {"instruction": "Get HP back up", "done": {"number": {"name": "HP", "share_at_least": 0.9}}, "target": None}
    assert gb.impose(goal, 5, walk)
    assert chat.seen[0]["need"]["done"] == goal["done"]
    g = gb.current
    assert g["instruction"] == "Talk to Mom at home" and g["target"] == {"place": 3}
    assert g["done"] == {"any": [goal["done"], {"talks": 1}]}     # the rest given counts: HP is off screen
    assert g["source"] == "upkeep" and not gb.impose(goal, 6, walk)
    gb._close(g, "reached", 9)
    assert gb.need_met is g


def test_upkeep_tracks_come_back_from_a_checkpoint_with_their_sets(tmp_path):
    """JSON stores a Track's set of drop sizes as a list; a resumed run adds to it, so it must be a set again."""
    import types
    from anygame.memory import load_checkpoint
    from anygame.upkeep import Upkeep, Track
    t = Track("HP")
    t.drops.add(3)
    (tmp_path / "run.json").write_text(json.dumps({"tick": 9, "worlds": {}, "upkeep": {"HP": dict(t.__dict__, drops=[3])}}))
    agent = types.SimpleNamespace(device=object(), worlds={}, keep=Upkeep())
    load_checkpoint(agent, str(tmp_path))
    agent.keep.tracks["HP"].drops.add(5)
    assert agent.keep.tracks["HP"].drops == {3, 5}


def test_a_stall_leaves_the_repeated_options_out_of_the_next_questions():
    from anygame.loop import _without
    qs = {"go__option": {"type": "choice", "instructions": "?", "criteria": {"explore_down": "a", "door_1": "b"}},
          "pick__option": {"type": "choice", "instructions": "?", "criteria": {"explore_down": "only"}}}
    out = _without(qs, {"explore_down"})
    assert list(out["go__option"]["criteria"]) == ["door_1"]
    assert list(out["pick__option"]["criteria"]) == ["explore_down"]     # nothing else to take: left as it was


def test_a_position_held_long_is_put_back_when_discovery_swaps_it():
    import types
    from anygame.loop import Agent as Loop
    disc = types.SimpleNamespace(found={"x": {"addr": 1, "type": "u8"}, "y": {"addr": 2, "type": "u8"}})
    lp = types.SimpleNamespace(base=types.SimpleNamespace(raw={"pos_lock": 3}), device=types.SimpleNamespace(discoverer=disc), tick=0)
    for t in range(5):
        lp.tick = t
        Loop._hold_position(lp)
    disc.found["y"] = {"addr": 9, "type": "u8"}        # a scroll byte wins a stretch
    lp.tick = 6
    Loop._hold_position(lp)
    assert disc.found["y"]["addr"] == 2


def test_a_refill_sign_said_meets_the_need_even_under_another_goal():
    m = RunMemory()
    gb = GoalBook(m, None)
    gb.goals = [{"id": "g1", "source": "upkeep", "outcome": "given up",
                 "done": {"any": [{"number": {"name": "HP", "share_at_least": 0.9}}, {"said": ["looking great"]}]}}]
    gb._refill_sign("MOM: Your POKEMON are looking great!")
    assert gb.need_met is gb.goals[0]


def test_a_screen_that_never_ends_in_any_direction_is_not_explored_as_a_menu():
    import numpy as np
    from anygame.perceive.menu import MenuTracker

    class Endless:
        def __init__(self):
            self.n, self.frames = 0, 0
        def snapshot(self):
            return self.n
        def restore(self, s):
            self.n = s
        def press(self, k, hold=0, after=0):
            self.n += {"up": 1, "down": 7, "left": 31, "right": 97}.get(k, 0)
        def wait(self, n=1):
            pass
        def screen(self):
            img = np.zeros((144, 160), np.uint8)
            img[(self.n * 13) % 140:(self.n * 13) % 140 + 4, :] = 255
            img[:, (self.n * 29) % 150:(self.n * 29) % 150 + 6] = 255
            return img
        frame = screen
    tr = MenuTracker({"kind": "menu", "depth": 3})
    out = tr.explore(Endless())
    assert out.get("not_a_menu") and out["entries"] == []


def test_after_a_reload_the_writer_is_shown_only_places_seen_since():
    m = RunMemory()
    m.places = {"68": {"first_tick": 1, "entered": 3, "last_tick": 900}, "14593": {"first_tick": 1000, "entered": 1, "last_tick": 1010}}
    m.since = 1000
    gb = GoalBook(m, None)
    ids = [p["id"] for p in gb.context({"map": 14593, "x": 1, "y": 1, "screen": "walk"})["places"]]
    assert ids == [14593]
