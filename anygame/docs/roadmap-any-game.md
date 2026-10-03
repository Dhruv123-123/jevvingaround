# Roadmap: from seven small games to any game

Written 2026-10-03 against `claude/anygame-integration` (PR #3's branch). Companion threads: "Pokemon Red start to
finish" builds the first long demo (spec: `pokemon-red-spec.md` in the project files); "Where the design breaks"
attacks the current design. This document is the whole picture: what "any game" means, what is missing, in what
order to build it, and what Jev's job is in the result.

## The short version

1. Everything anygame has beaten so far is short-horizon, and every win came from reads and compiler features
   written by hand for that one game. On Tetris, 2048 and very likely Go, Jev takes the compiler's top pick every
   tick, so those results measure the compiler. The parts that are already general are the devices, the tick, the
   rules, the tasks and the learn loop's checks.
2. The biggest unlock is **perception that comes from the platform instead of the game**: an emulator already
   knows the tile map, the sprites, the RAM and the text, for every game on that console. PyBoy exposes all of it
   (`game_area`, `tilemap_background`, sprites, `memory`, `symbol_lookup`, `save_state`). Measured here: a tile
   read costs microseconds, a savestate 20 ms to save and 7 ms to load, and the emulator runs about 1,000x real
   time with rendering off. The current Game Boy pack reads 2048 by OCR at about 0.7 s a frame.
3. The second unlock is **options**: actions that run for many frames under a compiled controller (walk to a door,
   page through a dialog, pick a menu item by name) so Jev decides at decision points, not every frame. That is
   what lets a 340 ms decider play a 30-hour game, and it keeps Jev the one making the choices.
4. The third is **a world memory and a goal layer**: a map of where the player has been, what is left to explore,
   and a current goal written as a verifiable task (the `tasks:` mechanism already exists). A chat model writes
   goals rarely; it never presses buttons.
5. Build these on the Game Boy first, with Pokemon Red as the proving ground, then prove they transfer by playing a
   second game nobody tuned for. Stop tuning the small games and stop porting every new layer to the extension.

## 1. Where anygame is today

The tick (`anygame/loop.py: Agent.step`): device frame → fingerprint → classify screen → reads → derived reads →
questions → one Jev call → rules → one input. A pack (YAML) names the zones, the reads, the actions, a paragraph,
the questions and the rules. Jev never sees pixels; it answers typed questions (choice, noul, score) about a JSON
state.

Measured facts this roadmap leans on (logs in the project files):

| fact | number | source |
|---|---|---|
| Jev latency | median 340 ms, p90 about 540 ms | 2,500 calls across 2048, dino, Go logs; real-web-trial.md (336 ms over 834 calls) |
| Jev input per call | 1,000 tokens (2048) to 2,500 (dino) | same logs, `tokens` field |
| Jev cost per call | $0.00004 to $0.0001 at $0.042 per million input tokens | `anygame/jev.py` |
| Perception per tick | 1 to 3 ms on a grid from pixels, 0.7 s for OCR over a 4x4 Game Boy grid | logs, `packs/2048gb/pack.yaml` |
| PyBoy tile read | microseconds; 32x32 tile ids from `game_area()` | measured for this roadmap on `roms/2048gb` |
| PyBoy savestate | 20 ms save, 7 ms load, 139 KB | measured for this roadmap |
| PyBoy speed, render off | 600 frames in 10 ms | measured for this roadmap |

What each result really rests on:

| game | result | what made it work | general or per-game |
|---|---|---|---|
| Snake | deaths 7/8 → 0/8 | `reflex:` lines, `margin` read | reflex is general; reads are hand-written |
| Tetris | game overs 7/8 → 0/8, lines 46 → 158 | `tetris` landing read + `lookahead: true` | per-game compiler feature |
| 2048 | median 2104 → 4626 | two-move lookahead ranking | per-game compiler feature |
| Go 9x9 | Jev 3/16 → 9/16; top-pick stand-in with re-rank 14/16 | `go` read: ladders, playouts, re-rank | per-game; 445 lines in `perceive/go.py` |
| Dino | Jev median about 850 vs 58–124 | `gap` tracker, frame-timed jumps, 30 fps stream | per-game reads, general timing features |
| Connect Four, tic-tac-toe | 8/8; 5W 7T 0L after the learn loop | hand packs; learn loop found the turn gate | mixed |
| Real web sites | tic-tac-toe, snake, dino at third-party URLs | hand-written packs, page state used only to grade | per-game |

The learn loop (PR #5, #6) is the most general piece: it diagnosed and rediscovered the three hand fixes (turn
gate, Tetris lookahead, snake reflex) with the fixes removed. It could not build the Go re-rank because rewrites
can only recombine read kinds and compiler options that already exist in code.

What exists but has never been proven on a real game: `device/pad.py` (virtual gamepad), `device/adb.py` (Android),
`device/window.py` and `device/screen.py` on a native game, `perceive/vocab.py` (YOLO-World), the author writing a
working pack for a game with moving objects (the `flappybird-io` pack cannot see the bird or the pipes), the
Clash Royale pack, `mouse_move` for a camera.

## 2. What "any game" means

Five axes. A game is a point on each; a capability is general when it works across a whole axis value without a
per-game pack edit.

| axis | values |
|---|---|
| horizon | reflex (sub-second deaths), tactical (one move to a few dozen), campaign (hours, many goals) |
| state access | page state (DOM, JS object), emulator (tiles, sprites, RAM), screen pixels only, native app memory |
| input | keys, mouse clicks, mouse look, gamepad, touch |
| platform | browser, retro console emulator, desktop, Android, modern console (capture card) |
| players | solo, versus a built-in AI, online versus people |

The classes that matter, with a representative game and the honest status today:

| class | representative | today | evidence |
|---|---|---|---|
| browser, reflex, keys | Chrome dino, snake | **plays**, with hand-written reads | dino-reflex.md, snake-reflex.md |
| browser, puzzle/board, clicks | 2048, Go, tic-tac-toe | **plays well**, but the compiler plays | 2048-lookahead.md, go-playout-rerank.md |
| browser, no state access, unknown game | any new .io game | **no**: author cannot see moving objects | flappybird-io pack, 2026-10-01 assessment |
| emulator, turn-paced, campaign | Pokemon Red | **no**: no goals, no memory, no map, no menus | nothing beyond one frame + 6 recent actions in the state |
| emulator, reflex, 2D | Super Mario Land | **no** reads; reflex and timing features exist | none |
| desktop, screen only, keys and mouse | Stardew Valley, Balatro | **untested**; devices exist | `device/screen.py`, `window.py`, `test_desktop.py` |
| desktop 3D, mouse look | Minecraft | **no**: no 3D perception, `mouse_move` untested | none |
| Android, touch | Clash Royale | **untested**; pack and device exist, never run | `packs/clash-royale`, `device/adb.py` |
| gamepad-only native or console | any Switch/PS game via capture | **untested**; uinput/ViGEm pad exists | `device/pad.py` |
| online versus people | chess.com, ranked anything | **out of scope** (terms of service, anti-cheat); say so plainly | none |

So today anygame covers one and a half of ten classes, and only with a human writing the reads.

## 3. The shape of an agent that can play any game, and Jev's place in it

Three layers, each on its own clock. The test of the design is that the middle layer, Jev, still makes the game
decisions.

```
deliberate  (chat/vision model, rare: new screen, new tile, stall, milestone)   Azure only
   writes: tile and object labels, pack modes, the next goal as a verifiable task, a diagnosis after a stall
   never:  presses a button, picks a move in a battle, picks a menu item
        │ goal (task with a done condition)        ▲ world memory summary, stall evidence
        ▼                                          │
decide      (Jev, at decision points, 340 ms, ~$0.0001)
   picks:  which option (explore frontier B, enter door C, talk to NPC D), which move, which menu entry,
           heal or push on; beliefs (noul) that rules turn into guards
        │ option + parameter                       ▲ candidates ranked and annotated by the compiler
        ▼                                          │
execute     (compiled controllers and reflexes, every frame, no model)
   runs:   path to a tile, mash through dialog, scroll a menu to a named entry, reflex dodges; reports done,
           blocked or interrupted (a battle started, a dialog opened)
```

What a fast, non-generative decider can carry: choosing among up to a few dozen named, annotated candidates;
judging yes/no beliefs; scoring. Go shows it can choose among dozens of board cells when the compiler annotates the best ones, and the
dino shows it can work asynchronously next to a reflex. What it cannot carry: generating a plan or text, reading
pixels, remembering anything not in the state it is sent, search or arithmetic. Those sit around it: the compiler
does search and arithmetic, the world memory remembers, the deliberate layer writes goals.

Three rules keep this from turning into a general agent that ignores Jev:

1. The deliberate layer's only outputs are labels, pack edits and tasks with a `done` condition over reads. It has
   no action channel. Enforce it in code: the planner's output is validated by `pack.check_tasks`, the way the
   setter's is today.
2. Every run reports three shares: decisions made by Jev, by a controller with no choice to make, and by a model
   in the deliberate layer (counting the VLM fallback). A campaign run where the deliberate layer makes more than
   a few percent of decisions is a failed run, whatever it reaches.
3. Every demo is also run with the top-pick stand-in (`test/clm_stub.py`) in Jev's place. If the stand-in does as
   well, the compiler is doing the playing; report that, as the Go and Tetris reports already do. Jev earns its
   place where candidates are close and judgment matters: which frontier to explore, when to heal, whether a
   battle is worth fighting.

## 4. The gaps, ordered by how much of the space each unlocks

Effort is in thread-days (one Claude thread working). Each gap names the seam in the code where it attaches.

### G1. Perception from the platform, not the game (unlocks every emulated game)

- **Build:** on `device/pyboy.py`, a `state()` that returns platform facts every tick: the visible tile ids
  (`game_area`), the window layer, on-screen sprites with tile ids and positions, and a per-game RAM map when one
  is supplied (a pret-style `.sym` file through PyBoy's `symbol_lookup`, or a small YAML of named addresses). New
  read kinds in `perceive/` and `pack.READ_KINDS`: `tiles` (a matrix of tile ids, presented like any grid read),
  `sprites`, `ram` (named addresses with a type: byte, word, BCD, flag bit). The existing `json` read already
  consumes `device.state()`, so the RAM half may need no new read kind at all.
- **Tile vocabulary:** a game has a few hundred distinct tiles. Label each tile id once (walkable, wall, water,
  door, grass, text glyph, NPC) by asking the vision model with a crop, and cache the labels in the pack, the way
  `fallback.py` memoises screens. Collision can be learned without a model: the player walked onto it or did not.
- **Text:** Game Boy text is tiles. A per-game charmap (tile id → character) turns the window layer into strings
  for free; learn it once by OCR on each glyph tile, or take it from the disassembly when one exists.
- **Reuses:** `device.state()` path in `Agent.step`, `json`/`json_grid` reads, `fingerprint.py` for screen class,
  `fallback.py` memo for labels.
- **Done when:** on Pokemon Red, the walkable map from `tiles` + learned labels agrees with the RAM collision data
  on 95% of tiles over 30 minutes of play; on two other Game Boy ROMs (2048gb, plus one free homebrew), the same
  read and labeller run with no game-specific code.
- **Effort:** 3–5. **Depends on:** nothing. The Pokemon thread will build the RAM half for Pokemon; this gap is
  making it a platform layer rather than a Pokemon one.

### G2. Options: multi-frame actions with controllers (unlocks every campaign and every menu)

- **Build:** a new action kind `option` in `pack.py` and `Agent.act`: `{id: go_to, kind: option, controller: path,
  targets: <read>}`. While an option runs, `Agent.step` calls its controller each tick and skips Jev; the
  controller returns `running`, `done`, `blocked` or `interrupted` (a screen class change, a battle flag, a dialog).
  Controllers to start with: `path` (A* over the walkable map to a target tile, re-planning when blocked),
  `dialog` (advance text until the window closes or a choice appears), `menu` (move the cursor to a named entry
  and confirm), `press_until` (press until a read changes).
- **Candidates for Jev:** the targets are a compiled read that ranks and annotates options, exactly what
  `criteria_from` already does for 2048 (`Agent.questions`). Jev picks one; the controller executes it.
- **Reuses:** `macro`, `chunk`, `hold_ms`, `criteria_from`, the noop filter (a blocked target is not offered
  again), rules (`exclude`, `only`).
- **Done when:** Pokemon Red from a save in Pallet Town reaches Viridian City and back with fewer than 200 Jev
  decisions and no deliberate-layer call.
- **Effort:** 4–6. **Depends on:** G1 for the walkable map on emulated games.

### G3. World memory (unlocks campaigns and exploration)

- **Build:** a `WorldMemory` object owned by the Agent and saved with the run: per map, the tile grid seen so far,
  visit counts, warps found (from map-id changes), NPCs talked to, items picked up, dialog lines read, and the
  frontier (walkable tiles next to unseen ones). It is exposed as derived reads, so Jev sees a compact summary
  (current map, the top frontier and door candidates with distance and novelty, the last few dialog lines), and the
  deliberate layer sees the full graph.
- **Reuses:** derived-read machinery in `perceive/__init__.py`, history reads (`_prev`), `Bank` for persistence.
- **Done when:** after 2 hours of Pokemon, the map graph lists every visited map with correct warps (checked against
  RAM map ids), and a restart from a savestate reloads it.
- **Effort:** 3–4. **Depends on:** G1.

### G4. Goals, progress and stall recovery (unlocks long horizons)

- **Build:** a goal layer in a new `anygame/goals.py` beside `tasks.py`. The deliberate model is called on start, on
  each completed goal, and on a stall, with the world memory summary, the goals done, and the recent dialog text;
  it returns the next goal as a task (`done` over reads, e.g. `ram.badges gte 1`, `ram.map equals 0x36`). The
  active task already reaches Jev as `state["task"]` (`Agent._tasks_tick`). Progress signals: new tiles seen, new
  maps, event flags set, party levels, money. A stall is N decisions with no progress signal; it triggers the
  deliberate layer with the evidence (which options were tried, which were blocked).
- **Open question:** does the planner use what it already knows about the game? For a famous game it will. Run two
  settings and report both: named game, and game name withheld. The withheld number is the honest "any game" one.
- **Reuses:** `tasks.py` (verifiable tasks, setter prompt structure), `pack.check_tasks`, learn-loop diagnosis on
  the PR #6 branch (`diagnose.py`).
- **Done when:** Pokemon Red gets the first badge without a human edit to the pack after the run starts, with the
  deliberate layer under 5% of decisions.
- **Effort:** 4–6. **Depends on:** G2, G3.

### G5. Menus, dialog and text-driven play (unlocks RPGs, strategy, card games)

- **Build:** a generic menu read: the cursor position (a sprite or arrow glyph next to text) and the entries as
  strings, from G1's text decoding on emulators and OCR elsewhere. Dialog choices (yes/no, a shop list, a move list)
  become Jev questions whose criteria are the entry strings, annotated by the compiler where it can (move type,
  power, PP, effectiveness from a damage read).
- **Reuses:** `ocr.py`, `criteria_from`, G2's `menu` controller.
- **Done when:** Pokemon battles are won using the menu path only (no hard-coded button sequences) on the first ten
  trainer battles; the same read works on a second Game Boy RPG's menus unchanged.
- **Effort:** 3–4. **Depends on:** G1, G2.

### G6. Lookahead from savestates (a generic forward model for emulated games)

- **Build:** `Device.snapshot()` / `restore()`; on PyBoy these are `save_state`/`load_state`. A compiler read
  `branch` tries each candidate option from a snapshot for a fixed number of frames or decisions and annotates
  the candidates with the outcome (HP lost, enemy fainted, map reached). This is Go's playouts with the emulator as
  the simulator, and at 1,000x real time a 10-candidate, 5-second branch costs about 50 ms.
- **Caveat:** the game's RNG makes one branch a sample, not the truth; branch several times with different input
  delays, or treat it like a playout win rate. Also, this is a capability a human does not have. Label any result
  that uses it, and report the same demo without it.
- **Done when:** on Pokemon battles, a `branch`-annotated move list raises the win rate on a fixed set of 20 battle
  savestates over the damage-formula annotation alone.
- **Effort:** 2–3. **Depends on:** G2.

### G7. Generic perception from pixels (unlocks browser, desktop and mobile games with no state access)

This is the hard one and the one most likely to stall. Emulators get G1 for free; screen-only games do not.

- **Build, in order of risk:** (a) grid inference: find the tile size and offset of 2D tile games from frame
  periodicity, then reuse G1's tile vocabulary on pixel tiles; (b) object tracking without labels: connected
  regions that move between frames (`blobs.py` exists), the player found as the region that moves with the input;
  (c) open-vocabulary detection prompted by the deliberate layer's labels (`vocab.py` exists, untested on real
  play); (d) a page's own state where it is reachable (`web.py` already reads it for grading).
- **Done when:** the author produces a working pack for Flappy Bird on a third-party site with no human edit, and it
  survives past the tenth pipe on 8 of 8 games.
- **Effort:** 8–15, uncertain. **Depends on:** G2 for the controller side. Experiment to settle feasibility before
  committing: run (a) and (b) on recorded frames from five web games and measure how many objects the reads find
  against the page state.

### G8. Learning that builds new capability, not only new packs (unlocks improvement without a human)

- **Build:** extend the learn loop in three directions. Stall incidents, not only losses: in a campaign the failure
  is going in circles for 2,000 steps, not a death. Long-window diagnosis over the world memory instead of the last
  ten decisions. And a library of compiler features the rewrite can turn on (the fault catalog in `diagnose.py`
  started this: slow reactions → reflex, wrong picks → playouts). New features stay code written by a person or a
  coding thread; the loop's job is to find which one is missing and say so with evidence.
- **Done when:** on a Pokemon stall that the current pack cannot get past, the loop names the cause and either
  fixes it in the pack or names the missing feature, judged against what a person diagnoses from the same log.
- **Effort:** 4–6. **Depends on:** G3, G4.

### G9. Input across platforms

- **Build:** prove what exists. `pad.py` on Linux uinput with a native game that only takes a gamepad; `adb.py` on
  an Android emulator in the container; `mouse_move` on a first-person camera. Add chords (two buttons at once) and
  analog stick magnitudes as action parameters.
- **Done when:** one game per input class plays one full level or match through that device.
- **Effort:** 2 per platform. **Depends on:** G7 for any game without state access.

### G10. Speed for real-time games

- **Build:** keep Jev off the frame clock. Emulators can be step-locked: no game time passes while Jev thinks
  (`device/pyboy.py` today runs as many frames as wall-clock time passed, so add `?lock=1`). For games that cannot
  pause, the reflex layer and options carry the frame clock and Jev runs asynchronously, as on dino. CLM (16–28 ms,
  same protocol, `sensors.open_sensor('clm')`) is the path to per-frame decisions; it has only been run against the
  stub.
- **Done when:** Super Mario Land world 1 is cleared with Jev choosing jumps and routes at decision points and
  reflexes handling enemies, without step-locking.
- **Effort:** 3–5. **Depends on:** G1, G2.

### Gaps not on the original list

- **G11. A generality scoreboard.** A fixed suite with games that are never tuned on, run on a schedule, reported as
  one table. Without it, "any game" progress is anecdotes, which is how the small-game tuning happened. Effort 2.
- **G12. Long runs that survive.** Checkpoints (savestate + world memory + pack + bank) every few minutes, resume
  after a crash or a reclaimed container, a softlock watchdog, and log compaction: a dino episode writes up to
  18 MB of log, so a 30-hour campaign at full detail would not fit. Effort 2–3. Needed before any full Pokemon run.
- **G13. Pack composition.** A platform pack (`extends: platform/gameboy`) carrying G1's reads, text and controllers,
  with a thin game pack on top. Today every pack is flat and the pool cannot share anything below a whole pack.
  Effort 2. Seam: `pack.merge_mode` already merges one pack dict into another.
- **G14. Two runtimes.** Every feature so far was built twice (Python and the TypeScript extension). For the layers
  above, build in Python only and decide later whether the extension calls a local Python backend instead of
  re-implementing. Effort: saves roughly a third of every gap above.

## 5. Cost per hour at Jev's prices

Jev's price is input tokens only: $0.042 per million. A call is 1,000–2,500 tokens today; a campaign state with a
world memory summary will be nearer 3,000.

| play style | Jev calls per hour | Jev cost per hour |
|---|---|---|
| per-tick, 3 decisions a second (today's loop) | 10,800 | $0.45 to $1.40 |
| options, one decision every 3 seconds of play | 1,200 | $0.05 to $0.15 |
| step-locked emulator, decision points only | bounded by latency, at most about 10,000 | under $1.30 |

Pokemon Red is roughly 25–30 hours for a person. With options, a full run is on the order of 30,000–60,000 Jev
decisions: about $3–8 in Jev calls, and 3–6 hours of wall-clock Jev latency if step-locked. The deliberate layer
is the cost to watch: at one Azure call per 200 Jev decisions with a 5,000-token prompt, a run is 150–300 calls
and roughly 1–2 million tokens. The OpenRouter account's $5 limit, already spent, does not cover one full run;
Dhruv needs to add credit before Phase 3's run.

## 6. The phased plan

Each phase ends on a demo with a number.

| phase | builds | ends on | rough effort |
|---|---|---|---|
| **0. Reset** | G11 scoreboard with held-out games; G13 platform pack skeleton; stop list below | the scoreboard's first table, honest about the ten classes | 2–3 |
| **1. Platform perception** | G1 on PyBoy (tiles, sprites, RAM map, charmap, tile labels), step-lock, G12 checkpoints | Pokemon Red: new game to choosing a starter and winning the first rival battle, menus and dialog included | 6–9 |
| **2. Options and memory** | G2 controllers, G3 world memory, G5 menus | Pokemon Red: Pewter City and Brock's badge, under 5% deliberate-layer decisions; stand-in ablation reported | 10–14 |
| **3. Goals and the campaign** | G4 goal layer, G6 branch lookahead, G8 stall learning | Pokemon Red start to finish: 8 badges and the Elite Four, with the decision shares and cost reported; also run with the game name withheld from the planner | 12–20 |
| **4. Transfer** | nothing new: run the Phase 3 stack on a Game Boy game it was never tuned on | a second Game Boy RPG or adventure reaches its first milestone with no game-specific code beyond a RAM map, or with no RAM map at all | 3–5 |
| **5. Off the emulator** | G7 pixel perception, G9 inputs, G10 real time | a screen-only web game authored with no human edit (Flappy Bird past pipe 10), and Super Mario Land world 1 | 15–25 |

The Pokemon thread owns the Pokemon-specific work in Phases 1–3. This roadmap's ask of that thread is to build
each piece behind the platform seam (G1, G2, G3) rather than inside a Pokemon pack, so Phase 4 is a test, not a
rewrite.

Parts of Pokemon Red known to be hard for this design, so they are planned for and not discovered: the naming
screens (a grid menu), Mt. Moon and Rock Tunnel (dark or maze-like, frontier exploration does the work), the
Rocket Hideout spinner floors (movement that does not follow input; the `path` controller must learn spinner
tiles as their own label), Strength boulder puzzles in Victory Road (needs a push-planning controller or the
deliberate layer), HM usage from the menu (Cut, Surf, Strength, Flash), and the Silph Scope and Poké Flute gates
(dialog-driven goals). The trainer battles are where Jev's judgment is most likely to matter.

## 7. Stop doing

- Tuning snake, Tetris, 2048, Go, dino, Connect Four or tic-tac-toe. Their numbers are good enough and their
  features do not transfer. Keep them only as regression tests in the scoreboard.
- Adding per-game read kinds (`go`, `tetris`, `gap`) as the way to win a game. A new read kind should serve a whole
  platform or a whole class.
- Porting each new feature to the extension in the same thread (G14).
- Jev runs while the OpenRouter account is out of credit: develop against the stand-in and random floor, and
  spend Jev on ablations once credit returns.

## 8. What is uncertain, and the experiment that settles each

| question | why it matters | experiment |
|---|---|---|
| Does Jev pick well among 10–30 annotated options with a 3,000-token state? | Jev's role in Phase 2 depends on it | 200 recorded Pokemon decision points with an oracle label (shortest path to the known goal); Jev vs top-pick stand-in vs random; also latency as state size doubles |
| How large can Jev's state get before latency or quality drops? | world memory has to fit | the same 50 states padded to 1k, 3k, 6k, 12k tokens; latency and agreement with the 1k answers |
| Do tile labels from the vision model generalise across a game's tilesets? | G1's cost and reliability | label Pokemon's overworld tiles, then measure accuracy on later towns against RAM collision |
| Does frontier exploration plus a planner get through Mt. Moon without help? | the first maze in the campaign | savestate at the entrance, 10 runs, count exits and decisions |
| How much does the planner lean on knowing the game? | the honest "any game" claim | Phase 3 with the name withheld, same seeds |
| Can pixel perception find moving objects in unknown web games? | Phase 5 is only worth starting if yes | G7's recorded-frames test on five web games against page state |

## 9. Where new code attaches

| layer | file and seam |
|---|---|
| platform state | `anygame/device/pyboy.py` (add `state()`, `snapshot()`, `restore()`, `?lock=1`); `device/base.py` gains the two optional methods |
| new reads | `anygame/perceive/` new modules, registered in `pack.READ_KINDS` and `perceive/__init__.read_all` |
| options and controllers | new `anygame/controllers.py`; `pack.py` validates `kind: option`; `Agent.act` starts it; `Agent.step` runs it before the Jev call |
| candidates for Jev | a derived read returning an annotated dict, consumed by `criteria_from` in `Agent.questions` |
| world memory | new `anygame/world.py`, owned by `Agent`, saved by `Bank` (`learn.py`) |
| goals | new `anygame/goals.py`, feeding `Agent._tasks_tick` and `state["task"]` |
| deliberate layer | `chat.py` (Azure only), validated by `pack.check_tasks`; `fallback.py` becomes the tile and screen labeller |
| run reporting | `cli.py` run summary gains decision shares (Jev, controller, deliberate) and cost per hour |
| platform packs | `pack.py` `extends:` resolved with `merge_mode`; `packs/platform/gameboy/` |
