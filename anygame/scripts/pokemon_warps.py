"""Print Pokemon Red map headers from the ROM: size, edge connections and warps (a test helper for planning fixture
walks, like pokemon_fixture_walk.py; the agent never reads the ROM or RAM).

    python scripts/pokemon_warps.py MAP [MAP ...]
    (each warp is (x, y, destination warp index, destination map); map 255 means "the map you came from")
"""
from __future__ import annotations
import sys

ROM = "/mnt/project-files/roms/pokemon-red.gb"


def header(rom: bytes, m: int) -> dict:
    def addr(bank, ptr):
        return ptr if ptr < 0x4000 else bank * 0x4000 + ptr - 0x4000

    def word(a):
        return rom[a] | rom[a + 1] << 8

    bank = rom[0xC23D + m]                      # MapHeaderBanks
    p = addr(bank, word(0x01AE + 2 * m))        # MapHeaderPointers
    flags, q, conns = rom[p + 9], p + 10, {}
    for bit, side in ((8, "N"), (4, "S"), (2, "W"), (1, "E")):
        if flags & bit:
            conns[side] = rom[q]                # the connected map; 11 bytes per connection
            q += 11
    obj = addr(bank, word(q))
    warps = [(rom[obj + 3 + 4 * i], rom[obj + 2 + 4 * i], rom[obj + 4 + 4 * i], rom[obj + 5 + 4 * i])
             for i in range(rom[obj + 1])]
    return {"blocks": (rom[p + 2], rom[p + 1]), "connections": conns, "warps": warps}


def main() -> None:
    rom = open(ROM, "rb").read()
    for m in map(int, sys.argv[1:]):
        print(m, header(rom, m))


if __name__ == "__main__":
    main()
