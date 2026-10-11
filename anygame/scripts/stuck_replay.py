"""Replays logged runs through anygame/stuck.py: when it would have raised a stall, what was repeated, and how many
steps each raise came after the stall began. Logs carry no frames, so this is the reads-only detector (screen kind,
text, found position and map); a live run also gives it the frame.

    python scripts/stuck_replay.py <log.jsonl> [...]        # several logs are one run, in order
"""
from __future__ import annotations
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.stuck import Stuck  # noqa: E402


def replay(paths, **kw):
    st = Stuck(**kw)
    seen_ticks, n = set(), 0
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            t = int(r.get("tick", r.get("step", 0)))
            if t in seen_ticks:
                continue                       # resumed parts overlap
            seen_ticks.add(t)
            n += 1
            s = r.get("screen") if isinstance(r.get("screen"), dict) else {}
            pos = (s.get("x"), s.get("y"), s.get("map")) if s.get("x") is not None else None
            st.see(t, r.get("action"), kind=s.get("screen", r.get("kind")), text=s.get("text"), pos=pos)
    return st.events, n


def episodes(ev, gap: int = 25):
    """Raises that follow each other (one every `quiet` steps while the stall lasts) are one stall."""
    out = []
    for e in ev:
        if out and e["tick"] - out[-1]["last"] <= gap:
            out[-1]["last"] = e["tick"]
            out[-1]["raises"] += 1
        else:
            out.append({"first": e["tick"], "since": e["since"], "last": e["tick"], "raises": 1, "repeated": e["repeated"]})
    return out


if __name__ == "__main__":
    ev, n = replay(sys.argv[1:])
    eps = episodes(ev)
    print(f"{n} steps, {len(ev)} raises, {len(eps)} stalls ({1000 * len(eps) / max(1, n):.1f} per 1000 steps)")
    for e in eps:
        print(" ", e)
