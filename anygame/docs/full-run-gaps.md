# Pokemon Red start to finish: what carries over, what was tuned, what is missing

2026-10-03, branch `claude/anygame-pokemon-full-run-gaps-85kn4w` (stacked on PR #14, which contains PR #12).
Read against: `pokemon-red-spec.md`, `roadmap-any-game.md`, `design-review-any-game.md`, and the run reports
`aevilia-run1.md`, `discovery-v2.md`, `red-bringup.md`, `longhorizon.md`, `heldout-score.md`. Rule kept throughout:
the published RAM map grades milestones only, the agent finds its own state, and no agent code names a game.

## The answer

What exists today gets a run through the intro and around towns: position from RAM, screens told apart by trying
buttons, menus as one Jev question, a world memory that walks paths, goals written from dialogue. That is enough
for Aevilia's demo (6 of 6 with Jev, $0.05) and for Pokemon up to Red's room. It is not enough for the campaign,
because the campaign is mostly three things the agent cannot do yet: **read what the game says exactly**, **judge a
choice by what it leads to several screens later** (every battle turn), and **track numbers** (HP, levels, money,
items). Ranked by how much of the game each one blocks:

| rank | gap | first milestone it blocks | share of the 21 milestones behind it | general mechanism |
|---|---|---|---|---|
| 0 | Pokemon's map label churns on every menu and text box (in flight, emulator thread) | 1 (out of the house, reliably) | all | state discovery |
| **1** | **Text read exactly, from the screen's 8x8 cells, each glyph learned once** | 4 (Oak's parcel) | 18 of 21 | state discovery, labels by the deliberate model once per glyph |
| 2 | A choice judged by what it leads to: play it out to the next decision, keep the text and what changed | 6 (Brock), soft from 3 (rival) | 16 of 21 | multi-step option, Jev question with discovered effects |
| 3 | Numbers: HP, level, money, item counts, party size, found and tracked; goals over them | 6 (Brock: level), hard at 20 (Elite Four: no healing) | 16 of 21 | state discovery, goal conditions the planner can check |
| 4 | Using things: an item or a field move from a menu chain (HM teach, Cut, Surf, Strength, Poke Flute, Bicycle); walls re-tested after a new capability | 10 (Cut to Surge's gym) | 12 of 21 | goal + one Jev question per menu (exists), world memory rule |
| 5 | Movement that does not follow the d-pad: ledges, spinners, warp pads, boulders, water, the Safari step limit | 13 (Rocket Hideout spinners) | 9 of 21 | world memory learns it (warps exist), branching for boulders |
| 6 | Throughput: about 1 s of wall time per tick, most of it re-probing screens it has seen | none (a wall-time budget) | all | caching what branching found, by screen |
| 7 | Planner budget and stall recovery over hours: 60 goal calls per run, conditions only about places and lines | 4 onward, as the run lengthens | 18 of 21 | goal planner (Azure), stall diagnosis (roadmap G6) |

Gaps 1–3 are the ones the coordinator's note guessed (battles, party, inventory, money, health). They come out as one
perception gap and two decision gaps, and each is a general mechanism, not a Pokemon module: the spec's old section 6
(a type chart and move table read from the ROM) is withdrawn; see "Spec changes" below.

## What proved general: keep as is

| mechanism | evidence it is general | file |
|---|---|---|
| Position from the d-pad, in RAM, with no addresses | found Pokemon's real x/y (D362/D361) and Aevilia's; 100% on replay; the text-box filter is measured against the game's own presses (an Otsu split), not a constant | `discover.py` |
| Screen kind by trying buttons from a save state | the same code labels title, naming, text, menus and walking in both games and four homebrews | `perceive` `probe` (device thread) |
| A choice is one Jev question, entries and outcomes found by trying | title menus, character select, START menu, yes/no in both games; Jev's "walk" pick broke Aevilia's START loop | `perceive/menu.py` |
| World memory: visited tiles, blocked edges, warps, frontier, paths | reached Startham Forest; nothing game-specific in it | `perceive/world.py` |
| Goals as conditions the code checks, written by Azure from dialogue | 9 calls, none rejected, 1.96 s median; goals reached | `goals.py` |
| The audit: Jev's pick vs the top pick played forward from a save state | measured Jev better 1.9% vs top better 0.6% on Aevilia | `audit.py` |
| Checkpoints and resume | a long run is a series of runs | `memory.py`, `cli.py` |

## What was quietly tuned to Aevilia or the intro

Each of these works on what it was tried on and will break later in Pokemon. None is a reason to throw the mechanism
away; each is a constant or a shortcut that has to become measured.

| where | tuned how | where it breaks in Pokemon |
|---|---|---|
| `menu.py` `settle: 90` (pack) | 1.5 s after A is enough to see a title menu or a yes/no open | a battle move resolves over several text boxes (inferred: several seconds of text); 90 frames shows "the screen changes, no new text" for every move |
| `menu.py` cache keyed on the exact screen | a static menu looks the same every time | the battle menu redraws with new HP bars every turn, so each turn re-explores (about 20 branches plus OCR per entry); shops change with money |
| `menu.py` "three directions each reach their own entry → a player turning", `walk_hold: 16` | written from Pokemon's intro, where a tap only turns Red | a real 4-way menu (Pokemon's naming keyboard, a 2x2 battle menu) while x is unknown gets walking offered beside it; harmless while x is known |
| `discover.py` `BURST_MIN = 150, BURST_X = 2.5` | fitted on Aevilia's stairs | Pokemon keeps its screen tile map in work RAM, so every menu and text box is a "door" (6 signatures for 1 map); Deep Dungeon counts 130 doors |
| the pack's text read: OCR at 0.67 scale on the whole frame | chosen for an 8 px font | reads "Fir=t: what i= YOUF name?", "OFTION", "playi ng the SMESI" (red-run5/6 logs), and 300 ms a tick |
| `goals.py` conditions (`new_place`, `leave_place`, `place`, `said`, `talks`, `screen`) and the prompt's examples ("leave a house, go downstairs") | Aevilia's demo only asks you to go places | no condition for "holds an item", "level at least", "party of two"; `said` fails when OCR garbles the word it waits for |
| `goals_cfg: max_calls 60, give_up 250` | sized for a 900-tick run | a campaign is 100k+ ticks: needs a budget per game-hour, not per run |
| `world.py` walls are permanent after three bumps | right in a town | water becomes walkable after Surf, a cut tree after Cut, a guard after a drink; the memory never re-tests them |
| the play paragraph's "a button that only reopens a menu you just closed is not progress" | the lesson of Aevilia's START loop | harmless, but it is a game's lesson in a generic pack |
| emulator timings `step 4, hold 8, after 8`, probe hold 16 | Pokemon's walk takes 16 frames; set after the intro | other games' walks differ; should be learned from the found position (the device thread's) |

## Walking the campaign: what each segment needs that does not exist

Milestone numbers are the spec's table. "Exists" means the mechanism is built and has run on at least one ROM.

| segment | milestones | what happens | blocked by (gap rank) |
|---|---|---|---|
| Intro to Red's room | 0 | names, text | exists (names are AAAAAAA) |
| Pallet, Oak's lab, starter, rival | 1–3 | scripted walk, a yes/no on a ball, first battle | 0 (map label); 2 soft: a mashed rival battle may be lost, which is allowed |
| Parcel and Pokedex | 4 | the Mart clerk hands over the parcel; Oak must be found again; the old man blocks Route 2 until then | **1**: the goal writer has to read "take this to PROF. OAK"; exploring alone cannot get past the old man |
| Viridian Forest, Pewter, Brock | 5–6 | maze with trainers; a rock gym | 2 (pick moves by effect), 3 (train until strong enough); Charmander mashing Scratch loses to Onix |
| Mt. Moon, Cerulean, Misty, Nugget Bridge, Bill | 7–8 | long cave, many Zubat, a gift fossil choice, Bill's dialogue gates the SS Anne ticket | 1, 2, 3 (heal before the cave: a goal over HP) |
| SS Anne, Cut, Lt. Surge | 9–10 | get HM01, teach it from the bag, use it on the tree from the party menu, trash-can switch puzzle | **4** (menu chain from a goal; tree tile re-tested), 1 |
| Rock Tunnel, Lavender, Celadon, Erika | 11–12 | dark cave (RAM position still works), department store, drinks | 1, 3 (buy balls, potions, a drink: money and counts) |
| Rocket Hideout, Pokemon Tower | 13–14 | hidden switch behind a poster, spinner floors, lift key, Silph Scope, Mr. Fuji, Poke Flute | **5** (spinners), 1 (the hints), 4 (use the flute on Snorlax) |
| Safari Zone, Surf, Strength, Koga | 15 | 500-step limit, Gold Teeth, warden; teach Surf and Strength | 3 (steps left is a number on screen), 4, 5 (water) |
| Silph Co., Sabrina | 16 | card key doors, warp pads, Lapras gift | 5 (warp pads: warps, exist; 36 tries worst case), 1 |
| Cinnabar, Blaine | 17 | Surf there; mansion switches open and close doors; quiz gym | 4 (Surf), 5 (doors that change: walls re-tested), 1 (quiz: a yes/no judged by text) |
| Giovanni | 18 | spinner gym | 5 |
| Victory Road, Elite Four, Champion | 19–21 | boulders onto switches; five battles without a Pokemon Center | 5 (boulders: branching), **3** (level 50ish party, healing items: numbers and goals), 2 |

What is no gap: catching is not strictly required (Lapras is a gift; whiteouts heal you), losing is allowed, darkness
does not hide the RAM position, and the naming screen is solved by accepting any name.

## The gaps, with the general mechanism for each

### 1. Text read exactly (state discovery)

A Game Boy draws text as 8x8 cells on a grid, one character per cell in both games tried (Pokemon's text box and
Aevilia's dialogue box). So a cell's pixels are a glyph's identity: learn what each glyph is **once**, then read every
later line exactly and in microseconds, instead of OCR at 300 ms that reads "OFTION". Labels come from the deliberate
model (Azure) reading a whole line image and returning one character per cell; a line with the wrong length is
discarded, and each glyph needs two agreeing lines before it is trusted. With no chat model, OCR of the same clean
line is the labeller. Measured on 120 presses from power-on: Pokemon showed 134 distinct two-tone cells over 12,733
occurrences, Aevilia 218 over 1,828: a small alphabet, reused constantly.

What it unlocks: every goal from dialogue (`said` stops missing words), menu labels Jev can trust ("POTION x3", "CUT"),
battle messages ("It's super effective!", "Enemy ONIX fainted!", "grew to level 14!"), and numbers printed on screen,
which is gap 3's cheapest source. **This is the one being built first** (below).

### 2. A choice judged by where it leads (multi-step option, Jev question with discovered effects)

Extend "try each entry from a save state" from 90 frames to **the next decision**: play the entry, page any text with
A, stop when the screen is a choice or walking again (or a frame cap), and report the text it produced and which
numbers changed. A battle move becomes "THUNDERSHOCK → 'It's super effective! Enemy PIDGEY fainted!' (enemy bar
gone)". The forward model is the emulator itself, so this is the roadmap's G2, without a type chart. RNG makes it a
sample (the audit already deals with that by replaying from the same state). Cache by the menu's text, not its pixels,
so a battle menu with new HP bars is recognised as the same menu.

### 3. Numbers (state discovery, goal conditions)

Two sources, both general: numbers printed in exact text (HP "23/ 30", level ":L14", money, "x3", Safari steps), labelled
by the words next to them; and RAM bytes that move with those printed numbers (the discoverer's method, pointed at a
printed number instead of the d-pad), which keeps them readable when not on screen. The planner then gets one more
condition, `{number: {name, at_least | at_most}}`, so it can write "heal: HP of the lead at least 80%" or "train until
level 14" from what it has read. Jev sees the numbers in its state and decides when to heal or run.

### 4. Using things (a goal, one Jev question per menu, a world rule)

Teaching an HM is START → ITEM → HM01 → yes → a Pokemon; using it is START → POKEMON → a Pokemon → CUT, facing the tree.
Each step is already a menu question; what is missing is the goal that names the outcome ("the tree is gone": the
blocked tile becomes passable, or a new place is reached) and a world rule: **after an event that may add a capability
(a "learned", "received" or "obtained" line), blocked edges are re-tested**. Nothing names Cut or Surf.

### 5. Movement that does not follow the d-pad (world memory, branching)

Ledges (one-way edges), spinners and warp pads (a step that lands elsewhere: already a warp within the map), water
(re-tested after a capability, as in 4), boulders (a step that moves another object: branching tells which pushes open
a path), the Safari step limit (a number, gap 3). Most is learned the way walls and doors are learned now.

### 6. Throughput (caching by screen)

The red-run logs show 120–400 ms of perception per tick, mostly the 8-branch probe, plus menu re-exploration in
battle; Aevilia's Jev run was about 1 s a tick before the audit. A campaign of 100k–300k ticks is then 30–80 wall
hours. Caching the probe's verdict by screen (the device thread's) and the menu read by its text (gap 2) is most of it.

