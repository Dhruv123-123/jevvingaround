// Minimal MCP-ish stdio server: initialize, tools/list, tools/call (echo; fails when args.fail is true).
import { createInterface } from "node:readline";
const tools = [
  { name: "read_file", description: "Read a file from disk", inputSchema: { type: "object", properties: { path: { type: "string" } } } },
  { name: "delete_repo", description: "Permanently delete a repository", inputSchema: { type: "object", properties: { name: { type: "string" } } } },
  { name: "send_email", description: "Send an email", inputSchema: { type: "object", properties: { to: { type: "string" }, body: { type: "string" } } } },
];
const out = (m) => process.stdout.write(JSON.stringify(m) + "\n");
createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.trim()) return;
  const msg = JSON.parse(line);
  if (msg.method === "initialize") return out({ jsonrpc: "2.0", id: msg.id, result: { protocolVersion: "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "fake-server", version: "0" } } });
  if (msg.method === "tools/list") return out({ jsonrpc: "2.0", id: msg.id, result: { tools } });
  if (msg.method === "tools/call") {
    const a = msg.params.arguments ?? {};
    if (a.fail) return out({ jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: "boom" }], isError: true } });
    return out({ jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: `ok:${msg.params.name}:${JSON.stringify(a)}` }] } });
  }
  if (msg.id !== undefined) out({ jsonrpc: "2.0", id: msg.id, result: {} });
});
