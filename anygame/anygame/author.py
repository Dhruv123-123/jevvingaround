"""`anygame author`: a slow model writes the pack, the runtime checks it, the fast model plays it.

The slow model (any vision model on OpenRouter; Claude by default) gets probe frames with a pixel grid, the
dominant colours with their hex codes, the pack format and three real packs, and writes a pack.yaml with
tests over the probe frames. The runtime then loads the pack, runs its reads on every frame and hands the
model exactly what its reads produced, so it can correct colours, rects and expectations. A few rounds of
that and the pack passes `anygame eval` without anyone opening an image editor.
"""
from __future__ import annotations
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLE_PACKS = ("2048", "connect4", "snake")

FORMAT = """
# Pack format (YAML). Everything the runtime needs to play a game from its screen.
game: <name>
screen: { orientation: portrait, size: [W, H] }          # the frame size the rects below are measured on
zones:                                                    # named rectangles; rect_px is pixels on that frame,
  board: { rect_px: [x0, y0, x1, y1], grid: [cols, rows] }   # rect is normalized 0..1. grid names cells c<col>r<row>
  status: { rect_px: [x0, y0, x1, y1] }                   # (1-based); a 1-row grid names c1..cN, a 1-col grid r1..rN
read:                                                     # each read is one key of the state the model sees
  <id>: { kind: color, zone: <zone>, options: { <label>: "#hex", ... }, max_dist: 60, otherwise: <label>, inset: 0.25, as: matrix, parse: int }
        # nearest named colour of the region's MEDIAN colour (per cell when the zone has a grid). max_dist is
        # Lab distance (40 strict, 90 loose). inset trims the cell border fraction. as: matrix shows a grid
        # as row strings (top row first). parse: int turns labels into numbers. stat: accent reads the colour
        # of whatever is DRAWN on the cell (a glyph, an icon, a piece) instead of the background: use it when
        # the symbols are letters or shapes on a flat cell, with the background colour as the empty option.
  <id>: { kind: ocr, zone: <zone>, parse: int, every: 4 }   # text/number by OCR; slow, so refresh every N ticks
  <id>: { kind: bar, zone: <zone>, color: "#hex", scale: 10 }   # fraction of a bar filled with a colour, times scale
  <id>: { kind: locate, in: <grid read id>, symbol: <label>, many: true, row: 1 }   # cell(s) holding a label
  <id>: { kind: runs, in: <grid read id>, symbol: <label>, length: 4, empty: ".", gravity: down, mode: hands }
        # empty cells that would complete `length` in a line for `symbol`; gravity: down keeps only landing
        # cells; mode: hands = landing cells whose cell above completes the line (drop there and you lose)
  <id>: { kind: around, of: <locate read id>, in: <grid read id>, free: [".", F] }
        # {up,down,left,right,ahead} neighbours plus <dir>_free (open cells that way) and <dir>_space (flood fill)
  <id>: { ..., history: 1 }        # also exposes <id>_prev; for a located cell <id>_moving and <id>_reverse
  <id>: { kind: tetris, in: <board grid read>, next_in: <preview grid read>, empty: ".", top_k: 6, moves_per_row: 3,
          keys: { rotate: ArrowUp, left: ArrowLeft, right: ArrowRight, drop: Space } }
        # falling-block games: the piece, the stack's features, and the reachable landings with computed
        # consequences as options a..f; pair it with a macro action
act:                                                      # typed actions; the model chooses one per tick
  - { id: <name>, kind: tap, zone: <grid zone>, description: "..." }   # the runtime also asks which cell: <id>__cell
  - { id: <name>, kind: tap, zone: <zone> }                            # tap the zone centre
  - { id: <name>, kind: swipe, zone: <zone>, dir: up|down|left|right, ms: 60 }
  - { id: <name>, kind: key, key: ArrowUp }                            # keyboard (web devices)
  - { id: place, kind: macro, options: <tetris read id>, key_ms: 40 }   # the runtime asks <id>__option among the read's landings and plays the keys
  - { id: keep, kind: wait, description: "do nothing this tick" }
tick_hz: 4                                                # decisions per second, at most
act_when:  { read: <id>, equals: <value> }                # only act when this holds (our turn)
stop_when: { read: <id>, in: [<value>, ...] }             # end the run
settle: screen_change                                     # after an action wait for the screen to change before deciding again (real-time games)
play: >                                                   # the paragraph: how to play, in terms of the read ids above
  ...
questions:                                                # asked every tick, all in one call; the model sees the reads
  - { id: <belief>, type: noul, instructions: "...?", criteria: { true: "...", false: "..." } }
  - { id: <name>, type: choice, instructions: "...", criteria: { a: "...", b: "..." } }
  # an `action` choice question whose criteria are the action ids is optional; without it the runtime builds one from `act`
rules:                                                    # policy the runtime enforces in the same tick
  - { if: { noul: <belief>, gte: 0.6 }, exclude: [<action>, $<read>] }      # $read = that read's value
  - { if: { read: <id>.<path>, in: [s, wall] }, exclude: [<action>] }       # equals|in|not|gte|lte
  - { if: { noul: <belief>, gte: 0.5 }, set: { <action>__cell: <choice question id> } }
  - { if: { read: <id>, equals: our_turn }, avoid: { <action>__cell: <read listing cells> } }   # drop those cells
  - { if: { read: <id>, equals: our_turn }, only:  { <action>__cell: <read listing cells> } }   # offer only those cells
tests:                                                    # required: perception checks on the frames provided
  - { frame: fixtures/probe-1.png, expect: { <read id>: <exact value>, ... } }
  # expect values must be exactly what the read returns: a label, a number, a cell name, a list of cells,
  # or for a grid read a {cell: value} map (partial is fine) or, with as: matrix, a list of row strings.
"""

