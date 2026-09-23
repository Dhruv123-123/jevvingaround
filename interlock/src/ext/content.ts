import { decide } from "../core/policy.js";
import { toWire } from "../core/jev.js";
import { Speculator } from "../core/speculate.js";
import { DEFAULT_SETTINGS, type AuditRecord, type EvalResult, type Evaluation, type SenderHistory, type Settings, type UserAction, type Verdict } from "../core/types.js";
import { adapterFor, type SurfaceAdapter } from "./adapter.js";
import type { ComposeCounters } from "./gmail.js";
import { send, type BudgetData } from "./messages.js";
import { InterlockUI } from "./ui.js";

/**
 * One Interlock per compose box, on any surface an adapter describes. Lifecycle:
 *   keystroke → Speculator.onChange → (pause) compile → Jev → policy → meter
 *   Send (click or send-key, captured) → Speculator.verdictFor → 0 ms on hash hit → ladder
 */
class ComposeInterlock<S> {
  private ui: InterlockUI;
  private spec: Speculator<S, Evaluation<S>>;
  private counters: ComposeCounters = { openedAt: Date.now(), keystrokes: 0, deletions: 0 };
  private previous: Verdict | undefined;
  private bypassNext = false;
  private disposed = false;
  private onInput = (e: Event) => {
    this.counters.keystrokes++;
    if (e instanceof InputEvent && e.inputType?.startsWith("delete")) this.counters.deletions++;
    this.spec.onChange();
  };
  private onKeydown = (e: KeyboardEvent) => { if (this.a.isSendKey(e)) this.intercept(e); };
  private onClick = (e: MouseEvent) => {
    const btn = this.a.findSendButton(this.root);
    if (btn && e.target instanceof Node && btn.contains(e.target)) this.intercept(e);
  };

  constructor(private a: SurfaceAdapter<S>, private root: HTMLElement, private sendBtn: HTMLElement, private settings: Settings, private history: SenderHistory) {
    this.ui = new InterlockUI(sendBtn);
    this.spec = new Speculator<S, Evaluation<S>>({
      getState: () => this.state(),
      evaluate: (s, h) => this.evaluate(s, h),
      debounceMs: settings.debounceMs,
      onResult: (r) => this.paint(r),
      onError: (e) => this.onError(e),
    });
    root.addEventListener("input", this.onInput, true);
    root.addEventListener("keydown", this.onKeydown, true);
    root.addEventListener("click", this.onClick, true);
    this.spec.onChange();
  }

  private state(): S | null { return this.a.compile(this.root, document, this.counters, this.history, this.settings); }

  private async evaluate(state: S, hash: string): Promise<Evaluation<S>> {
    this.ui.setPending(true);
    const bank = this.a.bank(state, this.settings);
    const res = await send<EvalResult>({ type: "evaluate", state, questions: toWire(bank) });
    const budget = await send<BudgetData>({ type: "budget.get", surface: this.a.surface });
    const verdict = decide(bank, res.answers, state, { interruptsUsed: budget.used, interruptBudget: this.settings.interruptBudgetPerDay, previous: this.previous, l0Flags: this.a.l0(state) });
    this.previous = verdict;
    return { hash, state, answers: res.answers, verdict, latencyMs: res.latencyMs, inputTokens: res.inputTokens, at: Date.now() };
  }

  private paint(ev: Evaluation<S>): void { if (!this.disposed) this.ui.setMeter(ev.verdict); }
  private onError(e: unknown): void { this.ui.setOffline((e as Error)?.message ?? String(e)); }

