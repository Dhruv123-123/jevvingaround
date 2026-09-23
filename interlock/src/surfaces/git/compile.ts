/** Git push surface. Runs inside the pre-push hook; everything comes from `git` itself. */
import { execFileSync } from "node:child_process";

export interface PushRef { localRef: string; localSha: string; remoteRef: string; remoteSha: string }
export interface GitPushInput { remoteName: string; remoteUrl: string; refs: PushRef[]; cwd: string; now?: number; git?: (args: string[]) => string }

export interface GitPushState {
  action: "git.push";
  remote: string;
  branch: string | null;
  protected_branch: boolean;
  is_force: boolean;
  is_delete: boolean;
  is_new_branch: boolean;
  commits: string[];
  commit_count: number;
  files: string[];
  files_changed: number;
  insertions: number;
  deletions: number;
  facts: {
    migration_files: string[];
    destructive_migration_ops: string[];
    tests_disabled_lines: string[];
    test_files_deleted: string[];
    ci_config_changed: string[];
    infra_files_changed: string[];
    lockfile_changed_without_manifest: boolean;
    large_files_added: string[];
    subjects_look_like_wip: boolean;
  };
  key_hunks: string[];
  local_time: string;
  l0_flags: string[];
}

const ZERO = /^0+$/;
const SECRET_RE = /(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['"][^'"]{8,}['"])/i;
const DESTRUCTIVE_MIG = /\b(DROP\s+(TABLE|COLUMN|INDEX|DATABASE|SCHEMA)|TRUNCATE|drop_(table|column|index)|remove_column|removeColumn|dropTable|dropColumn|\.drop\(|DELETE\s+FROM)\b/i;
const SKIP_TEST = /^\+.*(\.skip\(|\bxit\(|\bxdescribe\(|\bit\.only\(|\bdescribe\.only\(|@pytest\.mark\.skip|@unittest\.skip|t\.Skip\(|#\[ignore\]|@Ignore\b|@Disabled\b)/;

export function defaultGit(cwd: string) {
  return (args: string[]) => {
    try { return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 8 * 1024 * 1024 }); }
    catch { return ""; }
  };
}

export function parsePushStdin(stdin: string): PushRef[] {
  return stdin.trim().split("\n").filter(Boolean).map((l) => {
    const [localRef = "", localSha = "", remoteRef = "", remoteSha = ""] = l.trim().split(/\s+/);
    return { localRef, localSha, remoteRef, remoteSha };
  });
}

export function compileGitPushState(input: GitPushInput): GitPushState {
  const git = input.git ?? defaultGit(input.cwd);
  const now = input.now ?? Date.now();
  const ref = input.refs[0];
  const l0: string[] = [];
  if (!ref) {
    return { action: "git.push", remote: input.remoteName, branch: null, protected_branch: false, is_force: false, is_delete: false, is_new_branch: false, commits: [], commit_count: 0, files: [], files_changed: 0, insertions: 0, deletions: 0, facts: emptyFacts(), key_hunks: [], local_time: fmtTime(now), l0_flags: l0 };
  }
  const branch = ref.remoteRef.replace(/^refs\/heads\//, "") || null;
  const isDelete = ZERO.test(ref.localSha);
  const isNew = ZERO.test(ref.remoteSha);
  const protectedBranch = !!branch && /^(main|master|develop|trunk|release(\/|-|$)|prod(uction)?(\/|-|$)|hotfix\/)/.test(branch);
  let isForce = false;
  if (!isDelete && !isNew) {
    try { execFileSync("git", ["merge-base", "--is-ancestor", ref.remoteSha, ref.localSha], { cwd: input.cwd, stdio: "ignore" }); }
    catch { isForce = true; }
  }
  if (isForce && protectedBranch) l0.push("force_push_to_protected");
  if (isDelete && protectedBranch) l0.push("deleting_protected_branch");

  const range = isDelete ? null : isNew ? `${ref.localSha} --not --remotes` : `${ref.remoteSha}..${ref.localSha}`;
  const rangeArgs = range ? range.split(" ") : [];
  const commits = range ? git(["log", "--format=%s", "-n", "30", ...rangeArgs]).trim().split("\n").filter(Boolean) : [];
  const nameStatus = range ? git(["diff", "--name-status", "-M", ...(isNew ? [`${ref.localSha}~${Math.min(commits.length, 30)}`, ref.localSha] : [ref.remoteSha, ref.localSha])]).trim().split("\n").filter(Boolean) : [];
  const shortstat = range ? git(["diff", "--shortstat", ...(isNew ? [`${ref.localSha}~${Math.min(commits.length, 30)}`, ref.localSha] : [ref.remoteSha, ref.localSha])]) : "";
  const files = nameStatus.map((l) => l.replace(/\t/g, " ")).slice(0, 60);
  const diff = range ? git(["diff", "--unified=0", ...(isNew ? [`${ref.localSha}~${Math.min(commits.length, 30)}`, ref.localSha] : [ref.remoteSha, ref.localSha])]).slice(0, 400_000) : "";
  const added = diff.split("\n").filter((l) => l.startsWith("+") && !l.startsWith("+++"));

  const paths = nameStatus.map((l) => l.split("\t").pop() ?? "");
  const migrationFiles = paths.filter((p) => /migrat/i.test(p));
  const destructiveOps = added.filter((l) => DESTRUCTIVE_MIG.test(l)).map((l) => l.slice(0, 160)).slice(0, 8);
  const testsDisabled = added.filter((l) => SKIP_TEST.test(l)).map((l) => l.slice(0, 160)).slice(0, 8);
  const testFilesDeleted = nameStatus.filter((l) => l.startsWith("D") && /(test|spec)/i.test(l)).map((l) => l.split("\t").pop() ?? "");
  const ci = paths.filter((p) => /^\.github\/workflows\/|^\.gitlab-ci\.yml$|^Jenkinsfile$|^\.circleci\/|^\.buildkite\/|^bitbucket-pipelines\.yml$/.test(p));
  const infra = paths.filter((p) => /\.(tf|tfvars)$|^(k8s|kubernetes|helm|charts|terraform|infra|deploy)\/|Dockerfile|docker-compose|\.ya?ml$/.test(p) && !ci.includes(p));
  const lockChanged = paths.some((p) => /(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|Cargo\.lock|poetry\.lock|Gemfile\.lock|go\.sum)$/.test(p));
  const manifestChanged = paths.some((p) => /(package\.json|Cargo\.toml|pyproject\.toml|Gemfile|go\.mod)$/.test(p));
  const secretLines = added.filter((l) => SECRET_RE.test(l));
  if (secretLines.length) l0.push("secret_in_diff");
  const m = shortstat.match(/(\d+) files? changed(?:, (\d+) insertions?)?(?:, (\d+) deletions?)?/);

  const keyHunks = [...destructiveOps, ...testsDisabled, ...added.filter((l) => /\b(TODO|FIXME|HACK|XXX|console\.log\(|debugger;|print\()/i.test(l)).slice(0, 4).map((l) => l.slice(0, 160))].slice(0, 12).map((l) => l.replace(SECRET_RE, "<SECRET>"));

  return {
    action: "git.push",
    remote: input.remoteName,
    branch,
    protected_branch: protectedBranch,
    is_force: isForce,
    is_delete: isDelete,
    is_new_branch: isNew,
    commits: commits.slice(0, 20),
    commit_count: commits.length,
    files,
    files_changed: Number(m?.[1] ?? paths.length),
    insertions: Number(m?.[2] ?? 0),
    deletions: Number(m?.[3] ?? 0),
    facts: {
      migration_files: migrationFiles.slice(0, 10),
      destructive_migration_ops: destructiveOps,
      tests_disabled_lines: testsDisabled,
      test_files_deleted: testFilesDeleted.slice(0, 10),
      ci_config_changed: ci,
      infra_files_changed: infra.slice(0, 10),
      lockfile_changed_without_manifest: lockChanged && !manifestChanged,
      large_files_added: nameStatus.filter((l) => l.startsWith("A") && /\.(zip|tar|gz|bin|exe|dmg|iso|mp4|mov|psd|sqlite|db)$/i.test(l)).map((l) => l.split("\t").pop() ?? "").slice(0, 5),
      subjects_look_like_wip: commits.some((s) => /^(wip|fixup!|squash!|temp|tmp|asdf|test|\.+|x+)$/i.test(s.trim()) || /\b(wip|do not merge|dnm)\b/i.test(s)),
    },
    key_hunks: keyHunks,
    local_time: fmtTime(now),
    l0_flags: l0,
  };
}

function emptyFacts(): GitPushState["facts"] {
  return { migration_files: [], destructive_migration_ops: [], tests_disabled_lines: [], test_files_deleted: [], ci_config_changed: [], infra_files_changed: [], lockfile_changed_without_manifest: false, large_files_added: [], subjects_look_like_wip: false };
}
function fmtTime(ms: number): string {
  const d = new Date(ms);
  return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${String(d.getHours()).padStart(2, "0")}h`;
}
