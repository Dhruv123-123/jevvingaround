# Where the design breaks once the target is any game

Design review, 2026-10-03, against `claude/anygame-integration` (PR #3's branch). Companion documents: the roadmap
(`roadmap-any-game.md`, PR #9) and the Pokemon Red spec (`pokemon-red-spec.md`). This review does not repeat the
roadmap. It attacks the current design assumption by assumption, then attacks the roadmap where it carries a broken
assumption forward. Probes run offline (no Jev: the OpenRouter account is out of credit) on a free homebrew Game
Boy RPG, Aevilia (`/mnt/project-files/roms/homebrew/aevilia.gbc`), with the scripts in `scripts/review_*.py`.

## The short version

anygame today is a framework for hand-building a game-specific bot, where the last step of the bot asks Jev to
confirm the bot's top pick. That is what was optimised, and it worked: seven games beaten. It is not a path to any
game, for three reasons the evidence below makes concrete:

1. **Every win was written by a person for that game.** 65 of the branch's 138 commits name one game. About 900
   lines of `perceive/` are single-game engines (`go.py` 445, `tetris.py` 303, `slide.py` 147, plus the dino `gap`
   tracker in the loop), each written a second time in TypeScript. The "one-paragraph pack" for the dino is 75 lines
   with 13 rules and 8 hand-tuned millisecond thresholds; the paragraph is the least important part of it.
2. **Jev is designed out every time it proves useful.** On Go, Jev left the compiler's top pick 34 times; 13
   departures were better, 1 worse (`go-playouts.md`). The next step turned that judgment into a compiler rule
   (`rerank: playouts`), after which the top-pick stand-in beat Jev 14/16 to 9/16. On 2048 Jev took the top option on
   2,399 of 2,399 decisions; on Tetris about 9 in 10. Each game ends with the compiler playing.
3. **Nothing measures generality.** Every number is a win rate on a game a thread had already tuned. A design
   that needs a person per game scores perfectly on that kind of measure.

The roadmap (PR #9) sees 1 and 2. Its fix still carries the same pattern into Pokemon Red: a hand-supplied RAM map
from the disassembly, a goal list, and a rule that the strong model may make at most 5% of the decisions. The
findings, ranked by how much each unlocks:

| # | finding | replace with | cost (thread-days) |
|---|---|---|---|
| 1 | No measure of "any game"; the agent reads the same state the grader reads | A frozen held-out suite, a grader state the agent never sees, no per-game code, a fixed budget | 2–3 |
| 2 | The agent's state is written by hand per game (reads, RAM maps) | State discovered from the platform: RAM scan, tile ids, a vision model labelling once | 3–5 |
| 3 | Each game got its own forward model (lookahead, playouts, margin, gap timing) | One forward model per platform: emulator save states; the page itself for web games | 2–3 |
| 4 | One decision per tick over a fixed list | Options generated from state, run by controllers, interrupted by events (agree with roadmap G2; three gaps below) | 4–6 |
| 5 | Jev's role is set by design and ends up a rubber stamp | Jev's role set by a counterfactual audit per decision type; a cost budget instead of the 5% rule | 1–2 |
| 6 | No memory beyond 6 recent actions; screens are fingerprints, not places | Place memory keyed by discovered position; dialogue as the goal source | 3–4 |
| 7 | The pack is a program | A platform pack plus a data-only game layer, and no per-game code | 2 |
| 8 | Pixel reads by hand-picked colour | Off-emulator, a vision model writes the reads and never acts per tick (measured 3.5–5.5 s a frame) | 8–15, uncertain |
| 9 | The learn loop fires on losses | Fire on stalls; long-window diagnosis (agree with roadmap G8) | as roadmap |

## Probes run for this review

All offline, from a cold boot of Aevilia with uniform random presses (the `random` floor), one press per half
second of game time, as the loop does at `tick_hz: 2`. Reproduce with the commands under each.

**P1. What the screen classifier sees in an RPG** (`python scripts/review_rpg_probe.py <rom> --frames 36000`)

| measure, 10 game-minutes, 1,200 ticks | value |
|---|---|
| distinct "screens" in the fingerprint index (new at distance > 40, as `Agent.classify` uses) | **9**, all within the first minute |
| ticks where consecutive frames were "a different screen" | 1.3% |
| ticks where the press changed nothing at all (identical frame) | **47%** |
| fingerprint | 0.27 ms |
| 1 KB of work RAM | 0.05 ms |
| full-frame OCR (rapidocr, the `ocr` read) | **302 ms** |

Random play got through the title screen and character select, then spent nine minutes in the first room and
never left it. The fingerprint index recorded nine screens for the whole run: it tells a dialog from a menu, but
it cannot tell one place from another, and it says nothing about progress.

**P2. Finding the game's state without knowing the game** (`python scripts/review_ram_probe.py <rom>`)

Random direction presses, with work RAM (8 KB) diffed around each. A byte that rises on right and falls on left,
and stays put on up and down, scores 2.0. Result from 400 presses: x at `0xD712` (score 1.91), y at `0xD910`
(1.64), with no disassembly and no game knowledge. Checked by moving: right +6, left −6, up −6, down +6, which
matches a 6-pixel step. The Pokemon spec describes the same scan (`anygame ramscan`), so that thread has
seen this too.

**P3. Exact lookahead from the emulator** (same script)

Save state, try each of the four directions for 30 frames, restore: **144 ms median for all four branches**, on a
299 KB Game Boy Color state. Headless emulation runs at 18,000 frames a second, so most of that time is the state
copy, not the emulation. Every branch landed where the move should go.

**P4. A vision model as a general reader** (Azure `gpt-5.6-luna`, 3 frames from the P1 run; asked for the screen type, all text verbatim, the player's tile, the exits, and the next input, as JSON)

| frame | latency | screen type | text | next input |
|---|---|---|---|---|
| intro dialog | 3.5 s | dialog, correct | verbatim, correct | A, correct |
| character select | 5.5 s | menu, correct | verbatim, correct | RIGHT (a choice: plausible) |
| first room | 5.4 s | overworld, correct | none, correct | RIGHT toward the NPC (plausible; position not verified) |

About 380 prompt tokens per Game Boy frame. It reads unknown screens correctly, but at 3.5–5.5 s a call it cannot
run per tick. Its place is labelling (once per new tile, screen or glyph) and planning, not acting.

**P5. A count-based explorer is not enough** (scratch script, not committed)

A visit-count explorer over the discovered x and y (least-visited neighbour, walls learned by bumping) against
random, 3 seeds of 10 game-minutes each from the first room: distinct positions 83–110 against random's
39–140. Wall bumps fell from 95–232 to 42–58, but it did not reach more of the map. Inconclusive at 3 seeds, but
the cause is clear from the frames: positions are only meaningful together with *which room*, and leaving a room
needs a door the explorer has never seen. Exploration needs place memory with doors (finding 6), not a visit count.

## 1. Evaluation: nothing measures "any game"

**What the design assumes.** Progress is a per-game win rate before and after a change (every report in the
project files).

**Evidence.** Each report compares a pack to its own previous version on the game it was tuned on. The web trial
(`real-web-trial.md`) was the one honest exception: third-party sites, page state used only to grade. Its packs
were still hand-written.

**Where it fails.** "Any game" is a claim about games nobody has tuned for. A design that needs one engineer-week
per game scores 100% on every current measure. That is how the project spent two days on five small games after
deciding the goal was generality.

**Replace with.** One number, the **any-game score**, over a frozen suite:

- **Held out.** 10 games picked by Dhruv, not by a thread, across the roadmap's classes (for example 4 Game Boy:
  an RPG, a platformer, a puzzle, a homebrew; 3 web: one with no state access; 2 desktop; 1 text-heavy). No thread
  opens them before a scored run. The seven current games stay as regression tests, outside the score.
- **Grader state is not agent state.** Milestones come from a grader that reads what the agent may not: pret's
  RAM map for Pokemon, the page's JS object for web games, achievements on desktop. The agent gets only what the
  platform layer discovers. The web trial already did this for perception. The Pokemon spec currently puts the
  disassembly's addresses in the pack's reads *and* in the milestones; split them.
- **Zero touch.** No per-game code, no human pack edit after the run starts, game name withheld from every model
  (roadmap §8 has this as an experiment; it should be the rule, with the named run reported beside it).
- **Fixed budget.** Wall time (for example 2 hours per game), Azure dollars, Jev dollars.
- **Per game:** progress normalised between random (0) and a human milestone list written up front (1), as
  Atari's human-normalised score does. Report the median across the suite and the count of games above 0.1.
- **Always beside it:** the same run with the top-pick stand-in in Jev's place, and the decision shares (finding 5).

**Cost.** 2–3 thread-days, mostly the grader per game and a runner. This comes before any new capability,
because without it findings 2 to 9 cannot be compared.

## 2. Perception: the agent's state is written by hand per game

**What the design assumes.** A pack's `read:` section names zones and colours for this game; `perceive/` grows a
read kind when a game needs one (`pack.READ_KINDS`: 18 kinds, 4 of them single-game: `go`, `tetris`, `slide`,
`gap`).

**Evidence.** Every working pack was hand-written. The one authored pack that plays (`tictactoe-authored`) is a
static board. The flappybird pack cannot see the bird. `perceive/ocr.py` costs 302 ms on a Game Boy frame (P1)
and about 0.7 s on the 2048gb board.

**Where it fails.** Pokemon Red, the first frame after the intro: the state that matters is the map, the party, the
bag, the badges, the text on screen, the cursor. None of it is a colour in a fixed zone. The spec's answer is a
RAM map copied from the disassembly, which is a hand-written read section for one game, 50 addresses long.
On a game with no disassembly (most of them), that path does not exist.

**Replace with.** A platform layer that discovers state, in this order of trust:

1. **Platform structure** (free, exact): emulator tile map, sprites, window layer, registers; for web, the DOM,
   canvas calls and the page's own objects; for desktop, the accessibility tree.
2. **Discovered variables** (cheap, generic): the RAM scan of P2, generalised. Position from directions (shown).
   The map id is the byte that changes exactly when the screen fades. Menu cursor: the byte that steps with up and
   down while a menu is open. HP: the byte that falls when a battle message appears. Money and items: bytes that
   change on a shop transaction. Each is a correlation between an input or event and a byte, found in minutes of
   play with no model.
3. **Labels by a vision model, once**: what a tile is (wall, door, water, grass, NPC), what a glyph is, what a
   screen is (P4: correct on three of three). The labels are cached by tile id or fingerprint, as `fallback.py`
   already memoises screens.
4. **Pixel reads compiled from those labels**, only where 1–3 do not exist (finding 8).

**Cost.** 3–5 thread-days for the Game Boy (roadmap G1 plus the scan). The difference from G1 is the default:
the scan is the agent's source, and a disassembly map is for the grader. If the Pokemon demo reads pret's
addresses, it is another hand-written pack, larger.

## 3. Compiler features: each game got its own forward model

**What the design assumes.** When Jev loses, a thread writes a compiler feature for that game: Tetris landings and
`lookahead`, 2048's two-move lookahead, Go's ladders, playouts and `rerank`, Snake's `margin`, the dino's `gap`
tracker with time-to-contact.

**Evidence.** Look at what each feature is: a hand-written simulator of the game, used to score candidates by
their future. Tetris: drop each piece, score the stack. 2048: slide twice. Go: random games to the end. Snake:
move `lag` cells ahead and flood-fill. Dino: extrapolate the obstacle at its measured speed. Five games, five
simulators, all written twice (Python and TypeScript). The learn loop could not invent the sixth (`learn-loop-v2.md`:
Go discovery test, "unfixable by the loop").

**Where it fails.** The next game needs a seventh simulator. Pokemon battles need the damage formula, the type chart,
stat stages and the RNG, written by hand. That is a Pokemon battle engine in `perceive/`, and it transfers to no
other game.

**Replace with.** One forward model per platform, and one search on top of it:

- **Emulators:** save state, play each candidate forward, restore (P3: 4 branches in 144 ms). Exact for anything
  the game computes, battles included. It replaces all five hand simulators for emulated games, and the search
  (`branch: n frames | until event`, score by a generic progress signal, keep the best k) is one read kind.
- **Web games:** the page is its own forward model if the device can clone it (a second tab with the page's state
  copied in, or a paused page stepped by its own update function). Untested; for many canvas games it will not be
  possible.
- **Everything else:** no forward model. Rules, timing reflexes, and Jev's judgment carry these games. Say so
  in the scoreboard, as a class.

RNG makes one branch a sample, not the truth: branch with several input delays, like a playout win rate. The roadmap
labels this "a capability a human does not have" and schedules it as G6, after options, memory and goals. It
should come earlier, with options. It is the general version of every feature the project has built, and it is
also how Jev gets measured (finding 5). Report results with and without it.

**Cost.** 2–3 thread-days on PyBoy (snapshot/restore on the device, a `branch` read, a generic score). The web
version is a separate experiment, 2 days, likely to fail on canvas games.

## 4. Decisions: one pick per tick from a fixed list

**What the design assumes.** Each tick, the pack's actions (or a compiled read's ranked options, via
`criteria_from`) are the criteria of one `action` question; Jev picks one; `Agent.act` sends one input
(`loop.py: questions`, `step`).

**Where it fails, by kind of game:**

| game, moment | why one pick from a list fails |
|---|---|
| Pokemon Red, the naming screen | the "action" is a sequence of 8–10 cursor moves and presses spelling a word; no single pick means anything |
| Pokemon Red, Viridian City | "deliver the parcel" is hundreds of presses toward a goal that only a dialogue line stated |
| Aevilia, the first room (P1) | 47% of presses changed nothing; the useful action ("go through the door") is not in any list until a door is known |
| Balatro, any hand | the action is a subset: which of 8 cards to play or discard: 218 subsets, each played or discarded, valued only by the scoring rules |
| Wordle, a text adventure | the action is a word; Jev cannot generate one, only pick from a list someone generated |
| Minecraft | continuous mouse look plus held keys; "one input per tick at 3 Hz" cannot even turn smoothly |

**Replace with.** Options with controllers (roadmap G2, agreed), with three gaps the roadmap leaves open:

1. **Who generates the candidate list is the whole problem.** For walking, the world memory can list doors and
   frontiers. For a word, a card subset, or "what to do in this town", only a generative model or a search can.
   Rule: candidates come from the forward-model search (finding 3) when one exists, from the deliberate model when
   the action is language, and from memory for navigation. Jev picks among them.
2. **Interruption is a decision too.** A controller walking to a door gets interrupted by a wild battle, a forced
   dialogue, or a trainer's line of sight. The roadmap lists `interrupted` as a return value. Who decides whether
   to resume, re-plan, or flee? Make it a Jev question with resume, re-plan and handle-the-event as candidates.
3. **Continuous inputs** (mouse look, analog sticks, hold durations) need parameters with a range, not a choice.
   Jev's `score` answer type is an integer; that is enough for a coarse angle or duration bucket, but nobody has
   tried it. Test it before planning any 3D game.

**Cost.** As roadmap G2, plus 1 day for interruption as a question.

## 5. Jev as the only decider

**What the design assumes.** Jev makes every game decision; rules guard it; the compiler annotates the options.

**Evidence that this makes Jev decorative:**

| game | what Jev did | source |
|---|---|---|
| 2048 | took the top option 2,399 of 2,399 times; games identical to the stand-in's | `2048-lookahead.md` |
| Tetris | took landing `a` about 9 in 10; the 3 lost games had Jev taking `a` every time | `tetris-landing-fix.md` |
| Go v3 | took the `worth` top 298 of 298 free choices | `go-playouts.md` |
| Go v4 | left the top 34 times: 13 better, 1 worse, 20 even. Then the compiler absorbed it (`rerank`) and the stand-in won 14/16 against Jev's 9/16 | `go-playouts.md`, `go-playout-rerank.md` |
| Snake | before rules, Jev picked a rule-excluded move 28–62% of the time depending on list order; after rules the final choice matched under every order | `METHOD.md`, order audit |
| Dino | timing is entirely rules; Jev decides jump or duck once per bird, beside the loop | `packs/web-dino/pack.yaml` |

The pattern is a ratchet. Jev shows a judgment the compiler lacks. A thread encodes it in the compiler, and
Jev goes back to confirming. Each step looks like progress, and the end state is a bot with Jev attached. The
roadmap's three-layer design keeps the ratchet. If the options are ranked by distance to the goal and battle
moves by a damage annotation (spec, roadmap G5), Jev will take the top pick most of the time, as it did everywhere
else. This is inferred from the pattern; it can be measured on the first 200 Pokemon decision points (below).

The roadmap's rule 2 (a run where the deliberate layer makes more than a few percent of decisions has failed) makes
it worse. It counts calls, not consequences. The cheapest way to satisfy it is to write very specific goals ("walk
to (5,3) on map 0x01") so that every Jev call becomes trivial. The strong model then makes all the real decisions
but they are counted as one goal each. The other way to satisfy it is to send hard choices to the decider least
able to make them.

**Replace with.** Decide Jev's role by measurement, per decision type:

- **The audit.** At each decision point, save state; play Jev's pick and the top pick forward with the forward
  model (P3) for a fixed horizon; score both by the progress signal. Jev is **decisive** on a decision type if it
  departs from the top pick often enough and its departures score better. This is the Go recheck
  (`scripts/go_agree.py`), made general and exact on emulators.
- **The split, from the audit:** decision types where Jev is decisive stay with Jev. Types where Jev always agrees
  with the compiler go to the compiler, and Jev is not called (cheaper, faster). Types where neither is any good go to
  the deliberate model and are counted against a **cost budget** ($ per game-hour), not a call share.
- **Where Jev should be decisive, by hypothesis:** choices with no forward model and no clean ranking. Which NPC to
  talk to, whether a dialogue matters, which item to use, whether to keep exploring or head back to heal, and which
  of several decent candidates fits the goal text. These are judgments over typed state at 340 ms. Things Jev
  should not be asked: anything a search computes exactly (moves in a battle that save states can test), anything
  timed below its latency (the dino), anything that needs a word or a plan.

If the audit shows Jev is decisive nowhere in Pokemon, report that. It is a result about the product, and Dhruv
should hear it before 40 thread-days are spent, not after.

**Cost.** 1–2 thread-days once save states exist. It needs Jev credit for the Jev half, but the stand-in half (does
the top pick already do as well as anything?) runs today.

## 6. Memory: six recent actions and a screen fingerprint

**What the design assumes.** Jev's state is the current reads plus `recent_actions` (last 6) and noops since the
last change (`loop.py: step`). Places are screens, classified by a 16×16 fingerprint.

**Evidence.** P1: nine fingerprint screens in ten minutes of an RPG, none of which says where the player is. Within
one tileset, every overworld frame is "the same screen".

**Where it fails.** Pokemon Red, Viridian City, first visit: the old man blocks the road north until the parcel is
delivered. Without memory of where Oak is, that a parcel exists, and that the road was blocked, the agent walks
back and forth on the same tiles. P5 showed the small version: a visit count without doors does not get out of a
room.

**Replace with.** Roadmap G3 (world memory), with two changes:

- **Keyed by discovered position and map id** (finding 2), not fingerprints, so it works without a disassembly.
  The fingerprint index stays as a UI-screen classifier (dialog, menu, battle), which it does well.
- **Dialogue is memory and the goal source.** With the game name withheld, the only place goals come from is what
  the game says ("take this to Professor Oak"). Every text line read, with where and when, goes into memory; the
  deliberate model reads it to write goals. The roadmap's G4 mentions "the recent dialog text". Recent is not
  enough: the instruction for Pokemon's Silph Scope gate is given hours before it matters.

**Cost.** As roadmap G3, plus 1 day for the dialogue log.

## 7. The pack is a program

**What the design assumes.** A game is one YAML pack: a paragraph and reads. Everything learned is a pack change
(`ARCHITECTURE.md` §2–3).

**Evidence.** The dino pack's paragraph is 9 lines. Its rules are 13 conditions with eight thresholds in
milliseconds (205, 206, 416, 121, 120, 415, 900, 384) found by measuring this one site. Go's pack is 175 lines and
calls a 445-line engine. Once a pack depends on a per-game read kind, it is a program.

**What fraction of real games fit "a paragraph plus hand reads"?** Games where the whole decision state is on one
screen, the horizon is short, and a good move can be judged from the frame: board games, falling-block and
tile puzzles, single-screen arcade. The roadmap counts 1.5 of its 10 classes. By play time or by sales, they are a
small minority of games. That is an estimate, not a count.

**Replace with.** Roadmap G13 (platform packs), with a hard rule: the per-game layer is **data only**. That means
discovered RAM names, tile labels, the dialogue log and goals written by a model. No new read kinds, no thresholds
tuned by a person. A per-game read kind can stay in the repository as a regression test, and the scoreboard counts
any game that needs one as not general.

**Cost.** 2 thread-days, mostly moving reads into `packs/platform/gameboy`.

## 8. Off the emulator: pixels

The roadmap's G7 is right that this is the hardest and least certain part, and right to put it last. Two numbers
for its plan. A vision model reads unknown Game Boy screens correctly at 3.5–5.5 s a frame (P4), so it can author
reads and label tiles but cannot be the per-tick reader. OCR costs 300 ms a frame (P1), so text-heavy games off the
emulator need text found once and cached by glyph, not OCR every tick. Nothing to add beyond that. The extension
should stop receiving every new layer (roadmap G14, agreed).

## 9. Learning

Agreed with roadmap G8: in a campaign the failure is a stall, not a death, so the loop must fire on no-progress. One
addition: with save states, an incident is replayable. The loop can re-run the stalled stretch with a candidate
change and see whether it gets further, instead of judging by trial episodes of the whole game. That makes the
learn loop's check exact on emulators, the way finding 3 makes the compiler's ranking exact.

## Where the roadmap (PR #9) is wrong or underspecified

1. **Its rule 2 (deliberate layer under 5% of decisions) measures the wrong thing** and invites laundering decisions
   into goals (finding 5). Replace with the counterfactual audit and a cost budget.
2. **"Go shows it can choose among dozens of board cells"** (roadmap §3). Go shows something narrower. Jev's
   departures from the ranking were usually right (13 better, 1 worse of 34), it departed less than it should have
   (69 better departures missed against 31 worse), and when its judgment was compiled into `rerank` the stand-in
   beat it 14/16 to 9/16. That is evidence for Jev as a probe for what the compiler misses. It is not evidence that
   Jev's picks carry a game.
3. **G1 lets a pack carry the disassembly's RAM map.** For Pokemon, that is hand-written reads again. Make the
   discovered state the agent's default and the disassembly the grader's (finding 2).
4. **G6 (save-state lookahead) is placed late and treated as optional.** It is the one general replacement for
   every compiler feature built so far, and it is the instrument for measuring Jev. Move it into Phase 2, next to
   options.
5. **Transfer is tested only in Phase 4**, after 25–40 thread-days of building against one game. Every phase
   should end on two ROMs: Pokemon Red and Aevilia, already in the project files. A layer that works only on
   Pokemon then shows up in Phase 1, not after it.
6. **The cost section counts Jev dollars,** which are noise ($3–8 a run). The costs that decide feasibility are
   wall time and the deliberate model: 3.5–5.5 s a call here (P4), on a rate-limited key. Budget those.
7. **The spec's `auto:` rules** (dialogue → A, "a yes/no the goal already answers" → A) make choices with nobody
   deciding. Any screen with a cursor and more than one entry is a choice and should be a question. Aevilia's
   second screen (character select) is one.

Changes to the roadmap's order, if these are accepted: scoreboard with grader/agent split first (unchanged,
stricter). Then discovered platform state and save-state branching together (G1 and G6). Then options with the
audit built in (G2 plus finding 5). Then memory and goals (G3, G4). Pokemon and Aevilia run at the end of every
phase.

## What this review did not settle

- Whether Jev is decisive anywhere in a campaign game. That needs Jev credit and the audit; the stand-in half can
  run as soon as options exist.
- Whether web pages can be cloned as forward models. Two days to find out, on 2048 and one third-party canvas game.
- Whether a count-based or frontier explorer leaves a room with no door knowledge (P5 was 3 seeds). The world
  memory in the Pokemon thread will answer it more directly.
- Exact Azure cost per vision call: the endpoint did not report it.
