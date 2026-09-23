import type { Reason, Verdict, VerdictLevel } from "../core/types.js";

const CSS = `
:host { all: initial; font: 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #202124; }
* { box-sizing: border-box; }
.pill { display:inline-flex; align-items:center; gap:6px; height:24px; padding:0 9px; margin-left:8px; border-radius:12px;
  background:#f1f3f4; color:#3c4043; cursor:default; white-space:nowrap; user-select:none; vertical-align:middle; border:1px solid transparent; }
.pill .dot { width:8px; height:8px; border-radius:50%; background:#9aa0a6; transition: background .2s; }
.pill[data-level="proceed"] .dot { background:#34a853; }
.pill[data-level="nudge"] .dot { background:#fbbc04; }
.pill[data-level="hold"] .dot { background:#f29900; }
.pill[data-level="confirm"] .dot { background:#ea4335; }
.pill[data-level="block"] .dot { background:#c5221f; }
.pill[data-pending="true"] .dot { animation: pulse 1s infinite; }
.pill[data-offline="true"] { border-color:#dadce0; color:#80868b; }
@keyframes pulse { 0%,100%{opacity:.35} 50%{opacity:1} }
.card { position:fixed; z-index:2147483647; width:360px; max-width:calc(100vw - 32px); background:#fff; border-radius:10px;
  box-shadow:0 8px 28px rgba(0,0,0,.28); padding:14px 16px; }
.card h4 { margin:0 0 8px; font-size:13px; font-weight:600; }
.card ul { margin:0 0 12px; padding-left:18px; }
.card li { margin:3px 0; }
.card li[data-level="confirm"], .card li[data-level="block"] { font-weight:600; }
.row { display:flex; gap:8px; justify-content:flex-end; align-items:center; }
.row .spacer { flex:1; color:#5f6368; font-size:11px; }
button { font:inherit; border-radius:6px; padding:6px 12px; border:1px solid #dadce0; background:#fff; cursor:pointer; }
button.primary { background:#1a73e8; border-color:#1a73e8; color:#fff; }
button.danger { background:#d93025; border-color:#d93025; color:#fff; }
.bar { height:4px; background:#e8eaed; border-radius:2px; overflow:hidden; margin:8px 0 10px; }
.bar > div { height:100%; background:#f29900; transition: width .25s linear; }
.override { font-size:11px; color:#5f6368; }
.override input { width:100%; margin-top:6px; font:inherit; padding:5px 7px; border:1px solid #dadce0; border-radius:4px; }
`;

const LABEL: Record<VerdictLevel, string> = {
  proceed: "Looks fine",
  nudge: "Worth a glance",
  hold: "Holding briefly",
  confirm: "Check before sending",
  block: "Blocked",
};

export interface HoldHandlers { onSendNow(): void; onCancel(): void; onTimeout(): void }
export interface ConfirmHandlers { onSend(justification?: string): void; onCancel(): void }

