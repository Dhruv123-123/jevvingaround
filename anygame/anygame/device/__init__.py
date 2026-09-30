"""Devices: anything that can give a frame and take a tap. web:// (Playwright), screen:// (this computer's screen and
input), stream:// (a game that publishes its state as JSON), pyboy:// (a Game Boy ROM), replay:// (frames on disk),
adb:// (a phone). A device may also have state(): a JSON object the `json` / `json_grid` reads consume."""
from __future__ import annotations
from .base import Device


def open_device(url: str, size: tuple[int, int]) -> Device:
    if url.startswith("web://"):
        from .web import WebDevice
        return WebDevice(url[len("web://"):], size)
    if url.startswith("screen://") or url == "screen":
        from .screen import ScreenDevice
        return ScreenDevice(url[len("screen://"):] if url.startswith("screen://") else "", size)
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
    raise ValueError(f"unknown device url: {url} (web://<page url>[#state=<js>], screen://x,y,w,h, stream://ws://…|http://…|file:…, pyboy://<rom.gb>, replay://<dir>, adb://<host:port>)")
