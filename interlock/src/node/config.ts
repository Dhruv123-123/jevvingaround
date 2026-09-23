import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { DEFAULT_SETTINGS, type Settings } from "../core/types.js";

/** ~/.config/interlock/config.json, overridden by JEV_API_KEY / JEV_BASE_URL / JEV_MODEL / INTERLOCK_* env. */
export function configDir(): string {
  return process.env.INTERLOCK_HOME ?? join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "interlock");
}

export function loadSettings(): Settings {
  const dir = configDir();
  let file: Partial<Settings> = {};
  const p = join(dir, "config.json");
  if (existsSync(p)) {
    try { file = JSON.parse(readFileSync(p, "utf8")); } catch { /* corrupt config is the same as none */ }
  }
  const env = process.env;
  const s: Settings = { ...DEFAULT_SETTINGS, ...file };
  if (env.JEV_API_KEY) s.apiKey = env.JEV_API_KEY;
  if (env.JEV_BASE_URL) s.baseUrl = env.JEV_BASE_URL;
  if (env.JEV_MODEL) s.model = env.JEV_MODEL;
  if (env.INTERLOCK_FAIL_MODE === "open" || env.INTERLOCK_FAIL_MODE === "closed") s.failMode = env.INTERLOCK_FAIL_MODE;
  if (env.INTERLOCK_BUDGET) s.interruptBudgetPerDay = Number(env.INTERLOCK_BUDGET);
  return s;
}

export function saveSettings(patch: Partial<Settings>): Settings {
  const dir = configDir();
  mkdirSync(dir, { recursive: true });
  const cur = loadSettings();
  const next = { ...cur, ...patch };
  writeFileSync(join(dir, "config.json"), JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
  return next;
}
