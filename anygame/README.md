# anygame

**One paragraph, any game.** A pack describes what is on the screen, how to read it, what the moves are, and how
to play. [TypeSafe Jev](https://typesafe.ai) plays it live. No model is trained, ever.

```
device ──frames──▶ perception (colours, bars, templates, OCR, open-vocab) ──▶ ~400-token state
                                                                                  │
HUD ◀── frame + boxes + belief bars + action + latency + cost ◀── Jev (one call, all questions) ──▶ tap / swipe
```

## The Chrome extension

The whole runtime in a side panel: open a game tab, click the button, pick a pack or describe the game, play.
Frames and input go through the debugger API (trusted events, works on canvases), perception and the compiler
run in TypeScript inside the panel, Jev is called with your own key. No server, no Docker. See
[`ext/`](ext/README.md). `npm test` there runs every bundled pack's fixture tests through the port, headless
Chromium plays the bundled games through it, and with a chat model configured it wins Connect Four and authors a
pack from the panel, end to end.

## When the pack does not understand the screen

Every tick the runtime knows two things about the frame: **which screen it is** (a 16×16 Lab fingerprint,
looked up against the pack's fixtures and every screen it has read well since) and **how well the pack reads it**
(a support score from the reads' own confidences: colour distances, whether a located thing was found, whether
the falling piece was identified). A frame that is neither known nor supported for a couple of ticks is a miss.

A miss goes to the **VLM fallback**: the vision model sees the frame, the pack's typed actions and the goal, acts
now, and says what the screen is. A *transient* (a start prompt, a game-over card, a level-up popup) is
dismissed and memoised by fingerprint, so the next time it costs no model call. A *mode* (a shop, a map, a battle)
comes with a definition, zones, reads, actions, a paragraph, and is merged into the pack only if its reads return
on that frame what the model said they would. Packs carry `modes:` (sub-packs with `when: {read: …}` or
`when: {fingerprint: …}`) and `fingerprints:`, and the learned pack is written back.

The split: Jev plays every supported tick from compiled state (200 ms, text only); the VLM sees pixels only on a
miss and while authoring; the compiler and rules do everything deterministic in between. The VLM's cost decays,
because every screen it handles once is Jev's from then on.

```bash
anygame play snake --device "web://games/snake.html?menu=1" --fallback --goal "snake, arrow keys"   # start prompt and game-over card are unknown to the pack
```

Measured through the extension with GPT-5.6 on Azure as the fallback: the unknown start prompt was dismissed
and learned on the second tick, the pack played, the game-over card was reached. See `ext/test/e2e_hybrid.py`.

## Learning from a demonstration

The author's evidence no longer has to be the blind probe. A **demonstration** is frames plus every input for a
minute or two, from one of three sources: the human (*record me* in the extension: a content script logs keys
and clicks while the panel captures frames), the **explorer** (the VLM plays slowly, one input every few seconds,
each with a one-line intent), or the probe. The digest hands the author the action set as used, click clusters as
candidate zones, the regions that change after inputs, before/after frame pairs, and the intents as raw material
for the paragraph.

## Learning from experience

No model is trained, so the runtime grows the **typed frame** instead. Every game played is an **episode** in a
bank. A loss becomes an **incident**: the last decisions with their frames, Jev's probabilities and the rules
that fired. The chat model revises the pack (derived reads, rules, questions, paragraph; never the zones or the
pixel reads), and the revision is accepted only if it **replays** better than the incumbent on that incident:
Jev's recorded answers go back through the candidate's reads and rules, and the fatal decision must now be
excluded by a rule or separated by a new read, the ordinary decisions must stay allowed, and the screens must
still read (`anygame/learn.py`, `ext/src/core/learn.ts`). A revision then plays on trial: if its episode is
worse than the incumbent's median episode it is reverted. The game restarts by reloading the tab. In the
extension this is *keep learning* on the play button; in the CLI it is `anygame learn`. Replay costs no model
call, so a bad revision is rejected in milliseconds, and it is checked against the earlier incidents too, so a
rule that fits one loss and breaks the rest is out. [ARCHITECTURE.md](ARCHITECTURE.md) has the whole loop and
its mapping onto SIMA 2.

**The loop learns to judge.** Every revision that passes replay is recorded with its shape (guarded or visible,
how many ordinary decisions it blocks, how many rules and reads it adds, whether the paragraph changed); the trial
episode labels it kept or reverted. Once six revisions with both outcomes exist, a small logistic model on that
record (`Calibrator`) is consulted before a new revision goes on trial, and rejects shapes that were reverted
before; until then it is idle. Rules and reads a kept revision added become **lessons** in the pack (`lessons:`),
travel with it into the pool, and are shown to the model when this or a similar game loses next. This is the
part SIMA's loop does not have: the judge and the proposer improve from the record, not only the policy.

**The method behind it** is written up in [METHOD.md](METHOD.md), synthesised from five research notes in
`docs/research/` (representation learning, off-policy evaluation, control theory, decision science, evolutionary
search). Its core: a frozen decider that can be re-asked offline turns "improve the decisions" into a search over
its inputs with an exact oracle. Implemented so far: **re-query** (a revision is judged by what the decider now
answers on the banked states under the new frame, not only by replaying its old answers; on by default in
`anygame learn`), a **value-of-information audit** of every question (forced through the rules on banked
decisions; a question no rule consumes cannot change the action), a **relevance audit** (mutual information of
each read with the coming loss and with the decider's choice; the gap names what the decider ignores), and the
**`predict`** read (a located thing shifted by its last displacement, for the action that lands late). The audits
feed the revision prompt. On the eight-episode Snake run's own bank, the audit found that the learned pack's only
question, `food_reachable_safely`, is consumed by no rule and so never changed an action in forty decisions.

The second slice closes the scoring step: a **counterfactual return** for every candidate (per-decision importance
ratios from the logged probabilities and the re-query, the walk cut at the first tick the candidate would have
left the logged path; a revision must leave more of the banked losses than the incumbent did), a **held-out set**
of ordinary ticks banked from every episode that the decider is re-asked on so a fix for one loss cannot drift
everywhere else, an **option-order A/B** on the banked states, a **conformal floor** for the calibrator (at most a
quarter of revisions as good as the kept ones are refused; no veto until three have been kept), **`margin`**
reads (the room after each move with the decision latency compensated) and a per-tick **`budget_ms`** that lets
the rules act on the decider's last answers when the tick cannot afford it. `anygame audit <pack> --sensor jev`
prints all of it for a bank. On the Snake bank it found that listing `keep` first makes Jev want it 45% of the
time against 20% for no bias and want a rule-excluded move 62% of the time against 28% as authored, and that the
learned pack still owns one of its four banked losses, the pocket death a one-step rule cannot see.
[docs/research/sima2.md](docs/research/sima2.md) reads DeepMind's SIMA 2 report against this design.

**From SIMA 2, built without training a model.** A pack can carry **tasks** (`tasks:`): practice goals with a
verifier over the reads (`done`, one condition or several, held for `hold_ticks`; `when` for availability;
`limit_ticks`; a category from navigate, collect, score, survive, clear, build, avoid). The loop tells the
decider one task at a time beside the paragraph and verifies it every tick; `anygame learn --set-tasks N` lets
the chat model propose new ones from the typed frame and the frame, steered to the weakest category, and the
author writes the first from the demonstration. A completed task (or a win) banks the span as a **positive
incident**: every revision must keep those choices allowed, and the pack that first completes a task yields
lessons, so the loop learns from what worked and not only from the fatal tick; episodes rank by won, then
tasks done, then survival. `anygame suite <packs> --device … --seeds …` is the evaluation suite: per task,
done within its limit and done at all (SIMA's two numbers), per category, against a `reference_ticks` where
the task has one; the pack as written is the held-out number, `--learned` the learned one.
`anygame learn --rate` adds an **episode rater** (the chat model scores sampled frames and the action log 0 to
100 for completion and directedness), used as the score where the pack has none and calibrated against the
trial order the loop already trusts (`anygame audit` reports the agreement). And the input vocabulary grew
for 3D and action games: `key` takes `hold_ms`, `mouse_move` moves the pointer by `dx, dy`, and `chunk` plays
a short key sequence as one decision, which the demonstration digest proposes from recurring key runs.

Measured on Snake from a **naive pack** (no rules, no `around` read, a two-line paragraph), eight episodes with
GPT-5.6 revising and Jev playing, the trial record and lessons on: episode 1 died at tick 51; v2 (rules on free
cells) played 365 ticks; v3 381; v4 408 with score 1500, which is where the hand-written Snake pack sits. Eight
revisions were proposed: three kept, four reverted by trial, one on trial at the end; five lessons were banked.
By the seventh trial the calibrator was active and vetoed a round-one revision as "shaped like ones reverted
before" (keep probability 0.25), and the round-two revision it let through scored 1.00. Total model spend for
the run: about five cents. An earlier six-episode run without the calibrator plateaued at 136 ticks.

The **pool** (`packs/pool.json`) indexes every pack by site and by the fingerprints of its screens
(`anygame stamp` writes them into the packs). The extension checks it when the panel opens, matching the visible
tab by screen when the site is unknown; `anygame go` does the same before authoring anything.

## Point it at a game

```bash
pip install anygame                                   # or: docker run -p 8080:8080 -e OPENROUTER_API_KEY ghcr.io/dhruv123-123/anygame go …
OPENROUTER_API_KEY=… anygame go "web://https://example.com/some-game" --game "Snake, arrow keys"
```

`go` probes the game, has a vision model write the pack, checks the pack against the frames until its
tests pass, plays a short game and lets the model tune the paragraph and rules from the log, caches the pack
under `~/.anygame/packs`, and then plays with the HUD at http://localhost:8080. The second time it skips
straight to playing. `--pack 2048` uses a bundled pack instead of authoring one. `--learn 0` keeps playing and
learning from every loss until you stop it.

### Where the game comes from: pixels or a stream

The runtime does not care how it learns about the game, only that a device gives it frames and, optionally,
**state**. Every derived read, rule and paragraph works the same on both.

| device | what it is | frames | state |
|---|---|---|---|
| `web://<url>` | a page in headless Chromium | screenshots | `#state=window.__state()` evaluates an expression on the page every tick |
| `screen://x,y,w,h` | this computer's screen and input (`pip install anygame[desktop]`: mss + pynput); any window, any game. The one device that shares the person's keyboard and mouse, so the guard rails are on: it pauses after any input it did not send, Ctrl+Alt+Q stops it, and it sends at most 300 inputs a minute | a region of the monitor | no |
| `window://<title>` | one window: inputs are delivered to that window only (X11 XSendEvent, Windows PostMessage) and the person's focus, keyboard and mouse stay theirs. Browsers, toolkits and casual games take them; a game that reads raw input ignores them | that window's rectangle | no |
| `pad://x,y,w,h` | a virtual gamepad (`?backend=uinput` on Linux through python-evdev, `?backend=vigem` on Windows through vgamepad): the game sees a second controller, the person keeps their own input; keys map to buttons and the d-pad, `mouse_move` deflects the right stick | a region of the monitor | no |
| `nested://:99?run=<cmd>` | a display the runtime owns: Xvfb (invisible) or `&viewer=xephyr` (a window on the desktop showing the sandbox), the game launched inside it, frames and input bound to it; the person's desktop is never touched | that display | no |
| `coach://<device>` | suggest, never act: every move is shown on the HUD and performed by the person, or not (`anygame play --coach`); for games whose anti-cheat forbids injected input | the inner device's | the inner device's |
| `stream://ws://…`, `stream://http://…`, `stream://file:…`, `stream://stdin` | a game that publishes its state as JSON (`anygame[stream]` for WebSockets); `?input=screen://…` pairs an input device | the input device's, or blank | the latest JSON object |
| `pyboy://rom.gb`, `adb://host:port`, `replay://dir` | an emulator, a phone, recorded frames | yes | no |
| the Chrome extension | the tab you are looking at, through the debugger API | yes | a state expression in the panel |

State is consumed by two reads: `json` (`path: score`, `parse: int`, `map: {"true": dead, "false": playing}`)
and `json_grid` (a `c<col>r<row>` matrix from lists of coordinates: `symbols: {H: {path: snake, index: 0},
s: {path: snake, slice: [1, null]}, F: {path: food}}`). `packs/snake-state` plays Snake from the page's own
state with the same `locate`, `around`, rules and paragraph as the pixel pack, and its tests are JSON files:

```bash
anygame play snake-state --device "web://games/snake.html?seed=4&tick=700#state=window.__state()"
```

A game that streams its state is the fast path for anything with an API, a mod hook or a telemetry feed; a game
that does not still gets played from pixels. Both end in the same typed frame, so a pack can mix them.
`games/snake_ws.py` is such a game: Snake published over a WebSocket, keys taken back; `test/e2e_stream.py`
plays it through `stream://ws://127.0.0.1:8765` with nothing but the state (passes: 40 ticks, support 1.0, keys
on the socket). `test/e2e_screen.py` is the desktop device live: a virtual display, a real Chromium window in
kiosk mode, frames from the X framebuffer, keys through X; with Jev it played 200 ticks alive with score 60
(`python test/e2e_screen.py jev 200`; it starts an Xvfb when there is no display). Measured:
`snake-state` with Jev, 400 ticks, alive at the cap with score 140, 108 decisions, perception 27 ms p50 (the
page expression), Jev 190 ms p50; no pixel was read.

### Deploying it

```bash
docker compose up                                              # Jev plays 2048 at http://localhost:8080, no hardware
docker build -t anygame . && docker run --rm anygame eval snake # the image carries every extra and the tests
docker run --rm -e OPENROUTER_API_KEY anygame learn snake --device "web://games/snake.html?tick=700" --episodes 3
scripts/test-image.sh anygame                                  # proves the image: everything below, inside the container
```

Measured inside the image (`scripts/test-image.sh`, Playwright 1.56 base, every extra installed): 43 unit tests
pass (one skipped: no display at that point), every bundled pack's fixtures pass, Snake plays from pixels through
`web://`, from a WebSocket state stream through `stream://`, and from a virtual display through `screen://`
(Xvfb, a kiosk Chromium window, mss and pynput); with Jev through the desktop device, 150 ticks alive with 49
keystrokes and score 40. Behind a proxy with its own CA: `docker build --secret id=ca,src=ca.crt .` and
`CA_BUNDLE=ca.crt scripts/test-image.sh`.

`scripts/dist.sh` builds the two things that ship: the Python wheel (`pip install dist/anygame-*.whl[desktop,stream]`
gives the `anygame` command: the CLI, the desktop device, the learning loop, the HUD) and the Chrome extension
(`ext/anygame-extension.zip`, load it unpacked at `chrome://extensions`). No server, no Docker required; the
Dockerfile is for the CLI on a machine without Python.

### CLM: the same protocol, ten times faster

Stanford and NVIDIA's [CLM-8B](https://github.com/Contrastive-LM/CLM) (September 2026, Apache 2.0) is a
contrastive System One model: it embeds the state and each candidate action and ranks by similarity instead of
generating, at about 16–28 ms per decision on one RTX 4090 against Jev's ~150–200 ms, with candidate actions
cached across requests. It serves the same `/v1/systemone` protocol with the same `noul`, `choice` and `score`
questions, so it is a sensor here, not a port: `--sensor clm` (or `clm:<base url>`) in the CLI, "CLM" in the
extension's sensor list, `CLM_BASE_URL` / `CLM_MODEL` / `CLM_API_KEY` in the environment; run it with
`vllm serve Qwen/Qwen3-8B --runner pooling --port 8090` and `clm-serve` from the `contrastive-lm` package. A pack's
typed action set is exactly the stable candidate list CLM caches, so a 6 Hz game could tick at 20 Hz. Two
differences to keep in mind: CLM only ranks the candidates it is given (every pack already offers `wait` or
`keep`, and the rules guard the rest), and there is no hosted API yet, so it needs a GPU. This container has
none, so the wiring is proven against `test/clm_stub.py`, a stand-in that speaks the protocol faithfully.

### From scratch: five games with their packs held out

`scripts/from_scratch.sh` runs `anygame go --fresh --explore 60 --learn 6`: no pack, no pool, no lessons; the vision
model explores for a minute, the author writes a pack from that demonstration, Jev plays, every loss becomes a
replay-verified revision, the tab reloads. Same GPT-5.6 and Jev as everywhere else; every number below is from
the run itself.

| game | authored | first episode | best episode | revisions kept / reverted |
|---|---|---|---|---|
| Snake | 2 rounds | 48 ticks, dead | 400 ticks, alive at the cap (episodes 5 and 6) | 3 / 1 |
| Tic-tac-toe | 2 rounds | 14 ticks, lost | 53 ticks, deadlocked with one cell left | 3 / 2 |
| Connect Four | 1 round | 42 ticks, won | won all six games; nothing to revise | 0 / 0 |
| 2048 | 2 rounds | 194 ticks, score 500 | 300 ticks alive at the cap, score 1484 | 2 / 0 |
| a space shooter | 5 rounds, third attempt | 191 ticks, game over | 400 ticks alive at the cap, episodes 2 to 6 | 1 / 0 |

What the runs taught, and what changed because of them: an authored box a few pixels outside the frame used to
crash the loader (now clamped); a game that ends without the pack noticing used to sit at the tick cap as if it
had survived (a stalled screen now ends the episode and the vision model labels it won, lost, draw or playing,
and a stall while still playing counts as a loss); a pack whose `act_when` never opens used to wait forever with
nothing to learn from (that stall is now an incident the revision must open); the author did not know what a
`blobs` read returns, so the shooter's bullets took three attempts (documented now). Tic-tac-toe is the honest
failure: its packs either lose in 14 ticks or deadlock, and six episodes of revisions did not find the move
generator a person writes in one line (`legal: {kind: locate, symbol: "."}`); the loop needs more episodes there,
or a lesson from the pool, which was held out. Snake's authored score read is wrong (it reads a digit), which the
loop never notices because score is not the reward.

### Which model goes where

Jev always goes to OpenRouter (`OPENROUTER_API_KEY`) or `JEV_BASE_URL`. Every other model call, the authoring
model and any `llm:` sensor, goes wherever `ANYGAME_LLM_BASE` points:

```bash
# default: OpenRouter, any model id
ANYGAME_LLM_MODEL=anthropic/claude-sonnet-5
# Azure OpenAI / Foundry v1 endpoint: paste the portal's URL as is, the model is your deployment name
ANYGAME_LLM_BASE=https://<resource>.services.ai.azure.com/openai/v1/responses  ANYGAME_LLM_KEY=<api key>  ANYGAME_LLM_MODEL=<deployment>
# classic Azure OpenAI deployments endpoint
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
| `margin` | the room left *after* each move with the decision latency compensated (`lag` cells advance while the decider thinks): `now`, per direction the reachable room from where the mover will be when the action has landed (0 = death that way), `<dir>_ok` (keeps at least `1-alpha` of the room: a discrete control barrier condition), `safe`, `best`; a numeric form gives a number's distance to its bounds | snake (pockets), bars, timers |
| `tetris` | the falling piece, the stack's features, and the reachable landings with computed consequences as a typed choice; a `macro` action plays the choice as keys and the next spawn verifies it | tetris |
| `history: 1` | `<id>_prev` (last distinct value), and for a located cell `<id>_moving` / `<id>_reverse` | direction of travel |

Actions are typed. `swipe`, `tap` and `key` are direct (`key` with `hold_ms` is a held key; `chunk` plays a short
key sequence as one decision; `mouse_move` moves the pointer by `dx, dy` for a camera or a cursor); `play` means "pick a slot, then a target cell", and the
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

What the first real runs taught, with GPT-5.6 on Azure as the author and tic-tac-toe as the target, all
three now built into the loop:

1. **A model will lower the bar.** Run one produced a pack whose O read was wrong, then made round two "pass" by
   rewriting the expectations to what the wrong read returned. Now, when a passing round changes an
   expectation, the author shows the model the frame again and asks it to confirm each new value on its own;
   a "no" fails the round with "fix the read, not the test".
2. **Probe the transient states.** Run two passed perception in one round and stopped after two ticks: the
   status read had never seen the opponent's turn (the page answers in 350 ms) and fell to `otherwise:
   game_over`. The probe now looks right after every input as well as once settled.
3. **Show the tuner the frames.** The tuning round gets the play's middle and last frames with the digest, and a
   stop within three ticks is called out as a read missing a state.

Run three: perception passed in one round, the pack played full games from the first play, and the tune round
fixed the end state. That pack is `packs/tictactoe-authored`, untouched, next to the hand-written
`packs/tictactoe`: same reads, same rules, a longer paragraph.

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
questions: `jev`, `random` (the floor: uniform choices, every belief 0.5), or `llm:<model>` (any chat model,
answering the same questions in JSON with probabilities of 1.0 on its choice). Because the packs strip the
counting out, the numbers compare judgment, latency and cost, nothing else.

Connect Four, the same pack, the same six seeds, against the page's own opponent:

| Sensor | Wins / draws / losses | Decision p50 | Cost per game |
|---|---|---|---|
| Jev (OpenRouter) | 5 / 1 / 0 | 200 ms | $0.0007 |
| GPT-5.6 (Azure) | 5 / 1 / 0 | 2.9 s | not reported by Azure |
| random | 0 / 0 / 3 | 0 ms | $0 |

Both models play the compiled game perfectly; the paragraph plus `runs` reads leave nothing for a bigger
model to add on a turn-based board. The fifteen-fold latency gap is the whole difference, and it is the
difference between playable and not on Snake or Tetris.

## Packs

| Pack | Device | Status |
|---|---|---|
| `connect4` | `web://games/connect4.html` | plays and wins against the page's own opponent; fixtures, tests, rules |
| `snake` | `web://games/snake.html?tick=700` | plays in real time; `around` read, rules, settle, sensor-timeout fallback |
| `2048` | `web://games/2048.html` | plays end to end; fixtures and tests |
| `tictactoe` | `web://games/tictactoe.html` | the authoring target; draws against the page's opponent; `accent` read, `only` rule |
| `tictactoe-authored` | `web://games/tictactoe.html` | written entirely by GPT-5.6 through `anygame author`, no human edits |
| `tetris` | `web://games/tetris.html?level=N` | compiled landings, macro actions, post-check; fixtures and tests |
| `2048gb` | `pyboy://roms/2048gb/2048.gb` | the Game Boy 2048 in an emulator; OCR board read; fixture and test |
| `connect4-yellow` | `web://games/connect4.html?ai=0` | the red pack from yellow's side, for battles |
| `clash-royale` | `adb://<phone>` | zones, reads, actions, questions and the play paragraph are written; needs your frames for the card templates and the test fixtures (`anygame record`) |

The three web games are single self-contained HTML files under `games/` with a `?seed=` for reproducible runs,
so every pack is testable in CI with no hardware and no account beyond the model key.

## Commands

```bash
anygame packs
anygame play <pack> --device web://…[#state=<js>]|screen://x,y,w,h|window://<title>|pad://x,y,w,h|nested://:99?run=…|coach://<device>|stream://ws://…|pyboy://<rom>|adb://…|replay://<dir> [--hud 8080] [--max-ticks N] [--sensor none] [--coach]
anygame eval <pack> [--sensor jev]        # perception tests on the pack's frames; action checks with a sensor
anygame audit <pack> [--bank DIR] [--sensor jev]   # what the bank says: question value, ignored reads, option-order A/B, counterfactual return, tasks, rater
anygame suite <pack,pack> --device "web://games/snake.html?seed={seed}" --seeds 1,2,3 [--learned] [--out suite.jsonl]   # tasks done within the limit and at all, per category
anygame record --device adb://<ip>:5555 --out packs/<pack>/fixtures --seconds 30   # frames for authoring
anygame render <recorded-dir> --log run.jsonl --out demo.mp4                         # video with the decision panel
anygame go <device> [--game "…"] [--play "…"] [--pack <bundled>] [--learn N]   # pool → author if needed → play; --learn: episodes and revisions
anygame author --device <url> --game "<name>" --out packs/<name> [--play "…"] [--rounds 3] [--play-ticks 40 --tune 2] [--demo <dir>]
anygame explore --device <url> --out <dir> --seconds 90 --game "…"        # the vision model plays and writes a demonstration
anygame play <pack> --device <url> --fallback [--goal "…"]                # VLM on unknown screens; learned pack written next to the original
anygame learn <pack> --device <url> --episodes 5 [--fallback] [--max-ticks N]   # episodes; a loss → a replay-verified revision; keep what plays better
anygame stamp [pack …]                                                    # fixture fingerprints into pack.yaml, for the pool
anygame battle <pack-a> <pack-b> --device <url> [--sensor-a …] [--sensor-b …]
anygame bench <pack> --device "<url with {seed}>" --sensor jev|random|llm:<model> --seeds 1,2,3 [--score-read score]
```

`--sensor none` runs perception and the HUD with no model, for authoring a pack against a live screen.

## Acting without taking the computer over

Every way of acting goes through one `Device` interface; what differs is where the inputs land. The extension
acts on one tab through the debugger API. `stream://` hands inputs to the game's own socket. `window://` posts
them to one window, `pad://` presents a virtual controller, `nested://` runs the game on a display the runtime
owns, and `coach://` only suggests. `screen://` is the one path that drives the real keyboard and mouse, and it
carries the guard rails: a listener marks any input the device did not inject itself (its own injections are
recognised by timing) and pauses acting for three seconds while the loop keeps reading and says why on the HUD;
Ctrl+Alt+Q stops the run; and an action budget drops and counts anything past 300 inputs a minute, so a loop that
goes wrong cannot flood the game. The pack's `act` list is the only input vocabulary the loop can ever use, so an
allowlist is structural. The honest limits: synthetic window events are ignored by games that read raw input, a
virtual pad only helps games that take one, and anti-cheat systems treat every injected input as cheating, which
is what coach mode is for.

## Honest notes

- `adb screencap` is 100–250 ms a frame. Fine at 3 Hz; scrcpy's video stream is the path to 10 Hz.
- Open-vocabulary detection on cartoon sprites is hit-or-miss; the `blobs` read (coloured health bars) is the
  reliable fallback and is what the Clash Royale pack uses by default.
- Jev sees only the compiled state: numbers, labels, cells. It never sees pixels.
