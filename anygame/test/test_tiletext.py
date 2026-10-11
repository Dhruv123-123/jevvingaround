"""Text read from a tile-drawn screen: glyphs keyed by their cell's pixels, labelled once by a stand-in chat model,
answers kept only when their words fit the line's runs of inked cells."""
import json
import numpy as np
from anygame.perceive.tiletext import GlyphBook, TileText, cells

rng = np.random.default_rng(3)
FONT = {ch: (rng.random((8, 8)) < 0.35) for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ!?"}
for m in FONT.values():
    m[0, :] = False            # a row of background, so no glyph is mostly ink
    m[1, 1] = True
    m[2, 2] = True
    m[3, 3] = True


def screen(rows: dict[int, str], ink=(0, 0, 0), paper=(255, 255, 255), scale=3) -> np.ndarray:
    """A 160x144 screen with these lines of text (row → text from column 1), shown at `scale` like the device does."""
    img = np.zeros((144, 160, 3), np.uint8)
    img[:] = (90, 140, 90)                                 # the world behind the text box: one colour per cell
    img[8 * 12:, :] = paper                                 # the text box
    img[0:8, 0:8] = (10, 200, 40)
    img[2:5, 2:5] = (200, 10, 40)                           # a picture cell: three colours, never text
    img[5:7, 5:7] = (20, 20, 220)
    for r, text in rows.items():
        for q, ch in enumerate(text):
            if ch == " ":
                continue
            m = FONT[ch]
            cell = img[r * 8:(r + 1) * 8, (q + 1) * 8:(q + 2) * 8]
            cell[m] = ink
    return np.repeat(np.repeat(img, scale, 0), scale, 1)


class FakeChat:
    """Reads the strips it is shown by looking the glyphs up in the font, like a perfect vision model; `bad` misreads."""
    def __init__(self, truth_lines, bad=None):
        self.truth_lines = truth_lines
        self.bad = bad or {}
        self.calls = 0

    def complete(self, messages, max_tokens=0, extra=None):
        self.calls += 1
        desc = messages[1]["content"][0]["text"]
        n = desc.count("line ")
        out = [self.bad.get(t, t) for t in self.truth_lines[:n]]
        self.truth_lines = self.truth_lines[n:]
        return json.dumps({"lines": out}), {"total_tokens": 10}, 5


def test_cells_tell_text_from_pictures_and_empty():
    _img, keys, kinds = cells(screen({13: "HELLO"}))
    assert kinds[13, 1] == 1 and kinds[13, 6] == 0 and kinds[0, 0] == 2
    assert keys[13][1] and keys[13][1] != keys[13][2]                         # H and E: two glyphs
    assert keys[13][3] == keys[13][4]                                         # the two L's are one glyph


def test_a_glyph_is_trusted_after_two_agreeing_lines_and_then_read_exactly():
    b = GlyphBook()
    t = TileText({"sync": True, "batch": 1, "labeller": "chat"}, b)
    t.chat, t.chat_tried = FakeChat(["HELLO THERE", "THE OTHER"]), True
    text, st = t.read(screen({13: "HELLO THERE"}))
    assert "?" in text and st["unknown"] > 0                 # nothing known before the labeller answers
    t.read(screen({14: "THE OTHER"}))
    text, st = t.read(screen({13: "HELLO THERE", 15: "HOT"}))
    # letters seen in both lines are trusted (H, E, T, O, R); L only once: still '?'
    assert text.startswith("HE??O THERE") and "HOT" in text
    assert st["unknown"] == 2


def test_inverted_colours_are_the_same_glyph():
    a = cells(screen({13: "HI"}))[1][13][1]
    b = cells(screen({13: "HI"}, ink=(255, 255, 255), paper=(0, 0, 0)))[1][13][1]
    assert a == b


def test_an_answer_whose_words_do_not_fit_the_line_is_not_learned():
    b = GlyphBook()
    t = TileText({"sync": True, "batch": 1}, b)
    t.chat, t.chat_tried = FakeChat(["HELLO THERE", "HELLO THERE"], bad={"HELLO THERE": "HELLOTHERE"}), True
    t.read(screen({13: "HELLO THERE"}))
    t.read(screen({14: "HELLO THERE"}))
    assert not b.labels and b.rejected >= 1


def test_a_reading_that_contradicts_trusted_glyphs_is_dropped():
    b = GlyphBook()
    keys = cells(screen({13: "HOTEL"}))[1][13][1:6]
    for _ in range(2):
        assert b.vote(keys, "HOTEL", "chat")
    assert len(b.labels) == 5
    keys2 = cells(screen({13: "HOTELS"}))[1][13][1:7]
    assert not b.vote(keys2, "QWERTY", "chat")            # every known letter disagrees: a misread or another line
    assert "S" not in b.labels.values()


def test_the_book_round_trips(tmp_path):
    b = GlyphBook()
    keys = cells(screen({13: "AB CD"}))[1][13][1:6]
    b.vote(keys, "AB CD", "chat")
    b.vote(keys, "AB CD", "chat")
    p = str(tmp_path / "g.json")
    b.save(p)
    c = GlyphBook(p)
    assert c.labels == b.labels and len(c.labels) == 4


def test_a_second_glyph_for_a_character_already_known_needs_two_lines():
    b = GlyphBook()
    keys = cells(screen({13: "HOTEL"}))[1][13][1:6]
    for _ in range(2):
        b.vote(keys, "HOTEL", "chat")
    keys2 = cells(screen({13: "HOTELW"}))[1][13][1:7]
    b.vote(keys2, "HOTELL", "chat")                       # W read as L, vouched for by five trusted letters
    w = keys2[5]
    assert w not in b.labels                              # L is already another glyph's: a lookalike, not trusted yet
    keys3 = cells(screen({13: "HOTELS"}))[1][13][1:7]
    b.vote(keys3, "HOTELS", "chat")
    assert b.labels[keys3[5]] == "S"                      # a character no glyph has yet: one vouched line is enough


def test_a_line_read_as_all_not_text_settles_its_glyphs_at_once():
    from anygame.perceive.tiletext import GlyphBook
    b = GlyphBook()
    assert b.vote(["a", "b", None, "c"], "## #", "chat")
    assert b.labels == {"a": "#", "b": "#", "c": "#"}
    b2 = GlyphBook()
    b2.vote(["a", "b", None, "c"], "Hi !", "chat")
    assert b2.labels == {}                      # a line of characters still needs a second reading


def test_menu_boxes_come_from_the_cells_once_the_font_is_known_and_skip_unknown_cells():
    from anygame.perceive import tiletext
    r = {"labeller": "none"}
    t = tiletext.reader(r, None)
    t.book = GlyphBook()
    img = screen({13: "NEW GAME", 15: "OPTION"})
    assert tiletext.boxes(img, r, cold=20) is None                      # a cold book: the menu reads by OCR meanwhile
    for line in ("ABCDEFGHIJKLM", "NOPQRSTUVWXYZ"):
        for k, ch in zip(cells(screen({13: line}))[1][13][1:], line):
            t.book.labels[k] = ch
    out = tiletext.boxes(img, r, cold=20)
    assert [b[4] for b in out] == ["NEW GAME", "OPTION"] and out[0][1] == 13 * 8 * 3
    junk = img.copy()
    junk[16 * 24:17 * 24, 24:24 * 6] = rng.integers(0, 2, (24, 24 * 5, 1)) * 255   # cells no book knows
    assert [b[4] for b in tiletext.boxes(junk, r, cold=20)] == ["NEW GAME", "OPTION"]       # skipped, not sent to OCR
