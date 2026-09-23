import { describe, expect, it } from "vitest";
import { EMAIL_BANK, dynamicQuestions, effectiveBank } from "../src/core/bank.js";
import { decide, levelFor } from "../src/core/policy.js";
import type { Answer, EmailState, QuestionDef } from "../src/core/types.js";

const state: EmailState = {
  action: "email.send",
  draft: { subject: "x", body_head: "y", body_tail: "", body_chars: 1, attachments: [], mentions_attachment_in_text: false, has_placeholders: false, key_sentences: [] },
  recipients: [
    { addr: "a@x.com", kind: "to", external: true, first_time_ever: true, domain_first_time: true, in_original_thread: false },
    { addr: "b@y.com", kind: "cc", external: false, first_time_ever: false, domain_first_time: false, in_original_thread: true },
  ],
  thread: null,
  sender_context: { sends_in_last_5_min: 0, local_time: "Fri 17h", draft_age: "<30s", deletions_ratio: 0, external_recipient_count: 1, recipient_count: 2 },
  l0_flags: [],
};

const quiet = (): Record<string, Answer> => {
  const a: Record<string, Answer> = {};
  for (const q of EMAIL_BANK) if (q.type === "noul") a[q.id] = { type: "noul", noul: 0.05 };
  a["regret_risk"] = { type: "score", score: 0.2, legend: { "0": "none", "1": "minor", "2": "fix", "3": "damage", "4": "incident" }, probabilities: {}, confidence: 0.9 };
  return a;
};
const ctx = { interruptsUsed: 0, interruptBudget: 3, l0Flags: [] as string[] };

describe("levelFor", () => {
  const q: QuestionDef = { id: "q", type: "noul", instructions: "", criteria: {}, thresholds: { nudge: 0.4, hold: 0.6, confirm: 0.7, block: 0.9 } };
  it("walks the ladder", () => {
    expect(levelFor(q, 0.1)).toBe("proceed");
    expect(levelFor(q, 0.45)).toBe("nudge");
    expect(levelFor(q, 0.65)).toBe("hold");
    expect(levelFor(q, 0.75)).toBe("confirm");
    expect(levelFor(q, 0.95)).toBe("block");
  });
  it("applies hysteresis only downward", () => {
    expect(levelFor(q, 0.67, "confirm")).toBe("confirm"); // was confirm, wobbled to 0.67 → stays
    expect(levelFor(q, 0.67, "nudge")).toBe("hold"); // was lower → no slack
    expect(levelFor(q, 0.6, "confirm")).toBe("hold"); // wobble > 0.05 → really dropped
  });
});

describe("decide", () => {
  it("proceeds when everything is quiet", () => {
    const v = decide(EMAIL_BANK, quiet(), state, ctx);
    expect(v.level).toBe("proceed");
    expect(v.reasons).toEqual([]);
    expect(v.regret).toBeLessThan(0.1);
  });

  it("takes the max level across questions and ranks reasons by severity then weight×p", () => {
    const a = quiet();
    a["sender_rushed"] = { type: "noul", noul: 0.8 }; // nudge
    a["hostile_tone"] = { type: "noul", noul: 0.7 }; // hold
    a["external_leak"] = { type: "noul", noul: 0.7 }; // confirm (0.65)
    const v = decide(EMAIL_BANK, a, state, ctx);
    expect(v.level).toBe("confirm");
    expect(v.reasons.map((r) => r.id)).toEqual(["external_leak", "hostile_tone", "sender_rushed"]);
    expect(v.reasons[0]!.text).toBe("Restricted content is going outside the org (70%)");
  });

  it("degrades confirm to hold when the interrupt budget is spent, never block", () => {
    const a = quiet();
    a["external_leak"] = { type: "noul", noul: 0.7 };
    const v = decide(EMAIL_BANK, a, state, { ...ctx, interruptsUsed: 3 });
    expect(v.level).toBe("hold");
    expect(v.notes[0]).toMatch(/budget exhausted/);
    a["external_leak"] = { type: "noul", noul: 0.95 };
    expect(decide(EMAIL_BANK, a, state, { ...ctx, interruptsUsed: 3 }).level).toBe("block");
  });

  it("L0 hard rules block without the model", () => {
    const v = decide(EMAIL_BANK, quiet(), state, { ...ctx, l0Flags: ["secret_pattern_in_body", "external_recipient_present"] });
    expect(v.level).toBe("block");
    expect(v.reasons[0]!.id).toBe("l0:secret_pattern_in_body");
    expect(v.regret).toBe(1);
  });

  it("names the suspicious recipient when the model picked one confidently", () => {
    const bank = [...EMAIL_BANK, ...dynamicQuestions(state)];
    const a = quiet();
    a["wrong_recipient"] = { type: "noul", noul: 0.82 };
    a["most_suspicious_recipient"] = { type: "choice", choice: "a@x.com", probabilities: { "a@x.com": 0.8, "b@y.com": 0.1, none: 0.1 }, confidence: 0.8 };
    const v = decide(bank, a, state, ctx);
    expect(v.reasons[0]!.text).toBe("a@x.com looks out of place (82%)");
  });

  it("uses the model's regret score for the meter when present", () => {
    const a = quiet();
    a["regret_risk"] = { type: "score", score: 3.2, legend: { "0": "", "1": "", "2": "", "3": "", "4": "" }, probabilities: {}, confidence: 0.7 };
    expect(decide(EMAIL_BANK, a, state, ctx).regret).toBe(0.8);
  });

  it("keeps a confirm alive through a small wobble via previous verdict", () => {
    const a = quiet();
    a["external_leak"] = { type: "noul", noul: 0.66 };
    const first = decide(EMAIL_BANK, a, state, ctx);
    expect(first.level).toBe("confirm");
    a["external_leak"] = { type: "noul", noul: 0.62 };
    expect(decide(EMAIL_BANK, a, state, { ...ctx, previous: first }).level).toBe("confirm");
    expect(decide(EMAIL_BANK, a, state, ctx).level).toBe("nudge");
  });
});

describe("effectiveBank", () => {
  it("applies overrides, disables, and appends org questions", () => {
    const bank = effectiveBank(
      { thresholdOverrides: { hostile_tone: { confirm: 0.5 } }, disabledQuestions: ["sender_rushed"], extraQuestions: [{ id: "falcon", type: "noul", instructions: "x", criteria: { true: "t", false: "f" }, thresholds: { confirm: 0.6 } }] },
      state,
    );
    expect(bank.find((q) => q.id === "hostile_tone")!.thresholds).toEqual({ nudge: 0.45, hold: 0.65, confirm: 0.5 });
    expect(bank.some((q) => q.id === "sender_rushed")).toBe(false);
    expect(bank.some((q) => q.id === "falcon")).toBe(true);
    expect(bank.find((q) => q.id === "most_suspicious_recipient")!.criteria).toHaveProperty("a@x.com");
  });
});
