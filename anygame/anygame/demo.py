"""Demonstrations for the Python runtime: the explorer (a vision model plays slowly with intents) writes a
demonstration directory (frames as PNG + events.jsonl); the author reads one instead of the blind probe.
Mirror of ext/src/core/{demo,explore}.ts."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .chat import Chat
from .fallback import _data_url

EXPLORE_SYSTEM = """You are exploring a game to learn how it is played, one input at a time. Each turn you see the current frame.
Reply with ONE JSON object: {"action": {"kind": "key", "key": "ArrowLeft"} | {"kind": "tap", "at": [x, y]} | {"kind": "wait"},
"intent": "<one short line: what you are trying to do and what you expect to happen>"}.
Keys you may use: ArrowUp ArrowDown ArrowLeft ArrowRight Space Enter Escape and single letters. Taps are pixels on the frame.
Try the obvious controls first, then play to make progress. Say when a screen is a menu, a dialog, a game over, or the game itself."""


def explore(device, out: Path, seconds: int = 90, game: str = "", chat: Chat | None = None, log=print) -> Path:
    """The VLM plays for `seconds`; frames and inputs land in `out` as a demonstration."""
    chat = chat or Chat()
    out.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = [{"role": "system", "content": EXPLORE_SYSTEM}]
    t0 = time.perf_counter()
    n = 0
    h, w = device.frame().shape[:2]

    def snap() -> None:
        nonlocal n
        n += 1
        cv2.imwrite(str(out / f"{n:05d}.png"), device.frame())
        events.append({"t": round((time.perf_counter() - t0) * 1000), "type": "frame", "file": f"{n:05d}.png"})

    step = 0
    while time.perf_counter() - t0 < seconds:
        snap()
        frame = cv2.imread(str(out / f"{n:05d}.png"))
        step += 1
        messages.append({"role": "user", "content": [{"type": "text", "text": f"Game: {game}. Step {step}, {int(time.perf_counter() - t0)}s in, frame {w}x{h}."}, {"type": "image_url", "image_url": {"url": _data_url(frame)}}]})
        try:
            text, _u, _ms = chat.complete(messages, max_tokens=300, temperature=0)
            messages.append({"role": "assistant", "content": text})
            m = re.search(r"\{.*\}", text, re.S)
            j = json.loads(m.group(0)) if m else {}
        except Exception as e:  # noqa: BLE001
            log(f"explore: {str(e)[:100]}")
            time.sleep(2)
            continue
        if len(messages) > 14:
            del messages[1:3]
        a = j.get("action") or {}
        t = round((time.perf_counter() - t0) * 1000)
        if a.get("kind") == "key" and a.get("key"):
            device.key(a["key"])
            events.append({"t": t, "type": "key", "key": a["key"], "intent": j.get("intent")})
        elif a.get("kind") == "tap" and a.get("at"):
            x, y = int(a["at"][0]), int(a["at"][1])
            device.tap(x, y)
            events.append({"t": t, "type": "click", "x": x, "y": y, "intent": j.get("intent")})
        else:
            events.append({"t": t, "type": "wait", "intent": j.get("intent")})
        log(f"explore {step}: {json.dumps(a)} — {j.get('intent', '')}")
        time.sleep(0.4)
    snap()
    (out / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (out / "meta.json").write_text(json.dumps({"source": "explorer", "game": game, "seconds": seconds}))
    return out


def load_demo(path: Path) -> dict[str, Any]:
    """{frames: [(t, ndarray)], events: [...], source}. events.jsonl from `explore` or from the extension's export."""
    events = [json.loads(l) for l in (path / "events.jsonl").read_text().splitlines() if l.strip()]
    frames = [(e["t"], cv2.imread(str(path / e["file"]))) for e in events if e.get("type") == "frame"]
    meta = json.loads((path / "meta.json").read_text()) if (path / "meta.json").exists() else {}
    return {"frames": frames, "events": [e for e in events if e.get("type") != "frame"], "source": meta.get("source", "human"), "notes": meta.get("notes")}


def digest(demo: dict[str, Any], max_pairs: int = 6) -> dict[str, Any]:
    """What the author needs from a demonstration: keys used, click clusters, the regions that change, before/after pairs, intents."""
    keys: dict[str, int] = {}
    clusters: list[dict[str, Any]] = []
    for e in demo["events"]:
        if e["type"] == "key":
            keys[e["key"]] = keys.get(e["key"], 0) + 1
        elif e["type"] == "click":
            c = next((k for k in clusters if np.hypot(k["x"] - e["x"], k["y"] - e["y"]) <= 40), None)
            if c:
                c["x"] = (c["x"] * c["n"] + e["x"]) / (c["n"] + 1); c["y"] = (c["y"] * c["n"] + e["y"]) / (c["n"] + 1); c["n"] += 1
            else:
                clusters.append({"x": e["x"], "y": e["y"], "n": 1})
    clusters = sorted(({**c, "x": int(c["x"]), "y": int(c["y"])} for c in clusters), key=lambda c: -c["n"])
    change = np.zeros((8, 8))
    fr = demo["frames"]
    for (_, a), (_, b) in zip(fr, fr[1:]):
        if a is None or b is None:
            continue
        d = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2)
        h, w = d.shape
        for gy in range(8):
            for gx in range(8):
                change[gy, gx] += min(1.0, float(d[gy * h // 8:(gy + 1) * h // 8, gx * w // 8:(gx + 1) * w // 8].mean()) / 120)
    if len(fr) > 1:
        change /= len(fr) - 1
    hot = sorted(((round(float(change[y, x]), 2), x, y) for y in range(8) for x in range(8) if change[y, x] > 0.15), reverse=True)[:12]
    pairs = []
    step = max(1, len(demo["events"]) // max_pairs)
    for e in demo["events"][::step][:max_pairs]:
        before = next(((t, f) for t, f in reversed(fr) if t <= e["t"]), None)
        after = next(((t, f) for t, f in fr if t >= e["t"] + 150), None)
        if before and after and before[0] != after[0]:
            pairs.append({"event": e, "before": before[1], "after": after[1]})
    intents = [e["intent"] for e in demo["events"] if e.get("intent")]
    seconds = round((fr[-1][0] - fr[0][0]) / 1000, 1) if fr else 0
    text = "\n".join(x for x in [
        f"DEMONSTRATION ({demo['source']}): {seconds}s, {len(fr)} frames, {len(demo['events'])} inputs.",
        f"keys used: {json.dumps(keys)}",
        f"click clusters (px, count): {json.dumps(clusters[:12])}",
        f"regions that change most (8x8 grid, [value, x, y]): {json.dumps(hot)}",
        f"what the player said they were doing: {json.dumps(intents[:20])}" if intents else "",
        f"notes: {demo['notes']}" if demo.get("notes") else "",
    ] if x)
    return {"seconds": seconds, "keys": keys, "clicks": clusters, "hot": hot, "pairs": pairs, "intents": intents, "text": text}
