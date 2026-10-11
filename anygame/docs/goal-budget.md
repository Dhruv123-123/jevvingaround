# When to ask the goal writer (gap 7)

The goal writer (a chat model on Azure, `goals.py`) is now the biggest Azure cost: 412 calls across the Aevilia and
Pokemon runs, about $0.51. A run is capped at 60 calls, and a whole Pokemon game at the current rate would need
about 2,400. Most of the calls bought nothing.

## What the calls did

Every logged writer call (`longhorizon/goal-calls/*.jsonl`, 412 calls in 23 runs), classed by its answer:

| answer | calls |
|---|---|
| kept the goal it had | 140 (34%) |
| a new goal identical to the one before it | 120 (29%) |
| the generic "enter a new place", no direction | 49 (12%) |
| "enter a new place" with a direction | 26 (6%) |
| something specific (talk, a word to hear, a place to go back to) | 77 (19%) |

Three quarters of the calls produced a goal the program would have had without asking. Half the gaps between calls
were 15 ticks or less.

Two runs keep their full dialogue log (`pk-standin5`, `pk-standin6`), so each call can be matched with what the game
said since the call before:

- **Calls after a goal ended, with nothing new said since the last call.** These happen when a goal is reached or
  given up; map-label churn makes "enter a new place" come true within a tick or two. 36 such calls: 28 rewrote the
  same goal or the generic one.
- **Calls on "new" text that was not new.** These were the START menu, the save screen, the options screen, and a
  box typing out, all read again with OCR's variations ("OFTION", "FokeMoN"). 26 such calls kept the goal.

## The fix: `anygame/goalgate.py`

`GoalGate` decides when a call is worth it.

- `see(text, screen)` every tick. A line is news only when it is not a menu screen and has at least 3 words the run
  has never seen, making up at least half its words. A misread of a line already seen is not news.
- `ask(tick, frames, need=, ended=)` says to call only:
  - when there is news;
  - when a goal ends and the writer last kept its goal over news (that news may be for the next goal);
  - once after a goal is given up (the writer may know another way).
  
  Otherwise, a goal that ends is followed by the generic goal, for free.
- **Budget:** 16 calls at the start, plus 20 per hour of game time, instead of 60 per run. A run that spends an hour
  in menus cannot use up the calls, and a 12-hour game is not cut off at 60. At about 37 frames a tick, a whole game of
  ~72,000 ticks is about 12 game hours: at most about 260 calls, about $0.30.
- `compact(dialogue)` folds a box typing out into the line it became, and keeps one copy of a line read again. On these
  OCR logs it saves only 2-7% of the dialogue sent, because OCR rarely misreads a line twice the same way. With exact
  text (`tiletext`), the copies are exact.

## Replayed on the two runs

`scripts/goal_budget_replay.py` replays each run's calls through the gate:

| run | calls made | calls the gate makes | specific goals not asked for |
|---|---|---|---|
| pk-standin6 (1,000 ticks) | 34 | 14 | 1: "Go downstairs and enter the next area" (too soon after the last call) |
| pk-standin5 (~600 ticks) | 34 | 13 | 2: "Leave this place and enter a new area", "Leave the room by going downstairs" |

That is about 60% fewer calls. All three goals it would not have asked for are "enter a new place", given a
direction. In Red's house the generic goal finds the same stairs. "Go next door to Professor Oak's place" is still
asked for: the writer kept its goal when Mom said it, so the gate asks again when that goal ends.

## Call sites (for the long-horizon thread, `goals.py`)

- Every tick, in `GoalBook.update`: `gate.see(values.get("text", ""), values.get("screen"))`.
- Replace `if (need or news) and self.chat is not None and self.calls < self.max_calls:` with
  `ok, why = gate.ask(tick, frames, need=self.current is None, ended=<the outcome of the goal that just closed>)`.
  Then `gate.called(tick, frames, entry["result"].split()[0])` after `_write`, where "kept" or "set" is the first word.
- In `context()`, use `compact(self.memory.dialogue)` for the dialogue list. It keeps each line's index `i`, so
  `{line: i}` targets still work.
- `max_calls` can go; the gate's budget replaces it.
