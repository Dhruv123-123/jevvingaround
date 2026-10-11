// Tasks: goals the runtime can verify from the reads, and a setter that proposes new ones from the typed frame and
// the frame. SIMA 2's self-improvement loop is a task setter plus a reward model; here the reward is the task's
// `done` condition evaluated by the compiler every tick, and the practice is banked as success spans the learning
// loop must keep allowed. Port of anygame/tasks.py.
import type { Chat } from "./chat.js";
import { checkTasks, SETTER_LIMIT_MAX, SETTER_LIMIT_MIN, TASK_CATEGORIES, type Pack, type TaskDef } from "./pack.js";
import type { Values } from "./reads.js";
import type { Frame } from "./geometry.js";
import { frameToDataUrl } from "./author.js";
import { Agent } from "./loop.js";
import type { TaskResult } from "./learn.js";

const SETTER = `You set practice tasks for a game-playing runtime. The player is a fast judgment model that sees only the
compiled reads below (labels, numbers, cells) and is told one task at a time beside the play notes. A task is
verified by the runtime from the reads, so its \`done\` must be a condition on a read id (or id.path into a read
that returns an object) that the frame makes true when the task is achieved, and that is false now.

Propose tasks that are achievable from this state within the limit, concrete, and varied across categories;
prefer the categories listed as weakest. Never propose a task whose done condition already holds, or one that
no read can verify. A task must be achievable again on any later frame, not only this one: never test the exact
cell of a located thing (the food moves, the head moves); test counts, scores, statuses, relations (around,
runs, margin) and thresholds instead. Answer with ONE JSON array of task objects:
[{"id": "<snake_case>", "instruction": "<one line the player follows>",
  "done": {"read": "<read id or id.path>", "equals"|"in"|"not"|"gte"|"lte": <value>}  (or a list of such conditions, all must hold),
  "when": {... optional: when the task is available ...},
  "hold_ticks": 1, "limit_ticks": <ticks, ${SETTER_LIMIT_MIN} to ${SETTER_LIMIT_MAX}>, "category": "<one of ${TASK_CATEGORIES.join("|")}>"}]
No prose outside the array.`;

export interface TaskStat { attempts: number; done: number; rate: number | null; median_ticks: number | null; category: string }

/** Per task and per category: attempts, completions, success rate, median ticks to complete. */
export function taskStats(results: TaskResult[]): { tasks: Record<string, TaskStat>; categories: Record<string, TaskStat> } {
  const tasks: Record<string, any> = {}, categories: Record<string, any> = {};
  for (const r of results) {
    for (const [key, table] of [[r.id, tasks], [r.category ?? "other", categories]] as [string, Record<string, any>][]) {
      const t = (table[key] ??= { attempts: 0, done: 0, ticks: [], category: r.category ?? "other" });
      t.attempts++;
      if (r.outcome === "done") { t.done++; t.ticks.push(r.ticks); }
    }
  }
  for (const table of [tasks, categories]) for (const t of Object.values(table)) {
    t.rate = t.attempts ? Math.round((t.done / t.attempts) * 1000) / 1000 : null;
    const tk = [...t.ticks].sort((a: number, b: number) => a - b); delete t.ticks;
    t.median_ticks = tk.length ? tk[Math.floor(tk.length / 2)] : null;
  }
  return { tasks, categories };
}

/** The setter's preference: tasks in the weakest categories first, least attempted first within a category. */
export function chooseOrder(tasks: TaskDef[], results: TaskResult[]): string[] {
  const st = taskStats(results);
  const key = (t: TaskDef) => [st.categories[t.category ?? "other"]?.rate ?? -1, st.tasks[t.id]?.attempts ?? 0];
  return [...tasks].sort((a, b) => { const ka = key(a), kb = key(b); return ka[0] - kb[0] || ka[1] - kb[1]; }).map((t) => t.id);
}

export function weakestCategories(results: TaskResult[], tasks: TaskDef[]): string[] {
  const st = taskStats(results).categories;
  const have = new Set(tasks.map((t) => t.category ?? "other"));
  const out = Object.entries(st).sort((a, b) => (a[1].rate ?? 0) - (b[1].rate ?? 0)).slice(0, 2).map(([c]) => c);
  out.push(...TASK_CATEGORIES.filter((c) => !have.has(c) && !out.includes(c)).slice(0, 2));
  return out;
}

