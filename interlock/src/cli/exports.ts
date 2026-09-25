/** Regret detectors over exports: a Gmail/Takeout mbox and a Slack workspace export. Read-only, local. */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import type { RegretRecord } from "../core/types.js";

const SORRY_RE = /^\s*(sorry|apologies|apologis|oops|please (ignore|disregard)|ignore (that|my|the)|disregard|wrong (attachment|file|link|thread|recipient)|forgot (the|to) attach|(here'?s|attaching) the (attachment|file)|meant to|correction|resending|resend)/i;

interface MboxMsg { at: number; from: string; to: string[]; subject: string; head: string; messageId: string; inReplyTo: string }

/** Minimal mbox reader: enough for Takeout. Headers we use; body head only. */
export function parseMbox(text: string, max = 200_000): MboxMsg[] {
  const out: MboxMsg[] = [];
  const chunks = text.split(/^From \S+ .*\r?\n/m).filter(Boolean).slice(-max);
  for (const c of chunks) {
    const sep = c.search(/\r?\n\r?\n/);
    const rawHeaders = (sep >= 0 ? c.slice(0, sep) : c).replace(/\r?\n[ \t]+/g, " ");
    const body = sep >= 0 ? c.slice(sep).trim() : "";
    const h = (name: string) => rawHeaders.match(new RegExp(`^${name}:\\s*(.*)$`, "im"))?.[1]?.trim() ?? "";
    const at = Date.parse(h("Date"));
    if (Number.isNaN(at)) continue;
    const addrs = (s: string) => [...s.matchAll(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)].map((m) => m[0].toLowerCase());
    out.push({ at, from: addrs(h("From"))[0] ?? "", to: [...new Set([...addrs(h("To")), ...addrs(h("Cc"))])].sort(), subject: h("Subject"), head: body.replace(/^>.*$/gm, "").replace(/<[^>]+>/g, " ").trim().slice(0, 200), messageId: h("Message-ID"), inReplyTo: h("In-Reply-To") });
  }
  return out.sort((a, b) => a.at - b.at);
}

/** email: a follow-up from the same sender to the same recipients within 15 min whose first line reads like a correction. */
export function mboxRegrets(path: string, since: number, self?: string): RegretRecord[] {
  if (!existsSync(path)) throw new Error(`mbox not found: ${path}`);
  const msgs = parseMbox(readFileSync(path, "latin1")).filter((m) => m.at >= since && (!self || m.from === self.toLowerCase()));
  const out: RegretRecord[] = [];
  for (let i = 1; i < msgs.length; i++) {
    const b = msgs[i]!;
    if (!SORRY_RE.test(b.head)) continue;
    for (let j = i - 1; j >= 0 && b.at - msgs[j]!.at <= 15 * 60_000; j--) {
      const a = msgs[j]!;
      if (a.from === b.from && a.to.join(",") === b.to.join(",")) {
        out.push({ v: 1, kind: "regret", at: new Date(b.at).toISOString(), surface: "email", detector: "sorry_follow_up_15m", ref: a.messageId || `${a.at}`, detail: `${a.subject.slice(0, 60)} → "${b.head.slice(0, 60)}"` });
        break;
      }
    }
  }
  return out;
}

interface SlackMsg { ts: number; user: string; text: string; edited?: number; channel: string }

/** Slack exports: <dir>/<channel>/<YYYY-MM-DD>.json arrays. Deleted messages are absent, but edits keep their timestamp. */
export function readSlackExport(dir: string, since: number): SlackMsg[] {
  if (!existsSync(dir)) throw new Error(`slack export not found: ${dir}`);
  const out: SlackMsg[] = [];
  for (const ch of readdirSync(dir)) {
    const cdir = join(dir, ch);
    if (!statSync(cdir).isDirectory()) continue;
    for (const f of readdirSync(cdir).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f))) {
      if (Date.parse(f.slice(0, 10)) + 86_400_000 < since) continue;
      let arr: Array<Record<string, unknown>>;
      try { arr = JSON.parse(readFileSync(join(cdir, f), "utf8")); } catch { continue; }
      for (const m of arr) {
        if (typeof m.ts !== "string" || typeof m.text !== "string") continue;
        const ts = Number(m.ts) * 1000;
        if (ts < since) continue;
        const ed = (m.edited as { ts?: string } | undefined)?.ts;
        out.push({ ts, user: String(m.user ?? ""), text: m.text, edited: ed ? Number(ed) * 1000 : undefined, channel: ch });
      }
    }
  }
  return out.sort((a, b) => a.ts - b.ts);
}

/** slack: an edit within 60 s of posting, or a same-user follow-up within 60 s that reads like a correction. */
export function slackRegrets(dir: string, since: number, self?: string): RegretRecord[] {
  const msgs = readSlackExport(dir, since).filter((m) => !self || m.user === self);
  const out: RegretRecord[] = [];
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i]!;
    if (m.edited !== undefined && m.edited - m.ts <= 60_000 && m.edited > m.ts) out.push({ v: 1, kind: "regret", at: new Date(m.edited).toISOString(), surface: "slack", detector: "edited_within_60s", ref: `${m.channel}/${m.ts}`, detail: m.text.slice(0, 60) });
    const n = msgs[i + 1];
    if (n && n.user === m.user && n.channel === m.channel && n.ts - m.ts <= 60_000 && SORRY_RE.test(n.text)) out.push({ v: 1, kind: "regret", at: new Date(n.ts).toISOString(), surface: "slack", detector: "sorry_follow_up_60s", ref: `${m.channel}/${m.ts}`, detail: `${m.text.slice(0, 40)} → "${n.text.slice(0, 40)}"` });
  }
  return out;
}
