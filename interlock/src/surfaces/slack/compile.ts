import type { Settings } from "../../core/types.js";

export interface RawSlackDraft {
  text: string;
  channel: { name: string; kind: "channel" | "dm" | "group" | "thread" | "unknown"; memberCount: number | null; isPrivate: boolean | null; isSharedExternal: boolean | null };
  recent: Array<{ author: string; text: string }>;
  hasAttachment: boolean;
  senderName: string | null;
  draftOpenedAt: number;
  keystrokes: number;
  deletions: number;
}

export interface SlackState {
  action: "slack.send";
  channel: RawSlackDraft["channel"] & { member_count_bucket: "1" | "2-5" | "6-20" | "21-100" | "100+" | "unknown" };
  message: {
    text_head: string;
    text_chars: number;
    broadcast_mentions: string[];
    user_mentions: number;
    has_attachment: boolean;
    has_code_block: boolean;
    external_links: string[];
    has_placeholders: boolean;
  };
  recent: Array<{ author: string; text_head: string }>;
  sender_context: { local_time: string; draft_age: "<30s" | "30s-2m" | "2-10m" | ">10m"; deletions_ratio: number; name: string | null };
  l0_flags: string[];
}

const SECRET_RE = /\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)\b|password\s*[:=]\s*\S{6,}/i;
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const PHONE_RE = /(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b/g;
const PLACEHOLDER_RE = /\b(TODO|TBD|XXX|FIXME|\[insert[^\]]*\]|\[name\])\b/i;

export function compileSlackState(raw: RawSlackDraft, opts: { now?: number; redaction?: Settings["redaction"] } = {}): SlackState {
  const now = opts.now ?? Date.now();
  const text = raw.text.trim();
  const l0: string[] = [];
  if (SECRET_RE.test(text)) l0.push("secret_pattern_in_body");
  const broadcast = [...text.matchAll(/(?:^|\s)(@here|@channel|@everyone)\b/g)].map((m) => m[1]!);
  const mc = raw.channel.memberCount;
  if (broadcast.length && mc !== null && mc > 50) l0.push("broadcast_to_large_channel");
  if (raw.channel.isSharedExternal) l0.push("externally_shared_channel");
  const scrub = (s: string) => (opts.redaction === "none" ? s : s.replace(EMAIL_RE, "<EMAIL>").replace(PHONE_RE, "<PHONE>"));
  const age = now - raw.draftOpenedAt;
  return {
    action: "slack.send",
    channel: { ...raw.channel, member_count_bucket: mc === null ? "unknown" : mc <= 1 ? "1" : mc <= 5 ? "2-5" : mc <= 20 ? "6-20" : mc <= 100 ? "21-100" : "100+" },
    message: {
      text_head: scrub(text.slice(0, 700)),
      text_chars: text.length,
      broadcast_mentions: broadcast,
      user_mentions: (text.match(/(?:^|\s)@[\w.-]+/g) ?? []).length - broadcast.length,
      has_attachment: raw.hasAttachment,
      has_code_block: /```/.test(text),
      external_links: [...text.matchAll(/https?:\/\/([^\s/]+)/g)].map((m) => m[1]!).filter((h) => !/slack\.com$/.test(h)).slice(0, 5),
      has_placeholders: PLACEHOLDER_RE.test(text),
    },
    recent: raw.recent.slice(-6).map((m) => ({ author: m.author, text_head: scrub(m.text.trim().slice(0, 240)) })),
    sender_context: {
      local_time: fmtTime(now),
      draft_age: age < 30_000 ? "<30s" : age < 120_000 ? "30s-2m" : age < 600_000 ? "2-10m" : ">10m",
      deletions_ratio: raw.keystrokes ? Math.round((raw.deletions / raw.keystrokes) * 100) / 100 : 0,
      name: raw.senderName,
    },
    l0_flags: l0,
  };
}

function fmtTime(ms: number): string {
  const d = new Date(ms);
  return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${String(d.getHours()).padStart(2, "0")}h`;
}
