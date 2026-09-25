import { chmodSync, createReadStream, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { execFileSync } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import type { Evaluation, Settings, Surface, UserAction, Verdict } from "../core/types.js";
import { readAudit } from "../node/audit.js";
import { loadSettings, saveSettings, configDir } from "../node/config.js";
import { record, runGate, type GateOutput } from "../node/gate.js";
import { findPack, loadPack, type LoadedPack } from "../pack/loader.js";
import { sensorFor } from "../sensors/index.js";
import { startProxy } from "../surfaces/agent/proxy.js";
import { compileGitPushState, parsePushStdin } from "../surfaces/git/compile.js";
import { createPaymentServer } from "../surfaces/payment/server.js";
import { compileShellState, isInteresting } from "../surfaces/shell/compile.js";
import { evalPack, formatReport } from "./eval.js";
import { runRecall, formatRecall } from "./recall.js";
import { BASH_INIT, PRE_PUSH, ZSH_INIT } from "./hooks.js";

const argv = process.argv.slice(2);
const cmd = argv[0];
const dim = (s: string) => (process.stderr.isTTY ? `\x1b[2m${s}\x1b[0m` : s);
const bold = (s: string) => (process.stderr.isTTY ? `\x1b[1m${s}\x1b[0m` : s);
const red = (s: string) => (process.stderr.isTTY ? `\x1b[31m${s}\x1b[0m` : s);
const yellow = (s: string) => (process.stderr.isTTY ? `\x1b[33m${s}\x1b[0m` : s);
const err = (s: string): void => { process.stderr.write(s + "\n"); };

function usage(): never {
  err(`interlock — a 100 ms judgment before irreversible actions. Policy = Question Packs; sensor = Jev or none.

  interlock config [--key K] [--base-url U] [--model M] [--fail-mode open|closed] [--budget N]
  interlock packs                            (list the packs the runtime can see)
  interlock eval <pack…> [--sensor jev|llm|none] [--json]   (run a pack's tests: pass/fail, calibration, latency, cost)
  interlock recall [--since 90d] [--mbox f] [--slack-export d] [--self me@x] [--json]
                                             (regret events in git/shell/audit history and exports; joined to decisions)
  interlock mcp [--task "…"] [--allow-override] [--pack agent] -- <mcp server command…>
  interlock shell -- "<command line>"        (exit 0 = run it, 1 = don't)
  interlock shell-init zsh|bash              (eval this in your rc file)
  interlock git-push <remote> <url>          (pre-push hook entry; refs on stdin)
  interlock install-hooks                    (writes .git/hooks/pre-push in the current repo)
  interlock payment-server [--port 8790]
  interlock log [--surface s] [--n 50]
  interlock allow "<command line>"           (run a shell command once without the gate, logged)

  --sensor overrides INTERLOCK_SENSOR; packs are looked up in INTERLOCK_PACKS, ~/.config/interlock/packs, then the built-ins.`);
  process.exit(2);
}

/** Where packs live: env override, user dir, then the packs/ shipped beside dist/. */
function packDirs(): string[] {
  const here = dirname(fileURLToPath(import.meta.url));
  const out = [process.env.INTERLOCK_PACKS, join(configDir(), "packs"), join(here, "..", "packs"), join(here, "..", "..", "packs")].filter((d): d is string => !!d && existsSync(d));
  return [...new Set(out)];
}
function pack(name: string): LoadedPack { return loadPack(findPack(name, packDirs())); }

function flag(name: string): string | undefined {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : undefined;
}

/** Print a verdict the way a shell user wants to read it: one line for a nudge, a short block otherwise. */
function printVerdict(v: Verdict, latencyMs: number, cacheable = false): void {
  const head = { proceed: "", nudge: yellow("interlock: "), hold: yellow("interlock hold: "), confirm: red("interlock: "), block: red("interlock BLOCKED: ") }[v.level];
  if (v.level === "nudge") return err(`${head}${v.reasons[0]?.text ?? ""} ${dim(`(${latencyMs} ms)`)}`);
  err(`${head}${v.reasons[0]?.text ?? ""}`);
  for (const r of v.reasons.slice(1, 4)) err(`  • ${r.text}`);
  for (const n of v.notes) err(dim(`  ${n}`));
  err(dim(`  ${latencyMs} ms${cacheable ? "" : ""}`));
}

/** Ask on the controlling terminal even when stdin is a pipe (git hooks). No terminal → "" → decline. */
function ttyQuestion(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (a: string) => { if (!settled) { settled = true; resolve(a); } };
    if (process.stdin.isTTY) {
      const rl = createInterface({ input: process.stdin, output: process.stderr, terminal: true });
      return rl.question(prompt, (a) => { rl.close(); done(a.trim()); });
    }
    const tty = createReadStream("/dev/tty");
    tty.on("error", () => { err(dim("  (no terminal to ask on — declining; use INTERLOCK=off to bypass)")); done(""); });
    tty.once("open", () => {
      const rl = createInterface({ input: tty, output: process.stderr, terminal: true });
      rl.question(prompt, (a) => { rl.close(); tty.destroy(); done(a.trim()); });
    });
  });
}

