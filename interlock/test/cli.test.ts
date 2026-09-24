import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createPaymentServer } from "../src/surfaces/payment/server.js";
import { DEFAULT_SETTINGS } from "../src/core/types.js";
import { loadPack } from "../src/pack/loader.js";
import { jevSensor } from "../src/sensors/jev.js";
// @ts-expect-error plain ESM helper
import { startMock } from "../scripts/mock-jev.mjs";

let mock: { url: string; server: { close(): void } };
let home: string;
const CLI = join(process.cwd(), "dist", "cli.js");

beforeAll(async () => {
  mock = await startMock();
  home = mkdtempSync(join(tmpdir(), "interlock-cli-"));
  // always rebuild: these tests exercise the bundled CLI, and a stale dist/ is the classic false pass
  spawnSync("node", ["scripts/build.mjs"], { stdio: "ignore" });
  if (!existsSync(CLI)) throw new Error("build failed");
});
afterAll(() => mock.server.close());

// async on purpose: spawnSync would block the event loop that serves the in-process mock Jev
function run(args: string[], extraEnv: Record<string, string> = {}): Promise<{ status: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const p = spawn(process.execPath, [CLI, ...args], { env: { ...process.env, INTERLOCK_HOME: home, JEV_API_KEY: "test-key", JEV_BASE_URL: mock.url, ...extraEnv }, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "";
    p.stdout.on("data", (d) => (stdout += d));
    p.stderr.on("data", (d) => (stderr += d));
    p.on("close", (status) => resolve({ status, stdout, stderr }));
  });
}

describe("interlock shell (CLI)", () => {
  it("exits 0 instantly for an uninteresting command", async () => {
    const t0 = Date.now();
    const r = await run(["shell", "--", "ls -la"]);
    expect(r.status).toBe(0);
    expect(Date.now() - t0).toBeLessThan(1500);
    expect(r.stderr).toBe("");
  });
  it("lets a risky-but-quiet command through with no output", async () => {
    const r = await run(["shell", "--", "rm -rf build/"]);
    expect(r.status).toBe(0);
  });
  it("prints a nudge and still allows", async () => {
    const r = await run(["shell", "--", "rm -rf build/ # [[q:looks_like_a_slip=0.55]]"]);
    expect(r.status).toBe(0);
    expect(r.stderr).toMatch(/This might be a slip \(55%\)/);
  });
  it("confirm with no tty → declines", async () => {
    const r = await run(["shell", "--", "kubectl delete ns staging # [[q:destructive_on_shared_resource=0.8]]"]);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/This destroys something shared \(80%\)/);
  });
  it("L0 blocks without a network round trip", async () => {
    const r = await run(["shell", "--", "rm -rf /"], { JEV_BASE_URL: "http://127.0.0.1:9" });
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/BLOCKED/);
    expect(r.stderr).toMatch(/catastrophic command/);
  });
  it("logs everything to the audit file", async () => {
    await run(["shell", "--", "terraform apply # [[q:irreversible=0.9]]"]);
    const log = readFileSync(join(home, "audit.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(log.some((r) => r.surface === "shell" && r.level === "block" && r.actor === "human")).toBe(true);
    expect(log.some((r) => r.surface === "shell" && r.level === "confirm" && r.outcome === "cancelled")).toBe(true);
    const out = await run(["log", "--surface", "shell"]);
    expect(out.stdout).toMatch(/shell\s+human\s+block/);
  });
  it("shell-init emits the zsh widget and bash trap", async () => {
    expect((await run(["shell-init", "zsh"])).stdout).toMatch(/zle -N accept-line interlock-accept-line/);
    expect((await run(["shell-init", "bash"])).stdout).toMatch(/trap '__interlock_trap' DEBUG/);
  });
});

