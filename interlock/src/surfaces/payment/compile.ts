/**
 * Payment / AP surface. L0 does every number; Jev judges whether the story explains the numbers.
 * Meant to sit in the approval path of an ERP/AP tool as an HTTP call.
 */
export interface PriorPayment { amount: number; at: string }
export interface PaymentInput {
  id?: string;
  amount: number;
  currency: string;
  payee: {
    name: string;
    account_last4?: string;
    bank_country?: string;
    email?: string;
    first_seen_at?: string | null;
    details_changed_at?: string | null;
    prior_payments?: PriorPayment[];
  };
  requester: { id: string; role?: string };
  approver?: { id: string; role?: string };
  invoice?: { number?: string; text?: string; date?: string; due?: string };
  memo?: string;
  request_channel?: string;
  request_text?: string;
  recent_invoices?: Array<{ number?: string; amount: number; payee: string; at: string }>;
  known_payees?: string[];
  approval_threshold?: number;
  now?: string;
}

export interface PaymentState {
  action: "payment.release";
  amount: string;
  currency: string;
  payee: { name: string; bank_country: string | null; email_domain: string | null };
  requester: { id: string; role: string | null };
  approver: { id: string; role: string | null } | null;
  invoice: { number: string | null; text_head: string | null; date: string | null; due: string | null };
  memo: string | null;
  request_channel: string | null;
  request_text_head: string | null;
  facts: {
    first_time_payee: boolean;
    payee_age_days: number | null;
    details_changed_days_ago: number | null;
    prior_payment_count: number;
    amount_vs_median: string | null;
    amount_vs_max: string | null;
    round_amount: boolean;
    just_under_threshold: boolean;
    duplicate_candidates: string[];
    self_approval: boolean;
    lookalike_of_known_payee: string | null;
    bank_country_changed: boolean;
    urgency_words: string[];
    request_via_message_not_system: boolean;
    due_in_days: number | null;
  };
  l0_flags: string[];
}

const URGENCY = ["urgent", "asap", "immediately", "today", "right away", "before end of day", "eod", "don't call", "do not call", "confidential", "keep this between", "ceo", "cfo", "wire now", "final notice", "overdue"];
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;

function days(a: string | null | undefined, now: Date): number | null {
  if (!a) return null;
  const t = new Date(a).getTime();
  return Number.isNaN(t) ? null : Math.round((now.getTime() - t) / 86_400_000);
}
function lev(a: string, b: string): number {
  const dp = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0]!; dp[0] = i;
    for (let j = 1; j <= b.length; j++) { const t = dp[j]!; dp[j] = Math.min(dp[j]! + 1, dp[j - 1]! + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = t; }
  }
  return dp[b.length]!;
}
const norm = (s: string) => s.toLowerCase().replace(/\b(inc|llc|ltd|gmbh|co|corp|limited|pty|sa|ag)\b\.?/g, "").replace(/[^a-z0-9]/g, "");

export function compilePaymentState(input: PaymentInput): PaymentState {
  const now = input.now ? new Date(input.now) : new Date();
  const prior = (input.payee.prior_payments ?? []).map((p) => p.amount).filter((n) => n > 0).sort((a, b) => a - b);
  const median = prior.length ? prior[Math.floor(prior.length / 2)]! : null;
  const max = prior.length ? prior[prior.length - 1]! : null;
  const ratio = (n: number | null) => (n ? `${(input.amount / n).toFixed(1)}x` : null);
  const changedDays = days(input.payee.details_changed_at, now);
  const ageDays = days(input.payee.first_seen_at, now);
  const firstTime = prior.length === 0 && (ageDays === null || ageDays < 1);
  const threshold = input.approval_threshold ?? null;
  const justUnder = threshold !== null && input.amount < threshold && input.amount >= threshold * 0.9;
  const dupes: string[] = [];
  for (const r of input.recent_invoices ?? []) {
    const sameNumber = !!input.invoice?.number && r.number === input.invoice.number;
    const sameAmountPayee = norm(r.payee) === norm(input.payee.name) && Math.abs(r.amount - input.amount) < 0.01 && (days(r.at, now) ?? 999) <= 45;
    if (sameNumber || sameAmountPayee) dupes.push(`${r.number ?? "no-number"} ${r.payee} ${r.amount} on ${r.at}`);
  }
  const self = !!input.approver && input.approver.id === input.requester.id;
  let lookalike: string | null = null;
  const pn = norm(input.payee.name);
  for (const k of input.known_payees ?? []) {
    const kn = norm(k);
    if (kn !== pn && kn.length > 3 && lev(pn, kn) <= 2) { lookalike = k; break; }
  }
  const text = `${input.request_text ?? ""} ${input.memo ?? ""} ${input.invoice?.text ?? ""}`.toLowerCase();
  const urgency = URGENCY.filter((w) => text.includes(w));
  const l0: string[] = [];
  if (changedDays !== null && changedDays <= 14) l0.push("payee_details_changed_recently");
  if (dupes.length) l0.push("duplicate_invoice");
  if (self) l0.push("self_approval");
  if (lookalike) l0.push("payee_lookalike");
  if (firstTime && input.amount >= (threshold ?? 5000)) l0.push("large_first_payment");
  const scrub = (s: string | undefined | null) => (s ? s.replace(EMAIL_RE, "<EMAIL>").replace(/\b(?:\d[ -]?){13,19}\b/g, "<ACCOUNT>").slice(0, 700) : null);
  const prevCountry = input.payee.bank_country && (input.payee.prior_payments?.length ?? 0) > 0 ? null : null; // no history of countries in the input shape; kept explicit
  void prevCountry;

  return {
    action: "payment.release",
    amount: input.amount.toLocaleString("en-US", { maximumFractionDigits: 2 }),
    currency: input.currency,
    payee: { name: input.payee.name, bank_country: input.payee.bank_country ?? null, email_domain: input.payee.email ? input.payee.email.split("@")[1] ?? null : null },
    requester: { id: input.requester.id, role: input.requester.role ?? null },
    approver: input.approver ? { id: input.approver.id, role: input.approver.role ?? null } : null,
    invoice: { number: input.invoice?.number ?? null, text_head: scrub(input.invoice?.text), date: input.invoice?.date ?? null, due: input.invoice?.due ?? null },
    memo: scrub(input.memo),
    request_channel: input.request_channel ?? null,
    request_text_head: scrub(input.request_text),
    facts: {
      first_time_payee: firstTime,
      payee_age_days: ageDays,
      details_changed_days_ago: changedDays,
      prior_payment_count: prior.length,
      amount_vs_median: ratio(median),
      amount_vs_max: ratio(max),
      round_amount: input.amount >= 1000 && input.amount % 1000 === 0,
      just_under_threshold: justUnder,
      duplicate_candidates: dupes.slice(0, 5),
      self_approval: self,
      lookalike_of_known_payee: lookalike,
      bank_country_changed: false,
      urgency_words: urgency,
      request_via_message_not_system: /^(email|slack|chat|sms|whatsapp|phone|teams)$/i.test(input.request_channel ?? ""),
      due_in_days: input.invoice?.due ? -(days(input.invoice.due, now) ?? 0) : null,
    },
    l0_flags: l0,
  };
}
