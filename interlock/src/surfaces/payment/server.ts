/** `interlock payment-server`: POST /gate/payment → verdict JSON. Fails closed by default: money waits. */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { Settings, UserAction } from "../../core/types.js";
import { record, runGate, type GatePack } from "../../node/gate.js";
import type { Sensor } from "../../sensors/types.js";
import { compilePaymentState, type PaymentInput } from "./compile.js";

type Pending = { ev: Awaited<ReturnType<typeof runGate>>["evaluation"]; meta: Parameters<typeof record>[3] };
const pending = new Map<string, Pending>();

function json(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

export function createPaymentServer(settings: Settings, pack: GatePack, sensor: Sensor) {
  const s: Settings = { ...settings, failMode: process.env.INTERLOCK_FAIL_MODE === "open" ? "open" : "closed" };
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      void (async () => {
        try {
          if (req.method === "GET" && req.url === "/healthz") return json(res, 200, { ok: true, failMode: s.failMode });
          if (req.method === "POST" && req.url === "/gate/payment") {
            const input = JSON.parse(raw) as PaymentInput;
            if (typeof input.amount !== "number" || !input.currency || !input.payee?.name || !input.requester?.id) return json(res, 422, { error: "amount, currency, payee.name, requester.id are required" });
            const state = compilePaymentState(input);
            const g = await runGate({ surface: "payment", state, pack, sensor, l0Flags: state.l0_flags, settings: s });
            const { evaluation, degraded, error } = g;
            const id = input.id ?? evaluation.hash;
            const meta = { pack: g.pack, sensor: g.sensor, actor: "human" as const, costUsd: g.costUsd, cap: s.interruptBudgetPerDay };
            pending.set(id, { ev: evaluation, meta });
            const v = evaluation.verdict;
            if (v.level === "proceed" || v.level === "nudge") record("payment", evaluation, "allowed", meta);
            return json(res, 200, { id, verdict: v.level, regret: v.regret, reasons: v.reasons, notes: v.notes, facts: state.facts, l0_flags: state.l0_flags, degraded, error, latencyMs: evaluation.latencyMs });
          }
          const m = req.url?.match(/^\/gate\/payment\/([^/]+)\/decision$/);
          if (req.method === "POST" && m) {
            const p = pending.get(decodeURIComponent(m[1]!));
            if (!p) return json(res, 404, { error: "unknown id" });
            const body = JSON.parse(raw) as { action: UserAction; note?: string };
            record("payment", p.ev, body.action, p.meta, body.note);
            return json(res, 200, { ok: true });
          }
          json(res, 404, { error: "not found" });
        } catch (e) {
          json(res, 500, { error: (e as Error).message });
        }
      })();
    });
  });
}
