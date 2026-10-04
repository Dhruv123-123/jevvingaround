# Text read exactly: glyphs learned once from the screen's cells

2026-10-03, branch `claude/anygame-pokemon-full-run-gaps-85kn4w`. Full-run gap 1 (`full-run-gaps.md`): the
dialogue, menu labels and battle messages the whole campaign depends on were read by OCR, which reads Pokemon's
naming screen as "Fir=t: what i= YOUF name?" and costs about 220 ms a tick.

## How it works

`kind: tiletext` (`anygame/perceive/tiletext.py`) cuts the native 160x144 screen into 8x8 cells. A two-colour cell
with a small ink mask is a glyph, keyed by its pixels. Unknown glyphs are queued as lines. The Azure chat model is
shown each line enlarged and told how many cells each word has. It answers with a list of words, and an answer
whose word lengths do not match the inked runs is dropped, as is one that disagrees with glyphs already trusted.
A glyph is trusted after two agreeing lines, or after one line that agrees with three trusted glyphs. From then on
the read is a table lookup. The labeller runs in a background thread, so a run never waits for it. Unknown glyphs
read as `?`, and with `fallback: ocr` a screen that is still mostly unknown is read by OCR. Nothing in it names a
game. The glyph book can be saved and reloaded with `book:` or `ANYGAME_GLYPHS`.

`packs/gameboy` now reads `text` this way.

## Measured

`scripts/tiletext_check.py`: scripted presses from power-on (mostly A, plus some START, B and directions). For
Pokemon the truth is the screen tile map in work RAM decoded with pret's charmap. The script uses it for scoring
only; the agent never reads it. Labelling ran in sync mode here, so the learning curve can be compared across runs.

| Pokemon Red, 400 presses (through the intro, naming, Red's room, START menu, options) | tiletext | OCR |
|---|---|---|
| text cells read with a trusted glyph | 78% (the rest read `?`, mostly early on) | n/a |
| of those, right (case kept) | **98.9%**; the only error was lower-case w labelled v, prompt fixed since | n/a |
| similarity to the true text, median, last third of the run | **1.00** | 0.93 |
| similarity, whole run (tiletext still learning at the start) | 0.80 (0.86 with OCR fallback) | 0.86 |
| time per read | **0.75 ms** | 217 ms |
| Azure labeller | 29 calls, 13 s median, 366 s total, 61 glyphs | none |

The first version of the prompt reached 52% accuracy, because the model wrote "Pokémon" where the screen draws
POKéMON. After telling it to keep case and to answer word by word, accuracy is 98.9%. A late sample:
truth `POKéMON ITEM AAAR SAVE OPTION >EXIT`, tiletext the same, OCR `FOREMON ITEM AAAR SAVE OFTION EXIT`.

Aevilia, 300 presses (first prompt; there is no truth decoder, so these are samples):

| tiletext | OCR |
|---|---|
| `Use the d-pad to move around.` | `Use the -pa tomove around.` |
| `O?ay? enough shenanigans.` | `nU shenanisans.` |
| `PAUSE MENU START  : Exit menu B  : Save SELECT : Options DONE!` | `PAUSE HENU TART 一 xit menu ELECT Options DONE!` |
| `??? AEVILIA I NEED TO ?NOW IF YOU ARE A BOY OR ?IRL` | `Choose a character AEVILIAI NEEL TO MONM` |

On Aevilia the check read every frame, including the overworld, so it labelled 743 cells (mostly map tiles as
"not a character") and used up its 40-call cap. In the pack the read only runs on text and choice screens.

## Limits and next

- Labelling costs Azure seconds once per font: about 30 calls for Pokemon's intro alphabet. Glyphs seen in only one
  line stay `?` until a second line confirms them.
- A variable-width font, or text drawn with sprites, gives no repeated cells. That text keeps falling back to OCR.
- `menu.py` still uses OCR for entry labels and outcomes (it belongs to the long-horizon thread). Its two calls,
  `_ocr_boxes` and `_text`, can call `tiletext.reader(...).read(frame)` instead.
- Next is gap 2: a menu choice played out to the next decision, keyed by its now-exact text.

Files: `/mnt/project-files/anygame/pokemon-red/tiletext/` (summary.json, samples.jsonl, labeller.jsonl and
glyphs.json per run).
