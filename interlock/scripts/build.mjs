import { build, context } from "esbuild";
import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";

// packs/*.pack.yaml → src/generated/packs.ts (the extension bundles them; the CLI reads YAML at runtime)
execFileSync(process.execPath, ["--import", "tsx", "scripts/packs-to-json.ts"], { stdio: "inherit" });

const test = process.argv.includes("--test");
const watch = process.argv.includes("--watch");
// dist/cli.js is what npm publishes. The extension builds to dist-extension/ (dist-test/ for the e2e).
const ext = test ? "dist-test" : "dist-extension";

rmSync(ext, { recursive: true, force: true });
mkdirSync(ext, { recursive: true });
if (!test) { rmSync("dist", { recursive: true, force: true }); mkdirSync("dist", { recursive: true }); }

const common = { bundle: true, logLevel: "info", define: { "process.env.NODE_ENV": '"production"' } };
const browser = { ...common, target: "chrome120", sourcemap: "inline" };
const entries = [
  { ...browser, entryPoints: ["src/ext/content.ts"], outfile: `${ext}/content.js`, format: "iife" },
  { ...browser, entryPoints: ["src/ext/background.ts"], outfile: `${ext}/background.js`, format: "esm" },
  { ...browser, entryPoints: ["src/ext/options.ts"], outfile: `${ext}/options.js`, format: "iife" },
];
if (!test) entries.push({ ...common, entryPoints: ["src/cli/main.ts"], outfile: "dist/cli.js", format: "esm", platform: "node", target: "node20", sourcemap: false, // createRequire: the yaml dependency is CommonJS and esbuild's ESM output needs a real require for it
  banner: { js: "#!/usr/bin/env node\nimport { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" } });

cpSync("extension/options.html", `${ext}/options.html`);
const manifest = JSON.parse(readFileSync("extension/manifest.json", "utf8"));
if (test) {
  // The e2e loads local Gmail/Slack lookalikes; the shipped manifest only ever matches the real hosts.
  manifest.content_scripts[0].matches.push("http://127.0.0.1/*", "http://localhost/*");
  manifest.host_permissions.push("http://127.0.0.1/*", "http://localhost/*");
}
writeFileSync(`${ext}/manifest.json`, JSON.stringify(manifest, null, 2));

if (watch) {
  for (const e of entries) (await context(e)).watch();
} else {
  await Promise.all(entries.map((e) => build(e)));
}
