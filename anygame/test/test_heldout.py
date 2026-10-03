"""The held-out score: the agent never sees it, the grader reads memory correctly, a run is reproducible by seed."""
import ast
import json
from pathlib import Path

import pytest
import yaml

from heldout.grader import Grader, check_game, holds
from heldout.run import load_suite

ROOT = Path(__file__).resolve().parent.parent          # anygame/


def test_agent_never_imports_or_reads_heldout():
    """Nothing the agent runs may import heldout/ or name its files: the grader's memory addresses and the game list
    stay on the grader's side. heldout/ importing the agent is fine (that is how it runs it)."""
    bad = []
    for p in sorted((ROOT / "anygame").rglob("*.py")):
        tree = ast.parse(p.read_text(), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bad += [f"{p}: import {a.name}" for a in node.names if a.name.split(".")[0] == "heldout"]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "heldout":
                bad.append(f"{p}: from {node.module} import")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "heldout" in node.value:
                bad.append(f"{p}: names heldout in a string")
    for p in sorted((ROOT / "ext" / "src").rglob("*.ts")):
        if "heldout" in p.read_text():
            bad.append(f"{p}: names heldout")
    assert not bad, "\n".join(bad)


def test_generic_pack_names_no_game():
    """The pack the suite plays is the same for every game and names none of them."""
    text = (ROOT / "packs" / "gameboy" / "pack.yaml").read_text().lower()
    suite = load_suite()
    for gid in suite["games"]:
        for name in {gid, gid.replace("-", " "), gid.replace("-", "")}:
            assert name not in text, f"packs/gameboy names {name}"


def test_suite_games_are_valid():
    suite = load_suite()
    assert suite["held_out"] and not set(suite["held_out"]) & set(suite["development"])
    for gid, g in suite["games"].items():
        check_game(g)
        assert g["id"] == gid
        assert "url" in g["rom"] or "path" in g["rom"]
        if "url" in g["rom"]:
            assert g["rom"].get("sha256"), f"{gid}: a fetched ROM needs a sha256"


def test_conditions():
    ram = {0xC000: 0x76, 0xC001: 0x06, 0xC002: 0x00, 0xC010: 0b0000_0101, 0xC020: 0x34, 0xC021: 0x12}
    mem = lambda a: ram.get(a, 0)  # noqa: E731
    assert holds({"bcd": 0xC000, "bytes": 3, "ge": 676}, mem) and not holds({"bcd": 0xC000, "bytes": 3, "ge": 677}, mem)
    assert holds({"bcd": 0xC000, "bytes": 2, "order": "be", "eq": 7606}, mem)
    assert holds({"u16": 0xC020, "eq": 0x1234}, mem) and holds({"u16be": 0xC020, "eq": 0x3412}, mem)
    assert holds({"bit": 0xC010, "n": 2}, mem) and not holds({"bit": 0xC010, "n": 1}, mem)
    assert holds({"all": [{"u8": 0xC010, "in": [5, 6]}, {"any": [{"u8": 0xC099, "ne": 0}, {"u8": 0xC000}]}]}, mem)


def test_grader_latches_in_order():
    g = Grader({"id": "t", "milestones": [
        {"id": "inside", "desc": "a", "when": {"u8": 0xC000, "eq": 5}},
        {"id": "out", "desc": "b", "when": {"u8": 0xC000, "eq": 0}, "after": "inside"},   # 0 is also the power-on value
    ]})
    ram = {0xC000: 0}
    mem = lambda a: ram.get(a, 0)  # noqa: E731
    assert g.update(mem, {"frame": 1}) == []            # 0 before 'inside' does not count
    ram[0xC000] = 5
    assert g.update(mem, {"frame": 2}) == ["inside"]
    ram[0xC000] = 0
    assert g.update(mem, {"frame": 3}) == ["out"]
    ram[0xC000] = 9
    assert g.update(mem, {"frame": 4}) == [] and g.score == 1.0 and g.reached["inside"]["frame"] == 2


def test_check_game_refuses_bad_after():
    with pytest.raises(ValueError):
        check_game({"id": "t", "milestones": [{"id": "a", "desc": "a", "when": {"u8": 1}, "after": "b"}, {"id": "b", "desc": "b", "when": {"u8": 1}}]})


def test_run_is_reproducible_by_seed(tmp_path):
    """End to end on the repo's own Game Boy ROM (2048gb, zlib), with a stand-in milestone: two runs with one seed
    press the same buttons and reach the same milestone at the same frame."""
    pytest.importorskip("pyboy")
    from heldout.run import run_one
    rom = ROOT / "roms" / "2048gb" / "2048.gb"
    game = {"id": "t2048", "kind": "puzzle", "tier": "held_out", "rom": {"path": str(rom)},
            "milestones": [{"id": "on", "desc": "any frame", "when": {"u8": 0xC000, "ge": 0}},
                           {"id": "never", "desc": "a byte is never 300", "when": {"u8": 0xC000, "eq": 300}}]}
    suite = {"budget": {"frames": 1200, "presses": 40, "wall_s": 60, "jev_calls": 40, "usd": 0.01}, "games": {"t2048": game},
             "pack": "gameboy", "device": {"idle": 4, "hold": 6, "after": 16}}
    rows = [run_one(suite, "t2048", "random", 7, tmp_path / f"r{i}") for i in range(2)]
    for r in rows:
        assert r["score"] == 0.5 and r["stop"] in ("frames", "presses")
    logs = [[json.loads(l)["choice"] for l in (tmp_path / f"r{i}" / "t2048-random-7.jsonl").read_text().splitlines()] for i in range(2)]
    assert logs[0] == logs[1]
    assert len(logs[0]) > 10 and rows[0]["frames"] == rows[1]["frames"]
