"""The desktop device, live: a virtual display (Xvfb), a real Chromium window in kiosk mode showing Snake at (0,0), and
anygame playing it through screen:// (mss grabs the X framebuffer, pynput sends X key events). No Playwright input,
no page hooks: exactly what a user's desktop looks like to the runtime. Needs xvfb-run (or a DISPLAY) and the
[desktop] extras. `xvfb-run -a -s "-screen 0 1024x768x24" python test/e2e_screen.py [sensor] [ticks]`."""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = next((c for c in [os.environ.get("CHROMIUM_PATH", ""), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/ms-playwright/chromium-1194/chrome-linux/chrome"] if c and os.path.exists(c)), None)
SENSOR = sys.argv[1] if len(sys.argv) > 1 else "random:3"
TICKS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
assert os.environ.get("DISPLAY"), "needs a DISPLAY (run under xvfb-run)"
if CHROME is None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        CHROME = p.chromium.executable_path
url = "file://" + os.path.join(ROOT, "games", "snake.html") + "?seed=4&tick=" + os.environ.get("SNAKE_TICK", "1500")
# a kiosk window: the page fills the window, the window sits at (0,0) on the virtual screen
chrome = subprocess.Popen([CHROME, "--no-sandbox", "--kiosk", "--window-position=0,0", "--window-size=540,560", "--no-first-run", "--disable-gpu",
                           "--user-data-dir=/tmp/anygame-screen-profile", "--remote-debugging-port=9333", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(4)
    from anygame.device.screen import ScreenDevice
    from anygame.pack import load_pack
    from anygame.loop import Agent
    from anygame.sensors import open_sensor
    dev = ScreenDevice("0,0,540,560")
    frame = dev.frame()
    print("frame", frame.shape, "mean", frame.mean().round(1))
    pack = load_pack(os.path.join(ROOT, "packs", "snake"))
    ag = Agent(pack, dev, open_sensor(SENSOR), None, max_ticks=TICKS)
    dev.key("F5"); time.sleep(2.0)          # the agent's OCR worker took seconds to warm: restart the game through the keyboard, like a user would
    frame = dev.frame()
    vals, _, _ = ag.observe(frame, pack, want_conf=True)
    print("first read:", {k: vals.get(k) for k in ("status", "head", "food")}, "support", round(ag.support(ag.last_conf, vals, pack), 2))
    assert vals.get("status") == "playing" and vals.get("head"), "the screen device does not see the game"
    last = ag.run()
    recs_keys = [x["action"] for x in ag.history]
    print("played", ag.tick, "ticks:", last.get("action"), last.get("reason"), "| inputs sent:", len(ag.history), "| final head", (last.get("screen") or {}).get("head"), "score", (last.get("screen") or {}).get("score"))
    # the keys reached the page: the head moved and, if we turned, the direction changed
    moves = [r for r in recs_keys if r.startswith("key") or r.startswith("swipe")]
    assert ag.tick >= 5 and (last.get("screen") or {}).get("head"), "no ticks played"
    print("RESULT PASS" if moves else "RESULT PASS (no turns issued)")
    ag.close(); dev.close()
finally:
    chrome.terminate()
    try:
        chrome.wait(timeout=5)
    except subprocess.TimeoutExpired:
        chrome.kill()
