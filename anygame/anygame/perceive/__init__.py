"""Perception is layered: pixels (bars, colours, blobs) and templates are exact and cost ~1 ms; OCR reads numbers;
only genuinely dynamic objects go to an open-vocabulary detector. A read returns a value for the state and, where
it makes sense, boxes for the HUD."""
from __future__ import annotations
from typing import Any
import numpy as np
from ..geometry import Rect
from ..pack import Pack
from . import bar, blobs, color, ocr, template


def rect_for(pack: Pack, r: dict[str, Any]) -> Rect:
    return pack.zone(r["zone"]).rect if "zone" in r else Rect.parse(r["rect"])


def read_all(pack: Pack, frame: np.ndarray, only: set[str] | None = None, tick: int = 0, previous: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
    """Returns (values, detections, timings_ms). A read with `every: N` is refreshed every N ticks and otherwise carried over."""
    import time
    values: dict[str, Any] = {}
    dets: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    for rid, r in pack.reads.items():
        if only is not None and rid not in only:
            continue
        every = int(r.get("every", 1))
        if every > 1 and tick % every != 1 and previous is not None and rid in previous:
            values[rid] = previous[rid]
            continue
        t0 = time.perf_counter()
        kind = r["kind"]
        zone = pack.zone(r["zone"]) if "zone" in r else None
        rect = rect_for(pack, r)
        if kind == "bar":
            values[rid] = bar.read(frame, rect, r)
        elif kind == "color":
            values[rid] = color.read(frame, rect, r, zone)
        elif kind == "ocr":
            values[rid] = ocr.read(frame, rect, zone, r)
        elif kind == "templates":
            v, d = template.read(frame, rect, zone, r, pack.assets_dir())
            values[rid] = v
            dets += d
        elif kind == "blobs":
            v, d = blobs.read(frame, rect, zone, r)
            values[rid] = v
            dets += d
        elif kind == "vocab":
            from . import vocab
            v, d = vocab.read(frame, rect, zone, r)
            values[rid] = v
            dets += d
        timings[rid] = round((time.perf_counter() - t0) * 1000, 1)
    return values, dets, timings
