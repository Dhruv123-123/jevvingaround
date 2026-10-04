"""A live view of a run: every N ticks the current screen as `frame.png` (plus a numbered copy) and `status.json`
(tick, milestones, discovered position, screen kind, the last decisions, spend) in one directory, and `index.html`
there that reloads them. Open the folder, or serve it (`python -m http.server -d DIR`), to watch a long run as it plays.
Written beside the run only; nothing here is read by the agent."""
from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2

PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live run</title>
<style>body{font:14px system-ui,sans-serif;margin:16px;background:#111;color:#eee}img{image-rendering:pixelated;width:min(480px,100%);border:1px solid #444}
pre{white-space:pre-wrap;background:#1c1c1c;padding:8px}</style>
<h3 id=h>Live run</h3><img id=f src="frame.png"><pre id=s></pre>
<script>
async function tick(){try{const s=await (await fetch('status.json?'+Date.now())).json();
document.getElementById('f').src='frame.png?'+Date.now();
document.getElementById('h').textContent=`${s.game} tick ${s.tick} · ${s.screen} · $${s.cost_usd}`;
document.getElementById('s').textContent=JSON.stringify(s,null,1);}catch(e){}}
tick();setInterval(tick,3000);
</script>"""


class LiveWriter:
    def __init__(self, out: str, every: int = 10, keep_frames: bool = True):
        self.dir = Path(out)
        self.dir.mkdir(parents=True, exist_ok=True)
        # an earlier run's frames and status move to previous/<when it ended>, so ticks of two runs never mix
        old = [p for p in ("frames", "status.json", "status.jsonl", "frame.png") if (self.dir / p).exists()]
        if old:
            when = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime((self.dir / old[0]).stat().st_mtime))
            dest = self.dir / "previous" / when
            dest.mkdir(parents=True, exist_ok=True)
            for p in old:
                os.replace(self.dir / p, dest / p)
        self.every = max(1, int(every))
        self.keep = keep_frames
        self.recent: deque[dict[str, Any]] = deque(maxlen=12)
        self.milestones: list[dict[str, Any]] = []
        self.started = time.time()
        (self.dir / "index.html").write_text(PAGE)

    def record(self, agent, rec: dict[str, Any], frame, grader=None, game: str = "") -> None:
        act = rec.get("action")
        if act:
            self.recent.append({"tick": rec.get("tick"), "action": act, "screen": (rec.get("screen") or {}).get("screen"),
                                "jev": rec.get("jev_ms", 0) > 0, "top_agrees": rec.get("top_agrees")})
        for m in rec.get("grader") or []:
            self.milestones.append({"milestone": m, "tick": rec.get("tick"), "at": time.strftime("%H:%M:%SZ", time.gmtime())})
        tick = int(rec.get("tick") or 0)
        if tick % self.every and not rec.get("grader"):
            return
        self.write(agent, rec, frame, grader, game)

    def write(self, agent, rec, frame, grader=None, game: str = "") -> None:
        scr = {k: v for k, v in (rec.get("screen") or {}).items() if not isinstance(v, dict)}
        rep = grader.report() if grader is not None else None
        status = {"game": game, "tick": rec.get("tick"), "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "elapsed_s": round(time.time() - self.started), "screen": scr.get("screen"),
                  "found": {k: scr.get(k) for k in ("x", "y", "map", "cell")}, "text": scr.get("text"),
                  "goal": getattr(agent, "quest", None), "goals_reached": [g.get("id") for g in getattr(agent, "goal_log", [])],
                  "milestones": [m for m in (rep or {}).get("reached", [])], "milestone_log": self.milestones,
                  "progress": (rep or {}).get("progress"), "facts": (rep or {}).get("facts"),
                  "decisions": getattr(agent, "top_asked", 0), "agreed_with_top": getattr(agent, "top_agreed", 0),
                  "cost_usd": round(getattr(agent, "total_cost", 0.0), 4), "recent": list(self.recent)}
        if frame is not None:
            ok, png = cv2.imencode(".png", frame)
            if ok:
                tmp = self.dir / "frame.png.tmp"
                tmp.write_bytes(png.tobytes())
                os.replace(tmp, self.dir / "frame.png")
                if self.keep:
                    (self.dir / "frames").mkdir(exist_ok=True)
                    (self.dir / "frames" / f"{int(rec.get('tick') or 0):06d}.png").write_bytes(png.tobytes())
        tmp = self.dir / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=1, default=str))
        os.replace(tmp, self.dir / "status.json")
        with open(self.dir / "status.jsonl", "a") as f:
            f.write(json.dumps({k: status[k] for k in ("tick", "updated", "screen", "found", "milestones", "cost_usd")}, default=str) + "\n")


def attach(agent, out: str, every: int = 10, grader=None, game: str = "") -> LiveWriter:
    w = LiveWriter(out, every)
    prev = agent.on_record

    def on_record(rec, frame):
        if prev is not None:
            prev(rec, frame)
        try:
            w.record(agent, rec, frame, grader, game)
        except Exception as e:  # the view never stops the run
            print(f"live: {e}", flush=True)
    agent.on_record = on_record
    return w
