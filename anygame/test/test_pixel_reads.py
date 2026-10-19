"""Gauges and a menu cursor read from pixels by shape (anygame/perceive/pixel_reads.py), on drawn screens."""
import numpy as np

from anygame.perceive.pixel_reads import cursor, gauges


def _screen():
    return np.full((144, 160), 255, np.uint8)


def _bar(img, x, y, w, fill, shade=85):
    img[y, x:x + w] = 0
    img[y + 3, x:x + w] = 0
    img[y + 1:y + 3, x + 1:x + 1 + int((w - 2) * fill)] = shade


def _box(img, x0, y0, x1, y1):
    for d in (0, 2):                                    # a double border, as dialogue boxes have
        img[y0 + d, x0:x1] = 0
        img[y1 - d, x0:x1] = 0
        img[y0:y1, x0 + d] = 0
        img[y0:y1, x1 - 1 - d] = 0


def test_gauges_read_fill_and_skip_box_borders():
    img = _screen()
    _bar(img, 32, 18, 48, 1.0)
    _bar(img, 96, 74, 48, 0.25)
    _box(img, 0, 96, 160, 143)
    g = gauges(img)
    assert [(b["x"], b["y"]) for b in g] == [(32, 18), (96, 74)]
    assert g[0]["fill"] == 1.0 and abs(g[1]["fill"] - 0.25) < 0.05


def test_cursor_is_where_the_press_drew_the_small_moving_thing():
    before, after = _screen(), _screen()
    for img in (before, after):
        img[100:107, 50:100] = np.where(np.random.default_rng(0).random((7, 50)) < 0.4, 0, 255)   # menu text
    before[104:111, 40:46] = 0                          # the cursor on one row
    after[112:119, 40:46] = 0                           # and on the next, after "down"
    assert cursor(before, after) == (42, 115)
    moved = _screen()
    moved[:, :80] = 0                                   # half the screen changed: not a cursor
    assert cursor(_screen(), moved) is None