### 7. Planner budget and stall recovery

Goal calls per game-hour instead of 60 per run; the dialogue log summarised by place so a hint from hours ago reaches
the writer; a stall (no new place, line or number for N decisions) triggers a diagnosis call (roadmap G6). Cost is
Azure seconds, not Jev dollars.

## Jev cost per segment, against the $3–8 estimate

Measured: Jev cost $0.0000658 per decision on Aevilia (720 decisions, $0.0474, states with menus and the world read),
$0.000024 on the held-out games (small states). Assumed: a casual human finishes in about 16 game-hours; the agent
needs 3x the game time (Jev's Aevilia run took 6.2 game-minutes for what a person does in about 2); text pages without
a call, walking goes in chunks of up to 8 steps, a battle turn is 2 decisions; about 25 decisions per game-minute, at
$0.00007 each. Inferred, not measured on Pokemon past the intro.

| segment | milestones | human game-min (rough) | agent decisions | Jev $ |
|---|---|---|---|---|
| Intro, starter, rival | 0–3 | 10 | 750 | 0.05 |
| Parcel, Forest, Brock | 4–6 | 60 | 4,500 | 0.32 |
| Mt. Moon, Cerulean, Misty, Bill | 7–8 | 90 | 6,750 | 0.47 |
| SS Anne, Cut, Surge | 9–10 | 75 | 5,600 | 0.39 |
| Rock Tunnel, Celadon, Erika | 11–12 | 120 | 9,000 | 0.63 |
| Hideout, Tower, Flute | 13–14 | 90 | 6,750 | 0.47 |
| Safari, Surf, Strength, Koga | 15 | 120 | 9,000 | 0.63 |
| Silph, Sabrina | 16 | 90 | 6,750 | 0.47 |
| Cinnabar, Blaine | 17 | 75 | 5,600 | 0.39 |
| Giovanni | 18 | 45 | 3,400 | 0.24 |
| Training, Victory Road, Elite Four | 19–21 | 180 | 13,500 | 0.95 |
| **whole game** | | **955 (16 h)** | **72,000** | **$5.0** |

So the $3–8 range holds if the agent is within about 2–5x of a person's game time. What would break it is not Jev's
price but wasted decisions: a stall loop like Aevilia's START menu costs about $0.05 per 900 ticks, so a 10-hour stall
is under $3 but also 10 hours of wall time. Not counted: the audit (no Jev calls, ~19 s wall per new disagreement),
Azure goal and glyph calls (seconds, rate-limited; the glyph labeller needs a few calls per game), and wall time
(~1 s per tick today: 50–80 hours for the whole game until gap 6 is done).

## Spec and roadmap changes (made in the project files)

- `pokemon-red-spec.md`: section 6 (battles from the ROM's type chart and move table) and section 5 (a hand-written
  goal list) withdrawn: both contradict "map grades only". Replaced by gaps 1–4 above. The phased plan now follows the
  gap ranking, each phase ending on Pokemon Red and Aevilia.
- `roadmap-any-game.md`: a "Campaign gaps" section (C1–C7, the ranks above) and the Phase 2 and 3 rows updated: text
  and played-out choices move into Phase 2, numbers and using things into Phase 3. The repo copy lives on PR #9's
  branch; this branch does not carry it, to avoid two copies.

## Being built first: gap 1, text read exactly

`anygame/perceive/tiletext.py`, a new read kind `tiletext` (no device, scanner, probe, grader or runner change).
Landed: `docs/tiletext.md`. On Pokemon it reads 98.9% of learned cells right, 1.00 similarity to the true text late
in a 400-press run against OCR's 0.93, at 0.75 ms a read instead of 217 ms.

## Built second: gap 2, choices played out to the next decision

`anygame/playout.py`, see `docs/playout.md`. In Pokemon's rival battle, TACKLE now reads "SQUIRTLE used TACKLE!
Enemy BULBASAUR used TACKLE!" then back at the menu, and RUN reads "No! There's no running from a trainer battle!".
In Aevilia, a character pick plays out through the narrator to "Use the d-pad to move around.". The call site is
`menu.py`'s `_outcome` (the long-horizon thread's).