async function countdown(seconds: number): Promise<boolean> {
  if (!process.stderr.isTTY) return true;
  err(dim(`  continuing in ${seconds}s — Ctrl-C to abort`));
  let aborted = false;
  const onInt = () => { aborted = true; };
  process.once("SIGINT", onInt);
  for (let i = 0; i < seconds && !aborted; i++) await new Promise((r) => setTimeout(r, 1000));
  process.off("SIGINT", onInt);
  return !aborted;
}

/** Say once per process when no model is configured, so rules-only never passes for protection. */
function warnIfRulesOnly(sensorName: string): void {
  if (sensorName === "none" && !process.env.INTERLOCK_QUIET) err(dim("interlock: no sensor key configured — rules only. Set OPENROUTER_API_KEY or JEV_API_KEY, or INTERLOCK_QUIET=1 to hide this."));
}

/** Shared interactive verdict handling for shell and git. Returns the exit code. */
async function interactive<S>(surface: Surface, g: GateOutput<S>, holdSeconds: number, cap: number): Promise<number> {
  const ev: Evaluation<S> = g.evaluation;
  const v = ev.verdict;
  const meta = { pack: g.pack, sensor: g.sensor, actor: "human" as const, costUsd: g.costUsd, cap };
  const done = (a: UserAction, note?: string, code = 0) => { record(surface, ev, a, meta, note); return code; };
  const degraded = v.notes.find((n) => n.startsWith("degraded"));
  if (degraded && v.level === "proceed") err(dim(`interlock offline (${degraded.slice(10)}) — letting it through`));
  switch (v.level) {
    case "proceed": return done("allowed");
    case "nudge": printVerdict(v, ev.latencyMs); return done("allowed");
    case "hold": printVerdict(v, ev.latencyMs); return (await countdown(holdSeconds)) ? done("held") : done("cancelled", undefined, 1);
    case "confirm": {
      printVerdict(v, ev.latencyMs);
      const a = await ttyQuestion(bold("  Run anyway? [y/N] "));
      return /^y(es)?$/i.test(a) ? done("overrode_confirm") : done("cancelled", undefined, 1);
    }
    case "block": {
      printVerdict(v, ev.latencyMs);
      err(dim(`  To run regardless: INTERLOCK=off <command>   (logged)`));
      return done("blocked", undefined, 1);
    }
  }
}

function gitBranch(cwd: string): string | null {
  try {
    let dir = cwd;
    for (let i = 0; i < 12; i++) {
      const head = join(dir, ".git", "HEAD");
      if (existsSync(head)) { const m = readFileSync(head, "utf8").match(/ref: refs\/heads\/(.+)/); return m ? m[1]!.trim() : "(detached)"; }
      const parent = join(dir, "..");
      if (parent === dir) break;
      dir = parent;
    }
  } catch { /* not a repo */ }
  return null;
}

