# The long-horizon agent, end to end

`ARCHITECTURE.md` describes the pack pipeline: one frame in, one typed action out, the way anygame plays a short
game. This document is the layer built on top of it for long games (Pokemon Red, Aevilia, the held-out Game Boy
games): how the agent finds its way around a world much bigger than one screen, what it learns while it plays, and
what would carry over to an agent that sees only the screen.

## No training anywhere

No model is trained or fine-tuned. Jev is a small fixed model, and it is only ever asked one kind of question:
given a short description of the game and a handful of candidate presses, which one. Everything else is machinery
around that question.

## The structure

```
emulator ─▶ screen + RAM ─▶ discovery (which bytes are position, map) ─▶ place book + world memory
                                                                              │
     press ◀─ check the result ◀─ Jev picks ◀─ options (routes, doors, menu entries) ◀─ goals (Azure chat model)
                                         ▲
                     save-state lookahead, stall detector (no spend)
```

| layer | what it does | where |
|---|---|---|
| **emulator** | the screen and the raw work RAM, save states, presses | `device/pyboy.py` |
| **discovery** | works out on its own which bytes are the player's position and the map, by watching what changes when it presses buttons; the published RAM map is used only by the grader | `discover.py`, `ramscan.py` |
| **text** | each 8×8 glyph learned once (one chat-model look, then cached in a per-game font book); every later line read exactly | `perceive/tiletext.py` |
| **places** | which place the player is in, from the discovered map byte and position: maps that join without a door, stairs, doors taken, names that are only noise | `places.py`, `docs/places.md` |
| **world memory** | tiles stood on, walls, doors and warps per place, what characters said and where; saved in checkpoints | `perceive/world.py`, `memory.py`, `landmarks.py` |
| **goals** | a chat model on Azure reads the dialogue and the world memory and writes a small checkable goal (heal, find somewhere new, go to the shop), only when a call is worth it | `goals.py`, `goalgate.py` |
| **options** | a few concrete candidates per step: a route to the goal, an unexplored door, a menu entry, a fight move | `perceive/world.py`, `perceive/menu.py`, `battle.py`, `motion.py` |
| **decider** | Jev picks one option; the result is checked in memory before the next press | `jev.py`, `sensors.py` |
| **lookahead** | menu choices and fight moves played out from a save state until the game asks again, so the option text says what each did | `playout.py`, `chains.py` |
| **safety nets** | the stall detector drops options that keep returning to the same screens; upkeep watches a falling number and goes back to where it last refilled | `stuck.py`, `upkeep.py`, `heading.py` |
| **audit** | at each decision, replays Jev's pick and the top-ranked stand-in pick from a save state and records which did better | `audit.py` |
| **grader** | milestones from the game's published RAM map, for scoring only: no stall check or heuristic may read it | `graders/` |

Nothing below the grader knows the game. A rule earns its place by being written for any game and then measured on
Pokemon Red and on Aevilia, and re-checked on held-out games it has never seen.

## Two loops of improvement

**Inside a run** the agent learns the game's bytes, its font, its map and its places, so it plays better the longer
it runs. Checkpoints keep it: a resumed run keeps its discovery evidence, its place book and its world memory.

**Across runs** the improvement is engineering. A stall is replayed on its save at no model cost, the general rule
that caused it is found and fixed, and the fix is re-checked on the held-out score so it is not Pokemon-specific.
The Blue's house stall at tick 45,700 is a typical case: two options shared one plan that went back to its own
tile, and a door was recorded whose two ends were the same tile. Both were general rules, both were fixed, and both
have tests.

## Known tiles and new ones

On a Game Boy the screen is a grid of 8×8 tiles drawn from a fixed set, so a tile can be looked up exactly: hash its
pixels, look the hash up in the game's book. A hash with a label is known and costs nothing. A hash with no entry
has never been seen: it goes to the chat model once, with the surrounding screen for context, and the label is
cached. That is what tiletext does for letters today, and the same lookup works for any tile or sprite.

A lookup is not enough when a label exists but is wrong, because the chat model guesses from one look. The rule
that handles it has three states rather than two:

- **unseen**: no label; ask once.
- **labelled**: a label from one look, not yet confirmed.
- **verified**: the game confirmed it. A tile labelled walkable that the player walked onto, a word that matched
  the dialogue memory, a door that changed the map.

A label goes back to the chat model when its consequence fails (a "walkable" tile that blocked three presses), or
when the stall detector fires on a stretch where most tiles are unverified. So the expensive model is called on
first sight and on contradiction, and nothing else.

Off the emulator, tiles are not exact: "same tile" becomes a nearest match on a perceptual hash with a threshold,
and that is where it gets uncertain. The same split applies to decisions: the audit replays a decision type under
Jev and under a stand-in, and keeps Jev only where its picks measurably differ.

## What carries over to a screen-only agent

For "pixels in, presses out, any game on a computer", the parts on top carry over: options and controllers, world
memory, chat-model goals, the stall detector, the audit. They are about a third of the problem.

The foundation does not. Everything the agent perceives comes from the emulator: tile ids, sprite tables, memory
bytes, save-state lookahead. None of that exists on a real screen. Perception and "what happens if I press this"
are solved today by reading the machine.

Jev is not the part that learns. It cannot see and cannot be retrained, and so far its picks get compiled away: on
Go the stand-in beat it once playouts were in, and the held-out score is within noise of random for both. A fast
"doer" earns its place only if the slow model can keep teaching it, and the tile book is that: a lookup table
distilled from the chat model.

What one person can build is the inference-time version of the recipe that works in the field (pretrained vision,
a policy trained on large amounts of human play, then refinement):

- **Add** a pixel perception layer that turns a frame into a structured state (text, menus, entities, player),
  with the novelty cache above in front of it.
- **Add** press-and-watch on pixels in place of RAM discovery: learning what a button does from the screen is the
  same trick on a worse signal.
- **Add** a retrainable small model, or compiled rules, as the fast path.
- **Add** a screen graph as the world model: fingerprinted screens as nodes, presses as edges.
- **Keep** the RAM scan and the tile grid only as the grader and as an emulator-only shortcut.
- **Keep** the held-out score. "Within noise of random" is the honest number, and the one to move.

That reaches slow games at a few dollars an hour, and reflex games only where the fast path has learned them. The
first experiment is the perception layer with its cache on the existing held-out games, because it decides whether
the whole route is affordable.
