import { effectiveBank } from "../core/bank.js";
import { compileEmailState } from "../core/compile.js";
import { toWire } from "../core/jev.js";
import { decide } from "../core/policy.js";
import { Speculator } from "../core/speculate.js";
import { DEFAULT_SETTINGS, type AuditRecord, type EmailState, type EvalResult, type Evaluation, type SenderHistory, type Settings, type UserAction, type Verdict } from "../core/types.js";
import { extractDraft, findComposeRoots, findSendButton, findBody, type ComposeCounters } from "./gmail.js";
import { send, type BudgetData } from "./messages.js";
import { InterlockUI } from "./ui.js";

/**
 * One Interlock per compose window. Lifecycle:
 *   keystroke → Speculator.onChange → (pause) compile → Jev → policy → meter
 *   Send click (captured) → Speculator.verdictFor → 0 ms on hash hit → ladder → proceed | hold | confirm | block
 */
class ComposeInterlock {
  private ui: InterlockUI;
  private spec: Speculator<EmailState, Evaluation>;
  private counters: ComposeCounters = { openedAt: Date.now(), keystrokes: 0, deletions: 0 };
  private previous: Verdict | undefined;
  private bypassNext = false;
  private offline = false;
  private disposed = false;
  private onInput = (e: Event) => {
    this.counters.keystrokes++;
    if (e instanceof InputEvent && e.inputType?.startsWith("delete")) this.counters.deletions++;
    this.spec.onChange();
  };
  private onKeydown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) this.intercept(e);
  };
  private onClick = (e: MouseEvent) => {
    const btn = findSendButton(this.root);
    if (btn && e.target instanceof Node && btn.contains(e.target)) this.intercept(e);
  };

  constructor(private root: HTMLElement, private sendBtn: HTMLElement, private settings: Settings, private history: SenderHistory) {
    this.ui = new InterlockUI(sendBtn);
    this.spec = new Speculator<EmailState, Evaluation>({
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

  private state(): EmailState | null {
    const raw = extractDraft(this.root, document, this.counters);
    if (!raw.recipients.length && !raw.bodyText.trim()) return null;
    return compileEmailState(raw, this.history, { redaction: this.settings.redaction });
  }

  private async evaluate(state: EmailState, hash: string): Promise<Evaluation> {
    this.ui.setPending(true);
    const bank = effectiveBank(this.settings, state);
    const res = await send<EvalResult>({ type: "evaluate", state, questions: toWire(bank) });
    const budget = await send<BudgetData>({ type: "budget.get" });
    const verdict = decide(bank, res.answers, state, {
      interruptsUsed: budget.used,
      interruptBudget: this.settings.interruptBudgetPerDay,
      previous: this.previous,
      l0Flags: state.l0_flags,
    });
    this.previous = verdict;
    this.offline = false;
    return { hash, state, answers: res.answers, verdict, latencyMs: res.latencyMs, inputTokens: res.inputTokens, at: Date.now() };
  }

  private paint(ev: Evaluation): void { if (!this.disposed) this.ui.setMeter(ev.verdict); }

  private onError(e: unknown): void {
    this.offline = true;
    this.ui.setOffline((e as Error)?.message ?? String(e));
  }

  private intercept(e: Event): void {
    if (this.bypassNext) { this.bypassNext = false; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    void this.gate();
  }

  private async gate(): Promise<void> {
    const s = this.state();
    if (!s) return this.release("sent", null, false);
    let ev: Evaluation, cacheHit: boolean;
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
        void send({ type: "budget.spend" });
        return this.ui.showConfirm("confirm", v.reasons, {
          onSend: () => this.release("overrode_confirm", ev, cacheHit),
          onCancel: () => this.log("cancelled", ev, cacheHit),
        });
      case "block":
        void send({ type: "budget.spend" });
        return this.ui.showConfirm("block", v.reasons, {
          onSend: () => this.release("overrode_block", ev, cacheHit),
          onCancel: () => this.log("cancelled", ev, cacheHit),
        });
    }
  }

  /** Let the real send through: re-fire the click with the bypass flag set. */
  private release(action: UserAction, ev: Evaluation | null, cacheHit: boolean): void {
    if (ev) this.log(action, ev, cacheHit);
    const addrs = ev ? ev.state.recipients.map((r) => r.addr) : extractDraft(this.root, document, this.counters).recipients.map((r) => r.addr);
    if (addrs.length && !addrs[0]!.startsWith("<")) void send({ type: "history.touch", addrs });
    this.bypassNext = true;
    const btn = findSendButton(this.root) ?? this.sendBtn;
    btn.click();
  }

  private log(action: UserAction, ev: Evaluation, cacheHit: boolean): void {
    const nouls: Record<string, number> = {};
    for (const [k, a] of Object.entries(ev.answers)) if (a.type === "noul") nouls[k] = Math.round(a.noul * 1000) / 1000;
    const rec: AuditRecord = {
      at: Date.now(), surface: "email", hash: ev.hash, level: ev.verdict.level, regret: ev.verdict.regret,
      reasons: ev.verdict.reasons.map((r) => ({ id: r.id, p: Math.round(r.p * 1000) / 1000 })),
      nouls, action, latencyMs: ev.latencyMs, inputTokens: ev.inputTokens, cacheHit,
    };
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

const live = new Map<HTMLElement, ComposeInterlock>();
let settings: Settings = DEFAULT_SETTINGS;
let history: SenderHistory = { sentTo: {}, recentSends: [] };

async function boot(): Promise<void> {
  try {
    settings = await send<Settings>({ type: "settings.get" });
    history = await send<SenderHistory>({ type: "history.get" });
  } catch (e) {
    console.warn("[interlock] background unavailable", e);
  }
  const scan = () => {
    const roots = new Set(findComposeRoots(document));
    for (const r of roots) {
      if (live.has(r)) continue;
      const btn = findSendButton(r);
      const body = findBody(r);
      if (!btn || !body) continue;
      live.set(r, new ComposeInterlock(r, btn, settings, history));
    }
    for (const [r, il] of live) if (!roots.has(r) || !r.isConnected) { il.dispose(); live.delete(r); }
  };
  const mo = new MutationObserver(() => { clearTimeout(scanTimer); scanTimer = setTimeout(scan, 150); });
  let scanTimer: ReturnType<typeof setTimeout>;
  mo.observe(document.body, { childList: true, subtree: true });
  scan();
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "sync" && changes.settings) settings = { ...DEFAULT_SETTINGS, ...(changes.settings.newValue as Partial<Settings>) };
    if (area === "local" && changes.history) history = changes.history.newValue as SenderHistory;
  });
}

void boot();