function kubeContext(): string | null {
  try {
    const p = process.env.KUBECONFIG?.split(":")[0] ?? join(homedir(), ".kube", "config");
    const m = readFileSync(p, "utf8").match(/^current-context:\s*(.+)$/m);
    return m ? m[1]!.trim().replace(/^["']|["']$/g, "") : null;
  } catch { return null; }
}

async function main(): Promise<number> {
  if (!cmd || cmd === "-h" || cmd === "--help") usage();
  const settings = loadSettings();

  if (cmd === "config") {
    const patch: Partial<Settings> = {};
    if (flag("--key")) patch.apiKey = flag("--key");
    if (flag("--base-url")) patch.baseUrl = flag("--base-url");
    if (flag("--model")) patch.model = flag("--model");
    if (flag("--fail-mode")) patch.failMode = flag("--fail-mode") as Settings["failMode"];
    if (flag("--budget")) patch.interruptBudgetPerDay = Number(flag("--budget"));
    const s = Object.keys(patch).length ? saveSettings(patch) : settings;
    err(`config: ${join(configDir(), "config.json")}`);
    err(JSON.stringify({ ...s, apiKey: s.apiKey ? s.apiKey.slice(0, 6) + "…" : "(none)" }, null, 2));
    return 0;
  }

  if (cmd === "packs") {
    for (const d of packDirs()) {
      for (const f of (await import("node:fs")).readdirSync(d).filter((f) => f.endsWith(".pack.yaml"))) {
        try { const p = loadPack(join(d, f)); process.stdout.write(`${p.name.padEnd(12)} v${p.version}  ${p.surface.padEnd(8)} ${p.questions.length} questions, ${Object.keys(p.l0).length} rules, ${p.tests.length} tests  ${dim(join(d, f))}\n`); }
        catch (e) { process.stdout.write(`${f.padEnd(12)} ${red("invalid")}: ${(e as Error).message}\n`); }
      }
    }
    return 0;
  }

  if (cmd === "eval") {
    const names = argv.slice(1).filter((a) => !a.startsWith("--") && a !== flag("--sensor"));
    if (!names.length) { err("eval: name at least one pack (see `interlock packs`)"); return 2; }
    const sensor = sensorFor(settings, flag("--sensor"));
    let failed = 0;
    const reports = [];
    for (const n of names) {
      const r = await evalPack(pack(n), sensor);
      reports.push(r);
      failed += r.failed;
      if (!argv.includes("--json")) err(formatReport(r, { color: !!process.stderr.isTTY }) + "\n");
    }
    if (argv.includes("--json")) process.stdout.write(JSON.stringify(reports, null, 2) + "\n");
    return failed ? 1 : 0;
  }

  if (cmd === "recall") {
    const r = await runRecall({ cwd: process.cwd(), since: flag("--since") ?? "90d", home: homedir(), mbox: flag("--mbox"), slackExport: flag("--slack-export"), self: flag("--self") });
    if (argv.includes("--json")) process.stdout.write(JSON.stringify(r, null, 2) + "\n");
    else process.stdout.write(formatRecall(r) + "\n");
    return 0;
  }

  if (cmd === "shell-init") {
    const sh = argv[1];
    if (sh === "zsh") process.stdout.write(ZSH_INIT);
    else if (sh === "bash") process.stdout.write(BASH_INIT);
    else { err("shell-init: zsh or bash"); return 2; }
    return 0;
  }

  if (cmd === "shell" || cmd === "allow") {
    const sep = argv.indexOf("--");
    const line = (sep >= 0 ? argv.slice(sep + 1) : argv.slice(1)).join(" ");
    if (!line.trim()) return 0;
    if (!isInteresting(line)) return 0; // ~0 ms: no network for ordinary commands
    const state = compileShellState({ command: line, cwd: process.cwd(), home: homedir(), env: process.env, gitBranch: gitBranch(process.cwd()), kubeContext: kubeContext() });
    const sensor = sensorFor(settings, flag("--sensor"));
    warnIfRulesOnly(sensor.name);
    const g = await runGate({ surface: "shell", state, pack: pack("shell"), sensor, l0Flags: state.l0_flags, settings });
    if (cmd === "allow") {
      record("shell", g.evaluation, "overridden", { pack: g.pack, sensor: g.sensor, actor: "human", costUsd: g.costUsd, cap: settings.interruptBudgetPerDay }, "interlock allow");
      err(dim("interlock: allowed once (logged)"));
      return 0;
    }
    return interactive("shell", g, 3, settings.interruptBudgetPerDay);
  }

  if (cmd === "git-push") {
    const remoteName = argv[1] ?? "origin", remoteUrl = argv[2] ?? "";
    let stdin = "";
    try { stdin = readFileSync(0, "utf8"); } catch { /* no refs */ }
    const refs = parsePushStdin(stdin);
    if (!refs.length) return 0;
    const state = compileGitPushState({ remoteName, remoteUrl, refs, cwd: process.cwd() });
    const sensor = sensorFor(settings, flag("--sensor"));
    warnIfRulesOnly(sensor.name);
    const g = await runGate({ surface: "git", state, pack: pack("git-push"), sensor, l0Flags: state.l0_flags, settings });
    return interactive("git", g, 5, settings.interruptBudgetPerDay);
  }

  if (cmd === "install-hooks") {
    let hooksDir: string;
    try { hooksDir = execFileSync("git", ["rev-parse", "--git-path", "hooks"], { encoding: "utf8" }).trim(); }
    catch { err("install-hooks: not inside a git repository"); return 1; }
    mkdirSync(hooksDir, { recursive: true });
    const p = join(hooksDir, "pre-push");
    if (existsSync(p) && !readFileSync(p, "utf8").includes("interlock")) { err(`install-hooks: ${p} exists and isn't ours; add \`exec interlock git-push "$@"\` to it yourself`); return 1; }
    writeFileSync(p, PRE_PUSH); chmodSync(p, 0o755);
    err(`installed ${p}`);
    err(`shell: add   eval "$(interlock shell-init zsh)"   (or bash) to your rc file`);
    return 0;
  }

  if (cmd === "mcp") {
    const sep = argv.indexOf("--");
    if (sep < 0 || !argv[sep + 1]) usage();
    const task = flag("--task") ?? process.env.INTERLOCK_TASK;
    const sensor = sensorFor(settings, flag("--sensor"));
    warnIfRulesOnly(sensor.name);
    startProxy({ command: argv[sep + 1]!, args: argv.slice(sep + 2), settings, task, pack: pack(flag("--pack") ?? "agent"), sensor, allowOverride: argv.includes("--allow-override") || process.env.INTERLOCK_ALLOW_OVERRIDE === "1" });
    return new Promise(() => { /* runs until the server exits */ });
  }

  if (cmd === "payment-server") {
    const port = Number(flag("--port") ?? 8790);
    createPaymentServer(settings, pack(flag("--pack") ?? "payment"), sensorFor(settings, flag("--sensor"))).listen(port, "127.0.0.1", () => err(`interlock payment gate on http://127.0.0.1:${port}  (POST /gate/payment; fail ${process.env.INTERLOCK_FAIL_MODE === "open" ? "open" : "closed"})`));
    return new Promise(() => { /* serves forever */ });
  }

  if (cmd === "log") {
    const n = Number(flag("--n") ?? 50), surface = flag("--surface");
    const rows = readAudit(2000).filter((r) => !surface || r.surface === surface).slice(-n);
    for (const r of rows) process.stdout.write(`${r.at}  ${r.surface.padEnd(7)} ${r.actor.padEnd(5)} ${r.level.padEnd(7)} ${String(r.regret).padEnd(4)} ${r.outcome.padEnd(16)} ${[...r.fired.map((id) => `${id}:${Math.round((r.nouls[id] ?? 0) * 100)}`), ...r.l0.map((f) => `l0:${f}`)].join(",")}  ${dim(`${r.latency_ms}ms $${r.cost_usd}`)}${r.note ? `  "${r.note}"` : ""}\n`);
    const ints = rows.filter((r) => r.level === "confirm" || r.level === "block");
    const acted = ints.filter((r) => r.outcome === "cancelled" || r.outcome === "blocked").length;
    const agents = rows.filter((r) => r.actor === "agent").length;
    err(dim(`${rows.length} decisions · ${ints.length} interrupts · ${acted} acted on · ${agents} by agents · $${rows.reduce((s, r) => s + r.cost_usd, 0).toFixed(4)} total`));
    return 0;
  }

  usage();
}

main().then((code) => process.exit(code), (e) => { err(`interlock: ${(e as Error).message}`); process.exit(loadSettings().failMode === "closed" ? 1 : 0); });
