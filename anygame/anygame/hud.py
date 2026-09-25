"""A one-page HUD: the live frame with zones and detections drawn on, the belief bars, the chosen action, latency, cost."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np

PAGE = """<!doctype html><html><head><meta charset=utf-8><title>anygame</title>
<style>body{margin:0;background:#111;color:#eee;font:14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;display:flex;gap:16px;padding:16px}
img{max-height:92vh;border-radius:8px;background:#000}#side{min-width:340px}h2{margin:0 0 8px;font-size:16px}.bar{height:10px;background:#333;border-radius:5px;overflow:hidden;margin:2px 0 8px}
.bar>div{height:100%;background:#4ade80}.lbl{display:flex;justify-content:space-between;font-size:12px;color:#bbb}#action{font-size:22px;font-weight:700;margin:8px 0}
.dim{color:#888;font-size:12px}pre{font-size:11px;color:#9ca3af;white-space:pre-wrap;max-height:30vh;overflow:auto}</style></head>
<body><img id=f src=/frame.jpg><div id=side><h2 id=game></h2><div id=action>…</div><div id=probs></div><div id=nouls></div><div class=dim id=meta></div><pre id=screen></pre></div>
<script>
async function tick(){try{const s=await (await fetch('/state.json')).json();document.getElementById('f').src='/frame.jpg?'+Date.now();
document.getElementById('game').textContent=s.game+' · tick '+s.tick;document.getElementById('action').textContent=s.action||'…';
const bars=(o,el,title)=>{let h=title?'<div class=dim>'+title+'</div>':'';for(const[k,v]of Object.entries(o||{})){h+='<div class=lbl><span>'+k+'</span><span>'+Math.round(v*100)+'%</span></div><div class=bar><div style="width:'+Math.round(v*100)+'%"></div></div>'}el.innerHTML=h};
bars(s.action_probs,document.getElementById('probs'),'action');bars(s.nouls,document.getElementById('nouls'),'beliefs');
document.getElementById('meta').textContent='perception '+s.perception_ms+' ms · jev '+(s.jev_ms??'–')+' ms · '+(s.tokens??'–')+' tok · $'+(s.total_cost_usd??0).toFixed(4)+' so far';
document.getElementById('screen').textContent=JSON.stringify(s.screen,null,1)}catch(e){}setTimeout(tick,250)}tick();
</script></body></html>"""


class Hud:
    def __init__(self, port: int = 8080):
        self.jpg = b""
        self.state = {"game": "", "tick": 0}
        self.lock = threading.Lock()
        hud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/frame.jpg"):
                    with hud.lock:
                        body = hud.jpg
                    self.send_response(200); self.send_header("content-type", "image/jpeg"); self.send_header("cache-control", "no-store"); self.end_headers(); self.wfile.write(body)
                elif self.path.startswith("/state.json"):
                    with hud.lock:
                        body = json.dumps(hud.state).encode()
                    self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(body)
                else:
                    self.send_response(200); self.send_header("content-type", "text/html"); self.end_headers(); self.wfile.write(PAGE.encode())

        self.server = ThreadingHTTPServer(("0.0.0.0", port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = port

    def update(self, frame: np.ndarray, dets, rec, answers, pack):
        img = frame.copy()
        h, w = img.shape[:2]
        for z in pack.zones.values():
            x0, y0, x1, y1 = z.rect.px(w, h)
            cv2.rectangle(img, (x0, y0), (x1, y1), (90, 90, 90), 1)
        for d in dets:
            x0, y0, x1, y1 = [int(v) for v in d["rect"]]
            cv2.rectangle(img, (x0, y0), (x1, y1), (80, 220, 120), 2)
            cv2.putText(img, f"{d['label']} {d.get('conf', 0):.2f}", (x0, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 220, 120), 1)
        cv2.putText(img, str(rec.get("action", "")), (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.lock:
            self.jpg = buf.tobytes()
            self.state = {**rec, "game": pack.name}

    def close(self):
        self.server.shutdown()
