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
