"""The sensor. Same request shape as interlock/: one state, many typed questions, one call."""
from __future__ import annotations
import os
import time
import requests

USD_PER_INPUT_TOKEN = 0.042 / 1e6


class Jev:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None, timeout: float = 4.0):
        key = api_key or os.environ.get("JEV_API_KEY")
        base = base_url or os.environ.get("JEV_BASE_URL")
        mdl = model or os.environ.get("JEV_MODEL")
        if not key and os.environ.get("OPENROUTER_API_KEY"):
            key = os.environ["OPENROUTER_API_KEY"]
            base = base or "https://openrouter.ai/api"
            mdl = mdl or "typesafe/jev-1.13"
        if not key:
            raise RuntimeError("set OPENROUTER_API_KEY (or JEV_API_KEY)")
        self.key, self.base, self.model, self.timeout = key, (base or "https://api.typesafe.ai").rstrip("/"), mdl or "jev-latest", timeout
        self.s = requests.Session()

    def ask(self, state, questions: dict) -> dict:
        body = {"model": self.model, "state": state, "questions": questions}
        t0 = time.perf_counter()
        for attempt in range(2):
            r = self.s.post(self.base + "/v1/systemone", json=body, headers={"authorization": f"Bearer {self.key}"}, timeout=self.timeout)
            if r.status_code in (429, 529) and attempt == 0:
                time.sleep(0.15)
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"jev {r.status_code}: {r.text[:200]}")
        j = r.json()
        usage = j.get("usage", {})
        return {
            "answers": j["answers"],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "input_tokens": usage.get("input_tokens", 0),
            "cost_usd": usage.get("cost", usage.get("input_tokens", 0) * USD_PER_INPUT_TOKEN),
            "model": j.get("model", self.model),
        }
