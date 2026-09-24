/**
 * MCP stdio proxy: `interlock mcp -- <server command...>`
 * Sits between an MCP client (Claude Code, Cursor, …) and any MCP server. Forwards everything
 * verbatim except `tools/call`, which goes through the gate first.
 *
 *   proceed / nudge → forwarded (nudge is logged)
 *   hold            → forwarded (a countdown means nothing to an agent) and logged as held
 *   confirm         → returned to the agent as an isError result asking it to re-issue the call
 *                     with `_interlock_justification`; the justification is logged, then forwarded
 *   block           → returned as an isError result; no override unless INTERLOCK_ALLOW_OVERRIDE=1
 */
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import type { Settings, UserAction, Verdict } from "../../core/types.js";
import { record, runGate, type GatePack } from "../../node/gate.js";
import type { Sensor } from "../../sensors/types.js";
import { compileAgentState, type RecentCall, type ToolSchema } from "./compile.js";

interface Rpc { jsonrpc: "2.0"; id?: number | string; method?: string; params?: Record<string, unknown>; result?: unknown; error?: unknown }

export interface ProxyOptions {
  command: string;
  args: string[];
  settings: Settings;
  task?: string;
  allowOverride?: boolean;
  pack: GatePack;
  sensor: Sensor;
  stdin?: NodeJS.ReadableStream;
  stdout?: NodeJS.WritableStream;
  stderr?: NodeJS.WritableStream;
}

export const JUSTIFICATION_KEY = "_interlock_justification";

export function startProxy(opts: ProxyOptions): { child: ChildProcess; close(): void } {
  const stdin = opts.stdin ?? process.stdin;
  const stdout = opts.stdout ?? process.stdout;
  const stderr = opts.stderr ?? process.stderr;
  const child = spawn(opts.command, opts.args, { stdio: ["pipe", "pipe", "inherit"] });
  const tools = new Map<string, ToolSchema>();
  const recent: RecentCall[] = [];
  const pendingCalls = new Map<number | string, { tool: string; argsHead: string }>();
  const pendingLists = new Set<number | string>();
  let serverName: string | undefined, clientName: string | undefined;
  let previous: Verdict | undefined;

  const toChild = (m: Rpc) => child.stdin!.write(JSON.stringify(m) + "\n");
  const toClient = (m: Rpc) => stdout.write(JSON.stringify(m) + "\n");
  const log = (s: string) => stderr.write(`[interlock] ${s}\n`);

  // client → server
  createInterface({ input: stdin }).on("line", (line) => {
    if (!line.trim()) return;
    let msg: Rpc;
    try { msg = JSON.parse(line); } catch { return void child.stdin!.write(line + "\n"); }
    if (msg.method === "initialize") clientName = (msg.params?.clientInfo as { name?: string } | undefined)?.name;
    if (msg.method === "tools/list" && msg.id !== undefined) pendingLists.add(msg.id);
    if (msg.method !== "tools/call" || msg.id === undefined) return void toChild(msg);
    void gateCall(msg);
  });

  async function gateCall(msg: Rpc): Promise<void> {
    const params = (msg.params ?? {}) as { name: string; arguments?: Record<string, unknown> };
    const args = { ...(params.arguments ?? {}) };
    const justification = typeof args[JUSTIFICATION_KEY] === "string" ? (args[JUSTIFICATION_KEY] as string) : undefined;
    delete args[JUSTIFICATION_KEY];
    const state = compileAgentState({ tool: params.name, args, schema: tools.get(params.name), task: opts.task, recent, server: serverName, client: clientName });
    const g = await runGate({ surface: "agent", state, pack: opts.pack, sensor: opts.sensor, l0Flags: state.l0_flags, settings: opts.settings, previous });
    const { evaluation: ev, degraded } = g;
    previous = ev.verdict;
    const v = ev.verdict;
    const meta = { pack: g.pack, sensor: g.sensor, actor: "agent" as const, costUsd: g.costUsd, cap: opts.settings.interruptBudgetPerDay };
    const forward = (action: UserAction, note?: string) => {
      record("agent", ev, action, meta, note);
      pendingCalls.set(msg.id!, { tool: params.name, argsHead: JSON.stringify(args).slice(0, 80) });
      toChild({ ...msg, params: { ...params, arguments: args } });
    };
    const refuse = (kind: "confirm" | "block") => {
      record("agent", ev, kind === "confirm" ? "asked" : "blocked", meta);
      const lines = v.reasons.slice(0, 4).map((r) => `- ${r.text}`).join("\n");
      const text = kind === "confirm"
        ? `INTERLOCK: this call needs confirmation before it runs.\n${lines}\nIf it is genuinely required for the task, call ${params.name} again with the same arguments plus "${JUSTIFICATION_KEY}": "<one sentence on why>". Otherwise choose a different step.`
        : `INTERLOCK: this call is blocked.\n${lines}\n${opts.allowOverride ? `Override is enabled: re-issue with "${JUSTIFICATION_KEY}" if you are certain.` : "No override is available in this session; stop and tell the user what you were trying to do."}`;
      toClient({ jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text }], isError: true } });
    };
    if (degraded) log(`degraded: ${ev.verdict.notes.join("; ")}`);
    switch (v.level) {
      case "proceed": return forward("allowed");
      case "nudge": log(`nudge ${params.name}: ${v.reasons[0]?.text}`); return forward("allowed");
      case "hold": log(`hold ${params.name}: ${v.reasons[0]?.text}`); return forward("held");
      case "confirm":
        if (justification) { log(`override ${params.name}: ${justification}`); return forward("overridden", justification); }
        return refuse("confirm");
      case "block":
        if (justification && opts.allowOverride) { log(`OVERRIDE BLOCK ${params.name}: ${justification}`); return forward("overridden", justification); }
        return refuse("block");
    }
  }

  // server → client
  createInterface({ input: child.stdout! }).on("line", (line) => {
    if (!line.trim()) return;
    let msg: Rpc;
    try { msg = JSON.parse(line); } catch { return void stdout.write(line + "\n"); }
    if (msg.id !== undefined && pendingLists.has(msg.id)) {
      pendingLists.delete(msg.id);
      const list = (msg.result as { tools?: ToolSchema[] } | undefined)?.tools ?? [];
      for (const t of list) tools.set(t.name, t);
    }
    if (msg.id !== undefined && pendingCalls.has(msg.id)) {
      const p = pendingCalls.get(msg.id)!;
      pendingCalls.delete(msg.id);
      const isErr = !!msg.error || !!(msg.result as { isError?: boolean } | undefined)?.isError;
      recent.push({ tool: p.tool, ok: !isErr, at: Date.now(), argsHead: p.argsHead });
      if (recent.length > 20) recent.shift();
    }
    if (msg.result && typeof msg.result === "object" && (msg.result as { serverInfo?: { name?: string } }).serverInfo) serverName = (msg.result as { serverInfo: { name?: string } }).serverInfo.name;
    stdout.write(line + "\n");
  });

  child.on("exit", (code) => { log(`server exited ${code}`); if (stdout === process.stdout) process.exit(code ?? 0); });
  return { child, close: () => child.kill() };
}
