import type { EvalResult, JevResponse, QuestionDef, WireQuestion } from "./types.js";

export interface JevClientOptions {
  apiKey: string;
  baseUrl: string;
  model: string;
  fetchImpl?: typeof fetch;
  /** One short retry on 429/529. Interactive callers should keep this tiny. */
  retryDelayMs?: number;
  timeoutMs?: number;
}

export class JevError extends Error {
  constructor(message: string, public status: number, public body?: string) {
    super(message);
  }
}

/** Strip policy metadata; the API only wants {type, instructions, criteria}. */
export function toWire(defs: QuestionDef[]): Record<string, WireQuestion> {
  const out: Record<string, WireQuestion> = {};
  for (const q of defs) out[q.id] = { type: q.type, instructions: q.instructions, criteria: q.criteria };
  return out;
}

export class JevClient {
  private opts: Required<JevClientOptions>;
  constructor(opts: JevClientOptions) {
    this.opts = {
      // wrapped, not referenced: calling fetch as a method of `opts` throws "Illegal invocation"
      fetchImpl: (input, init) => globalThis.fetch(input, init),
      retryDelayMs: 150,
      timeoutMs: 2500,
      ...opts,
    };
  }

  async evaluate(state: unknown, questions: Record<string, WireQuestion>, signal?: AbortSignal): Promise<EvalResult> {
    const url = this.opts.baseUrl.replace(/\/+$/, "") + "/v1/systemone";
    const body = JSON.stringify({ model: this.opts.model, state, questions });
    const t0 = performance.now();
    let attempt = 0;
    for (;;) {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), this.opts.timeoutMs);
      signal?.addEventListener("abort", () => ctl.abort(), { once: true });
      let res: Response;
      try {
        res = await this.opts.fetchImpl(url, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${this.opts.apiKey}` },
          body,
          signal: ctl.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      if ((res.status === 429 || res.status === 529) && attempt === 0) {
        attempt++;
        await new Promise((r) => setTimeout(r, this.opts.retryDelayMs));
        continue;
      }
      if (!res.ok) throw new JevError(`jev ${res.status}`, res.status, await res.text().catch(() => ""));
      const json = (await res.json()) as JevResponse;
      return {
        answers: json.answers,
        latencyMs: Math.round(performance.now() - t0),
        inputTokens: json.usage?.input_tokens ?? 0,
        model: json.model,
      };
    }
  }
}
