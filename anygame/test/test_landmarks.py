"""Names heard at places: who speaks where, and words that are only sentence starts."""
from anygame.landmarks import Landmarks


def test_a_speaker_belongs_where_it_speaks_and_ordinary_words_have_no_place():
    lines = [
        {"map": 1, "text": "MOM: Right. All boys leave home some day."},
        {"map": 1, "text": "MOM: PROF.OAK, next door, is looking for you."},
        {"map": 3, "text": "OAK: Now, RED, which POKeMON do you want?"},
        {"map": 3, "text": "OAK? Take this to your rival."},       # a colon misread as "?"
        {"map": 3, "text": "OAK: Right! Take good care of it."},
        {"map": 2, "text": "Right now the road is closed."},
        {"map": 5, "text": "Hey! You came from PALLET TOWN? Take this to PROF.OAK."},
    ]
    m = Landmarks()
    m.update(lines)
    assert m.where("oak") == 3 and m.where("mom") == 1
    assert m.where("right") is None                    # also written "right" in lower case: not a name
    assert m.heard_at(3)[0] == "oak"
    found = dict(m.find("Take this to PROF.OAK, then go see MOM"))
    assert found["oak"] == 3 and found["mom"] == 1


def test_merged_places_count_as_one():
    m = Landmarks()
    m.update([{"map": 7, "text": "Tom: Let's talk inside."}, {"map": 8, "text": "Tom: Can I spend some time with you?"}],
             canonical=lambda p: 7)
    assert m.where("tom") == 7


def test_a_closed_road_and_a_named_person_make_an_errand_out_and_back():
    from anygame.landmarks import errand_from
    lines = [
        {"map": 3, "tick": 10, "text": "OAK: Now, RED, which POKeMON do you want?"},
        {"map": 3, "tick": 12, "text": "OAK: Take good care of it."},
        {"map": 3, "tick": 14, "text": "OAK: Off you go."},
        {"map": 9, "tick": 400, "text": "Hey! You came from PALLET TOWN? Take this to PROF.OAK, will you?"},
        {"map": 9, "tick": 402, "text": "Thank you."},
    ]
    m = Landmarks()
    m.update(lines)
    e = errand_from(m, lines, here=9, since=390)
    assert e is not None and (e.origin, e.place, e.name) == (9, 3, "oak")
    assert e.goal()["target"] == {"place": 3}
    assert e.next()["done"] == {"talks": 2}
    assert e.next()["target"] == {"place": 9}
    assert e.next() is None
    assert errand_from(m, lines, here=3) is None        # nothing said here names a place elsewhere
