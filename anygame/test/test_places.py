"""Places from a discovered map signature and position: joins without doors, stairs, and names that are only noise."""
import numpy as np
from anygame.places import PlaceBook, cut_between

STEP = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def walk(book, sig, path, x, y):
    """Walk one tile per read along `path`, returning the place ids and where it ended."""
    out = []
    for d in path:
        x, y = x + STEP[d][0], y + STEP[d][1]
        out.append(book.see(sig, x, y, moves=[d], walking=True))
    return out, x, y


def test_a_map_joined_without_a_door_is_its_own_place_both_ways():
    b = PlaceBook()
    town = b.see("A", 10, 3)
    ids, x, y = walk(b, "A", ["up"] * 3, 10, 3)               # to the top row of the town
    assert set(ids) == {town}
    route = b.see("A", 10, 35, moves=["up"], walking=True)  # same name, row 0 -> 35 pressing up: the next map
    assert route != town
    ids, x, y = walk(b, "A", ["up"] * 5, 10, 35)
    assert set(ids) == {route}
    walk(b, "A", ["down"] * 5, x, y)
    assert b.see("A", 10, 0, moves=["down"], walking=True) == town   # back down: the town again
    assert b.neighbours(town) == {"up": route} and b.neighbours(route) == {"down": town}


def test_stairs_on_the_next_tile_are_a_door_and_noise_is_folded_back():
    b = PlaceBook()
    up = b.see("U", 5, 1)
    walk(b, "U", ["right"], 5, 1)
    down = b.see("D", 7, 1, moves=["right"], walking=True)  # a new name on an ordinary step: a door on trial
    assert down != up
    walk(b, "D", ["down", "down", "up", "up"], 7, 1)
    assert b.see("U", 6, 1, moves=["left"], walking=True) == up   # back by the same tile: stairs, kept
    assert b.canonical(down) == down
    # a byte that flips with scenery: the old name comes back somewhere else
    town = b.see("T", 20, 20)
    flip = b.see("T2", 21, 20, moves=["right"], walking=True)
    walk(b, "T2", ["right", "right", "right"], 21, 20)
    back = b.see("T", 25, 20, moves=["right"], walking=True)
    assert back == town and b.canonical(flip) == town
    assert any(e["kind"] == "merge" for e in b.events)


def test_a_name_written_after_the_step_still_counts_and_a_misread_position_is_no_join():
    b = PlaceBook()
    room = b.see("R", 7, 2)
    b.see("R", 7, 1, moves=["up"], walking=True)             # onto the stairs; the name is written late
    assert b.see("S", 7, 1) != room                          # the next read, standing: the new name
    b2 = PlaceBook()
    p = b2.see("A", 4, 4)
    assert b2.see("A", 4, 4000, moves=["up"], walking=True) == p   # a jump no map is wide enough for


def test_a_scroll_is_not_a_cut_and_a_new_scene_is():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 4, (144, 160)) * 80
    assert not cut_between(a, np.roll(a, 16, axis=1))
    assert cut_between(a, rng.integers(0, 4, (144, 160)) * 80)


def test_round_trip():
    b = PlaceBook()
    b.see("A", 10, 0)
    b.see("A", 10, 35, moves=["up"], walking=True)
    c = PlaceBook.from_dict(b.to_dict())
    assert c.report()["places"] == 2 and c.joins == b.joins and c.see("A", 10, 34, moves=["up"], walking=True) == b.here.id
