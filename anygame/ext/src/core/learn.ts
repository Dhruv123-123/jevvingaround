// Learning from experience without touching a model. The runtime cannot tighten Jev's weights, so it grows the
// typed frame instead: every episode goes to a bank, a loss becomes an incident (the last decisions with their
// frames), the chat model proposes a revision of the pack (derived reads, rules, questions, paragraph), and the
// revision is accepted only if it REPLAYS better than the incumbent on the incident: the fatal decision must now be
// guarded by a rule or visible in the typed frame, the ordinary decisions must stay allowed, and the pack must still
// read the screens. Replay is deterministic and costs no model call: Jev's recorded answers are pushed through the
// candidate's reads and rules. Same contract as anygame/learn.py.
import type { Frame } from "./geometry.js";
import { Agent, stableHash, type Rec, type Answer } from "./loop.js";
import type { Values } from "./reads.js";
import { loadPack, dumpPack, type Pack } from "./pack.js";
import { extractYaml, frameToDataUrl } from "./author.js";
import type { Chat } from "./chat.js";
import { StillDevice } from "./index.js";

export interface Decision { rec: Rec; frame: Frame }
/** The fatal window of an episode, oldest first; the last decision is the one that lost. */
export interface Incident { reason: string; tick: number; decisions: Decision[]; at: string }
export interface Episode { n: number; ticks: number; decisions: number; reason: string; score: number | null; won: boolean; lost: boolean; cost_usd: number; version: number; at: string }
export interface Verdict { ok: boolean; why: string; guarded: boolean; distinguished: string[]; overblocked: number; support: number }

export const LOST = /lost|dead|over|game_over|crash|died/i;
export const WON = /won|win|victory|cleared/i;

/** The outcome of an episode from its records: the last record's reason, the score read if the pack names one. */
export function outcome(recs: Rec[], n: number, version: number, scoreRead?: string): Episode {
  const last = recs[recs.length - 1];
  const reason = String(last?.reason ?? (last?.action === "stop" ? "stop" : "tick cap"));
  const dec = recs.filter((r) => r.jev_ms !== undefined);
  const s = scoreRead ? (last?.screen as any)?.[scoreRead] : undefined;
  return {
    n, ticks: recs.length, decisions: dec.length, reason, score: typeof s === "number" ? s : null,
    won: WON.test(reason) && !LOST.test(reason), lost: LOST.test(reason),
    cost_usd: Math.round((last?.total_cost_usd ?? 0) * 1e6) / 1e6, version, at: new Date().toISOString(),
  };
}

/** Is episode b better than a? won > not lost > longer when lost > higher score. Same order as the Python author's _better. */
export function betterEpisode(a: Episode | null, b: Episode): boolean {
  if (!a) return true;
  const key = (e: Episode) => [e.won ? 1 : 0, e.lost ? 0 : 1, e.lost ? e.ticks : 0, e.score ?? 0];
  const ka = key(a), kb = key(b);
  for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return kb[i] > ka[i];
  return false;
}

/** The median episode of a list, by the same order: what a candidate has to beat to stay. */
export function medianEpisode(eps: Episode[]): Episode | null {
  if (!eps.length) return null;
  const sorted = [...eps].sort((x, y) => (betterEpisode(x, y) ? -1 : betterEpisode(y, x) ? 1 : 0));
  return sorted[Math.floor(sorted.length / 2)];
}

/** Jev's answers, rebuilt from a record: enough for the rules to run again. */
export function answersOf(rec: Rec): Record<string, Answer> {
  const out: Record<string, Answer> = {};
  if (rec.action_probs || rec.choice) out.action = { type: "choice", choice: rec.choice, probabilities: rec.action_probs ?? (rec.choice ? { [rec.choice]: 1 } : {}) };
  for (const [k, v] of Object.entries(rec.nouls ?? {})) out[k] = { type: "noul", noul: v };
  for (const [k, v] of Object.entries(rec.choices ?? {})) out[k] = { type: "choice", choice: v };
  return out;
}

/** Cut the fatal window out of an episode: the last `window` decisions before the end, with their frames. */
export function incidentOf(decisions: Decision[], reason: string, tick: number, window = 6): Incident {
  return { reason, tick, decisions: decisions.slice(-window), at: new Date().toISOString() };
}

/** Push the incident through a pack: the presented values, the support, and what the rules would do to the recorded answers. */
export function replay(pack: Pack, inc: Incident): { values: Values[]; choices: string[]; applied: string[][]; support: number[] } {
  const ag = new Agent(pack, new StillDevice([], pack.size), null);
  const values: Values[] = [], choices: string[] = [], applied: string[][] = [], support: number[] = [];
  for (const d of inc.decisions) {
    const { values: v, conf } = ag.observe(d.frame, pack);
    ag.lastValues = v;
    const a = answersOf(d.rec);
    const ap = ag.applyRules(a, v);
    values.push(v); applied.push(ap); choices.push(a.action?.choice ?? "wait"); support.push(ag.support(conf, v, pack));
  }
  return { values, choices, applied, support };
}

