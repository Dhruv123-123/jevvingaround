import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { AuditRecord, Surface } from "../core/types.js";
import { configDir } from "./config.js";

export function auditPath(): string { return join(configDir(), "audit.jsonl"); }

export function appendAudit(rec: AuditRecord): void {
  mkdirSync(configDir(), { recursive: true });
  appendFileSync(auditPath(), JSON.stringify(rec) + "\n");
}

export function readAudit(limit = 500): AuditRecord[] {
  const p = auditPath();
  if (!existsSync(p)) return [];
  const lines = readFileSync(p, "utf8").trim().split("\n").filter(Boolean);
  return lines.slice(-limit).map((l) => JSON.parse(l) as AuditRecord);
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
