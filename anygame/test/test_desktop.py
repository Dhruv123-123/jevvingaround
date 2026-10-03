"""The desktop paths that never take the person's computer over, and the guard rails on the one that shares it.
Needs Xvfb (skipped without); every X-facing test runs on a display of its own."""
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XVFB = shutil.which("Xvfb")


def _xvfb(num: str, size="640x480"):
    p = subprocess.Popen(["Xvfb", f":{num}", "-screen", "0", f"{size}x24", "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(f"/tmp/.X11-unix/X{num}"):
            return p
        time.sleep(0.1)
    p.kill()
    raise RuntimeError("Xvfb did not come up")


def _client(log, title="anygame-xclient", display=":97"):
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "xclient.py"), log, title], env={**os.environ, "DISPLAY": display}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(log) and "ready" in open(log).read():
            return p
        time.sleep(0.1)
    p.kill()
    raise RuntimeError("the x client did not start")


def _desktop_extra():
    import importlib.util
    missing = [m for m in ("mss", "pynput", "Xlib") if importlib.util.find_spec(m) is None]   # not imported: pynput needs a display
    if missing:
        pytest.skip(f"desktop extra not installed ({', '.join(missing)}): pip install -e '.[desktop]'")


@pytest.fixture(scope="module")
def xdisplay():
    if not XVFB:
        pytest.skip("no Xvfb")
    _desktop_extra()
    p = _xvfb("97")
    saved = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = ":97"
    yield ":97"
    if saved is None:
        os.environ.pop("DISPLAY", None)
    else:
        os.environ["DISPLAY"] = saved
    p.terminate()


def test_guard_rails_pause_on_human_input_cap_the_budget_and_stop_on_the_hotkey():
    from anygame.device.guard import Guarded
    class G(Guarded):
        pass
    g = G(); g.pause_s = 0.2; g.max_actions_per_minute = 3
    g._guard_start(listen=False)
    assert not g.listening and not g.paused and not g.exhausted
    # our own injection in flight is not a person
    g._own(100); g._on_human()
    assert not g.paused and g.human_events == 0
    time.sleep(0.2)
    g._on_human()
    assert g.paused and g.human_events == 1
    time.sleep(0.25)
    assert not g.paused
    # the budget: three a minute, the fourth is dropped and counted
    assert [g._allow() for _ in range(4)] == [True, True, True, False] and g.dropped == 1
    # the hotkey: ctrl + alt + q stops; a plain q is a person
    class K:
        def __init__(self, name=None, char=None): self.name, self.char = name, char
    g._on_key(K(char="q")); assert not g.exhausted and g.human_events == 2
    g._on_key(K(name="ctrl_l")); g._on_key(K(name="alt_l")); g._on_key(K(char="q"))
    assert g.exhausted and not g._allow()
    assert g.guard_status()["stopped"] and g.guard_status()["dropped"] == 2
    # the loop honours a paused device: it reads and waits, and says why
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from anygame.sensors import RandomSensor
    from test_state import StateDevice
    class PausedDev(StateDevice):
        paused = True
        def guard_status(self): return {"paused": True, "human_events": 1, "dropped": 0, "stopped": False, "listening": False}
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    ag = Agent(pack, PausedDev([{"snake": [[3, 6], [2, 6], [1, 6]], "food": [9, 2], "score": 0, "over": False}]), RandomSensor(1))
    r = ag.step()
    assert r["action"] == "wait" and r["reason"].startswith("paused") and r["guard"]["paused"] and "jev_ms" not in r


def test_coach_mode_suggests_and_never_acts(tmp_path):
    import cv2
    from anygame.device import open_device
    from anygame.device.coach import CoachDevice
    from anygame.loop import Agent
    from anygame.pack import load_pack
    from anygame.sensors import RandomSensor
    from test_state import StateDevice
    inner = StateDevice([{"snake": [[3 + i, 6], [2 + i, 6], [1 + i, 6]], "food": [9, 2], "score": 0, "over": False} for i in range(4)])
    dev = CoachDevice(inner)
    pack = load_pack(os.path.join(ROOT, "packs", "snake-state"))
    ag = Agent(pack, dev, RandomSensor(2))
    recs = [ag.step() for _ in range(3)]
    acted = [r for r in recs if r.get("choice")]
    assert acted and all(r["action"].startswith("suggest: ") for r in acted) and inner.keys == [] and dev.suggestions
    assert dev.state() == inner.state()
    # coach:// wraps any device url
    d = tmp_path / "frames"; d.mkdir(); cv2.imwrite(str(d / "0.png"), np.zeros((560, 540, 3), np.uint8))
    c = open_device(f"coach://replay://{d}", (540, 560))
    c.key("ArrowUp", 200); c.tap(1, 2); c.mouse_move(3, 4)
    assert c.suggestions == ["key ArrowUp held 200 ms", "tap (1,2)", "move the mouse by 3,4"] and c.inner.actions == []


