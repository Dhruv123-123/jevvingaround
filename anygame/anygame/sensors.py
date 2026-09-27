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
    if spec == "random" or spec.startswith("random:"):
        return RandomSensor(int(spec.split(":", 1)[1]) if ":" in spec else 0)
    if spec.startswith("llm:"):
        return LLMSensor(spec[4:], timeout=timeout)
    raise SystemExit(f"unknown sensor '{spec}': jev | none | random | llm:<model>")


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
    """Any chat model as a sensor. Same questions, JSON answers, probabilities = 1.0 on the chosen option."""

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None, timeout: float | None = None):
        import requests
        self.model = model
        self.key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise SystemExit("llm sensor needs OPENROUTER_API_KEY (or OPENAI_API_KEY with ANYGAME_LLM_BASE)")
        self.base = (base_url or os.environ.get("ANYGAME_LLM_BASE", "https://openrouter.ai/api/v1")).rstrip("/")
        self.timeout = timeout or 30.0
        self.s = requests.Session()

    def ask(self, state, questions: dict) -> dict:
        qtext = []
        for k, q in questions.items():
            if q["type"] == "choice":
                qtext.append(f"- {k} (choice, one of {list(q['criteria'])}): {q['instructions']}")
            elif q["type"] == "noul":
                qtext.append(f"- {k} (probability true): {q['instructions']}")
            else:
                qtext.append(f"- {k} (integer score): {q['instructions']}")
        body = {"model": self.model, "messages": [{"role": "user", "content": PROMPT % (json.dumps(state, default=str), "\n".join(qtext))}],
                "max_tokens": 400, "temperature": 0, "usage": {"include": True}}
        t0 = time.perf_counter()
        r = self.s.post(self.base + "/chat/completions", json=body, headers={"authorization": f"Bearer {self.key}"}, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"llm {r.status_code}: {r.text[:200]}")
        j = r.json()
        text = j["choices"][0]["message"]["content"] or ""
        m = re.search(r"\{.*\}", text, re.S)
        raw = json.loads(m.group(0)) if m else {}
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
        usage = j.get("usage") or {}
        return {"answers": answers, "latency_ms": int((time.perf_counter() - t0) * 1000), "input_tokens": usage.get("prompt_tokens", 0),
                "cost_usd": float(usage.get("cost") or 0.0), "model": self.model}
