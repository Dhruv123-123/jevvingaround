"""The long-horizon layer on a game it was not written for: a tiny tile world served as RAM-like state, played by the
world read (memory + navigator), auto rules for text, goals, and a decider that takes the top-ranked option."""
import os
import numpy as np
import pytest
from anygame.device.base import Device
from anygame.device.pyboy import decode, decode_all
from anygame.loop import Agent
from anygame.pack import load_pack, PackError
from anygame.perceive.world import WorldTracker
from anygame.sensors import open_sensor

ROOT = os.path.dirname(os.path.dirname(__file__))

# map 0: a room with a door at the top right; map 1: a room with a person (P) who says something when faced with A
MAPS = {
    0: ["#########D#",
        "#.........#",
        "#..###....#",
        "#.........#",
        "###########"],
    1: ["#######",
        "#.....#",
        "#..P..#",
        "#.....#",
        "###S###"],
}
DOOR = {(0, 9, 0): (1, 3, 3), (1, 3, 4): (0, 9, 1)}     # stepping onto D / S puts you here


class GridGame(Device):
    clock = "game"

    def __init__(self):
        self.map, self.x, self.y, self.facing = 0, 2, 3, "down"
        self.talking, self.talked, self.frames, self.presses = 0, False, 0, []

    def size(self):
        return (160, 144)

    def frame(self):
        return self.screen()

    def screen(self):
        return np.zeros((144, 160, 3), np.uint8)

    def state(self):
        return {"map": self.map, "x": self.x, "y": self.y, "talking": self.talking > 0, "talked": self.talked}

    def wait(self, frames):
        self.frames += frames

    def press(self, b, hold=8, after=8):
        self.presses.append(b)
        self.frames += hold + after
        if self.talking:
            if b == "a":
                self.talking -= 1
            return
        d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(b)
        if d:
            self.facing = b
            if hold < 4:
                return                       # a tap turns without walking
            nx, ny = self.x + d[0], self.y + d[1]
            c = MAPS[self.map][ny][nx]
            if (self.map, nx, ny) in DOOR:
                self.map, self.x, self.y = DOOR[(self.map, nx, ny)]
            elif c == ".":
                self.x, self.y = nx, ny
        elif b == "a":
            d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[self.facing]
            if MAPS[self.map][self.y + d[1]][self.x + d[0]] == "P":
                self.talking, self.talked = 3, True

    def key(self, name, hold_ms=0, **_):
        self.press(name)


PACK = """
game: gridworld
screen: { size: [160, 144] }
read:
  map: { kind: json, path: map }
  x: { kind: json, path: x }
  y: { kind: json, path: y }
  talking: { kind: json, path: talking }
  talked: { kind: json, path: talked }
  world: { kind: world, map: map, x: x, y: y, step_hold: 8, after: 8, max_steps: 6, learn_when: { read: talking, equals: false } }
auto:
  - { if: { read: talking, equals: true }, key: a }
act:
  - { id: go, kind: macro, options: world }
  - { id: wait, kind: wait }
tick_hz: 1000
play: walk around
questions:
  - { id: action, type: choice, instructions: which, criteria: { go: walk, wait: nothing } }
goals:
  - { id: next_room, instruction: "go through the door at the top right", done: { read: map, equals: 1 }, target: { map: 0, x: 9, y: 1, label: "the door" } }
  - { id: talk, instruction: "talk to the person", done: { read: talked, equals: true } }
tests:
  - { state: s.json, expect: { map: 0 } }
"""


def _pack(tmp_path):
    (tmp_path / "pack.yaml").write_text(PACK)
    (tmp_path / "s.json").write_text('{"map": 0, "x": 2, "y": 3}')
    return load_pack(tmp_path)


