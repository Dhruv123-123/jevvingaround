"""Aevilia milestones from RAM: for grading only. Addresses from the game's own source (Apache-2.0,
github.com/ISSOtm/Aevilia-GB: main/wram.asm, constants/maps.asm), located in the ROM by the variables around them:
wSaveFileID, wTargetWarpID, wLoadedMap, wLoadedMapROMBank, wLoadedTileset, wMapScriptPtr, wMapWidth, wMapHeight sit
together in HomeRAM. The game is unfinished (a 2017 demo), so the list ends where its story does."""
from __future__ import annotations
from typing import Any

W_SAVE_FILE_ID = 0xC3C2
W_LOADED_MAP = 0xC3C4
W_Y = 0xD710      # wYPos, wXPos: 2 bytes each, pixels (the agent finds these itself with `anygame ramscan`)
W_X = 0xD712
MAPS = {0: "STARTHAM", 1: "TEST_HOUSE", 2: "INTRO_MAP", 3: "STARTHAM_FOREST", 4: "PLAYER_HOUSE", 5: "PLAYER_HOUSE_2F",
        6: "STARTHAM_HOUSE_2", 7: "STARTHAM_LARGE_HOUSE"}


def facts(mem) -> dict[str, Any]:
    m = mem[W_LOADED_MAP]
    return {"map": m, "map_name": MAPS.get(m), "save_file": mem[W_SAVE_FILE_ID],
            "y": mem[W_Y] | mem[W_Y + 1] << 8, "x": mem[W_X] | mem[W_X + 1] << 8}


def _at(name):
    return lambda f, h: f["map_name"] == name and "tutorial" in h


MILESTONES: list[tuple[str, str, Any]] = [
    ("tutorial", "in the tutorial room (past the title screen and character select)", lambda f, h: f["map_name"] == "INTRO_MAP"),
    ("house_2f", "out of the tutorial: in the player's room", _at("PLAYER_HOUSE_2F")),
    ("house_1f", "downstairs in the player's house", _at("PLAYER_HOUSE")),
    ("startham", "outside in Startham", _at("STARTHAM")),
    ("other_house", "inside another house in Startham", lambda f, h: f["map_name"] in ("STARTHAM_HOUSE_2", "STARTHAM_LARGE_HOUSE") and "startham" in h),
    ("forest", "reached Startham Forest", _at("STARTHAM_FOREST")),
]


class Grader:
    game = "aevilia"

    def __init__(self):
        self.reached: dict[str, int] = {}
        self.updates = 0
        self.last: dict[str, Any] = {}
        self.maps_seen: set[int] = set()

    def update(self, mem, when: int | None = None) -> list[str]:
        self.updates += 1
        f = facts(mem)
        self.last = f
        if "tutorial" in self.reached or f["map_name"] == "INTRO_MAP":
            self.maps_seen.add(f["map"])
        new = []
        for mid, _, test in MILESTONES:
            if mid not in self.reached and test(f, self.reached):
                self.reached[mid] = self.updates if when is None else when
                new.append(mid)
        return new

    def progress(self) -> float:
        idx = [i for i, (mid, _, _) in enumerate(MILESTONES) if mid in self.reached]
        return (max(idx) + 1) / len(MILESTONES) if idx else 0.0

    def report(self) -> dict[str, Any]:
        return {"game": self.game, "reached": [m for m, _, _ in MILESTONES if m in self.reached], "when": dict(self.reached),
                "progress": round(self.progress(), 4), "milestones": len(MILESTONES), "maps_seen": sorted(self.maps_seen), "facts": self.last}


def matches(rom_title: str) -> bool:
    return rom_title.strip().upper().startswith("AEVILIA")
