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

That plays 2048 in a browser inside the container with nothing else attached. For a phone:

```bash
# phone: Settings → Developer options → Wireless debugging → pair
DEVICE=adb://192.168.1.20:5555 PACK=clash-royale docker compose run --service-ports anygame
```

Three steps: a key, a device, a pack name.

## What a pack is

```yaml
game: "2048"
zones:
  board: { rect: [0.037, 0.2, 0.963, 0.914], grid: [4, 4] }     # normalized; scales to any screen
read:
  tiles: { kind: color, zone: board, parse: int, options: { "0": "#cdc1b4", "2": "#eee4da", "4": "#ede0c8", … } }
  score: { kind: ocr, zone: score, parse: int, every: 5 }
act:
  - { id: left,  kind: swipe, zone: board, dir: left }
  - { id: right, kind: swipe, zone: board, dir: right }
play: >
  Keep the largest tile in the bottom-right corner, build a monotone chain along the bottom row…
questions:
  - { id: corner_at_risk, type: noul, instructions: …, criteria: { true: …, false: … } }
tests:
  - { frame: fixtures/board-a.png, expect: { tiles: { c4r4: 128, … }, score: 512 }, expect_action: { not: [up] } }
```

Perception is layered and the cheap layers come first: a colour read is ~1 ms, a template match ~5 ms, OCR
~200 ms, an open-vocabulary detector (YOLO-World, `pip install anygame[vocab]`) ~300 ms on CPU. Most of a game's
state is the first two layers; 2048 needs zero OCR on the board because every tile value has its own colour.
Templates are crops you paste into the pack's folder — four card icons is a deck, and that is the whole
"training".

Actions are typed. `swipe` and `tap` are direct; `play` means "pick a slot, then a target cell", and the runtime
asks Jev for the slot and the cell in the same call as the action, so a Clash Royale tick is one request.

Two rules the loop enforces without the model: an action that changed nothing on screen is not offered again
until the screen changes, and a read marked `every: N` is only refreshed every N ticks.

## Measured, 2048 in headless Chromium, real Jev via OpenRouter

- Perception 32 ms p50 (colour read of 16 tiles + score OCR every 5th tick). Jev ~220 ms p50. About 4 ticks/s.
- $0.000034 per tick; a 120-tick game costs less than half a cent.
- Play quality: mediocre — Jev is a judgment model, not a search, and 2048 rewards search. It reliably keeps the
  corner strategy and never swipes up unless forced, which is exactly what the paragraph told it. The point of
  2048 here is that the loop is provable with no hardware; the interesting games are the ones where judgment
  beats search — real-time ones on a phone.

## Packs

| Pack | Device | Status |
|---|---|---|
| `2048` | `web://games/2048.html` | plays end to end in the container; fixtures and tests included |
| `clash-royale` | `adb://<phone>` | zones, reads, actions, questions and the play paragraph are written; needs your frames for the card templates and the test fixtures (`anygame record`) |

## Commands

```bash
anygame packs
anygame play <pack> --device web://…|adb://…|replay://<dir> [--hud 8080] [--max-ticks N] [--sensor none]
anygame eval <pack> [--sensor jev]        # perception tests on the pack's frames; action checks with a sensor
anygame record --device adb://<ip>:5555 --out packs/<pack>/fixtures --seconds 30   # frames for authoring
```

`--sensor none` runs perception and the HUD with no model, for authoring a pack against a live screen.

## Honest notes

- `adb screencap` is 100–250 ms a frame. Fine at 3 Hz; scrcpy's video stream is the path to 10 Hz.
- Open-vocabulary detection on cartoon sprites is hit-or-miss; the `blobs` read (coloured health bars) is the
  reliable fallback and is what the Clash Royale pack uses by default.
- Jev sees only the compiled state: numbers, labels, cells. It never sees pixels.