describe("interlock eval / packs / recall (CLI)", () => {
  it("lists packs and runs every pack's L0 cases under the none sensor", async () => {
    const ls = await run(["packs"]);
    expect(ls.stdout).toMatch(/agent\s+v1\s+agent/);
    expect(ls.stdout).toMatch(/git-push/);
    const r = await run(["eval", "agent", "shell", "git-push", "email", "slack", "payment", "--sensor", "none"]);
    expect(r.status).toBe(0);
    expect(r.stderr).toMatch(/agent@1\s+sensor=none\s+\d+ passed/);
    expect(r.stderr).toMatch(/skipped \(need a sensor\)/);
  });
  it("runs the model-dependent cases against the steerable mock and reports calibration", async () => {
    const r = await run(["eval", "agent", "--sensor", "jev", "--json"]);
    const [rep] = JSON.parse(r.stdout);
    expect(rep.skipped).toBe(0);
    expect(rep.cases.length).toBe(6);
    // the mock answers 0.04 to everything unless steered, so model-dependent 'fires' cases fail: that is the point of eval
    expect(rep.failed).toBeGreaterThan(0);
    expect(rep.cases.find((c: any) => c.name.startsWith("rm -rf")).pass).toBe(true);
    expect(rep.calibration.some((row: any) => row.id === "irreversible")).toBe(true);
    expect(rep.latency.p95).toBeGreaterThanOrEqual(0);
  });
  it("recall runs without a git repo or history and says so", async () => {
    const r = await run(["recall", "--since", "7d"]);
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/regret events in the last 7d/);
  });
});

describe("payment gate server", () => {
  it("returns a verdict, fails closed when Jev is down, and records decisions", async () => {
    process.env.INTERLOCK_HOME = home;
    const PAY = loadPack("packs/payment.pack.yaml");
    const srv = createPaymentServer({ ...DEFAULT_SETTINGS, apiKey: "test-key", baseUrl: mock.url }, PAY, jevSensor({ apiKey: "test-key", baseUrl: mock.url, model: "jev-latest" }));
    await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
    const port = (srv.address() as { port: number }).port;
    const post = (path: string, body: unknown) => fetch(`http://127.0.0.1:${port}${path}`, { method: "POST", body: JSON.stringify(body) }).then((r) => r.json() as Promise<any>);
    const routine = await post("/gate/payment", { amount: 1200, currency: "USD", payee: { name: "Acme", prior_payments: [{ amount: 1150, at: "2026-08-01" }] }, requester: { id: "a" }, approver: { id: "b" }, memo: "August retainer" });
    expect(routine.verdict).toBe("proceed");
    const bec = await post("/gate/payment", { id: "p2", amount: 48000, currency: "USD", payee: { name: "Acme", details_changed_at: new Date().toISOString(), prior_payments: [{ amount: 1150, at: "2026-08-01" }] }, requester: { id: "a" }, approver: { id: "b" }, request_channel: "email", request_text: "CEO needs this wired today, don't call [[q:bec_pattern=0.9]]" });
    expect(bec.verdict).toBe("block");
    expect(bec.l0_flags).toContain("payee_details_changed_recently");
    expect(bec.reasons[0].text).toMatch(/fraud pattern \(90%\)/);
    const dec = await post("/gate/payment/p2/decision", { action: "cancelled", note: "called vendor, confirmed fraud" });
    expect(dec.ok).toBe(true);
    srv.close();
    const down = createPaymentServer({ ...DEFAULT_SETTINGS, apiKey: "test-key", baseUrl: "http://127.0.0.1:9" }, PAY, jevSensor({ apiKey: "test-key", baseUrl: "http://127.0.0.1:9", model: "jev-latest", timeoutMs: 500 }));
    await new Promise<void>((r) => down.listen(0, "127.0.0.1", r));
    const p2 = (down.address() as { port: number }).port;
    const r = await fetch(`http://127.0.0.1:${p2}/gate/payment`, { method: "POST", body: JSON.stringify({ amount: 10, currency: "USD", payee: { name: "x" }, requester: { id: "a" } }) }).then((r) => r.json() as Promise<any>);
    expect(r.verdict).toBe("block");
    expect(r.degraded).toBe(true);
    down.close();
    const log = readFileSync(join(home, "audit.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(log.some((x) => x.surface === "payment" && x.outcome === "cancelled" && x.note?.includes("confirmed fraud"))).toBe(true);
  });
});
