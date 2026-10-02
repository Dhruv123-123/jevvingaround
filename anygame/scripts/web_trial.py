"""Play a hand-written pack on a real third-party web game with Jev, and check every read against the page's own state.

    python scripts/web_trial.py tictactoe --episodes 5 --out trial/ttt

The page's state is read (by a JS expression) right after each screenshot, so a read is compared with what the page
held when the frame was taken. Per tick the log line gets `truth` and `wrong` (the reads that disagree). The summary
says how often perception was right, what Jev did, and how each episode ended. No chat model is called.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from anygame.device import open_device          # noqa: E402
from anygame.loop import Agent                   # noqa: E402
from anygame.pack import load_pack               # noqa: E402
from anygame.sensors import open_sensor          # noqa: E402

HERE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- tic-tac-toe: playtictactoe.org
TTT_JS = """(() => { const sq = [...document.querySelectorAll('.board .square > div')].map(d => d.className);
  const s = [...document.querySelectorAll('.scores .score, .scores p, .scores span')].map(e => e.innerText);
  return {cells: sq, over: document.querySelector('.restart').style.display !== 'none', text: document.querySelector('.scores')?.innerText || ''}; })()"""


def ttt_compare(values, truth):
    want = ["".join({"x": "X", "o": "O"}.get(truth["cells"][r * 3 + c], ".") for c in range(3)) for r in range(3)]
    b = values.get("board") or {}
    got = list(b) if isinstance(b, list) else ["".join(str(b.get(f"c{c + 1}r{r + 1}", "?")) for c in range(3)) for r in range(3)]
    wrong = {}
    if got != want:
        wrong["board"] = {"read": got, "page": want}
    over_read = bool(values.get("faded"))
    if over_read != truth["over"]:
        wrong["faded"] = {"read": values.get("faded"), "page_over": truth["over"]}
    return wrong


def ttt_outcome(truth):
    nums = [int(t) for t in truth["text"].split() if t.isdigit()]
    return {"player": nums[0], "tie": nums[1], "computer": nums[2]} if len(nums) >= 3 else truth["text"]


def ttt_restart(dev):
    dev.tap(270, 225)
    time.sleep(1.5)


# ---------------------------------------------------------------- snake: playsnake.org, level Slug
SNAKE_JS = """(() => { const c = [...document.querySelectorAll('.board .cell')].map(e => e.className.replace('cell', '').trim());
  return {cells: c, state: document.querySelector('.game').className.replace(/game|notranslate/g, '').trim(),
          score: document.querySelector('.score')?.innerText}; })()"""


def snake_compare(values, truth):
    if len(truth.get("cells", [])) != 315:
        return {"truth": "no board"}
    want = ["".join({"snake": "s", "food": "F"}.get(truth["cells"][r * 21 + c], ".") for c in range(21)) for r in range(15)]
    b = values.get("cells")
    got = list(b) if isinstance(b, list) else want
    wrong = {}
    diff = [f"c{c + 1}r{r + 1}:{got[r][c]}≠{want[r][c]}" for r in range(15) for c in range(21) if got[r][c] != want[r][c]]
    if diff and truth["state"] == "playing":
        wrong["cells"] = diff[:6]
    snake = {(c, r) for r in range(15) for c in range(21) if want[r][c] == "s"}
    h = values.get("head")
    if truth["state"] == "playing" and len(snake) > 1:
        import re
        m = re.match(r"c(\d+)r(\d+)$", str(h))
        hc = (int(m.group(1)) - 1, int(m.group(2)) - 1) if m else None
        ends = {p for p in snake if sum((p[0] + dc, p[1] + dr) in snake for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))) <= 1}
        if hc not in ends:
            wrong["head"] = {"read": h, "page_ends": sorted(f"c{x + 1}r{y + 1}" for x, y in ends)}
    dead = values.get("status") == "dead"
    if dead != ("ended" in truth["state"]):
        wrong["status"] = {"read": values.get("status"), "page": truth["state"]}
    return wrong


def snake_start(dev):
    dev.reload()
    page = dev._page
    page.wait_for_timeout(1500)
    page.click("p.level[data-level='0']")
    page.wait_for_function("document.querySelector('.game').className.includes('playing')", timeout=15000)


# ---------------------------------------------------------------- dino: chromedino.com
DINO_JS = """(() => { const r = Runner.instance_; return {crashed: r.crashed, playing: r.playing, speed: +r.currentSpeed.toFixed(2),
  dist: Math.round(r.distanceRan), score: r.distanceMeter.getActualDistance(r.distanceRan), y: r.tRex.yPos, jumping: r.tRex.jumping,
  obs: r.horizon.obstacles.map(o => [o.typeConfig.type, Math.round(o.xPos), Math.round(o.yPos), o.width])}; })()"""


def dino_truth_next(truth, x0=96, x1=540):
    """The page's nearest obstacle in front of the dino's nose: (gap px, width px, type, y) or None."""
    obs = [o for o in truth.get("obs", []) if o[1] + o[3] > x0 and o[1] < x1]
    if not obs:
        return None
    o = min(obs, key=lambda o: o[1])
    return max(0, o[1] - x0), o[3], o[0], o[2]


def dino_compare(values, truth):
    wrong = {}
    if truth.get("crashed"):
        if values.get("status") != "over":
            wrong["status"] = {"read": values.get("status"), "page": "crashed"}
        return wrong
    if values.get("status") == "over":
        wrong["status"] = {"read": "over", "page": "running"}
    ys = {truth.get("y"), (truth.get("before") or truth).get("y")}
    if values.get("dino") == "air" and ys == {93}:
        wrong["dino"] = {"read": "air", "page_y": 93}
    elif values.get("dino") == "ground" and values.get("above") != "dino" and all(y is not None and y < 85 for y in ys):
        # within 8 px of the ground the legs still show; a cactus under the dino fills `feet`, then `above` shows it
        wrong["dino"] = {"read": "ground", "page_y": sorted(ys)}
    nxt = values.get("next") or {}
    t = dino_truth_next(truth)
    t0 = dino_truth_next(truth.get("before") or truth)      # the frame was taken between these two page reads
    if t is None and t0 is None:
        if nxt.get("rows") not in (None, "none"):
            wrong["next"] = {"read": nxt, "page": "clear"}
    elif t is None or t0 is None or t[2] != t0[2]:
        pass        # an obstacle entered or left the road between the two page reads: either read is right
    elif t[2] == "PTERODACTYL" and t[3] < 60:
        pass        # a high bird the dino runs under: the road may read it or not, both are safe
    elif nxt.get("rows") in (None, "none") or not (min(t[0], t0[0]) - 8 <= nxt.get("px", 0) <= max(t[0], t0[0]) + 8):
        # 8 px: one 6 px column plus rounding
        wrong["next"] = {"read": {k: nxt.get(k) for k in ("px", "rows", "width_px")}, "page": t, "page_before": t0}
    return wrong


def dino_start(dev):
    dev.reload()
    page = dev._page
    page.wait_for_timeout(1500)
    page.keyboard.press("Space")
    page.wait_for_function("Runner.instance_ && Runner.instance_.activated && !Runner.instance_.crashed && Runner.instance_.tRex.yPos >= 90", timeout=15000)


GAMES = {
    "dino": dict(url="https://chromedino.com", pack="web-dino", js=DINO_JS, compare=dino_compare, start=dino_start, restart=dino_start,
                 outcome=lambda t: {"score": t.get("score"), "speed": t.get("speed"), "crashed": t.get("crashed")}, ticks=3000, stall=0),
    "snake": dict(url="https://playsnake.org", pack="web-snake", js=SNAKE_JS, compare=snake_compare, start=snake_start, restart=snake_start,
                  outcome=lambda t: {"score": t.get("score"), "length": sum(1 for c in t.get("cells", []) if c == "snake"), "state": t.get("state")},
                  ticks=600, stall=40),
    "tictactoe": dict(url="https://playtictactoe.org", pack="web-tictactoe", js=TTT_JS, compare=ttt_compare, outcome=ttt_outcome,
                      restart=ttt_restart, ticks=40),
}


class TruthDevice:
    """The device, plus the page's own state captured right after each frame."""

    def __init__(self, dev, js):
        self.dev, self.js, self.truth = dev, js, None

    def frame(self):
        try:
            before = self.dev._page.evaluate(self.js)
        except Exception:  # noqa: BLE001
            before = None
        f = self.dev.frame()
        try:
            self.truth = self.dev._page.evaluate(self.js)
            if isinstance(self.truth, dict) and isinstance(before, dict):
                self.truth["before"] = before      # the page just before the screenshot: the frame lies between the two
        except Exception as e:  # noqa: BLE001
            self.truth = {"error": str(e)[:120]}
        return f

    def __getattr__(self, k):
        return getattr(self.dev, k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", choices=sorted(GAMES))
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--sensor", default="jev")
    ap.add_argument("--ticks", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    g = GAMES[a.game]
    out = Path(a.out or HERE / "trial" / a.game)
    out.mkdir(parents=True, exist_ok=True)
    pack = load_pack(HERE / "packs" / g["pack"])
    dev = TruthDevice(open_device("web://" + g["url"], pack.size), g["js"])
    if g.get("start"):
        g["start"](dev)
    sensor = open_sensor(a.sensor)
    summary = []
    try:
        for ep in range(a.episodes):
            rows = []

            def on_record(rec, frame, rows=rows):
                t = dev.truth or {}
                rec["truth"] = t
                rec["wrong"] = g["compare"](rec.get("screen") or {}, t) if "error" not in t else {"truth_error": t["error"]}
                rows.append(rec)
            agent = Agent(pack, dev, sensor, log_path=str(out / f"ep{ep + 1}.jsonl"), max_ticks=a.ticks or g["ticks"])
            agent.on_record = on_record
            agent.stall_ticks = g.get("stall", 20)
            last = agent.run()
            # the page as the episode ended (a later look can find the game restarted: Chrome's dino restarts on a
            # key up after a crash)
            final = rows[-1]["truth"] if rows and "error" not in rows[-1].get("truth", {"error": 1}) else None
            if final is None:
                time.sleep(g.get("end_wait", 1.0))
                dev.frame()
                final = dev.truth
            n = len(rows)
            wrong = [r for r in rows if r["wrong"]]
            fields = {}
            for r in wrong:
                for k in r["wrong"]:
                    fields[k] = fields.get(k, 0) + 1
            acted = [r for r in rows if r.get("action") not in (None, "wait", "stop", "keep")]
            lat = sorted(r["jev_ms"] for r in rows if "jev_ms" in r)
            row = {"episode": ep + 1, "ticks": n, "asked_async": getattr(agent, "asked_async", 0), "reflex_ticks": getattr(agent, "skipped_reflex", 0), "end": last.get("reason"), "reads_wrong_ticks": len(wrong), "wrong_by_read": fields,
                   "actions": len(acted), "jev_calls": len(lat), "jev_ms_median": lat[len(lat) // 2] if lat else None,
                   "cost_usd": round(agent.total_cost, 5), "outcome": g["outcome"](final) if final and "error" not in final else final}
            print(json.dumps(row), flush=True)
            summary.append(row)
            if ep + 1 < a.episodes:
                g["restart"](dev)
    finally:
        dev.close()
    (out / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
