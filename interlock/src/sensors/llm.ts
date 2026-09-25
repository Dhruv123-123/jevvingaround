import type { Answer, WireQuestion } from "../core/types.js";
import type { Sensor, SensorResult } from "./types.js";

/**
 * Any OpenAI-compatible chat endpoint (OpenAI, OpenRouter, Ollama, a gateway) answering the same typed questions
 * through JSON output. It exists so the "why a System One model" claim is measured, not asserted: same packs,
 * same tests, `interlock eval --sensor llm` vs `--sensor jev`.
 *
 * Caveat, on purpose: an LLM's "probability" is a number it wrote, not a calibrated distribution. The calibration
 * table will show what that is worth.
 */
export interface LlmSensorOptions { apiKey: string; baseUrl: string; model: string; timeoutMs?: number; fetchImpl?: typeof fetch }

export function llmSensor(opts: LlmSensorOptions): Sensor {
  const fetchImpl = opts.fetchImpl ?? ((i, init) => globalThis.fetch(i, init));
  const timeoutMs = opts.timeoutMs ?? 30_000;
  return {
    name: `llm:${opts.model}`,
    async evaluate(state: unknown, questions: Record<string, WireQuestion>, signal?: AbortSignal): Promise<SensorResult> {
      const schema = { type: "object", additionalProperties: false, required: Object.keys(questions), properties: {} as Record<string, unknown> };
      const lines: string[] = [];
      for (const [id, q] of Object.entries(questions)) {
        if (q.type === "noul") {
          schema.properties[id] = { type: "number", minimum: 0, maximum: 1 };
          const c = q.criteria as Record<string, string | null>;
          lines.push(`- ${id} (probability 0..1 that this is TRUE): ${q.instructions}\n    true: ${c.true ?? ""}\n    false: ${c.false ?? ""}`);
        } else if (q.type === "choice") {
          const opts_ = Object.keys(q.criteria as object);
          schema.properties[id] = { type: "string", enum: opts_ };
          lines.push(`- ${id} (pick one of ${opts_.map((o) => JSON.stringify(o)).join(", ")}): ${q.instructions}`);
        } else {
          const levels = q.criteria as string[];
          schema.properties[id] = { type: "integer", minimum: 0, maximum: levels.length - 1 };
          lines.push(`- ${id} (integer level 0..${levels.length - 1}): ${q.instructions}\n    levels: ${levels.map((l, i) => `${i}=${l}`).join("; ")}`);
        }
      }
      const body = {
        model: opts.model,
        temperature: 0,
        response_format: { type: "json_schema", json_schema: { name: "answers", strict: true, schema } },
        messages: [
          { role: "system", content: "You evaluate a STATE against independent typed questions. Answer every question on its own. Output only the JSON object described; no prose." },
          { role: "user", content: `STATE:\n${JSON.stringify(state)}\n\nQUESTIONS:\n${lines.join("\n")}` },
        ],
      };
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), timeoutMs);
      signal?.addEventListener("abort", () => ctl.abort(), { once: true });
      const t0 = performance.now();
      let res: Response;
      try {
        res = await fetchImpl(opts.baseUrl.replace(/\/+$/, "") + "/chat/completions", { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${opts.apiKey}` }, body: JSON.stringify(body), signal: ctl.signal });
      } finally { clearTimeout(timer); }
      if (!res.ok) throw new Error(`llm ${res.status}: ${(await res.text().catch(() => "")).slice(0, 200)}`);
      const json = (await res.json()) as { choices?: Array<{ message?: { content?: string } }>; usage?: { prompt_tokens?: number; cost?: number } };
      const text = json.choices?.[0]?.message?.content ?? "{}";
      let parsed: Record<string, unknown>;
      try { parsed = JSON.parse(text.replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { throw new Error(`llm returned non-JSON: ${text.slice(0, 120)}`); }
      const answers: Record<string, Answer> = {};
      for (const [id, q] of Object.entries(questions)) {
        const v = parsed[id];
        if (q.type === "noul") answers[id] = { type: "noul", noul: clamp(Number(v)) };
        else if (q.type === "choice") {
          const opts_ = Object.keys(q.criteria as object);
          const pick = opts_.includes(String(v)) ? String(v) : opts_[0]!;
          answers[id] = { type: "choice", choice: pick, probabilities: Object.fromEntries(opts_.map((o) => [o, o === pick ? 1 : 0])), confidence: 0.5 };
        } else {
          const levels = q.criteria as string[];
          const i = Math.max(0, Math.min(levels.length - 1, Math.round(Number(v)) || 0));
          answers[id] = { type: "score", score: i, legend: Object.fromEntries(levels.map((l, k) => [String(k), l])), probabilities: {}, confidence: 0.5 };
        }
      }
      // OpenRouter reports usage.cost; a bare OpenAI endpoint does not, and we do not guess a price list
      return { answers, latencyMs: Math.round(performance.now() - t0), inputTokens: json.usage?.prompt_tokens ?? 0, costUsd: typeof json.usage?.cost === "number" ? json.usage.cost : undefined, model: opts.model };
    },
  };
}

const clamp = (n: number) => (Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0);
