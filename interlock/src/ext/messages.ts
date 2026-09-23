import type { AuditRecord, EvalResult, SenderHistory, Settings, Surface, WireQuestion } from "../core/types.js";

export type Req =
  | { type: "settings.get" }
  | { type: "settings.set"; patch: Partial<Settings> }
  | { type: "evaluate"; state: unknown; questions: Record<string, WireQuestion> }
  | { type: "history.get" }
  | { type: "history.touch"; addrs: string[] }
  | { type: "budget.get"; surface: Surface }
  | { type: "budget.spend"; surface: Surface }
  | { type: "log.append"; record: AuditRecord }
  | { type: "log.list" }
  | { type: "log.clear" }
  | { type: "ping"; state?: unknown };

export type Res =
  | { ok: true; data: unknown }
  | { ok: false; error: string; status?: number };

export function send<T = unknown>(req: Req): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(req, (res: Res) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!res) return reject(new Error("no response"));
      if (!res.ok) return reject(Object.assign(new Error(res.error), { status: res.status }));
      resolve(res.data as T);
    });
  });
}

export type EvaluateData = EvalResult;
export type HistoryData = SenderHistory;
export type BudgetData = { used: number; date: string };
