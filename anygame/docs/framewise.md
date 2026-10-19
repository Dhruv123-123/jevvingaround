# Framewise: Jev plays every frame, the vision model works behind it

Oct 17, 2026. Code: `anygame/framewise.py`. Bench: `scripts/framewise_bench.py`. Data: `/mnt/project-files/anygame/framewise/`.

## What changed

The typed agent (`typed_screen.py`, Oct 15) stops and waits whenever it asks a model. The vision model names a new
screen (about 4 s on Azure), then the decider picks (Jev about 400 ms). On a real-time game, the game runs on
while the agent is frozen.

The framewise agent splits this into two lanes that never wait on each other:

| Lane | Who | When | Writes |
|---|---|---|---|
| Slow | Azure vision model, own thread | each screen hash with no label yet, newest first; stale ones dropped | label + subgoal to the blackboard |
| Fast | Jev (or any typed decider), own thread | each (label, goal) with no memoised answer; prefetched the moment a label lands | a press macro in the memo |
| Frame loop | no model | every frame | plays the macro, re-plans on surprise, else explores |

* **Memo.** Answers are keyed by (screen label, goal). A screen seen before costs no call. An answer that finds
  nothing new twice is forgotten and asked again, with what happened in the decider's state.
* **Macros.** An answer is one of the label's options, up to 12 presses, so one ~400 ms call covers many frames.
  The rest of a macro is dropped when the screen becomes something it was not for: a different label after a scene
  change or a change of kind, such as a fight or a text box. A map that scrolls under the same label keeps it.
* **Patience.** On a labelled screen with no answer yet, the loop holds for at most `patience_ms` (600), then the
  explorer presses. On an unlabelled screen it explores while the slow lane works.
* **Cache folder.** With `cache=DIR`, labels (`labels.npz`) and the memo (`memo.json`) outlive the run, so a second
  run calls models only for what is new.

Use it with `screen_agent(..., decider="jev", framewise=True)`, `heldout --agent screen+framewise`, or the chain
setting `{"decider": "jev", "framewise": true}`.

## First measurement (stubbed decider)

Jev has no OpenRouter credit (402 since Oct 16), so the decider is `stub:400`: it waits 400 ms, like Jev's p50, and
picks the option that shares the most words with the vision model's subgoal. **It is not a model.** These numbers
show the loop's behaviour, not the quality of play. Labels are the real Azure model.

Setup: Viridian City save, goal "go into the Poke Mart", 180 s on a 60 fps wall clock (the game never runs ahead of
real time), 2 seeds.

| | typed | framewise |
|---|---|---|
| time blocked in a model call | 62 s, 64 s of 180 | 0 s, 0 s |
| slowest frame step | (the model call) | 21 ms, 16 ms |
| presses | 441, 453 | 491, 491 |
| labels written | 10, 12 | 27, 22 |
| decider answers | 19, 17 | 34, 37 |
| presses played from Jev's macros | not separated | 100, 175 (20%, 36%) |
| memo hits (no call) | none | 28, 56 |
| places stood on (RAM, grader only) | 57, 99 | 94, 88 |
| Azure spend | $0.008 | $0.018–0.023 |

Readout: the frame loop never waits, and in the same three minutes both models get about twice as much work done,
because neither sits idle while the other runs. Neither run reached the Mart: the stub cannot judge, so progress has
to be measured with Jev itself.

## Round 2 (Oct 19): pixel reads and where options led

`perceive/pixel_reads.py` reads gauges (HP bars) and a menu cursor from pixels by shape, with no game layout. A gauge
is a thin band between two long dark lines over the same columns; a cursor is the small thing a d-pad press drew when
little else changed. The fast lane's state now carries each bar's fill (and its last value), the cursor's text row,
and, per option, where it led the last time it was picked on this screen. Off the map the memo key also holds the
cursor row and whether a bar is low.

Same setup as above but 300 s and stopping at the Mart, round 1 code vs round 2, `stub:400` decider (not a model):

| | round 1 | round 2 |
|---|---|---|
| presses from Jev's macros | 147, 226 | 309, 259 |
| decider calls | 79, 71 | 62, 56 |
| places stood on | 24, 113 | 100, 109 |
| maps entered | 2, 2 | 3, 3 |
| reached the Mart | no, no | no, no |
| Azure | $0.025–0.030 | $0.028–0.029 |

The decider drives about 46% more presses with about 20% fewer calls, since replayed answers carry where they led.
Cursor reads fired 6 and 2 times (Viridian has few menus). The Mart still needs a decider that can judge.

### With a judging stand-in (Azure answering Jev's questions)

Same runs with the Azure model as the decider (p50 about 2.1 s per answer, five times Jev's), round 1 vs round 2:

| | round 1 | round 2 |
|---|---|---|
| presses from the decider's macros | 99, 137 | 106, 237 |
| places stood on | 124, 142 | 98, 82 |
| reached the Mart | no, no | no, no |
| spend (labels + decisions) | $0.067, $0.054 | $0.064, $0.048 |

No gain yet: neither version reached the Mart, and round 2 covered less ground. With a 2 s decider, the explorer
plays 70–87% of presses because the 600 ms patience runs out first, so the decider's judgment barely steers.
That is the next thing to fix, by waiting longer when the decider is slow or keeping the explorer to the heading the
last answer gave. Total spend for these four runs was $0.23.

### Round 3 (Oct 19): why the explorer still plays most presses

The wait for an answer now stretches to 1.5x the decider's recent median (at most 4 s). Rerun with Azure as the
decider (p50 2.0 s), 2 seeds: no Mart, 143 and 74 places, the explorer still played 82% of presses ($0.11).

New counters (`explore_why` in the summary) show the cause: with the stub, about 80% of explorer presses happen on
screens that have no label yet. A new view takes about 4 s to label, so after each door the explorer plays for a
while. Timeouts are rare (2–6), and so are "explore" answers. "Explore" answers now expire after 8 presses instead
of pinning a screen to the explorer for good.

A fix tried for unlabelled views: keep the last map label when no scene change happened (`borrow=True`). That
halves unlabelled explorer presses and raises the decider's presses on 2 of 3 seeds. Places reached: 21, 59, 84 with
it vs 72, 26, 66 without, a wash. It stays off by default. The likely real fix is labelling faster (a smaller image,
or a lower-detail first pass) so a new view is named in under a second.

## Next

1. With Jev credit: 10 power-on badge runs with `{"decider": "jev", "framewise": true}` against the Oct 15 typed
   numbers (8/10 at $0.33), plus Jev's share of presses and the memo hit rate. The cap is $3.
2. A judging stand-in until then (the Azure model answering Jev's questions), to measure whether the readings
   and outcomes help it reach the Mart.