export class InterlockUI {
  private host: HTMLElement;
  private shadow: ShadowRoot;
  private pill: HTMLElement;
  private card: HTMLElement | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private anchor: HTMLElement) {
    this.host = document.createElement("span");
    this.host.setAttribute("data-interlock", "host");
    this.shadow = this.host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    this.shadow.appendChild(style);
    this.pill = document.createElement("span");
    this.pill.className = "pill";
    this.pill.setAttribute("data-testid", "interlock-pill");
    this.pill.innerHTML = `<span class="dot"></span><span class="txt">Interlock</span>`;
    this.shadow.appendChild(this.pill);
    anchor.insertAdjacentElement("afterend", this.host);
  }

  setPending(p: boolean): void { this.pill.setAttribute("data-pending", String(p)); }

  setOffline(msg: string): void {
    this.pill.setAttribute("data-offline", "true");
    this.pill.removeAttribute("data-level");
    this.txt(`Interlock offline`);
    this.pill.title = msg;
  }

  setMeter(v: Verdict | null): void {
    this.pill.removeAttribute("data-offline");
    this.setPending(false);
    if (!v) { this.pill.removeAttribute("data-level"); this.txt("Interlock"); this.pill.title = ""; return; }
    this.pill.setAttribute("data-level", v.level);
    this.pill.setAttribute("data-regret", String(v.regret));
    const top = v.reasons[0];
    this.txt(v.level === "proceed" ? LABEL.proceed : (top?.text ?? LABEL[v.level]));
    this.pill.title = v.reasons.map((r) => `• ${r.text}`).join("\n") || "No concerns";
  }

  private txt(s: string): void { (this.pill.querySelector(".txt") as HTMLElement).textContent = s; }

  private openCard(): HTMLElement {
    this.closeCard();
    const c = document.createElement("div");
    c.className = "card";
    c.setAttribute("data-testid", "interlock-card");
    const r = this.anchor.getBoundingClientRect();
    const top = Math.max(8, r.top - 8);
    c.style.left = `${Math.max(8, Math.min(window.innerWidth - 376, r.left))}px`;
    c.style.bottom = `${Math.max(8, window.innerHeight - top)}px`;
    this.shadow.appendChild(c);
    this.card = c;
    return c;
  }

  closeCard(): void {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    this.card?.remove();
    this.card = null;
  }

  private list(reasons: Reason[]): string {
    return `<ul>${reasons.slice(0, 4).map((r) => `<li data-level="${r.level}">${esc(r.text)}</li>`).join("")}</ul>`;
  }

  showHold(seconds: number, reasons: Reason[], h: HoldHandlers): void {
    const c = this.openCard();
    c.setAttribute("data-kind", "hold");
    c.innerHTML = `<h4>Sending in <span class="n">${seconds}</span>s</h4>${this.list(reasons)}
      <div class="bar"><div style="width:100%"></div></div>
      <div class="row"><span class="spacer">Edit the draft to cancel.</span>
        <button data-act="cancel">Cancel</button><button class="primary" data-act="now">Send now</button></div>`;
    const n = c.querySelector(".n") as HTMLElement;
    const bar = c.querySelector(".bar > div") as HTMLElement;
    let left = seconds;
    this.timer = setInterval(() => {
      left -= 1;
      n.textContent = String(left);
      bar.style.width = `${(left / seconds) * 100}%`;
      if (left <= 0) { this.closeCard(); h.onTimeout(); }
    }, 1000);
    c.querySelector('[data-act="now"]')!.addEventListener("click", () => { this.closeCard(); h.onSendNow(); });
    c.querySelector('[data-act="cancel"]')!.addEventListener("click", () => { this.closeCard(); h.onCancel(); });
  }

  showConfirm(kind: "confirm" | "block", reasons: Reason[], h: ConfirmHandlers): void {
    const c = this.openCard();
    c.setAttribute("data-kind", kind);
    const block = kind === "block";
    c.innerHTML = `<h4>${block ? "Interlock blocked this send" : "Send anyway?"}</h4>${this.list(reasons)}
      ${block ? `<div class="override">To send regardless, say why (this is logged):<input data-role="why" placeholder="e.g. recipient confirmed by phone"></div>` : ""}
      <div class="row"><span class="spacer"></span>
        <button data-act="cancel" class="${block ? "primary" : ""}">Go back</button>
        <button data-act="send" class="${block ? "danger" : "primary"}" ${block ? "disabled" : ""}>${block ? "Override & send" : "Send anyway"}</button></div>`;
    const sendBtn = c.querySelector('[data-act="send"]') as HTMLButtonElement;
    const why = c.querySelector<HTMLInputElement>('[data-role="why"]');
    why?.addEventListener("input", () => { sendBtn.disabled = why.value.trim().length < 4; });
    sendBtn.addEventListener("click", () => { this.closeCard(); h.onSend(why?.value.trim()); });
    c.querySelector('[data-act="cancel"]')!.addEventListener("click", () => { this.closeCard(); h.onCancel(); });
    (c.querySelector('[data-act="cancel"]') as HTMLElement).focus();
  }

  destroy(): void { this.closeCard(); this.host.remove(); }
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
