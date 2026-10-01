# How anygame is put together

anygame is an application that lives on a computer, looks at whatever game is on the screen, and plays it
with a 200 ms judgment model. It learns every game the same way: a **pack** is the typed contract between
one game and the model, and everything the system learns is a change to that pack, never to a model's
weights. This document is the parse pipeline, the structure it feeds, and the loop that grows it.

## 1. The pipeline: pixels to a typed action

Every tick is the same sequence in both runtimes (`anygame/loop.py` and `ext/src/core/loop.ts`):

```
device ─▶ frame ─▶ fingerprint ─▶ classify (which screen?) ─▶ reads ─▶ present ─▶ history ─▶ derived reads
                                                                                             │
   tap · swipe · key ◀─ act ◀─ rules ◀─ Jev (one call, all questions) ◀─ questions ◀─ typed frame + support
```

| stage | contract | where |
|---|---|---|
| **device** | `frame() → RGB image`, optional `state() → JSON`, `tap`, `swipe`, `key`, `reload` | a browser tab through the debugger API, Playwright, the computer's screen (mss + pynput), a state stream (WebSocket, HTTP, file, stdin), ADB, PyBoy |
| **fingerprint** | 16×16 Lab grid of the frame; distance < 25 same layout, > 40 a different screen | `fingerprint.*` |
| **classify** | the nearest known fingerprint names the screen: `main`, a `mode`, or a `transient:` | `Agent.classify` |
| **reads** | each read turns a zone's pixels into a value with a confidence: colour, bar, OCR, templates, open-vocab; or picks it out of the device's state: `json`, `json_grid` | `perceive/`, `perceive/state.py`, `reads.ts` |
| **present** | grid reads `as: matrix` become rows of characters, the form models read best | `_present` / `present` |
| **history** | `<id>_prev`, `<id>_moving`, `<id>_reverse` for reads with `history: 1` | `observe` |
| **derived reads** | the arithmetic the model must never do: `locate`, `runs`, `around`, `tetris` landings | `observe` |
| **support** | mean confidence of the reads (a mode is judged on its own reads); below 0.7 the screen is a miss | `Agent.support` |
| **questions** | the pack's questions plus one `action` choice and its parameters, offered from the typed frame | `Agent.questions` |
| **Jev** | one request: `{game, how_to_play, screen, recent_actions, …}` and the questions; answers with probabilities | `sensors.*` |
| **rules** | `if: {read…}` or `if: {noul…}` → `exclude`, `set`, `avoid`, `only`; policy in the same tick | `applyRules` |
| **act** | the chosen typed action, with its parameter, becomes device input | `Agent.act` |

Everything before Jev is deterministic and costs about 3 ms on a 12×12 grid. Jev never sees a pixel: it sees
the **typed frame**, the `screen` object made of the reads, presented, with history and derived facts.

**Two sources of truth, one frame.** A game is either watched (pixels through a device) or listened to (a state
stream: a JSON object the game publishes over a WebSocket, an HTTP endpoint, a file, stdin, or an expression on
its own page). Pixel reads and state reads land in the same `values`, so `locate`, `runs`, `around`, the rules and
the paragraph do not know which one fed them, and a pack may use both (the board from the stream, a popup from
the screen). Support is computed the same way: a state read is 1.0 when its path resolves and 0 when it does not,
so a stream that goes quiet is a miss like any unreadable screen.

## 2. The structure: the pack

A pack is one YAML file and a folder of fixture screenshots. Its sections are the layers of the pipeline:

```yaml
game: snake
screen: { size: [540, 560] }
zones:      # where things are (normalized rects, grids of named cells)
read:       # how pixels become values (kind, zone, colours, symbol, …)  ← pixel reads and derived reads
act:        # the typed actions (tap a cell, swipe, key, macro, wait)
play:       # the paragraph: what the game is and how to play it
questions:  # what Jev is asked every tick (noul beliefs, choices, scores)
rules:      # beliefs and reads become policy: exclude, set, avoid, only
act_when / stop_when / settle / tick_hz / sensor_timeout_s / budget_ms
tasks:      # practice goals with a verifier over the reads (done, when, hold_ticks, limit_ticks, category)
tests:      # fixtures with the exact values the reads must produce
modes:      # sub-packs for other screens (a shop, a map), each with a `when`
fingerprints:   # screen name → base64 fingerprint (main and every mode and transient)
pool:       # which sites this pack is for
```