/** The keys of the typed frame that separate the fatal tick from every healthy tick under this pack. */
function separators(values: Values[]): string[] {
  if (values.length < 2) return [];
  const fatal = values[values.length - 1], healthy = values.slice(0, -1);
  const out: string[] = [];
  const flat = (v: Values, prefix = ""): Record<string, string> => {
    const o: Record<string, string> = {};
    for (const [k, x] of Object.entries(v)) {
      if (k.endsWith("_prev")) continue;
      if (x && typeof x === "object" && !Array.isArray(x)) Object.assign(o, flat(x as Values, `${prefix}${k}.`)); else o[`${prefix}${k}`] = stableHash(x);
    }
    return o;
  };
  const ff = flat(fatal), hh = healthy.map((h) => flat(h));
  for (const [k, v] of Object.entries(ff)) if (hh.every((h) => h[k] !== v)) out.push(k);
  return out;
}

/** Does the candidate handle the incident better than the incumbent, by replay alone? */
export function verifyRevision(candidate: Pack, incumbent: Pack, inc: Incident, threshold = 0.7, maxOverblock = 0.34): Verdict {
  if (!inc.decisions.length) return { ok: false, why: "no decisions to replay", guarded: false, distinguished: [], overblocked: 0, support: 0 };
  const c = replay(candidate, inc), i = replay(incumbent, inc);
  const support = Math.min(...c.support);
  if (support < threshold) return { ok: false, why: `reads the incident screens worse (support ${support.toFixed(2)})`, guarded: false, distinguished: [], overblocked: 0, support };
  const n = inc.decisions.length - 1;
  const fatalRec = inc.decisions[n].rec;
  const guarded = c.choices[n] !== (fatalRec.choice ?? "wait") && i.choices[n] === (fatalRec.choice ?? "wait");
  // the candidate's frame tells the fatal tick apart where the incumbent's did not
  const sepI = new Set(separators(i.values));
  const distinguished = separators(c.values).filter((k) => !sepI.has(k));
  let changed = 0;
  for (let k = 0; k < n; k++) if (c.choices[k] !== inc.decisions[k].rec.choice && i.choices[k] === inc.decisions[k].rec.choice) changed++;
  const overblocked = n ? changed / n : 0;
  if (overblocked > maxOverblock) return { ok: false, why: `blocks ${changed} of ${n} ordinary decisions too`, guarded, distinguished, overblocked, support };
  if (!guarded && !distinguished.length) return { ok: false, why: "the fatal decision is neither excluded by a rule nor visible in the typed frame", guarded, distinguished, overblocked, support };
  return { ok: true, why: guarded ? `rule now excludes ${fatalRec.choice} at the fatal tick` : `typed frame now separates the fatal tick: ${distinguished.slice(0, 4).join(", ")}`, guarded, distinguished, overblocked, support };
}

const trim = (v: any, n = 420) => { const s = JSON.stringify(v, (k, x) => (String(k).endsWith("_prev") ? undefined : x)); return s.length > n ? s.slice(0, n) + "…" : s; };

/** The incident as the chat model sees it: every decision with its typed frame, Jev's beliefs and what the rules did. */
export function incidentDigest(inc: Incident, episodes: Episode[] = []): string {
  const lines = [`LOSS: ${inc.reason} at tick ${inc.tick}. The last ${inc.decisions.length} decisions before it, oldest first; the LAST one is the fatal decision:`];
  inc.decisions.forEach((d, k) => {
    const r = d.rec;
    lines.push(`${k === inc.decisions.length - 1 ? "FATAL " : ""}tick ${r.tick}: screen=${trim(r.screen)} → ${r.action} probs=${trim(r.action_probs)} beliefs=${trim(r.nouls)} rules=${trim(r.rules)}`);
  });
  if (episodes.length) {
    lines.push(`\nEPISODES so far (newest last): ` + episodes.slice(-10).map((e) => `#${e.n} v${e.version} ${e.won ? "won" : e.lost ? "lost" : "ended"} after ${e.ticks} ticks${e.score !== null ? ` score ${e.score}` : ""} (${e.reason.slice(0, 40)})`).join("; "));
  }
  return lines.join("\n");
}

export const REVISION_RULES =
  "Revise the pack so this loss cannot happen again, without a model being trained: grow the TYPED FRAME. You may add or " +
  "change derived reads (locate, runs, around, history on a read), questions, rules (exclude/set with if: {read…} or {noul…}), " +
  "act_when/settle/stop_when and the play paragraph. Do not change zones or the pixel reads (color, ocr, templates, vocab, blobs) " +
  "unless a frame shows one is wrong, and never remove a rule that fired correctly. The fatal decision must become impossible " +
  "(a rule excludes it from the values the reads had at that tick) or visible (a new read separates that tick from the ordinary ones), " +
  "and the ordinary decisions in the window must stay allowed. Every rule must only name reads that exist. " +
  "Return the whole pack.yaml in one fenced yaml block.";

