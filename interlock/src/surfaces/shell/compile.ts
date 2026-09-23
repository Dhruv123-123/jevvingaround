/** Shell surface: one command line about to run. Cheap prefilter first; Jev only for risky verbs. */
export interface ShellInput {
  command: string;
  cwd: string;
  home: string;
  env: Record<string, string | undefined>;
  gitBranch?: string | null;
  kubeContext?: string | null;
  now?: number;
}

export interface ShellState {
  action: "shell.command";
  command: string;
  argv0: string;
  subcommand: string | null;
  cwd: string;
  git_branch: string | null;
  kube_context: string | null;
  aws_profile: string | null;
  is_root: boolean;
  local_time: string;
  facts: {
    has_force_flag: boolean;
    has_recursive_flag: boolean;
    targets_root_or_home: boolean;
    mentions_prod: boolean;
    pipes_remote_to_shell: boolean;
    uses_sudo: boolean;
    dry_run_available: boolean;
    dry_run_used: boolean;
    glob_or_wildcard: boolean;
    context_mentions_prod: boolean;
  };
  l0_flags: string[];
}

/** Verbs worth a network round trip. Everything else exits in ~0 ms with no call. */
const RISKY = [
  /(^|[;&|]\s*)(sudo\s+)?rm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+|--recursive|--force)/,
  /(^|[;&|]\s*)(sudo\s+)?(mv|cp)\s+.*\s\/(?:\s|$)/,
  // plain `git push` is the pre-push hook's job; the shell only cares about force pushes
  /\bgit\s+(push\b.*(\s-f\b|--force|\s\+\S)|reset\s+--hard|clean\s+-[a-z]*f|branch\s+-D|checkout\s+--\s+\.|restore\s+\.|stash\s+drop|rebase|filter-branch)\b/,
  /\bkubectl\s+(delete|apply|scale|rollout|drain|cordon|exec|patch|replace|edit)\b/,
  /\bhelm\s+(uninstall|upgrade|rollback|delete|install)\b/,
  /\bterraform\s+(apply|destroy|import|state\s+(rm|mv|push))\b/,
  /\b(aws|gcloud|az)\s+\S+\s+(delete|terminate|remove|put|update|rm|destroy|stop)\b/,
  /\bdocker\s+(rm|rmi|system\s+prune|volume\s+(rm|prune)|compose\s+down\s+.*-v)\b/,
  /\b(psql|mysql|mongosh?|sqlite3|redis-cli)\b.*\s(-c|-e|--command|--eval|FLUSHALL|flushall)\b/,
  /\b(DROP|TRUNCATE|DELETE\s+FROM|ALTER)\s+(TABLE|DATABASE|SCHEMA|INDEX)?/i,
  /\b(curl|wget)\b.*(-X\s*(POST|PUT|DELETE|PATCH)|--data|-d\s|\|\s*(ba)?sh\b)/,
  /\b(chmod|chown)\s+-[a-zA-Z]*R/,
  /\b(dd\s+.*of=|mkfs|fdisk|parted|wipefs)\b/,
  /\b(shutdown|reboot|halt|poweroff)\b/,
  /\bsystemctl\s+(stop|disable|restart|mask)\b/,
  /\b(crontab\s+-r|launchctl\s+(unload|remove))\b/,
  /\b(npm|pnpm|yarn)\s+(publish|unpublish|deprecate)\b|\bcargo\s+publish\b|\btwine\s+upload\b|\bgem\s+push\b/,
  /\bgh\s+(pr\s+merge|repo\s+delete|release\s+delete|secret\s+set)\b/,
  /\b(rsync|scp)\b.*--delete\b/,
  /\bfind\b.*-(delete|exec\s+rm)\b/,
  /\b(kill\s+-9\s+-1|pkill|killall)\b/,
  /\b(iptables|ufw|nft)\s+(-F|-X|flush|delete|deny|reset)\b/,
  /\bssh\b.*\s(rm|shutdown|reboot|kubectl|docker)\b/,
  /:\(\)\s*\{\s*:\|:&\s*\};:/,
];

export function isInteresting(command: string): boolean {
  const c = command.trim();
  if (!c) return false;
  return RISKY.some((re) => re.test(c));
}

const SECRET_RE = /\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b/g;
const PROD_RE = /\b(prod|production|live|master|main|release)\b/i;

export function compileShellState(input: ShellInput): ShellState {
  const now = input.now ?? Date.now();
  const raw = input.command.trim();
  const command = raw.replace(SECRET_RE, "<SECRET>").slice(0, 600);
  const tokens = raw.split(/\s+/);
  const sudo = tokens[0] === "sudo";
  const argv0 = (sudo ? tokens[1] : tokens[0]) ?? "";
  const sub = (sudo ? tokens[2] : tokens[1]) ?? null;
  const home = input.home.replace(/\/$/, "");
  const cwd = input.cwd.startsWith(home) ? "~" + input.cwd.slice(home.length) : input.cwd;
  const l0: string[] = [];
  if (/(^|[;&|]\s*)(sudo\s+)?rm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+(\/|~|\$HOME|\*|\.\s*$|\/\*)(\s|$)/.test(raw) || /:\(\)\s*\{\s*:\|:&\s*\};:/.test(raw) || /\b(mkfs|dd\s+.*of=\/dev\/(sd|nvme|disk))/.test(raw) || /\bDROP\s+DATABASE\b/i.test(raw) || /\bchmod\s+-R\s+777\s+\/(\s|$)/.test(raw))
    l0.push("catastrophic_command");
  const isForcePush = /\bgit\s+push\b.*(\s-f\b|--force\b|\+\S+)/.test(raw);
  const branch = input.gitBranch ?? null;
  if (isForcePush && (branch === null || /^(main|master|develop|release\/|prod)/.test(branch))) l0.push("force_push_to_protected");
  const dryRunAvailable = /\b(kubectl|terraform|helm|rsync|npm\s+publish|aws\s+s3|git\s+clean|git\s+push|ansible-playbook)\b/.test(raw);
  const dryRunUsed = /--dry-run|\bplan\b|-n\b(?!\S)|--check\b|--what-if\b/.test(raw);
  const kube = input.kubeContext ?? null;
  return {
    action: "shell.command",
    command, argv0, subcommand: sub && !sub.startsWith("-") ? sub : null,
    cwd,
    git_branch: branch,
    kube_context: kube,
    aws_profile: input.env.AWS_PROFILE ?? null,
    is_root: input.env.USER === "root" || sudo,
    local_time: fmtTime(now),
    facts: {
      has_force_flag: /(\s-f\b|--force\b|--hard\b|-9\b)/.test(raw),
      has_recursive_flag: /(\s-[a-zA-Z]*[rR][a-zA-Z]*\b|--recursive\b)/.test(raw),
      targets_root_or_home: /\s(\/|~|\$HOME)(\s|$|\/\*)/.test(raw),
      mentions_prod: PROD_RE.test(raw),
      pipes_remote_to_shell: /\b(curl|wget)\b.*\|\s*(sudo\s+)?(ba|z)?sh\b/.test(raw),
      uses_sudo: sudo,
      dry_run_available: dryRunAvailable,
      dry_run_used: dryRunUsed,
      glob_or_wildcard: /[*?]/.test(raw),
      context_mentions_prod: PROD_RE.test(`${kube ?? ""} ${input.env.AWS_PROFILE ?? ""} ${branch ?? ""}`),
    },
    l0_flags: l0,
  };
}

function fmtTime(ms: number): string {
  const d = new Date(ms);
  return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${String(d.getHours()).padStart(2, "0")}h`;
}
