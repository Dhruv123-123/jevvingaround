// The loop: frame → reads → derived reads → state → one sensor call → rules → typed action. Port of anygame/loop.py.
import { center, type Frame } from "./geometry.js";
import { dumpPack, loadPack, type ActionDef, type Pack } from "./pack.js";
import { aroundOf, readAll, type Values } from "./reads.js";
import { TetrisTracker } from "./tetris.js";
import { FingerprintIndex, fingerprint, fpToBase64, type Fingerprint } from "./fingerprint.js";
import { palette } from "./color.js";
import type { FallbackDecision, VLMFallback } from "./fallback.js";

export interface Device {
  size(): [number, number];
  frame(): Promise<Frame>;
  tap(x: number, y: number): Promise<void>;
  swipe(x0: number, y0: number, x1: number, y1: number, ms?: number): Promise<void>;
  key(name: string): Promise<void>;
  close(): Promise<void>;
}

export interface Answer { type: string; choice?: string; probabilities?: Record<string, number>; confidence?: number; noul?: number; score?: number }
export interface SensorResult { answers: Record<string, Answer>; latency_ms: number; input_tokens: number; cost_usd: number; model?: string }
export interface Sensor { ask(state: any, questions: Record<string, any>): Promise<SensorResult>; model?: string }

export interface Rec { tick: number; hash: string; perception_ms: number; timings_ms: Record<string, number>; screen: Values; action: string; reason?: string; choice?: string; rules?: string[]; action_probs?: Record<string, number>; nouls?: Record<string, number>; choices?: Record<string, string | undefined>; jev_ms?: number; tokens?: number; cost_usd?: number; total_cost_usd?: number; sensor?: string; acted_after_ms?: number;
  mode?: string; support?: number; known?: string | null; fallback?: string }

export function stableHash(v: any): string {
  const s = JSON.stringify(v, (_, val) => (val && typeof val === "object" && !Array.isArray(val) ? Object.keys(val).sort().reduce((o: any, k) => ((o[k] = val[k]), o), {}) : val));
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16) + s.length.toString(16);
}

export function get(values: any, path: string): any {
  let cur = values;
  for (const part of path.split(".")) { if (!cur || typeof cur !== "object") return undefined; cur = cur[part]; }
  return cur;
}

export function direction(prev: string, cur: string): string {
  const m0 = /c(\d+)r(\d+)/.exec(prev ?? ""), m1 = /c(\d+)r(\d+)/.exec(cur ?? "");
  if (!m0 || !m1) return "none";
  const dc = +m1[1] - +m0[1], dr = +m1[2] - +m0[2];
  if (Math.abs(dc) > Math.abs(dr)) return dc > 0 ? "right" : "left";
  if (dr) return dr > 0 ? "down" : "up";
  return "none";
}
const REVERSE: Record<string, string> = { up: "down", down: "up", left: "right", right: "left" };

export class Agent {
  tick = 0;
  history: { tick: number; action: string; choice: string; key: string }[] = [];
  noops: string[] = [];
  lastHash: string | null = null;
  lastValues: Values | null = null;
  prevDistinct: Values = {};
  errors = 0;
  totalCost = 0;
  settling = 0;
  lastAnswers: Record<string, Answer> | null = null;
  trackers: Record<string, TetrisTracker> = {};
  onRecord?: (rec: Rec, frame: Frame, answers: Record<string, Answer> | null) => void;
  // ---- the hybrid: which screen is this, does the pack understand it, and who decides when it does not
  base: Pack;
  mode: string = "main";
  fps = new FingerprintIndex();
  fallback: VLMFallback | null = null;
  goal = "";
  missTicks = 0;
  fallbackCalls = 0;
  onPackChange?: (yaml: string, why: string) => void;
  lastSupport = 1;
  lastFp: Fingerprint | null = null;

  constructor(pack: Pack, public device: Device, public sensor: Sensor | null, public maxTicks: number | null = null) {
    this.base = pack;
    this.pack = pack;
    this.loadFingerprints();
  }
  pack: Pack;

