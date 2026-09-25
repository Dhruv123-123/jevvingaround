// Core types shared by every surface (Gmail today; git/shell/agents later).

export type QuestionType = "noul" | "choice" | "score";

/** A question as the engine sees it: the wire definition plus policy metadata. */
export interface QuestionDef {
  id: string;
  type: QuestionType;
  instructions: string;
  /** noul: {true,false}; choice: option->description; score: ordered level descriptions */
  criteria: Record<string, string | null> | string[];
  /** Policy thresholds on P(true) for nouls (choice/score are informational). */
  thresholds?: { nudge?: number; hold?: number; confirm?: number; block?: number };
  /** Template for the one-line reason shown to the user. {p} = percent, {choice} = choice answer. */
  reason?: string;
  /** Static weight used to rank reasons when several fire. */
  weight?: number;
  /** Questions an org adds are marked so the UI can show provenance. */
  origin?: "builtin" | "org" | "user";
  /** Optional richer reason using sibling answers (e.g. name the recipient a choice question picked). */
  reasonFor?: (a: Answer, answers: Record<string, Answer>) => string | undefined;
}

export type Surface = "email" | "slack" | "agent" | "shell" | "git" | "payment";

export interface WireQuestion {
  type: QuestionType;
  instructions: string;
  criteria: Record<string, string | null> | string[];
}

export interface NoulAnswer { type: "noul"; noul: number }
export interface ChoiceAnswer { type: "choice"; choice: string; probabilities: Record<string, number>; confidence: number }
export interface ScoreAnswer { type: "score"; score: number; legend: Record<string, string>; probabilities: Record<string, number>; confidence: number }
export type Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer;

export interface JevResponse {
  model: string;
  answers: Record<string, Answer>;
  usage: { input_tokens: number; output_tokens: number; cost?: number };
}

export interface EvalResult {
  answers: Record<string, Answer>;
  latencyMs: number;
  inputTokens: number;
  model: string;
  /** USD as reported by the server, when it reports one (OpenRouter does) */
  costUsd?: number;
}

// ---- Email surface ----

export interface RawRecipient { addr: string; name?: string; kind: "to" | "cc" | "bcc" }
export interface RawThreadMessage { from: string; toAddrs: string[]; text: string }

/** What the DOM extractor hands the compiler. Nothing derived yet. */
export interface RawDraft {
  subject: string;
  bodyText: string;
  recipients: RawRecipient[];
  attachments: string[];
  thread: RawThreadMessage[];
  isReplyAll: boolean;
  /** The account sending. Used for org-domain inference. */
  senderAddr: string;
  draftOpenedAt: number;
  keystrokes: number;
  deletions: number;
}

export interface SenderHistory {
  /** addr -> number of prior sends */
  sentTo: Record<string, number>;
  /** timestamps (ms) of recent sends */
  recentSends: number[];
}

export interface CompiledRecipient {
  addr: string;
  kind: "to" | "cc" | "bcc";
  external: boolean;
  first_time_ever: boolean;
  domain_first_time: boolean;
  in_original_thread: boolean;
  /** cheap similarity flag: another known contact differs by <=2 chars */
  looks_like_a_known_contact?: string;
}

export interface EmailState {
  action: "email.send";
  draft: {
    subject: string;
    body_head: string;
    body_tail: string;
    body_chars: number;
    attachments: string[];
    mentions_attachment_in_text: boolean;
    has_placeholders: boolean;
    key_sentences: string[];
  };
  recipients: CompiledRecipient[];
  thread: {
    message_count: number;
    participants_not_in_recipients: string[];
    last_msg_from: string | null;
    last_msg_head: string | null;
    is_reply_all: boolean;
    original_recipient_count: number;
  } | null;
  sender_context: {
    sends_in_last_5_min: number;
    /** coarse on purpose: the state hash must be stable across the seconds before a click */
    local_time: string;
    draft_age: "<30s" | "30s-2m" | "2-10m" | ">10m";
    deletions_ratio: number;
    external_recipient_count: number;
    recipient_count: number;
  };
  l0_flags: string[];
}

// ---- Policy ----

export type VerdictLevel = "proceed" | "nudge" | "hold" | "confirm" | "block";

export interface Reason {
  id: string;
  p: number;
  text: string;
  level: VerdictLevel;
}

export interface Verdict {
  level: VerdictLevel;
  reasons: Reason[];
  /** 0..1 aggregate for the ambient meter */
  regret: number;
  /** why the level is what it is when it differs from the raw ladder (budget, hysteresis, L0) */
  notes: string[];
}

export interface Evaluation<S = unknown> {
  hash: string;
  state: S;
  answers: Record<string, Answer>;
  verdict: Verdict;
  latencyMs: number;
  inputTokens: number;
  at: number;
}

/** Closed set of outcomes. `asked` = a confirmation was requested and not yet answered (an agent may re-issue). */
export type UserAction =
  | "allowed" | "held" | "sent_after_hold" | "sent_now_from_hold"
  | "overrode_confirm" | "overrode_block" | "overridden"
  | "cancelled" | "blocked" | "asked";

/** Audit Vector v1: one line per decision, no content, only hashes and probabilities. See docs/audit.md. */
export interface AuditRecord {
  v: 1;
  kind: "decision";
  at: string;
  surface: Surface;
  pack: string;
  sensor: string;
  hash: string;
  level: VerdictLevel;
  regret: number;
  nouls: Record<string, number>;
  fired: string[];
  l0: string[];
  outcome: UserAction;
  /** the only field that may carry content: what the person or agent typed to override */
  note?: string;
  latency_ms: number;
  input_tokens: number;
  cost_usd: number;
  cache_hit: boolean;
  actor: "human" | "agent";
  budget: { used: number; cap: number };
}

/** A regret event found by `interlock recall`; joins to a decision by hash when one exists. */
export interface RegretRecord {
  v: 1;
  kind: "regret";
  at: string;
  surface: Surface;
  detector: string;
  hash?: string;
  ref?: string;
  detail?: string;
}

export interface Settings {
  apiKey: string;
  baseUrl: string;
  model: string;
  redaction: "none" | "body" | "strict";
  interruptBudgetPerDay: number;
  holdSeconds: number;
  debounceMs: number;
  /** per-question threshold overrides, id -> thresholds */
  thresholdOverrides: Record<string, QuestionDef["thresholds"]>;
  /** org/user-added questions (policy-as-questions) */
  extraQuestions: QuestionDef[];
  disabledQuestions: string[];
  failMode: "open" | "closed";
}

export const DEFAULT_SETTINGS: Settings = {
  apiKey: "",
  baseUrl: "https://api.typesafe.ai",
  model: "jev-latest",
  redaction: "body",
  interruptBudgetPerDay: 3,
  holdSeconds: 20,
  debounceMs: 400,
  thresholdOverrides: {},
  extraQuestions: [],
  disabledQuestions: [],
  failMode: "open",
};
