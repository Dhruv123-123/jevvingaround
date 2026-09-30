"""A stand-in for a CLM server, speaking the /v1/systemone protocol (the same one Jev and clm-serve speak): noul,
choice and score questions, probabilities over the criteria, usage and the X-CLM-Latency-Ms header. It ranks by a
fixed heuristic (the first criterion that appears in the state text, else the first), so tests can prove the client,
the sensor wiring and the loop without a GPU. Not a model. `python test/clm_stub.py [port]`."""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer


def answer(state, questions):
    text = json.dumps(state, default=str).lower()
    out = {}
    for qid, q in questions.items():
        t = q.get("type")
        if t == "noul":
            out[qid] = {"type": "noul", "noul": 0.5}
        elif t == "choice":
            opts = list((q.get("criteria") or {}).keys()) or ["none"]
            hit = next((o for o in opts if o.lower() in text and o != "none"), opts[0])
            n = len(opts)
            probs = {o: (0.7 if o == hit else 0.3 / max(1, n - 1)) for o in opts}
            out[qid] = {"type": "choice", "choice": hit, "confidence": 0.7 - 0.3 / max(1, n - 1), "probabilities": probs}
        elif t == "score":
            levels = q.get("criteria") or ["low", "high"]
            levels = list(levels) if isinstance(levels, (list, tuple)) else list(levels.keys())
            out[qid] = {"type": "score", "score": 0, "legend": levels[0], "probabilities": {str(l): (1.0 if i == 0 else 0.0) for i, l in enumerate(levels)}}
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"ok": True, "cache": {"occupancy": 0, "hit_rate": 0.0}}).encode()
        elif self.path == "/v1/models":
            body = json.dumps({"models": ["clm-latest", "clm-raw"]}).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/systemone":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("content-length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        t0 = time.perf_counter()
        ans = answer(req.get("state"), req.get("questions") or {})
        ms = (time.perf_counter() - t0) * 1000 + 16.0     # what a real CLM-8B reports on a 4090, roughly
        body = json.dumps({"model": req.get("model", "clm-latest"), "answers": ans, "usage": {"input_tokens": len(json.dumps(req.get("state"), default=str)) // 4, "billing_units": 1}}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("X-CLM-Latency-Ms", f"{ms:.1f}"); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8700
    print(f"clm stub on http://127.0.0.1:{port}/v1/systemone", flush=True)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