  loadFingerprints() {
    this.fps.clear();
    for (const [name, b64] of Object.entries(this.base.fingerprints)) { try { this.fps.add(name, b64); } catch { /* bad fingerprint: skip */ } }
  }

  /** Replace the pack while playing: the paragraph is the weights, and now the reads and modes are too. */
  swapPack(pack: Pack) {
    this.base = pack;
    this.pack = this.mode !== "main" && pack.modes[this.mode] ? pack.modes[this.mode] : pack;
    this.trackers = {};
    this.lastAnswers = null;
    this.loadFingerprints();
  }

  /** Which mode the frame belongs to: a mode's read condition first (deterministic), then the fingerprint index. */
  classify(baseValues: Values, fp: Fingerprint): { mode: string; known: string | null } {
    for (const [name, m] of Object.entries(this.base.modes)) {
      const w = m.raw.when ?? {};
      if (w.read && this.cond(w, baseValues)) return { mode: name, known: name };
    }
    const k = this.fps.known(fp);
    if (k) return { mode: k.name in this.base.modes ? k.name : "main", known: k.name };
    return { mode: "main", known: null };
  }

  /** Average confidence of the reads that can be confident: colour matches, single locates, the falling piece. */
  support(conf: Record<string, number>, values: Values, pack: Pack = this.pack): number {
    let c: Record<string, number> = { ...conf };
    for (const [rid, r] of Object.entries(pack.reads)) if (r.kind === "tetris" && values[rid]) c[rid] = values[rid].phase === "none" ? 0.4 : 1;
    const own: string[] = pack.raw.own_reads ?? [];
    if (own.length && own.some((k) => k in c)) c = Object.fromEntries(Object.entries(c).filter(([k]) => own.includes(k)));
    const xs = Object.values(c);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 1;
  }