def test_ram_decoding_covers_the_types_a_game_boy_game_uses():
    mem = bytearray(0x10000)
    mem[0xD347:0xD34A] = bytes([0x01, 0x23, 0x45])       # money 12345 in BCD
    mem[0xD356] = 0b00000101                              # two badges
    mem[0xD16C:0xD16E] = bytes([0x01, 0x02])              # big-endian 258
    mem[0xD158:0xD15C] = bytes([0x91, 0x84, 0x83, 0x50])  # "RED" in Pokemon's charmap, then the terminator
    ram = {"money": {"addr": 0xD347, "type": "bcd", "len": 3}, "badges": {"addr": 0xD356, "type": "bits"},
           "hp": {"addr": 0xD16C, "type": "u16"}, "hp_le": {"addr": 0xD16C, "type": "u16le"}, "name": {"addr": "0xD158", "type": "text", "len": 11, "charmap": "pokemon"},
           "flag": {"addr": 0xD356, "type": "bit", "bit": 2}, "party": {"addr": 0xD16C, "type": "struct", "stride": 1, "count": 2, "fields": {"v": {"off": 0}}},
           "bad": {"addr": 0xD000, "type": "nope"}}
    s = decode_all(mem, ram)
    assert s["money"] == 12345 and s["badges"] == {"count": 2, "on": [0, 2]} and s["hp"] == 258 and s["hp_le"] == 513
    assert s["name"] == "RED" and s["flag"] is True and s["party"] == [{"v": 1}, {"v": 2}]
    assert s["bad"] is None and "bad" in s["_errors"]
    assert decode(mem, {"addr": 0xD356}) == 5


def test_world_tracker_learns_walls_and_doors_and_plans_around_them():
    w = WorldTracker({"x": "x", "y": "y", "map": "map", "max_steps": 4})
    a = (0, 1, 1)
    w.visit(a)
    assert w.learn(a, "right", (0, 2, 1)) == "moved"
    assert w.learn((0, 2, 1), "right", (0, 2, 1)) == "blocked" and w.is_blocked((0, 2, 1), "right")
    assert w.learn((0, 2, 1), "up", (5, 3, 3)) == "warp" and w.warps[(0, 2, 1, "up")] == (5, 3, 3)
    w.visit((0, 2, 2))
    tree = w.bfs((0, 1, 1))
    assert (0, 3, 1) not in tree            # behind the wall
    assert w.path_to(tree, (0, 2, 2)) in (["right", "down"], ["down", "right"])
    # a person seen once is forgotten after a while; a wall bumped three times is not
    w.steps += 1000
    assert not w.is_blocked((0, 2, 1), "right")
    for _ in range(3):
        w.learn((0, 2, 1), "right", (0, 2, 1))
    w.steps += 1000
    assert w.is_blocked((0, 2, 1), "right")
    # the door chain to another map
    opts, plans = w.options((0, 1, 1), {"map": 5, "label": "map five"})
    assert plans["goal"] == ["right", "up"] and "door" in opts["goal"]
    # memory survives a save and a load
    w2 = WorldTracker({"x": "x", "y": "y"})
    w2.load(w.dump())
    assert w2.warps == w.warps and w2.visited == w.visited and w2.is_blocked((0, 2, 1), "right")


def test_long_horizon_layer_reaches_goals_in_a_world_it_explores(tmp_path):
    pack = _pack(tmp_path)
    game = GridGame()
    agent = Agent(pack, game, open_sensor("top"), background=False)
    for _ in range(80):
        agent.step()
        if "talk" in agent.goals_done:
            break
    done = [g["id"] for g in agent.goal_log]
    assert done == ["next_room", "talk"], done
    for _ in range(4):
        agent.step()
    assert agent.auto_ticks == 3 and game.talking == 0  # the dialogue was paged through without the decider
    w = agent.worlds["world"]
    assert (0, 9, 1, "up") in w.warps                   # the door it learned
    assert w.blocked                                    # and some walls


def test_pack_refuses_bad_goals_and_auto(tmp_path):
    (tmp_path / "s.json").write_text("{}")
    (tmp_path / "pack.yaml").write_text(PACK.replace("key: a }", "}"))
    with pytest.raises(PackError, match="auto needs"):
        load_pack(tmp_path)
    (tmp_path / "pack.yaml").write_text(PACK.replace('done: { read: talked, equals: true }', 'done: { read: talked }'))
    with pytest.raises(PackError, match="goal 'talk'"):
        load_pack(tmp_path)


