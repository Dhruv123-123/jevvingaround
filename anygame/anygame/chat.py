"""One chat-completion client for every model that is not Jev: the authoring model and the `llm:` sensor.

Jev always goes to OpenRouter (or JEV_BASE_URL). Everything else goes wherever ANYGAME_LLM_BASE points. There is
no default: with nothing set, Chat() stops and names the variables, it never picks a model on its own.
OpenRouter is for Jev only: a chat model pointed at OpenRouter is refused, whatever the model.

  Any other OpenAI-compatible server:
    ANYGAME_LLM_BASE=https://…/v1   ANYGAME_LLM_KEY=…   ANYGAME_LLM_MODEL=…
  Azure OpenAI (model = your deployment name):
    ANYGAME_LLM_API=azure  ANYGAME_LLM_BASE=https://<resource>.openai.azure.com  ANYGAME_LLM_KEY=<api key>
    ANYGAME_LLM_API_VERSION=2024-10-21 (optional)
  Azure AI Foundry "models" endpoint (serverless, model = the model name):
    ANYGAME_LLM_API=azure-models  ANYGAME_LLM_BASE=https://<resource>.services.ai.azure.com  ANYGAME_LLM_KEY=…
"""
from __future__ import annotations
import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


NOT_CONFIGURED = ("no chat model configured: set ANYGAME_LLM_BASE, ANYGAME_LLM_KEY and ANYGAME_LLM_MODEL "
                  "(and ANYGAME_LLM_API for Azure; see anygame/chat.py), or pass --model with a base and key")


# Dollars per million tokens (input, output). Azure does not return a price, so every call is priced here and
# written to the usage ledger. gpt-5.6-luna: Azure list rate as of 2026-10 ($0.22 in, $1.32 out; Global Standard
# tracks OpenAI's $0.20/$1.20). Override with ANYGAME_LLM_PRICE_IN / ANYGAME_LLM_PRICE_OUT.
PRICES = {"gpt-5.6-luna": (0.22, 1.32)}
# which part of anygame made the call, from the calling module
PURPOSES = {"author": "authoring", "explore": "authoring", "learn": "learn loop", "diagnose": "learn loop", "goals": "goals",
            "tiletext": "tiletext", "fallback": "vision", "sensors": "llm sensor", "rater": "rater", "tasks": "tasks",
            "demo": "demo", "cellbook": "screen-only perception", "screenonly_run": "screen-only perception"}
_LEDGER_LOCK = threading.Lock()


def ledger_path() -> Path | None:
    """Where every chat call is appended: ANYGAME_USAGE_LOG, else the project's shared folder when it exists, else
    ~/.anygame/usage.jsonl. ANYGAME_USAGE_LOG=off turns it off."""
    p = os.environ.get("ANYGAME_USAGE_LOG")
    if p:
        return None if p.lower() in ("off", "0", "none") else Path(p)
    if "PYTEST_CURRENT_TEST" in os.environ:      # tests never write the real ledger
        return None
    shared = Path("/mnt/project-files/anygame")
    return shared / "azure-usage.jsonl" if shared.is_dir() else Path.home() / ".anygame" / "usage.jsonl"


def price(model: str, usage: dict[str, Any]) -> float:
    """Dollars for one call from its token counts (cached input at a tenth of the input rate)."""
    pin, pout = PRICES.get(model.split("/")[-1], (None, None))
    pin = float(os.environ.get("ANYGAME_LLM_PRICE_IN") or pin or 0.0)
    pout = float(os.environ.get("ANYGAME_LLM_PRICE_OUT") or pout or 0.0)
    prompt = int(usage.get("prompt_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    out = int(usage.get("completion_tokens") or 0)
    return ((prompt - cached) * pin + cached * pin / 10 + out * pout) / 1e6


def purpose() -> str:
    for f in inspect.stack()[2:12]:
        mod = Path(f.filename).stem
        if mod in PURPOSES:
            return PURPOSES[mod]
    return "other"


def summarize(path: Path | None = None, since: str | None = None) -> dict[str, Any]:
    """Calls, tokens and dollars in the ledger, in all and per purpose (and from `since`, an ISO time, if given)."""
    path = path or ledger_path()
    out: dict[str, Any] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0, "by_purpose": {}}
    if not path or not path.exists():
        return out
    for line in path.read_text(errors="ignore").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if since and e.get("at", "") < since:
            continue
        for t in (out, out["by_purpose"].setdefault(e.get("purpose", "other"), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0})):
            t["calls"] += 1
            t["prompt_tokens"] += e.get("prompt_tokens", 0)
            t["completion_tokens"] += e.get("completion_tokens", 0)
            t["usd"] = round(t["usd"] + e.get("usd", 0.0), 6)
    return out


