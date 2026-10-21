import numpy as np

from anygame.walk_book import STEPS, FightBook


def test_a_box_of_one_colour_matches_no_fight(tmp_path):
    # a fight's opening flash: a black frame, where the demo pressed A
    black = np.zeros((144, 160, 3), np.uint8)
    np.savez(tmp_path / "f.npz", shots=np.array([black]), steps=np.array([STEPS.index("a")]))
    book = FightBook(str(tmp_path / "f.npz"), box=True)
    # a cave entrance: rock above, the black past the map's edge below
    cave = np.zeros((144, 160, 3), np.uint8)
    cave[:96] = np.random.default_rng(0).integers(0, 255, (96, 160, 1), dtype=np.uint8)
    assert book.act(cave)[0] is None
    # a fight screen whose message box is new to the book still goes by its box
    fight = cave.copy()
    fight[96:] = 255
    fight[98, 8:152] = 0
    np.savez(tmp_path / "g.npz", shots=np.array([fight]), steps=np.array([STEPS.index("b")]))
    other = fight.copy()
    other[:96] = 128
    assert FightBook(str(tmp_path / "g.npz"), box=True).act(other)[0] == "b"
