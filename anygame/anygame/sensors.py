"""Sensors answer the pack's typed questions from the compiled state. Jev is the point; the others exist so
the same packs measure judgment per dollar across models (`anygame bench`) and so the mechanics run without
a key (`random`).

  jev            TypeSafe Jev (anygame.jev.Jev)
  random         uniform choices, nouls at 0.5: the floor every model must beat
  llm:<model>    any OpenAI-compatible chat model answering in JSON (through OpenRouter by default)
"""
from __future__ import annotations
import json
import os
import random
import re
import time
from typing import Any


def open_sensor(spec: str | None, timeout: float | None = None):
    if spec in (None, "none"):
        return None
    if spec == "jev":
        from .jev import Jev
        return Jev(timeout=timeout)
    if spec == "clm" or spec.startswith("clm:"):
        # CLM (Stanford / NVIDIA's contrastive System One model): the same /v1/systemone protocol, ~10x faster. Served
        # locally by `clm-serve` (port 8700) or by any TypeSafe-compatible host: CLM_BASE_URL, CLM_MODEL, CLM_API_KEY.
        from .jev import Jev
        base = spec[4:] if spec.startswith("clm:") else os.environ.get("CLM_BASE_URL", "http://127.0.0.1:8700")
        return Jev(api_key=os.environ.get("CLM_API_KEY", "local"), base_url=base, model=os.environ.get("CLM_MODEL", "clm-latest"), timeout=timeout)
    if spec == "random" or spec.startswith("random:"):
        return RandomSensor(int(spec.split(":", 1)[1]) if ":" in spec else 0)
    if spec.startswith("llm:"):
        # a chat model answers in seconds, not milliseconds: the pack's Jev timeout would only make it fall back to rules
        return LLMSensor(spec[4:], timeout=max(float(timeout or 0), float(os.environ.get("ANYGAME_LLM_TIMEOUT", "60"))))
    raise SystemExit(f"unknown sensor '{spec}': jev | clm[:<base url>] | none | random | llm:<model>")


class RandomSensor:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.model = "random"

    def ask(self, state, questions: dict) -> dict:
        answers = {}
        for k, q in questions.items():
            if q["type"] == "noul":
                answers[k] = {"type": "noul", "noul": 0.5}
            elif q["type"] == "choice":
                crit = list(q["criteria"])
                pick = self.rng.choice(crit)
                answers[k] = {"type": "choice", "choice": pick, "probabilities": {c: 1.0 / len(crit) for c in crit}, "confidence": 0.0}
            else:
                answers[k] = {"type": "score", "score": 0}
        return {"answers": answers, "latency_ms": 0, "input_tokens": 0, "cost_usd": 0.0, "model": "random"}


PROMPT = """You are playing a game from its compiled screen state. Answer every question.
Reply with ONE JSON object: {"<question id>": <answer>, ...} where a noul answer is a probability 0..1 that the
statement is true, a choice answer is exactly one of the criteria keys, and a score answer is an integer.
No prose, no markdown, just the JSON object.

STATE:
%s

QUESTIONS:
%s
"""


class LLMSensor:
    """Any chat model as a sensor. Same questions, JSON answers, probabilities = 1.0 on the chosen option.
    Routed by ANYGAME_LLM_* (Azure or any OpenAI-compatible endpoint); Jev is never routed here."""

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None, timeout: float | None = None):
        from .chat import Chat
        self.chat = Chat(model=model, api_key=api_key, base_url=base_url, timeout=timeout or 30.0)
        self.model = self.chat.model

    def ask(self, state, questions: dict) -> dict:
        qtext = []
        for k, q in questions.items():
            if q["type"] == "choice":
                qtext.append(f"- {k} (choice, one of {list(q['criteria'])}): {q['instructions']}")
            elif q["type"] == "noul":
                qtext.append(f"- {k} (probability true): {q['instructions']}")
            else:
                qtext.append(f"- {k} (integer score): {q['instructions']}")
        before = self.chat.cost
        text, usage, ms = self.chat.complete([{"role": "user", "content": PROMPT % (json.dumps(state, default=str), "\n".join(qtext))}], max_tokens=400, temperature=0)
        m = re.search(r"\{.*\}", text, re.S)
        try:
            raw = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            raw = {}
        answers: dict[str, Any] = {}
        for k, q in questions.items():
            v = raw.get(k)
            if q["type"] == "noul":
                try:
                    p = float(v)
                except (TypeError, ValueError):
                    p = 0.5
                answers[k] = {"type": "noul", "noul": max(0.0, min(1.0, p))}
            elif q["type"] == "choice":
                crit = list(q["criteria"])
                pick = str(v) if str(v) in crit else crit[0]
                answers[k] = {"type": "choice", "choice": pick, "probabilities": {c: (1.0 if c == pick else 0.0) for c in crit}, "confidence": 1.0 if str(v) in crit else 0.0}
            else:
                try:
                    answers[k] = {"type": "score", "score": int(v)}
                except (TypeError, ValueError):
                    answers[k] = {"type": "score", "score": 0}
        return {"answers": answers, "latency_ms": ms, "input_tokens": usage.get("prompt_tokens", 0),
                "cost_usd": self.chat.cost - before, "model": self.model}
