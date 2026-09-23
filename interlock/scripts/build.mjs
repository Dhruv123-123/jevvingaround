import { build, context } from "esbuild";
import { cpSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";

const test = process.argv.includes("--test");
const watch = process.argv.includes("--watch");
const out = test ? "dist-test" : "dist";

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const common = { bundle: true, target: "chrome120", sourcemap: "inline", logLevel: "info", define: { "process.env.NODE_ENV": '"production"' } };
const entries = [
  { entryPoints: ["src/ext/content.ts"], outfile: `${out}/content.js`, format: "iife" },
  { entryPoints: ["src/ext/background.ts"], outfile: `${out}/background.js`, format: "esm" },
  { entryPoints: ["src/ext/options.ts"], outfile: `${out}/options.js`, format: "iife" },
];

cpSync("extension/options.html", `${out}/options.html`);
const manifest = JSON.parse(readFileSync("extension/manifest.json", "utf8"));
if (test) {
  // The e2e loads a local Gmail lookalike; the shipped manifest only ever matches mail.google.com.
  manifest.content_scripts[0].matches.push("http://127.0.0.1/*", "http://localhost/*");
  manifest.host_permissions.push("http://127.0.0.1/*", "http://localhost/*");
}
writeFileSync(`${out}/manifest.json`, JSON.stringify(manifest, null, 2));

if (watch) {
  for (const e of entries) (await context({ ...common, ...e })).watch();
} else {
  await Promise.all(entries.map((e) => build({ ...common, ...e })));
}
