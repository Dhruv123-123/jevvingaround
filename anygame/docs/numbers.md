# Numbers: read from the exact text, then found in RAM

2026-10-04, full-run gap 3 (`full-run-gaps.md`). Healing, training, buying and the Elite Four all depend on numbers:
HP, levels, money and counts. The agent had none of them.

## How it works

`anygame/numbers.py`, `NumberBook`:
- **Read.** `observe(text, ram)` takes the screen's exact text (`kind: tiletext`) and finds every number in it, with
  a label and a shape. The label is the nearest word before the number. The shape is `#` or `#/#`, plus whatever is
  glued to the number (`:L#`, `$#`, `x#`). A fraction also gets a share. For example, "SQUIRTLE 13/ 19" becomes
  `SQUIRTLE #/#` = 13 of 19, a share of 0.684.
- **Bind to RAM.** Work RAM is kept beside each reading. Once a number has shown three different values, the bytes
  that matched it every time are where the game keeps it. The book checks four encodings: one byte, a 16-bit pair
  in either byte order, and BCD.
- **Read it later.** From then on `values(ram)` reads the number from RAM whether or not it is on screen. The bound
  places vote, so a scratch copy that has moved on is outvoted.
- **Goals.** `check()` and `holds()` handle the goal condition `{number: {name, at_least | at_most | share_at_least |
  share_at_most}}`, which lets the goal writer say "heal until HP is at least 80%" or "train until level 14".

Nothing in it names a game.

## Measured (`scripts/numbers_check.py`, Pokemon Red rival battle, TACKLE every turn)

| turn | SQUIRTLE HP read from the screen | true HP (grader) |
|---|---|---|
| 2 | 13/19 | 13 |
| 3 | 10/19 | 10 |
| 6 | 4/19 | 4 |
| 8 | 1/19 | 1 |

On the first run the HP digits read as `?` until the labeller learned them. Two tiletext changes fixed that, and
both are in this PR:
- a short queue of unlabelled lines is sent to the labeller after 20 reads, not only when 6 lines are waiting;
- a status line ("13/ 19") is trusted from one reading when every other glyph in it was read exactly as already
  trusted.

After four different HP values, `SQUIRTLE #/#` was bound to 14 places. Among them are `0xD015` (u16 big-endian),
which is pret's `wBattleMonHP`, and `0xD16C`, the party copy. The grader's map was used only to check this. At the
end of the run, with no new reading, the book read HP 3 of 19 from RAM. Turn 5's 7 HP read as `?/`, because the
glyph for 7 had not been learned yet.

Aevilia: its first 300 presses print no numbers (its demo has no HP, money or counts on screen). The read and the
binding are the same code; they are checked there when a screen shows numbers.

## Where it plugs in (other threads' files)

- **Loop** (long-horizon thread): once per tick, after reads,
  `book.observe(values.get("text", ""), ram); values["numbers"] = book.values(ram)`, with
  `ram = anygame.discover.ram(device.memory)`.
- **Goals** (`goals.py`, long-horizon thread): add `number` to `check()` (via `numbers.check`) and to `_holds()` (via
  `numbers.holds`). Also give the goal writer the names and values of the known numbers.

## Limits

- A label is only the word before the number. Two "HP" displays on one screen get `(2)` suffixes.
- A number shown with fewer than three different values (a level that has not changed) stays screen-only.
- An enemy's HP drawn as a bar has no number. Bars are not read yet.
