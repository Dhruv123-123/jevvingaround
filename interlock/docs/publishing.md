# Publishing

Everything below is a one-time account action; the repo already carries the files.

## npm (`interlock-gate`)

1. Add `NPM_TOKEN` (an automation token) as a repository secret.
2. Tag and push: `git tag v0.2.0 && git push --tags`. `.github/workflows/release.yml` runs typecheck, tests, build and `npm publish --provenance --access public`.
3. Check: `npx interlock-gate@0.2.0 packs`.

## MCP Registry

`server.json` at the package root and `mcpName` in `package.json` are already aligned (`io.github.Dhruv123-123/interlock`).
The registry verifies the npm package carries that `mcpName`, so publish to npm first.

```bash
brew install mcp-publisher            # or the curl one-liner in the registry quickstart
cd interlock
mcp-publisher login github            # device-code flow; the namespace must match your GitHub user
mcp-publisher publish
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Dhruv123-123/interlock"
```

If `publish` reports a schema error on `packageArguments`, run `mcp-publisher init` in a scratch directory and
compare the generated shape; the field names in `server.json` follow the 2025-12-11 schema.

## CI with the model

Add `OPENROUTER_API_KEY` (or `JEV_API_KEY`) as a repository secret. The `packs` workflow then runs all 59 cases
against the model on every push; without it, only the rule-based cases run and the model step is skipped.

## Listings

- [madewithjev.com](https://madewithjev.com) — submit with the README's measured table and the Jev-vs-LLM comparison.
- awesome-jev lists — open a PR with one line: *Interlock — policy as Question Packs, decisions as Audit Vectors; MCP proxy, shell, git, payments; eval with calibration.*
- MCP client docs / awesome-mcp-servers — the `mcp` line from [agents.md](agents.md).