def forbidden(base: str) -> bool:
    """OpenRouter is for Jev only, by the project's rule: no chat model goes through it."""
    return "openrouter" in base.lower()


class Chat:
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None, api: str | None = None, timeout: float = 240):
        base = base_url or os.environ.get("ANYGAME_LLM_BASE")
        if not base:
            raise SystemExit(NOT_CONFIGURED)
        self.base = base.rstrip("/")
        if self.base.endswith("/responses") or self.base.endswith("/chat/completions"):
            self.base = self.base.rsplit("/", 1)[0]          # accept the full URL from the Azure portal
        self.api = (api or os.environ.get("ANYGAME_LLM_API") or
                    ("azure" if (self.base.endswith("/openai/v1") or ".openai.azure.com" in self.base) else "azure-models" if ".services.ai.azure.com" in self.base else "openai")).lower()
        self.model = model or os.environ.get("ANYGAME_LLM_MODEL")
        if not self.model:
            raise SystemExit("set ANYGAME_LLM_MODEL (on Azure: the deployment name) or pass --model")
        if forbidden(self.base):
            raise SystemExit("OpenRouter is for Jev only: point ANYGAME_LLM_BASE at another endpoint (e.g. Azure) for the chat model")
        self.key = api_key or os.environ.get("ANYGAME_LLM_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")
        if not self.key:
            raise SystemExit(f"no key for {self.base}: set ANYGAME_LLM_KEY")
        self.version = os.environ.get("ANYGAME_LLM_API_VERSION", "2024-10-21")
        self.timeout = timeout
        self.s = requests.Session()
        self.cost = 0.0
        self.calls = 0
        self.tokens = {"prompt": 0, "completion": 0}

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

    def complete(self, messages: list[dict[str, Any]], max_tokens: int = 1000, temperature: float = 0.0,
                 extra: dict[str, Any] | None = None) -> tuple[str, dict[str, Any], int]:
        """Returns (text, usage, latency_ms). Every call is priced (the server's cost if it reports one, else PRICES) and
        appended to the usage ledger; self.cost, self.calls and self.tokens are this client's running totals. `extra`
        goes into the request body as is (for example {"reasoning_effort": "low"} on a reasoning model)."""
        body: dict[str, Any] = {"messages": messages, "model": self.model, **(extra or {})}
        # newer OpenAI-family models take max_completion_tokens and only the default temperature
        strict = self.api.startswith("azure") or self.model.split("/")[-1].startswith(("gpt-5", "o1", "o3", "o4"))
        if strict:
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
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
        ms = int((time.perf_counter() - t0) * 1000)
        self.record(usage, ms)
        return text, usage, ms

    def record(self, usage: dict[str, Any], ms: int) -> float:
        """Count one call on this client and append it to the usage ledger with its estimated dollars."""
        usd = float(usage.get("cost") or 0.0) or price(self.model, usage)
        self.cost += usd
        self.calls += 1
        self.tokens["prompt"] += int(usage.get("prompt_tokens") or 0)
        self.tokens["completion"] += int(usage.get("completion_tokens") or 0)
        path = ledger_path()
        if path is None:
            return usd
        entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "api": self.api, "model": self.model,
                 "purpose": purpose(), "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                 "cached_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                 "completion_tokens": int(usage.get("completion_tokens") or 0),
                 "reasoning_tokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                 "usd": round(usd, 7), "ms": ms, "client_usd": round(self.cost, 6), "pid": os.getpid()}
        try:
            with _LEDGER_LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
        except OSError:
            pass                      # a full or read-only disk never stops a run
        return usd
