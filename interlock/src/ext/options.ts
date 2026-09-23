import { EMAIL_BANK } from "../core/bank.js";
import { DEFAULT_SETTINGS, type AuditRecord, type QuestionDef, type Settings } from "../core/types.js";
import { send } from "./messages.js";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const LEVELS = ["nudge", "hold", "confirm", "block"] as const;

let settings: Settings = DEFAULT_SETTINGS;

function renderBank(): void {
  const tb = $("bank").querySelector("tbody")!;
  tb.innerHTML = "";
  const all: QuestionDef[] = [...EMAIL_BANK.filter((q) => q.type === "noul"), ...settings.extraQuestions];
  for (const q of all) {
    const t = { ...q.thresholds, ...settings.thresholdOverrides[q.id] };
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><code>${q.id}</code>${q.origin && q.origin !== "builtin" ? `<span class="tag">${q.origin}</span>` : ""}</td>
      <td class="muted" style="max-width:320px">${esc(q.instructions)}</td>
      ${LEVELS.map((l) => `<td><input type="number" min="0" max="1" step="0.05" data-q="${q.id}" data-l="${l}" value="${t[l] ?? ""}"></td>`).join("")}
      <td><input type="checkbox" data-on="${q.id}" ${settings.disabledQuestions.includes(q.id) ? "" : "checked"}></td>`;
    tb.appendChild(tr);
  }
}

function readBank(): void {
  const overrides: Settings["thresholdOverrides"] = {};
  for (const inp of document.querySelectorAll<HTMLInputElement>("input[data-q]")) {
    const id = inp.dataset.q!, l = inp.dataset.l as (typeof LEVELS)[number];
    const base = EMAIL_BANK.find((q) => q.id === id)?.thresholds?.[l];
    const v = inp.value === "" ? undefined : Number(inp.value);
    if (v !== base) (overrides[id] ??= {})![l] = v;
  }
  settings.thresholdOverrides = overrides;
  settings.disabledQuestions = [...document.querySelectorAll<HTMLInputElement>("input[data-on]")].filter((i) => !i.checked).map((i) => i.dataset.on!);
}

function renderForm(): void {
  $<HTMLInputElement>("apiKey").value = settings.apiKey;
  const sel = $<HTMLSelectElement>("baseUrl");
  const known = [...sel.options].some((o) => o.value === settings.baseUrl);
  sel.value = known ? settings.baseUrl : "custom";
  $<HTMLInputElement>("baseUrlCustom").style.display = known ? "none" : "";
  $<HTMLInputElement>("baseUrlCustom").value = known ? "" : settings.baseUrl;
  $<HTMLInputElement>("model").value = settings.model;
  $<HTMLSelectElement>("redaction").value = settings.redaction;
  $<HTMLInputElement>("interruptBudgetPerDay").value = String(settings.interruptBudgetPerDay);
  $<HTMLInputElement>("holdSeconds").value = String(settings.holdSeconds);
  $<HTMLInputElement>("debounceMs").value = String(settings.debounceMs);
  $<HTMLSelectElement>("failMode").value = settings.failMode;
  renderBank();
}

function readForm(): void {
  settings.apiKey = $<HTMLInputElement>("apiKey").value.trim();
  const sel = $<HTMLSelectElement>("baseUrl").value;
  settings.baseUrl = sel === "custom" ? $<HTMLInputElement>("baseUrlCustom").value.trim() : sel;
  settings.model = $<HTMLInputElement>("model").value.trim() || "jev-latest";
  settings.redaction = $<HTMLSelectElement>("redaction").value as Settings["redaction"];
  settings.interruptBudgetPerDay = Number($<HTMLInputElement>("interruptBudgetPerDay").value);
  settings.holdSeconds = Number($<HTMLInputElement>("holdSeconds").value);
  settings.debounceMs = Number($<HTMLInputElement>("debounceMs").value);
  settings.failMode = $<HTMLSelectElement>("failMode").value as Settings["failMode"];
  readBank();
}

async function refreshLog(): Promise<void> {
  const log = await send<AuditRecord[]>({ type: "log.list" });
  const tb = $("log").querySelector("tbody")!;
  tb.innerHTML = "";
  for (const r of [...log].reverse().slice(0, 50)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${new Date(r.at).toLocaleString()}</td><td>${r.level}</td><td>${r.regret}</td><td>${r.action}</td>
      <td>${r.reasons.map((x) => `${x.id} ${Math.round(x.p * 100)}%`).join(", ")}</td><td>${r.latencyMs}</td><td>${r.inputTokens}</td><td>${r.cacheHit ? "hit" : "miss"}</td>`;
    tb.appendChild(tr);
  }
  const interrupts = log.filter((r) => r.level === "confirm" || r.level === "block");
  const accepted = interrupts.filter((r) => r.action === "cancelled" || r.action === "edited").length;
  const hits = log.filter((r) => r.cacheHit).length;
  const lat = log.filter((r) => !r.cacheHit).map((r) => r.latencyMs).sort((a, b) => a - b);
  const p = (q: number) => (lat.length ? lat[Math.min(lat.length - 1, Math.floor(q * lat.length))] : "–");
  $("stats").textContent = `${log.length} sends · ${interrupts.length} interrupts, ${accepted} acted on (${interrupts.length ? Math.round((100 * accepted) / interrupts.length) : 0}% precision proxy) · cache hit ${log.length ? Math.round((100 * hits) / log.length) : 0}% · miss latency p50 ${p(0.5)} p95 ${p(0.95)} ms`;
}

