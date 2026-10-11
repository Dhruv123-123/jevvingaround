"""Choosing by what a choice does to the other side's bar, against what its siblings do."""
import numpy as np
from anygame.battle import Fight, bars


def screen(enemy: int, mine: int, box: int = 0) -> np.ndarray:
    """A 144x160 grey screen: two bars on white with a black frame line above and below, and a menu box."""
    g = np.full((144, 160), 255, np.uint8)
    for top, x0, n in ((18, 32, enemy), (74, 96, mine)):
        g[top - 1, x0:x0 + 48] = 0
        g[top + 2, x0:x0 + 48] = 0
        g[top:top + 2, x0:x0 + n] = 90
    g[100:140, 10:150] = 255 - box
    return g


def outcome(enemy, mine, nums=None, box=0):
    return {"screen_before": screen(48, 48), "screen_after": screen(enemy, mine, box),
            "numbers_before": ["19/19"], "numbers_after": nums or [f"{round(19 * mine / 48)}/19"]}


def test_bars_are_found_and_text_rows_are_not():
    g = screen(40, 30)
    found = bars(g)
    assert found[(18, 32, 90 // 32)] == 40 and found[(74, 96, 90 // 32)] == 30
    g[60, 20:100:3] = 0                         # a line of "letters": no one colour beside the runs between them
    assert all(k[0] not in (59, 61) for k in bars(g))


def test_the_move_that_lowers_the_other_bar_ranks_first_and_the_own_bar_counts_against():
    f = Fight()
    order = f.rank({"tackle": f.effect("tackle", outcome(40, 40)), "growl": f.effect("growl", outcome(48, 40))})
    assert order == ["tackle", "growl"]
    # the player's own bar follows the shown number over two menus; then a choice that lowers it is worse
    f.rank({"a": f.effect("a", outcome(30, 30)), "b": f.effect("b", outcome(40, 24))})
    f.rank({"a": f.effect("a", outcome(24, 20)), "b": f.effect("b", outcome(30, 12))})
    assert (74, 96, 90 // 32) in f.own
    order = f.rank({"a": f.effect("a", outcome(20, 20)), "b": f.effect("b", outcome(18, 6))})
    assert order == ["a", "b"]


def test_nothing_to_tell_apart_and_different_end_screens_rank_nothing():
    f = Fight()
    assert f.rank({"a": f.effect("a", outcome(40, 40)), "b": f.effect("b", outcome(40, 40))}) == []
    assert f.rank({"a": f.effect("a", outcome(40, 40)), "b": f.effect("b", outcome(48, 40, box=200))}) == []
