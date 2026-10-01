// One chat-completion client for every model that is not Jev: the authoring model and llm: sensors.
// Azure OpenAI / Foundry v1 endpoints (paste the portal URL), classic Azure deployments, or any OpenAI-compatible server.
// There is no default endpoint or model, and Claude Sonnet through OpenRouter is refused.
import type { Keys } from "./sensors.js";

export const NOT_CONFIGURED = "no chat model configured: set the chat model endpoint, key and model in \"keys and models\"";

export function forbidden(base: string, model: string): boolean {
  return base.toLowerCase().includes("openrouter") && model.toLowerCase().includes("sonnet");
}

export class Chat {
  base: string;
  api: "azure" | "azure-models" | "openai";
  model: string;
  key: string;
  version: string;
  cost = 0;

  constructor(keys: Keys, private timeoutMs = 240000) {
    if (!keys.llmBase) throw new Error(NOT_CONFIGURED);
    let base = keys.llmBase.replace(/\/$/, "");
    if (base.endsWith("/responses") || base.endsWith("/chat/completions")) base = base.slice(0, base.lastIndexOf("/"));
    this.base = base;
    this.api = keys.llmApi ?? (base.endsWith("/openai/v1") || base.includes(".openai.azure.com") ? "azure" : base.includes(".services.ai.azure.com") ? "azure-models" : "openai");
    this.model = keys.llmModel ?? "";
    if (!this.model) throw new Error("set the authoring model (on Azure: the deployment name)");
    if (forbidden(base, this.model)) throw new Error(`refusing ${this.model} through OpenRouter: Claude Sonnet on OpenRouter is not used`);
    this.key = keys.llmKey ?? (base.includes("openrouter") ? keys.openrouter ?? "" : "");
    if (!this.key) throw new Error(`no key for ${this.base}`);
    this.version = keys.llmApiVersion ?? "2024-10-21";
  }

  url(): string {
    if (this.api === "azure") return this.base.endsWith("/openai/v1") ? `${this.base}/chat/completions` : `${this.base}/openai/deployments/${this.model}/chat/completions?api-version=${this.version}`;
    if (this.api === "azure-models") return `${this.base}/models/chat/completions?api-version=${this.version === "2024-10-21" ? "2024-05-01-preview" : this.version}`;
    return `${this.base}/chat/completions`;
  }

  headers(): Record<string, string> {
    return this.api.startsWith("azure") ? { "api-key": this.key, "content-type": "application/json" } : { authorization: `Bearer ${this.key}`, "content-type": "application/json" };
  }

  async complete(messages: any[], maxTokens = 1000, temperature = 0): Promise<{ text: string; usage: any; ms: number }> {
    const body: any = { messages, model: this.model };
    const strict = this.api.startsWith("azure") || /^(gpt-5|o1|o3|o4)/.test(this.model.split("/").pop() ?? "");
    if (strict) body.max_completion_tokens = maxTokens; else { body.max_tokens = maxTokens; body.temperature = temperature; }
    if (this.base.includes("openrouter")) body.usage = { include: true };
    const t0 = performance.now();
    let r: Response | null = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
      try {
        r = await fetch(this.url(), { method: "POST", headers: this.headers(), body: JSON.stringify(body), signal: ctrl.signal });
      } catch (e) {
        clearTimeout(timer);
        if (attempt < 3) { await new Promise((res) => setTimeout(res, 3000 * (attempt + 1))); continue; }
        throw new Error(`${this.base}: ${(e as Error).message}`);
      }
      clearTimeout(timer);
      if ((r.status === 429 || r.status >= 500) && attempt < 3) { await new Promise((res) => setTimeout(res, (r!.status === 429 ? 8000 : 4000) * (attempt + 1))); continue; }   // rate limit or a gateway blip: the run is worth more than a retry
      if (r.status === 402) throw new Error(`${this.base} refused the call (402): add credits or point the model settings at another endpoint`);
      if (r.status !== 200) throw new Error(`${this.api} ${r.status}: ${(await r.text()).slice(0, 300)}`);
      break;
    }
    const j = await r!.json();
    if (j.error && !j.choices) throw new Error(`model error: ${JSON.stringify(j.error).slice(0, 200)}`);
    const text: string = j.choices?.[0]?.message?.content ?? "";
    const usage = j.usage ?? {};
    this.cost += Number(usage.cost ?? 0);
    return { text, usage, ms: Math.round(performance.now() - t0) };
  }
}
