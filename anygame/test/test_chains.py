"""Chains: a menu chain toward a named outcome found by playing chains out, on a tiny scripted game standing in for an
emulator; and walls tried again after a gain."""
import numpy as np
from anygame.chains import Gains, gains, moves, reopen, replay, says, search
from anygame.perceive.world import WorldTracker

MENUS = {"main": ["ITEM", "PARTY"], "items": ["POTION"], "party": ["CUT", "STATS"]}


class Game:
    """A world with a tree east of the player. START opens a menu; PARTY > CUT says so and the tree is gone; ITEM >
    POTION says the player got it. B backs out of a menu; text boxes page with A."""

    def __init__(self):
        self.s = {"mode": "world", "stack": [], "cur": 0, "pages": [], "x": 0, "y": 0, "tree": True, "bag": 0}
        self.frames = 0
        self.discoverer = None

    # -- the device API used by play-outs and the search
    def snapshot(self):
        return ({**self.s, "stack": list(self.s["stack"]), "pages": list(self.s["pages"])}, self.frames)

    def restore(self, snap):
        s, f = snap
        self.s = {**s, "stack": list(s["stack"]), "pages": list(s["pages"])}
        self.frames = f

    def wait(self, n):
        self.frames += n

    def screen(self):
        s = self.s
        img = np.zeros((144, 160, 3), np.uint8)
        img[0:24] = {"world": 0, "menu": 80, "text": 160}[s["mode"]]
        img[24:48] = 30 * len(s["stack"]) + (5 * len(s["stack"][-1]) if s["stack"] else 0)
        img[48:72] = 40 * s["cur"]
        img[72:96] = 20 * len(s["pages"])
        img[96:120] = 20 * s["x"] + 7 * s["y"]
        img[120:144] = 100 if s["tree"] else 0
        return img

    def text(self):
        s = self.s
        if s["mode"] == "text":
            return s["pages"][0]
        if s["mode"] == "menu":
            return " ".join(MENUS[s["stack"][-1]])
        return ""

    def _say(self, *pages):
        self.s["mode"], self.s["pages"] = "text", list(pages)

    def press(self, k, hold=4, after=10):
        self.frames += hold + after
        s = self.s
        if s["mode"] == "world":
            if k == "start":
                s["mode"], s["stack"], s["cur"] = "menu", ["main"], 0
            elif k == "right" and not (s["tree"] and s["x"] == 0):
                s["x"] += 1
            elif k == "left" and s["x"] > 0:
                s["x"] -= 1
            elif k in ("up", "down"):
                s["y"] += 1 if k == "down" else -1
        elif s["mode"] == "menu":
            items = MENUS[s["stack"][-1]]
            if k == "down":
                s["cur"] = min(s["cur"] + 1, len(items) - 1)
            elif k == "up":
                s["cur"] = max(s["cur"] - 1, 0)
            elif k == "b":
                s["stack"].pop()
                s["cur"] = 0
                if not s["stack"]:
                    s["mode"] = "world"
            elif k == "a":
                pick = items[s["cur"]]
                if pick == "ITEM":
                    s["stack"].append("items"); s["cur"] = 0  # noqa: E702
                elif pick == "PARTY":
                    s["stack"].append("party"); s["cur"] = 0  # noqa: E702
                elif pick == "POTION":
                    s["bag"] += 1
                    s["stack"] = []
                    self._say("Got a POTION!")
                elif pick == "CUT":
                    s["tree"] = False
                    s["stack"] = []
                    self._say("BULBA used CUT!", "The tree was cut down.")
                elif pick == "STATS":
                    self._say("HP 20/20")
        elif s["mode"] == "text" and k == "a":
            s["pages"].pop(0)
            if not s["pages"]:
                s["mode"] = "menu" if s["stack"] else "world"

    def branch(self, seqs, frames=16, hold=4):
        snap = self.snapshot()
        out = {}
        for lab, keys in seqs.items():
            self.restore(snap)
            for k in keys:
                self.press(k, hold=hold)
            self.wait(frames)
            out[lab] = {"screen": self.screen()}
        self.restore(snap)
        return out


def _read(g):
    return lambda img: g.text()


def test_search_finds_the_menu_chain_that_opens_a_wall_and_puts_the_game_back():
    g = Game()
    pos = lambda: (0, g.s["x"], g.s["y"])  # noqa: E731
    r = search(g, _read(g), moves(pos, "right"))
    assert r["found"]
    assert [s["keys"] for s in r["steps"]] == [["start"], ["down", "a"], ["a"]]       # START, PARTY, CUT
    assert any("CUT" in t for t in r["lines"])
    assert g.s["tree"] and g.s["mode"] == "world" and g.frames == 0                     # put back exactly
    replay(g, r["trace"])
    assert not g.s["tree"]


def test_search_finds_a_named_gain():
    g = Game()
    r = search(g, _read(g), says("POTION"))
    # START, then ITEM: a list of one entry where no direction moves a cursor is paged on with A like a text box
    assert r["found"] and [s["keys"] for s in r["steps"]] == [["start"], ["a"]]
    assert g.s["bag"] == 0
    replay(g, r["trace"])
    assert g.s["bag"] == 1


def test_search_gives_up_within_its_budget():
    g = Game()
    r = search(g, _read(g), says("MASTER BALL"), max_tries=12)
    assert not r["found"] and r["tries"] <= 12 and g.frames == 0


def test_a_gain_reopens_the_walls_given_up_on():
    w = WorldTracker({"forget_after": 150})
    here = (1, 4, 4)
    for _ in range(3):
        w.learn(here, "right", here)
    assert w.is_blocked(here, "right")
    gs = Gains(w)
    assert gs.see("BULBA used CUT!") == []
    assert gs.see("Received HM01 CUT!") == ["Received HM01 CUT!"]
    assert gs.see("Received HM01 CUT!") == []           # once while it stays on screen
    assert not w.is_blocked(here, "right") and gs.reopened == 1
    w.learn(here, "right", here)                          # still a wall: given up on again
    assert w.is_blocked(here, "right")
    assert gains(["Withdrew POTION.", "POTION x1"], "potion") == ["Withdrew POTION."]
    assert reopen(w) == 1