def test_virtual_gamepad_maps_keys_to_buttons_and_the_stick(xdisplay):
    from anygame.device.pad import PadDevice, button_of, RANGE
    assert button_of("ArrowUp") == "DPAD_UP" and button_of("Space") == "BTN_SOUTH" and button_of("BTN_TR") == "BTN_TR" and button_of("w") == "LS_UP"
    class Fake:
        def __init__(self): self.events = []
        def button(self, name, down): self.events.append(("btn", name, down))
        def axis(self, name, value): self.events.append(("axis", name, value))
        def close(self): self.events.append(("close",))
    fake = Fake()
    dev = PadDevice("0,0,320,240?press=10&guard=0", backend=fake)
    assert dev.size() == (320, 240) and dev.frame().shape == (240, 320, 3)
    dev.key("Space"); dev.key("ArrowLeft", 30); dev.key("RS_UP"); dev.swipe(0, 0, 0, 50, 20); dev.mouse_move(100, -200); dev.tap(5, 5)
    e = fake.events
    assert e[0:2] == [("btn", "BTN_SOUTH", True), ("btn", "BTN_SOUTH", False)]
    assert ("axis", "ABS_HAT0X", -1) in e and ("axis", "ABS_HAT0X", 0) in e
    assert ("axis", "ABS_RY", -RANGE) in e and ("axis", "ABS_HAT0Y", 1) in e
    assert ("axis", "ABS_RX", RANGE // 2) in e and ("axis", "ABS_RY", -RANGE) in e and e[-2:] == [("btn", "BTN_SOUTH", True), ("btn", "BTN_SOUTH", False)]
    dev.close()
    assert e[-1] == ("close",)
    # without /dev/uinput the real backend says so instead of crashing elsewhere
    if not os.path.exists("/dev/uinput"):
        with pytest.raises(Exception):
            PadDevice("0,0,320,240?guard=0")


def test_window_device_delivers_keys_and_clicks_to_one_window_only(xdisplay, tmp_path):
    from anygame.device import open_device
    log = str(tmp_path / "events.txt")
    client = _client(log)
    other_log = str(tmp_path / "other.txt")
    other = _client(other_log, title="another-window")
    try:
        dev = open_device("window://anygame-xclient", (300, 200))
    except Exception:
        client.terminate(); other.terminate(); raise
    try:
        assert dev.size() == (300, 200)
        f = dev.frame()
        assert f.shape == (200, 300, 3) and abs(int(f[100, 150, 0]) - 0xf6) < 8 and abs(int(f[100, 150, 2]) - 0x3b) < 8   # the window's own blue, BGR
        dev.key("ArrowUp"); dev.key("Space", 50); dev.tap(40, 30); dev.mouse_move(10, 10)
        time.sleep(0.5)
        got = open(log).read()
        assert "key 65362 send_event=1" in got and "key 32 send_event=1" in got and "button 1 at 40,30" in got and "motion" in got
        assert "key" not in open(other_log).read()      # the other window saw nothing
        assert dev.guard_status()["dropped"] == 0
        dev.close()
        with pytest.raises(ValueError):
            open_device("window://no-such-window-title", (1, 1))
    finally:
        client.terminate(); other.terminate()


def test_nested_display_runs_the_game_in_a_sandbox_the_runtime_owns(tmp_path):
    if not XVFB:
        pytest.skip("no Xvfb")
    _desktop_extra()
    from anygame.device import open_device
    log = str(tmp_path / "events.txt")
    run = f"{sys.executable} {os.path.join(ROOT, 'test', 'xclient.py')} {log} sandboxed 400 300"
    from urllib.parse import quote
    saved = os.environ.get("DISPLAY")
    dev = open_device(f"nested://:96?run={quote(run)}&size=400x300&wait=1.5&guard=0", (400, 300))
    try:
        assert os.environ.get("DISPLAY") == saved            # the person's display is untouched
        assert dev.server is not None and dev.child is not None and dev.display == ":96"
        for _ in range(30):
            if os.path.exists(log) and "ready" in open(log).read():
                break
            time.sleep(0.1)
        f = dev.frame()
        assert f.shape == (300, 400, 3) and abs(int(f[150, 200, 0]) - 0xf6) < 8      # the client's blue, through the nested display
        dev.key("ArrowRight"); dev.tap(50, 60)
        time.sleep(0.5)
        got = open(log).read()
        assert "key 65363 send_event=0" in got and "button 1 at 40,40" in got        # real X input (XTest), not synthetic; the window sits at (10,20)
    finally:
        dev.close()
        import gc; gc.collect()
    assert not os.path.exists("/tmp/.X11-unix/X96") or dev.server.poll() is not None
