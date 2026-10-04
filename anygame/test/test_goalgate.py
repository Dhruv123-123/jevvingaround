"""When the goal writer is called: only on news, once after a give-up, within a budget that grows with game time."""
from anygame.goalgate import GoalGate, compact

HOUR = 60 * 3600


def test_news_is_text_the_run_has_not_seen_and_not_a_menu():
    g = GoalGate()
    assert g.see("Hello there! Welcome to the world of POKEMON!")
    assert not g.see("Hello there! Welcome to the vorld of POKEMON!")       # a misread of a line already seen
    assert not g.see("POKEMON ITEM RED SAVE OPTION EXIT", screen="choice")  # a menu
    assert not g.see("ITEM SAVE")                                           # too little that is new
    assert g.see("Mom says Professor Oak is next door looking for you")


def test_the_writer_is_asked_on_news_and_not_when_a_goal_just_ends():
    g = GoalGate(min_gap=10)
    assert g.ask(0, 0, need=True) == (False, "nothing new since the last call")
    g.see("Professor Oak wants to see you in his lab")
    assert g.ask(5, 300, need=False)[0]
    g.called(5, 300, "set")
    g.see("Professor Oak is out right now, come back later")
    assert g.ask(8, 400, need=False) == (False, "too soon")
    assert g.ask(20, 900, need=False)[0]
    g.called(20, 900, "set")
    assert not g.ask(40, 1500, need=True, ended="reached")[0]               # the generic goal follows, for free
    assert g.ask(41, 1500, need=True, ended="given up")[0]                  # once after a give-up
    g.called(41, 1500, "set")
    assert not g.ask(80, 2500, need=True, ended="reached")[0]


def test_news_kept_over_is_asked_again_when_the_goal_ends():
    g = GoalGate(min_gap=1)
    g.see("Take this parcel to Professor Oak in Pallet Town")
    assert g.ask(1, 60, need=False)[0]
    g.called(1, 60, "kept")
    assert g.ask(30, 900, need=True, ended="reached")[0]
    g.called(30, 900, "set")
    assert not g.ask(60, 1800, need=True, ended="reached")[0]


def test_the_budget_grows_with_game_time():
    g = GoalGate(per_hour=10, burst=2, min_gap=0)
    for t, line in enumerate(["alpha bravo charlie delta", "echo foxtrot golf hotel"]):
        g.see(line)
        assert g.ask(t, 0, need=False)[0]
        g.called(t, 0)
    g.see("entirely different words arrive here")
    assert g.ask(3, 0, need=False) == (False, "over budget")
    assert g.ask(4, HOUR // 10, need=False)[0]                               # six game minutes later: one more


def test_compact_folds_typing_and_rereads():
    lines = [{"text": t, "tick": i} for i, t in enumerate([
        "Mom: Right.", "Mom: Right. All boys leave home", "POKEMON ITEM RED SAVE", "Prof Oak next door is looking",
        "POKEMON ITEM RED SAVE OPTION"])]
    out = compact(lines)
    assert [d["text"] for d in out] == ["Mom: Right. All boys leave home", "Prof Oak next door is looking",
                                        "POKEMON ITEM RED SAVE OPTION"]
    assert [d["i"] for d in out] == [1, 3, 4]