export const PACK_SCHEMA_HINT =
  "Exact syntax (anything else fails to load):\n" +
  "- locate: { kind: locate, in: <matrix read id>, symbol: \"<char>\", many: true|false, row: N, col: N } → a cell \"c<col>r<row>\" (a list with many)\n" +
  "- runs: { kind: runs, in: <matrix read id>, symbol: \"<char>\", length: N, gravity: down } → the empty cells that would complete N in a line\n" +
  "- around: { kind: around, of: <locate read id>, in: <matrix read id>, free: [\"<char>\", …] } → { up, down, left, right, ahead, <dir>_free, <dir>_space }\n" +
  "- history: put `history: 1` on a read → <id>_prev; on a locate also <id>_moving and <id>_reverse\n" +
  "- rule: { if: { read: <id or id.path>, equals|in|not|gte|lte: v }, exclude: [<action id or $read>] } or { if: { noul: <question id>, gte|lte: p }, set: { <action>__cell: <choice question id> } }; avoid/only: { <action>__cell: <read id> }\n" +
  "- question: { id, type: noul|choice|score, instructions, criteria: { <option>: <meaning> } }\n" +
  "No other keys. YAML with a duplicated key does not load.";

/** A revision: incident → chat model → candidate → replay verdict, with one repair round when the candidate does not
 *  load or the replay rejects it. Returns the accepted pack or null. */
export async function improve(chat: Chat, pack: Pack, inc: Incident, episodes: Episode[] = [], log: (m: string) => void = () => {}, opts: { threshold?: number; maxTokens?: number; rounds?: number } = {}): Promise<{ pack: Pack | null; verdict: Verdict | null; yaml: string | null }> {
  const parts: any[] = [{ type: "text", text: REVISION_RULES + "\n\n" + PACK_SCHEMA_HINT + "\n\n" + incidentDigest(inc, episodes) + "\n\n```yaml\n" + dumpPack(pack.raw) + "\n```" }];
  const n = inc.decisions.length;
  for (const k of n > 1 ? [n - 2, n - 1] : [n - 1]) {
    parts.push({ type: "text", text: `${k === n - 1 ? "the fatal" : "the previous"} decision's frame (tick ${inc.decisions[k].rec.tick}):` });
    parts.push({ type: "image_url", image_url: { url: await frameToDataUrl(inc.decisions[k].frame) } });
  }
  const threshold = opts.threshold ?? Number(pack.raw.support_threshold ?? 0.7);
  let messages: any[] = [{ role: "user", content: parts }];
  let lastYaml: string | null = null, lastVerdict: Verdict | null = null;
  log(`learn: asking ${chat.model} about the loss at tick ${inc.tick} …`);
  for (let round = 1; round <= (opts.rounds ?? 2); round++) {
    const { text } = await chat.complete(messages, opts.maxTokens ?? 12000, 0.2);
    const y = extractYaml(text);
    let problem: string | null = null, cand: Pack | null = null, v: Verdict | null = null;
    if (!y) problem = "there was no ```yaml block";
    else {
      lastYaml = y;
      try {
        cand = loadPack(y, pack.name);
        cand.raw.fingerprints = { ...(pack.raw.fingerprints ?? {}), ...(cand.raw.fingerprints ?? {}) };
        cand.raw.modes = cand.raw.modes ?? pack.raw.modes;
        cand = loadPack(dumpPack(cand.raw), pack.name);
        v = verifyRevision(cand, pack, inc, threshold);
        lastVerdict = v;
        if (!v.ok) problem = `replaying the loss through it: ${v.why}`;
      } catch (e) { problem = `it does not load: ${(e as Error).message.slice(0, 200)}`; }
    }
    if (!problem && cand && v) { log(`learn: accepted (round ${round}): ${v.why}`); return { pack: cand, verdict: v, yaml: y }; }
    log(`learn: round ${round} rejected: ${problem}`);
    messages = [...messages, { role: "assistant", content: text }, { role: "user", content: `That revision was rejected: ${problem}.\n${PACK_SCHEMA_HINT}\nReturn the whole corrected pack.yaml in one fenced yaml block.` }];
  }
  return { pack: null, verdict: lastVerdict, yaml: lastYaml };
}

/** The bank: what the runtime remembers about a pack across episodes. Frames are kept for the last few incidents only. */
export class Bank {
  episodes: Episode[] = [];
  incidents: Incident[] = [];
  version = 1;
  constructor(public maxIncidents = 4, public maxEpisodes = 60) {}
  addEpisode(e: Episode) { this.episodes.push(e); if (this.episodes.length > this.maxEpisodes) this.episodes.shift(); }
  addIncident(i: Incident) { this.incidents.push(i); if (this.incidents.length > this.maxIncidents) this.incidents.shift(); }
  /** Episodes played with a given pack version. */
  ofVersion(v: number): Episode[] { return this.episodes.filter((e) => e.version === v); }
}
