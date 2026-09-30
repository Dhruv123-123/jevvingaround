"""A game with an API, live: games/snake_ws.py publishes Snake's state over a WebSocket and takes keys back; anygame
plays it through stream://ws://… with the snake-state pack. No pixels anywhere: the frame is blank, the typed frame
comes from the stream, the keys go back on the socket. `python test/e2e_stream.py [sensor] [ticks]`."""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENSOR = sys.argv[1] if len(sys.argv) > 1 else "random:3"
TICKS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
PORT = int(os.environ.get("PORT", "8765"))
server = subprocess.Popen([sys.executable, os.path.join(ROOT, "games", "snake_ws.py"), str(PORT), "4", "700"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    t0 = time.time()
    while time.time() - t0 < 40:
        line = server.stdout.readline()
        if "snake state on" in line:
            break
    else:
        raise SystemExit("the stream server did not start")
    from anygame.device import open_device
    from anygame.pack import load_pack
    from anygame.loop import Agent
    from anygame.sensors import open_sensor
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    dev = open_device(f"stream://ws://127.0.0.1:{PORT}", pack.size)
    for _ in range(50):
        if dev.state():
            break
        time.sleep(0.1)
    st = dev.state()
    assert st and "snake" in st, f"no state arrived: {st}"
    print("state arrived:", {k: v for k, v in st.items() if k != "snake"}, "| frame", dev.frame().shape)
    ag = Agent(pack, dev, open_sensor(SENSOR), None, max_ticks=TICKS)
    last = ag.run()
    heads = [x for x in (r.get("head") for r in [last.get("screen") or {}]) if x]
    keys = [h["action"] for h in ag.history if h["action"].startswith("key")]
    print("played", ag.tick, "ticks:", last.get("action"), last.get("reason") or "", "| keys sent on the socket:", len(keys), "| final head", (last.get("screen") or {}).get("head"), "score", (last.get("screen") or {}).get("score"), "support", last.get("support"))
    assert ag.tick >= 5 and last.get("support") == 1.0 and (last.get("screen") or {}).get("head"), "the stream did not drive the loop"
    print("RESULT PASS")
    ag.close(); dev.close()
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
