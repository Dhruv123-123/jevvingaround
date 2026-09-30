"""The VLM fallback: for a frame the pack does not understand, a vision model returns an action to take now and
what the screen is; decisions are memoised by fingerprint; a mode definition it returns is verified against the
frame before the loop merges it into the pack. Mirror of ext/src/core/fallback.py."""
from __future__ import annotations
import base64
import json
import re
import time
from typing import Any

import cv2
import numpy as np

from .chat import Chat
from .fingerprint import distance, fingerprint

SYSTEM = """You are the fallback for a game-playing runtime. The fast path plays from a typed "pack" (zones, colour reads,
typed actions); it has hit a screen it cannot read. You see the frame. Answer with ONE JSON object:
{
  "now": {"action": "<one of the pack's action ids>", "cell": "<c<col>r<row> if that action taps a grid>"}   // or
         {"kind": "key", "key": "Enter"} or {"kind": "tap", "at": [x, y]} (pixels on this frame) or {"kind": "wait"},
  "screen": "transient" | "mode" | "unknown",
  "name": "<short snake_case name for this screen>",
  "note": "<one line: what this screen is and why that input>",
  "mode": { ... }           // only for "mode": how to play THIS screen, same keys as a pack (zones with rect_px, read with
                            // colour options, act, play, questions, rules, act_when, stop_when), as a JSON object.
                            // Read kinds that exist, nothing else: color {zone, options: {name: "#hex"}, max_dist, otherwise},
                            // ocr {zone, parse: int}, locate {in: <matrix read>, symbol}, around {of, in, free}, runs {in, symbol},
                            // bar {zone, color}, templates. A read with any other kind is rejected and the mode is lost.
  "expect": { "<read id>": <value>, ... }   // for "mode": what the mode's reads must return on this exact frame
}
"transient" is a dialog, overlay or animation that one input dismisses: give the input in "now" and no mode. "mode" is
a real screen the runtime will see again and must play: give the input for now AND a mode definition. Prefer the
pack's own typed actions when one fits; raw key/tap only when none does. Never invent an action id."""


def _data_url(frame: np.ndarray, grid: bool = False) -> str:
    img = frame
    if grid:
        img = frame.copy()
        h, w = img.shape[:2]
        for x in range(0, w, 50):
            cv2.line(img, (x, 0), (x, h), (255, 255, 255), 1)
            cv2.putText(img, str(x), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
        for y in range(0, h, 50):
            cv2.line(img, (0, y), (w, y), (255, 255, 255), 1)
            cv2.putText(img, str(y), (2, y - 2 if y else 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


class VLMFallback:
    def __init__(self, chat: Chat | None = None, memo_threshold: float = 25.0, max_calls: int = 50):
        self.chat = chat or Chat()
        self.memo: list[tuple[np.ndarray, dict[str, Any]]] = []
        self.memo_threshold = memo_threshold
        self.max_calls = max_calls
        self.calls = 0

    def recall(self, fp: np.ndarray) -> dict[str, Any] | None:
        best = None
        for e, d in self.memo:
            dist = distance(e, fp)
            if best is None or dist < best[0]:
                best = (dist, d)
        if best and best[0] <= self.memo_threshold:
            return {**best[1], "memo": True, "ms": 0}
        return None

    def remember(self, fp: np.ndarray, decision: dict[str, Any]) -> None:
        self.memo.append((fp, {k: v for k, v in decision.items() if k not in ("mode", "expect")}))

    def decide(self, frame: np.ndarray, pack, goal: str, recent: list[str]) -> dict[str, Any]:
        fp = fingerprint(frame)
        hit = self.recall(fp)
        if hit:
            return hit
        if self.calls >= self.max_calls:
            return {"now": {"kind": "wait"}, "screen": "unknown", "note": "fallback budget spent", "ms": 0}
        self.calls += 1
        actions = []
        for a in pack.actions:
            z = pack.zone(a.params["zone"]) if a.params.get("zone") else None
            extra = (" " + a.params["key"] if a.params.get("key") else "") + (" " + a.params["dir"] if a.params.get("dir") else "")
            zd = f", zone {a.params['zone']}" + (f" grid {z.grid[0]}x{z.grid[1]}" if z and z.grid else "") if z else ""
            actions.append(f"{a.id} ({a.kind}{extra}{zd})" + (f": {a.params['description']}" if a.params.get("description") else ""))
        h, w = frame.shape[:2]
        t0 = time.perf_counter()
        text, _usage, _ms = self.chat.complete([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": f"Game: {pack.name}. Goal: {goal}\nFrame: {w}x{h} px. Recent actions: {json.dumps(recent[-6:])}\nPack actions:\n" + "\n".join(actions) + "\nThe frame, raw then with a 50 px grid:"},
                {"type": "image_url", "image_url": {"url": _data_url(frame)}},
                {"type": "image_url", "image_url": {"url": _data_url(frame, True)}},
            ]},
        ], max_tokens=4000, temperature=0)
        m = re.search(r"\{.*\}", text, re.S)
        try:
            j = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            j = {}
        d = {
            "now": j.get("now") if isinstance(j.get("now"), dict) else {"kind": "wait"},
            "screen": j.get("screen") if j.get("screen") in ("transient", "mode", "unknown") else "unknown",
            "name": re.sub(r"[^a-z0-9_]+", "_", str(j.get("name") or ""), flags=re.I)[:32] or None,
            "mode": j.get("mode") if isinstance(j.get("mode"), dict) else None,
            "expect": j.get("expect") if isinstance(j.get("expect"), dict) else None,
            "note": str(j.get("note") or "")[:200] or None,
            "ms": int((time.perf_counter() - t0) * 1000),
        }
        if d["screen"] != "unknown":
            self.remember(fp, d)
        return d