## Built third: gap 3, numbers

`anygame/numbers.py`, see `docs/numbers.md`. Numbers are read with their labels from the exact text and bound to the
RAM that follows them after three distinct values. In the rival battle, Squirtle's HP was bound to two places
(the battle copy and the party copy) with no addresses given. A goal condition `{number: {name, at_least | ...}}`
checks them.

## Built fourth: gap 4, using things

`anygame/chains.py`, see `docs/chains.md`. A breadth-first search over menu chains, each pick played out, toward an
outcome the goal names: Pokemon's "Withdrew POTION." from Red's PC was found in 19 tries and replays exactly. On
Aevilia it mapped the pause menu, which lists buttons rather than a cursor. A line that tells of a gain reopens the
walls the world tracker had given up on.

## Gap 6, step 1: wall time

See `docs/speed.md`. Profiling the long-horizon agent on Tobu Tobu Girl showed menu trials taking 90% of the wall time.
Faster screen comparison and an OCR cache took 91 ticks from 184 s to 69 s with identical decisions. The rest is in
the menu reader's choice of when to explore.

## Gap 5: what each button does

`anygame/motion.py`, see `docs/motion.md`. Each input is tried from a save state for a tap and a hold. The player's x
and y are found in memory (the sprite table is preferred), and each input is described: a step of one tile, a walk
while held, a jump with its height, a dash. On Pokemon a tap is a whole tile; on Aevilia movement is continuous; on
Tobu Tobu Girl B is a jump and A with a direction a dash; on Renegade Rush left and right steer.