  // ---- questions ----------------------------------------------------------------------------
  questions(values: Values): Record<string, any> {
    const qs: Record<string, any> = {};
    for (const q of this.pack.questions) qs[q.id] = { type: q.type, instructions: q.instructions, criteria: q.criteria };
    if (!qs.action) {
      const criteria: Record<string, string | null> = {};
      for (const a of this.pack.actions) criteria[a.id] = a.params.description ?? null;
      qs.action = { type: "choice", instructions: "Which action now? Follow the play notes in the state.", criteria };
    }
    const crit = qs.action.criteria;
    const bare = new Set(this.noops.filter((n) => !n.includes("→")));
    const left = Object.fromEntries(Object.entries(crit).filter(([k]) => !bare.has(k)));
    if (Object.keys(left).length >= 1 && Object.keys(left).length < Object.keys(crit).length) qs.action = { ...qs.action, criteria: left };
    for (const n of this.noops) {
      if (!n.includes("→")) continue;
      const [aid, val] = n.split("→");
      for (const pq of [`${aid}__cell`, `${aid}__target`, `${aid}__slot`, `${aid}__option`]) {
        if (qs[pq]) { const c = Object.fromEntries(Object.entries(qs[pq].criteria).filter(([k]) => k !== val)); if (Object.keys(c).length) qs[pq] = { ...qs[pq], criteria: c }; }
      }
    }
    for (const a of this.pack.actions) {
      if (a.kind === "play") {
        const hand = a.params.slot ? values[a.params.slot] : null;
        if (hand && typeof hand === "object") {
          const opts: Record<string, null> = {};
          for (const [k, v] of Object.entries(hand)) if (v) opts[`${k}:${v}`] = null;
          if (Object.keys(opts).length) qs[`${a.id}__slot`] = { type: "choice", instructions: `If the action is ${a.id}, which slot (slot:card) to use?`, criteria: opts };
        }
        if (a.params.target) {
          const cells = Object.keys(this.pack.zones[a.params.target].cells()).slice(0, 255);
          qs[`${a.id}__target`] = { type: "choice", instructions: `If the action is ${a.id}, which cell of ${a.params.target} to target? Cells are c<col>r<row>; row 1 is the top of the zone.`, criteria: Object.fromEntries(cells.map((k) => [k.split(".", 2)[1], null])) };
        }
      }
      if (a.kind === "macro") {
        const opts = get(values, a.params.options);
        const landings = opts && typeof opts === "object" ? opts.landings : null;
        if (landings && Object.keys(landings).length) qs[`${a.id}__option`] = { type: "choice", instructions: `If the action is ${a.id}, which option? Each is a computed landing with its consequences.`, criteria: { ...landings } };
      }
      if (a.kind === "tap" && a.params.zone && this.pack.zones[a.params.zone]?.grid && !qs[`${a.id}__cell`]) {
        const cells = Object.keys(this.pack.zones[a.params.zone].cells()).slice(0, 255);
        qs[`${a.id}__cell`] = { type: "choice", instructions: `If the action is ${a.id}, which cell of ${a.params.zone}?`, criteria: Object.fromEntries(cells.map((k) => [k.split(".", 2)[1], null])) };
      }
    }
    const listOf = (read: string) => { const c = get(values, read) ?? []; return (Array.isArray(c) ? c : [c]).map(String); };
    for (const rl of this.pack.rules) {
      for (const [pq, read] of Object.entries<string>(rl.only ?? {})) {
        const cells = listOf(read);
        if (qs[pq]) { const keep = Object.fromEntries(Object.entries(qs[pq].criteria).filter(([k]) => cells.some((x) => x === k || x.startsWith(k + "r")))); if (Object.keys(keep).length) qs[pq] = { ...qs[pq], criteria: keep }; }
      }
      for (const [pq, read] of Object.entries<string>(rl.avoid ?? {})) {
        const cells = listOf(read);
        if (qs[pq]) { const keep = Object.fromEntries(Object.entries(qs[pq].criteria).filter(([k]) => !cells.some((x) => x === k || x.startsWith(k + "r")))); if (Object.keys(keep).length && Object.keys(keep).length < Object.keys(qs[pq].criteria).length) qs[pq] = { ...qs[pq], criteria: keep }; }
      }
    }
    return qs;
  }

  // ---- rules ----------------------------------------------------------------------------------
  cond(c: any, values: Values): boolean {
    const v = get(values, c.read);
    if ("equals" in c) return v === c.equals;
    if ("in" in c) return (c.in as any[]).includes(v);
    if ("not" in c) return v !== c.not;
    const n = Number(v);
    if (Number.isNaN(n)) return false;
    if ("gte" in c) return n >= Number(c.gte);
    if ("lte" in c) return n <= Number(c.lte);
    return false;
  }

  applyRules(answers: Record<string, Answer>, values: Values): string[] {
    const applied: string[] = [];
    const excluded = new Set<string>();
    for (const rl of this.pack.rules) {
      const c = rl.if;
      let hit: boolean, why: string;
      if ("noul" in c) {
        const a = answers[c.noul];
        if (!a || a.type !== "noul") continue;
        const p = a.noul ?? 0;
        hit = "gte" in c ? p >= c.gte : p <= c.lte;
        why = `${c.noul}=${p.toFixed(2)}`;
      } else { hit = this.cond(c, values); why = `${c.read}=${get(values, c.read)}`; }
      if (!hit) continue;
      for (const x of rl.exclude ?? []) {
        const v = typeof x === "string" && x.startsWith("$") ? get(values, x.slice(1)) : x;
        if (v !== undefined && v !== null && v !== "none") { excluded.add(String(v)); applied.push(`${why} → not ${v}`); }
      }
      for (const [target, source] of Object.entries<string>(rl.set ?? {})) {
        const src = answers[source];
        if (src && src.type === "choice" && src.choice && src.choice !== "none" && answers[target] && answers[target].choice !== src.choice) {
          answers[target] = { ...answers[target], choice: src.choice };
          applied.push(`${why} → ${target} = ${source} (${src.choice})`);
        }
      }
    }
    const act = answers.action;
    if (excluded.size && act && act.choice && excluded.has(act.choice)) {
      const probs = Object.entries(act.probabilities ?? {}).filter(([k]) => !excluded.has(k));
      if (probs.length) { const best = probs.sort((a, b) => b[1] - a[1])[0][0]; answers.action = { ...act, choice: best }; applied.push(`→ ${best}`); }
    }
    return applied;
  }

