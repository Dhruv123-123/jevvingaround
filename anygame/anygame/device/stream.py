"""A game that tells you its state. The stream is the source of truth for `json` / `json_grid` reads; pixels are
optional. Transports: `stream://ws://host:port/path` (each message a JSON object, the latest one is the state; actions
are sent back as JSON), `stream://http://host/state` (polled), `stream://file:/path/state.json` (rewritten by the game),
`stream://stdin` (JSON lines). `?input=<device url>` pairs an input device (screen://…, web://…) for keys and taps
and, when it has frames, for the picture; otherwise the frame is a blank canvas and keys go back on the socket."""
from __future__ import annotations
import json
import sys
import threading
from typing import Any

import numpy as np

from .base import Device


class StreamDevice(Device):
    def __init__(self, spec: str, size: tuple[int, int] = (320, 240)):
        self._input: Device | None = None
        self._latest: Any = None
        self._lock = threading.Lock()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop = False
        q: dict[str, str] = {}
        if "?input=" in spec:
            spec, inp = spec.split("?input=", 1)
            q["input"] = inp
        self.url = spec
        if q.get("input"):
            from . import open_device
            self._input = open_device(q["input"], size)
        self._size = self._input.size() if self._input else size
        if spec.startswith("ws://") or spec.startswith("wss://"):
            self._start_ws(spec)
        elif spec.startswith("file:"):
            self._path = spec[len("file:"):]
        elif spec.startswith("http://") or spec.startswith("https://"):
            self._http = spec
        elif spec == "stdin":
            self._start_stdin()
        else:
            raise ValueError(f"stream:// needs ws://, http://, file: or stdin, got {spec!r}")

    # ---- transports ------------------------------------------------------------------------------
    def _start_ws(self, url: str) -> None:
        import websocket   # websocket-client

        def on_message(_ws, msg):
            try:
                v = json.loads(msg)
            except json.JSONDecodeError:
                return
            with self._lock:
                self._latest = v

        self._ws = websocket.WebSocketApp(url, on_message=on_message)
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()

    def _start_stdin(self) -> None:
        def pump():
            for line in sys.stdin:
                try:
                    v = json.loads(line)
                except json.JSONDecodeError:
                    continue
                with self._lock:
                    self._latest = v
        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()

    # ---- the device --------------------------------------------------------------------------------
    def state(self) -> Any:
        if hasattr(self, "_path"):
            try:
                with open(self._path) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return self._latest
        if hasattr(self, "_http"):
            import requests
            try:
                r = requests.get(self._http, timeout=2)
                if r.ok:
                    with self._lock:
                        self._latest = r.json()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            return self._latest

    def size(self):
        return self._size

    def frame(self):
        if self._input is not None:
            return self._input.frame()
        return np.zeros((self._size[1], self._size[0], 3), np.uint8)

    def send(self, payload: dict[str, Any]) -> None:
        if self._ws is not None:
            try:
                self._ws.send(json.dumps(payload))
            except Exception:  # noqa: BLE001
                pass
        elif hasattr(self, "_http"):
            import requests
            try:
                requests.post(self._http, json=payload, timeout=2)
            except Exception:  # noqa: BLE001
                pass
        else:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()

    def tap(self, x, y):
        if self._input is not None:
            return self._input.tap(x, y)
        self.send({"tap": [int(x), int(y)]})

    def swipe(self, x0, y0, x1, y1, ms=120):
        if self._input is not None:
            return self._input.swipe(x0, y0, x1, y1, ms)
        self.send({"swipe": [int(x0), int(y0), int(x1), int(y1)], "ms": ms})

    def key(self, name):
        if self._input is not None:
            return self._input.key(name)
        self.send({"key": name})

    def close(self):
        self._stop = True
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._input is not None:
            self._input.close()
