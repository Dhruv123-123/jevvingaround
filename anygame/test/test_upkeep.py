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
    k.see(2, hp(18), place="lab")
    k.see(3, hp(9), place="lab")                              # dropped 9 at once: one more such turn reaches 0
    assert "one bad turn" in k.advice()["why"]


def test_a_count_the_player_spends_is_not_health_and_the_fatal_one_is_the_last_to_come_down():
    k = Upkeep()
    pp = lambda v: {"TYPE/ NORMAL #/# (2)": {"value": v, "of": 10}}
    for t, v in enumerate((10, 9, 8, 5, 2, 1, 0)):            # spent where the player chooses: never a reason to leave
        k.see(t, pp(v), screen="choice")
    assert k.advice() is None
    for t, v in enumerate((20, 14, 9, 1), start=10):          # taken while the game plays on, by different amounts
        k.see(t, {**hp(v), **pp(0)}, screen="text")
    assert k.advice()["number"] == "HP #/#"
    k.see(20, None, moved=True)                               # a blackout: HP came down last, the PP long before
    assert k.tracks["HP #/#"].fatal is True and k.tracks["TYPE/ NORMAL #/# (2)"].fatal is None


def test_exits_are_choices_that_come_back_to_the_world_soonest():
    out = {"FIGHT": {"ends_on": "choice", "frames": 300}, "RUN": {"ends_on": "walk", "frames": 120},
           "ITEM": {"ends_on": "walk", "frames": 400}}
    assert rank_exits(out) == ["RUN", "ITEM"]
