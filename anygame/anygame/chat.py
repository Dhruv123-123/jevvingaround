"""One chat-completion client for every model that is not Jev: the authoring model and the `llm:` sensor.

Jev always goes to OpenRouter (or JEV_BASE_URL). Everything else goes wherever ANYGAME_LLM_BASE points:

  OpenRouter / any OpenAI-compatible server (default base; ANYGAME_LLM_MODEL is required, there is no default model):
    ANYGAME_LLM_BASE=https://openrouter.ai/api/v1   ANYGAME_LLM_KEY=…   (falls back to OPENROUTER_API_KEY)
  Azure OpenAI (model = your deployment name):
    ANYGAME_LLM_API=azure  ANYGAME_LLM_BASE=https://<resource>.openai.azure.com  ANYGAME_LLM_KEY=<api key>
    ANYGAME_LLM_API_VERSION=2024-10-21 (optional)
  Azure AI Foundry "models" endpoint (serverless, model = the model name):
    ANYGAME_LLM_API=azure-models  ANYGAME_LLM_BASE=https://<resource>.services.ai.azure.com  ANYGAME_LLM_KEY=…
"""
from __future__ import annotations
import os
import time
from typing import Any

import requests


class Chat:
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None, api: str | None = None, timeout: float = 240):
        self.base = (base_url or os.environ.get("ANYGAME_LLM_BASE") or "https://openrouter.ai/api/v1").rstrip("/")
        if self.base.endswith("/responses") or self.base.endswith("/chat/completions"):
            self.base = self.base.rsplit("/", 1)[0]          # accept the full URL from the Azure portal
        self.api = (api or os.environ.get("ANYGAME_LLM_API") or
                    ("azure" if (self.base.endswith("/openai/v1") or ".openai.azure.com" in self.base) else "azure-models" if ".services.ai.azure.com" in self.base else "openai")).lower()
        self.model = model or os.environ.get("ANYGAME_LLM_MODEL")      # no default: the chat model is always chosen explicitly
        if not self.model:
            raise SystemExit("set ANYGAME_LLM_MODEL (on Azure: the deployment name) or pass --model; there is no default chat model")
        if "openrouter" in self.base and not os.environ.get("ANYGAME_ALLOW_OPENROUTER_CHAT"):
            raise SystemExit("OpenRouter is for Jev only: point ANYGAME_LLM_BASE at another endpoint (e.g. Azure) for the chat model")
        self.key = api_key or os.environ.get("ANYGAME_LLM_KEY") or os.environ.get("AZURE_OPENAI_API_KEY") or (os.environ.get("OPENROUTER_API_KEY") if "openrouter" in self.base else None)
        if not self.key:
            raise SystemExit(f"no key for {self.base}: set ANYGAME_LLM_KEY")
        self.version = os.environ.get("ANYGAME_LLM_API_VERSION", "2024-10-21")
        self.timeout = timeout
        self.s = requests.Session()
        self.cost = 0.0

    def url(self) -> str:
        if self.api == "azure":
            if self.base.endswith("/openai/v1"):
                return f"{self.base}/chat/completions"
            return f"{self.base}/openai/deployments/{self.model}/chat/completions?api-version={self.version}"
        if self.api == "azure-models":
            return f"{self.base}/models/chat/completions?api-version={os.environ.get('ANYGAME_LLM_API_VERSION', '2024-05-01-preview')}"
        return f"{self.base}/chat/completions"

    def headers(self) -> dict[str, str]:
        if self.api.startswith("azure"):
            return {"api-key": self.key, "content-type": "application/json"}
        return {"authorization": f"Bearer {self.key}", "content-type": "application/json"}

    def complete(self, messages: list[dict[str, Any]], max_tokens: int = 1000, temperature: float = 0.0) -> tuple[str, dict[str, Any], int]:
        """Returns (text, usage, latency_ms). Adds to self.cost when the server reports a cost (OpenRouter does)."""
        body: dict[str, Any] = {"messages": messages, "model": self.model}
        # newer OpenAI-family models take max_completion_tokens and only the default temperature
        strict = self.api.startswith("azure") or self.model.split("/")[-1].startswith(("gpt-5", "o1", "o3", "o4"))
        if strict:
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
        if "openrouter" in self.base:
            body["usage"] = {"include": True}
        t0 = time.perf_counter()
        for attempt in range(4):
            try:
                r = self.s.post(self.url(), json=body, headers=self.headers(), timeout=self.timeout)
            except requests.exceptions.RequestException as e:      # a dropped connection or proxy blip is not a reason to lose the run
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(f"{self.base}: {type(e).__name__}: {str(e)[:160]}") from e
            if (r.status_code == 429 or r.status_code >= 500) and attempt < 3:      # rate limit or a gateway blip: retry, the run is worth more
                time.sleep((8 if r.status_code == 429 else 4) * (attempt + 1))
                continue
            if r.status_code == 402:
                msg = (r.json().get("error") or {}).get("message", "")
                raise SystemExit(f"{self.base} refused the call (402): {msg}\nAdd credits, or point ANYGAME_LLM_BASE at another endpoint (see anygame/chat.py).")
            if r.status_code != 200:
                raise RuntimeError(f"{self.api} {r.status_code}: {r.text[:300]}")
            break
        j = r.json()
        if "error" in j and not j.get("choices"):
            raise RuntimeError(f"model error: {j['error']}")
        text = j["choices"][0]["message"].get("content") or ""
        usage = j.get("usage") or {}
        self.cost += float(usage.get("cost") or 0.0)
        return text, usage, int((time.perf_counter() - t0) * 1000)
