"""The chain script's redo rules (scripts/screenonly_chain.py): map landings and low health after a fight."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "screenonly_chain", os.path.join(os.path.dirname(__file__), "..", "scripts", "screenonly_chain.py"))
chain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chain)


def mem(map_id=59, hp=80, top=80, battle=0):
    m = [0] * 0x10000
    m[0xD35E], m[0xD057] = map_id, battle
    m[0xD16C], m[0xD16D], m[0xD18D], m[0xD18E] = hp >> 8, hp & 255, top >> 8, top & 255
    return m


def test_redo_list_takes_one_or_many():
    assert chain.redo_list({}) == []
    assert chain.redo_list({"redo": {"map": 68, "from": 0}}) == [{"map": 68, "from": 0}]
    assert len(chain.redo_list({"redo": [{"map": 68, "from": 0}, {"hp": 0.3, "from": 1}]})) == 2


def test_map_redo_fires_on_landing_only():
    r = {"map": [14, 68], "from": 0}
    assert chain.redo_due(mem(68), r, moved=True)
    assert not chain.redo_due(mem(68), r, moved=False)
    assert not chain.redo_due(mem(59), r, moved=True)


def test_hp_redo_waits_for_the_fight_to_end():
    r = {"hp": 0.3, "from": 0}
    assert chain.redo_due(mem(hp=20), r, moved=False)
    assert not chain.redo_due(mem(hp=20, battle=1), r, moved=False)
    assert not chain.redo_due(mem(hp=40), r, moved=False)
