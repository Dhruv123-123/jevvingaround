"""An episode rater: the chat model scores a played episode 0 to 100 for completion (did the play achieve the goal
or the task) and directedness (did the moves serve it, or wander), from a dozen sampled frames and the action log.
SIMA 2's reward model is this rubric over video, tuned on a few human preferences; here it is a VLM over frames,
calibrated against the trial order (`better_episode`) the loop already trusts. Used as the score where a pack has no
score read, and reported next to the trial verdict; never the last word, because rater and proposer share a model."""
from __future__ import annotations
import json
import re
from typing import Any

import numpy as np

RUBRIC = """You rate one episode of a game played by an automated player. You see frames sampled evenly across the episode
(first to last) and a summary of the actions taken. Score two things, each 0 to 100:
- completion: how far the play got toward the goal (and the task, if one is named): 0 nothing, 50 clearly half way or a
  modest success, 100 fully achieved (a won game, a completed task, a long survival with a high score).
- directedness: how much of the play served the goal: 100 every move purposeful, 50 half the moves wasted or
  wandering, 0 random.
Answer with ONE JSON object: {"completion": <int>, "directedness": <int>, "note": "<one line: what happened>"}."""


def sample_frames(frames: list[tuple[int, np.ndarray]], k: int = 10) -> list[tuple[int, np.ndarray]]:
    """k frames spread evenly across the episode, the first and the last always among them."""
    if len(frames) <= k:
        return list(frames)
    idx = sorted({0, len(frames) - 1} | {round(i * (len(frames) - 1) / (k - 1)) for i in range(k)})
    return [frames[i] for i in idx][:k]


def actions_summary(recs: list[dict[str, Any]], limit: int = 40) -> str:
    acts = [str(r.get("action")) for r in recs if r.get("choice") and r.get("choice") != "fallback"]
    if not acts:
        return "no actions"
    from collections import Counter
    c = Counter(acts)
    head = ", ".join(f"{a}×{n}" for a, n in c.most_common(8))
    tail = " ".join(acts[-limit:])
    return f"{len(acts)} actions ({head}); the last {min(limit, len(acts))}: {tail}"


def rate_episode(chat, frames: list[tuple[int, np.ndarray]], recs: list[dict[str, Any]], goal: str = "", task: str = "", outcome: str = "") -> dict[str, Any]:
    """Returns {completion, directedness, note, cost_usd}; completion and directedness are None when the rater fails."""
    from .author import _b64
    picked = sample_frames(frames)
    text = (f"Game: {goal[:300] or 'unknown'}. " + (f"Task given to the player: {task}. " if task else "") + (f"How the episode ended: {outcome}. " if outcome else "") +
            f"{len(recs)} ticks. Actions: {actions_summary(recs)}.\nFrames follow, tick numbers first.")
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for tick, fr in picked:
        parts.append({"type": "text", "text": f"tick {tick}:"})
        parts.append({"type": "image_url", "image_url": {"url": _b64(fr)}})
    try:
        before = getattr(chat, "cost", 0.0)
        # a reasoning model spends tokens before it answers: a small budget returns nothing at all
        reply = chat.complete([{"role": "system", "content": RUBRIC}, {"role": "user", "content": parts}], max_tokens=2500, temperature=0.0)[0]
        m = re.search(r"\{.*\}", reply, re.S)
        j = json.loads(m.group(0)) if m else {}
        cost = round(float(getattr(chat, "cost", 0.0) - before), 6)
        if not m:
            return {"completion": None, "directedness": None, "note": f"rater answered without a JSON object: {reply[:80]!r}", "cost_usd": cost}
    except Exception as e:  # noqa: BLE001
        return {"completion": None, "directedness": None, "note": f"rater failed: {str(e)[:80]}", "cost_usd": 0.0}
    def clamp(v):
        try:
            return max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            return None
    return {"completion": clamp(j.get("completion")), "directedness": clamp(j.get("directedness")), "note": str(j.get("note", ""))[:160], "cost_usd": cost}


def calibrate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """How well the rater's order agrees with the trial order the loop trusts (won > tasks > not lost > longer > score),
    over every pair of rated episodes where that order is strict. Agreement near 1 means the rater can stand in for
    the score where there is none; near 0.5 means it is noise. The episodes' own `score` is left out of the order so
    a rating used as the score cannot vouch for itself."""
    from .learn import _key
    rated = [e for e in episodes if isinstance(e.get("rating"), dict) and e["rating"].get("completion") is not None]
    pairs = agree = 0
    for i in range(len(rated)):
        for j in range(i + 1, len(rated)):
            a, b = rated[i], rated[j]
            ka, kb = _key({**a, "score": None}), _key({**b, "score": None})
            if ka == kb:
                continue
            ra, rb = a["rating"]["completion"], b["rating"]["completion"]
            if ra == rb:
                continue
            pairs += 1
            agree += 1 if ((ka > kb) == (ra > rb)) else 0
    return {"rated": len(rated), "pairs": pairs, "agreement": round(agree / pairs, 3) if pairs else None}
