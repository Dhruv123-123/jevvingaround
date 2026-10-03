"""Pokemon Red/Blue milestones from RAM: for grading only. The agent never reads these addresses (Dhruv's call,
2026-10-03: the published memory map grades, it does not play). Addresses and ids are from the pret/pokered
disassembly (wram.asm, map_constants.asm, item_constants.asm); the ones marked `verify` are checked against the
ROM the first time it runs.

    from anygame.graders.pokemon_red import Grader
    g = Grader()
    g.update(device.memory)     # every tick or every few seconds of game time: milestones are sticky
    g.report()                  # {"reached": [...], "progress": 0.14, "facts": {...}}
"""
from __future__ import annotations
from typing import Any

# wram addresses (pret/pokered)
W_PARTY_COUNT = 0xD163
W_PARTY_MONS = 0xD16B          # 44 bytes each; level at +0x21, HP at +1 (2 bytes, big-endian)
W_PLAYER_NAME = 0xD158
W_NUM_BAG_ITEMS = 0xD31D
W_BAG_ITEMS = 0xD31E           # (id, quantity) pairs, 0xFF ends
W_PLAYER_MONEY = 0xD347        # 3 bytes BCD
W_OBTAINED_BADGES = 0xD356
W_CUR_MAP = 0xD35E
W_Y = 0xD361
W_X = 0xD362
W_IS_IN_BATTLE = 0xD057        # 0 none, 1 wild, 2 trainer, 0xFF lost
W_POKEDEX_OWNED = 0xD2F7       # 19 bytes of flags

MAPS = {
    0x00: "PALLET_TOWN", 0x01: "VIRIDIAN_CITY", 0x02: "PEWTER_CITY", 0x03: "CERULEAN_CITY", 0x04: "LAVENDER_TOWN",
    0x05: "VERMILION_CITY", 0x06: "CELADON_CITY", 0x07: "FUCHSIA_CITY", 0x08: "CINNABAR_ISLAND", 0x09: "INDIGO_PLATEAU",
    0x0A: "SAFFRON_CITY", 0x0C: "ROUTE_1", 0x0D: "ROUTE_2", 0x0E: "ROUTE_3", 0x0F: "ROUTE_4", 0x21: "ROUTE_22", 0x22: "ROUTE_23",
    0x25: "REDS_HOUSE_1F", 0x26: "REDS_HOUSE_2F", 0x27: "BLUES_HOUSE", 0x28: "OAKS_LAB", 0x33: "VIRIDIAN_FOREST",
    0x3B: "MT_MOON_1F", 0x52: "ROCK_TUNNEL_1F", 0x6C: "VICTORY_ROAD_1F", 0x71: "LANCES_ROOM", 0x76: "HALL_OF_FAME",
    0x78: "CHAMPIONS_ROOM", 0xF5: "LORELEIS_ROOM", 0xF6: "BRUNOS_ROOM", 0xF7: "AGATHAS_ROOM",
}
ITEMS = {"OAKS_PARCEL": 0x46, "SS_TICKET": 0x3F, "SILPH_SCOPE": 0x48, "POKE_FLUTE": 0x49, "SECRET_KEY": 0x2B,   # verify
         "HM01": 0xC4, "HM03": 0xC6, "HM04": 0xC7}


def facts(mem) -> dict[str, Any]:
    """The grader's view of the game: what it reads, decoded. `mem` is anything indexable by address."""
    n = mem[W_PARTY_COUNT]
    n = n if n <= 6 else 0
    bag = []
    for i in range(min(mem[W_NUM_BAG_ITEMS], 20)):
        it = mem[W_BAG_ITEMS + 2 * i]
        if it == 0xFF:
            break
        bag.append(it)
    money = 0
    for i in range(3):
        b = mem[W_PLAYER_MONEY + i]
        money = money * 100 + (b >> 4) * 10 + (b & 15)
    name0 = mem[W_PLAYER_NAME]
    return {
        # before New Game the RAM is zeros, and map 0 is Pallet Town: the player's name (letters 0x80-0xBF in the
        # game's charmap) says the game has started
        "started": 0x80 <= name0 <= 0xBF,
        "map": mem[W_CUR_MAP], "map_name": MAPS.get(mem[W_CUR_MAP]), "x": mem[W_X], "y": mem[W_Y],
        "party_count": n, "levels": [mem[W_PARTY_MONS + 44 * i + 0x21] for i in range(n)],
        "badges": bin(mem[W_OBTAINED_BADGES]).count("1"), "badge_bits": mem[W_OBTAINED_BADGES],
        "money": money, "bag": bag, "in_battle": mem[W_IS_IN_BATTLE],
        "owned": sum(bin(mem[W_POKEDEX_OWNED + i]).count("1") for i in range(19)),
    }


def _map(f, name):
    return f["started"] and f["map_name"] == name


