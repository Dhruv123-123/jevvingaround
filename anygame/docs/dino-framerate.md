# Dino at 15 or 30 frames a second (2026-10-03)

Branch `claude/anygame-dino-framerate-wtqykg` (off `claude/anygame-integration`, PR #3).

**Answer: the drop was run-to-run noise plus one rare 30 fps bug, now fixed. Played back to back on the same day,
real Jev scores the same at both rates, so the pack keeps shipping at 30 fps.**

## The decisive run: 16 games each, same day, alternating

Blocks of 4 games, 15 fps then 30 fps, four times over, so machine drift hits both rates alike. Same pack (with the
fix below), same 200 s cap (3000 ticks at 15 fps, 6000 at 30), no game hit the cap.

| Real Jev | games | median | mean | range | ticks apart | Jev cost |
|---|---|---|---|---|---|---|
| 15 fps (screenshots) | 16 | 849 | 855 | 315–1776 | 67 ms | $0.20 |
| 30 fps (`frames: stream`) | 16 | **831** | **902** | 307–1790 | 33 ms | $0.21 |

A 30 fps game beats a 15 fps game 52% of the time (permutation p = 0.84): no difference. Per block (15 | 30):
1542 684 511 1776 | 917 959 521 815; 640 870 1140 953 | 1089 788 825 391; 812 855 315 434 | 1074 837 1790 941;
340 842 877 1095 | 763 307 756 1653.

Deaths: 15 fps 13 cacti, 3 birds; 30 fps 13 cacti, 3 birds. Most are still the close pair (landing as the next
obstacle arrives). Jev's calls took 375 ms median at both rates.

## Why the earlier numbers looked different

- The 1277 at 15 fps was one 8-game round on an older pack, and two of its games ran into the time cap (3422,
  3425). Pooling every earlier Jev run, CLI and extension, 15 fps beat 30 fps 58% of the time, p = 0.40. The
  extension's 714 vs 473 alone is p = 0.45. Neither is evidence of a real gap.
- The stand-in can't show a Jev-only effect: its answer is always "jump first", so the only place Jev and the
  stand-in take different paths is when Jev's ranking changes (duck for a bird).

## The one real 30 fps mechanism (fixed)

Jev is asked about an obstacle when it becomes the nearest. For the second obstacle of a close pair, that leaves
~400 ms, about one Jev call, so the answer often lands just as the dino jumps. At 30 fps the frame right after the
jump key can still show the dino on the ground. If Jev's answer ("duck", for a bird) landed on that frame, the
rules pressed ArrowDown, which in Chrome is a fast drop out of the jump, straight into the bird.

- In the earlier logs: 4 such presses in 32 CLI games at 30 fps (1 death, round 4 game 7), 2 in 8 extension games
  at 30 fps, and none at 15 fps in either runtime, where the next frame already shows the jump.
- Fix: key actions take `lock_ms` (no other key goes down that soon after this one), and the dino jump has
  `lock_ms: 100` (`anygame/loop.py` `Agent.act`, `packs/web-dino/pack.yaml`, test in
  `test/test_learn.py::test_dino_jumps_on_the_frame_and_asks_jev_beside_the_loop`).
- It is rare: the lock fired 0 times in the 32 games above. It explains one death, not the gap.

The other candidates were checked and ruled out: the ask window is in ms, not ticks (`GapTracker.age_ms`); Jev was
asked once per obstacle at both rates; the reflex acts on Jev's last answer the same way at both; the ~1% stale
screencast reads are not behind deaths.

## Shipping setting

**30 fps** (`tick_hz: 30`, `frames: stream`). What decided it: real Jev is level same-day (831 vs 849 median,
902 vs 855 mean), the stand-in was ahead at 30 fps in both earlier back-to-back comparisons (912 vs 606, 415 vs
311), and the low jump for close pairs, the remaining killer, needs the shorter frame gap to be timeable.

## Not done

- The extension (PR #4) does not have `lock_ms` yet; it ignores the key, so the shared pack still loads there.
- Asking Jev about the second obstacle of a close pair before it becomes the nearest would give it time to answer.

## Rerun

```bash
cd anygame && pip install -e ".[stream]" playwright
certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n proxy -i /root/.ccr/agent-proxy-ca.crt
# 15 fps variant: the pack with tick_hz: 15 and no frames: line
OPENROUTER_API_KEY=placeholder python scripts/web_trial.py dino --episodes 4 --ticks 3000 --pack <dino15> --sensor jev --out runs/jev15-b1
OPENROUTER_API_KEY=placeholder python scripts/web_trial.py dino --episodes 4 --ticks 6000 --sensor jev --out runs/jev30-b1
```

Logs: `/mnt/project-files/anygame/dino-framerate/` (`jev15-b1..4`, `jev30-b1..4`). Jev spend: $0.41.
