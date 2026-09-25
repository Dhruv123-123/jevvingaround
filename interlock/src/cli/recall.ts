/**
 * `interlock recall`: find regret events in local history and join them to decisions in the audit log.
 * Detectors are read-only and local. Email/Slack detectors (exports) are not implemented yet.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { RegretRecord } from "../core/types.js";
import { appendAudit, readAudit, readRegrets } from "../node/audit.js";
import { isInteresting } from "../surfaces/shell/compile.js";
import { mboxRegrets, slackRegrets } from "./exports.js";

export interface RecallOptions { cwd: string; since: string; home: string; write?: boolean; mbox?: string; slackExport?: string; self?: string }
export interface RecallReport {
  since: string;
  regrets: RegretRecord[];
  decisions: number;
  /** regrets that match a decision by hash or by time window on the same surface */
  matched: Array<{ regret: RegretRecord; level: string | null }>;
  caught: number;
  recall: number | null;
  notes: string[];
}

function git(cwd: string, args: string[]): string {
  try { return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 16 * 1024 * 1024 }); } catch { return ""; }
}

function sinceMs(spec: string): number {
  const m = spec.match(/^(\d+)([dhw])$/);
  if (!m) return Date.now() - 90 * 86_400_000;
  const n = Number(m[1]);
  return Date.now() - n * (m[2] === "h" ? 3_600_000 : m[2] === "w" ? 7 * 86_400_000 : 86_400_000);
}

/** git: a revert, a force-push, or an amend-after-push within an hour of a push, from the reflog. */
export function gitRegrets(cwd: string, since: number): RegretRecord[] {
  const out: RegretRecord[] = [];
  if (!existsSync(join(cwd, ".git"))) return out;
  const log = git(cwd, ["log", "--all", "--format=%H%x09%ct%x09%s", "--since", new Date(since).toISOString()]).trim().split("\n").filter(Boolean);
  for (const line of log) {
    const [sha, ct, subject] = line.split("\t") as [string, string, string];
    if (/^Revert "/.test(subject)) {
      const target = subject.match(/^Revert "(.+)"/)?.[1];
      out.push({ v: 1, kind: "regret", at: new Date(Number(ct) * 1000).toISOString(), surface: "git", detector: "revert_commit", ref: sha.slice(0, 10), detail: target });
    }
  }
  // reflog on remote-tracking refs shows forced updates as "forced-update"
  const reflog = git(cwd, ["reflog", "show", "--all", "--date=iso-strict", "--format=%gd%x09%gs%x09%cI"]).trim().split("\n").filter(Boolean);
  for (const line of reflog) {
    const [ref, msg, when] = line.split("\t") as [string, string, string];
    if (!when || new Date(when).getTime() < since) continue;
    if (/forced-update|\(forced update\)/i.test(msg)) out.push({ v: 1, kind: "regret", at: when, surface: "git", detector: "force_push", ref, detail: msg.slice(0, 120) });
    if (/commit \(amend\)/.test(msg) && /origin|upstream/.test(ref)) out.push({ v: 1, kind: "regret", at: when, surface: "git", detector: "amend_after_push", ref, detail: msg.slice(0, 120) });
  }
  return out;
}

