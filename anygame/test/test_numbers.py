"""Numbers printed on screen, labelled, found in RAM, and checked by a goal condition."""
import numpy as np
from anygame.numbers import NumberBook, parse, check, holds


def test_parse_labels_and_fractions():
    got = parse("BULBASAUR :L5 HP: SQUIRTLE :L5 13/ 19 >FIGHT")
    names = {d["name"]: d for d in got}
    assert names["BULBASAUR :L#"]["value"] == 5 and names["SQUIRTLE :L#"]["value"] == 5
    hp = names["SQUIRTLE #/#"]
    assert hp["value"] == 13 and hp["of"] == 19 and hp["share"] == 0.684
    assert parse("MONEY $3000")[0]["name"] == "MONEY $#"


def test_a_number_is_bound_to_the_ram_that_follows_it_and_read_from_there():
    b = NumberBook()
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, 0x2000).astype(np.uint8)
    for hp in (19, 13, 10, 4):
        ram = base.copy()
        ram[0x1015], ram[0x1016] = hp >> 8, hp & 0xFF        # the game's own variable, 16-bit big-endian
        b.observe(f"SQUIRTLE {hp}/ 19", ram)
    assert ("u16be", 0xD015) in b.bound["SQUIRTLE #/#"]
    ram = base.copy()
    ram[0x1016] = 2                                           # off screen now: read from RAM
    v = b.values(ram)["SQUIRTLE #/#"]
    assert v["value"] == 2 and v["from"] == "ram" and v["share"] == round(2 / 19, 3)


def test_goal_condition_over_a_number():
    vals = {"SQUIRTLE #/#": {"value": 4, "of": 19, "share": 0.21}, "SQUIRTLE :L#": {"value": 5}}
    assert check({"number": {"name": "SQUIRTLE #/#", "share_at_least": 0.8}}, set(vals)) is None
    assert check({"number": {"name": "PIKACHU", "at_least": 3}}, set(vals))
    assert check({"number": {"name": "SQUIRTLE :L#", "at_least": 3, "at_most": 9}})
    assert not holds({"number": {"name": "SQUIRTLE #/#", "share_at_least": 0.8}}, vals)
    assert holds({"number": {"name": "SQUIRTLE :L#", "at_least": 5}}, vals)