async function main(): Promise<void> {
  settings = await send<Settings>({ type: "settings.get" });
  renderForm();
  await refreshLog();

  $("baseUrl").addEventListener("change", () => { $<HTMLInputElement>("baseUrlCustom").style.display = $<HTMLSelectElement>("baseUrl").value === "custom" ? "" : "none"; });
  $("save").addEventListener("click", async () => {
    readForm();
    settings = await send<Settings>({ type: "settings.set", patch: settings });
    $("saveOut").textContent = " saved";
    setTimeout(() => ($("saveOut").textContent = ""), 1500);
  });
  $("test").addEventListener("click", async () => {
    readForm();
    await send({ type: "settings.set", patch: settings });
    const out = $("testOut");
    out.textContent = "…";
    const t0 = performance.now();
    try {
      const r = await send<{ latencyMs: number; inputTokens: number; model: string }>({
        type: "evaluate",
        state: { text: "ping" },
        questions: { ok: { type: "noul", instructions: "Is the text 'ping'?", criteria: { true: "yes", false: "no" } } },
      });
      out.className = "ok";
      out.textContent = `ok — ${r.model}, ${r.latencyMs} ms model / ${Math.round(performance.now() - t0)} ms end to end, ${r.inputTokens} tokens`;
    } catch (e) {
      out.className = "err";
      out.textContent = (e as Error).message;
    }
  });
  $("addQ").addEventListener("click", () => {
    const id = $<HTMLInputElement>("qId").value.trim();
    if (!/^[a-z][a-z0-9_]{2,40}$/.test(id)) return alert("ID must be snake_case");
    if ([...EMAIL_BANK, ...settings.extraQuestions].some((q) => q.id === id)) return alert("ID already exists");
    settings.extraQuestions.push({
      id, type: "noul", origin: "user",
      instructions: $<HTMLTextAreaElement>("qInstr").value.trim(),
      criteria: { true: $<HTMLInputElement>("qTrue").value.trim(), false: $<HTMLInputElement>("qFalse").value.trim() },
      thresholds: { nudge: 0.5, confirm: 0.75 },
      reason: $<HTMLInputElement>("qReason").value.trim() || `${id.replace(/_/g, " ")} ({p}%)`,
      weight: 1,
    });
    renderBank();
  });
  $("refreshLog").addEventListener("click", () => void refreshLog());
  $("clearLog").addEventListener("click", async () => { await send({ type: "log.clear" }); await refreshLog(); });
  $("exportLog").addEventListener("click", async () => {
    const log = await send<AuditRecord[]>({ type: "log.list" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(log, null, 2)], { type: "application/json" }));
    a.download = `interlock-log-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
  });
}

function esc(s: string): string { return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!); }
void main();
