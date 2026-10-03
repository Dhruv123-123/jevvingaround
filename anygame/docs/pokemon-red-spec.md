# Pokemon Red, start to finish: spec

Status: draft 1, 2026-10-03. Branch `claude/anygame-pokemon-red-zlo39b`, stacked on `claude/anygame-integration` (PR #3).

## Why this game

Every game anygame has beaten so far (snake, Tetris, 2048, Go, the Chrome dino, Connect Four) is short-horizon:
the whole state fits on one screen, a good move can be judged from that screen, and a game lasts minutes. On
Tetris, 2048 and Go the compiler's ranking is so strong that Jev takes the top pick every time, so those games
measure the compiler, not the decider. Polishing them further is overfitting.

Pokemon Red is the opposite on every axis: tens of hours, most of the world off-screen, menus and dialogue
between every meaningful choice, goals that take hours to pay off (badges, HMs, the Elite Four), and a party whose
state carries across the whole game. If anygame can finish it with one pack, the architecture is general. If it
can't, the places where it breaks are the parts "any game" still lacks.

## What "start to finish" means

From power-on with no save file to the Hall of Fame screen after beating the Champion, in one continuous run with
no human input and no hand-made save states along the way. The run may save and reload its own states (that is
what a player does when they save before a gym), and the harness may restart from the run's last save if the
emulator process dies. Losing a battle is part of the game (you wake up at the last Pokemon Center) and does not
end the run.

## Milestones

Each milestone is a RAM condition, so progress is measured, not judged. Map ids and flags come from the pret/pokered
disassembly; the ones marked "verify" are checked against the ROM as soon as it is available.

| # | Milestone | Condition (RAM) |
|---|---|---|
| 0 | Past the intro: names chosen, standing in Red's room | map = REDS_HOUSE_2F (0x26) and the overworld has control |
| 1 | Out of the house | map = PALLET_TOWN (0x00) |
| 2 | Has a starter | party count (0xD163) >= 1 |
| 3 | Beat or lost to the rival in Oak's lab, left Pallet Town | party >= 1 and map = ROUTE_1 (0x0C) |
| 4 | Oak's Parcel delivered, has a Pokedex | event flag (verify) |
| 5 | Viridian Forest crossed | map = PEWTER_CITY (0x02) |
| 6 | Boulder Badge | badges (0xD356) bit 0 |
| 7 | Mt. Moon crossed | map = ROUTE_4 east side / CERULEAN_CITY (0x03) |
| 8 | Cascade Badge | badges bit 1 |
| 9 | S.S. Anne, HM01 Cut | bag has HM01 (verify) |
| 10 | Thunder Badge | badges bit 2 |
| 11 | Rock Tunnel crossed | map = LAVENDER_TOWN (0x04) |
| 12 | Rainbow Badge | badges bit 3 |
| 13 | Rocket Hideout, Silph Scope | bag has Silph Scope (verify) |
| 14 | Pokemon Tower, Poke Flute | bag has Poke Flute (verify) |
| 15 | Soul Badge (Safari Zone, HM03 Surf, HM04 Strength first) | badges bit 4 |
| 16 | Silph Co., Marsh Badge | badges bit 5 |
| 17 | Volcano Badge (Cinnabar, Secret Key) | badges bit 6 |
| 18 | Earth Badge | badges bit 7 |
| 19 | Victory Road crossed | map = INDIGO_PLATEAU (0x09) |
| 20 | Elite Four: Lorelei, Bruno, Agatha, Lance | event flags (verify) |
| 21 | Champion beaten, Hall of Fame | map = HALL_OF_FAME (0x76) |

Secondary measures logged per milestone: in-game time, wall time, decider calls and cost, battles won and lost,
whiteouts, party levels, steps walked, and how often the run was stuck (no milestone progress for N game-minutes).

## What Jev can carry, and what the harness must supply

Jev is a fast, non-generative decider: one state in, typed answers out, about 200–400 ms, about $0.00005 per call
at Pokemon-sized states. It never sees earlier calls and is never retrained. Each call picks among options it is
shown. That is exactly right for "which of these four moves", "which of these three paths", "fight or run". It
cannot, on its own:

- **see the world off-screen** or remember where it has been. The harness must keep a map memory.
- **plan over hours** ("get Surf before Fuchsia's gym is reachable"). The harness must hold a goal list and the
  current goal, and show Jev only the next step of it.
- **read the game reliably from pixels at scale** (text, HP bars, menus, cursor). The harness reads RAM.
- **press 40 buttons to get through a dialogue.** Routine screens must be handled by rules, without a call.

So the split is: the harness turns the game into a short list of meaningful options with their consequences
(the same idea as Tetris landings and Go playouts, at a larger scale), and Jev picks one. The harness parts are
general; only the RAM map, the goal list and a few game facts are Pokemon-specific.

## Architecture

```
 PyBoy (pyboy://)                 pack.yaml (pokemon-red)
  frames ─────────────────┐        ram:      RAM map           (Pokemon-specific data)
  RAM ── device.state() ──┤        read:     json reads of it  (general)
  buttons, holds  ◄───┐   │        auto:     routine screens → a key, no call   (general)
  save/load states    │   │        goals:    ordered milestones + targets        (Pokemon-specific data)
  game clock          │   ▼        read world: map memory + navigator           (general)
                      │  Agent.step ── reads ─ situation ─ options ─ Jev picks ─ act
                      └────────────────────────────────────────────── macro (a path, a menu sequence)
```

### 1. Emulator device (general, any Game Boy / Game Boy Color ROM)

`pyboy://<rom>` already existed for the 2048gb homebrew. It gains:

- **RAM state.** The pack's `ram:` section names addresses and how to decode them: `u8`, `u16` (big/little
  endian), `bcd` (money), `bits` (badges, as a count and a list), `bytes` (an array), `text` with a charmap
  (names, the text on screen read from the tile map). `device.state()` returns the decoded dict every tick, and
  the existing `json` reads consume it, exactly as the browser games that publish their state do.