  // ---- perception -----------------------------------------------------------------------------
  present(values: Values, pack: Pack = this.pack): Values {
    const out = { ...values };
    for (const [rid, r] of Object.entries(pack.reads)) {
      if (r.as === "matrix" && values[rid] && typeof values[rid] === "object" && r.zone && pack.zones[r.zone]?.grid) {
        const [cols, rows] = pack.zones[r.zone].grid!;
        const v = values[rid];
        const lines: string[] = [];
        for (let rr = 1; rr <= rows; rr++) { let s = ""; for (let c = 1; c <= cols; c++) s += String(v[`c${c}r${rr}`] ?? "?").slice(0, 1); lines.push(s); }
        out[rid] = lines;
      }
    }
    return out;
  }

  observe(frame: Frame, pack: Pack = this.pack): { values: Values; timings: Record<string, number>; conf: Record<string, number> } {
    const { values: raw, timings, conf } = readAll(pack, frame);
    const values = this.present(raw, pack);
    for (const [rid, r] of Object.entries(pack.reads)) {
      if (!r.history) continue;
      const cur = values[rid];
      if (this.lastValues && rid in this.lastValues && stableHash(this.lastValues[rid]) !== stableHash(cur)) this.prevDistinct[rid] = this.lastValues[rid];
      if (rid in this.prevDistinct) {
        values[`${rid}_prev`] = this.prevDistinct[rid];
        if (r.kind === "locate" && typeof cur === "string" && typeof this.prevDistinct[rid] === "string") {
          values[`${rid}_moving`] = direction(this.prevDistinct[rid], cur);
          values[`${rid}_reverse`] = REVERSE[values[`${rid}_moving`]] ?? "none";
        }
      }
    }
    for (const [rid, r] of Object.entries(pack.reads)) {
      if (r.kind === "around") values[rid] = aroundOf(values[r.of], raw[r.in], values[`${r.of}_moving`] ?? null, r);
      else if (r.kind === "tetris") {
        if (!this.trackers[rid]) this.trackers[rid] = new TetrisTracker(r);
        values[rid] = this.trackers[rid].read(raw[r.in], r.next_in ? raw[r.next_in] : null);
      }
    }
    return { values, timings, conf };
  }

  // ---- actions --------------------------------------------------------------------------------
  private centerOf(name: string): [number, number] {
    const [w, h] = this.device.size();
    const [zn, cell] = name.includes(".") ? name.split(".", 2) : [name, null];
    const z = this.pack.zones[zn];
    const r = cell ? z.cells()[`${zn}.${cell}`] : z.rect;
    const [cx, cy] = center(r);
    return [Math.round(cx * w), Math.round(cy * h)];
  }