SYSTEM = """You write anygame packs: a YAML file that lets a fast judgment model (TypeSafe Jev) play a game from
its screen. Jev sees only the compiled reads (labels, numbers, cells), never pixels, and it cannot count or
compare numbers reliably, so anything arithmetic (which cell completes a line, what is next to the head) must
be a derived read (locate, runs, around), and anything fatal must be a rule, not advice.

Write colour reads from the palette hex codes given (they are measured medians), rects from the pixel grid
drawn on the frames, and tests whose expectations are exactly what the frames show. Prefer colour reads over
OCR for anything that has its own colour. Keep the play paragraph short and in terms of the read ids.
Answer with ONE fenced ```yaml block containing the whole pack.yaml, then a short note."""


def grid_overlay(frame: np.ndarray, step: int = 50) -> np.ndarray:
    """The frame with a labelled pixel grid so the model can read rects off it."""
    img = frame.copy()
    h, w = img.shape[:2]
    for x in range(0, w, step):
        cv2.line(img, (x, 0), (x, h), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(img, str(x), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1, cv2.LINE_AA)
    for y in range(0, h, step):
        cv2.line(img, (0, y), (w, y), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(img, str(y), (2, y - 2 if y else 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1, cv2.LINE_AA)
    return cv2.addWeighted(frame, 0.35, img, 0.65, 0)


def palette(frame: np.ndarray, k: int = 14) -> list[dict[str, Any]]:
    """Dominant colours as hex with share and bounding box, from k-means on a downsampled frame."""
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    px = small.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centres = cv2.kmeans(px, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(small.shape[:2])
    out = []
    for i, c in enumerate(centres):
        mask = labels == i
        share = float(mask.mean())
        if share < 0.002:
            continue
        ys, xs = np.where(mask)
        b, g, r = [int(v) for v in c]
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(share, 3),
                    "bbox_px": [int(xs.min() * 4), int(ys.min() * 4), int(xs.max() * 4) + 4, int(ys.max() * 4) + 4]})
    return sorted(out, key=lambda d: -d["share"])


def probe(device, out_dir: Path, n: int = 4, keys: bool = True) -> list[Path]:
    """Frames from a short exploration: the start, then after taps and keys, keeping only frames that differ."""
    from .loop import stable_hash
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = device.size()
    frames: list[Path] = []
    seen: set[str] = set()

    def keep():
        f = device.frame()
        hsh = stable_hash(cv2.resize(f, (64, 64)).tolist())
        if hsh in seen or len(frames) >= n:
            return
        seen.add(hsh)
        p = out_dir / f"probe-{len(frames) + 1}.png"
        cv2.imwrite(str(p), f)
        frames.append(p)

    time.sleep(0.5)
    keep()
    # after every input, look twice: right away (a transient state such as the opponent's turn) and once settled
    moves = [("tap", w // 2, h // 2), ("tap", w // 4, h // 2), ("tap", 3 * w // 4, h // 2), ("tap", w // 2, h // 4), ("tap", w // 2, 3 * h // 4),
             ("tap", w // 4, h // 4), ("tap", 3 * w // 4, 3 * h // 4), ("tap", w // 4, 3 * h // 4), ("tap", 3 * w // 4, h // 4)]
    for m in moves:
        if len(frames) >= n:
            break
        try:
            device.tap(m[1], m[2])
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.12)
        keep()
        time.sleep(0.8)
        keep()
    if keys:
        for k in ("ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Space"):
            if len(frames) >= n:
                break
            try:
                device.key(k)
            except Exception:  # noqa: BLE001
                break
            time.sleep(0.12)
            keep()
            time.sleep(0.8)
            keep()
    return frames


def _b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


class Author:
    """The authoring model: any vision-capable chat model, routed by ANYGAME_LLM_* (Azure or OpenAI-compatible)."""

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        from .chat import Chat
        self.chat = Chat(model=model or os.environ.get("ANYGAME_AUTHOR_MODEL"), api_key=api_key, base_url=base_url)
        self.model = self.chat.model
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]

    @property
    def cost(self) -> float:
        return self.chat.cost

    def ask(self, parts: list[dict[str, Any]]) -> str:
        self.messages.append({"role": "user", "content": parts})
        text, _usage, _ms = self.chat.complete(self.messages, max_tokens=12000, temperature=0.2)
        self.messages.append({"role": "assistant", "content": text})
        return text


def extract_yaml(text: str) -> str | None:
    m = re.search(r"```ya?ml\s*\n(.*?)```", text, re.S)
    return m.group(1) if m else None


def examples_text() -> str:
    from .cli import find_pack
    out = []
    for name in EXAMPLE_PACKS:
        try:
            p = find_pack(name)
        except SystemExit:
            continue
        out.append(f"### example pack: {name}\n```yaml\n{Path(p).read_text()}\n```")
    return "\n\n".join(out)


def expectations(pack_dir: Path) -> dict[str, dict[str, Any]]:
    """{frame: {read: expected}} from the pack's tests, for spotting expectations that were changed to fit a read."""
    import yaml
    try:
        raw = yaml.safe_load((pack_dir / "pack.yaml").read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}
    return {t.get("frame", ""): dict(t.get("expect") or {}) for t in (raw.get("tests") or []) if isinstance(t, dict)}


def verify_changes(au: "Author", pack_dir: Path, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[str]:
    """When a round changes what a test expects, ask the model to look at the frame again and confirm each new
    value in isolation. A 'no' means the read is wrong and the test was bent to it. Returns the rejected items."""
    changed = []
    for frame, exp in after.items():
        for read, val in exp.items():
            old = before.get(frame, {}).get(read, None)
            if old is not None and old != val:
                changed.append((frame, read, old, val))
    if not changed:
        return []
    parts: list[dict[str, Any]] = [{"type": "text", "text":
        "Some test expectations changed between rounds. For each item look at the frame again and answer whether the NEW "
        "value is exactly what the frame shows. Reply with one JSON object {\"1\": true/false, ...} and nothing else."}]
    for i, (frame, read, old, val) in enumerate(changed, 1):
        img = cv2.imread(str(pack_dir / frame))
        parts.append({"type": "text", "text": f"{i}. frame {frame}, read `{read}`: previously expected {json.dumps(old)}, now expected {json.dumps(val)}"})
        if img is not None:
            parts.append({"type": "image_url", "image_url": {"url": _b64(img)}})
    text = au.ask(parts)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        verdict = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        verdict = {}
    rejected = []
    for i, (frame, read, old, val) in enumerate(changed, 1):
        if not verdict.get(str(i), False):
            rejected.append(f"{frame}: `{read}` now expects {json.dumps(val)} but the frame shows {json.dumps(old)}: the READ is wrong, fix the read (colours, rect, inset, stat) and restore the expectation")
    return rejected


def check_pack(pack_dir: Path, frames: list[Path]) -> tuple[bool, str]:
    """Load the pack, run every test, and dump what every read sees on every probe frame."""
    from .loop import Agent
    from .pack import PackError, load_pack
    from .perceive import read_all
    from .cli import _Dummy, _match
    try:
        pack = load_pack(pack_dir)
    except PackError as e:
        return False, f"PACK ERROR: {e}"
    lines = []
    ok = True
    ag = Agent(pack, device=_Dummy(pack.size), jev=None)
    for f in frames:
        frame = cv2.imread(str(f))
        try:
            values, _, timings = ag.observe(frame)
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"{f.name}: READ ERROR {type(e).__name__}: {e}")
            continue
        shown = json.dumps(values, default=str)
        lines.append(f"{f.name}: reads → {shown[:1800]}")
    for t in pack.tests:
        frame = cv2.imread(str(pack.path.parent / t["frame"]))
        if frame is None:
            ok = False
            lines.append(f"TEST {t['frame']}: frame not found")
            continue
        values, _, _ = ag.observe(frame)
        misses = {k: (v, values.get(k)) for k, v in t["expect"].items() if not _match(v, values.get(k))}
        if misses:
            ok = False
            lines.append(f"TEST {t['frame']}: MISMATCH " + "; ".join(f"{k}: expected {e!r} got {g!r}" for k, (e, g) in misses.items()))
        else:
            lines.append(f"TEST {t['frame']}: ok")
    return ok, "\n".join(lines)


def play_digest(summary: dict[str, Any], log_path: Path, max_lines: int = 12) -> str:
    """What happened when the pack was played, compressed for the authoring model: outcome, what the actions did,
    how often the screen failed to change, which rules fired, sensor timing, and a few sampled ticks."""
    recs = [json.loads(l) for l in open(log_path)] if log_path.exists() else []
    dec = [r for r in recs if "jev_ms" in r]
    from collections import Counter
    acts = Counter(r["action"].split(" (")[0] for r in dec)
    noop = sum(1 for r in recs if r.get("reason") == "screen unchanged")
    rules = Counter(x.split(" → ")[0] for r in dec for x in (r.get("rules") or []))
    lines = [f"OUTCOME: {summary.get('reason') or 'tick cap reached (' + str(summary.get('ticks')) + ' ticks)'}",
             f"ticks {summary.get('ticks')}, decisions {len(dec)}, screen-unchanged waits {noop}, sensor errors {summary.get('sensor_errors')}, "
             f"sensor p50 {summary.get('sensor_ms_p50')} ms, cost ${summary.get('total_cost_usd')}",
             f"actions taken: {dict(acts.most_common())}",
             f"rules fired: {dict(rules.most_common())}",
             f"final screen: {json.dumps(summary.get('final_screen'), default=str)[:600]}"]
    step = max(1, len(dec) // max_lines)
    for r in dec[::step][:max_lines]:
        scr = {k: v for k, v in r["screen"].items() if not str(k).endswith("_prev")}
        lines.append(f"tick {r['tick']}: screen={json.dumps(scr, default=str)[:400]} → {r['action']} probs={r.get('action_probs')} beliefs={r.get('nouls')} rules={r.get('rules')}")
    return "\n".join(lines)


def _better(a: dict[str, Any] | None, b: dict[str, Any], score_read: str | None) -> bool:
    """Is play summary b better than a? won > not lost > longer > higher score."""
    if a is None:
        return True
    def key(s):
        reason = str(s.get("reason") or "")
        won = "we_won" in reason or "won" in reason
        lost = "we_lost" in reason or "dead" in reason or "over" in reason
        score = (s.get("final_screen") or {}).get(score_read or "score")
        return (1 if won else 0, 0 if lost else 1, s.get("ticks", 0) if lost else 0, float(score) if isinstance(score, (int, float)) else 0.0)
    return key(b) > key(a)


def author(device_url: str, game: str, out: Path, play: str | None = None, rounds: int = 3, model: str | None = None,
           frames_n: int = 4, size: tuple[int, int] = (540, 560), play_ticks: int = 0, tune: int = 0, sensor: str = "jev",
           score_read: str | None = None, log=print, demo: Path | None = None) -> tuple[bool, Path]:
    """Write a pack for the game behind device_url. rounds: perception rounds until eval passes. tune: after that,
    play `play_ticks` ticks, hand the model a digest of the run, and let it revise the paragraph, questions and
    rules; the best-playing pack is kept."""
    from .device import open_device
    out.mkdir(parents=True, exist_ok=True)
    fixtures = out / "fixtures"
    demo_text, demo_parts = "", []
    if demo is not None:
        from .demo import load_demo, digest as demo_digest
        d = load_demo(Path(demo))
        dg = demo_digest(d)
        fixtures.mkdir(parents=True, exist_ok=True)
        picks = [f for _, f in d["frames"] if f is not None]
        step = max(1, len(picks) // frames_n)
        frames = []
        for i, f in enumerate(picks[::step][:frames_n], 1):
            pth = fixtures / f"probe-{i}.png"
            cv2.imwrite(str(pth), f)
            frames.append(pth)
        demo_text = "\n\n" + dg["text"] + "\n"
        for pr in dg["pairs"]:
            demo_parts.append({"type": "text", "text": f"before and after the input {json.dumps(pr['event'])}:"})
            demo_parts.append({"type": "image_url", "image_url": {"url": _b64(pr["before"])}})
            demo_parts.append({"type": "image_url", "image_url": {"url": _b64(pr["after"])}})
        log(f"using a {dg['seconds']}s {d['source']} demonstration with {len(d['events'])} inputs")
    else:
        dev = open_device(device_url, size)
        try:
            frames = probe(dev, fixtures, n=frames_n, keys=device_url.startswith("web://"))
        finally:
            dev.close()
        log(f"probed {len(frames)} distinct frames into {fixtures}")
    w, h = size
    au = Author(model=model)
    parts: list[dict[str, Any]] = [{"type": "text", "text":
        f"Game: {game}\nDevice: {device_url}\nFrame size: {w}x{h} pixels (write rect_px in these pixels).\n"
        + (f"How the user wants it played: {play}\n" if play else "")
        + (f"\nThe frames fixtures/probe-1.png … fixtures/probe-{len(frames)}.png are sampled from a demonstration of someone playing (details below)." if demo is not None else
           f"\nProbe frames are fixtures/probe-1.png … fixtures/probe-{len(frames)}.png, in order: the start screen, then after "
           "taps at the centre / left / right / top / bottom and arrow keys.")
        + " Each is shown twice: raw, then with a 50 px grid.\n" + demo_text
        + FORMAT + "\n\n" + examples_text()}]
    for i, f in enumerate(frames, 1):
        img = cv2.imread(str(f))
        pal = palette(img)
        parts.append({"type": "text", "text": f"--- fixtures/probe-{i}.png raw, then with grid. Dominant colours (median hex, share, bbox px): {json.dumps(pal)}"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(img)}})
        parts.append({"type": "image_url", "image_url": {"url": _b64(grid_overlay(img))}})
    parts.extend(demo_parts)
    parts.append({"type": "text", "text": "Write the complete pack.yaml now, with a test for every probe frame."
                  + (" Use the demonstration: the keys and clicks it used are the action set, the regions that changed are where the reads go, and what the player said they were doing goes into the paragraph." if demo is not None else "")})
    ok = False
    prev_exp: dict[str, dict[str, Any]] = {}
    for rnd in range(1, rounds + 1):
        log(f"round {rnd}: asking {au.model} …")
        text = au.ask(parts)
        y = extract_yaml(text)
        if not y:
            parts = [{"type": "text", "text": "I could not find a ```yaml block. Send the whole pack.yaml in one fenced yaml block."}]
            continue
        (out / "pack.yaml").write_text(y)
        ok, report = check_pack(out, frames)
        cur_exp = expectations(out)
        if ok and prev_exp:
            rejected = verify_changes(au, out, prev_exp, cur_exp)
            if rejected:
                ok = False
                report += "\nEXPECTATIONS CHANGED TO FIT A WRONG READ (the model itself confirmed the frame disagrees):\n" + "\n".join(rejected)
        prev_exp = prev_exp or cur_exp      # round 1's expectations are what the model saw in the images: the bar
        log(report)
        log(f"round {rnd}: {'PASS' if ok else 'FAIL'}  (author spend so far ${au.cost:.4f})")
        if ok:
            break
        parts = [{"type": "text", "text":
            "Here is what your pack does on the probe frames. Fix the pack so every test passes: correct colours "
            "(use the median hex values), rects, grid sizes, max_dist, and the expectations themselves where the read is "
            "right and the expectation was wrong. Return the whole corrected pack.yaml in one fenced yaml block.\n\n" + report}]
    if ok and play_ticks:
        from .cli import cmd_play_inline
        best: dict[str, Any] | None = None
        best_yaml = (out / "pack.yaml").read_text()
        for t in range(0, tune + 1):
            log_path = out / f"play-{t}.jsonl"
            rec_dir = out / f"play-{t}-frames"
            summary = cmd_play_inline(out, device_url, play_ticks, log_path=str(log_path), sensor=sensor, record_dir=str(rec_dir))
            digest = play_digest(summary, log_path)
            if summary.get("reason") and summary.get("ticks", 0) <= 3 and "stop_when" in (out / "pack.yaml").read_text():
                digest = ("WARNING: stop_when fired after only " + str(summary.get("ticks")) + " ticks. Almost certainly a read met a state it has no "
                          "option for (the opponent's turn, an animation) and fell to `otherwise`. Look at the last frames below, add the missing "
                          "options with their colours, and make stop_when match only real end states.\n\n") + digest
            log(f"play {t}: {summary.get('reason') or 'tick cap'} after {summary.get('ticks')} ticks, ${summary.get('total_cost_usd')}")
            if _better(best, summary, score_read):
                best, best_yaml = summary, (out / "pack.yaml").read_text()
            if t == tune:
                break
            log(f"tune {t + 1}: asking {au.model} …")
            tune_parts: list[dict[str, Any]] = [{"type": "text", "text":
                "The pack passes its perception tests. Here is how it PLAYED. Revise the pack so it plays better: the play "
                "paragraph, the questions, the rules (move any counting into derived reads: runs, around, locate; make "
                "fatal or wasted moves impossible with exclude/avoid/only rules; add act_when/settle/stop_when if the "
                "log shows waits or missed turns). Keep the zones, reads and tests that pass unless the log or the frames "
                "show a read is wrong. Return the whole pack.yaml in one fenced yaml block.\n\n" + digest}]
            shots = sorted(rec_dir.glob("*.jpg")) if rec_dir.exists() else []
            for f in ([shots[len(shots) // 2], shots[-1]] if len(shots) > 2 else shots):
                img = cv2.imread(str(f))
                if img is not None:
                    tune_parts.append({"type": "text", "text": f"frame at tick {int(f.stem)} of the play run (raw, then with the pixel grid):"})
                    tune_parts.append({"type": "image_url", "image_url": {"url": _b64(img)}})
                    tune_parts.append({"type": "image_url", "image_url": {"url": _b64(grid_overlay(img))}})
            try:
                text = au.ask(tune_parts)
            except Exception as e:  # noqa: BLE001 — keep the best pack so far rather than lose the run
                log(f"tune {t + 1}: model call failed ({str(e)[:120]}); keeping the best pack so far")
                break
            y = extract_yaml(text)
            if not y:
                break
            (out / "pack.yaml").write_text(y)
            ok2, report = check_pack(out, frames)
            if not ok2:
                log("tuned pack broke perception; keeping the previous one\n" + report)
                (out / "pack.yaml").write_text(best_yaml)
                break
        (out / "pack.yaml").write_text(best_yaml)
        log(f"kept the best-playing pack: {best.get('reason') or 'tick cap'} after {best.get('ticks')} ticks" if best else "no play result")
    log(f"author spend: ${au.cost:.4f} on {au.model}")
    return ok, out
