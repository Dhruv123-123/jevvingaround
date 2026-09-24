import type { Answer, QuestionDef, Reason, Verdict, VerdictLevel } from "./types.js";

export const LEVEL_ORDER: VerdictLevel[] = ["proceed", "nudge", "hold", "confirm", "block"];
const rank = (l: VerdictLevel) => LEVEL_ORDER.indexOf(l);
const maxLevel = (a: VerdictLevel, b: VerdictLevel) => (rank(a) >= rank(b) ? a : b);

export interface PolicyContext {
  /** interrupts (confirm/block) already spent today */
  interruptsUsed: number;
  interruptBudget: number;
  /** last verdict for this same compose, for hysteresis */
  previous?: Verdict;
  /** L0 flags the compiler raised for this state */
  l0Flags: string[];
  /** flag → forced level, from the pack; only confirm|block */
  l0Rules?: Record<string, VerdictLevel>;
}

/** Fallback when no pack supplies rules (the built-in packs all do). */
export const DEFAULT_L0_RULES: Record<string, VerdictLevel> = {
  secret_pattern_in_body: "block",
  catastrophic_command_in_args: "block",
  catastrophic_command: "block",
  force_push_to_protected: "confirm",
  payee_details_changed_recently: "confirm",
};

const HYSTERESIS = 0.05;

export function levelFor(q: QuestionDef, p: number, previousLevel?: VerdictLevel): VerdictLevel {
  const t = q.thresholds ?? {};
  // if this question was already at a level last tick, don't drop it for a wobble of < HYSTERESIS
  const slack = (lvl: VerdictLevel) => (previousLevel && rank(previousLevel) >= rank(lvl) ? HYSTERESIS : 0);
  if (t.block !== undefined && p >= t.block - slack("block")) return "block";
  if (t.confirm !== undefined && p >= t.confirm - slack("confirm")) return "confirm";
  if (t.hold !== undefined && p >= t.hold - slack("hold")) return "hold";
  if (t.nudge !== undefined && p >= t.nudge - slack("nudge")) return "nudge";
  return "proceed";
}

export function reasonText(q: QuestionDef, a: Answer, answers: Record<string, Answer> = {}): string {
  const rich = q.reasonFor?.(a, answers);
  if (rich) return rich;
  const p = a.type === "noul" ? a.noul : a.confidence;
  let s = q.reason ?? `${q.id.replace(/_/g, " ")} ({p}%)`;
  s = s.replace("{p}", String(Math.round(p * 100)));
  if (a.type === "choice") s = s.replace("{choice}", a.choice);
  return s;
}

/** Surface-agnostic: the state is only here so callers can pass it through for logging symmetry. */
export function decide(bank: QuestionDef[], answers: Record<string, Answer>, _state: unknown, ctx: PolicyContext): Verdict {
  const notes: string[] = [];
  const reasons: Reason[] = [];
  const prevById = new Map((ctx.previous?.reasons ?? []).map((r) => [r.id, r.level] as const));
  const byId = new Map(bank.map((q) => [q.id, q] as const));

  let level: VerdictLevel = "proceed";
  for (const q of bank) {
    const a = answers[q.id];
    if (!a || a.type !== "noul") continue;
    const lvl = levelFor(q, a.noul, prevById.get(q.id));
    if (lvl !== "proceed") {
      reasons.push({ id: q.id, p: a.noul, text: reasonText(q, a, answers), level: lvl });
      level = maxLevel(level, lvl);
    }
  }

  // L0 hard rules override the model, in both directions of trust: they never wait on the network.
  const rules = ctx.l0Rules ?? DEFAULT_L0_RULES;
  for (const f of ctx.l0Flags) {
    const forced = rules[f];
    if (forced) {
      reasons.push({ id: `l0:${f}`, p: 1, text: `Blocked by rule: ${f.replace(/_/g, " ")}`, level: forced });
      level = maxLevel(level, forced);
      notes.push(`l0 ${f} → ${forced}`);
    }
  }

  // Rank reasons: weight × p, most severe level first
  reasons.sort((x, y) => {
    const dl = rank(y.level) - rank(x.level);
    if (dl) return dl;
    const wx = (byId.get(x.id)?.weight ?? 1) * x.p;
    const wy = (byId.get(y.id)?.weight ?? 1) * y.p;
    return wy - wx;
  });

  // Interrupt budget: a confirm we can't afford degrades to a hold. Blocks are never degraded.
  if (level === "confirm" && ctx.interruptsUsed >= ctx.interruptBudget) {
    level = "hold";
    notes.push(`interrupt budget exhausted (${ctx.interruptsUsed}/${ctx.interruptBudget}) → hold`);
  }

  // Aggregate meter: model's regret score if present, else max weighted noul.
  const rr = answers["regret_risk"];
  let regret = 0;
  if (rr && rr.type === "score") {
    const levels = Object.keys(rr.legend).length || 5;
    regret = Math.max(0, Math.min(1, rr.score / (levels - 1)));
  } else {
    for (const r of reasons) regret = Math.max(regret, Math.min(1, r.p * (byId.get(r.id)?.weight ?? 1)));
  }
  regret = Math.max(regret, level === "block" ? 1 : level === "confirm" ? 0.75 : 0);

  return { level, reasons, regret: Math.round(regret * 100) / 100, notes };
}