  async act(a: ActionDef, answers: Record<string, Answer>): Promise<string> {
    const [w, h] = this.device.size();
    const p = a.params;
    if (a.kind === "wait") return "wait";
    if (a.kind === "key") { await this.device.key(p.key); return `key ${p.key}`; }
    if (a.kind === "macro") {
      const label = answers[`${a.id}__option`]?.choice;
      const tracker = this.trackers[String(p.options).split(".")[0]];
      const keys = tracker && label ? tracker.macros[label] : null;
      if (!keys) return `${a.id} (no option)`;
      for (const k of keys) { await this.device.key(k); await sleep(Number(p.key_ms ?? 40)); }
      tracker.predict(label!);
      return `${a.id} ${label}: ${keys.join(" ")}`;
    }
    if (a.kind === "tap") {
      const cell = answers[`${a.id}__cell`]?.choice;
      let x: number, y: number;
      if (cell || p.zone) [x, y] = this.centerOf(cell ? `${p.zone}.${cell}` : p.zone);
      else { x = Math.round(p.at[0] * w); y = Math.round(p.at[1] * h); }
      await this.device.tap(x, y);
      return `tap ${p.zone ?? ""}${cell ? "." + cell : ""} (${x},${y})`;
    }
    if (a.kind === "swipe") {
      const z = p.zone ? this.pack.zones[p.zone] : null;
      const [cx, cy] = z ? center(z.rect) : [0.5, 0.5];
      const d = Number(p.distance ?? 0.3);
      const [dx, dy] = ({ up: [0, -d], down: [0, d], left: [-d, 0], right: [d, 0] } as Record<string, [number, number]>)[p.dir];
      await this.device.swipe(Math.round(cx * w), Math.round(cy * h), Math.round((cx + dx) * w), Math.round((cy + dy) * h), Number(p.ms ?? 120));
      return `swipe ${p.dir}`;
    }
    if (a.kind === "play") {
      const slot = answers[`${a.id}__slot`]?.choice, target = answers[`${a.id}__target`]?.choice;
      if (!slot || !target) return "play (no slot/target)";
      const [sx, sy] = this.centerOf(`${p.slot}.${slot.split(":")[0]}`);
      const [tx, ty] = this.centerOf(`${p.target}.${target}`);
      if ((p.gesture ?? "tap-tap") === "drag") await this.device.swipe(sx, sy, tx, ty, Number(p.ms ?? 250));
      else { await this.device.tap(sx, sy); await sleep(Number(p.pause ?? 0.15) * 1000); await this.device.tap(tx, ty); }
      return `play ${slot} → ${target}`;
    }
    return `unknown kind ${a.kind}`;
  }

  async actFallback(now: { action?: string; cell?: string; key?: string; at?: [number, number]; kind?: string }): Promise<string> {
    if (now.action) {
      const a = this.pack.actions.find((x) => x.id === now.action) ?? this.base.actions.find((x) => x.id === now.action);
      if (a) {
        const answers: Record<string, Answer> = {};
        if (now.cell) answers[`${a.id}__cell`] = { type: "choice", choice: now.cell };
        return "fallback " + (await this.act(a, answers));
      }
    }
    if (now.kind === "key" && now.key) { await this.device.key(now.key); return `fallback key ${now.key}`; }
    if (now.kind === "tap" && now.at) { await this.device.tap(Math.round(now.at[0]), Math.round(now.at[1])); return `fallback tap (${Math.round(now.at[0])},${Math.round(now.at[1])})`; }
    return "fallback wait";
  }

  /** A mode the VLM defined becomes part of the pack only if its reads return what it said they would on this frame. */
  mergeMode(name: string, mode: Record<string, any>, expect: Record<string, any>, frame: Frame, fp: Fingerprint): boolean {
    try {
      const raw = JSON.parse(JSON.stringify(this.base.raw));
      raw.modes = { ...(raw.modes ?? {}), [name]: { ...mode, when: { fingerprint: fpToBase64(fp) } } };
      const cand = loadPack(dumpPack(raw), `${this.base.name}+${name}`);
      const mp = cand.modes[name];
      const probe = new Agent(mp, this.device, null);
      const { values, conf } = probe.observe(frame, mp);
      const misses = Object.entries(expect).filter(([k, v]) => JSON.stringify(values[k]) !== JSON.stringify(v));
      const sup = probe.support(conf, values, mp);
      if (misses.length || sup < Number(this.base.raw.support_threshold ?? 0.7)) {
        this.onPackChange?.(dumpPack(this.base.raw), `mode ${name} rejected: ${misses.map(([k, v]) => `${k} expected ${JSON.stringify(v)} got ${JSON.stringify(values[k])}`).join("; ") || `support ${sup.toFixed(2)}`}`);
        return false;
      }
      this.swapPack(cand);
      this.onPackChange?.(dumpPack(cand.raw), `learned mode ${name}`);
      return true;
    } catch (e) {
      this.onPackChange?.(dumpPack(this.base.raw), `mode ${name} invalid: ${(e as Error).message.slice(0, 120)}`);
      return false;
    }
  }