# (id, description, test over (facts, the grader's sticky history)). Ordered: progress is the furthest one reached.
MILESTONES: list[tuple[str, str, Any]] = [
    ("intro_done", "past the intro, standing in Red's room", lambda f, h: _map(f, "REDS_HOUSE_2F")),
    ("left_house", "out of the house, in Pallet Town", lambda f, h: _map(f, "PALLET_TOWN") and "intro_done" in h),
    ("starter", "has a starter Pokemon", lambda f, h: f["started"] and f["party_count"] >= 1),
    ("route_1", "left Pallet Town with a starter", lambda f, h: _map(f, "ROUTE_1") and f["party_count"] >= 1),
    ("viridian", "reached Viridian City", lambda f, h: _map(f, "VIRIDIAN_CITY")),
    ("parcel", "has Oak's Parcel", lambda f, h: f["started"] and ITEMS["OAKS_PARCEL"] in f["bag"]),
    ("pokedex", "delivered the parcel (it left the bag)", lambda f, h: "parcel" in h and ITEMS["OAKS_PARCEL"] not in f["bag"]),
    ("forest", "entered Viridian Forest", lambda f, h: _map(f, "VIRIDIAN_FOREST")),
    ("pewter", "reached Pewter City", lambda f, h: _map(f, "PEWTER_CITY")),
    ("badge_1", "Boulder Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x01),
    ("mt_moon", "entered Mt. Moon", lambda f, h: _map(f, "MT_MOON_1F")),
    ("cerulean", "reached Cerulean City", lambda f, h: _map(f, "CERULEAN_CITY")),
    ("badge_2", "Cascade Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x02),
    ("vermilion", "reached Vermilion City", lambda f, h: _map(f, "VERMILION_CITY")),
    ("hm01", "has HM01 Cut", lambda f, h: f["started"] and ITEMS["HM01"] in f["bag"]),
    ("badge_3", "Thunder Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x04),
    ("rock_tunnel", "entered Rock Tunnel", lambda f, h: _map(f, "ROCK_TUNNEL_1F")),
    ("lavender", "reached Lavender Town", lambda f, h: _map(f, "LAVENDER_TOWN")),
    ("badge_4", "Rainbow Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x08),
    ("silph_scope", "has the Silph Scope", lambda f, h: f["started"] and ITEMS["SILPH_SCOPE"] in f["bag"]),
    ("poke_flute", "has the Poke Flute", lambda f, h: f["started"] and ITEMS["POKE_FLUTE"] in f["bag"]),
    ("badge_5", "Soul Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x10),
    ("badge_6", "Marsh Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x20),
    ("badge_7", "Volcano Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x40),
    ("badge_8", "Earth Badge", lambda f, h: f["started"] and f["badge_bits"] & 0x80),
    ("victory_road", "entered Victory Road", lambda f, h: _map(f, "VICTORY_ROAD_1F")),
    ("indigo", "reached the Indigo Plateau", lambda f, h: _map(f, "INDIGO_PLATEAU")),
    ("lorelei", "beat Lorelei (reached Bruno's room)", lambda f, h: _map(f, "BRUNOS_ROOM")),
    ("bruno", "beat Bruno (reached Agatha's room)", lambda f, h: _map(f, "AGATHAS_ROOM")),
    ("agatha", "beat Agatha (reached Lance's room)", lambda f, h: _map(f, "LANCES_ROOM")),
    ("lance", "beat Lance (reached the Champion's room)", lambda f, h: _map(f, "CHAMPIONS_ROOM")),
    ("hall_of_fame", "beat the Champion: Hall of Fame", lambda f, h: _map(f, "HALL_OF_FAME")),
]


class Grader:
    """Sticky milestones over a run. update() as often as you like; report() any time."""

    game = "pokemon-red"

    def __init__(self):
        self.reached: dict[str, int] = {}      # milestone → the update count when first reached
        self.updates = 0
        self.last: dict[str, Any] = {}

    def update(self, mem, when: int | None = None) -> list[str]:
        """Returns the milestones newly reached by this state."""
        self.updates += 1
        f = facts(mem)
        self.last = f
        new = []
        for mid, _, test in MILESTONES:
            if mid not in self.reached and test(f, self.reached):
                self.reached[mid] = self.updates if when is None else when
                new.append(mid)
        return new

    def progress(self) -> float:
        """Furthest milestone reached, as a fraction of the list (the harness normalises against random and a human)."""
        idx = [i for i, (mid, _, _) in enumerate(MILESTONES) if mid in self.reached]
        return (max(idx) + 1) / len(MILESTONES) if idx else 0.0

    def report(self) -> dict[str, Any]:
        return {"game": self.game, "reached": [m for m, _, _ in MILESTONES if m in self.reached], "when": dict(self.reached),
                "progress": round(self.progress(), 4), "milestones": len(MILESTONES), "facts": self.last}


def matches(rom_title: str) -> bool:
    return rom_title.strip().upper() in ("POKEMON RED", "POKEMON BLUE")
