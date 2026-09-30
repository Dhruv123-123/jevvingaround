"""The pool: packs the project (and later, everyone) has already learned, indexed by site and by screen fingerprint.
A known game starts instantly: the pack is fetched, not authored. Same index (packs/pool.json) as the extension."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from .fingerprint import distance, fingerprint, from_b64

POOL_URL = os.environ.get("ANYGAME_POOL_URL", "https://raw.githubusercontent.com/Dhruv123-123/jevvingaround/main/anygame/packs/pool.json")
LOCAL_POOL = Path(__file__).resolve().parent.parent / "packs" / "pool.json"


def fetch_pool(timeout: float = 8.0) -> dict[str, Any]:
    """The published index, or the repo's own copy when offline."""
    try:
        import requests
        r = requests.get(POOL_URL, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001
        return json.loads(LOCAL_POOL.read_text()) if LOCAL_POOL.exists() else {"packs": []}


def match(pool: dict[str, Any], url: str | None = None, frame: np.ndarray | None = None, threshold: float = 40.0) -> dict[str, Any] | None:
    """The pool entry for this site (a URL substring) or, failing that, for this screen (nearest fingerprint under the
    threshold). Returns the entry with `how` and `distance` filled in, or None."""
    here = (url or "").lower()
    for p in pool.get("packs", []):
        if any(u and u.lower() in here for u in p.get("urls", [])):
            return {**p, "how": "url", "distance": 0.0}
    if frame is None:
        return None
    fp = fingerprint(frame)
    best: tuple[float, dict[str, Any]] | None = None
    for p in pool.get("packs", []):
        fps = p.get("fingerprints") or {}
        if not isinstance(fps, dict):
            continue
        for b64 in fps.values():
            try:
                d = distance(fp, from_b64(b64))
            except Exception:  # noqa: BLE001
                continue
            if best is None or d < best[0]:
                best = (d, p)
    if best and best[0] <= threshold:
        return {**best[1], "how": "fingerprint", "distance": round(best[0], 1)}
    return None


def install(entry: dict[str, Any], into: Path, timeout: float = 15.0) -> Path:
    """Fetch the entry's pack.yaml into a pack directory (fixtures are not needed to play: the fingerprints stand in)."""
    import requests
    d = into / entry["name"]
    d.mkdir(parents=True, exist_ok=True)
    r = requests.get(entry["yaml_url"], timeout=timeout)
    r.raise_for_status()
    (d / "pack.yaml").write_text(r.text)
    return d


def stamp(pack_dir: Path) -> int:
    """Write the fixtures' fingerprints into pack.yaml (appended as a `fingerprints:` block, so hand-written YAML and
    its comments survive). Returns how many screens were stamped."""
    import cv2
    import yaml
    from .fingerprint import to_b64
    p = pack_dir / "pack.yaml"
    raw = yaml.safe_load(p.read_text()) or {}
    fps: dict[str, str] = dict(raw.get("fingerprints") or {})
    n = 0
    for t in raw.get("tests") or []:
        f = pack_dir / t["frame"]
        if not f.exists():
            continue
        img = cv2.imread(str(f))
        if img is None:
            continue
        key = "main:" + Path(t["frame"]).stem
        fps[key] = to_b64(fingerprint(img))
        n += 1
    if not n:
        return 0
    text = p.read_text()
    if "fingerprints" in raw:
        raw["fingerprints"] = fps
        p.write_text(yaml.safe_dump(raw, sort_keys=False, width=120))
    else:
        block = yaml.safe_dump({"fingerprints": fps}, sort_keys=False, width=120)
        p.write_text(text.rstrip("\n") + "\n" + block)
    return n
