import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { AuditRecord, RegretRecord, Surface } from "../core/types.js";
import { configDir } from "./config.js";

export function auditPath(): string { return join(configDir(), "audit.jsonl"); }

export function appendAudit(rec: AuditRecord | RegretRecord): void {
  mkdirSync(configDir(), { recursive: true });
  appendFileSync(auditPath(), JSON.stringify(rec) + "\n");
}

export function readAudit(limit = 500): AuditRecord[] {
  return readAll(limit).filter((r): r is AuditRecord => r.kind === "decision");
}

export function readRegrets(limit = 5000): RegretRecord[] {
  return readAll(limit).filter((r): r is RegretRecord => r.kind === "regret");
}

function readAll(limit: number): Array<AuditRecord | RegretRecord> {
  const p = auditPath();
  if (!existsSync(p)) return [];
  const lines = readFileSync(p, "utf8").trim().split("\n").filter(Boolean);
  const out: Array<AuditRecord | RegretRecord> = [];
  for (const l of lines.slice(-limit)) {
    try { const r = JSON.parse(l); if (r && r.v === 1 && (r.kind === "decision" || r.kind === "regret")) out.push(r); } catch { /* skip a torn line */ }
  }
  return out;
}

/** Daily interrupt budget, one counter per surface so a chatty agent can't starve the shell. */
export function budget(surface: Surface): { used: number; date: string } {
  const p = join(configDir(), "budget.json");
  const today = new Date().toISOString().slice(0, 10);
  let all: Record<string, { used: number; date: string }> = {};
  if (existsSync(p)) { try { all = JSON.parse(readFileSync(p, "utf8")); } catch { all = {}; } }
  const b = all[surface];
  return b && b.date === today ? b : { used: 0, date: today };
}

export function spendBudget(surface: Surface): void {
  const p = join(configDir(), "budget.json");
  mkdirSync(configDir(), { recursive: true });
  let all: Record<string, { used: number; date: string }> = {};
  if (existsSync(p)) { try { all = JSON.parse(readFileSync(p, "utf8")); } catch { all = {}; } }
  const b = budget(surface);
  all[surface] = { used: b.used + 1, date: b.date };
  writeFileSync(p, JSON.stringify(all));
}
