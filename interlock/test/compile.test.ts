import { describe, expect, it } from "vitest";
import { compileEmailState, redact } from "../src/core/compile.js";
import type { RawDraft, SenderHistory } from "../src/core/types.js";

const base: RawDraft = {
  subject: "Re: Q3 pricing",
  bodyText: "Hi Sam, attached is the pricing schedule. Call me on 415-555-0199 or mail bob@ourco.com. TODO check numbers",
  recipients: [{ addr: "sam@acme.com", kind: "to" }, { addr: "cfo@ourco.com", kind: "cc" }],
  attachments: ["Q3_pricing_FINAL_v3.xlsx"],
  thread: [
    { from: "legal@ourco.com", toAddrs: ["me@ourco.com", "cfo@ourco.com"], text: "Please don't share the discount schedule externally until we sign." },
  ],
  isReplyAll: true,
  senderAddr: "me@ourco.com",
  draftOpenedAt: 1_000_000,
  keystrokes: 100,
  deletions: 35,
};
const history: SenderHistory = { sentTo: { "cfo@ourco.com": 4, "sam.b@acme.com": 2 }, recentSends: [1_050_000, 1_020_000, 500_000] };

describe("compileEmailState", () => {
  const s = compileEmailState(base, history, { now: 1_060_000 });

  it("derives recipient facts instead of leaving them to the model", () => {
    const sam = s.recipients.find((r) => r.addr === "sam@acme.com")!;
    expect(sam.external).toBe(true);
    expect(sam.first_time_ever).toBe(true);
    expect(sam.domain_first_time).toBe(false); // sam.b@acme.com is known
    expect(sam.in_original_thread).toBe(false);
    expect(sam.looks_like_a_known_contact).toBe("sam.b@acme.com");
    const cfo = s.recipients.find((r) => r.addr === "cfo@ourco.com")!;
    expect(cfo.external).toBe(false);
    expect(cfo.first_time_ever).toBe(false);
    expect(cfo.in_original_thread).toBe(true);
  });

  it("computes thread set differences", () => {
    expect(s.thread?.participants_not_in_recipients).toEqual(["legal@ourco.com"]);
    expect(s.thread?.last_msg_from).toBe("legal@ourco.com");
    expect(s.thread?.original_recipient_count).toBe(3);
  });

  it("pre-digests numbers and time", () => {
    expect(s.sender_context.sends_in_last_5_min).toBe(2);
    expect(s.sender_context.deletions_ratio).toBe(0.35);
    expect(s.sender_context.draft_age).toBe("30s-2m");
    expect(s.sender_context.local_time).toMatch(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat) \d\dh$/);
    expect(s.sender_context.external_recipient_count).toBe(1);
  });

  it("raises L0 flags and content facts", () => {
    expect(s.l0_flags).toEqual(expect.arrayContaining(["sensitive_attachment_name", "external_recipient_present", "lookalike_recipient"]));
    expect(s.draft.mentions_attachment_in_text).toBe(true);
    expect(s.draft.has_placeholders).toBe(true);
    expect(s.draft.key_sentences.join(" ")).toMatch(/attached/);
  });

  it("redacts PII in free text by default but keeps recipient addresses", () => {
    expect(s.draft.body_head).not.toMatch(/415-555-0199/);
    expect(s.draft.body_head).toMatch(/<PHONE>/);
    expect(s.draft.body_head).not.toMatch(/bob@ourco\.com/);
    expect(s.recipients[0]!.addr).toBe("sam@acme.com");
  });

  it("strict mode replaces recipient addresses with domain-only placeholders, consistently", () => {
    const strict = redact(compileEmailState(base, history, { now: 1_060_000, redaction: "none" }), "strict");
    expect(strict.recipients[0]!.addr).toMatch(/^<R\d@acme\.com>$/);
    expect(strict.recipients[0]!.looks_like_a_known_contact).toMatch(/^<R\d@acme\.com>$/);
    expect(strict.thread!.participants_not_in_recipients[0]).toMatch(/^<R\d@ourco\.com>$/);
    expect(strict.thread!.last_msg_from).toBe(strict.thread!.participants_not_in_recipients[0]);
  });

  it("flags a secret pattern as an L0 hard rule", () => {
    const withKey = compileEmailState({ ...base, bodyText: "here you go: AKIAIOSFODNN7EXAMPLE" }, history, { now: 1_060_000 });
    expect(withKey.l0_flags).toContain("secret_pattern_in_body");
  });

  it("is stable across the seconds before a click (hashable)", () => {
    const a = compileEmailState(base, history, { now: 1_060_000 });
    const b = compileEmailState({ ...base, keystrokes: 103, deletions: 36 }, history, { now: 1_064_000 });
    expect(a).toEqual(b);
  });
});