The pack is versioned by content: `dump_pack` / `dumpPack` write it back after every change, and the
extension keeps authored and learned packs in its storage under the page they were learned on.

## 3. Where each kind of learning grows the structure

There is no training step. Learning is growing the pack, and every growth is verified before it is kept.

| what happens | what is learned | verified by |
|---|---|---|
| a screen the pack cannot read (support < 0.7 for two ticks) | the VLM acts now; a **transient** is memoised by fingerprint; a **mode** (zones, reads, actions, paragraph) is merged | the mode's reads must return on that frame what the VLM said they would (`expect`) |
| a screen the pack reads well but has not seen | its fingerprint joins the index as `main` | support alone |
| a game with no pack | the author writes one from a **demonstration** (your recording, or the explorer's minute of play with intents): the action set as used, the regions that change, the paragraph | the pack must pass tests on the demonstration's frames; changed expectations are re-checked against the image ("cannot lower the bar") |
| a **loss** while playing | the last decisions and their frames become an **incident**; the chat model revises the typed frame: derived reads, rules, questions, paragraph | **replay**: Jev's recorded answers are pushed through the candidate's reads and rules; the fatal decision must be guarded (a rule excludes it) or visible (a new read separates that tick), ordinary decisions must stay allowed, screens must still read |
| the next episode with a revision | the revision stays or goes | it must not play worse than the incumbent's median episode (won > tasks done > not lost > longer > score) |
| a **task** completes or the game is won | the span becomes a **positive incident**; the pack that first completed a task yields lessons | every later revision must keep the span's choices allowed (replay) |
| the task record per category | the **setter** proposes new tasks from the typed frame, weakest category first | a task must name real reads and not already hold; it is verified every tick by the compiler |

The last two rows are the closest thing to reinforcement learning this system does, and they never touch a
model: the gradient is a change to the typed frame, and the reward is an episode outcome (won > not lost >
longer > higher score). The **bank** keeps the episodes and the last incidents per pack (`learn.py`,
`learn.ts`), so what was learned survives a restart and the next revision sees how the pack has been playing.

Two more things learn, and they are what separates this from a fixed self-improvement loop:

| what | learns from | how |
|---|---|---|
| the **judge** (`Calibrator`) | the trial record: each accepted revision's shape and whether it was kept or reverted | a small logistic model, consulted before a revision goes on trial once six labelled revisions of both outcomes exist; its veto floor is conformal (at most a quarter of revisions as good as the kept ones refused), so it abstains until three revisions have been kept |
| the **scorer** (re-query) | the frozen decider itself, re-asked on banked states under the candidate frame | the fatal state must be avoided, the counterfactual return over every banked loss must beat the incumbent's, and the held-out ordinary ticks must keep their choices |
| the **proposer** | lessons: the rules and reads that kept revisions added, on this pack and on others in the pool | shown in the revision prompt, filtered to the read kinds this pack has |

Still fixed: Jev (or CLM), the chat model that proposes, and the set of read kinds and rule forms, which are code.
[METHOD.md](METHOD.md) is the fuller account: why a re-queryable frozen decider makes the search over its inputs
exact, and which audits and estimates follow from that.

## 4. The application loop

```
open a game ──▶ pool: known site or known screen? ──yes──▶ pack ──▶ play
                       │ no
                       ▼
             demonstration (record me / explorer) ──▶ author ──▶ pack ──▶ play
                                                                          │
              ┌───────────────────────────────────────────────────────────┘
              ▼
        episode: Jev plays from the typed frame; a miss goes to the VLM once and becomes Jev's
              │ loss
              ▼
        incident ──▶ revision ──▶ replay says better? ──▶ restart with it on trial ──▶ keep or revert
```

- **Known game**: instant. The pool (`packs/pool.json`) indexes packs by site and by the fingerprints of
  their screens; the extension checks it when the panel opens and the CLI's `go` checks it before authoring.
- **New game**: minutes. A demonstration, a pack, tests, then play.
- **New screen inside a game**: once. The VLM handles it and the runtime remembers.
- **Loss**: a revision that has to earn its place by replay, then by play.

In the extension the whole loop runs in the side panel (`play` with *keep learning* on): play, bank, revise,
reload the tab, play again, forever until *stop*. In the CLI it is `anygame learn <pack> --device … --episodes N`.

## 5. How it ships

| artifact | what it is | how it is made |
|---|---|---|
| `anygame` wheel | the CLI and the desktop application: every device, the author, the learning loop, the HUD; `[desktop]` adds the screen device, `[stream]` WebSocket streams | `scripts/dist.sh` → `dist/anygame-*.whl` |
| the Chrome extension | the whole runtime in a side panel; frames and input through the debugger API; the pool, the author, the learning loop, the state expression | `scripts/dist.sh` → `ext/anygame-extension.zip` |
| the pool | `packs/pool.json` on `main`: every pack with its site hints and screen fingerprints | `npm run build` in `ext/` after `anygame stamp` |

| the Docker image | the CLI with every extra, Xvfb for the desktop device, the tests | `docker build .`; `scripts/test-image.sh` runs the unit tests, the fixture evals and a play through pixels, a state stream and a virtual desktop inside it |

The same pack plays in both: the YAML is the contract, the fixtures (screenshots or state JSON) are the tests.

## 6. What this is, in SIMA terms

SIMA 2 (DeepMind, 2025) is a generalist agent: it sees the screen, acts with keyboard and mouse, follows
instructions, explains what it is doing, transfers to games it has not seen, and improves itself from its own
experience with a large model providing tasks and reward. anygame is the same shape with a different engine:

| SIMA 2 | anygame |
|---|---|
| Gemini as the cognitive core, seconds per decision | Jev on a typed frame, 200 ms per decision (CLM, the same protocol, 16–28 ms); a vision model only on a miss, while authoring, and after a loss |
| a policy trained on demonstrations and self-play | a pack: the typed frame, the paragraph, the rules; grown, never trained |
| Gemini generates tasks and estimates reward | the outcome of an episode is the reward; the chat model proposes the revision, the replay and the next episode judge it, and the judge is calibrated from the trial record |
| an experience bank feeding later generations | the bank: episodes and incidents per pack; each accepted revision is a generation |
| transfer across games by concept | transfer by structure: `locate`, `runs`, `around` and the rules mean the same in every grid game |
| explains its plan in language | intents from the explorer, Jev's beliefs and the rules that fired, shown every tick |

The point of the split is speed and permanence: everything that can be compiled is compiled, the slow model is
paid once per new thing, and every new thing becomes part of a pack that anyone can play from instantly.

## 7. Reading the code

| file | what it holds |
|---|---|
| `anygame/loop.py`, `ext/src/core/loop.ts` | the tick: classify, observe, support, miss → fallback, questions, Jev, rules, act |
| `anygame/perceive/`, `ext/src/core/reads.ts`, `color.ts`, `tetris.ts` | reads and derived reads, including the state reads |
| `anygame/device/` (`web.py`, `screen.py`, `stream.py`, …), `ext/src/device/tab.ts` | devices: frames, state, input |
| `anygame/pack.py`, `ext/src/core/pack.ts` | the pack model, modes, dump/load |
| `anygame/fallback.py`, `ext/src/core/fallback.ts` | the VLM fallback and its memo |
| `anygame/demo.py`, `ext/src/core/demo.ts`, `explore.ts` | demonstrations: digest, explorer |
| `anygame/author.py`, `ext/src/core/author.ts` | the author: probe or demonstration → pack → tests → tune |
| `anygame/learn.py`, `ext/src/core/learn.ts` | episodes, incidents, replay verification, revisions, the bank |
| `anygame/pool.py`, `ext/build.mjs`, `packs/pool.json` | the pool index and matching by site or screen |
| `ext/src/panel/panel.ts` | the side panel: the whole loop as a UI |
| `test/`, `ext/test/` | unit tests on painted boards, fixture evals, headless end-to-end runs |
