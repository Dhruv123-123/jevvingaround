# Roadmap: from seven small games to any game

Written 2026-10-03 against `claude/anygame-integration` (PR #3's branch), revised the same day to take in the design
review (`design-review-any-game.md`, PR #10). Companion: the Pokemon Red spec (`pokemon-red-spec.md`). This is the
one plan: what "any game" means, what to build in what order, how each step is proven, and Jev's job in the result.
Section 9 lists each point where the review disagreed with the first version, and how it was settled.

## The short version

1. Everything anygame has beaten is short-horizon, and every win came from reads and a game simulator written by a
   person for that game (Tetris landings, 2048 slides, Go playouts, snake flood fill, dino timing). On 2048 Jev took
   the top option 2,399 of 2,399 times; on Go its useful departures were compiled into `rerank`, after which the
   top-pick stand-in beat it 14/16 to 9/16. Each game ended with the compiler playing.
2. **Measure generality first.** A frozen suite of held-out games, a grader that reads state the agent never sees,
   no per-game code, game names withheld from every model, a fixed budget. Until that exists, nothing below can be
   compared, and per-game tuning will keep looking like progress.
3. **State from the platform, discovered, not written.** An emulator exposes tiles, sprites, text and RAM for every
   game on it. Position, map id, menu cursor and HP can be found by correlating inputs and events with RAM bytes
   (the review found Aevilia's x and y this way with no disassembly). A vision model labels tiles and glyphs once.
   A disassembly's RAM map is for the grader only.
4. **One forward model per platform.** Save states replace every hand-written simulator: on PyBoy, four 30-frame
   branches cost 144 ms. The same branching is how Jev's value gets measured, decision by decision.
5. **Options, memory and goals.** Multi-frame actions run by controllers; a world memory keyed by discovered
   position and map; a dialogue log; goals written by the deliberate model as verifiable conditions. Jev decides at
   decision points, and its role is set by measurement, not by rule.
6. Every phase ends on two ROMs, **Pokemon Red and Aevilia** (a free homebrew Game Boy Color RPG in the project
   files), so a layer that only works on Pokemon shows up in that phase. Stop tuning the small games and stop porting
   each new layer to the extension.

## 1. Where anygame is today

The tick (`anygame/loop.py: Agent.step`): device frame → fingerprint → classify screen → reads → derived reads →
questions → one Jev call → rules → one input. Jev never sees pixels; it answers typed questions (choice, noul,
score) about a JSON state.

| fact | number | source |
|---|---|---|
| Jev latency | median 340 ms, p90 about 540 ms | 2,500 calls in 2048, dino and Go logs; `real-web-trial.md` |
| Jev input per call, cost | 1,000–2,500 tokens, $0.00004–0.0001 | logs; `anygame/jev.py` |
| OCR on a Game Boy frame | 302 ms (0.7 s for the 2048gb grid) | review P1; `packs/2048gb` |
| PyBoy tile read | microseconds, from `game_area()` | measured for this roadmap |
| PyBoy save / load state | 20 ms / 7 ms (139 KB); four 30-frame branches 144 ms on a 299 KB GBC state | this roadmap; review P3 |
| Headless emulation | 18,000 frames a second | review P3 |
| Vision model on an unknown frame | 3.5–5.5 s, correct screen type and text on 3 of 3 | review P4 |
| Random play in an RPG | never left the first room in 10 minutes; 47% of presses changed nothing | review P1 |

What is general already: the devices (web, screen, window, pad, adb, stream, pyboy), the tick, rules, tasks, the
VLM fallback's memo, and the learn loop's checks (it rediscovered the snake, Tetris and tic-tac-toe fixes on its
own, PR #6). What is not: every read section and the four single-game read kinds (`go`, `tetris`, `slide`, `gap`),
each also written in TypeScript. Never proven on a real game: `pad.py`, `adb.py`, `window.py`, `vocab.py`,
`mouse_move`, an authored pack for a game with moving objects.

## 2. What "any game" means

| axis | values |
|---|---|
| horizon | reflex (sub-second), tactical (a move to a few dozen), campaign (hours, many goals) |
| state access | page state, emulator (tiles, sprites, RAM), screen pixels only, native memory |
| input | keys, mouse clicks, mouse look, gamepad, touch |
| platform | browser, retro emulator, desktop, Android, console via capture |
| players | solo, versus built-in AI, online versus people |

| class | representative | today |
|---|---|---|
| browser, reflex, keys | Chrome dino, snake | plays, with hand-written reads |
| browser, puzzle or board, clicks | 2048, Go, tic-tac-toe | plays well; the compiler plays |
| browser, no state access, unknown game | a new .io game | no: the author cannot see moving objects |
| emulator, turn-paced campaign | Pokemon Red, Aevilia | no: no goals, memory, places or menus |
| emulator, 2D reflex | Super Mario Land | no reads; reflex and timing features exist |
| desktop, screen only | Stardew Valley, Balatro | untested |
| desktop 3D, mouse look | Minecraft | no |
| Android, touch | Clash Royale | untested; pack and device exist, never run |
| gamepad-only native or console | anything via capture | untested |
| online versus people | ranked play | out of scope (terms of service, anti-cheat) |

Today: about 1.5 of 10 classes, all with a person writing the reads.

## 3. The shape of the agent, and Jev's place in it

```
deliberate  (Azure chat/vision model, rare: a new tile or screen, a stall, a goal done, language)
   writes: tile, glyph and screen labels; goals as verifiable conditions; candidate words or plans when the
           action is language; a diagnosis after a stall.        Has no input channel.
        │ goal                                          ▲ memory, dialogue log, stall evidence
decide      (Jev, at decision points, 340 ms)
   picks among candidates from search (save-state branches), memory (doors, frontiers, NPCs) or the
   deliberate layer (words); also decides what to do when an option is interrupted.
        │ option + parameter                            ▲ candidates, annotated
execute     (controllers and reflexes, every frame, no model)
   walk a path, page through dialogue, move a cursor to a named entry, reflex dodges;
   returns done, blocked or interrupted.
```

Jev can carry: a pick among a few dozen named, annotated candidates; yes/no beliefs that rules use; integer
scores. It cannot: produce a word or a plan, read pixels, remember what is not in its state, search, or act below
its latency. The design review's evidence is that whenever Jev's picks matter, a thread compiles them away. So Jev's
role is not fixed by the design; it is measured:

- **The Jev audit.** At each decision point, save state; play Jev's pick and the top pick forward for a fixed horizon;
  score both with the generic progress signal. Per decision type (navigation target, battle move, menu entry,
  interrupt handling, item use), Jev is decisive if it departs from the top pick often enough and its departures do
  better. This is the Go recheck (`scripts/go_agree.py`) made exact by the emulator.
- **The split follows the audit.** Types where Jev is decisive stay with Jev. Types where it always agrees with the
  top pick go to the compiler and Jev is not called. Types where neither is good go to the deliberate layer and are
  charged against a **cost budget** in dollars and seconds per game-hour, not a share of calls.
- **Goals stay at outcome level**, so decisions cannot be laundered into them: a goal's condition is over progress
  reads (a map reached, a flag set, an item held, a level), never a coordinate. `pack.check_tasks` enforces it, as
  it already refuses exact-cell tasks from the setter.
- **Expectation, to be tested:** Jev is most useful where there is no forward model and no clean ranking: which NPC
  to talk to, whether to push on or go heal, which of several decent targets fits the goal text, what to do when a
  walk is interrupted. If the audit finds Jev decisive nowhere in Pokemon, that is a product result, and Dhruv hears
  it at the end of Phase 2, not after Phase 4.

Every run reports, beside its score: the same run with the top-pick stand-in (`test/clm_stub.py`) in Jev's place, the
audit per decision type, and the cost and wall time per game-hour.

## 4. The gaps, in build order

Effort is in thread-days. Each gap names its seam in the code.

### G0. The any-game score (before anything else)

- **Build:** a runner and a grader per game. The suite: about 10 games **picked by Dhruv**, across the classes above
  (for example four Game Boy: an RPG, a platformer, a puzzle, a homebrew; three web, one with no state access; two
  desktop; one text-heavy). No thread opens them before a scored run. Per game, progress is normalised between
  random (0) and a human milestone list written up front (1); the suite reports the median and the count above 0.1.
  The grader reads what the agent may not (pret's RAM map for Pokemon, the page's JS object for web games); the agent
  gets only what the platform layer discovers. Zero touch: no per-game code, no human pack edit after start, game name
  withheld from every model (the named run reported beside it). Fixed budget: wall time, Azure dollars, Jev dollars.
- **Development pair:** Pokemon Red and Aevilia are worked on openly, outside the score. The seven current games
  stay as regression tests, outside the score.
- **Reuses:** `scripts/web_trial.py` (grading by page state), `anygame suite`, `ANYGAME_LOG_TRUTH`.
- **Done when:** the first table exists, with random and stand-in rows. **Effort:** 2–3.

### G1. Discovered platform state (Game Boy first)

- **Build:** `device/pyboy.py` gains `state()` with platform facts every tick (visible tile ids, window layer,
  sprites), `snapshot()`/`restore()`, and `?lock=1` so no game time passes while Jev thinks. A RAM scanner
  (`anygame ramscan`, already in the Pokemon spec) finds variables by correlation: position from directions, map id
  from the byte that changes on a screen fade, menu cursor from up/down in a menu, HP from battle messages, money from
  a shop. Its output is a data file in the game layer. A vision model labels each tile id, glyph and screen type once
  (walkable, door, water, grass, NPC, letter); collision is confirmed by walking. Text on emulators is tiles, so a
  learned charmap reads it for free.
- **Seams:** `device/base.py` (two optional methods), new read kinds `tiles`, `sprites`, `ram` in `perceive/` and
  `pack.READ_KINDS`; the existing `json` read already consumes `device.state()`; `fallback.py`'s memo for labels.
- **Done when:** on both ROMs, the discovered position and map id agree with the grader's RAM truth on 99% of ticks
  over 30 minutes, the walkable map agrees with the game's collision on 95% of tiles, and dialogue text is read
  verbatim. No per-game code. **Effort:** 4–6.

### G2. Save-state branching (one forward model for every emulated game)

- **Build:** a `branch` read: from a snapshot, play each candidate forward for n frames or until an event, score by
  the generic progress signal (new position, new map, flag or item byte changed, HP kept), keep the best k with their
  outcomes as annotations. RNG makes one branch a sample: branch with a few input delays and report a rate, as Go's
  playouts do.
- **Label:** it is a capability a human player lacks. Report scores with and without it.
- **Done when:** on 20 saved battle states from each ROM, branch-annotated choices beat the stand-in's unannotated
  pick, and the same read with no change replaces the 2048 lookahead in the regression test. **Effort:** 2–3.

### G3. Options, with interruption and the Jev audit

- **Build:** `kind: option` in `pack.py` and `Agent.act`; while one runs, `Agent.step` calls its controller and skips
  Jev. Controllers: `path` (A* over the walkable map, re-plan on block), `dialog` (advance until the box closes or a
  choice appears), `menu` (move the cursor to a named entry and confirm), `press_until`. An interrupted option (a
  battle, a forced dialogue, a trainer's line of sight) becomes a Jev question: resume, re-plan, or handle the event.
  Any screen with a cursor and more than one entry is a question; only single-entry dialogue advances without one.
  Candidates come from search (G2) when it exists, from memory (G4) for navigation, from the deliberate layer when
  the action is language (a name, a word). They reach Jev through `criteria_from` in `Agent.questions`.
- **Audit:** built in from the first run (section 3).
- **Done when:** on both ROMs, from a save in the first town, the agent reaches the next town and returns with no
  deliberate-layer call, and the audit table exists for the decision types seen. **Effort:** 5–7.

### G4. Place memory and the dialogue log

- **Build:** `anygame/world.py`, owned by `Agent` and saved by `Bank`. Keyed by discovered map id and position (not
  fingerprints, which stay as the dialog/menu/battle classifier): tiles seen, visit counts, warps found, NPCs talked
  to, items, the frontier, and every line of dialogue with where and when it was read. Jev sees a compact summary
  (current place, top door and frontier candidates with distance and novelty); the deliberate layer sees all of it.
- **Done when:** after 2 hours on each ROM, the map graph lists every visited map with correct warps against the
  grader, and a restart from a checkpoint reloads it. **Effort:** 4–5.

### G5. Goals from what the game says, and stall recovery

- **Build:** `anygame/goals.py` beside `tasks.py`. The deliberate model is called at start, when a goal completes,
  and on a stall, with the memory summary and the **whole** dialogue log (a hint can come hours before it matters);
  it returns the next goal as an outcome-level condition, validated by `pack.check_tasks`, and the active goal reaches
  Jev as `state["task"]` (`Agent._tasks_tick`). A stall is n decisions with no progress signal.
- **Done when:** with the game name withheld, Pokemon Red delivers Oak's parcel and Aevilia reaches its first
  story milestone, with no human edit after start. **Effort:** 4–6.

### G6. Learning on stalls, replayed from save states

- **Build:** incidents from stalls as well as losses, diagnosed over memory rather than the last ten decisions; and
  because a stalled stretch has a save state, a candidate change is judged by re-running that stretch, not by whole
  trial episodes. The loop's output is a pack (data) change or a named missing capability with evidence.
- **Reuses:** PR #6's `diagnose.py` fault catalog, `learn.py` checks. **Effort:** 4–6.

### G7. Off the emulator: perception from pixels

The hardest and least certain gap. Grid inference for 2D tile games, then reuse of G1's labels; moving regions found
by which one moves with the input (`blobs.py`); `vocab.py` prompted by the labels; page state where reachable. A
vision model authors reads and labels (3.5–5.5 s a frame, so never per tick); text found once and cached by glyph,
since OCR costs 300 ms a frame. **First, a feasibility test:** on recorded frames from five web games, count the
objects these reads find against page state. Also untested: cloning a web page as a forward model (2 days, 2048 and
one canvas game). **Effort:** 8–15.

### G8. Inputs and real time

Prove `pad.py`, `adb.py` and `mouse_move` on one game each; add chords and analog parameters (try Jev's integer
`score` as a coarse angle or duration bucket before planning any 3D game). Real time without step-locking: reflexes
and options carry the frame clock and Jev runs beside them, as on dino; CLM (16–28 ms, same protocol) has only run
against the stub. **Done when:** Super Mario Land world 1 cleared, unlocked. **Effort:** 2 per platform, 3–5 for real
time.

### Supporting work

- **Checkpoints and long runs (G9):** save state + memory + pack + bank every few minutes, resume after a crash or a
  reclaimed container, a softlock watchdog, log compaction (a dino episode logs up to 18 MB). Needed before any run
  longer than an hour. 2–3.
- **Platform packs, data-only game layer (G10):** `extends: platform/gameboy` resolved with `pack.merge_mode`. The game
  layer holds only data: discovered RAM names, labels, the dialogue log, goals. A game that needs a new read kind or a
  hand-tuned threshold counts as not general on the scoreboard. 2.
- **One runtime for new layers (G11):** Python only; decide later whether the extension calls a local Python backend.

## 5. Cost and time

Jev dollars are small: at about $0.0001 a call, a full Pokemon run of 30,000–60,000 decisions is $3–8. They still
need credit on the OpenRouter account, which is out. What decides feasibility is:

| budget | number | consequence |
|---|---|---|
| deliberate-model latency | 3.5–5.5 s a call (review P4), on a rate-limited Azure key | labels must be cached; goals and stall diagnoses only; budget seconds per game-hour |
| deliberate-model calls | unknown per hour until G5 runs; cost per call not reported by the endpoint | log tokens and seconds per call from the first run |
| Jev wall time, step-locked | 340 ms × decisions: 3–6 hours for a full Pokemon run | fine for a demo; checkpoints required |
| branching | about 36 ms per 30-frame branch | 10 candidates per decision fits under Jev's latency |

## 6. Phases

Each phase ends on Pokemon Red **and** Aevilia, plus a scoreboard row.

| phase | builds | ends on | effort |
|---|---|---|---|
| **0. Measure** | G0 suite, graders, runner; G10 skeleton; stop list | first any-game table with random and stand-in rows | 2–3 |
| **1. See and branch** | G1 discovered state, G2 branching, G9 checkpoints | both ROMs: through the intro and the first menus (Pokemon: starter chosen, rival battle won), state checked against the grader | 7–10 |
| **2. Act and audit** | G3 options with interruption, G4 place memory | both ROMs: next town and back with no deliberate call; **the first Jev audit table**, which decides Jev's role from here on | 9–12 |
| **3. The campaign** | G5 goals from dialogue, G6 stall learning | Pokemon Red start to finish (8 badges, Elite Four) and Aevilia to its end, name withheld, with the named run beside it; scoreboard rerun | 12–20 |
| **4. Off the emulator** | G7 pixels, G8 inputs and real time | an unknown web game played with no human edit; Super Mario Land world 1 | 15–25 |

Hard parts of Pokemon Red, planned for: the naming screens (a language action: the deliberate layer proposes names,
Jev picks), Mt. Moon and Rock Tunnel (frontier exploration plus memory), the Rocket Hideout spinners (movement that
does not follow input: a learned tile label for `path`), Victory Road's boulders (push planning by branching), HM use
from menus, and the Silph Scope and Poké Flute gates (goals from dialogue heard hours earlier).

## 7. Stop doing

- Tuning snake, Tetris, 2048, Go, dino, Connect Four or tic-tac-toe. They stay as regression tests only.
- Per-game read kinds and hand-tuned thresholds as the way to beat a game.
- Copying a disassembly's addresses into an agent's reads. They go to the grader.
- Porting each new layer to the extension.
- Jev runs while the account is out of credit: build against the stand-in, spend Jev on the audit once credit returns.

## 8. Open questions and the experiment for each

| question | experiment |
|---|---|
| Is Jev decisive anywhere in a campaign? | the Phase 2 audit on both ROMs; the stand-in half runs without Jev credit |
| Can the RAM scan find menu cursor, HP, party and items, not only position? | scan both ROMs against the grader in Phase 1 |
| How large can Jev's state get? | 50 states padded to 1k, 3k, 6k, 12k tokens; latency and agreement with the 1k answers |
| Does frontier exploration with place memory leave rooms and get through mazes? | 10 runs from saves at Aevilia's first room and Mt. Moon's entrance |
| How much does the planner lean on knowing the game? | Phase 3 named vs withheld, same seeds |
| Can pixel perception find moving objects in unknown web games? | G7's recorded-frames test before Phase 4 starts |
| Can a web page be cloned as a forward model? | 2 days on 2048 and one canvas game |

## 9. Reconciled with the design review

The review (PR #10) named seven places this roadmap was wrong. All seven are taken in; two with a qualification.

| # | review's point | settled |
|---|---|---|
| 1 | The "deliberate layer under 5% of decisions" rule counts calls, not consequences, and invites hiding decisions in very specific goals | **Accepted.** Replaced by the per-decision Jev audit, a cost budget in dollars and seconds, and outcome-level goals enforced by `check_tasks` (section 3) |
| 2 | "Go shows Jev can choose among dozens of cells" overstates it | **Accepted.** Go shows Jev as a probe of what the compiler misses (13 better, 1 worse in 34 departures), not that its picks carry a game; the claim is gone |
| 3 | G1 let the agent read the disassembly's RAM map | **Accepted.** Discovered state is the agent's source; the disassembly map is the grader's. Qualification: the scan finding cursor, HP and items is unproven, so Phase 1 measures it first |
| 4 | Save-state lookahead was late and optional | **Accepted.** Now G2, in Phase 1, and the instrument for the Jev audit. Still reported with and without, because a human player cannot do it |
| 5 | Transfer tested only after 25–40 days on one game | **Accepted.** Every phase ends on Pokemon Red and Aevilia; the held-out suite is the real transfer test |
| 6 | The cost section counted Jev dollars, which are noise | **Accepted with a qualification.** Wall time and the deliberate model are now the budgets that matter (section 5). Jev dollars stay as one line, because the OpenRouter account is out of credit and a full run needs some |
| 7 | The spec's `auto:` rules make choices with nobody deciding | **Accepted.** Any screen with a cursor and more than one entry is a question (G3). This changes the Pokemon spec, which belongs to the Pokemon thread |

Also taken from the review: the held-out suite picked by Dhruv, with zero touch and the game name withheld (G0); the
dialogue log as memory and as the goal source (G4, G5); interruption as a Jev question (G3); a data-only game layer
(G10); and stall learning replayed from save states (G6).
