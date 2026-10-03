"""End to end in headless Chromium for the features ported from the CLI: load the unpacked extension, open a bundled
game page, play it from the panel with an offline decider (the CLM stand-in, test/clm_stub.py, or random), and read
the panel's records back.

    python ext/test/e2e_parity.py snake  --seeds 1-8 --ticks 150 --delay 700            # reflex on (the bundled pack)
    python ext/test/e2e_parity.py snake  --seeds 1-8 --ticks 150 --delay 700 --drop reflex
    python ext/test/e2e_parity.py tetris --seeds 1-8 --ticks 400 --set read.piece.lookahead=false
    python ext/test/e2e_parity.py go     --seeds 1-4 --ticks 200 --query ai=mc

`--drop KEY` / `--set path=value` play a variant of the bundled pack, stored as an authored pack. One JSON line per
episode on stdout: outcome, ticks, how often the reflex or a re-read fired, perception time, and per-game numbers."""
import argparse, json, os, shutil, socket, statistics, subprocess, sys, tempfile, time
import yaml
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "..", "dist")
ROOT = os.path.join(HERE, "..", "..")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
GAMES = {"snake": ("snake.html", "tick=700"), "tetris": ("tetris.html", "level=1"), "go": ("go.html", "")}


def seeds(s):
    a, _, b = s.partition("-")
    return list(range(int(a), int(b or a) + 1))


