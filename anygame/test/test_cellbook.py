"""The screen-only cell book: keys from pixels, novelty, votes, the game's confirmations, the labeller's batching."""
import json

import numpy as np

from anygame.perceive.cellbook import CellBook, Labeller, ahead, grid, parse, shift, sheet, crop


def _screen(seed=0, n=4):
    """A tiled screen: n distinct 8x8 tiles laid out on a 20x18 grid."""
    rng = np.random.default_rng(seed)
    tiles = rng.integers(0, 4, size=(n, 8, 8)) * 80
    layout = rng.integers(0, n, size=(18, 20))
    img = np.zeros((144, 160, 3), np.uint8)
    for r in range(18):
        for c in range(20):
            img[r * 8:(r + 1) * 8, c * 8:(c + 1) * 8] = tiles[layout[r, c]][:, :, None]
    return img, layout


def test_same_pixels_same_key():
    img, layout = _screen()
    keys = grid(img)
    assert keys.shape == (18, 20)
    by_tile = {}
    for r in range(18):
        for c in range(20):
            by_tile.setdefault(layout[r, c], set()).add(keys[r, c])
    assert all(len(v) == 1 for v in by_tile.values())
    assert len({next(iter(v)) for v in by_tile.values()}) == len(by_tile)


def test_novelty_and_hits():
    img, _ = _screen()
    book = CellBook()
    keys = book.keys(img)
    seen = book.see(img, keys)
    assert seen["known"] == 0 and len(seen["novel"]) == 360 and not seen["screen_known"]
    for k in set(keys.flat):
        book.vote(k, "G")
    seen = book.see(img, keys)
    assert seen["known"] == 360 and seen["screen_known"]
    assert book.novel(keys) == []


def test_phase_found_on_a_scrolled_screen():
    img, _ = _screen(1, n=80)
    book = CellBook()
    for k in set(grid(img).flat):
        book.vote(k, "G")
    scrolled = np.roll(img, (3, 5), axis=(0, 1))       # 3 down, 5 right
    keys = book.keys(scrolled)
    assert book.phase == (5, 3)
    assert sum(1 for k in keys.flat if k in book.cells) / keys.size > 0.95


def test_votes_verify_and_contradict():
    book = CellBook()
    assert book.vote("k", "G") == "new"
    assert book.cells["k"]["state"] == "labelled"
    assert book.vote("k", "G") == "agree"
    assert book.cells["k"]["state"] == "verified"
    assert book.vote("k", "W") == "contradict"
    assert book.cells["k"]["contradictions"] == 1 and book.cells["k"]["label"] == "G"


def test_game_confirmation_outweighs_the_model():
    book = CellBook()
    book.vote("k", "W")
    assert book.confirm("k", walkable=True) == "contradict"
    assert book.cells["k"]["label"] == "G" and book.cells["k"]["state"] == "verified"
    book.vote("p", "P")
    assert book.confirm("p", walkable=True) == "skip"
    assert book.confirm("new", walkable=True) == "new" and book.cells["new"]["source"] == "game"


def test_shift_and_ahead():
    img, _ = _screen(2)
    moved = np.roll(img, -16, axis=1)                   # walking right scrolls the picture left
    moved[:, -16:] = 0
    assert shift(img, moved, "right") == 16
    assert shift(img, img, "right") == 0
    player = [(7, 8), (7, 9), (8, 8), (8, 9), (9, 8), (9, 9)]
    assert ahead(player, "right", (18, 20)) == [(8, 10), (8, 11), (9, 10), (9, 11)]
    assert ahead(player, "up", (18, 20), reach=1) == [(7, 8), (7, 9)]


def test_parse_and_sheet():
    assert parse('{"0": "G", "1": "w", "2": "T"}', 3) == "GWT"
    assert parse('{"0": "G", "2": "T"}', 3) == "GUT"
    assert parse('{"0": "G"}', 3) is None
    assert parse('{"labels": "GGWT"}', 4) == "GGWT"
    assert parse('{"labels": "G G W"}', 3) == "GGW"
    assert parse('{"labels": "GG"}', 3) is None
    assert parse("no json", 1) is None
    img, _ = _screen()
    c = crop(img, 0, 0)
    assert c.shape == (24, 24, 3)
    s = sheet([c] * 10, scale=4, cols=8)
    assert s.shape[0] == 2 * (96 + 18)


class FakeChat:
    def __init__(self, letter="G"):
        self.cost, self.calls, self.letter, self.sent = 0.0, 0, letter, []

    def complete(self, msgs, max_tokens=0, extra=None):
        n = int(msgs[1]["content"][0]["text"].split()[0])
        self.sent.append(n)
        self.cost += 0.002
        return json.dumps({str(i): self.letter for i in range(n)}), {"prompt_tokens": 10, "completion_tokens": 5}, 1


def test_labeller_batches_new_keys_once_and_stops_at_budget():
    img, _ = _screen()
    book = CellBook()
    chat = FakeChat()
    lab = Labeller(chat, per_call=3, budget=0.003)
    keys = book.keys(img)
    assert lab.add(img, keys, book.phase, book)
    assert not lab.add(img, keys, book.phase, book)     # the same keys are already queued
    assert len(lab.queue) == 4
    lab.flush(book)
    assert chat.sent == [3] and len(lab.queue) == 1
    lab.flush(book)
    assert chat.sent == [3, 1]
    assert all(book.label(k) == "G" for k in set(keys.flat))
    img2, _ = _screen(5)
    lab.add(img2, book.keys(img2), book.phase, book)
    assert lab.over() and lab.flush(book) is None
