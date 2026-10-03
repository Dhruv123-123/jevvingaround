# Dino on chromedino.com: rules on the frame, Jev beside the loop (2026-10-03)

Branch `claude/anygame-dino-reflex` (snake reflex branch + PR #2's real-web work merged in), not merged, no PR.
Pack `packs/web-dino`, harness `scripts/web_trial.py dino`, which reads the page's own state just before and just
after each screenshot and grades every read against it.

## Results, 8 games each

| | score median | range | mean | Jev cost |
|---|---|---|---|---|
| Old pack, real Jev ([real-web-trial.md](real-web-trial.md), 5 games) | – | 58–124 | – | – |
| New pack, stand-in at Jev's pace (400 ms per answer) | 592 | 202–1332 | 654 | – |
| New pack, real Jev | **600** | **254–1339** | 672 | $0.045 |

The score is the game's own distance counter. The old pack died at the 2nd to 6th cactus; the new one runs 6–7×
further. Run-to-run spread is large: an earlier 8-game stand-in run on a slightly different version of the pack
(road read from x 96, no `under` read) got median 1175 (204–2209).

Jev and the stand-in end up level, for different reasons. Jev does the right thing per obstacle: it picked
`long_jump` for 169 of 188 wide cactus groups and `duck` for all 42 chest-height birds; the stand-in always takes a
short `jump`. Six of the stand-in's 8 deaths were short jumps over wide groups. Jev's long jumps clear those, but
they keep it in the air longer, and closely spaced obstacles then catch it landing late.

Perception: on 6,466 Jev-run ticks, 0 wrong road reads on cacti. On birds the read starts at the beak, 15–40 px
behind the page's box (the sprite's empty margin), on 65 ticks. The in-air read said "ground" on 38 ticks, all at the
top of a jump with a bird passing under the dino. Game over was read 1 frame late 4 times.

## What changed

- **A `gap` read** (`anygame/perceive/__init__.py`, `GapTracker`): from a grid strip in front of a runner, the distance
  to the nearest obstacle, its width, which rows it fills (`low`, `chest`), the closing speed measured over its
  whole approach, time to contact, and how long it has been the nearest.
- **Rules time every move on the frame.** Jump at 205 ms to contact from the road's start (about 250 ms from the dino's
  nose). No key while the dino is in the air, because letting go of Space ends Chrome's jump early (this was the first
  big killer). In the air, a fast drop (`ArrowDown`) when a new obstacle is close and nothing is under the dino.
- **`reflex`** is in the pack (ttc ≤ 900 ms → rules on the last answers), but on its own it was not enough: at high
  speed an obstacle appears less than one Jev call away, so Jev would only ever be asked about an empty road.
- **`ask: async` + `ask_when`** (`Agent.step` in `anygame/loop.py`): Jev runs beside the loop and the loop never waits.
  It is asked once per obstacle, when it is the nearest and fully in view; its ranking applies when the obstacle
  arrives. About one call per 1.3 s of play, 340 ms median.
- **`release: later`** on key actions: a held key goes down now and up on the next frame after `hold_ms`, so a 250 ms
  long jump does not cost 4 frames.
- Rules take `if: [ ... ]` (all must hold) and `unless: [ ... ]` (any one skips the rule).
- Harness: the site sometimes shows a ~100 px banner above the game, which moved every zone (it broke a first Jev
  run). `dino_start` now scrolls the game back to where the pack expects it and checks.
- The ducking dino reaches x 111, past the old road start: Jev's ducks read as an obstacle at 0 px and the rules then
  jumped into the bird. The road now starts at x 114.

## What still kills it

1. **Landing late for a close second obstacle** (most of Jev's deaths). A long jump lasts ~600 ms; when the next
   obstacle is less than that behind, the dino lands with it too close to jump. The fast drop helps only when the
   next obstacle is seen early enough. A rule that picks a short jump when a second obstacle is close behind would
   need the road read to report the second obstacle too.
2. **Short jumps over wide groups**: the stand-in's main death. Jev avoids it by choosing `long_jump`.
3. **Birds, 2 of 8 Jev games.** One was a repeated duck: each re-press let go of the key, so the dino stood up for a
   frame. Fixed after the run (re-pressing a held key now keeps it held, `WebDevice.key`) but not measured yet. The
   other was the close-pair problem with a bird second.
4. Zones are fixed pixels. A pack has no way to find the game on a page whose layout shifts; the harness does it here.
5. The extension's TypeScript runtime does not have `gap`, `ask: async`, `release: later` or list conditions yet, so
   this pack runs from the CLI only.

## Rerun

```bash
cd anygame && pip install -e ".[stream]" playwright
# cloud Chromium needs the proxy CA: certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n proxy -i /root/.ccr/agent-proxy-ca.crt
OPENROUTER_API_KEY=placeholder python scripts/web_trial.py dino --episodes 8 --sensor jev --out runs/dino-jev
CLM_STUB_DELAY_MS=400 python test/clm_stub.py 8722 &
python scripts/web_trial.py dino --episodes 8 --sensor clm:http://127.0.0.1:8722 --out runs/dino-stub
```

Logs: `/mnt/project-files/anygame/dino-reflex/` (`jev/`, `stub-400ms/`, and the earlier stand-in run's summary).
