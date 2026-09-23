import type { EmailState, QuestionDef, Settings } from "./types.js";

/**
 * The email question bank. Nouls are the sensor; policy.ts is the judgment.
 * Criteria wording is where most of the accuracy lives — write both sides.
 */
export const EMAIL_BANK: QuestionDef[] = [
  // ---- recipients ----
  {
    id: "wrong_recipient",
    type: "noul",
    instructions:
      "A recipient appears to be included by mistake: an autocomplete slip, a lookalike address, or a person with no role in this conversation.",
    criteria: {
      true: "At least one recipient has no apparent reason to receive this message given the thread, subject and body.",
      false: "Every recipient plausibly belongs given the thread, subject and body.",
    },
    thresholds: { nudge: 0.4, confirm: 0.7 },
    reason: "One recipient looks out of place ({p}%)",
    weight: 1.0,
  },
  {
    id: "missing_recipient",
    type: "noul",
    instructions: "Someone who was part of the thread, or who the body clearly addresses or depends on, is not a recipient.",
    criteria: {
      true: "A thread participant or a person the body names as needing this is absent from the recipients and the omission looks accidental.",
      false: "The recipient set looks intentional; dropped participants, if any, are clearly deliberate.",
    },
    thresholds: { nudge: 0.5, confirm: 0.8 },
    reason: "Someone from the thread was dropped ({p}%)",
    weight: 0.6,
  },
  {
    id: "external_leak",
    type: "noul",
    instructions: "Internal, confidential, or explicitly restricted content is being sent to a recipient outside the sender's organisation.",
    criteria: {
      true: "The body, attachment names, or the thread mark content as internal/confidential/not-to-be-shared, and at least one recipient is external.",
      false: "Nothing appears restricted, or all recipients are internal.",
    },
    thresholds: { nudge: 0.4, confirm: 0.65, block: 0.92 },
    reason: "Restricted content is going outside the org ({p}%)",
    weight: 1.4,
  },
  {
    id: "reply_all_unneeded",
    type: "noul",
    instructions: "This reply-all should have been a reply to one or two people.",
    criteria: {
      true: "The message is addressed to one person or is a brief acknowledgement, yet many thread participants are copied.",
      false: "The content is relevant to everyone copied, or the message is not a reply-all.",
    },
    thresholds: { nudge: 0.6, hold: 0.8 },
    reason: "This looks like it should be a reply, not reply-all ({p}%)",
    weight: 0.4,
  },
  // ---- content ----
  {
    id: "secret_present",
    type: "noul",
    instructions: "The message body or an attachment name contains or refers to a credential: password, API key, token, private key, or login details.",
    criteria: {
      true: "A credential or something that reads as one appears in the body or attachment names.",
      false: "No credentials present; mentions of security are generic.",
    },
    thresholds: { confirm: 0.6, block: 0.9 },
    reason: "Looks like a credential is in this email ({p}%)",
    weight: 1.5,
  },
  {
    id: "missing_attachment",
    type: "noul",
    instructions: "The text refers to an attachment, but nothing is attached.",
    criteria: {
      true: "The body says something is attached or enclosed and the attachment list is empty.",
      false: "Either nothing is referenced as attached, or an attachment is present.",
    },
    thresholds: { confirm: 0.7 },
    reason: "You mention an attachment but nothing is attached ({p}%)",
    weight: 0.9,
  },
  {
    id: "commits_to_terms",
    type: "noul",
    instructions: "The sender commits the organisation to a specific price, discount, date, or deliverable.",
    criteria: {
      true: "The body states a concrete price, discount, delivery date or promise as agreed or offered.",
      false: "No concrete commitment; discussion is exploratory or references existing terms.",
    },
    thresholds: { nudge: 0.6, hold: 0.8 },
    reason: "This commits you to terms ({p}%)",
    weight: 0.7,
  },
  {
    id: "contradicts_thread",
    type: "noul",
    instructions: "The draft ignores or contradicts an explicit instruction or constraint stated earlier in the thread.",
    criteria: {
      true: "An earlier message set a constraint (don't share X, wait for Y, use Z) and the draft violates it.",
      false: "No earlier constraint, or the draft respects it.",
    },
    thresholds: { nudge: 0.5, confirm: 0.75 },
    reason: "This goes against something said earlier in the thread ({p}%)",
    weight: 1.1,
  },
  {
    id: "unfinished_draft",
    type: "noul",
    instructions: "The draft is not finished: placeholders, half sentences, missing greeting where one is expected, or a subject line that is empty or a leftover.",
    criteria: {
      true: "Placeholders like TODO/TBD/[name], trailing incomplete sentences, or an empty/placeholder subject remain.",
      false: "The draft reads as complete.",
    },
    thresholds: { nudge: 0.5, confirm: 0.8 },
    reason: "This looks unfinished ({p}%)",
    weight: 0.8,
  },
  // ---- tone / sender ----
  {
    id: "hostile_tone",
    type: "noul",
    instructions: "A reasonable recipient would read the message as angry, sarcastic, contemptuous, or passive-aggressive.",
    criteria: {
      true: "Wording, punctuation, or framing would land as hostile to the recipient.",
      false: "Neutral, warm, or firm-but-professional.",
    },
    thresholds: { nudge: 0.45, hold: 0.65, confirm: 0.85 },
    reason: "This may read as hostile ({p}%)",
    weight: 0.9,
  },
  {
    id: "sender_rushed",
    type: "noul",
    instructions: "Signals suggest the sender is hurried or emotional: a burst of sends, late on a Friday, heavy deletions, terse wording.",
    criteria: {
      true: "The sender context and wording together indicate haste or agitation.",
      false: "Pace and wording look normal.",
    },
    thresholds: { nudge: 0.7 },
    reason: "You seem to be in a hurry ({p}%)",
    weight: 0.3,
  },
  {
    id: "will_be_forwarded",
    type: "noul",
    instructions: "The content is the kind that gets screenshotted or forwarded beyond its recipients.",
    criteria: {
      true: "Gossip, criticism of named people, salary or HR matters, or blunt opinions about customers/partners.",
      false: "Routine content with no forwarding appeal.",
    },
    thresholds: { nudge: 0.6, hold: 0.8 },
    reason: "This is the kind of email that gets forwarded ({p}%)",
    weight: 0.5,
  },
  // ---- aggregate (ranking only, never policy on its own) ----
  {
    id: "regret_risk",
    type: "score",
    instructions: "How likely is the sender to wish they had not sent this message, as written, to these recipients?",
    criteria: [
      "none: nothing to regret",
      "minor awkwardness: a small typo-level embarrassment",
      "needs a follow-up correction: they'd have to send a fix",
      "damages a relationship or deal",
      "legal, security, or HR incident",
    ],
    weight: 0,
  },
];

/** Questions whose options depend on the state (recipient list) are built per call. */
export function dynamicQuestions(state: EmailState): QuestionDef[] {
  if (state.recipients.length < 2) return [];
  const criteria: Record<string, string | null> = { none: "All recipients look right" };
  for (const r of state.recipients.slice(0, 40)) criteria[r.addr] = null;
  return [
    {
      id: "most_suspicious_recipient",
      type: "choice",
      instructions: "If any recipient looks like a mistake, which one?",
      criteria,
      weight: 0,
    },
  ];
}

/** Apply settings: disable, override thresholds, append org/user questions. */
export function effectiveBank(settings: Pick<Settings, "thresholdOverrides" | "extraQuestions" | "disabledQuestions">, state: EmailState): QuestionDef[] {
  const disabled = new Set(settings.disabledQuestions);
  const base = [...EMAIL_BANK, ...dynamicQuestions(state), ...settings.extraQuestions]
    .filter((q) => !disabled.has(q.id))
    .map((q) => (settings.thresholdOverrides[q.id] ? { ...q, thresholds: { ...q.thresholds, ...settings.thresholdOverrides[q.id] } } : q));
  return base;
}
