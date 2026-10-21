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
    assert parse_presses('{"presses": ["up*3", "a*x", "b"]}', ["up", "a", "b"])[0] == ["up", "up", "up", "a", "b"]
    assert parse_presses("no json", ["a"]) == ([], "")


class MenuFight:
    """A fight seen only as screens: a two-entry move menu (the first entry has no uses left: choosing it says so and
    shows the menu again), and a bag that B closes. Every screen is a different flat pattern."""

    def __init__(self):
        self.at, self.won, self.in_bag = "menu0", False, 0

    def frame(self):
        img = np.zeros((144, 160, 3), np.uint8)
        k = ["menu0", "menu1", "nopp", "bag", "won"].index(self.at)
        img[:, :] = 30 + 40 * k
        img[16 * k:16 * k + 40, 20:140] = 250 - 30 * k
        return img

    def press(self, b, hold=None, after=None):
        self.in_bag += self.at == "bag"
        self.at = {("menu0", "a"): "nopp", ("menu0", "down"): "menu1", ("menu0", "right"): "bag",
                   ("menu1", "a"): "won", ("menu1", "up"): "menu0", ("menu1", "right"): "bag",
                   ("nopp", "a"): "menu0", ("nopp", "b"): "menu0", ("bag", "b"): "menu0"}.get((self.at, b), self.at)
        self.won = self.won or self.at == "won"


class MenuBook:
    """A fight book that was only ever shown the move menu, choosing the first entry."""

    def __init__(self, game):
        self.g = game

    def act(self, img, box=True):
        return ({"menu0": "a", "menu1": "up"}.get(self.g.at),)


def test_a_fight_menu_that_goes_nowhere_gets_another_press():
    g = MenuFight()
    agent = ScreenAgent(g, seed=1, place_weight=0)
    agent.fight_book = MenuBook(g)
    for _ in range(60):
        agent.step()
        if g.won:
            break
    assert g.won


def test_an_unknown_fight_screen_gets_a_then_b():
    g = MenuFight()
    agent = ScreenAgent(g, seed=2, place_weight=0)
    agent.fight_book = MenuBook(g)
    g.at = "menu1"
    agent.step()                             # the book knows this one
    g.at = "bag"                             # wandered into the bag: A on the item there says no and shows it again
    assert [agent.step()["action"] for _ in range(3)] == ["a", "a", "b"]
    assert g.at == "menu0"