- **Game clock.** `?clock=game` (the default for RPG packs) advances the emulator only when anygame acts or
  waits, so the game is frozen while Jev thinks and runs as fast as the CPU allows otherwise (PyBoy runs a few
  thousand frames a second headless). `?clock=wall` keeps the old real-time behaviour for action games.
- **Holds and waits.** A button can be held for N frames; `wait` runs N frames. Walking one tile in Pokemon is
  a ~16-frame hold.
- **Save states.** `save_state(path)` / `load_state(path)`, and `?state=<file>` to start from one. The run saves
  at every milestone, so a crash or a regression costs one milestone, not the run, and a phase can be tested
  from its start.
- **Screenshots** stay for Jev's optional view, the HUD and debugging; they are not the state source.

### 2. RAM map (Pokemon-specific data, general mechanism)

From pret/pokered `wram.asm`: map id 0xD35E, y 0xD361, x 0xD362, party count 0xD163, party species 0xD164,
party structs from 0xD16B (44 bytes each: HP, level, max HP, moves, PP), badges 0xD356, money 0xD347 (3 bytes
BCD), in-battle 0xD057, enemy species/HP/level around 0xCFE5, player's battle mon around 0xD014, menu cursor
0xCC26 and max item 0xCC28, the screen's tile map 0xC3A0 (20x18), event flags from 0xD747, bag 0xD31D. These are
checked one by one against the ROM before they are trusted (a short script prints each while a scripted
sequence of known actions runs).

For games without a public RAM map, `anygame ramscan` (new) finds position and map bytes by itself: it walks the
player in each direction and keeps the bytes that change by +1/−1 in step with the moves. That is how the
homebrew stand-in (Aevilia) was mapped, and it is the general path for "any game".

### 3. Situations and auto rules (general)

At any tick the game is in one situation, decided from reads: overworld, dialogue, menu, battle, transition.
The pack's `auto:` list maps routine situations to a key without asking the decider: dialogue → A, a
"yes/no" that the goal already answers → A, a transition → wait. Jev is only asked where there is a choice.
In Pokemon that cuts calls by roughly 10x, since most frames are text.

### 4. World memory and navigator (general, for any tile-based game)

A derived read, `kind: world`, takes the position reads (map, x, y) and keeps, across the whole run:

- every tile visited, per map;
- **blocked edges** learned by trying: a step that did not change the position, outside dialogue and battle,
  is a wall or an NPC (NPC blocks expire, walls do not);
- **warps** learned by trying: a step that changed the map records (map, x, y, direction) → (new map, x, y);
- the **frontier**: visited tiles with an untried neighbour.

