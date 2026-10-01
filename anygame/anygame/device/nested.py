"""A sandbox the runtime owns: its own X display with the game inside it. The person's desktop, focus, keyboard and
mouse are never touched; what they see, if anything, is a viewer window. `nested://:99?run=<command>&size=1024x768
[&viewer=xephyr][&region=x,y,w,h][&scale=]`. The display is started if it is not up (Xephyr when a viewer is asked
for and installed, which shows the sandbox as a window on the person's desktop; Xvfb otherwise, invisible), the
command is launched with DISPLAY set to it, and frames and input are the screen device bound to that display. On
close, what this device started is stopped."""
from __future__ import annotations
import os
import shlex
import shutil
import subprocess
import time
from urllib.parse import unquote

from .screen import ScreenDevice


class NestedDevice(ScreenDevice):
    def __init__(self, spec: str, size: tuple[int, int] | None = None):
        q: dict[str, str] = {}
        if "?" in spec:
            spec, qs = spec.split("?", 1)
            q = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
        self.display = spec.strip() or ":99"
        self.server = None
        self.child = None
        num = self.display.lstrip(":").split(".")[0]
        if not os.path.exists(f"/tmp/.X11-unix/X{num}"):
            w, h = (q.get("size") or "1024x768").lower().split("x")
            if q.get("viewer") == "xephyr" and shutil.which("Xephyr"):
                cmd = ["Xephyr", self.display, "-screen", f"{w}x{h}", "-title", "anygame sandbox", "-resizeable"]
            else:
                cmd = ["Xvfb", self.display, "-screen", "0", f"{w}x{h}x24", "-nolisten", "tcp"]
            self.server = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                if os.path.exists(f"/tmp/.X11-unix/X{num}"):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError(f"nested://{self.display}: the display server did not come up")
        if q.get("run"):
            env = {**os.environ, "DISPLAY": self.display}
            self.child = subprocess.Popen(shlex.split(unquote(q["run"])), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(float(q.get("wait", 3)))
        region = q.get("region", "")
        extra = "&".join(f"{k}={v}" for k, v in q.items() if k in ("scale", "pause", "budget", "guard"))
        super().__init__(region + (("?" + extra) if extra else ""), size, display=self.display)

    def close(self):
        super().close()
        for p in (self.child, self.server):
            if p is not None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