## Gap 7: when to ask the goal writer

`anygame/goalgate.py`, see `docs/goal-budget.md`. Of 412 logged writer calls, three quarters bought a goal the program
would have had anyway: the same goal kept, rewritten as itself, or the generic one. The gate asks only on text the
run has not seen before, when a goal ends after news was kept over, or once after a give-up, from a budget that grows
with game time. Replayed on two Pokemon runs, it makes 13-14 calls where 34 were made.

## Second pass (2026-10-04): what stands between the agent and the first badge

All seven gaps above are built. This pass re-reads the Pokemon Jev run from power-on to Route 1
(`longhorizon/pk-jev-route1/`, three parts, 2,476 ticks). It also re-scores every logged run's places against the grader's map,
using `scripts/place_check.py`. The held-out re-score after the speed work has not landed yet. The held-out lines below use the last table in
`heldout-score.md`.

What the Route 1 run shows:

- **The world memory has two places for the whole game so far.** Red's house (two floors), Pallet Town, Oak's lab
  and Route 1 are 5 maps. The run's world memory names 2 places, and in part 3, 27% of ticks are spent in a place that is
  mostly another map. Two things cause it:
  - Pallet Town and Route 1 join without a door or a fade. The map signature does not change at the join, and the
    position jumps from row 0 to row 35. The world records it as a warp inside one place, so Route 1's tiles land on
    top of Pallet Town's.
  - When the signature does change (to Route 1's map byte, five steps in), the change came on a one-tile step. It is
    made a permanent alias of Pallet Town.

  So a "new place" goal cannot fire on Route 1 and will not fire at Viridian City. The walls and visited tiles of two
  maps are mixed together, and "go back to the lab" has no place to point at.
- **The run blacked out once, and was heading for a second.** The report's "walked home to Red's house" at the end of
  part 2 was a blackout: "RED is out of useable POKéMON", "RED blacked out". Bulbasaur fought every wild battle in
  the grass with FIGHT and never ran or healed. In part 3 it was at 1 HP of 24 when the run stopped. The game puts the
  player back home, so each blackout undoes the walk.
- **Route 1 is mostly battles.** 88% of Route 1 ticks were battle screens. In 870 Route 1 ticks the best the run did
  was 13 rows of Route 1's 36.
- **The goal writer ran out.** The 60-call cap was hit at tick 1744, before Route 1. Every goal after that was the
  generic explore with no direction, so the walk drifted sideways. Gap 7's gate is the fix, once it is wired.
- **The rival was lost** with FIGHT/TACKLE on every turn. Brock needs the better move picked by its played-out effect.

Re-ranked, by what each blocks between here and Brock:

| rank | gap | blocks | mechanism (general) |
|---|---|---|---|
| **8** | **Place identity: joins without a door, and aliases that are guesses** | Viridian City (next milestone), the parcel's return to the lab, any "go back to" | a place book: a step that lands on the far side of the map is a join to a neighbour place, and an alias stays a guess until the tiles agree |
| 9 | Upkeep: notice a number falling (HP), leave the fight (a choice whose played-out text ends it), and go back to where it last refilled | every route with grass; Viridian Forest; Brock | numbers (gap 3) + places (8) + played-out choices (gap 2) |
| 7 | Goal budget: wire the gate (built) | everything after tick ~1,700 | `goalgate.py` call sites |
| 10 | A heading: keep walking the way new places were found instead of the nearest unexplored tile | Route 1, Viridian Forest | world frontier, scored by direction |
| 11 | A battle choice judged by what it does to the other side's number (the enemy's HP bar) | the rival, Brock | numbers + played-out choices |

