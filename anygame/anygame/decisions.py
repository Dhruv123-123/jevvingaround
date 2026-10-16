"""OpenAI's Decisions API as the sensor: the same typed questions Jev answers (noul / choice / score), one call per
state, typed answers back. Drop-in for anygame.jev.Jev: `ask(state, questions)` takes and returns Jev's wire shape.

  POST {OPENAI_BASE_URL}/v1/decisions  {model, input, questions: [{type, name, instructions, choices|levels}]}
  → {answers: [{type, name, probability | choice, probabilities, confidence | score, probabilities} | {type: refusal, name}], usage}

Jev's `noul` is a Decisions `predicate`; a choice's criteria dict becomes `choices`; a score's criteria list becomes
`levels`. Keys: OPENAI_API_KEY (or ANYGAME_DECISIONS_KEY); model ANYGAME_DECISIONS_MODEL (default gpt-6-luna).
"""
from __future__ import annotations
import json
import os
import time

import requests

USD_PER_INPUT_TOKEN = 0.10 / 1e6   # Decisions bills input tokens only


def to_wire(questions: dict[str, dict]) -> list[dict]:
    """Jev questions (dict keyed by id) → Decisions questions (list with names)."""
    out = []
    for name, q in questions.items():
        t = q["type"]
        crit = q.get("criteria")
        instr = q.get("instructions") or name
        if t == "noul":
            if isinstance(crit, dict) and (crit.get("true") or crit.get(True)):
                # Jev's noul criteria say what true and false mean; Decisions has only the instructions
                yes, no = crit.get("true") or crit.get(True), crit.get("false") or crit.get(False)
                instr = f"{instr}\nTrue means: {yes}" + (f"\nFalse means: {no}" if no else "")
            out.append({"type": "predicate", "name": name, "instructions": instr})
        elif t == "choice":
            items = crit.items() if isinstance(crit, dict) else ((c, None) for c in crit)
            choices = []
            for v, d in items:
                c = {"value": str(v)}
                if d:
                    c["description"] = d if isinstance(d, str) else json.dumps(d, default=str)
                choices.append(c)
            out.append({"type": "choice", "name": name, "instructions": instr, "choices": choices})
        elif t == "score":
            levels = crit.items() if isinstance(crit, dict) else ((str(c), None) for c in crit)
            out.append({"type": "score", "name": name, "instructions": instr,
                        "levels": [{"label": str(l), **({"description": str(d)} if d else {})} for l, d in levels]})
        else:
            raise ValueError(f"question {name}: unknown type {t}")
    return out


def from_wire(answers: list[dict], questions: dict[str, dict]) -> dict[str, dict]:
    """Decisions answers → Jev answers keyed by question id."""
    by = {a["name"]: a for a in answers}
    out: dict[str, dict] = {}
    for name, q in questions.items():
        a = by.get(name)
        if a is None or a.get("type") == "refusal":
            # Decisions may refuse a question (e.g. no offered option fits); Jev never does. A refused noul is a
            # coin flip; a refused choice or score is left out, so the loop treats it like an unanswered question
            if a is not None and q["type"] == "noul":
                out[name] = {"type": "noul", "noul": 0.5, "refused": True}
            continue
        if q["type"] == "noul":
            out[name] = {"type": "noul", "noul": float(a["probability"])}
        elif q["type"] == "choice":
            out[name] = {"type": "choice", "choice": a["choice"],
                         "probabilities": {p["value"]: p["probability"] for p in a.get("probabilities", [])},
                         "confidence": a.get("confidence", 0.0)}
        else:
            out[name] = {"type": "score", "score": a["score"],
                         "probabilities": {p.get("label", p["value"]): p["probability"] for p in a.get("probabilities", [])},
                         "confidence": a.get("confidence", 0.0)}
    return out


class Decisions:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None, timeout: float | None = None):
        key = api_key or os.environ.get("ANYGAME_DECISIONS_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("set OPENAI_API_KEY for the decisions sensor")
        base = base_url or os.environ.get("ANYGAME_DECISIONS_BASE") or "https://api.openai.com"
        self.key, self.base = key, base.rstrip("/").removesuffix("/v1")
        self.model = model or os.environ.get("ANYGAME_DECISIONS_MODEL", "gpt-6-luna")
        self.timeout = timeout if timeout is not None else float(os.environ.get("ANYGAME_JEV_TIMEOUT", "4"))
        self.s = requests.Session()

    def ask(self, state, questions: dict) -> dict:
        # a choice with one option has its answer already (Decisions wants two or more); it is never sent
        fixed = {k: q for k, q in questions.items() if q["type"] == "choice" and len(q.get("criteria") or ()) < 2}
        answers = {k: {"type": "choice", "choice": str(next(iter(q["criteria"]))), "probabilities": {str(next(iter(q["criteria"]))): 1.0},
                       "confidence": 1.0} for k, q in fixed.items() if q.get("criteria")}
        asked = {k: q for k, q in questions.items() if k not in fixed}
        if not asked:
            return {"answers": answers, "latency_ms": 0, "server_ms": None, "input_tokens": 0, "cost_usd": 0.0, "model": self.model}
        body = {"model": self.model, "input": state if isinstance(state, str) else json.dumps(state, default=str),
                "questions": to_wire(asked)}
        t0 = time.perf_counter()
        for attempt in range(2):
            r = self.s.post(self.base + "/v1/decisions", json=body, headers={"authorization": f"Bearer {self.key}"}, timeout=self.timeout)
            if r.status_code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(0.15)
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"decisions {r.status_code}: {r.text[:200]}")
        j = r.json()
        tokens = j.get("usage", {}).get("input_tokens", 0)
        return {
            "answers": {**answers, **from_wire(j["answers"], asked)},
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "server_ms": float(r.headers["openai-processing-ms"]) if "openai-processing-ms" in r.headers else None,
            "input_tokens": tokens,
            "cost_usd": tokens * USD_PER_INPUT_TOKEN,
            "model": j.get("model", self.model),
        }


def default_sensor() -> str:
    """`ANYGAME_SENSOR` if set, else Jev. OpenAI Decisions only when asked for (ANYGAME_SENSOR=openai or --sensor openai),
    even with an OpenAI key in the environment (Dhruv, Oct 16: bring Jev back)."""
    return os.environ.get("ANYGAME_SENSOR") or "jev"

