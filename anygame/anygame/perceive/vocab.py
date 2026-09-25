"""Open-vocabulary detection (YOLO-World via ultralytics) prompted with the pack's words. Optional dependency."""
from __future__ import annotations
import numpy as np
from .common import mean_color, nearest_named

_model = None
_classes: list[str] | None = None


def _load():
    global _model
    if _model is None:
        try:
            from ultralytics import YOLO
        except ImportError as e:  # noqa: F841
            raise RuntimeError("read kind 'vocab' needs `pip install ultralytics` (or anygame[vocab])")
        _model = YOLO("yolov8s-worldv2.pt")
    return _model


def read(frame, rect, zone, r):
    global _classes
    m = _load()
    prompts = list(r["prompts"])
    if _classes != prompts:
        m.set_classes(prompts)
        _classes = prompts
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = rect.px(w, h)
    img = frame[y0:y1, x0:x1]
    res = m.predict(img, imgsz=int(r.get("imgsz", 416)), conf=float(r.get("conf", 0.2)), verbose=False, device="cpu")[0]
    items, dets = [], []
    sides = r.get("side_by_color")
    for b in res.boxes:
        bx0, by0, bx1, by1 = [int(v) for v in b.xyxy[0].tolist()]
        label = prompts[int(b.cls[0])]
        conf = float(b.conf[0])
        cx, cy = (x0 + (bx0 + bx1) / 2) / w, (y0 + (by0 + by1) / 2) / h
        cell = zone.cell_of(cx, cy) if zone else None
        item = {"what": label, "conf": round(conf, 2), "cell": cell.split(".", 1)[1] if cell else None}
        if sides:
            patch = img[max(0, by0):by1, max(0, bx0):bx1]
            if patch.size:
                item["side"], _ = nearest_named(mean_color(patch), sides)
        items.append(item)
        dets.append({"label": f"{item.get('side', '')} {label}".strip(), "conf": conf, "rect": (x0 + bx0, y0 + by0, x0 + bx1, y0 + by1)})
    return items[: int(r.get("max", 30))], dets
