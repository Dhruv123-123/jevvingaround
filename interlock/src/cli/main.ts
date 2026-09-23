import { chmodSync, createReadStream, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { createInterface } from "node:readline";
import type { Evaluation, Settings, Surface, UserAction, Verdict } from "../core/types.js";
import { readAudit } from "../node/audit.js";
import { loadSettings, saveSettings, configDir } from "../node/config.js";
import { record, runGate } from "../node/gate.js";
import { startProxy } from "../surfaces/agent/proxy.js";
import { compileGitPushState, parsePushStdin } from "../surfaces/git/compile.js";
import { GIT_BANK } from "../surfaces/git/bank.js";
import { createPaymentServer } from "../surfaces/payment/server.js";
import { compileShellState, isInteresting } from "../surfaces/shell/compile.js";
import { SHELL_BANK } from "../surfaces/shell/bank.js";
import { BASH_INIT, PRE_PUSH, ZSH_INIT } from "./hooks.js";

const argv = process.argv.slice(2);
const cmd = argv[0];
const dim = (s: string) => (process.stderr.isTTY ? `\x1b[2m${s}\x1b[0m` : s);
const bold = (s: string) => (process.stderr.isTTY ? `\x1b[1m${s}\x1b[0m` : s);
const red = (s: string) => (process.stderr.isTTY ? `\x1b[31m${s}\x1b[0m` : s);
const yellow = (s: string) => (process.stderr.isTTY ? `\x1b[33m${s}\x1b[0m` : s);
const err = (s: string): void => { process.stderr.write(s + "\n"); };

function usage(): never {
  err(`interlock — a 100 ms judgment before irreversible actions (sensor: TypeSafe Jev)

  interlock config [--key K] [--base-url U] [--model M] [--fail-mode open|closed] [--budget N]
  interlock mcp [--task "…"] [--allow-override] -- <mcp server command…>
  interlock shell -- "<command line>"        (exit 0 = run it, 1 = don't)
  interlock shell-init zsh|bash              (eval this in your rc file)
  interlock git-push <remote> <url>          (pre-push hook entry; refs on stdin)
  interlock install-hooks                    (writes .git/hooks/pre-push in the current repo)
  interlock payment-server [--port 8790]
  interlock log [--surface s] [--n 50]
  interlock allow "<command line>"           (run a shell command once without the gate, logged)`);
  process.exit(2);
}

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

/** Shared interactive verdict handling for shell and git. Returns the exit code. */
async function interactive<S>(surface: Surface, ev: Evaluation<S>, holdSeconds: number): Promise<number> {
  const v = ev.verdict;
  const done = (a: UserAction, note?: string, code = 0) => { record(surface, ev, a, note); return code; };
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
    if (cmd === "allow") {
      const { evaluation } = await runGate({ surface: "shell", state, bank: SHELL_BANK, l0Flags: state.l0_flags, settings });
      record("shell", evaluation, "overridden", "interlock allow");
      err(dim("interlock: allowed once (logged)"));
      return 0;
    }
    const { evaluation } = await runGate({ surface: "shell", state, bank: SHELL_BANK, l0Flags: state.l0_flags, settings });
    return interactive("shell", evaluation, 3);
  }

  if (cmd === "git-push") {
    const remoteName = argv[1] ?? "origin", remoteUrl = argv[2] ?? "";
    let stdin = "";
    try { stdin = readFileSync(0, "utf8"); } catch { /* no refs */ }
    const refs = parsePushStdin(stdin);
    if (!refs.length) return 0;
    const state = compileGitPushState({ remoteName, remoteUrl, refs, cwd: process.cwd() });
    const { evaluation } = await runGate({ surface: "git", state, bank: GIT_BANK, l0Flags: state.l0_flags, settings });
    return interactive("git", evaluation, 5);
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
    startProxy({ command: argv[sep + 1]!, args: argv.slice(sep + 2), settings, task, allowOverride: argv.includes("--allow-override") || process.env.INTERLOCK_ALLOW_OVERRIDE === "1" });
    return new Promise(() => { /* runs until the server exits */ });
  }

  if (cmd === "payment-server") {
    const port = Number(flag("--port") ?? 8790);
    createPaymentServer(settings).listen(port, "127.0.0.1", () => err(`interlock payment gate on http://127.0.0.1:${port}  (POST /gate/payment; fail ${process.env.INTERLOCK_FAIL_MODE === "open" ? "open" : "closed"})`));
    return new Promise(() => { /* serves forever */ });
  }

  if (cmd === "log") {
    const n = Number(flag("--n") ?? 50), surface = flag("--surface");
    const rows = readAudit(2000).filter((r) => !surface || r.surface === surface).slice(-n);
    for (const r of rows) process.stdout.write(`${new Date(r.at).toISOString()}  ${r.surface.padEnd(7)} ${r.level.padEnd(7)} ${String(r.regret).padEnd(4)} ${r.action.padEnd(16)} ${r.reasons.map((x) => `${x.id}:${Math.round(x.p * 100)}`).join(",")}${r.note ? `  "${r.note}"` : ""}\n`);
    const ints = rows.filter((r) => r.level === "confirm" || r.level === "block");
    const acted = ints.filter((r) => r.action === "cancelled" || r.action === "blocked").length;
    err(dim(`${rows.length} records · ${ints.length} interrupts · ${acted} acted on`));
    return 0;
  }

  usage();
}

main().then((code) => process.exit(code), (e) => { err(`interlock: ${(e as Error).message}`); process.exit(loadSettings().failMode === "closed" ? 1 : 0); });
