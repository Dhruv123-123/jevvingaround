// Sensors answer the pack's typed questions: Jev (TypeSafe, through OpenRouter), random (the floor), or any
// OpenAI-compatible / Azure chat model answering in JSON. Same shapes as the Python runtime.
import type { Answer, Sensor, SensorResult } from "./loop.js";

export interface Keys {
  openrouter?: string;            // Jev
  llmBase?: string;               // everything that is not Jev
  llmKey?: string;
  llmModel?: string;
  llmApi?: "azure" | "azure-models" | "openai";
  llmApiVersion?: string;
}

export class Jev implements Sensor {
  model: string;
  constructor(private key: string, private base = "https://openrouter.ai/api", model = "typesafe/jev-1.13", private timeoutMs = 4000) {
    if (!key) throw new Error("Jev needs an OpenRouter key");
    this.model = model;
  }
  async ask(state: any, questions: Record<string, any>): Promise<SensorResult> {
    const t0 = performance.now();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const r = await fetch(this.base.replace(/\/$/, "") + "/v1/systemone", {
        method: "POST", headers: { authorization: `Bearer ${this.key}`, "content-type": "application/json" },
        body: JSON.stringify({ model: this.model, state, questions }), signal: ctrl.signal,
      });
      if (r.status !== 200) throw new Error(`jev ${r.status}: ${(await r.text()).slice(0, 200)}`);
      const j = await r.json();
      const usage = j.usage ?? {};
      return { answers: j.answers, latency_ms: Math.round(performance.now() - t0), input_tokens: usage.input_tokens ?? 0, cost_usd: usage.cost ?? (usage.input_tokens ?? 0) * 0.042e-6, model: j.model ?? this.model };
    } finally { clearTimeout(timer); }
  }
}

export class RandomSensor implements Sensor {
  model = "random";
  private s: number;
  constructor(seed = 0) { this.s = (seed || 1) >>> 0; }
  private rnd() { this.s = (Math.imul(this.s, 1103515245) + 12345) >>> 0; return (this.s & 0x7fffffff) / 0x7fffffff; }
  async ask(_state: any, questions: Record<string, any>): Promise<SensorResult> {
    const answers: Record<string, Answer> = {};
    for (const [k, q] of Object.entries<any>(questions)) {
      if (q.type === "noul") answers[k] = { type: "noul", noul: 0.5 };
      else if (q.type === "choice") {
        const crit = Object.keys(q.criteria);
        const pick = crit[Math.floor(this.rnd() * crit.length)];
        answers[k] = { type: "choice", choice: pick, probabilities: Object.fromEntries(crit.map((c) => [c, 1 / crit.length])), confidence: 0 };
      } else answers[k] = { type: "score", score: 0 };
    }
    return { answers, latency_ms: 0, input_tokens: 0, cost_usd: 0, model: "random" };
  }
}

const PROMPT = `You are playing a game from its compiled screen state. Answer every question.
Reply with ONE JSON object: {"<question id>": <answer>, ...} where a noul answer is a probability 0..1 that the
statement is true, a choice answer is exactly one of the criteria keys, and a score answer is an integer.
No prose, no markdown, just the JSON object.

STATE:
%s

QUESTIONS:
%s
`;

export class LLMSensor implements Sensor {
  model: string;
  constructor(private chat: import("./chat.js").Chat) { this.model = chat.model; }
  async ask(state: any, questions: Record<string, any>): Promise<SensorResult> {
    const q = Object.entries<any>(questions).map(([k, v]) =>
      v.type === "choice" ? `- ${k} (choice, one of ${JSON.stringify(Object.keys(v.criteria))}): ${v.instructions}` :
      v.type === "noul" ? `- ${k} (probability true): ${v.instructions}` : `- ${k} (integer score): ${v.instructions}`).join("\n");
    const before = this.chat.cost;
    const { text, usage, ms } = await this.chat.complete([{ role: "user", content: PROMPT.replace("%s", JSON.stringify(state)).replace("%s", q) }], 400, 0);
    const m = /\{[\s\S]*\}/.exec(text);
    let raw: any = {};
    try { raw = m ? JSON.parse(m[0]) : {}; } catch { raw = {}; }
    const answers: Record<string, Answer> = {};
    for (const [k, v] of Object.entries<any>(questions)) {
      const val = raw[k];
      if (v.type === "noul") { const p = Number(val); answers[k] = { type: "noul", noul: Number.isNaN(p) ? 0.5 : Math.max(0, Math.min(1, p)) }; }
      else if (v.type === "choice") {
        const crit = Object.keys(v.criteria);
        const pick = crit.includes(String(val)) ? String(val) : crit[0];
        answers[k] = { type: "choice", choice: pick, probabilities: Object.fromEntries(crit.map((c) => [c, c === pick ? 1 : 0])), confidence: crit.includes(String(val)) ? 1 : 0 };
      } else { const n = parseInt(String(val), 10); answers[k] = { type: "score", score: Number.isNaN(n) ? 0 : n }; }
    }
    return { answers, latency_ms: ms, input_tokens: usage.prompt_tokens ?? 0, cost_usd: this.chat.cost - before, model: this.model };
  }
}

export async function openSensor(spec: string, keys: Keys, timeoutMs?: number): Promise<Sensor | null> {
  if (!spec || spec === "none") return null;
  if (spec === "jev") return new Jev(keys.openrouter ?? "", undefined, undefined, timeoutMs);
  if (spec === "random" || spec.startsWith("random:")) return new RandomSensor(spec.includes(":") ? Number(spec.split(":")[1]) : 0);
  if (spec.startsWith("llm:") || spec === "llm") {
    const { Chat } = await import("./chat.js");
    return new LLMSensor(new Chat({ ...keys, llmModel: spec.startsWith("llm:") ? spec.slice(4) : keys.llmModel }, Math.max(timeoutMs ?? 0, 60000)));
  }
  throw new Error(`unknown sensor '${spec}': jev | none | random | llm:<model>`);
}
