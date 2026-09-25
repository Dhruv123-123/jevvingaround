"""Devices: anything that can give a frame and take a tap. web:// (Playwright), replay:// (frames on disk), adb:// (a phone)."""
from __future__ import annotations
from .base import Device


def open_device(url: str, size: tuple[int, int]) -> Device:
    if url.startswith("web://"):
        from .web import WebDevice
        return WebDevice(url[len("web://"):], size)
    if url.startswith("replay://"):
        from .replay import ReplayDevice
        return ReplayDevice(url[len("replay://"):])
    if url.startswith("adb://") or url == "adb":
        from .adb import AdbDevice
        return AdbDevice(url[len("adb://"):] if url.startswith("adb://") else "")
    raise ValueError(f"unknown device url: {url} (web://<page url>, replay://<dir>, adb://<host:port>)")
