# SIMA 2 (DeepMind, 2025-12-05) read against anygame

Source: the 40-page technical report. Page numbers are the `=== page N ===` markers of the extracted text.

## 1. What SIMA 2 is

**Model and training.** A Gemini Flash-Lite checkpoint, supervised-finetuned on gameplay data mixed with Gemini
pretraining data; the mixture keeps vision, dialogue and reasoning alive (p7). Flash-Lite, not Pro, "due to the
latency constraints that come with embodied action" (p21). Then online RL from verifiable rewards: a task is
(initial game state, text instruction, verification function), reward for completion or a correct grounded answer,
some tasks shaped (p9); RL only in training environments (p10).

**Interface.** 720p RGB; the Figure 3 prompt says "running at 30 fps. You will only see every 10 frames", so about
3 Hz observation (p7). No privileged state. 96 keyboard keys, mouse clicks, discretized relative mouse moves; the
model emits "chunks of actions" as structured text (`MouseRight=30,KeyD,KeyD,,KeyD,MouseDown=5,ClickLeft`) parsed
deterministically, interleaved with reasoning and dialogue, "the agent specifying which modalities to produce"
(p7). Latency is never quantified.

**Data.** Human data is the bulk: single-person play annotated post hoc; two-person "Setter-Solver" play, instruction
before action; "game-tasks" from a fixed state with a time limit; human ratings and pairwise comparisons "to
calibrate reward models" (p8). Preprocessing: heuristic and score-based filtering,
reweighting across environments, cutting trajectories into "spans" of one instruction each (p9). "Bridge data" is a
small set of successful examples that Gemini Pro annotates with reasoning and dialogue consistent with the frames,
with no-ops so the agent stays still when done (p9). RL tasks came from contractors dropped into random states who
proposed achievable tasks; verifiers were run over all human trajectories to find completion points; tasks were
"filtered down to those that a human could complete within a specified time limit" (p10).

**Self-improvement (Section 4.5, p22-26).** Three models: task setter, agent, reward model (p4). The setter is
Gemini prompted for instructions "likely to be achievable from the current state", coupled to the running
environment so it can change the task mid-episode; evaluation results fed back let it "steer the agent toward
skills that need to be improved" (p23). The reward model is Gemini rating each trajectory video with a rubric, 0 to
100, for completion and "directedness, i.e., not performing unnecessary actions"; the prompt was tuned until scores
matched human preference pairs on a small set; 50 or more is success (p23). Scored trajectories become training data;
iterations are only "multiple", and whether low scores are dropped or weighted is not said. On a fixed
ASKA set (resource gathering, interaction, navigation, menu use) the initial agent passed under a quarter of tasks;
after iterations it exceeds 50 on all and the average exceeds the human reference, judged by the same reward model
(p24). With the setter steering toward progression it learned ASKA's crafting menu and built a shelter within one
hour (p24-25). In Genie 3, self-improvement on urban worlds transferred to most held-out natural-world tasks (p25-26).

**Evaluation.** Three evaluators (p10): ground truth (Construction Lab, Playhouse, WorldLab, MineDojo);
programmatic, from OCR, pixel colours and the agent's actions (ASKA, Goat Simulator 3, Hydroneer, No Man's Sky,
Satisfactory, Space Engineers, Valheim, Wobbly Life); human, five raters per video. "SIMA Evaluation Suite 2.0"
(p10-11) requires detected text to persist for several seconds, caps actions after completion, and chains
sequential instructions. Eight categories (Table 2, p37): interaction, navigation, menu use, tool use, construction,
object management, resource gathering, combat; combat weakest (p16). SIMA 1 about 30-33%, SIMA 2 65-66%, humans
76-86% with and without timeouts, some as short as three seconds (Figure 6, p14). Held-out: +12% in ASKA, +13% in
MineDojo, both still under 20%; 26 of 50 MineDojo categories solved; naive humans 19% (MineDojo) and 32% (ASKA);
humans fail on time, agents on "suboptimal exploration" (p16-18). The Gunk: 15-20 minutes by manual
instruction, inferring a held button from on-screen "HOLD" (p18-19). Baseline Gemini without SIMA data: Flash-Lite 3.2%, Pro
7.0% (p20). Retention after SFT / SFT+RL: LiveCodeBench -4.0% / -8.4%, AIME -25.5% / -15.4%, GPQA Diamond
-16.3% / -19.5% (Table 1, p21).

**Reasoning, memory, multimodal goals.** Internal reasoning conditions actions ("ripe tomato" to red house, p12);
other languages, emojis, sketches drawn on the frame, wiki images (p13); a recipe diagram with Gemini Pro (p22). Memory is short: Gemini Pro "every k steps" issues instructions and keeps a text summary
as "a form of recurrent memory" (p21; Appendix B, p38-39). Stated limits (p26-27): long-horizon tasks needing goal verification, a short context kept small for
latency, precise low-level control, robust 3D scene understanding.

## 2. What applies to anygame

