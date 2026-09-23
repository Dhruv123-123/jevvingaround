import { hashState } from "../core/hash.js";
import { JevClient, toWire } from "../core/jev.js";
import { decide } from "../core/policy.js";
import type { Answer, AuditRecord, Evaluation, QuestionDef, Settings, Surface, UserAction, Verdict } from "../core/types.js";
import { appendAudit, budget, spendBudget } from "./audit.js";

export interface GateInput<S> {
  surface: Surface;
  state: S;
  bank: QuestionDef[];
  l0Flags: string[];
  settings: Settings;
  previous?: Verdict;
}

export interface GateOutput<S> {
  evaluation: Evaluation<S>;
  /** true when Jev was unreachable and the verdict came from fail-mode + L0 only */
  degraded: boolean;
  error?: string;
}

/**
 * One call: bank → Jev → policy. Used by every Node surface (agent, shell, git, payment).
 * On a Jev failure the L0 flags still run; the verdict is then `proceed` (fail open) or `block` (fail closed).
 */
export async function runGate<S>(input: GateInput<S>): Promise<GateOutput<S>> {
  const { surface, state, bank, l0Flags, settings } = input;
  const hash = hashState(state);
  const b = budget(surface);
  const ctx = { interruptsUsed: b.used, interruptBudget: settings.interruptBudgetPerDay, previous: input.previous, l0Flags };
  let answers: Record<string, Answer> = {};
  let latencyMs = 0, inputTokens = 0, degraded = false, error: string | undefined;
  if (!settings.apiKey) { degraded = true; error = "no api key (set JEV_API_KEY or run `interlock config`)"; }
  else {
    try {
      const client = new JevClient({ apiKey: settings.apiKey, baseUrl: settings.baseUrl, model: settings.model });
      const r = await client.evaluate(state, toWire(bank));
      answers = r.answers; latencyMs = r.latencyMs; inputTokens = r.inputTokens;
    } catch (e) { degraded = true; error = (e as Error).message; }
  }
  let verdict = decide(bank, answers, state, ctx);
  if (degraded && settings.failMode === "closed" && verdict.level !== "block") {
    verdict = { ...verdict, level: "block", reasons: [{ id: "offline", p: 1, text: `Interlock can't reach Jev (${error}) and is set to fail closed`, level: "block" }, ...verdict.reasons], notes: [...verdict.notes, "fail closed"] };
  } else if (degraded) {
    verdict = { ...verdict, notes: [...verdict.notes, `degraded: ${error}`] };
  }
  if (verdict.level === "confirm" || verdict.level === "block") spendBudget(surface);
  return { evaluation: { hash, state, answers, verdict, latencyMs, inputTokens, at: Date.now() }, degraded, error };
}

export function record<S>(surface: Surface, ev: Evaluation<S>, action: UserAction, note?: string): AuditRecord {
  const nouls: Record<string, number> = {};
  for (const [k, a] of Object.entries(ev.answers)) if (a.type === "noul") nouls[k] = Math.round(a.noul * 1000) / 1000;
  const rec: AuditRecord = {
    at: Date.now(), surface, hash: ev.hash, level: ev.verdict.level, regret: ev.verdict.regret,
    reasons: ev.verdict.reasons.map((r) => ({ id: r.id, p: Math.round(r.p * 1000) / 1000 })),
    nouls, action, latencyMs: ev.latencyMs, inputTokens: ev.inputTokens, cacheHit: false,
  };
  if (note) rec.note = note;
  appendAudit(rec);
  return rec;
}
