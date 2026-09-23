import { JevClient, JevError } from "../core/jev.js";
import { DEFAULT_SETTINGS, type AuditRecord, type SenderHistory, type Settings } from "../core/types.js";
import type { Req, Res } from "./messages.js";

const LOG_MAX = 500;
const HISTORY_MAX_ADDRS = 5000;

async function getSettings(): Promise<Settings> {
  const s = (await chrome.storage.sync.get("settings")).settings as Partial<Settings> | undefined;
  return { ...DEFAULT_SETTINGS, ...(s ?? {}) };
}

async function getHistory(): Promise<SenderHistory> {
  const h = (await chrome.storage.local.get("history")).history as SenderHistory | undefined;
  return h ?? { sentTo: {}, recentSends: [] };
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

async function handle(req: Req): Promise<unknown> {
  switch (req.type) {
    case "ping": return { ok: true, at: Date.now() };
    case "settings.get": return getSettings();
    case "settings.set": {
      const cur = await getSettings();
      const next = { ...cur, ...req.patch };
      await chrome.storage.sync.set({ settings: next });
      return next;
    }
    case "evaluate": {
      const s = await getSettings();
      if (!s.apiKey) throw Object.assign(new Error("no api key configured"), { status: 401 });
      const client = new JevClient({ apiKey: s.apiKey, baseUrl: s.baseUrl, model: s.model });
      return client.evaluate(req.state, req.questions);
    }
    case "history.get": return getHistory();
    case "history.touch": {
      const h = await getHistory();
      for (const a of req.addrs) h.sentTo[a.toLowerCase()] = (h.sentTo[a.toLowerCase()] ?? 0) + 1;
      const cutoff = Date.now() - 60 * 60_000;
      h.recentSends = [...h.recentSends.filter((t) => t >= cutoff), Date.now()];
      const keys = Object.keys(h.sentTo);
      if (keys.length > HISTORY_MAX_ADDRS) for (const k of keys.slice(0, keys.length - HISTORY_MAX_ADDRS)) delete h.sentTo[k];
      await chrome.storage.local.set({ history: h });
      return h;
    }
    // one counter per surface, so a noisy Slack day can't silence the email gate
    case "budget.get": {
      const all = ((await chrome.storage.local.get("budget")).budget as Record<string, { used: number; date: string }> | undefined) ?? {};
      const b = all[req.surface];
      return b && b.date === today() ? b : { used: 0, date: today() };
    }
    case "budget.spend": {
      const all = ((await chrome.storage.local.get("budget")).budget as Record<string, { used: number; date: string }> | undefined) ?? {};
      const b = (await handle({ type: "budget.get", surface: req.surface })) as { used: number; date: string };
      all[req.surface] = { used: b.used + 1, date: today() };
      await chrome.storage.local.set({ budget: all });
      return all[req.surface];
    }
    case "log.append": {
      const cur = ((await chrome.storage.local.get("log")).log as AuditRecord[] | undefined) ?? [];
      cur.push(req.record);
      await chrome.storage.local.set({ log: cur.slice(-LOG_MAX) });
      return { size: Math.min(cur.length, LOG_MAX) };
    }
    case "log.list": return ((await chrome.storage.local.get("log")).log as AuditRecord[] | undefined) ?? [];
    case "log.clear": { await chrome.storage.local.set({ log: [] }); return { size: 0 }; }
  }
}

chrome.runtime.onMessage.addListener((req: Req, _sender, sendResponse: (r: Res) => void) => {
  handle(req).then(
    (data) => sendResponse({ ok: true, data }),
    (e: unknown) => {
      const err = e as Error & { status?: number };
      sendResponse({ ok: false, error: err?.message ?? String(e), status: err instanceof JevError ? err.status : err?.status });
    },
  );
  return true; // async
});

chrome.runtime.onInstalled.addListener(() => {
  void getSettings().then((s) => { if (!s.apiKey) void chrome.runtime.openOptionsPage(); });
});
