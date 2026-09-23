/**
 * Agent tool-call surface. The state is already JSON; the compiler's job is truncation,
 * redaction of obvious secrets, and the derived facts Jev can't compute (repeat counts, spend hints).
 */
export interface ToolSchema { name: string; description?: string; inputSchema?: unknown }
export interface RecentCall { tool: string; ok: boolean | null; at: number; argsHead: string }

export interface AgentCallInput {
  tool: string;
  args: unknown;
  schema?: ToolSchema;
  task?: string;
  recent: RecentCall[];
  server?: string;
  client?: string;
}

export interface AgentState {
  action: "agent.tool_call";
  task: string | null;
  server: string | null;
  client: string | null;
  tool: { name: string; description: string | null; args: string; arg_keys: string[]; arg_chars: number };
  recent_calls: Array<{ tool: string; ok: boolean | null; argsHead: string }>;
  facts: {
    same_tool_called_in_last_5: number;
    same_args_as_a_recent_failed_call: boolean;
    args_mention_paths_outside_cwd: boolean;
    args_look_like_shell: boolean;
    tool_name_suggests_write: boolean;
    tool_name_suggests_delete_or_money: boolean;
  };
  l0_flags: string[];
}

const ARGS_MAX = 1200;
const SECRET_RE = /\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----/g;
const WRITE_RE = /\b(write|create|update|put|post|patch|set|edit|apply|run|exec|execute|send|push|commit|deploy|upload|insert)\b/i;
const DANGER_RE = /\b(delete|remove|drop|destroy|purge|wipe|reset|pay|transfer|charge|refund|withdraw|force|kill|terminate|revoke|grant|admin)\b/i;
const SHELL_RE = /(?:^|\s)(rm|sudo|curl|wget|bash|sh|chmod|chown|kubectl|terraform|aws|gcloud)\b|\|\s*sh\b|&&|\$\(/;

export function compileAgentState(input: AgentCallInput): AgentState {
  const raw = JSON.stringify(input.args ?? {});
  const argsStr = raw.replace(SECRET_RE, "<SECRET>");
  const argKeys = input.args && typeof input.args === "object" && !Array.isArray(input.args) ? Object.keys(input.args as object) : [];
  const recent = input.recent.slice(-10);
  const last5 = recent.slice(-5);
  const name = input.tool;
  const nameWords = name.replace(/[_\-.]+/g, " "); // "delete_repo" → "delete repo" so \b works
  const l0: string[] = [];
  if (SECRET_RE.test(raw)) l0.push("secret_in_args");
  if (/\b(rm\s+-rf\s+\/(?:\s|$)|DROP\s+DATABASE|mkfs\.|dd\s+if=)/i.test(raw)) l0.push("catastrophic_command_in_args");
  const failedSame = recent.some((r) => r.tool === name && r.ok === false && r.argsHead === argsStr.slice(0, 80));
  if (failedSame) l0.push("retrying_identical_failed_call");
  return {
    action: "agent.tool_call",
    task: input.task ?? null,
    server: input.server ?? null,
    client: input.client ?? null,
    tool: {
      name,
      description: input.schema?.description?.slice(0, 300) ?? null,
      args: argsStr.length > ARGS_MAX ? argsStr.slice(0, ARGS_MAX) + "…" : argsStr,
      arg_keys: argKeys,
      arg_chars: raw.length,
    },
    recent_calls: recent.map((r) => ({ tool: r.tool, ok: r.ok, argsHead: r.argsHead })),
    facts: {
      same_tool_called_in_last_5: last5.filter((r) => r.tool === name).length,
      same_args_as_a_recent_failed_call: failedSame,
      args_mention_paths_outside_cwd: /"(?:\/etc|\/usr|\/var|~\/\.ssh|\/root|C:\\\\Windows)/i.test(raw),
      args_look_like_shell: SHELL_RE.test(raw),
      tool_name_suggests_write: WRITE_RE.test(nameWords),
      tool_name_suggests_delete_or_money: DANGER_RE.test(nameWords) || DANGER_RE.test(argsStr.slice(0, 200)),
    },
    l0_flags: l0,
  };
}
