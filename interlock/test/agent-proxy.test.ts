import { PassThrough } from "node:stream";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { startProxy, JUSTIFICATION_KEY } from "../src/surfaces/agent/proxy.js";
import { compileAgentState } from "../src/surfaces/agent/compile.js";
import { DEFAULT_SETTINGS, type Settings } from "../src/core/types.js";
// @ts-expect-error plain ESM helper
import { startMock } from "../scripts/mock-jev.mjs";

let mock: { url: string; server: { close(): void } };
let home: string;
beforeAll(async () => {
  mock = await startMock();
  home = mkdtempSync(join(tmpdir(), "interlock-"));
  process.env.INTERLOCK_HOME = home;
});
afterAll(() => mock.server.close());

function harness(settings: Partial<Settings> = {}, opts: { allowOverride?: boolean; task?: string } = {}) {
  const stdin = new PassThrough();
  const stdout = new PassThrough();
  const stderr = new PassThrough();
  const errLines: string[] = [];
  stderr.on("data", (d) => errLines.push(String(d)));
  const lines: unknown[] = [];
  const waiters: Array<(m: unknown) => void> = [];
  let buf = "";
  stdout.on("data", (d) => {
    buf += String(d);
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const l = buf.slice(0, i); buf = buf.slice(i + 1);
      if (!l.trim()) continue;
      const m = JSON.parse(l);
      const w = waiters.shift();
      w ? w(m) : lines.push(m);
    }
  });
  const next = () => new Promise<any>((r) => (lines.length ? r(lines.shift()) : waiters.push(r)));
  const proxy = startProxy({
    command: process.execPath, args: ["test/fixtures/fake-mcp-server.mjs"],
    settings: { ...DEFAULT_SETTINGS, apiKey: "test-key", baseUrl: mock.url, ...settings },
    stdin, stdout, stderr, allowOverride: opts.allowOverride, task: opts.task ?? "Read the README and summarise it",
  });
  let id = 0;
  const send = (method: string, params?: unknown) => { const m = { jsonrpc: "2.0", id: ++id, method, params }; stdin.write(JSON.stringify(m) + "\n"); return id; };
  return { send, next, errLines, close: () => proxy.close() };
}

describe("MCP proxy", () => {
  it("forwards initialize / tools/list and lets a benign call through", async () => {
    const h = harness();
    h.send("initialize", { clientInfo: { name: "test-client" } });
    expect((await h.next()).result.serverInfo.name).toBe("fake-server");
    h.send("tools/list");
    expect((await h.next()).result.tools.map((t: any) => t.name)).toContain("read_file");
    h.send("tools/call", { name: "read_file", arguments: { path: "README.md" } });
    const r = await h.next();
    expect(r.result.isError).toBeUndefined();
    expect(r.result.content[0].text).toBe('ok:read_file:{"path":"README.md"}');
    h.close();
  });

  it("returns a confirm to the agent, then forwards on re-issue with a justification (stripped from args)", async () => {
    const h = harness();
    h.send("tools/call", { name: "send_email", arguments: { to: "x@y.com", body: "[[q:irreversible=0.9]]" } });
    const r1 = await h.next();
    expect(r1.result.isError).toBe(true);
    expect(r1.result.content[0].text).toMatch(/needs confirmation/);
    expect(r1.result.content[0].text).toMatch(/This is irreversible \(90%\)/);
    expect(r1.result.content[0].text).toContain(JUSTIFICATION_KEY);
    h.send("tools/call", { name: "send_email", arguments: { to: "x@y.com", body: "[[q:irreversible=0.9]]", [JUSTIFICATION_KEY]: "user asked for this email explicitly" } });
    const r2 = await h.next();
    expect(r2.result.isError).toBeUndefined();
    expect(r2.result.content[0].text).not.toContain(JUSTIFICATION_KEY);
    expect(h.errLines.join("")).toMatch(/override send_email: user asked/);
    h.close();
  });

  it("blocks and refuses an override unless enabled", async () => {
    const h = harness();
    const args = { name: "prod-db", note: "[[q:escalates_permissions=0.95]]", [JUSTIFICATION_KEY]: "trust me" };
    h.send("tools/call", { name: "delete_repo", arguments: args });
    const r = await h.next();
    expect(r.result.isError).toBe(true);
    expect(r.result.content[0].text).toMatch(/blocked/);
    expect(r.result.content[0].text).toMatch(/No override is available/);
    h.close();
    const h2 = harness({}, { allowOverride: true });
    h2.send("tools/call", { name: "delete_repo", arguments: args });
    expect((await h2.next()).result.isError).toBeUndefined();
    h2.close();
  });

  it("L0 blocks a catastrophic command without asking the model", async () => {
    const h = harness();
    h.send("tools/call", { name: "run_shell", arguments: { cmd: "rm -rf / --no-preserve-root" } });
    const r = await h.next();
    expect(r.result.isError).toBe(true);
    expect(r.result.content[0].text).toMatch(/Blocked by rule: catastrophic command in args/);
    h.close();
  });

  it("fails open with a degraded note when there is no key", async () => {
    const h = harness({ apiKey: "" });
    h.send("tools/call", { name: "read_file", arguments: { path: "a" } });
    expect((await h.next()).result.content[0].text).toMatch(/^ok:read_file/);
    expect(h.errLines.join("")).toMatch(/degraded: .*no api key/);
    h.close();
  });

  it("fails closed when configured", async () => {
    const h = harness({ apiKey: "", failMode: "closed" });
    h.send("tools/call", { name: "read_file", arguments: { path: "a" } });
    const r = await h.next();
    expect(r.result.isError).toBe(true);
    expect(r.result.content[0].text).toMatch(/fail closed/);
    h.close();
  });

  it("writes an audit trail with the surface and noul vector", () => {
    const log = readFileSync(join(home, "audit.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(log.length).toBeGreaterThanOrEqual(5);
    expect(log.every((r) => r.surface === "agent")).toBe(true);
    expect(log.some((r) => r.action === "overridden" && r.note?.startsWith("user asked"))).toBe(true);
    expect(log.some((r) => r.action === "blocked")).toBe(true);
    expect(Object.keys(log[0].nouls)).toContain("irreversible");
  });
});

describe("compileAgentState", () => {
  it("derives loop and danger facts and redacts secrets in args", () => {
    const recent = [{ tool: "curl", ok: false, at: 1, argsHead: '{"url":"http://x"}' }, { tool: "curl", ok: false, at: 2, argsHead: '{"url":"http://x"}' }];
    const s = compileAgentState({ tool: "curl", args: { url: "http://x", token: "AKIAIOSFODNN7EXAMPLE" }, recent, task: "t" });
    expect(s.facts.same_tool_called_in_last_5).toBe(2);
    expect(s.facts.args_look_like_shell).toBe(false);
    expect(s.tool.args).toContain("<SECRET>");
    expect(s.tool.args).not.toContain("AKIAIOSFODNN7EXAMPLE");
    expect(s.l0_flags).toContain("secret_in_args");
    const t = compileAgentState({ tool: "delete_repo", args: { name: "x" }, recent: [] });
    expect(t.facts.tool_name_suggests_delete_or_money).toBe(true);
  });
});
