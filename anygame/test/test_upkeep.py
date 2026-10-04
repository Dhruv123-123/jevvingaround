"""Upkeep: a falling number, a floor the game shows to be fatal, and where the number last refilled."""
from anygame.upkeep import Upkeep, rank_exits


def hp(v, most=20):
    return {"HP #/#": {"value": v, "of": most}}


def test_it_learns_the_floor_is_fatal_and_sends_the_player_back_to_where_it_refilled():
    k = Upkeep()
    k.see(1, hp(20), place="town")
    k.see(2, hp(12), place="route")
    assert k.advice() is None
    k.see(3, hp(3), place="route")
    a = k.advice()
    assert a["leave"] and "assumed fatal" in a["why"] and a["goal"]["target"] is None   # nowhere known to refill yet
    k.see(4, hp(1), place="route")
    k.see(9, None, place="home", moved=True)                 # put somewhere without walking, just after nearing 0
    assert k.tracks["HP #/#"].fatal is True
    k.see(10, hp(20), place="home")                          # full again there: that is where it refills
    assert k.advice() is None and k.tracks["HP #/#"].refill["place"] == "home"
    k.see(20, hp(15), place="route")
    k.see(21, hp(5), place="route")
    a = k.advice()
    assert "shown it is fatal" in a["why"] and a["goal"]["target"] == {"place": "home"}
    assert a["goal"]["done"] == {"number": {"name": "HP #/#", "share_at_least": 0.9}}


def test_a_number_that_hits_zero_without_consequence_is_watched_but_a_big_drop_warns_early():
    k = Upkeep()
    k.see(1, hp(20), place="lab")
    k.see(2, hp(9), place="lab")                              # dropped 11 at once: one more such turn reaches 0
    assert "one bad turn" in k.advice()["why"]


def test_exits_are_choices_that_come_back_to_the_world_soonest():
    out = {"FIGHT": {"ends_on": "choice", "frames": 300}, "RUN": {"ends_on": "walk", "frames": 120},
           "ITEM": {"ends_on": "walk", "frames": 400}}
    assert rank_exits(out) == ["RUN", "ITEM"]
