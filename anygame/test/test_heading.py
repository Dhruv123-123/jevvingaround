"""Heading: which way to explore first when no goal names one."""
from anygame.heading import Heading
from anygame.places import PlaceBook


def test_a_route_entered_by_a_join_is_crossed_the_same_way_then_away_from_the_way_in():
    b = PlaceBook()
    h = Heading(b)
    town = b.see("A", 10, 1)
    assert h.toward(town) is None                         # where the run started: no way in, no heading
    b.see("A", 10, 0, moves=["up"], walking=True)
    route = b.see("A", 10, 35, moves=["up"], walking=True)
    assert h.toward(route) == "up"                        # walked off the top of the town: keep north
    house = b.see("H", 3, 7, moves=["up"], walking=True)  # a door into a house, landing at its bottom edge
    for y in (6, 5, 4):
        b.see("H", 3, y, moves=["up"], walking=True)
    b.see("H", 4, 4, moves=["right"], walking=True)
    assert h.toward(house) == "up"                        # furthest from the door, not back out of it