  private intercept(e: Event): void {
    if (this.bypassNext) { this.bypassNext = false; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    void this.gate();
  }

  private async gate(): Promise<void> {
    const s = this.state();
    if (!s) return this.release("sent", null, false);
    let ev: Evaluation<S>, cacheHit: boolean;
    try {
      this.ui.setPending(true);
      ({ result: ev, cacheHit } = await this.spec.verdictFor(s));
    } catch (e) {
      this.onError(e);
      if (this.settings.failMode === "open") return this.release("sent", null, false);
      this.ui.showConfirm("block", [{ id: "offline", p: 1, text: "Interlock can't reach Jev and is set to fail closed.", level: "block" }], {
        onSend: () => this.release("overrode_block", null, false),
        onCancel: () => {},
      });
      return;
    }
    this.ui.setMeter(ev.verdict);
    const v = ev.verdict;
    switch (v.level) {
      case "proceed":
      case "nudge":
        return this.release("sent", ev, cacheHit);
      case "hold":
        return this.ui.showHold(this.settings.holdSeconds, v.reasons, {
          onSendNow: () => this.release("sent_now_from_hold", ev, cacheHit),
          onTimeout: () => this.release("sent_after_hold", ev, cacheHit),
          onCancel: () => this.log("cancelled", ev, cacheHit),
        });
      case "confirm":
        void send({ type: "budget.spend", surface: this.a.surface });
        return this.ui.showConfirm("confirm", v.reasons, {
          onSend: () => this.release("overrode_confirm", ev, cacheHit),
          onCancel: () => this.log("cancelled", ev, cacheHit),
        });
      case "block":
        void send({ type: "budget.spend", surface: this.a.surface });
        return this.ui.showConfirm("block", v.reasons, {
          onSend: (why) => this.release("overrode_block", ev, cacheHit, why),
          onCancel: () => this.log("cancelled", ev, cacheHit),
        });
    }
  }

  /** Let the real send through: re-fire the native action with the bypass flag set. */
  private release(action: UserAction, ev: Evaluation<S> | null, cacheHit: boolean, note?: string): void {
    if (ev) this.log(action, ev, cacheHit, note);
    const addrs = ev ? this.a.recipients(ev.state) : [];
    if (addrs.length) void send({ type: "history.touch", addrs });
    this.bypassNext = true;
    const btn = this.a.findSendButton(this.root) ?? this.sendBtn;
    btn.click();
  }

  private log(action: UserAction, ev: Evaluation<S>, cacheHit: boolean, note?: string): void {
    const nouls: Record<string, number> = {};
    for (const [k, a] of Object.entries(ev.answers)) if (a.type === "noul") nouls[k] = Math.round(a.noul * 1000) / 1000;
    const rec: AuditRecord = {
      at: Date.now(), surface: this.a.surface, hash: ev.hash, level: ev.verdict.level, regret: ev.verdict.regret,
      reasons: ev.verdict.reasons.map((r) => ({ id: r.id, p: Math.round(r.p * 1000) / 1000 })),
      nouls, action, latencyMs: ev.latencyMs, inputTokens: ev.inputTokens, cacheHit,
    };
    if (note) rec.note = note;
    void send({ type: "log.append", record: rec });
  }

  dispose(): void {
    this.disposed = true;
    this.root.removeEventListener("input", this.onInput, true);
    this.root.removeEventListener("keydown", this.onKeydown, true);
    this.root.removeEventListener("click", this.onClick, true);
    this.ui.destroy();
  }
}

const live = new Map<HTMLElement, ComposeInterlock<unknown>>();
let settings: Settings = DEFAULT_SETTINGS;
let history: SenderHistory = { sentTo: {}, recentSends: [] };

async function boot(): Promise<void> {
  const adapter = adapterFor(location.hostname);
  if (!adapter) return;
  try {
    settings = await send<Settings>({ type: "settings.get" });
    history = await send<SenderHistory>({ type: "history.get" });
  } catch (e) {
    console.warn("[interlock] background unavailable", e);
  }
  const scan = () => {
    const roots = new Set(adapter.findRoots(document));
    for (const r of roots) {
      if (live.has(r)) continue;
      const btn = adapter.findSendButton(r);
      const body = adapter.findBody(r);
      if (!btn || !body) continue;
      live.set(r, new ComposeInterlock(adapter, r, btn, settings, history));
    }
    for (const [r, il] of live) if (!roots.has(r) || !r.isConnected) { il.dispose(); live.delete(r); }
  };
  let scanTimer: ReturnType<typeof setTimeout>;
  const mo = new MutationObserver(() => { clearTimeout(scanTimer); scanTimer = setTimeout(scan, 150); });
  mo.observe(document.body, { childList: true, subtree: true });
  scan();
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "sync" && changes.settings) settings = { ...DEFAULT_SETTINGS, ...(changes.settings.newValue as Partial<Settings>) };
    if (area === "local" && changes.history) history = changes.history.newValue as SenderHistory;
  });
}

void boot();