For the held-out set the ranking is unchanged until the re-score lands. Wall time ended 100% of the top-pick runs at 18
presses a minute. The speed work since then (PR #21, 2.6x on Tobu) is what that re-score measures. Then come movement
options from `motion.py` (Tobu's jump, Renegade's steering), which no decider offers yet.

### The font's cold start (from the held-out re-score after the speed work)

Each held-out run starts with an empty glyph book. On Tobu Tobu Girl and Renegade Rush the labeller hit its cap of
40 calls, and the calls add up to 470–540 s. `scripts/glyph_coldstart.py` replays a cold start with a finished book
answering in place of the model, so labelling policies compare without spending anything:

| game | calls before (6 waiting lines start a call) | scenery settled in one reading | + 24 waiting lines start a call |
|---|---|---|---|
| Pokemon Red | 25 | 24 | 21 |
| Renegade Rush | 27 (95% of text cells read) | 26 (97%) | 25 (97%) |
| GBHack | 13 | 13 | 12 |

What this shows:
- **Fewer, larger batches do not cut much.** The number of calls follows how new text keeps appearing over play,
  not how lines are grouped into calls.
- **Picking lines with the most new glyphs first makes it worse** (Pokemon 25 to 38 calls). A glyph is trusted when
  a line agrees with glyphs already known, and that pick leaves each line with fewer known glyphs.
- **What does help is small.** A line the model reads as entirely not-text now settles its glyphs in one reading
  (`scenery_once`). That is most of Tobu Tobu Girl, whose two-colour scenery tiles were 162 of the 164 glyphs it
  learned.

The labeller also runs in a background thread, so its seconds overlap play rather than add to it. Whether it costs
wall time at all is what the held-out run with a kept book (`book-top`) measures. The lever that would matter is a
book kept per game (Dhruv's decision card), or a deliberate first pass over the first text screen only. No measured
policy turns a cold start into seconds.

### C11 built: battle choice by the other side's bar

`anygame/battle.py`, `docs/battle.md`. A menu's play-outs are compared by the bars on the screens they end on. The
entry that leaves the other side's bar shortest ranks first, and the player's own bar is told apart by matching its
shown number.
- Rival, 20 fights each: 18 won by the bar, 15 always-TACKLE, 13 random.
- Route 1 wild, 20 fights each: 19, 19, 14.
- Silent on Aevilia, Renegade Rush, Tobu and GBHack.
- Call site: `menu-battle.patch` for long-horizon.

### Next speed item, noted, not built: "is this screen a menu"

The held-out profile (coordinator, 2026-10-04) puts 91% of Tobu's wall time in menu explores. A platformer's play
screen was explored as a menu on 75 of 112 steps, at 3.7 s each. Long-horizon is gating explores on screen kind.
A general check would say whether a screen is a menu before exploring it, from three signals:
- a cursor: a small shape that moves between text lines on the d-pad;
- choice text: two or more short lines in a box;
- a d-pad response without the world moving: the screen changes in one small region only.

It would be a module with its own replay over the held-out logs. It is the next speed item after C11.

### Upkeep fix: health, not move PP (2026-10-04)

The live power-on run (pk9–pk14) left fights over a move's PP ("Get TY #/# back up"), which healing cannot meet.
It also marked PP fatal at a blackout. `upkeep.py` now treats a number as health before the game has shown it fatal
only when it fell while the game played on by itself, by different amounts, some by more than one. At a forced move
the number that came near its floor last is the fatal one. The one-bad-turn rule needs the number at half or below.
On the live run replayed with every fraction under its live name (`scripts/upkeep_replay.py --names`), every warning
names HP and each of the four blackouts is preceded by one, 150–180 ticks earlier; before, 22 warnings included PP.

### Menu reads from the cells, not RapidOCR (2026-10-04)

`tiletext.boxes()` gives the menu reader its text boxes from the glyph book. OCR is used only while the book is cold
(fewer than 30 characters) and most of the screen is unknown. Before, any screen with more unknown cells than known
went to OCR: on Tobu Tobu Girl that was the play screen's scenery, every menu read. The menu.py side is
`menu-tiletext.patch` (one function, for long-horizon). The explore gate is long-horizon's (`needs_words`).

`scripts/step_profile.py`: 200 steps of the gameboy agent, top pick, the per-game book from the held-out runs,
no labeller, the same code before and after but for this change (four games at once, so seconds are relative):

| game | s per step before | after | actions identical |
|---|---|---|---|
| Tobu Tobu Girl | 3.60 | **2.20** (−39%) | 200 of 200 |
| Renegade Rush | 1.16 | **0.93** (−20%) | 200 of 200 |
| GBHack | 0.49 | **0.39** (−21%) | 200 of 200 |
| PostBot | 0.15 | 0.15 | 200 of 200 |
| Pokemon Red (power-on) | 0.30 | 0.30 | 200 of 200 |
| Aevilia (power-on) | 0.35 | 0.35 | 200 of 200 |

Pokemon and Aevilia already read their menus from the cells (their screens' text is known), so nothing changes there.
Tobu still spends most of a step exploring menus. With this change those explores cost no OCR. Long-horizon's
explore gate is the change that removes the explores themselves.

### Stall detector (2026-10-04)

`anygame/stuck.py` notices the agent going round in circles. It sees what the agent sees, never the grader: each
step's screen kind, text read, found position and map, and the frame reduced to a coarse print (18x20 blocks, four
grey levels). A step is new when that observation or print has not been seen before in the run. It raises when 40
steps bring at most 2 new ones and the agent took at most 4 different actions, then waits 20 steps before raising
again. `suggest(options)` lists what to try instead: the options on this screen the loop did not take, then B, then
the repeated ones (a caller with play-outs keeps the first that changes the screen). The loop's own `noops` list
catches one screen where nothing changes; this catches cycles through several screens that each change.

Today's Pokemon logs, replayed from the reads (`scripts/stuck_replay.py`, no frames), 7,464 steps of pk9–pk15:

| stall | started | raised | steps to detect |
|---|---|---|---|
| Oak's "Don't go away yet!" sending the player back | 388 | 489 | 101 (the first walks up still find new tiles) |
| the Pokemon menu opened and closed over and over | 5365 | 5404 | 39 |
| Rattata's move menu walked "down" (cursor read as position) | ~5764 | 5835 | ~71 |

That is 0.7 raises per 1000 steps on the replayed logs, every one a real loop. On Route 1 (pk-jev-route1) it raised
once, on a pick-and-wait loop at 474–753.

Live with frames (`scripts/step_profile.py --stuck`, top pick, the stand-in never acting on a raise):

| game | steps | raises | what they were |
|---|---|---|---|
| GBHack | 1000 | 0 | |
| Tobu Tobu Girl | 400 | 0 | |
| Renegade Rush | 600 | 0 | |
| Pokemon Red (power-on, through the rival fight) | 1000 | 0 | |
| Aevilia (power-on) | 1000 | 3 stalls | waiting 40+ steps on a frozen screen; pacing left/right between two map edges (twice) |
| PostBot | 1000 | 1 stall | A, SELECT, SELECT, A, B on the same five screens from step 22 to the end |

No false alarms on the three held-out games or on Pokemon; every raise was a loop the stand-in never left. A stall
the agent does not break re-raises every 20 steps, so counts here are in stalls, not raises.

Runner call site (long-horizon's, in `Loop.step` after the action is chosen):

    s = self.stuck.see(self.tick, rec["action"], kind=values.get("screen"), text=values.get("text"),
                       pos=(x, y, map) if found else None, frame=frame)
    if s: rec["stuck"] = s    # next step: steer by self.stuck.suggest(options) (exclude s["repeated"]),
                              # then B, then play out each option and take the first that changes the screen

### Going back where the text says (2026-10-04)

Pewter's badge sits behind an errand. An old man closes the road north of Viridian until the player has fetched
Oak's Parcel from the Mart, carried it back to Oak in Pallet Town, and come back. The general piece is going back
to a place the run has been, because a line named it, and then on again.

**What was there.** A goal can already target a known place (`{place: id}`), and the navigator walks the known door
chain to it. On the live run (pk17–pk20, ticks 5701–9313, 3,900 walking ticks under goals) the navigator offered that
walk on 28 of them.

**Why it fails: the run does not know a place again when it gets back.** For each return to a map the run had been
on, `scripts/reentry_check.py` asks whether the place book named it as before (the grader's map is used only for
scoring). Over the Pokemon logs, 112 of 172 returns (65%) were known again. The live run's map signature reads
Pallet Town as 15 values and Red's house as 9, so a place a goal names is left under one id and re-entered under
another. That is the emulator thread's discovery: the live run sits on 0xC750/0xC751 since its tick 4300
checkpoint, not 0xD35E.

**Re-measured on the new map rule (10e1632).** Two fresh stand-in runs from power-on on the current branch
(`step_profile.py --full` logs the grader's map), and one on Aevilia:

| run | reads | maps | places | wrong place (mixed) |
|---|---|---|---|---|
| Pokemon, power-on, run 1 | 1,274 | 4 | 15 | 1.5% |
| Pokemon, power-on, run 2 | 852 | 4 | 15 | 1.1% |
| Aevilia, from Startham | 1,492 | 1 | 4 (7 without door memory) | 0% |

The new rule mixes little. But until a map has been revisited it falls back to the old rule, and in the first 1,200
steps Red's house 1F reads as 7 signature values and Pallet Town as 7. So 4 maps are split into 15 places.

**Built (anygame/places.py, anygame/landmarks.py):**

- *Door memory.* A door taken again from the very tile it was taken from, arriving on the very tile it arrived on
  before, leads to the place it led to before, whatever the signature reads. It is kept both ways (out is the reverse
  of in). On the Pokemon logs, returns known again went from 65% to 69% (112 to 119 of 172), and places from 205 to
  186. Mixing went from 5.8% to 5.9%. Allowing one tile of slack mixed more (6.6%), so the match is exact.
- *Tried and dropped:* knowing a place by how the screen looks at a tile. Look-alike rooms got merged (mixing 6.2–6.9%).
- *`PlaceBook.route(src, dst)`* gives the first move on the shortest known way over joins walked and doors taken,
  both ways: `{kind: join, dir}` or `{kind: door, x, y, dir}`. A place entered on trial (a new name on an ordinary
  step) borrows the way of the place it was entered from.
- *Landmarks* are names the game writes with a capital and never in lower case, filed where they were said; a
  speaker tag counts three times. On the live logs OAK's place is the lab and MOM's is the house's ground floor
  (`scripts/landmark_check.py`). The goal writer gets each place's `heard_here`, so "take this to PROF.OAK" can
  become `{place: <lab>}`.
- *Errand.* When the way on stalls and a line said here names a known place elsewhere, the run makes three goals: go
  there, talk, and come back to where the way was closed.

**Live check (`scripts/goback_check.py`).** The stand-in plays from power-on, and on its first walking step in
Pallet Town after step 250 it is sent back to Red's house (place id from the grader's map, for choosing only). It
had 300 steps. Before (long-horizon a9e946c), it was sent to 1F and 2F: once it walked into 1F by chance after 233
steps, but the goal never checked as reached; the 2F try never arrived. After (route option), it was sent to 1F three
times and 2F once, and never arrived. On the try with options logged, the route was found ("walk 7 steps back
through the door at (5,5)"). But the next step's signature change put the player in a new place (ids 9, 10, 11 within
20 steps of Pallet Town), and from there no way was known. **Going back works only once a map keeps one name;**
until then the route breaks on the next misread.

Aevilia has no fetch-or-return step the player walks: Tom's "let's talk a bit, but inside" moves the player into the
house by a scripted walk (run 3, ticks 455–459).

**Hand-off.** For long-horizon: `pokemon-red/world-goback.patch` (world.py: the route option when no door chain is
known; goals.py: `heard_here` and its line in the writer's prompt). Errand call site: on a stuck raise on a walking
screen, `errand_from(goalbook.marks, memory.dialogue, here, since)`, then impose its goals in turn. For the emulator
thread, the blocker: a map signature that stays one value per map from the first visit.

**Re-measured on the emulator fixes (17e108c and e80b499).**

| run | returns known again | wrong place (mixed) |
|---|---|---|
| fresh power-on, 1,500 steps (17e108c; e80b499 the same) | 16 of 22 (73%) | 5.1% |
| from long-horizon's tick-8600 save, ticks 8931–9324 (after the map byte settled) | 32 of 34 (94%) | — |
| from the 8600 save, all 1,500 steps (17e108c) | 124 of 130 (95%) | 15.1% |

From power-on the first 1,500 steps still read Pallet Town as 7 values and Red's house 2F as 10. The map locks
only at the first revisit (the emulator thread's limit). e80b499 changes nothing here; it helps after a faint.

On the save, the place book knows 94–95% of returns again, and door memory adds nothing there because the name
alone is enough. But the reading did not stay put. After about tick 9300 the signature moved from 7 to 34895 and
33360, and Oak's lab and Pallet Town read the same two values (lab: 33360 ×261, 34895 ×93; Pallet: 34895 ×378,
33360 ×94). Over the whole run, 15.1% of reads sit in a place that is mostly another map. That is a finding for the
emulator thread: a settled signature that two maps share again later.

Go-back checks:
- From power-on, Pallet Town to Red's house 1F and 2F: no arrival in 2 tries before and 2 tries after, on either
  fix.
- From the 8600 save, Pallet Town back to Oak's lab: arrived after 166 steps before, and not within 300 after. Both
  runs lost Pallet Town to a new place one step after leaving the lab (the byte was still settling), so this is one
  try each and luck decides.

A door known from another place on the very same tiles (`door_any`) raised returns known on the logs from 73% to
76%, and on fresh runs from 80% to 84%. It also raised mixing by 0.3 to 0.7 points, so it is off.

First-visit place naming is being built on the emulator side (05:45Z). These checks are re-run on its commit.

**Re-measured on first-visit naming (90fb48a).**

| run | returns known again | wrong place (mixed) | maps sharing one name |
|---|---|---|---|
| fresh power-on, 1,500 steps | 53 of 56 (95%; 91% without door memory) | 5.1% | Pallet and Blue's house (768); Oak's lab and Red's 2F (129174661) |
| from the 8600 save, 1,500 steps | 124 of 126 (98%) | 37.5% | Red's 1F, Red's 2F and Pallet (512) |

Returns look known because maps now share names. On the save, 37.5% of reads sit in a place that is mostly another
map, against 15.1% on 17e108c.

Go-back checks:
- From power-on to Red's house 1F, before and after: the target place was the place the player stood in (Pallet
  and the house merged), so there was nothing to measure.
- From the save, Pallet back to Oak's lab: the player reached the lab after 268 steps before and 144 after. In
  neither run did the goal check as reached, because the lab came back under a new name.

These are findings for the emulator thread. Logs with the grader's map:
`longhorizon/pk-jev-poweron/lab-door-loop/gaps-{s8600,poweron}-90fb48a-full.jsonl`.
