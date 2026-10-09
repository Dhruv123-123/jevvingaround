"""The screen-only agent on a toy game: a player sprite walking a walled room, seen only as frames."""
import numpy as np

from anygame.screen_agent import ScreenAgent, Nodes, parse_presses


class GridGame:
    """A 10x8 room of 16-px cells drawn on a 160x144 screen, walls round the edge; the d-pad moves a sprite one cell,
    other buttons do nothing. frame() returns BGR like a real device."""

    def __init__(self):
        self.x, self.y = 2, 2
        self.visited = set()
        rng = np.random.default_rng(3)
        self.spr = (rng.integers(0, 2, size=(16, 16)) * 200 + 30).astype(np.uint8)
        self.frames = 0

    def frame(self):
        img = np.full((144, 160, 3), 120, np.uint8)
        img[::2, ::2] = 140                                      # a fine texture on the floor
        img[:16], img[-16:], img[:, :16], img[:, -16:] = 20, 20, 20, 20
        img[self.y * 16:(self.y + 1) * 16, self.x * 16:(self.x + 1) * 16] = self.spr[:, :, None]
        self.frames += 4
        return img[:, :, ::-1].copy()

    def press(self, b, hold=None, after=None):
        d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(b)
        if d:
            nx, ny = self.x + d[0], self.y + d[1]
            if 1 <= nx <= 8 and 1 <= ny <= 7:
                self.x, self.y = nx, ny
        self.visited.add((self.x, self.y))
        self.frames += 22


def test_nodes_match_with_tolerance():
    g = GridGame()
    nodes = Nodes()
    a = g.frame()[:, :, ::-1]
    g.press("right")
    b = g.frame()[:, :, ::-1]
    assert nodes(a) == nodes(a.copy())
    assert nodes(a) == nodes(b)              # a sprite one cell over: the same screen
    c = a.copy()
    c[40:100, 30:130] = 255                  # a box over a third of the screen: a new one
    assert nodes(c) != nodes(a)


def test_the_agent_covers_the_room_better_than_chance():
    g = GridGame()
    agent = ScreenAgent(g, seed=1)
    for _ in range(400):
        agent.step()
    assert len(g.visited) >= 54               # of 56 cells; random presses reach 47-52 in this many


def test_parse_presses():
    assert parse_presses('ok {"why": "go", "presses": ["Right", "jump", "a"]}', ["right", "a"]) == (["right", "a"], "go")
    assert parse_presses("no json", ["a"]) == ([], "")
