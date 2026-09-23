// Measure real Jev latency for the email bank from wherever you run this.
//   JEV_API_KEY=… npm run bench            (TypeSafe direct)
//   JEV_API_KEY=… JEV_BASE_URL=https://openrouter.ai/api npm run bench
import { EMAIL_BANK, dynamicQuestions } from "../src/core/bank.js";
import { compileEmailState } from "../src/core/compile.js";
import { JevClient, toWire } from "../src/core/jev.js";

const key = process.env.JEV_API_KEY;
if (!key) { console.error("set JEV_API_KEY"); process.exit(1); }
const client = new JevClient({ apiKey: key, baseUrl: process.env.JEV_BASE_URL ?? "https://api.typesafe.ai", model: process.env.JEV_MODEL ?? "jev-latest" });

const state = compileEmailState(
  {
    subject: "Re: Q3 pricing",
    bodyText: "Hi Sam, attached is the pricing schedule we discussed. Let me know if the 18% works for the first year.",
    recipients: [{ addr: "sam@acme.com", kind: "to" }, { addr: "cfo@ourco.com", kind: "cc" }],
    attachments: ["Q3_pricing_FINAL_v3.xlsx"],
    thread: [{ from: "legal@ourco.com", toAddrs: ["me@ourco.com", "cfo@ourco.com"], text: "Please don't share the discount schedule externally until we sign the MSA." }],
    isReplyAll: true, senderAddr: "me@ourco.com", draftOpenedAt: Date.now() - 40_000, keystrokes: 120, deletions: 20,
  },
  { sentTo: { "cfo@ourco.com": 5 }, recentSends: [] },
);
const questions = toWire([...EMAIL_BANK, ...dynamicQuestions(state)]);
const n = Number(process.env.N ?? 20);
const lat: number[] = [];
let tokens = 0;
for (let i = 0; i < n; i++) {
  const r = await client.evaluate(state, questions);
  lat.push(r.latencyMs); tokens = r.inputTokens;
  if (i === 0) {
    console.log("model", r.model, "| input tokens", r.inputTokens, "| questions", Object.keys(questions).length);
    for (const [id, a] of Object.entries(r.answers)) console.log(`  ${id.padEnd(28)} ${a.type === "noul" ? a.noul.toFixed(3) : a.type === "choice" ? `${a.choice} (${a.confidence.toFixed(2)})` : `${a.score.toFixed(2)} (${a.confidence.toFixed(2)})`}`);
  }
}
lat.sort((a, b) => a - b);
const p = (q: number) => lat[Math.min(lat.length - 1, Math.floor(q * lat.length))];
console.log(`\n${n} calls: p50 ${p(0.5)} ms  p95 ${p(0.95)} ms  max ${lat[lat.length - 1]} ms`);
console.log(`cost/eval ≈ $${((tokens / 1e6) * 0.042).toFixed(6)}  → ~$${(((tokens / 1e6) * 0.042) * 50 * 10).toFixed(4)} per user-day at 50 sends × 10 speculative evals`);