/** Ask the chat model for up to k new tasks from the current typed frame and frame; returns the ones that validate. */
export async function proposeTasks(chat: Chat, pack: Pack, frame: Frame, values: Values, results: TaskResult[] = [], k = 3, log: (m: string) => void = () => {}, game = ""): Promise<TaskDef[]> {
  const reads = Object.fromEntries(Object.entries(pack.reads).map(([rid, r]) => [rid, Object.fromEntries(Object.entries(r).filter(([kk]) => ["kind", "options", "symbol", "in", "of", "zone", "parse"].includes(kk)))]));
  const shown = Object.fromEntries(Object.entries(values).filter(([kk]) => !kk.endsWith("_prev")));
  const st = taskStats(results), weak = weakestCategories(results, pack.tasks);
  const text = `Game: ${game || pack.name}. Play notes: ${pack.play.slice(0, 600)}\n\nREADS (id → definition): ${JSON.stringify(reads).slice(0, 2500)}\n\nCURRENT VALUES: ${JSON.stringify(shown).slice(0, 2500)}\n\nACTIONS: ${JSON.stringify(pack.actions.map((a) => a.id))}\n\nEXISTING TASKS: ${JSON.stringify(pack.tasks.map((t) => ({ id: t.id, instruction: t.instruction, done: t.done, category: t.category, limit_ticks: t.limit_ticks }))).slice(0, 2000)}\nRECORD per category (rate = completions / attempts): ${JSON.stringify(st.categories)}\nWEAKEST categories to prefer: ${JSON.stringify(weak)}\n\nPropose up to ${k} NEW tasks (ids not in the existing list).`;
  const messages = [{ role: "system", content: SETTER }, { role: "user", content: [{ type: "text", text }, { type: "image_url", image_url: { url: await frameToDataUrl(frame) } }] }];
  const out: TaskDef[] = [];
  let reply: string;
  try { reply = (await chat.complete(messages, 2500, 0.3)).text; } catch (e) { log(`tasks: setter failed: ${String((e as Error).message ?? e).slice(0, 120)}`); return out; }
  const m = reply.match(/\[[\s\S]*\]/);
  let arr: any;
  try { arr = m ? JSON.parse(m[0]) : []; } catch { log("tasks: the setter's answer was not a JSON array"); return out; }
  const have = new Set(pack.tasks.map((t) => t.id));
  const still = new Agent(pack, { size: () => pack.size, frame: async () => frame, tap: async () => {}, swipe: async () => {}, key: async () => {}, close: async () => {} }, null);
  for (const t of Array.isArray(arr) ? arr : []) {
    if (!t || typeof t !== "object") continue;
    t.id = String(t.id ?? "").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
    if (!t.id || have.has(t.id)) continue;
    let ok: TaskDef;
    try { ok = checkTasks([t], pack.reads, "setter", [SETTER_LIMIT_MIN, SETTER_LIMIT_MAX], pack.zones)[0]; } catch (e) { log(`tasks: rejected ${t.id}: ${String((e as Error).message ?? e).slice(0, 140)}`); continue; }
    if (ok.limit_ticks !== (t.limit_ticks ?? 150)) log(`tasks: ${ok.id}: limit_ticks ${t.limit_ticks} clamped to ${ok.limit_ticks} (the setter's range is ${SETTER_LIMIT_MIN}..${SETTER_LIMIT_MAX})`);
    if (ok.done.every((c) => still.cond(c, values))) { log(`tasks: rejected ${ok.id}: already done on this frame`); continue; }
    const narrow = cellTask(ok, pack.reads);
    if (narrow) { log(`tasks: rejected ${ok.id}: tests the exact cell of ${narrow}; it would hold only on this frame`); continue; }
    have.add(ok.id); out.push(ok);
    if (out.length >= k) break;
  }
  return out;
}

/** The located read a task's condition pins to an exact cell (equals/in on a locate read), or "": the same trap as a cell rule. */
export function cellTask(task: TaskDef, reads: Record<string, any>): string {
  for (const c of [...task.done, ...(task.when ? [task.when] : [])]) {
    const rid = String(c.read ?? "").split(".")[0];
    if (reads[rid]?.kind === "locate" && ("equals" in c || "in" in c) && String(c.read) === rid) return rid;
  }
  return "";
}

/** The task record as a line for logs and the revision prompt. */
export function tasksText(tasks: TaskDef[], results: TaskResult[]): string {
  if (!tasks.length) return "";
  const st = taskStats(results).tasks;
  return "TASKS (practice goals; rate = completions / attempts): " + tasks.map((t) => `${t.id} [${t.category ?? "other"}] ` + (st[t.id] ? `${st[t.id].done}/${st[t.id].attempts}` : "untried")).join("; ");
}