Each tick it offers the decider a handful of options, each with its consequence: "walk to the goal target (12
steps, path known)", "explore the nearest frontier north (3 steps)", "take the unvisited door at (5,3)", "talk
to what is in front". Each option is a key macro (the path), played in one go, the way Tetris landings are. A
step that bumps re-plans on the next tick. Paths come from breadth-first search over known-open and unknown
tiles (optimistic: unknown is assumed open until proven blocked).

This is what makes a 40-hour game a sequence of short decisions: Jev picks among 3–6 options every few seconds
of game time, and the memory, not Jev, knows the world.

What it does not do yet: ledges (one-way edges, learned the same way as walls, but in one direction), the
Rocket hideout spinner tiles (a step that moves you several tiles: recorded as a warp within the map, which the
same mechanism already handles), strength boulders, surf (water is blocked until the party has Surf and
the goal says to use it), and darkness in Rock Tunnel (position still works; only the screenshot is dark).

### 5. Goals (Pokemon-specific list, general mechanism)

The pack's `goals:` is the ordered milestone list above, each with a `done:` condition over reads, an
`instruction` shown to Jev as the current goal, and optional `target:` (a map and tile, or a map to reach)
for the navigator. Goals are sticky: once done they stay done (saved with the run). The current goal is the
first not done. A goal with no known target falls back to exploration, biased toward unvisited warps.