def test_pyboy_device_reads_ram_saves_and_restores_state(tmp_path):
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    d = open_device("pyboy://" + os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60&clock=game&step=2", None)
    try:
        d.use_pack({"ram": {"b": {"addr": 0xC000, "type": "bytes", "len": 4}}})
        f0 = d.frames
        d.frame()
        assert d.frames == f0 + 2                       # the game clock: a frame() runs `step` frames, no more
        d.press("start", hold=4, after=10)
        assert d.frames == f0 + 16
        s = d.state()
        assert len(s["b"]) == 4 and s["frames"] == d.frames
        d.save_state(str(tmp_path / "a.state"))
        before = d.screen().copy()
        for k in ("left", "up", "right", "down") * 3:
            d.press(k)
        d.load_state(str(tmp_path / "a.state"))
        assert d.frames == f0 + 16 + 1
        assert np.abs(d.screen().astype(int) - before.astype(int)).mean() < 1.0
    finally:
        d.close()


def test_pyboy_device_takes_the_found_file_of_a_save_named_in_the_url(tmp_path):
    # the save in the URL is loaded before the pack turns discovery on: its .found must still be read (a run started
    # from a mid-game save rediscovered everything from nothing, and its first doors went to sprite bytes)
    pytest.importorskip("pyboy")
    import json
    from anygame.device import open_device
    rom = os.path.join(ROOT, "roms", "2048gb", "2048.gb")
    d = open_device("pyboy://" + rom + "?boot=60&clock=game&step=2", None)
    try:
        d.save_state(str(tmp_path / "a.state"))
    finally:
        d.close()
    (tmp_path / "a.state.found").write_text(json.dumps({"x": {"addr": 0xD362, "type": "u8", "score": 1.0},
                                                         "y": {"addr": 0xD361, "type": "u8", "score": 1.0}, "cell": 1}))
    d = open_device("pyboy://" + rom + f"?clock=game&step=2&state={tmp_path / 'a.state'}", None)
    try:
        d.use_pack({"discover": True}, str(tmp_path))
        assert d.discoverer.found["x"]["addr"] == 0xD362 and d.discoverer.found["y"]["addr"] == 0xD361
    finally:
        d.close()


def test_pyboy_device_shows_discovery_a_fade_between_drawn_frames():
    # stairs in Red's house fade out and in between the frames a press draws: the dark frame is passed on as blank
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    d = open_device("pyboy://" + os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60&clock=game&step=2", None)
    try:
        seen = []

        class Disc:
            trace = None
            found: dict = {}

            def frame(self, mem, blank):
                seen.append(bool(blank))

            def press(self, *a, **k):
                pass

        d.discoverer = Disc()
        calls = iter(range(1000))
        d._dark = lambda: next(calls) in (3, 4, 5)          # dark for three frames inside the press
        d.press("left", hold=6, after=16)
        # the two drawn frames (end of the hold, end of the press) and before them the dark one, as blank
        assert 2 < len(seen) < 6 and seen[0] is True        # once per run of frames, not once per dark frame
    finally:
        d.close()


def test_discoverer_finds_position_and_map_from_ram_alone():
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(0)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y, MAP, TIMER = 0xD362 - LO, 0xD361 - LO, 0xD35E - LO, 0xC0F0 - LO
    mem[X], mem[Y], mem[MAP] = 10, 10, 3
    for k in range(60):
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        mem[TIMER] = (mem[TIMER] + 7) % 256                        # noise that moves on every press
        blocked = rng.random() < 0.3                                # a wall
        if not blocked:
            mem[X] += {"left": -1, "right": 1}.get(b, 0)
            mem[Y] += {"up": -1, "down": 1}.get(b, 0)
        d.press(b, before, mem.copy())
        d.frame(mem.copy(), blank=False)
    assert d.found["x"]["addr"] == 0xD362 and d.found["y"]["addr"] == 0xD361      # u8 or a pair with a zero high byte: the same value
    # a door: a step that lands elsewhere, with the map byte and the new map's tiles changed
    d.frame(mem.copy(), blank=False)
    before = mem.copy()
    mem[MAP], mem[X], mem[Y] = 7, 3, 4
    mem[0xC400 - LO: 0xC600 - LO] = rng.integers(0, 256, 512)    # the new map's tiles and sprites loaded
    d.press("up", before, mem.copy())
    for _ in range(20):
        d.frame(mem.copy(), blank=False)
    for b in ["right"] * 8:                                         # the new map holds while the player walks on
        before = mem.copy()
        mem[X] += 1
        d.press(b, before, mem.copy())
        d.frame(mem.copy(), blank=False)
    assert 0xC0F0 not in d.found["map"]["addrs"]                    # the timer moves on every press: never the map
    assert d.found["map"]["addrs"]
    st = d.state(mem)
    assert st["x"] == 11 and st["y"] == 4 and st["map"] is not None


def test_discoverer_drops_a_copy_that_stops_following_and_keeps_the_map_steady():
    """A sprite copy of the position follows the d-pad in the first room and freezes after a door (Aevilia's
    tutorial entity at 0xC212): the real position, which follows in every room, must win. A byte that changes on
    some doors and also between frames (a timer reset by a fade) is not the map."""
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(1)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y, CX, CY, MAP, TICK = 0xD712 - LO, 0xD710 - LO, 0xC212 - LO, 0xC210 - LO, 0xC3C4 - LO, 0xC100 - LO
    mem[X], mem[Y], mem[MAP] = 40, 40, 2

    def walk(n, copy_follows):
        for _ in range(n):
            b = ["up", "down", "left", "right"][rng.integers(4)]
            before = mem.copy()
            if rng.random() > 0.25:
                dx, dy = {"left": -1, "right": 1}.get(b, 0), {"up": -1, "down": 1}.get(b, 0)
                mem[X] += dx
                mem[Y] += dy
                if copy_follows:
                    mem[CX] = mem[X] + 1        # a copy that scores the same while it follows: listed first
                    mem[CY] = mem[Y] + 1
            d.press(b, before, mem.copy())
            mem[TICK] = (mem[TICK] + 1) % 256
            d.frame(mem.copy(), blank=False)

    def door(new_map):
        before = mem.copy()                          # the step through the door: the player lands elsewhere
        mem[MAP], mem[X], mem[Y], mem[TICK] = new_map, 20, 20, 0
        mem[0xC400 - LO: 0xC600 - LO] = np.random.default_rng(new_map).integers(0, 256, 512)   # the map's tiles, the same each time
        d.press("up", before, mem.copy())
        d.frame(mem.copy(), blank=True)
        d.frame(mem.copy(), blank=False)

    walk(60, copy_follows=True)
    sigs = {}
    for m in (5, 4, 0, 4, 5):
        door(m)
        walk(40, copy_follows=False)
        seen = set()
        for _ in range(10):                          # steady within a visit, whatever the timer does
            walk(2, copy_follows=False)
            seen.add(d.state(mem)["map"])
        assert len(seen) == 1
        sigs.setdefault(m, []).append(mem.copy())
    assert d.found["x"]["addr"] == 0xD712 and d.found["y"]["addr"] == 0xD710
    assert 0xC100 not in d.found["map"]["addrs"]
    sigs = {m: {d.state(x)["map"] for x in v} for m, v in sigs.items()}   # with what was learned by the end
    assert all(len(v) == 1 for v in sigs.values())                # coming back to a map gives its signature back
    assert len({next(iter(v)) for v in sigs.values()}) == 3     # three maps, three signatures


class BranchingGridGame(GridGame):
    """GridGame with save states: what the probe needs."""

    def snapshot(self):
        return (self.map, self.x, self.y, self.facing, self.talking, self.talked, self.frames)

    def restore(self, s):
        self.map, self.x, self.y, self.facing, self.talking, self.talked, self.frames = s

    def screen(self):
        img = np.zeros((144, 160, 3), np.uint8)
        img[self.y * 10:(self.y + 1) * 10, self.x * 10:(self.x + 1) * 10] = 255 if self.talking == 0 else 0
        if self.talking:
            img[120:, :] = 40 * self.talking                         # a text box that changes as it is paged
        return img

    def branch(self, seqs, frames=16, hold=4):
        snap, out = self.snapshot(), {}
        for label, keys in seqs.items():
            self.restore(snap)
            for k in keys:
                k, _, h = str(k).partition(":")
                self.press(k, hold=int(h) if h else 8, after=0)
            out[label] = {"screen": self.screen(), "state": self.state(), "ram": None}
        self.restore(snap)
        return out


def test_probe_tells_walking_text_and_nothing_apart_by_branching(tmp_path):
    pack = _pack(tmp_path)
    game = BranchingGridGame()
    agent = Agent(pack, game, None, background=False)
    probe = {"kind": "probe", "pos": ["x", "y"]}
    assert agent._probe(probe) == "walk"
    before = game.snapshot()
    game.talking = 2
    assert agent._probe(probe) == "text"                           # only A changes anything
    assert game.talking == 2 and game.snapshot()[:3] == before[:3]  # and the game is put back as it was


def test_graders_read_milestones_the_agent_never_sees():
    from anygame.graders import for_title
    from anygame.graders import pokemon_red as pr
    g = for_title("POKEMON RED")
    mem = bytearray(0x10000)
    g.update(mem)
    assert g.report()["reached"] == []                              # zeroed RAM before New Game is not Pallet Town
    mem[pr.W_PLAYER_NAME: pr.W_PLAYER_NAME + 6] = bytes(pr.NINTEN)  # the title demo's placeholder names, and
    mem[pr.W_RIVAL_NAME: pr.W_RIVAL_NAME + 4] = bytes(pr.SONY)      # New Game sets Red's room before Oak's speech
    mem[pr.W_CUR_MAP] = 0x26
    assert g.update(mem) == []
    mem[pr.W_PLAYER_NAME] = 0x91                                    # "R..." and a rival named: the game has started
    mem[pr.W_RIVAL_NAME] = 0x81
    assert g.update(mem) == ["intro_done"]
    mem[pr.W_CUR_MAP], mem[pr.W_PARTY_COUNT] = 0x0C, 1
    assert g.update(mem) == ["starter", "route_1"]
    mem[pr.W_OBTAINED_BADGES] = 0x01
    assert "badge_1" in g.update(mem) and 0 < g.progress() < 1
    a = for_title("AEVILIA")
    m2 = bytearray(0x10000)
    m2[0xC3C4] = 2
    assert a.update(m2) == ["tutorial"]


def test_discoverer_drops_a_map_signature_from_the_older_rule():
    """A checkpoint from before door steps carries a signature of screen tiles (no "doors"): it is dropped, not
    kept or compared against the new one."""
    from anygame.discover import Discoverer, LO, N
    d = Discoverer()
    d.load({"x": {"addr": 0xD362, "type": "u8"}, "y": {"addr": 0xD361, "type": "u8"}, "cell": 1,
            "map": {"addrs": [0xC5AC, 0xC5AD, 0xC5C4, 0xC5C5], "transitions": 109}})
    mem = np.zeros(N, np.int32)
    for _ in range(10):
        before = mem.copy()
        mem[0xD362 - LO] += 1
        d.press("right", before, mem.copy())
        d.frame(mem.copy(), blank=False)
    assert d.found["map"]["addrs"] == [] and d.state(mem)["map"] == 0


def test_discoverer_credits_a_tap_with_the_step_it_started():
    """Pokemon walks one tile on a tap but writes the position after the press is over, while a facing byte (-1, 0,
    1) changes during it: a press that the game goes on from is judged by the RAM when the next one comes."""
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(3)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y, FX, FY = 0xD362 - LO, 0xD361 - LO, 0xC105 - LO, 0xC103 - LO
    mem[X], mem[Y] = 20, 20
    late = (0, 0)
    for _ in range(120):
        mem[X] += late[0]                       # the last tap's step lands now, before the next press
        mem[Y] += late[1]
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        dx, dy = {"left": -1, "right": 1}.get(b, 0), {"up": -1, "down": 1}.get(b, 0)
        mem[FX], mem[FY] = dx % 256, dy % 256    # the facing byte follows at once
        late = (dx, dy) if rng.random() > 0.2 else (0, 0)
        d.press(b, before, mem.copy(), full=False, continues=True)
        d.frame(mem.copy(), blank=False)
    assert d.found["x"]["addr"] == 0xD362 and d.found["y"]["addr"] == 0xD361


def test_discoverer_takes_the_map_id_from_warps_and_returns():
    """Two outdoor maps joined by a seamless edge (y jumps 0 -> 35, no door) and a house: the game writes the map
    id as the player steps onto the door and the new position only a press later; a 'last map' byte changes on
    doors but not at the edge, and a landing spot's bytes take a new value on every warp. Only the id tells each
    place apart and gives the same value on every visit."""
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(5)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y, ID, LAST, LAND = 0xD362 - LO, 0xD361 - LO, 0xD35E - LO, 0xD73C - LO, 0xC110 - LO
    mem[X], mem[Y], mem[ID] = 8, 8, 0
    places = {0: (2, 0, 14, 12), 12: (2, 20, 14, 35), 37: (1, 1, 7, 7)}
    late: list = []                              # writes the game makes after the press is over
    land = [0]
    seen: dict = {}

    def warp(to, pos, door):
        late.append((ID, to)) if not door else None
        if door:
            mem[LAST] = mem[ID]
            mem[ID] = to                         # written as the player steps onto the door
        land[0] += 1
        late.extend([(X, pos[0]), (Y, pos[1]), (LAND, land[0] % 256)])

    for _ in range(900):
        for a, v in late:
            mem[a] = v
        late.clear()
        place = int(mem[ID])
        if "x" in d.found and "y" in d.found and d.found.get("map", {}).get("addrs"):
            seen.setdefault(place, set()).add(d.state(mem)["map"])
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        x, y = int(mem[X]), int(mem[Y])
        dx, dy = {"left": -1, "right": 1}.get(b, 0), {"up": -1, "down": 1}.get(b, 0)
        x0, y0, x1, y1 = places[place]
        if place == 0 and b == "up" and y == 0 and x in (9, 10):
            warp(12, (x, 35), door=False)         # the seamless edge to the route
        elif place == 12 and b == "down" and y == 35 and x in (9, 10):
            warp(0, (x, 0), door=False)
        elif place == 0 and b == "up" and (x, y) == (5, 6):
            mem[Y] = 5
            warp(37, (3, 7), door=True)
        elif place == 37 and b == "down" and (x, y) == (3, 7):
            warp(0, (5, 6), door=True)
        elif x0 <= x + dx <= x1 and y0 <= y + dy <= y1:
            late.extend([(X, x + dx), (Y, y + dy)])
        # steer toward the exits now and then so every place is visited many times
        d.press(b, before, mem.copy(), full=True, continues=True)
        d.frame(mem.copy(), blank=False)
        if rng.random() < 0.3:
            target = {0: [(10, 0), (5, 6)][rng.integers(2)], 12: (10, 35), 37: (3, 7)}[place]
            mem[X], mem[Y] = target
    assert d.found["map"]["addrs"] == [0xD35E]
    assert all(len(v) == 1 for v in seen.values() if v) and len(set().union(*seen.values())) == len(seen)


def test_discoverer_leaves_out_a_byte_that_records_where_the_player_came_from():
    """A house (0) with a hall (37) and a room behind it (38), doors only: the map id and a 'last map' byte both change
    on every door and come back together on the first trip in and out, and the 'last map' byte sits higher, so it
    led. But through each door it takes the value the id had before (and splits the hall by the side it was entered
    from): once the trips go on through the hall, it is left out."""
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(3)
    d = Discoverer()
    d.found.update({"x": {"addr": 0xD362, "type": "u8"}, "y": {"addr": 0xD361, "type": "u8"}, "cell": 1})
    mem = np.zeros(N, np.int32)
    X, Y, ID, LAST, TILES = 0xD362 - LO, 0xD361 - LO, 0xD35E - LO, 0xD73C - LO, 0xC3A0 - LO
    mem[X], mem[Y], mem[LAST] = 5, 5, 37                          # came in from the hall
    route = [(37, (2, 27)), (0, (5, 6)), (37, (2, 27)), (38, (6, 47)), (37, (6, 26)), (0, (5, 6))]  # in, out, in, on
    seen: dict = {}

    def walk(n, lap):
        for _ in range(n):
            b = ["left", "right"][int(rng.integers(2))]
            before = mem.copy()
            mem[X] = min(9, max(1, int(mem[X]) + (1 if b == "right" else -1)))
            mem[TILES: TILES + 40] = rng.integers(0, 256, 40)        # the screen's tiles scroll with every step
            d.press(b, before, mem.copy(), full=True, continues=True)
            d.frame(mem.copy(), blank=False)
            if d.found.get("map", {}).get("addrs") and lap >= 8:
                seen.setdefault(int(mem[ID]), set()).add(d.state(mem)["map"])

    for lap in range(12):
        for to, pos in route:
            walk(int(rng.integers(20, 30)), lap)
            before = mem.copy()
            mem[LAST], mem[ID] = mem[ID], to
            mem[X], mem[Y] = pos
            d.press("up", before, mem.copy(), full=True, continues=True)
            d.frame(mem.copy(), blank=False)
    walk(30, 12)
    assert d.found["map"]["addrs"] == [0xD35E]
    assert all(len(v) == 1 for v in seen.values()) and len(seen) == 3

def test_discoverer_keeps_y_through_a_menu_whose_cursor_follows_the_pad():
    """A menu with a cursor on both axes (a battle's grid of choices, a job grid): the d-pad moves the cursor's bytes
    on every press while the position never moves, and the battle's flashes start new visits until the walking ones
    are forgotten. The position found while walking stays; without the guard the cursor takes x and y."""
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(4)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y, CUR, CURX = 0xD362 - LO, 0xD361 - LO, 0xCC2A - LO, 0xCC2B - LO
    mem[X], mem[Y] = 20, 20
    for _ in range(300):
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        nx, ny = mem[X] + {"left": -1, "right": 1}.get(b, 0), mem[Y] + {"up": -1, "down": 1}.get(b, 0)
        if 16 <= nx <= 24 and 18 <= ny <= 22:                            # a room: some presses hit a wall
            mem[X], mem[Y] = nx, ny
        mem[0xC300 - LO: 0xC340 - LO] = rng.integers(0, 256, 64)         # a step redraws part of the screen
        d.press(b, before, mem.copy(), full=True, continues=True)
        d.frame(mem.copy(), blank=False)
    assert d.found["y"]["addr"] == 0xD361 and d.found["x"]["addr"] == 0xD362
    for t in range(400):
        if t % 80 == 79:                                                 # a flash: a burst of changes, a new visit
            mem[0xC400 - LO: 0xCC00 - LO] = rng.integers(0, 256, 0x800)
            for _ in range(4):
                d.frame(mem.copy(), blank=False)
            mem[0xC400 - LO: 0xCC00 - LO] = 0
            for _ in range(4):
                d.frame(mem.copy(), blank=False)
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        mem[CUR] = (mem[CUR] + {"up": -1, "down": 1}.get(b, 0)) % 256
        mem[CURX] = (mem[CURX] + {"left": -1, "right": 1}.get(b, 0)) % 256
        mem[0xC300 - LO: 0xC340 - LO] = rng.integers(0, 256, 64)         # the battle animates
        d.press(b, before, mem.copy(), full=True, continues=True)
        d.frame(mem.copy(), blank=False)
    assert d.found["y"]["addr"] == 0xD361 and d.found["x"]["addr"] == 0xD362


def test_pyboy_snapshot_is_reused_until_the_game_moves():
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    d = open_device("pyboy://" + os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60&clock=game&step=2", None)
    try:
        a = d.snapshot()
        assert d.snapshot() is a                        # nothing ran: the same state, not saved again
        r1 = d.branch({k: [k] for k in ("left", "up", "right")}, frames=20)
        assert d.snapshot() is a                        # a branch puts the game back where it was
        r2 = d.branch({k: [k] for k in ("left", "up", "right")}, frames=20)
        assert all((r1[k]["ram"] == r2[k]["ram"]).all() for k in r1)
        d.press("left")
        b = d.snapshot()
        assert b is not a and b[0] != a[0]
        d.restore(a)
        assert d.snapshot() is a and d.frames == a[1]
    finally:
        d.close()


def test_pyboy_save_state_carries_what_discovery_found(tmp_path):
    """A save that opens on a battle has no walking to discover from: loading it brings back the position bytes
    known when it was saved, unless this run already knows its own."""
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    rom = os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60&clock=game&step=2"
    found = {"x": {"addr": 0xD362, "type": "u8", "score": 1.0}, "y": {"addr": 0xD361, "type": "u8", "score": 1.0}, "cell": 1}
    a = open_device("pyboy://" + rom, None)
    b = open_device("pyboy://" + rom, None)
    try:
        a.use_pack({"discover": True}, None)
        a.discoverer.found.update(found)
        a.save_state(str(tmp_path / "s.state"))
        b.use_pack({"discover": True}, None)
        b.load_state(str(tmp_path / "s.state"))
        assert b.discoverer.found["x"]["addr"] == 0xD362 and b.discoverer.found["y"]["addr"] == 0xD361
    finally:
        a.close()
        b.close()


def test_discovery_trace_is_appended_and_survives_a_killed_run(tmp_path):
    from anygame.discover import append_trace, load_trace
    p = str(tmp_path / "t.bin")
    tr = [("f", False, b"a")]
    done = append_trace(p, tr, 0)
    tr += [("p", "up", b"b", b"c", True, True)]
    done = append_trace(p, tr, done)
    assert load_trace(p) == tr
    with open(p, "ab") as f:
        f.write(b"\x40\x00\x00\x00partial")       # a chunk the run was killed while writing
    assert load_trace(p) == tr
    assert append_trace(p, tr[:1], done) == 1 and load_trace(p) == tr[:1]   # a shorter trace: written whole


def test_pyboy_holds_several_buttons_together():
    pytest.importorskip("pyboy")
    from anygame.device import open_device
    d = open_device("pyboy://" + os.path.join(ROOT, "roms", "2048gb", "2048.gb") + "?boot=60&clock=game&step=2", None)
    try:
        f0 = d.frames
        a = d.snapshot()
        d.hold_keys(["a", "right"], 6)
        d.hold_keys(["a", "right"], 4)                  # still down: held 10 frames in all
        d.release_keys(["a", "right"])
        assert d.frames == f0 + 10 and d.snapshot() is not a
    finally:
        d.close()


def test_discoverer_evidence_survives_a_checkpoint():
    """A run resumed from a checkpoint goes on from the evidence the map was judged from, not from nothing."""
    import json
    from anygame.discover import Discoverer, LO, N
    rng = np.random.default_rng(1)
    d = Discoverer()
    mem = np.zeros(N, np.int32)
    X, Y = 0xD712 - LO, 0xD710 - LO
    mem[X], mem[Y] = 40, 40
    for _ in range(80):
        b = ["up", "down", "left", "right"][rng.integers(4)]
        before = mem.copy()
        mem[X] += {"left": -1, "right": 1}.get(b, 0)
        mem[Y] += {"up": -1, "down": 1}.get(b, 0)
        d.press(b, before, mem.copy())
        d.frame(mem.copy(), blank=False)
    saved = json.loads(json.dumps(d.dump()))
    e = Discoverer()
    e.load(saved)
    assert (e.by_pad == d.by_pad).all() and (e._seen == d._seen).all() and e.pad_presses == d.pad_presses
    assert "evidence" not in d.dump(evidence=False)


def test_discoverer_drops_an_old_rule_signature_but_keeps_the_position():
    """A checkpoint saved under an older map rule: its signature is judged again, the position resumes as it was."""
    from anygame.discover import Discoverer, MAP_RULE
    d = Discoverer()
    d.load({"x": {"addr": 0xD362, "type": "u8", "score": 1.0}, "y": {"addr": 0xD361, "type": "u8", "score": 1.0},
            "map": {"addrs": [0xC750, 0xC751], "doors": 23, "transitions": 4, "rule": MAP_RULE - 1}, "cell": 1})
    assert "map" not in d.found
    assert d.found["x"]["addr"] == 0xD362 and d.found["y"]["addr"] == 0xD361


def test_discoverer_keeps_place_names_when_the_signature_changes_hands():
    """A place named under one signature keeps its name when another signature takes over and tells the same places
    apart; a name an early signature gave two maps alike does not carry over."""
    from anygame.discover import Discoverer, LO, N
    d = Discoverer()
    d.found.update({"x": {"addr": 0xD362, "type": "u8"}, "y": {"addr": 0xD361, "type": "u8"}})
    A, B, J = 0xC750, 0xD35E, 0xC110               # A: a sprite table loaded with each map; B: the map's id; J: junk

    def at(place, junk):
        mem = np.zeros(N, np.int32)
        mem[A - LO], mem[B - LO], mem[J - LO] = 10 + place, place, junk
        return mem
    d.found["map"] = {"addrs": [A]}
    names = {}
    for place in (0, 1, 2, 0, 1):
        for _ in range(12):
            names.setdefault(place, set()).add(d.state(at(place, 0))["map"])
    assert all(len(v) == 1 for v in names.values()) and len(set().union(*names.values())) == 3
    d.found["map"] = {"addrs": [B]}
    for place in (2, 1, 0):
        assert d.state(at(place, 0))["map"] in names[place]
    # junk named maps 0 and 1 alike: under the id they part, so that name goes to neither
    d.found["map"] = {"addrs": [J]}
    for place in (0, 1):
        for _ in range(12):
            joint = d.state(at(place, 7))["map"]
    d.found["map"] = {"addrs": [B]}
    assert d.state(at(1, 7))["map"] != joint and d.state(at(0, 7))["map"] != joint
