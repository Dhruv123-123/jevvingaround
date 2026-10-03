// An episode rater: the chat model scores a played episode 0 to 100 for completion (did the play achieve the goal or
// the task) and directedness (did the moves serve it, or wander), from a dozen sampled frames and the action log.
// Used as the score where a pack has no score read, and reported next to the trial verdict; never the last word,
// because rater and proposer share a model. Port of anygame/rater.py.
import type { Chat } from "./chat.js";
import type { Frame } from "./geometry.js";
import type { Rec } from "./loop.js";
import { frameToDataUrl } from "./author.js";
import type { Episode } from "./learn.js";

const RUBRIC = `You rate one episode of a game played by an automated player. You see frames sampled evenly across the episode
(first to last) and a summary of the actions taken. Score two things, each 0 to 100:
- completion: how far the play got toward the goal (and the task, if one is named): 0 nothing, 50 clearly half way or a
  modest success, 100 fully achieved (a won game, a completed task, a long survival with a high score).
- directedness: how much of the play served the goal: 100 every move purposeful, 50 half the moves wasted or
  wandering, 0 random.
Answer with ONE JSON object: {"completion": <int>, "directedness": <int>, "note": "<one line: what happened>"}.`;

export interface Rating { completion: number | null; directedness: number | null; note: string; cost_usd: number }

/** k frames spread evenly across the episode, the first and the last always among them. */
export function sampleFrames<T>(frames: [number, T][], k = 10): [number, T][] {
  if (frames.length <= k) return [...frames];
  const idx = new Set<number>([0, frames.length - 1]);
  for (let i = 0; i < k; i++) idx.add(Math.round((i * (frames.length - 1)) / (k - 1)));
  return [...idx].sort((a, b) => a - b).slice(0, k).map((i) => frames[i]);
}

export function actionsSummary(recs: Rec[], limit = 40): string {
  const acts = recs.filter((r) => r.choice && r.choice !== "fallback").map((r) => String(r.action));
  if (!acts.length) return "no actions";
  const c: Record<string, number> = {}; for (const a of acts) c[a] = (c[a] ?? 0) + 1;
  const head = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([a, n]) => `${a}×${n}`).join(", ");
  return `${acts.length} actions (${head}); the last ${Math.min(limit, acts.length)}: ${acts.slice(-limit).join(" ")}`;
}

const clamp = (v: any): number | null => { const n = Number(v); return v === null || v === undefined || !Number.isFinite(n) ? null : Math.max(0, Math.min(100, Math.round(n))); };

export async function rateEpisode(chat: Chat, frames: [number, Frame][], recs: Rec[], goal = "", task = "", outcome = ""): Promise<Rating> {
  const picked = sampleFrames(frames);
  const text = `Game: ${goal.slice(0, 300) || "unknown"}. ` + (task ? `Task given to the player: ${task}. ` : "") + (outcome ? `How the episode ended: ${outcome}. ` : "") +
    `${recs.length} ticks. Actions: ${actionsSummary(recs)}.\nFrames follow, tick numbers first.`;
  const parts: any[] = [{ type: "text", text }];
  for (const [tick, fr] of picked) { parts.push({ type: "text", text: `tick ${tick}:` }); parts.push({ type: "image_url", image_url: { url: await frameToDataUrl(fr) } }); }
  const before = chat.cost ?? 0;
  let j: any;
  try {
    // a reasoning model spends tokens before it answers: a small budget returns nothing at all
    const reply = (await chat.complete([{ role: "system", content: RUBRIC }, { role: "user", content: parts }], 2500, 0)).text;
    const m = reply.match(/\{[\s\S]*\}/);
    const cost = Math.round(((chat.cost ?? 0) - before) * 1e6) / 1e6;
    if (!m) return { completion: null, directedness: null, note: `rater answered without a JSON object: ${JSON.stringify(reply.slice(0, 80))}`, cost_usd: cost };
    j = JSON.parse(m[0]);
  } catch (e) { return { completion: null, directedness: null, note: `rater failed: ${String((e as Error).message ?? e).slice(0, 80)}`, cost_usd: 0 }; }
  return { completion: clamp(j.completion), directedness: clamp(j.directedness), note: String(j.note ?? "").slice(0, 160), cost_usd: Math.round(((chat.cost ?? 0) - before) * 1e6) / 1e6 };
}

/** How well the rater's order agrees with the trial order the loop trusts (won > tasks > not lost > longer > score),
 *  over every pair of rated episodes where that order is strict; the episodes' own score is left out so a rating used
 *  as the score cannot vouch for itself. Same as rater.py's calibrate. */
export function calibrateRater(episodes: (Episode & { rating?: Rating })[]): { rated: number; pairs: number; agreement: number | null } {
  const key = (e: Episode) => [e.won ? 1 : 0, e.tasks_done ?? 0, e.lost ? 0 : 1, e.lost ? e.ticks : 0];
  const cmp = (a: number[], b: number[]) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0; };
  const rated = episodes.filter((e) => e.rating && e.rating.completion !== null);
  let pairs = 0, agree = 0;
  for (let i = 0; i < rated.length; i++) for (let k = i + 1; k < rated.length; k++) {
    const a = rated[i], b = rated[k];
    const o = cmp(key(a), key(b)); if (o === 0) continue;
    const ra = a.rating!.completion!, rb = b.rating!.completion!; if (ra === rb) continue;
    pairs++; if ((o > 0) === (ra > rb)) agree++;
  }
  return { rated: rated.length, pairs, agreement: pairs ? Math.round((agree / pairs) * 1000) / 1000 : null };
}
