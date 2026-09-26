# anygame

**One paragraph, any game.** A pack describes what is on the screen, how to read it, what the moves are, and how
to play. [TypeSafe Jev](https://typesafe.ai) plays it live. No model is trained, ever.

```
device ──frames──▶ perception (colours, bars, templates, OCR, open-vocab) ──▶ ~400-token state
                                                                                  │
HUD ◀── frame + boxes + belief bars + action + latency + cost ◀── Jev (one call, all questions) ──▶ tap / swipe
```

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
| `locate` | the cell(s) holding a symbol in a grid read (`row`/`col` filters, `many`) | snake head/food, legal columns |
| `runs` | empty cells that would complete N-in-a-line of a symbol (optionally under gravity) | Connect Four wins and threats; tic-tac-toe, gomoku |
| `around` | what is next to a located cell in each direction, straight `ahead`, `<dir>_free` (open cells that way), `<dir>_space` (flood-fill room that way) | snake |
| `history: 1` | `<id>_prev` (last distinct value), and for a located cell `<id>_moving` / `<id>_reverse` | direction of travel |

Actions are typed. `swipe`, `tap` and `key` are direct; `play` means "pick a slot, then a target cell", and the
runtime asks Jev for the slot and the cell in the same call as the action, so a Clash Royale tick is one request.

**Rules turn beliefs into policy in the same tick.** `if: { noul: q, gte: p }` or `if: { read: id.path,
equals|in|not|gte|lte: v }`, then `exclude: [actions]` (the choice becomes the best remaining action by
probability; `$read` means that read's value, e.g. `$head_reverse`) or `set: { param_question: source_question }`.
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
| Connect Four vs the page's built-in opponent | 4 seeds | 4 wins, every move legal, threats blocked | ~$0.0007 / game |
| Snake, 12x12, 700 ms per step | 4 seeds | alive at the 600-tick cap on 3 of 4, scores 1880–2000 (~37 food, ~40-long snake); one death at tick 460 by self-trapping | ~$0.0085 / 600 ticks |
| 2048 | 2 seeds | 64 and 128 tiles, corner strategy held, never swipes up unless forced | ~$0.005 / 150 ticks |

- Perception is 3–30 ms a tick for a whole board (colour reads); score OCR runs every 4th tick in a worker
  process and never blocks. Jev is 210–220 ms p50 and ~300 ms p95 from this container. The action lands
  270–280 ms p50 and ~370 ms p95 after the frame. When Jev is slower than the pack's `sensor_timeout_s`, the
  rules replay its last answers so a safe move still goes out (it fired 3 times in 2400 Snake ticks).
- A tick is ~$0.00003. A whole Connect Four game costs a tenth of a cent; a 600-tick Snake game under a cent.
- **Connect Four** is the clean demo: the state compiler lists winning and threatened cells, Jev turns that
  and the paragraph into a legal move every time, and the rules make a block or a win a certainty.
- **Snake** is the real-time one. The game steps every 700 ms; the loop makes one decision per step. The rules
  make walls, the body and pockets impossible and Jev steers toward the food. Deaths are self-trapping late in
  a long snake, and the occasional late answer at a corner.
- **2048** is a judgment model playing a search game: it keeps the corner and never swipes up unless forced,
  which is exactly what the paragraph says, and gets to 128–256. Provable with no hardware, not impressive.

Every game here has a demo video: `anygame play … --record dir --log run.jsonl`, then
`anygame render dir --log run.jsonl --out demo.mp4` draws the action, its probabilities, the beliefs, the
rules that fired, latency and cost next to every frame.

## Packs

| Pack | Device | Status |
|---|---|---|
| `connect4` | `web://games/connect4.html` | plays and wins against the page's own opponent; fixtures, tests, rules |
| `snake` | `web://games/snake.html?tick=700` | plays in real time; `around` read, rules, settle, sensor-timeout fallback |
| `2048` | `web://games/2048.html` | plays end to end; fixtures and tests |
| `clash-royale` | `adb://<phone>` | zones, reads, actions, questions and the play paragraph are written; needs your frames for the card templates and the test fixtures (`anygame record`) |

The three web games are single self-contained HTML files under `games/` with a `?seed=` for reproducible runs,
so every pack is testable in CI with no hardware and no account beyond the model key.

## Commands

```bash
anygame packs
anygame play <pack> --device web://…|adb://…|replay://<dir> [--hud 8080] [--max-ticks N] [--sensor none]
anygame eval <pack> [--sensor jev]        # perception tests on the pack's frames; action checks with a sensor
anygame record --device adb://<ip>:5555 --out packs/<pack>/fixtures --seconds 30   # frames for authoring
anygame render <recorded-dir> --log run.jsonl --out demo.mp4                         # video with the decision panel
```

`--sensor none` runs perception and the HUD with no model, for authoring a pack against a live screen.

## Honest notes

- `adb screencap` is 100–250 ms a frame. Fine at 3 Hz; scrcpy's video stream is the path to 10 Hz.
- Open-vocabulary detection on cartoon sprites is hit-or-miss; the `blobs` read (coloured health bars) is the
  reliable fallback and is what the Clash Royale pack uses by default.
- Jev sees only the compiled state: numbers, labels, cells. It never sees pixels.