def variant(name, drop, sets):
    raw = yaml.safe_load(open(os.path.join(ROOT, "packs", name, "pack.yaml")))
    for k in drop:
        raw.pop(k, None)
    for s in sets:
        path, val = s.split("=", 1)
        cur = raw
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur[p]
        cur[parts[-1]] = yaml.safe_load(val)
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), raw["screen"]["size"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def episode(p, game, seed, args, pack_yaml, size, clm_base):
    page, query = GAMES[game]
    q = "&".join(x for x in [f"seed={seed}", query, args.query] if x)
    path = os.path.abspath(os.path.join(ROOT, "games", page))
    url = "file://" + path + "?" + q
    profile = tempfile.mkdtemp(prefix="anygame-e2e-")
    proxy = None
    if args.sensor == "jev" and os.environ.get("HTTPS_PROXY"):
        from urllib.parse import urlparse
        u = urlparse(os.environ["HTTPS_PROXY"])
        proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}      # its CA must be in ~/.pki/nssdb (certutil)
    ctx = p.chromium.launch_persistent_context(profile, headless=False, proxy=proxy, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", "--window-size=540,900"], viewport={"width": 540, "height": 570}, no_viewport=True)
    try:
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        ext_id = sw.url.split("/")[2]
        store = {"keys": {"clmBase": clm_base}} if clm_base else {"keys": {"openrouter": os.environ.get("OPENROUTER_API_KEY") or "proxy"}} if args.sensor == "jev" else {}
        pack_name = game
        if pack_yaml is not None:
            pack_name = f"{game}-variant (authored)"
            store["packs"] = {f"{game}-variant": pack_yaml}
            store["regions"] = {path: {"x": 0, "y": 0, "w": size[0], "h": size[1]}}
        g = ctx.pages[0] if ctx.pages else ctx.new_page()
        g.goto(url); g.wait_for_load_state("load")
        # the worker can answer before its chrome.* bindings are up: wait for them
        tab_id = None
        for _ in range(50):
            tab_id = sw.evaluate("async () => { if (!globalThis.chrome || !chrome.tabs) return null; const [t] = await chrome.tabs.query({}); return t ? t.id : null; }")
            if tab_id is not None:
                break
            time.sleep(0.2)
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
        panel.wait_for_function("document.getElementById('log').textContent.includes('ready')", timeout=15000)
        if store:
            # keys, the variant pack and its region go in the extension's storage; the panel reads them on load
            panel.evaluate("async (s) => { await chrome.storage.local.set(s); }", store)
            panel.reload()
            panel.wait_for_function("document.getElementById('log').textContent.includes('ready')", timeout=15000)
        panel.wait_for_function("() => !document.getElementById('poolinfo').textContent.includes('checking')", timeout=15000)
        panel.select_option("#pack", pack_name); panel.select_option("#sensor", args.sensor)
        g.bring_to_front()
        panel.click("#play")
        t0 = time.time()
        recs = []
        while time.time() - t0 < args.seconds:
            time.sleep(1)
            recs = panel.evaluate("window.__anygameRecords || []")
            if (recs and recs[-1].get("action") == "stop") or len(recs) >= args.ticks:
                break
        state = g.evaluate("window.__state ? window.__state() : null")     # the game at the cap, before it runs on unattended
        panel.evaluate("() => { const b = document.getElementById('stop'); if (!b.disabled) b.click(); }")
        time.sleep(1.5)
        recs = panel.evaluate("window.__anygameRecords || []")[:max(len(recs), 1)]
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            with open(os.path.join(args.out, f"{game}-{seed}.jsonl"), "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in recs)
        return summarize(game, seed, recs, state, time.time() - t0)
    finally:
        ctx.close()
        shutil.rmtree(profile, ignore_errors=True)


def summarize(game, seed, recs, state, secs):
    last = recs[-1] if recs else {}
    out = {"game": game, "seed": seed, "ticks": len(recs), "seconds": round(secs), "end": last.get("action"), "reason": last.get("reason"),
           "decider_calls": sum(1 for r in recs if r.get("jev_ms") is not None and not r.get("skipped")),
           "reflex": sum(1 for r in recs if r.get("skipped") == "reflex"), "rereads": sum(r.get("reread", 0) for r in recs),
           "implausible": sum(1 for r in recs if r.get("implausible")),
           "perception_ms_median": statistics.median([r["perception_ms"] for r in recs]) if recs else None}
    acting = [r for r in recs if r.get("choice")]
    if acting:
        out["acted_after_ms_median"] = statistics.median([r["acted_after_ms"] for r in acting if r.get("acted_after_ms") is not None] or [0])
        out["reflex_acted_after_ms_median"] = statistics.median([r["acted_after_ms"] for r in acting if r.get("skipped") == "reflex"] or [0])
    if game == "snake" and state:
        out.update(dead=bool(state.get("over")), length=len(state.get("snake") or []), score=state.get("score"))
    if game == "tetris" and state:
        out.update(over=bool(state.get("over")), lines=state.get("lines"), score=state.get("score"))
        lands = [r["screen"]["piece"]["landings"] for r in recs if isinstance((r.get("screen") or {}).get("piece"), dict) and r["screen"]["piece"].get("landings")]
        out["ticks_with_landings"] = len(lands)
        placed = [r for r in acting if r.get("choice") == "place"]
        out["placed"], out["took_a"] = len(placed), sum(1 for r in placed if (r.get("choices") or {}).get("place__option") == "a")
    if game == "go" and state:
        sc = state.get("score") or {}
        out.update(over=state.get("over"), black=sc.get("black"), white=sc.get("white"), moves=state.get("moves"))
        po = [r for r in recs if isinstance((r.get("screen") or {}).get("go"), dict) and r["screen"]["go"].get("playouts")]
        out["ticks_with_playouts"] = len(po)
        out["go_read_ms_median"] = statistics.median([r["timings_ms"].get("go", 0) for r in po]) if po else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", choices=list(GAMES))
    ap.add_argument("--seeds", default="1-4")
    ap.add_argument("--ticks", type=int, default=150)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--sensor", default="clm", choices=["clm", "random", "jev"], help="jev: real Jev on OpenRouter (costs money), through HTTPS_PROXY when set")
    ap.add_argument("--delay", type=int, default=0, help="CLM_STUB_DELAY_MS for the stand-in")
    ap.add_argument("--query", default="")
    ap.add_argument("--out", default="", help="a directory for each episode's records")
    ap.add_argument("--drop", action="append", default=[])
    ap.add_argument("--set", action="append", default=[], dest="sets")
    args = ap.parse_args()
    pack_yaml, size = (variant(args.game, args.drop, args.sets) if (args.drop or args.sets) else (None, None))
    stub = None
    clm_base = None
    if args.sensor == "clm":
        port = free_port()
        stub = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "clm_stub.py"), str(port)], env={**os.environ, "CLM_STUB_DELAY_MS": str(args.delay)}, stdout=subprocess.DEVNULL)
        clm_base = f"http://127.0.0.1:{port}"
        time.sleep(0.8)
    try:
        with sync_playwright() as p:
            for s in seeds(args.seeds):
                for attempt in (1, 2):         # a browser that fails to start is tried once more, not counted as a game
                    try:
                        print(json.dumps(episode(p, args.game, s, args, pack_yaml, size, clm_base)), flush=True)
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"seed {s} attempt {attempt}: {e}", file=sys.stderr)
    finally:
        if stub:
            stub.terminate()


if __name__ == "__main__":
    main()
