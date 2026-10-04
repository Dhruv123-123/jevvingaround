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