| SIMA 2 | anygame today | gap and how to build it |
|---|---|---|
| Task setter proposing achievable tasks from the current state (p23) | none. `Agent.goal` (`loop.py`) is one string shown only to the VLM fallback; Jev sees `how_to_play`. The explorer (`demo.explore`, `explore.ts`) emits per-input intents, not tasks | a `tasks:` pack section (instruction, verifier over reads, limit, category) proposed by the VLM from a frame; the active task enters Jev's state as `task`; the setter picks the worst-scoring category |
| Reward model: 0-100 rubric with directedness, success at 50 (p23) | `learn.outcome` regex on the stop reason plus `score_read`; `better_episode` lexicographic (won > not lost > ticks > score); `VLMFallback.outcome` one look at a stalled frame | an episode rater: VLM scores sampled frames and the action log for completion and directedness, calibrated against `better_episode` and human references |
| Verifiable tasks and programmatic evaluators from OCR, colours, actions (p9-10) | read kinds `ocr`, `color`; `stop_when`, `act_when`; `tests:`; `cmd_bench` seeds and `score_read`; `cmd_battle` | SIMA hand-writes verifiers; anygame's author can write them and check them on fixtures, as rule conditions on reads |
| Training on scored self-generated experience (p23) | losses only: `cmd_learn` → `incident_of` → `improve` → `verify_revision`, `requery`, `holdout_check`, `Calibrator` → trial | weight updates are not transferable. Transferable: bank successful spans as positive incidents the replay must keep allowed; `lessons_of` on them |
| Spans, quality filters, verifier-derived tasks from human play, "human can finish in time" (p9-10) | `Bank.add_holdout` (24 ticks), `add_incident` (4), a 12-decision window, `demo.digest` (keys, click clusters, hot regions, 6 pairs, intents) | run verifiers over demonstrations to cut spans at completion points; keep a task only if the demonstration or explorer finished it within the limit |
| Held-out environments and a skill taxonomy (p5, p37) | pool packs; `--fresh` ignores lessons; no categories | a suite: held-out packs excluded from `pool_lessons`, tasks tagged by category |
| 96 keys, clicks, relative mouse, chunks, ~3 Hz (p7) | `Action` kinds tap, swipe, key, wait, play, macro; `tick_hz` 3; `key` is press-release (`screen.py`, 30 ms); macros `key_ms` 40 | no held keys, relative mouse or camera: add `hold_ms`, `mouse_move`, and a `chunk` option carrying several inputs per decision |
| Sketch, image, emoji goals (p13, p22) | `author --play`; HUD live edit of `play` and `rules` (`take_edits` in `Agent.step`) | a sketch is compiled, not followed: the VLM turns it into a `templates` read or `locate` target plus a verifier; Jev never sees the image |
| Reasoning traces, bridge data (p9, p12) | the `play` paragraph, `noul` questions (snake's `food_reachable_safely`), rules, derived reads; `audit_questions` | not transferable as training. `improve` already compiles the VLM's reasoning about a loss into questions and reads; reasoning about successes is the missing half |
| Gemini Pro planner every k steps with a summary as memory (p21) | VLM only on a miss | a slow loop: VLM every k ticks sets `task` and keeps a summary; fits the frozen-decider split |
| SFT, RL, forgetting mitigation, Genie 3 | n/a | not transferable: needs a trainable model or a world model |

## 3. What to build next, ranked

1. **Tasks in the pack and a task setter.** `tasks:` entries `{id, instruction, when, done, limit_ticks, category}`
with `when` and `done` as rule conditions on reads, `done` required to hold for n ticks. The author writes the first
from the demonstration; a setter (VLM, per episode or every k ticks) proposes new ones from the typed frame and the
frame, prefers the worst category, and may switch mid-episode. Jev gets `task` beside `how_to_play`. Benefit: a
loss-only loop becomes practice on goals; the SIMA mechanism with the strongest evidence (p24). Cost: schema, loop,
one prompt; moderate.

2. **Positive incidents.** When `done` fires, bank the last 12 decisions as a success incident. `verify_revision`
already replays `others`; require that a candidate keep the successful choices allowed (the existing `overblocked`
test) and run `lessons_of` on the pack that completed a new task. Benefit: SIMA trains only on successes; anygame
learns only from the fatal tick. Cost: low, all in `learn.py` and `Bank`.

3. **Evaluation Suite 2.0 for packs.** `cmd_bench` over tasks: success per category, held-out packs outside
`pool_lessons`, a human or explorer reference per task, persistence, stillness, time limits, and SIMA's two numbers
per pack (within the limit, without). Benefit: today "better" is ticks survived. Cost: harness only, moderate.

4. **Episode rater with calibration.** A VLM rates 8-12 sampled frames and the action log, 0 to 100, for completion
and directedness, its prompt tuned until its order agrees with `better_episode` and the item 3 references. Use it as
`score` where no `score_read` exists and as the trial verdict with a margin. Benefit: a reward for games with no
readable score, and a measure of wasted moves. Cost: cents per episode; rater and proposer share a model, so the trial
episode stays the last word (METHOD.md).

5. **Held inputs, relative mouse, chunks.** `key` gains `hold_ms`, a `mouse_move` kind takes `[dx, dy]`, and a
`chunk` action offers short sequences mined from the demonstration's recurring key runs. Benefit: 3D and action
games need a held key (The Gunk's HOLD, p18) and anygame cannot express one. Cost: every device (`screen.py`,
`web.py`, `tab.ts`) and the explorer; moderate, and `settle` must learn chunk durations.