Where the goal list comes from: written once by hand from the walkthrough structure (about 60 lines of YAML for
the whole game), with the Azure chat model available to draft sub-goals when a goal stalls (for example, "find
the Silph Scope" → "the Rocket hideout is under the Celadon Game Corner; the switch is behind the poster").
That drafting is optional and is not on the critical path.

### 6. Battles (Pokemon-specific facts, general shape)

In battle the options are the four moves, switching to each party member, an item, and run, each with its
consequence computed from RAM and the ROM's own tables: move power, type, PP left, type effectiveness against
the enemy (the type chart is a 15x15 table in the ROM), expected damage as a fraction of the enemy's HP, our HP
fraction, whether running is allowed. Ranked best first, the way 2048 swipes are, and Jev picks. Menu
navigation (FIGHT → move 2) is a macro, not a decision.

Outside battle the same treatment covers healing (go to the Pokemon Center when the party's HP fraction is low
— a goal that preempts the milestone goal), buying Poke Balls and potions, and catching (throw a ball when the
enemy's HP is low and the party has a free slot).

### 7. How Jev is called, and how often

One call per decision: per path chunk in the overworld, per turn in battle, per real menu choice. Dialogue,
transitions and walking along a chosen path make no calls. Expected rate: 0.5–1 call per game-second of
meaningful play.

State per call: the play paragraph (~250 tokens), the situation and its reads (~300), the current goal (~50), the
options with their consequences (~300). About 1,000–1,500 input tokens. At Jev's price ($0.042 per million input
tokens) that is about $0.00005 per call.

| | calls per game-hour | cost per game-hour |
|---|---|---|
| overworld-heavy | ~1,500 | ~$0.08 |
| battle-heavy (grinding) | ~3,000 | ~$0.15 |
| whole game (est. 40–80 game-hours with grinding) | 80k–200k | **$4–12** |

With the game clock the emulator waits for Jev, so wall time is roughly calls x latency: 100k calls x 0.35 s ≈ 10
hours. The offline stand-in (takes the top-ranked option) and random deciders run the same pipeline at no cost.

### 8. Which parts are Pokemon-specific

| Part | Specific to Pokemon? |
|---|---|
| PyBoy device: RAM state, game clock, holds, save states | No: any Game Boy ROM |
| `ram:` decoding (u8, u16, bcd, bits, text + charmap) | No |
| `anygame ramscan` | No |
| `auto:` rules for routine screens | No |
| `world` read: map memory, blocked edges, warps, frontier, paths | No: any tile-based game with a position |
| `goals:` mechanism (ordered, sticky, with targets) | No |
| Battle option ranking | Shape general ("options with computed consequences"), facts Pokemon (type chart, move table) |
| The RAM addresses, charmap, map ids | Yes |
| The goal list | Yes |
| The play paragraph | Yes |

## Known hard parts

- **The intro and naming.** The naming screens are a keyboard grid. The pack picks the preset names (RED, BLUE)
  from the menu with an `auto:` rule; no free typing needed.
- **Oak stops you leaving Pallet Town** and walks you to the lab. Scripted movement looks like a stuck position to
  the world memory; steps made while the game moves the player must not be learned as walls (learning is
  paused while a script or dialogue is active).
- **Viridian Forest, Mt. Moon, Rock Tunnel, Victory Road**: mazes with trainers. The navigator handles mazes; the
  cost is steps, and trainer battles interrupt paths (battle situation takes over, the path re-plans after).
- **Rock Tunnel is dark** without Flash: irrelevant to RAM position, so it is easier for us than for a human.
- **Rocket Hideout spinner floors** move the player several tiles per step. Recorded as warps within the map; the
  BFS uses them. Expect a lot of trial and error the first time through.
- **Silph Co. and Sabrina's gym warp pads**: a maze of teleporters. Same warp learning; the gym is 9 rooms with
  4 pads each, so worst case ~36 tries. Fine for a machine, slow for a human.
- **Safari Zone**: a step limit (500) and a time-limited goal (Surf and the Gold Teeth). If the steps run out
  you are put outside; the goal stays open and the navigator's memory survives, so the second entry is shorter.
- **HMs in the field**: Cut a tree, Surf on water, Strength on boulders. Each is an option the navigator offers
  only when the party has the HM and the move is taught; teaching an HM is a menu sequence (macro).
- **The Elite Four**: five battles in a row with no healing. Needs a party around level 50–55. This is where
  grinding happens: a "train" goal (fight wild Pokemon on a route until the lead's level reaches N) preempts the
  next milestone when the level gap is too big. Grinding is cheap in calls (one per turn) but long in game time.
- **Party management**: catching, switching the lead, using items, the PC box when the party is full. Every one is
  a menu macro with a choice at the top; the choice is Jev's.
- **Losing**: whiteout puts you in the last Pokemon Center with half the money. The memory survives; the goal
  stays the same. A goal that loses three times in a row triggers the train goal.
- **Softlocks the agent can make**: releasing Pokemon, tossing key items, saving in a bad place. Release and toss
  are excluded actions in the pack; the in-game save is never used (emulator save states instead).

## Phased plan

| Phase | Work | What it proves |
|---|---|---|
| 0 | Emulator device with RAM state, game clock, save states; `ramscan`; tested on Aevilia (free homebrew RPG) | The adapter is general and fast; RAM beats pixels for state |
| 1 | `auto:` rules, `world` read, `goals:`; Aevilia from new game to leaving the first map, measured | The long-horizon layer works on a game it was not written for |
| 2 | Pokemon Red pack: RAM map verified, intro, Red's room to Route 1 with a starter (milestones 0–3) | Intro, scripted events, first battle |
| 3 | Battle option ranking (moves, type chart, switching, run); healing goal | Battles are decided, not mashed |
| 4 | Viridian to the Boulder Badge (milestones 4–6) | Forest maze, trainers, a gym: one full loop of the game |
| 5 | Through Cerulean, Vermilion, Lavender (7–12), catching and party management | Hours-long runs without getting stuck; HMs |
| 6 | Rocket Hideout, Tower, Safari, Silph, Saffron (13–16) | The hard navigation cases: spinners, warp pads, step limits |
| 7 | Cinnabar, Viridian gym, Victory Road, Elite Four (17–21), with a training goal | The full game |

Each phase ends with a measured run: milestones reached, game time, wall time, calls, cost, stuck time. A phase is
done when two runs in a row reach its last milestone from the previous phase's save state.

## Risks and open questions

- **The ROM is the user's.** The repo never contains or downloads a commercial ROM. The run reads it from
  `/mnt/project-files/roms/` (or any path given on the command line).
- **How much is Jev doing?** On Tetris and Go the ranking decided everything. In Pokemon the risk is the same: if
  the navigator and the battle ranking are good, the stand-in that takes the top option may finish too. That is
  a fine outcome for "any game", and the comparison (Jev vs. stand-in vs. random on the same milestones) is
  reported at every phase, so it stays honest where Jev's judgment matters.
- **Jev is blocked** while the OpenRouter account has no credit. Everything up to phase 2 runs on the offline
  deciders; the Jev comparison slots in when credit returns.
- **Event flags and item ids** marked "verify" need the ROM.
