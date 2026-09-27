# anygame

**One paragraph, any game.** A pack describes what is on the screen, how to read it, what the moves are, and how
to play. [TypeSafe Jev](https://typesafe.ai) plays it live. No model is trained, ever.

```
device ──frames──▶ perception (colours, bars, templates, OCR, open-vocab) ──▶ ~400-token state
                                                                                  │
HUD ◀── frame + boxes + belief bars + action + latency + cost ◀── Jev (one call, all questions) ──▶ tap / swipe
```

## Point it at a game

```bash
pip install anygame                                   # or: docker run -p 8080:8080 -e OPENROUTER_API_KEY ghcr.io/dhruv123-123/anygame go …
OPENROUTER_API_KEY=… anygame go "web://https://example.com/some-game" --game "Snake, arrow keys"
```

`go` probes the game, has a vision model write the pack, checks the pack against the frames until its
tests pass, plays a short game and lets the model tune the paragraph and rules from the log, caches the pack
under `~/.anygame/packs`, and then plays with the HUD at http://localhost:8080. The second time it skips
straight to playing. `--pack 2048` uses a bundled pack instead of authoring one.

### Which model goes where

Jev always goes to OpenRouter (`OPENROUTER_API_KEY`) or `JEV_BASE_URL`. Every other model call, the authoring
model and any `llm:` sensor, goes wherever `ANYGAME_LLM_BASE` points:

```bash
# default: OpenRouter, any model id
ANYGAME_LLM_MODEL=anthropic/claude-sonnet-5
# Azure OpenAI: the model is your deployment name
ANYGAME_LLM_BASE=https://<resource>.openai.azure.com  ANYGAME_LLM_KEY=<api key>  ANYGAME_LLM_MODEL=<deployment>  ANYGAME_LLM_API_VERSION=2024-10-21
# Azure AI Foundry serverless models endpoint
ANYGAME_LLM_BASE=https://<resource>.services.ai.azure.com  ANYGAME_LLM_KEY=<key>  ANYGAME_LLM_MODEL=<model name>
```

The API shape is picked from the host (`ANYGAME_LLM_API=azure|azure-models|openai` overrides it).

## Watch it in one command

```bash
OPENROUTER_API_KEY=… docker compose up        # then open http://localhost:8080
```

That plays 2048 in a browser inside the container with nothing else attached. Other games:

```bash
PACK=connect4 DEVICE="web://games/connect4.html" docker compose up         # watch it block, then win
PACK=snake DEVICE="web://games/snake.html?tick=700" docker compose up      # real time, one decision per step
```

For a phone:

```bash
# phone: Settings → Developer options → Wireless debugging → pair
DEVICE=adb://192.168.1.20:5555 PACK=clash-royale docker compose run --service-ports anygame
```

Three steps: a key, a device, a pack name.

## What a pack is

```yaml
game: connect4
zones:
  board:   { rect: [0.02, 0.11, 0.95, 0.94], grid: [7, 6] }        # normalized; scales to any screen
  columns: { rect: [0.02, 0.11, 0.95, 0.94], grid: [7, 1] }        # one-row grid: cells are c1..c7
read:
  board:     { kind: color, zone: board, as: matrix, options: { ".": "#1d4ed8", R: "#ef4444", Y: "#facc15" } }
  status:    { kind: color, zone: status, options: { our_turn: "#ef4444", their_turn: "#eabf0b", we_won: … } }
  r_wins_at: { kind: runs, in: board, symbol: R, length: 4, gravity: down }   # drop here and R has four
  y_wins_at: { kind: runs, in: board, symbol: Y, length: 4, gravity: down }   # Y drops here and wins: block it
  legal:     { kind: locate, in: board, symbol: ".", row: 1, many: true }
act:
  - { id: drop, kind: tap, zone: columns, description: "drop a piece in a column" }
act_when:  { read: status, equals: our_turn }
stop_when: { read: status, in: [we_won, we_lost, draw] }
play: >
  We are R. Priorities: if r_wins_at is not empty, drop in that column; else if y_wins_at is not empty,
  drop there to block; else prefer the centre and cells that extend your own lines…
questions:
  - { id: must_block, type: noul, instructions: Is y_wins_at non-empty?, criteria: { true: …, false: … } }
  - { id: threat_column, type: choice, instructions: The column of the first cell in y_wins_at, or none., criteria: { none: …, c1: …, … } }
rules:
  - { if: { noul: must_block, gte: 0.5 }, set: { drop__cell: threat_column } }
tests:
  - { frame: fixtures/threat.png, expect: { status: our_turn }, expect_action: { is: drop }, expect_cell: c4 }
```

Perception is layered and the cheap layers come first: a colour read is ~1 ms (a whole 12x12 grid in 3 ms), a
template match ~5 ms, OCR ~200–1000 ms, an open-vocabulary detector (YOLO-World, `pip install anygame[vocab]`)
~300 ms on CPU. Most of a game's state is the first two layers; 2048 needs zero OCR on the board because every
tile value has its own colour. Templates are crops you paste into the pack's folder — four card icons is a
deck, and that is the whole "training".

**The state compiler does the counting; Jev does the judgment.** Jev is a fast judgment model that cannot
reliably count cells or compare numbers, so the pack has derived reads that turn pixels into facts it can match
on:

| read | gives | used by |
|---|---|---|
| `color` with `stat: accent` | the colour of whatever is drawn on a cell instead of its background | tic-tac-toe X/O, pieces, icons |
| `locate` | the cell(s) holding a symbol in a grid read (`row`/`col` filters, `many`) | snake head/food, legal columns |
| `runs` | empty cells that would complete N-in-a-line of a symbol (optionally under gravity) | Connect Four wins and threats; tic-tac-toe, gomoku |
| `around` | what is next to a located cell in each direction, straight `ahead`, `<dir>_free` (open cells that way), `<dir>_space` (flood-fill room that way) | snake |
| `tetris` | the falling piece, the stack's features, and the reachable landings with computed consequences as a typed choice; a `macro` action plays the choice as keys and the next spawn verifies it | tetris |
| `history: 1` | `<id>_prev` (last distinct value), and for a located cell `<id>_moving` / `<id>_reverse` | direction of travel |

Actions are typed. `swipe`, `tap` and `key` are direct; `play` means "pick a slot, then a target cell", and the
runtime asks Jev for the slot and the cell in the same call as the action, so a Clash Royale tick is one request;
`macro` means "pick one of the options a read computed" and plays it as a key sequence.

**Rules turn beliefs into policy in the same tick.** `if: { noul: q, gte: p }` or `if: { read: id.path,
equals|in|not|gte|lte: v }`, then `exclude: [actions]` (the choice becomes the best remaining action by
probability; `$read` means that read's value, e.g. `$head_reverse`), `set: { param_question: source_question }`,
`avoid: { param_question: read }` (drop the cells a read lists) or `only: { param_question: read }` (offer just them).
Snake's rules say "never move into a wall, a body cell or a pocket smaller than the snake"; Jev picks among what
is left, toward the food.

Things the loop enforces without the model: an action that changed nothing on screen is not offered again
until the screen changes (per parameter: `drop→c4` is dropped, `drop` stays); a read marked `every: N` is
refreshed every N ticks in a background thread so a slow OCR never stalls a decision; `settle: screen_change`
makes the loop wait for the screen to change after an action before deciding again (one decision per game
step, so a queued turn is never re-decided from a stale frame); `act_when` waits for your turn; `stop_when` ends
the game; a sensor error costs one tick, not the run.

## Measured: three games, headless Chromium, real Jev through OpenRouter

| Game | Runs | Result | Cost |
|---|---|---|---|
| Connect Four vs the page's built-in opponent | 6 seeds | 5 wins, 1 draw, 0 losses; every move legal, every threat blocked | ~$0.0007 / game |
| Snake, 12x12, 700 ms per step | 4 seeds | alive at the 600-tick cap on 3 of 4, scores 1880–2000 (~37 food, ~40-long snake); one death at tick 460 by self-trapping | ~$0.0085 / 600 ticks |
| 2048 | 2 seeds | 64 and 128 tiles, corner strategy held, never swipes up unless forced | ~$0.005 / 150 ticks |

- Perception is 3–30 ms a tick for a whole board (colour reads); score OCR runs every 4th tick in a worker
  process and never blocks. Jev is 210–220 ms p50 and ~300 ms p95 from this container. The action lands
  270–280 ms p50 and ~370 ms p95 after the frame. When Jev is slower than the pack's `sensor_timeout_s`, the
  rules replay its last answers so a safe move still goes out (it fired 3 times in 2400 Snake ticks).
- A tick is ~$0.00003. A whole Connect Four game costs a tenth of a cent; a 600-tick Snake game under a cent.
- **Connect Four** is the clean demo: the state compiler lists winning, threatened and poisoned cells, Jev
  turns that and the paragraph into a legal move every time, and the rules make a block or a win a certainty
  and a poisoned column impossible. Before the `hands` read it lost 1 of 6 by giving Y a win on top of its
  own piece; after it, none.
- **Snake** is the real-time one. The game steps every 700 ms; the loop makes one decision per step. The rules
  make walls, the body and pockets impossible and Jev steers toward the food. Deaths are self-trapping late in
  a long snake, and the occasional late answer at a corner.
- **2048** is a judgment model playing a search game: it keeps the corner and never swipes up unless forced,
  which is exactly what the paragraph says, and gets to 128–256. Provable with no hardware, not impressive.

Every game here has a demo video: `anygame play … --record dir --log run.jsonl`, then
`anygame render dir --log run.jsonl --out demo.mp4` draws the action, its probabilities, the beliefs, the
rules that fired, latency and cost next to every frame.

## Tetris: the compiler enumerates, Jev chooses

```bash
anygame play tetris --device "web://games/tetris.html?level=5"
```

A frame of Tetris never reaches the model as a frame. The `tetris` read turns the board grid into the falling
piece (shape, rotation, column, matched against the 19 tetromino orientations), the stack's features (heights,
holes, bumpiness, the well), and **every reachable landing of that piece, dropped in simulation, with its
consequences computed**: lines cleared, holes made, height afterwards, whether the well stays open. The top six
become a typed choice:

```
landings:
  a: "rot2 col4: clears 2, holes +0, height 0, bumpiness 0, keeps well"
  b: "rot1 col4: clears 1, holes +0, height 2, bumpiness 4, keeps well"
  …
```

Jev picks a letter. The `macro` action turns it into keys (rotate, move, hard drop), and on the next spawn the
compiler checks the stack is exactly what the chosen landing predicted. One decision per piece instead of per
frame, and a `reachable` filter that shrinks the list when a decision comes late, so a 200 ms model plays a
60 fps game without being frame perfect.

Measured, real Jev through OpenRouter, seed 7, 150-piece cap, one run per level:

| Level (gravity) | Pieces | Lines | Placements verified | Jev p50 / p95 | Cost |
|---|---|---|---|---|---|
| 1 (800 ms/row) | 147, alive | 49 | 146 / 146 | 200 / 280 ms | $0.009 |
| 5 (520 ms/row) | 150, alive | 49 | 149 / 149 | 202 / 282 ms | $0.010 |
| 9 (240 ms/row) | 150, alive | 55 | 149 / 149 | 195 / 269 ms | $0.010 |
| random sensor, level 1, 3 seeds | 29 on average, dead | 0 | | | $0 |

The random sensor picks among the same six computed options and dies in thirty pieces with no lines, so the
ranking is not the player; the choice is. At level 9 a piece falls a row every 240 ms and the loop still
decides once per piece, because the decision lands before the piece has fallen far and `reachable` keeps the
list honest when it has not.

This is the general pattern for any game with a small action set and a cheap world model, and it is the part
of this repo that is actually new: **candidate enumeration with compiled consequences, then a typed choice.**
`runs` in Connect Four is the one-line version; `tetris` is the full one. Puyo, Dr. Mario, 2048 (simulate all
four swipes) and card placements in Clash Royale are the same read with a different simulator.

## Game Boy: same paragraph, different machine

```bash
anygame play 2048gb --device pyboy://roms/2048gb/2048.gb        # Sanqui's 2048gb (Zlib) in the PyBoy emulator
```

`pyboy://<rom.gb>` is a device like any other: frames are the 160x144 screen scaled up, keys are the pad,
swipes map to the d-pad and taps to A, so a pack written for a touch screen plays unchanged. The emulator
advances by wall-clock time only when the loop asks for a frame, so no game time passes between a frame and
the action decided on it. The `2048gb` pack is the web 2048 pack with the perception swapped (pixel-font
digits are an OCR read instead of tile colours) and the corner moved; the paragraph is the same. Any homebrew
or your own dumped ROM works the same way; only the Zlib-licensed one ships in the repo.

## Let a slow model write the pack

```bash
anygame author --device "web://games/tictactoe.html" --game "Tic-tac-toe, we are X" --out packs/tictactoe --play-ticks 30
```

The runtime probes the game (start screen, then after taps and arrow keys), hands the frames to a vision
model (Claude Sonnet through OpenRouter by default, `--model` for any other) with a 50 px pixel grid drawn on
them, the dominant colours as measured hex codes, the pack format and three real packs, and asks for a
pack.yaml with tests over those frames. Then it loads the pack, runs every read on every frame, and sends the
model exactly what its reads saw next to the images, so it corrects colours, rects and expectations. Up to
`--rounds` of that; the pack is done when `anygame eval` passes. Then `--play-ticks N --tune K` plays it, hands
the model a digest of the run (outcome, what each action did, screen-unchanged waits, which rules fired, sampled
ticks with the state, probabilities and beliefs) and lets it revise the paragraph, questions and rules K times;
the best-playing pack that still passes its tests is kept. That closes the second loop: a pack can be
perceptually right and play badly, and now the model sees that too.

The layering is the point: the slow model authors once, the state compiler counts every tick, the fast model
judges every tick, rules guard every tick, fixtures prove perception before a dollar is spent.

The tic-tac-toe pack in this repo came out of that loop's checker in one round: the `accent` colour stat
(the colour of whatever is drawn on a cell, so X and O are colour reads) and the `only` rule (offer just the
cells `empty` lists) were the two things the format needed for it. Two games against the page's own
win-block-centre opponent: two draws, which is the right result.

## Battles and benchmarks

```bash
anygame battle connect4 connect4-yellow --device "web://games/connect4.html?ai=0" --sensor-a jev --sensor-b llm:openai/gpt-4o-mini
anygame bench connect4 --device "web://games/connect4.html?seed={seed}" --sensor jev --seeds 1,2,3,4,5,6 --append results.jsonl
anygame bench snake --device "web://games/snake.html?seed={seed}&tick=700" --sensor random --score-read score
```

A **battle** is two packs on one screen, each acting only when its own `act_when` holds; the yellow pack is
the red one with the symbols swapped, so the only thing that differs between two players is what they were
told. Write two paragraphs, let them fight for a tenth of a cent.

A **bench** is one pack over several seeds with one sensor, and a sensor is anything that answers the pack's
questions: `jev`, `random` (the floor: uniform choices, every belief 0.5), or `llm:<model>` (any chat model
on OpenRouter, answering the same questions in JSON with probabilities of 1.0 on its choice). Because the
packs strip the counting out, the numbers compare judgment, latency and cost, nothing else.

## Packs

| Pack | Device | Status |
|---|---|---|
| `connect4` | `web://games/connect4.html` | plays and wins against the page's own opponent; fixtures, tests, rules |
| `snake` | `web://games/snake.html?tick=700` | plays in real time; `around` read, rules, settle, sensor-timeout fallback |
| `2048` | `web://games/2048.html` | plays end to end; fixtures and tests |
| `tictactoe` | `web://games/tictactoe.html` | the authoring target; draws against the page's opponent; `accent` read, `only` rule |
| `tetris` | `web://games/tetris.html?level=N` | compiled landings, macro actions, post-check; fixtures and tests |
| `2048gb` | `pyboy://roms/2048gb/2048.gb` | the Game Boy 2048 in an emulator; OCR board read; fixture and test |
| `connect4-yellow` | `web://games/connect4.html?ai=0` | the red pack from yellow's side, for battles |
| `clash-royale` | `adb://<phone>` | zones, reads, actions, questions and the play paragraph are written; needs your frames for the card templates and the test fixtures (`anygame record`) |

The three web games are single self-contained HTML files under `games/` with a `?seed=` for reproducible runs,
so every pack is testable in CI with no hardware and no account beyond the model key.

## Commands

```bash
anygame packs
anygame play <pack> --device web://…|pyboy://<rom>|adb://…|replay://<dir> [--hud 8080] [--max-ticks N] [--sensor none]
anygame eval <pack> [--sensor jev]        # perception tests on the pack's frames; action checks with a sensor
anygame record --device adb://<ip>:5555 --out packs/<pack>/fixtures --seconds 30   # frames for authoring
anygame render <recorded-dir> --log run.jsonl --out demo.mp4                         # video with the decision panel
anygame go <device> [--game "…"] [--play "…"] [--pack <bundled>]        # author if needed, cache, play with HUD
anygame author --device <url> --game "<name>" --out packs/<name> [--play "…"] [--rounds 3] [--play-ticks 40 --tune 2] [--model …]
anygame battle <pack-a> <pack-b> --device <url> [--sensor-a …] [--sensor-b …]
anygame bench <pack> --device "<url with {seed}>" --sensor jev|random|llm:<model> --seeds 1,2,3 [--score-read score]
```

`--sensor none` runs perception and the HUD with no model, for authoring a pack against a live screen.

## Honest notes

- `adb screencap` is 100–250 ms a frame. Fine at 3 Hz; scrcpy's video stream is the path to 10 Hz.
- Open-vocabulary detection on cartoon sprites is hit-or-miss; the `blobs` read (coloured health bars) is the
  reliable fallback and is what the Clash Royale pack uses by default.
- Jev sees only the compiled state: numbers, labels, cells. It never sees pixels.
