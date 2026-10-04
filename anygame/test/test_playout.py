"""Play-outs: a choice played until the game asks again, on a tiny scripted game standing in for an emulator."""
import numpy as np
from anygame.playout import play_out, describe, new_lines, numbers


class Game:
    """A battle menu: A on the menu starts a message of two pages; each page waits for A; then the menu again, where
    'down' moves a cursor. The screen is a picture of (page, cursor); text is read from the state, not pixels."""
    PAGES = ["SQUIRTLE used TACKLE!", "Enemy HP 19/19 -> 15/19"]

    def __init__(self):
        self.page, self.cursor, self.frames, self.typed = None, 0, 0, 0
        self.discoverer = None

    def screen(self):
        img = np.zeros((144, 160, 3), np.uint8)
        img[:72, :] = (40 * (1 + (self.page if self.page is not None else 4)) + min(self.typed, 3) * 10) % 250
        img[72:, :] = 100 * self.cursor
        return img

    def text(self):
        if self.page is None:
            return "FIGHT RUN HP 19/19"
        return self.PAGES[self.page][: 6 * (self.typed + 1)]

    def snapshot(self):
        return (self.page, self.cursor, self.frames, self.typed)

    def restore(self, s):
        self.page, self.cursor, self.frames, self.typed = s

    def wait(self, n):
        self.frames += n
        if self.page is not None:
            self.typed += 1          # the box types out over a few waits, then stands still

    def press(self, k, hold=4, after=10):
        self.frames += hold + after
        if self.page is None:
            if k == "a":
                self.page, self.typed = 0, 0
            elif k == "down":
                self.cursor = 1 - self.cursor
        elif k == "a" and self.typed >= 3:
            self.page = self.page + 1 if self.page + 1 < len(self.PAGES) else None
            self.typed = 0

    def branch(self, seqs, frames=16):
        s = self.snapshot()
        out = {}
        for lab, keys in seqs.items():
            self.restore(s)
            for k in keys:
                self.press(k)
            self.wait(frames)
            out[lab] = {"screen": self.screen()}
        self.restore(s)
        return out


def test_a_choice_is_played_until_the_game_asks_again_and_the_game_is_put_back():
    g = Game()
    read = lambda img: g.text()  # noqa: E731
    r = play_out(g, ["a"], read, step=5)
    assert r["end"] == "asks" and r["pages"] >= 2
    said = new_lines(r)
    assert any("SQUIRTLE used TACKLE" in t for t in said) and any("15/19" in t for t in said)
    assert g.page is None and g.frames == 0                     # put back exactly
    assert "then asks again" in describe(r)


def test_numbers_keep_fractions_together():
    assert numbers("HP 19/ 19 :L5 x3") == ["19/19", "5", "3"]


def test_a_game_that_never_asks_stops_at_the_cap():
    g = Game()
    g.PAGES = ["..."] * 50
    r = play_out(g, ["a"], lambda img: g.text(), step=5, max_frames=300)
    assert r["end"] == "cap" and r["frames"] >= 300


def test_a_screen_where_neither_a_nor_a_direction_does_anything_waits():
    g = Game()
    g.PAGES = []
    g.press = lambda k, hold=4, after=10: setattr(g, "frames", g.frames + hold + after)    # every button ignored
    r = play_out(g, [], lambda img: "PAUSE START: exit", step=5, max_frames=600)
    assert r["end"] == "waits" and r["frames"] < 600 and "waits for another button" in describe(r)
