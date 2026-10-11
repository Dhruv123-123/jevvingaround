"""Graders: progress read from state the agent is not allowed to read. One module per game, chosen by the ROM's
header title. A grader has update(mem) (sticky milestones, newly reached ones returned), progress() in 0..1 and
report(). The scoring harness calls these; the agent never imports them.

    from anygame.graders import for_rom
    g = for_rom("pokemon-red.gb")      # None when no grader knows the game
"""
from __future__ import annotations


def rom_title(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(0x150)
    return head[0x134:0x144].split(b"\x00")[0].decode("ascii", "replace")


def for_title(title: str):
    from . import pokemon_red, aevilia
    for mod in (pokemon_red, aevilia):
        if mod.matches(title):
            return mod.Grader()
    return None


def for_rom(path: str):
    return for_title(rom_title(path))
