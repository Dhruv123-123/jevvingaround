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

## Follow-up (2026-10-03): the ducking fix, and close pairs

| 8 games each | score median | range | Jev cost |
|---|---|---|---|
| Real Jev, ducking fix (pack as in the first round) | **1277** | 181–3425 | $0.090 |
| Real Jev, low jump for close pairs (v1, later timing) | 537 | 295–1371 | $0.083 |
| Stand-in, low jump for close pairs (v1) | 630 | 287–1896 | – |
| Stand-in, low jump for close pairs (v2, normal timing) | 820 | 45–1654 | – |
| Stand-in, final pack (full jump everywhere) | 606 | 266–798 | – |

**Birds.** With the ducking fix, birds caused 1 of 8 Jev deaths (at score 3425), down from 2 of 8, and the
median doubled to 1277. That run also showed the fix had a side effect. Pressing Space again while it was still held
only extended the hold, so a jump right after a fast drop never came down anew (1 death). The fix now applies only to
actions marked `repeat: hold` (the duck). One of the 8 games had the ad described below over the game.

**Close pairs did not improve, so the change is not kept.**
- The old `jump` (120 ms) and `long_jump` (250 ms) were the same jump: 550 vs 575 ms in the air on the page. Jev's
  choice between them changed nothing. A plain press is also a full jump, because Space comes up before Chrome
  counts it. Only a ~60 ms hold gives Chrome's low jump: about 60 px high and 460 ms in the air.
- The road read now also gives `then_px` and `then_ms` (how far behind the nearest obstacle the next one starts)
  and a head-height row that marks tall cacti. Conditions can test `contains:`.
- Rules that used the low jump when the next obstacle followed within 650 ms did worse with Jev (median 537) and no
  better with the stand-in. The deadly pairs are ~400 ms apart. That is too close for a full jump and still too
  close for the low one. The low jump is also only 60 px high and short, so with frames ~65 ms apart its timing
  window is narrower than a frame: a later press ran out of height, and an earlier one landed on a single small
  cactus. The pack is back to one full jump. Both reads stay, unused by its rules.
- A fast drop could fire while a thin cactus was still under the dino's back; `under` now covers the whole dino
  and needs any ink, not a sixth of it.

**Harness.** Some visits get an ad anchored over the top of the page, which also pushes the game down ~100 px. Before
each game, `dino_start` now hides ads and fixed overlays and scrolls the game back into place.

**What is left**: pairs about 400 ms apart. The likely fix is not in the pack: the loop sees a frame only every
~65 ms. Faster frames, for example a smaller screenshot of only the game's strip, would make the low jump usable.
Jev spend this round: $0.22 (three runs, two of them with fixes found during the run), over the ~$0.05 asked:
better runs last longer, and each game costs about $0.007 per 1,000 points.

## Third round (2026-10-03): 30 frames a second

| 8 games each, same 200 s cap | score median | range | Jev cost |
|---|---|---|---|
| Stand-in, 15 fps (final pack above) | 606 | 266–798 | – |
| Stand-in, 30 fps, first try | 428 | 78–1214 | – |
| Stand-in, 30 fps, double press fixed | **912** | 301–1662 | – |
| **Real Jev, 30 fps** (final pack) | **770** | 220–1781 | $0.10 |
| Stand-in, 30 fps, earlier jump before a close pair (dropped) | 910 | 331–1797 | – |

**The limit was the screenshot.** A Playwright screenshot takes 35–50 ms whatever its size or format, so the loop
could not go much past 15 frames a second. A pack can now say `frames: stream`: the web device takes frames from
Chrome's screencast, which pushes every painted frame, and `frame()` returns the first one painted after it is
called (~10 ms), or a screenshot when the page paints nothing new. It is a pack setting, so other games are
unchanged. The dino pack now runs at `tick_hz: 30`, and ticks measured 34 ms apart.

**A fast loop pressed the jump twice.** One frame after the jump key the screen can still show the dino on the
ground, so the rules pressed Space again 33 ms later, which let go of the first press (149 double presses in 8 games,
median 428). Key actions take `again_ms` (the jump: 150), and within it the loop waits instead of pressing.

**Results.** The stand-in went from 606 to 912 and Jev scored 770. That is above Jev's 537 with the low jump. It is
below the 1277 from the ducking-fix run at 15 fps, but that run used the old pack and 8-game medians spread widely.
The stand-in's own medians ranged 592–1175 on similar packs. Jev's games cost $0.10, about $0.007 per 1,000 points as
before, over the ~$0.05 asked because the games ran longer.

**What still kills it: the same close pairs.** In 5 of Jev's 8 deaths the obstacle arrived 580–615 ms after the
previous jump: the dino lands just as it arrives, too late to jump. Faster frames did not change that, because the
full jump lasts ~575 ms whatever the frame rate. Jumping earlier when a second obstacle follows within 500 ms did not
help (910 vs 912), so it was dropped. What is left to try: a fast drop timed from the gap to the second obstacle,
and the low jump now that frames come every 34 ms.

**Perception at 30 fps.** About 1% of road reads are one game frame (~9 px) behind the page's state, because a
screencast frame shows the game as drawn up to a frame earlier. Before, with screenshots, there were no such reads.

Logs: `/mnt/project-files/anygame/dino-reflex/r3-*`.
