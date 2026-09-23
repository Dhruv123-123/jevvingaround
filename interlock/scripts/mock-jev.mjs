// A stand-in for api.typesafe.ai for local dev and the e2e. Answers are steered by markers in the state
// so a test can force any rung of the ladder. Also serves test/fixtures/*.html.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";

export function startMock(port = 0) {
  const requests = [];
  let failNext = 0;
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      if (req.method === "GET" && req.url === "/__requests") return json(res, requests);
      if (req.method === "POST" && req.url === "/__fail") { failNext = Number(raw || "1"); return json(res, { failNext }); }
      if (req.method === "GET" && req.url?.startsWith("/fixtures/")) {
        try { res.writeHead(200, { "content-type": "text/html" }); return res.end(readFileSync("test/fixtures/" + req.url.slice(10).split("?")[0])); }
        catch { res.writeHead(404); return res.end(); }
      }
      if (req.method === "POST" && req.url === "/v1/systemone") {
        if (req.headers.authorization !== "Bearer test-key") { res.writeHead(401); return res.end("bad key"); }
        if (failNext > 0) { failNext--; res.writeHead(529); return res.end("overloaded"); }
        const body = JSON.parse(raw);
        requests.push({ at: Date.now(), body });
        return json(res, answer(body));
      }
      res.writeHead(404); res.end();
    });
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve({ server, port: server.address().port, requests, url: `http://127.0.0.1:${server.address().port}` })));
}

function json(res, v) { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify(v)); }

function answer({ model, state, questions }) {
  const text = JSON.stringify(state);
  const has = (m) => text.includes(m);
  // Generic steering: any "[[q:<id>=<p>]]" marker anywhere in the state sets that noul.
  const steer = {};
  for (const m of text.matchAll(/\[\[q:([a-z0-9_]+)=([0-9.]+)\]\]/g)) steer[m[1]] = Number(m[2]);
  const answers = {};
  for (const [id, q] of Object.entries(questions)) {
    if (q.type === "noul") {
      let p = steer[id] ?? 0.04;
      if (id === "external_leak" && has("[[confirm]]")) p = 0.8;
      if (id === "hostile_tone" && has("[[hold]]")) p = 0.7;
      if (id === "wrong_recipient" && has("[[wrong]]")) p = 0.9;
      if (id === "sender_rushed" && has("[[nudge]]")) p = 0.75;
      if (id === "falcon" && has("Falcon")) p = 0.85;
      answers[id] = { type: "noul", noul: p };
    } else if (q.type === "choice") {
      const opts = Object.keys(q.criteria);
      const pick = has("[[wrong]]") ? opts.find((o) => o.includes("sam")) ?? opts[0] : (opts.includes("none") ? "none" : opts[0]);
      const probabilities = Object.fromEntries(opts.map((o) => [o, o === pick ? 0.85 : 0.15 / Math.max(1, opts.length - 1)]));
      answers[id] = { type: "choice", choice: pick, probabilities, confidence: 0.85 };
    } else {
      const n = q.criteria.length;
      const score = has("[[confirm]]") ? 3.1 : has("[[hold]]") ? 1.6 : 0.3;
      answers[id] = { type: "score", score, legend: Object.fromEntries(q.criteria.map((c, i) => [String(i), c])), probabilities: {}, confidence: 0.8 };
    }
  }
  return { model: model === "jev-latest" ? "jev-1.13" : model, answers, usage: { input_tokens: Math.ceil(text.length / 4), output_tokens: 0 } };
}

if (process.argv[1] && process.argv[1].endsWith("mock-jev.mjs")) {
  const m = await startMock(Number(process.env.PORT ?? 8787));
  console.log(`mock jev on ${m.url}  (key: test-key; fixture: ${m.url}/fixtures/gmail.html)`);
}
