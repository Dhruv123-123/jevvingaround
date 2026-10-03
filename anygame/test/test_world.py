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