  // ---- one tick -------------------------------------------------------------------------------
  async step(): Promise<Rec> {
    this.tick++;
    const t0 = performance.now();
    const frame = await this.device.frame();
    const fp = fingerprint(frame);
    this.lastFp = fp;
    // classify on the base pack's reads, then observe with the active mode's pack
    let obs = this.observe(frame, this.base);
    const cls = this.classify(obs.values, fp);
    if (cls.mode !== this.mode) { this.mode = cls.mode; this.trackers = {}; this.lastAnswers = null; this.noops = []; }
    this.pack = this.mode === "main" ? this.base : this.base.modes[this.mode];
    if (this.mode !== "main") obs = this.observe(frame, this.pack);
    const { values, timings } = obs;
    const support = this.support(obs.conf, values, this.pack);
    this.lastSupport = support;
    const threshold = Number(this.base.raw.support_threshold ?? 0.7);
    const supported = support >= threshold;
    if (supported && !cls.known) this.fps.add(this.mode, fp);          // a screen the pack reads well is a known screen from now on
    const tPerc = performance.now() - t0;
    const h = stableHash(Object.fromEntries(Object.entries(values).filter(([k]) => !k.endsWith("_prev"))));
    const changed = h !== this.lastHash;
    if (changed) this.noops = [];
    else { const last = this.history[this.history.length - 1]; if (last?.key && !this.noops.includes(last.key)) this.noops.push(last.key); }
    const state = { game: this.pack.name, tick: this.tick, how_to_play: this.pack.play, screen: values, recent_actions: this.history.slice(-6).map((x) => x.action), last_action_changed_screen: this.history.length ? changed : null, actions_that_did_nothing_since_last_change: [...this.noops] };
    this.lastValues = values;
    const rec: Rec = { tick: this.tick, hash: h, perception_ms: Math.round(tPerc), timings_ms: timings, screen: values, action: "wait", mode: this.mode, support: Math.round(support * 100) / 100, known: cls.known };
    const done = (r: Rec) => { this.lastHash = h; this.onRecord?.(r, frame, null); return r; };
    // ---- the hybrid: a screen the pack cannot read goes to the VLM, which acts now and may define a mode
    if (!supported && !cls.known) {
      this.missTicks++;
      if (this.fallback && this.missTicks >= Number(this.base.raw.miss_ticks ?? 2)) {
        const d = await this.fallback.decide(frame, this.pack, this.goal || this.base.play.slice(0, 300), this.history.slice(-6).map((x) => x.action), palette(frame, 8));
        rec.fallback = `${d.memo ? "memo" : "vlm"} ${d.screen}${d.name ? " " + d.name : ""}: ${JSON.stringify(d.now)}${d.note ? " — " + d.note : ""}`;
        if (!d.memo) this.fallbackCalls++;
        rec.action = await this.actFallback(d.now);
        rec.reason = `unsupported screen (support ${rec.support}) → fallback`;
        if (d.screen === "mode" && d.mode && d.name) this.mergeMode(d.name, d.mode, d.expect ?? {}, frame, fp);
        else if (d.screen === "transient" && d.name) { this.fps.add(`transient:${d.name}`, fp); this.base.fingerprints[`transient:${d.name}`] = fpToBase64(fp); this.base.raw.fingerprints = this.base.fingerprints; this.onPackChange?.(dumpPack(this.base.raw), `learned transient screen ${d.name}`); }
        this.history.push({ tick: this.tick, action: rec.action, choice: "fallback", key: "fallback" });
        this.missTicks = 0;
        return done(rec);
      }
      if (this.fallback) { rec.action = "wait"; rec.reason = `unsupported screen (support ${rec.support}), ${this.missTicks} tick(s)`; return done(rec); }
    } else this.missTicks = 0;
    if (cls.known?.startsWith("transient:") && this.fallback) {
      // a remembered dismissable screen: replay its memoised input without a model call
      const d = this.fallback.recall(fp);
      if (d) { rec.action = await this.actFallback(d.now); rec.fallback = `memo transient: ${JSON.stringify(d.now)}`; rec.reason = "known transient screen"; return done(rec); }
    }
    const stop = this.pack.raw.stop_when;
    if (stop && this.cond(stop, values)) { rec.action = "stop"; rec.reason = `${stop.read} is ${get(values, stop.read)}`; return done(rec); }
    const gate = this.pack.raw.act_when;
    if (gate && !this.cond(gate, values)) { rec.action = "wait"; rec.reason = `${gate.read} is ${get(values, gate.read)}`; return done(rec); }
    const last = this.history[this.history.length - 1];
    if (this.pack.raw.settle && !changed && last && !["wait", "keep"].includes(last.action) && this.settling < Number(this.pack.raw.settle_ticks ?? 3)) {
      this.settling++; rec.action = "wait"; rec.reason = `settling (${last.action})`; return done(rec);
    }
    if (changed) this.settling = 0;
    if (!this.sensor) { rec.action = "wait"; return done(rec); }
    if (!changed && last && last.action === "wait") { rec.action = "wait"; rec.reason = "screen unchanged"; return done(rec); }
    const qs = this.questions(values);
    let res: SensorResult;
    try {
      res = await this.sensor.ask(state, qs);
    } catch (e) {
      this.errors++;
      if (this.pack.rules.length && this.lastAnswers) {
        res = { answers: JSON.parse(JSON.stringify(this.lastAnswers)), latency_ms: 0, input_tokens: 0, cost_usd: 0 };
        rec.sensor = `error → rules on last answers: ${String((e as Error).message ?? e).slice(0, 80)}`;
      } else { rec.action = "wait"; rec.reason = `sensor error: ${String((e as Error).message ?? e).slice(0, 120)}`; return done(rec); }
    }
    const answers = res.answers;
    if (!rec.sensor) this.lastAnswers = JSON.parse(JSON.stringify(answers));
    const applied = this.applyRules(answers, values);
    const choice = answers.action?.choice ?? "wait";
    const a = this.pack.actions.find((x) => x.id === choice) ?? { id: "wait", kind: "wait", params: {} };
    const acted = await this.act(a, answers);
    this.totalCost += res.cost_usd ?? 0;
    const param = [`${choice}__cell`, `${choice}__target`, `${choice}__slot`, `${choice}__option`].map((k) => answers[k]?.choice).find(Boolean);
    Object.assign(rec, {
      action: acted, choice, rules: applied, acted_after_ms: Math.round(performance.now() - t0), action_probs: answers.action?.probabilities,
      nouls: Object.fromEntries(Object.entries(answers).filter(([, v]) => v.type === "noul").map(([k, v]) => [k, Math.round((v.noul ?? 0) * 100) / 100])),
      choices: Object.fromEntries(Object.entries(answers).filter(([k, v]) => v.type === "choice" && k !== "action").map(([k, v]) => [k, v.choice])),
      jev_ms: res.latency_ms, tokens: res.input_tokens, cost_usd: res.cost_usd, total_cost_usd: Math.round(this.totalCost * 1e6) / 1e6,
    });
    this.history.push({ tick: this.tick, action: acted, choice, key: param ? `${choice}→${param}` : choice });
    this.lastHash = h;
    this.onRecord?.(rec, frame, answers);
    return rec;
  }

  async run(shouldStop?: () => boolean): Promise<Rec> {
    const period = 1000 / this.pack.tickHz;
    let rec: Rec;
    for (;;) {
      const t = performance.now();
      rec = await this.step();
      if (rec.action === "stop" || (this.maxTicks && this.tick >= this.maxTicks) || shouldStop?.()) return rec;
      const dt = performance.now() - t;
      if (dt < period) await sleep(period - dt);
    }
  }
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
