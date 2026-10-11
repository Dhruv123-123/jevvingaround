"""Plausibility checks: a reading that cannot follow the last accepted one is read again, not acted on, and ends
the episode when it persists."""
import os
import cv2
import pytest
from anygame.pack import load_pack, load_pack_text, dump_pack, PackError
from anygame.perceive import read_all
from anygame.plausible import violations, check_spec
from anygame.loop import Agent
from test_anygame import FakeDevice, ChoiceJev

ROOT = os.path.dirname(os.path.dirname(__file__))
TTT = os.path.join(ROOT, "packs", "tictactoe")


def _probe(n):
    return cv2.imread(os.path.join(TTT, "fixtures", f"probe-{n}.png"))


def _glitch():
    """probe-3 (X at c1r2 and c2r2, O at c3r2 and c1r3) with the X at c1r2 painted out: a placed mark vanished."""
    f = _probe(3).copy()
    f[218:385, 20:186] = (55, 41, 31)          # the empty-cell colour #1f2937, BGR
    return f


SPEC = [
    {"read": "board", "sticky": ["X", "O"]},
    {"read": "board", "max_changes": 2},
    {"read": "board", "count": ["X", "O"], "diff": [0, 1]},
    {"when": {"read": "status", "equals": "our_turn"}, "read": "board", "count": ["X", "O"], "diff": [0, 0]},
    {"when": {"line": "board", "symbols": ["X", "O"], "length": 3}, "require": {"read": "status", "in": ["we_won", "we_lost"]}},
]
READS = {"board": {"otherwise": "."}, "status": {}}


def test_a_move_that_follows_passes_every_check():
    prev = {"board": ["...", ".X.", "O.."], "status": "our_turn"}
    now = {"board": ["...", "XXO", "O.."], "status": "our_turn"}
    assert violations(SPEC, now, prev, READS) == []
    assert violations(SPEC, now, None, READS) == []                       # the first reading has nothing to follow


def test_each_kind_of_impossible_reading_is_named():
    prev = {"board": ["...", "XXO", "O.."], "status": "our_turn"}
    flipped = violations(SPEC, {"board": ["...", "OXO", "O.."], "status": "our_turn"}, prev, READS)
    assert any("placed" in v and "c1r2 X→O" in v for v in flipped)
    jumped = violations(SPEC, {"board": ["XOX", "XXO", "O.."], "status": "our_turn"}, prev, READS)
    assert any("3 cells changed" in v for v in jumped)
    uneven = violations(SPEC, {"board": ["...", "XXO", "OO."], "status": "our_turn"}, prev, READS)
    assert any("count(X) - count(O) is -1" in v for v in uneven)
    # three in a row while the status still says it is a turn: the status read is missing the end state
    over = violations(SPEC, {"board": ["...", "XXX", "OO."], "status": "their_turn"}, {"board": ["...", "XX.", "OO."]}, READS)
    assert over == ["status is 'their_turn' but board has 3 in a line (require status in ['we_won', 'we_lost'])"]
    # `when` gates a check: the same uneven count is fine while it is their turn
    assert violations([SPEC[3]], {"board": ["...", "XX.", "O.."], "status": "their_turn"}, None, READS) == []


def test_a_cleared_board_is_a_restart_and_the_raw_grid_form_is_read_too():
    prev = {"board": ["XO.", "XXO", "O.X"]}
    assert violations(SPEC[:2], {"board": ["...", "...", "..."]}, prev, READS) == []
    raw_prev = {"board": {"c1r1": "X", "c2r1": ".", "c1r2": ".", "c2r2": "."}}
    raw_now = {"board": {"c1r1": ".", "c2r1": "X", "c1r2": ".", "c2r2": "."}}
    assert any("c1r1 X→." in v for v in violations([SPEC[0]], raw_now, raw_prev, READS))


def test_the_loader_refuses_a_malformed_check():
    base = open(os.path.join(TTT, "pack.yaml")).read().split("\ntests:")[0]
    assert load_pack(TTT).raw["plausible"]                                  # the bundled pack declares its checks
    for bad, why in [({"read": "nope", "sticky": ["X"]}, "grid read id"),
                     ({"read": "board", "count": ["X", "O"]}, "diff"),
                     ({"read": "board", "sticky": ["X"], "max_changes": 1}, "exactly one"),
                     ({"require": {"read": "status"}}, "condition")]:
        with pytest.raises(PackError, match=why):
            load_pack_text(base.replace("plausible:", f"plausible:\n  - {bad}\n  #", 1), "ttt")
    assert check_spec(None, {}) is None


def test_a_wrong_read_is_read_again_and_the_fresh_frame_is_acted_on():
    pack = load_pack(TTT)
    assert read_all(pack, _glitch())[0]["board"]["c1r2"] == "."            # the glitch frame really reads wrong
    dev = FakeDevice([_probe(2), _glitch(), _probe(3)])
    ag = Agent(pack, dev, ChoiceJev(noul=0.1))
    r1 = ag.step()
    assert r1["choice"] == "mark" and "implausible" not in r1
    r2 = ag.step()
    assert r2["reread"] == 1 and "implausible" not in r2
    assert r2["screen"]["board"] == ["...", "XXO", "O.."] and r2["choice"] == "mark"
    assert ag.rereads == 1 and ag.implausible_total == 0


def test_a_wrong_read_that_persists_is_never_acted_on_and_ends_the_episode():
    raw = load_pack(TTT).raw
    pack = load_pack_text(dump_pack({**{k: v for k, v in raw.items() if k != "tests"}, "plausible_ticks": 2}), "ttt")
    dev = FakeDevice([_probe(2), _glitch()])                                # the glitch never goes away
    ag = Agent(pack, dev, ChoiceJev(noul=0.1))
    ag.step()
    taps = len(dev.log)
    r2 = ag.step()
    assert r2["action"] == "wait" and r2["reason"] == "implausible read: board: count(X) - count(O) is -1, outside [0, 1]"
    assert r2["reread"] == 2
    r3 = ag.step()
    assert r3["action"] == "stop" and r3["reason"].startswith("stalled: implausible read for 2 ticks")
    assert len(dev.log) == taps                                            # nothing was done on a reading that did not add up
    # the next good reading is judged against the last accepted one, not the glitch
    assert ag.accepted["board"] == ["...", ".X.", "O.."]


def test_a_replay_is_not_read_again(tmp_path):
    from anygame.device.replay import ReplayDevice
    for i, f in enumerate([_probe(2), _glitch(), _probe(3)]):
        cv2.imwrite(str(tmp_path / f"{i:05d}.png"), f)
    dev = ReplayDevice(str(tmp_path))
    ag = Agent(load_pack(TTT), dev, ChoiceJev(noul=0.1))
    ag.step()
    r2 = ag.step()
    assert "reread" not in r2 and r2["implausible"] and dev.i == 2         # looking again would have skipped a recorded frame


def test_the_revision_is_pointed_at_the_read():
    from anygame.learn import Incident, Decision, incident_digest
    rec = {"tick": 30, "screen": {"board": ["...", "XXX", "OO."], "status": "their_turn"}, "action": "wait"}
    inc = Incident("stalled: lost (O won); implausible read: status is 'their_turn' but board has 3 in a line", 30, [Decision(rec, _probe(4), None)])
    assert "IMPLAUSIBLE READ" in incident_digest(inc) and "Fix the read" in incident_digest(inc)