/** shell: the same risky command re-run within 5 minutes with one token changed (a corrected path or flag). */
export function shellRegrets(home: string, since: number): RegretRecord[] {
  const out: RegretRecord[] = [];
  const zsh = join(home, ".zsh_history"), bash = join(home, ".bash_history");
  const entries: Array<{ at: number; cmd: string }> = [];
  if (existsSync(zsh)) {
    for (const line of readFileSync(zsh, "latin1").split("\n")) {
      const m = line.match(/^: (\d+):\d+;(.*)$/);
      if (m) entries.push({ at: Number(m[1]) * 1000, cmd: m[2]! });
    }
  } else if (existsSync(bash)) {
    let t = 0;
    for (const line of readFileSync(bash, "latin1").split("\n")) {
      if (line.startsWith("#") && /^#\d+$/.test(line)) t = Number(line.slice(1)) * 1000;
      else if (line.trim()) entries.push({ at: t, cmd: line });
    }
  }
  const risky = entries.filter((e) => e.at >= since && isInteresting(e.cmd));
  for (let i = 1; i < risky.length; i++) {
    const a = risky[i - 1]!, b = risky[i]!;
    if (b.at - a.at > 5 * 60_000 || a.cmd === b.cmd) continue;
    const ta = a.cmd.split(/\s+/), tb = b.cmd.split(/\s+/);
    if (ta.length === tb.length && ta.filter((t, k) => t !== tb[k]).length === 1) {
      out.push({ v: 1, kind: "regret", at: new Date(b.at).toISOString(), surface: "shell", detector: "rerun_with_one_token_changed", detail: `${a.cmd.slice(0, 80)} → ${b.cmd.slice(0, 80)}` });
    }
  }
  return out;
}

/** agent: a confirm the agent overrode whose tool call then errored, or repeated asks on the same hash. */
export function agentRegrets(since: number): RegretRecord[] {
  const out: RegretRecord[] = [];
  const rows = readAudit(5000).filter((r) => r.surface === "agent" && new Date(r.at).getTime() >= since);
  const asks = new Map<string, number>();
  for (const r of rows) {
    if (r.outcome === "asked") asks.set(r.hash, (asks.get(r.hash) ?? 0) + 1);
    if (r.outcome === "asked" && (asks.get(r.hash) ?? 0) >= 3) out.push({ v: 1, kind: "regret", at: r.at, surface: "agent", detector: "asked_three_times_same_call", hash: r.hash });
  }
  return out;
}

export async function runRecall(opts: RecallOptions): Promise<RecallReport> {
  const since = sinceMs(opts.since);
  const notes: string[] = [];
  const regrets = [...gitRegrets(opts.cwd, since), ...shellRegrets(opts.home, since), ...agentRegrets(since)];
  if (opts.mbox) regrets.push(...mboxRegrets(opts.mbox, since, opts.self)); else notes.push("email: pass --mbox <Takeout .mbox> to scan sent mail for sorry-follow-ups");
  if (opts.slackExport) regrets.push(...slackRegrets(opts.slackExport, since, opts.self)); else notes.push("slack: pass --slack-export <dir> to scan an export for quick edits and corrections");
  const known = new Set(readRegrets().map((r) => `${r.detector}|${r.ref ?? r.hash ?? r.at}`));
  for (const r of regrets) if (!known.has(`${r.detector}|${r.ref ?? r.hash ?? r.at}`)) appendAudit(r);
  const decisions = readAudit(20000).filter((d) => new Date(d.at).getTime() >= since);
  const matched: RecallReport["matched"] = [];
  for (const r of regrets) {
    const byHash = r.hash ? decisions.find((d) => d.hash === r.hash) : undefined;
    const t = new Date(r.at).getTime();
    const byTime = byHash ?? decisions.filter((d) => d.surface === r.surface && Math.abs(new Date(d.at).getTime() - t) < 3_600_000).sort((a, b) => Math.abs(new Date(a.at).getTime() - t) - Math.abs(new Date(b.at).getTime() - t))[0];
    matched.push({ regret: r, level: byTime?.level ?? null });
  }
  const gated = matched.filter((m) => m.level !== null);
  const caught = gated.filter((m) => m.level === "confirm" || m.level === "block" || m.level === "hold").length;
  return { since: opts.since, regrets, decisions: decisions.length, matched, caught, recall: gated.length ? Math.round((100 * caught) / gated.length) / 100 : null, notes };
}

export function formatRecall(r: RecallReport): string {
  const lines = [`regret events in the last ${r.since}: ${r.regrets.length}   decisions logged: ${r.decisions}`];
  for (const m of r.matched) lines.push(`  ${m.regret.at.slice(0, 16)}  ${m.regret.surface.padEnd(6)} ${m.regret.detector.padEnd(30)} ${m.level ? `gate said ${m.level}` : "no decision on record"}  ${m.regret.detail ?? m.regret.ref ?? ""}`);
  const gated = r.matched.filter((m) => m.level !== null).length;
  lines.push(gated ? `recall: ${r.caught}/${gated} regret events that went through the gate were at hold or above (${Math.round((r.recall ?? 0) * 100)}%)` : `recall: no regret event has a matching decision yet — install the gates, live with them, run this again`);
  for (const n of r.notes) lines.push(`note: ${n}`);
  return lines.join("\n");
}
