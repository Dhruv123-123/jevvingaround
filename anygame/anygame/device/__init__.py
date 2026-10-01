"""Devices: anything that can give a frame and take a tap. web:// (Playwright), screen:// (this computer's screen and
input, guarded), window:// (one window, the person's focus untouched), pad:// (a virtual gamepad), nested:// (a
display the runtime owns), coach:// (suggest, never act), stream:// (a game that publishes its state as JSON),
pyboy:// (a Game Boy ROM), replay:// (frames on disk), adb:// (a phone). A device may also have state(): a JSON
object the `json` / `json_grid` reads consume; paused / exhausted: the guard rails the loop honours."""
from __future__ import annotations
from .base import Device


def open_device(url: str, size: tuple[int, int]) -> Device:
    if url.startswith("web://"):
        from .web import WebDevice
        return WebDevice(url[len("web://"):], size)
    if url.startswith("screen://") or url == "screen":
        from .screen import ScreenDevice
        return ScreenDevice(url[len("screen://"):] if url.startswith("screen://") else "", size)
    if url.startswith("window://"):
        from .window import WindowDevice
        return WindowDevice(url[len("window://"):], size)
    if url.startswith("pad://") or url == "pad":
        from .pad import PadDevice
        return PadDevice(url[len("pad://"):] if url.startswith("pad://") else "", size)
    if url.startswith("nested://"):
        from .nested import NestedDevice
        return NestedDevice(url[len("nested://"):], size)
    if url.startswith("coach://"):
        from .coach import CoachDevice
        return CoachDevice(open_device(url[len("coach://"):], size))
    if url.startswith("stream://"):
        from .stream import StreamDevice
        return StreamDevice(url[len("stream://"):], size)
    if url.startswith("replay://"):
        from .replay import ReplayDevice
        return ReplayDevice(url[len("replay://"):])
    if url.startswith("pyboy://"):
        from .pyboy import PyBoyDevice
        return PyBoyDevice(url, size)
    if url.startswith("adb://") or url == "adb":
        from .adb import AdbDevice
        return AdbDevice(url[len("adb://"):] if url.startswith("adb://") else "")
    raise ValueError(f"unknown device url: {url} (web://<page url>[#state=<js>], screen://x,y,w,h, window://<title>, pad://x,y,w,h, nested://:99?run=…, coach://<device>, stream://ws://…|http://…|file:…, pyboy://<rom.gb>, replay://<dir>, adb://<host:port>)")
