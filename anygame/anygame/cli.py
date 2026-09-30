from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

PACKS_DIRS = [os.environ.get("ANYGAME_PACKS"), os.path.join(os.path.dirname(__file__), "..", "packs")]


def find_pack(name: str) -> str:
    if os.path.exists(name):
        return name
    for d in PACKS_DIRS:
        if not d:
            continue
        for cand in (os.path.join(d, name, "pack.yaml"), os.path.join(d, name + ".yaml")):
            if os.path.exists(cand):
                return cand
    sys.exit(f"pack '{name}' not found in {[d for d in PACKS_DIRS if d]}")


def cmd_packs(_):
    from .pack import load_pack
    for d in PACKS_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for entry in sorted(os.listdir(d)):
            p = os.path.join(d, entry, "pack.yaml")
            if os.path.exists(p):
                try:
                    pk = load_pack(p)
                    print(f"{pk.name:14} {len(pk.reads)} reads, {len(pk.actions)} actions, {len(pk.questions)} questions, {len(pk.tests)} tests   {p}")
                except Exception as e:  # noqa: BLE001
                    print(f"{entry:14} invalid: {e}")


def cmd_play(a):
    from .device import open_device
    from .hud import Hud
    from .jev import Jev
    from .loop import Agent
    from .pack import load_pack
    pack = load_pack(find_pack(a.pack))
    device = open_device(a.device, pack.size)
    from .sensors import open_sensor
    jev = open_sensor(a.sensor, timeout=float(pack.raw.get("sensor_timeout_s", os.environ.get("ANYGAME_JEV_TIMEOUT", "4"))))
    hud = Hud(a.hud) if a.hud else None
    if hud:
        print(f"HUD on http://localhost:{a.hud}", file=sys.stderr)
    agent = Agent(pack, device, jev, hud, log_path=a.log, max_ticks=a.max_ticks, record_dir=a.record)
    if a.fallback:
        from .fallback import VLMFallback
        agent.fallback = VLMFallback()
        agent.goal = a.goal or ""
        learned = Path(a.fallback if a.fallback != "yes" else str(pack.path.parent / "pack.learned.yaml"))
        def _changed(y, why):
            print(f"pack: {why}", file=sys.stderr)
            if "learned" in why:
                learned.write_text(y)
        agent.on_pack_change = _changed
    try:
        last = agent.run()
    finally:
        device.close()
    summary = {"game": pack.name, "fallback_calls": agent.fallback_calls, "mode": agent.mode, "ticks": agent.tick, "last": last.get("action"), "reason": last.get("reason"), "sensor_errors": agent.errors,
               "total_cost_usd": round(agent.total_cost, 6), "final_screen": {k: v for k, v in (last.get("screen") or {}).items() if not isinstance(v, dict)}}
    print(json.dumps(summary, indent=1))
    if a.record:
        Path(a.record, "summary.json").write_text(json.dumps(summary, indent=1))
    if a.hud and a.hold:
        print("HUD still up; Ctrl-C to exit", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def _match(expected, got, tol=0.05):
    if isinstance(expected, dict) and isinstance(got, dict):
        return all(_match(v, got.get(k), tol) for k, v in expected.items())
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return abs(expected - got) <= max(tol * abs(expected), 0.5 if isinstance(expected, int) else tol)
    if isinstance(expected, list):
        return list(expected) == list(got or [])
    return expected == got


def cmd_eval(a):
    import cv2
    import numpy as np
    from .jev import Jev
    from .loop import Agent
    from .pack import load_pack
    from .perceive import read_all
    pack = load_pack(find_pack(a.pack))
    jev = Jev() if a.sensor == "jev" else None
    failed = 0
    print(f"{pack.name}  sensor={a.sensor}")
    for t in pack.tests:
        frame = cv2.imread(str(pack.path.parent / t["frame"])) if t.get("frame") else np.zeros((pack.size[1], pack.size[0], 3), np.uint8)
        state = json.loads((pack.path.parent / t["state"]).read_text()) if t.get("state") else None
        t0 = time.perf_counter()
        values, _, timings = Agent(pack, device=_Dummy(pack.size), jev=None).observe(frame, state=state)
        ms = (time.perf_counter() - t0) * 1000
        misses = {k: (v, values.get(k)) for k, v in t["expect"].items() if not _match(v, values.get(k))}
        ok = not misses
        line = f"  {'✓' if ok else '✗'} {t.get('frame') or t.get('state')}  reads {ms:.0f} ms"
        if misses:
            line += "  mismatch: " + "; ".join(f"{k}: expected {e} got {g}" for k, (e, g) in misses.items())
        if t.get("expect_action"):
            if jev is None:
                line += "  (action check skipped: no sensor)"
            else:
                ag = Agent(pack, device=_Dummy(pack.size), jev=jev)
                vals, _, _ = ag.observe(frame, state=state)
                res = jev.ask({"game": pack.name, "how_to_play": pack.play, "screen": vals, "recent_actions": []}, ag.questions(vals))
                choice = res["answers"]["action"]["choice"]
                ea = t["expect_action"]
                want = ea.get("one_of") or ([ea["is"]] if "is" in ea else None)
                good = (choice in want) if want else (choice not in ea.get("not", []))
                want = want or [f"anything but {'|'.join(ea.get('not', []))}"]
                ok = ok and good
                line += f"  action {choice} {'✓' if good else '✗ expected ' + '|'.join(want)}"
                if t.get("expect_cell"):
                    cell = res["answers"].get(f"{choice}__cell", {}).get("choice")
                    cg = cell == t["expect_cell"]
                    good = good and cg
                    line += f"  cell {cell} {'✓' if cg else '✗ expected ' + t['expect_cell']}"
                line += f"  jev {res['latency_ms']} ms ${res['cost_usd']:.6f}"
        print(line)
        failed += 0 if ok else 1
    print(f"  {len(pack.tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


def cmd_play_inline(pack_dir, device_url: str, ticks: int, log_path: str | None = None, sensor: str = "jev", record_dir: str | None = None) -> dict:
    """Play a pack for N ticks and return the summary (used by `author --play-ticks` and `bench`)."""
    from .device import open_device
    from .loop import Agent
    from .pack import load_pack
    from .sensors import open_sensor
    pack = load_pack(pack_dir)
    device = open_device(device_url, pack.size)
    jev = open_sensor(sensor, timeout=float(pack.raw.get("sensor_timeout_s", os.environ.get("ANYGAME_JEV_TIMEOUT", "4"))))
    agent = Agent(pack, device, jev, None, log_path=log_path, max_ticks=ticks, record_dir=record_dir)
    try:
        last = agent.run()
    finally:
        device.close()
    recs = [json.loads(l) for l in open(log_path)] if log_path else []
    dec = [r for r in recs if "jev_ms" in r]
    q = lambda a, p: sorted(a)[min(len(a) - 1, int(p * len(a)))] if a else None  # noqa: E731
    return {"game": pack.name, "ticks": agent.tick, "decisions": len(dec), "last": last.get("action"), "reason": last.get("reason"), "sensor_errors": agent.errors,
            "total_cost_usd": round(agent.total_cost, 6), "sensor_ms_p50": q([r["jev_ms"] for r in dec], .5), "sensor_ms_p95": q([r["jev_ms"] for r in dec], .95),
            "final_screen": {k: v for k, v in (last.get("screen") or {}).items() if not isinstance(v, dict)}}


def cmd_battle(a):
    """Two packs, one screen, alternating: each agent acts only when its own act_when holds."""
    from .device import open_device
    from .loop import Agent
    from .pack import load_pack
    from .sensors import open_sensor
    packs = [load_pack(find_pack(a.pack_a)), load_pack(find_pack(a.pack_b))]
    device = open_device(a.device, packs[0].size)
    sensors = [open_sensor(a.sensor_a or a.sensor), open_sensor(a.sensor_b or a.sensor)]
    logs = [a.log and a.log.replace(".jsonl", f"-{i}.jsonl") for i in (1, 2)]
    agents = [Agent(p, device, s, None, log_path=l, max_ticks=None) for p, s, l in zip(packs, sensors, logs)]
    period = 1.0 / max(p.tick_hz for p in packs)
    result = {"a": packs[0].name, "b": packs[1].name, "ticks": 0}
    try:
        for tick in range(a.max_ticks):
            t = time.perf_counter()
            stops = [ag.step().get("action") == "stop" for ag in agents]
            result["ticks"] = tick + 1
            if any(stops):
                break
            dt = time.perf_counter() - t
            if dt < period:
                time.sleep(period - dt)
        final = device.frame()
    finally:
        for ag in agents:
            ag.close()
        device.close()
    from .perceive import read_all
    for key, ag in zip(("a", "b"), agents):
        vals = ag._present(read_all(ag.pack, final)[0])       # both sides read the final screen through their own pack
        stop = ag.pack.raw.get("stop_when")
        result[key + "_status"] = vals.get(stop["read"]) if stop else None
        result[key + "_cost_usd"] = round(ag.total_cost, 6)
        result[key + "_moves"] = sum(1 for h in ag.history if h["action"] not in ("wait", "stop"))
        if key == "a":
            result["final"] = {k: v for k, v in vals.items() if isinstance(v, list) and v and isinstance(v[0], str) and len(v) <= 12}
    print(json.dumps(result, indent=1))


def cmd_bench(a):
    """The same pack, several seeds, one sensor: score, outcome, latency and cost per run, then a summary row."""
    rows = []
    for seed in a.seeds.split(","):
        url = a.device.replace("{seed}", seed)
        import hashlib
        tag = hashlib.sha1(a.device.encode()).hexdigest()[:6]          # the device URL (level, speed…) is part of the run's name
        log = os.path.join(a.out, f"{a.pack}-{a.sensor.replace(':', '_').replace('/', '_')}-{tag}-{seed}.jsonl")
        Path(a.out).mkdir(parents=True, exist_ok=True)
        s = cmd_play_inline(find_pack(a.pack), url, a.max_ticks, log_path=log, sensor=a.sensor)
        score = None
        if a.score_read:
            from .loop import _get
            recs = [json.loads(l) for l in open(log)]
            score = next((_get(r["screen"], a.score_read) for r in reversed(recs) if _get(r.get("screen") or {}, a.score_read) is not None), None)
        row = {"seed": seed, "ticks": s["ticks"], "decisions": s["decisions"], "outcome": s["reason"], "score": score,
               "cost_usd": s["total_cost_usd"], "sensor_ms_p50": s["sensor_ms_p50"], "sensor_ms_p95": s["sensor_ms_p95"], "errors": s["sensor_errors"]}
        rows.append(row)
        print(json.dumps(row), file=sys.stderr)
    summary = {"pack": a.pack, "sensor": a.sensor, "runs": len(rows),
               "wins": sum(1 for r in rows if r["outcome"] and "we_won" in str(r["outcome"])),
               "losses": sum(1 for r in rows if r["outcome"] and "we_lost" in str(r["outcome"])),
               "mean_score": (sum((r["score"] or 0) for r in rows) / len(rows)) if a.score_read else None,
               "mean_ticks": sum(r["ticks"] for r in rows) / len(rows), "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
               "sensor_ms_p50": sorted(r["sensor_ms_p50"] or 0 for r in rows)[len(rows) // 2], "rows": rows}
    print(json.dumps(summary, indent=1))
    if a.append:
        with open(a.append, "a") as f:
            f.write(json.dumps({k: v for k, v in summary.items() if k != "rows"}) + "\n")


def cmd_go(a):
    """The one command: a device URL in, a playing game with a HUD out. Packs are cached per game under --packs."""
    import hashlib
    import re as _re
    from .author import author
    from .device import open_device
    from .hud import Hud
    from .loop import Agent
    from .pack import load_pack
    from .sensors import open_sensor
    base = a.device.split("?", 1)[0]
    name = a.game or _re.sub(r"[^a-z0-9]+", "-", os.path.splitext(os.path.basename(base.rstrip("/")))[0].lower()).strip("-") or "game"
    slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] + "-" + hashlib.sha1(base.encode()).hexdigest()[:6]
    pack_dir = Path(a.packs) / slug
    known = Path(find_pack(a.pack)).parent if a.pack else (pack_dir if (pack_dir / "pack.yaml").exists() and not a.fresh else None)
    if known is None and not a.fresh:
        # the pool first: a game somebody already learned starts now, by site or by what the screen looks like
        from .pool import fetch_pool, install, match
        pool = fetch_pool()
        hit = match(pool, a.device)
        if hit is None and a.device.startswith("web://"):
            try:
                probe_dev = open_device(a.device, tuple(int(v) for v in a.size.split("x")))
                try:
                    hit = match(pool, a.device, probe_dev.frame())
                finally:
                    probe_dev.close()
            except Exception as e:  # noqa: BLE001
                print(f"pool: could not look at the screen ({str(e)[:80]})", file=sys.stderr)
        if hit is not None:
            local = Path(a.packs) / hit["name"]
            known = local if (local / "pack.yaml").exists() else (Path(find_pack(hit["name"])).parent if any(os.path.exists(os.path.join(d or "", hit["name"], "pack.yaml")) for d in PACKS_DIRS if d) else install(hit, Path(a.packs)))
            print(f"pool: \"{hit['name']}\" matches this {'site' if hit['how'] == 'url' else 'screen (distance ' + str(hit['distance']) + ')'}: playing it from {known}", file=sys.stderr)
    if known is None:
        print(f"no pack for {base}: authoring one into {pack_dir} …", file=sys.stderr)
        size = tuple(int(v) for v in a.size.split("x"))
        demo = None
        if a.explore:
            # the explorer plays first: the vision model's minute of play, with intents, is the author's evidence
            from .demo import explore
            dev = open_device(a.device, size)
            try:
                demo = explore(dev, pack_dir / "demo", seconds=a.explore, game=a.game or name, log=lambda m: print(m, file=sys.stderr))
            finally:
                dev.close()
        ok, _ = author(a.device, a.game or name, pack_dir, play=a.play, model=a.model, size=size, play_ticks=a.play_ticks, tune=a.tune,
                       sensor=a.sensor, log=lambda m: print(m, file=sys.stderr), demo=demo, rounds=a.rounds)
        if not ok:
            sys.exit(f"could not write a pack that passes its own tests; see {pack_dir}")
        known = pack_dir
    if a.learn is not None:
        # the application loop: episodes with the fallback on, a replay-verified revision after every loss, restarts
        import argparse as _ap
        print(f"learning {known} over {a.learn or 'endless'} episodes", file=sys.stderr)
        return cmd_learn(_ap.Namespace(pack=str(known), device=a.device, sensor=a.sensor, episodes=a.learn, max_ticks=a.max_ticks, goal=a.game, fallback=True, bank=None, out=None, fresh=a.fresh))
    pack = load_pack(known)
    device = open_device(a.device, pack.size)
    hud = Hud(a.hud) if a.hud else None
    if hud:
        print(f"playing {pack.name} from {known}  HUD on http://localhost:{a.hud}", file=sys.stderr)
    agent = Agent(pack, device, open_sensor(a.sensor), hud, max_ticks=a.max_ticks)
    try:
        last = agent.run()
    finally:
        device.close()
    print(json.dumps({"pack": str(known), "ticks": agent.tick, "reason": last.get("reason"), "total_cost_usd": round(agent.total_cost, 6)}, indent=1))


def cmd_explore(a):
    from .demo import explore
    from .device import open_device
    size = tuple(int(v) for v in a.size.split("x"))
    dev = open_device(a.device, size)
    try:
        out = explore(dev, Path(a.out), seconds=a.seconds, game=a.game, log=lambda m: print(m, file=sys.stderr))
    finally:
        dev.close()
    print(json.dumps({"demo": str(out)}))


def cmd_author(a):
    from .author import author
    size = tuple(int(v) for v in a.size.split("x"))
    ok, out = author(a.device, a.game, Path(a.out), play=a.play, rounds=a.rounds, model=a.model, frames_n=a.frames, size=size,
                     play_ticks=a.play_ticks, tune=a.tune, sensor=a.sensor, score_read=a.score_read, log=lambda m: print(m, file=sys.stderr),
                     demo=Path(a.demo) if a.demo else None)
    print(json.dumps({"pack": str(out / "pack.yaml"), "passes_eval": ok}))
    sys.exit(0 if ok else 1)


class _Dummy:
    def __init__(self, size):
        self._s = size

    def size(self):
        return self._s


def _panel(frame, rec, total_cost, width=330):
    """The frame plus a side panel drawn from the tick's log record: the action, its probabilities, the beliefs,
    the rules that fired, latency and running cost. What the HUD shows, baked into the video."""
    import cv2
    import numpy as np
    h, w = frame.shape[:2]
    out = np.full((h, w + width, 3), (24, 24, 28), np.uint8)
    out[:, :w] = frame
    x, y = w + 14, 30
    white, grey, green, amber = (235, 235, 235), (150, 150, 150), (120, 220, 120), (60, 200, 255)

    def text(t, color=white, scale=0.55, dy=24, bold=1):
        nonlocal y
        cv2.putText(out, t, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, bold, cv2.LINE_AA)
        y += dy

    def bar(label, p, color):
        nonlocal y
        cv2.putText(out, f"{label[:22]}", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, grey, 1, cv2.LINE_AA)
        cv2.rectangle(out, (x, y + 6), (x + width - 28, y + 16), (50, 50, 56), -1)
        cv2.rectangle(out, (x, y + 6), (x + int((width - 28) * max(0.0, min(1.0, p))), y + 16), color, -1)
        cv2.putText(out, f"{p:.2f}", (x + width - 70, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, white, 1, cv2.LINE_AA)
        y += 28

    text(f"tick {rec.get('tick', '?')}", grey, 0.5)
    act = rec.get("action", "")
    text(act if len(act) < 26 else act[:25], green if act not in ("wait", "stop") else grey, 0.75, 34, 2)
    if rec.get("reason"):
        text(str(rec["reason"])[:34], grey, 0.45)
    if rec.get("action_probs"):
        y += 6
        text("action", grey, 0.45, 18)
        for k, v in sorted(rec["action_probs"].items(), key=lambda kv: -kv[1])[:6]:
            bar(k, float(v), green if k == rec.get("choice") else (90, 90, 96))
    # a macro action's computed options (e.g. Tetris landings): list them, the chosen one in green
    for qk, chosen in (rec.get("choices") or {}).items():
        if not qk.endswith("__option"):
            continue
        rid = next((k for k, v in (rec.get("screen") or {}).items() if isinstance(v, dict) and isinstance(v.get("landings"), dict)), None)
        landings = (rec["screen"][rid]["landings"] if rid else {}) or {}
        if not landings:
            continue
        y += 6
        text("computed options", grey, 0.45, 18)
        for lab, desc in list(landings.items())[:6]:
            short = str(desc).replace("bumpiness", "bump").replace("keeps well", "well ok").replace("FILLS the well", "fills well")
            text(f"{lab}  {short[:44]}", green if lab == chosen else grey, 0.38, 16, 1)
    if rec.get("nouls"):
        y += 6
        text("beliefs", grey, 0.45, 18)
        for k, v in rec["nouls"].items():
            bar(k, float(v), amber)
    if rec.get("rules"):
        y += 6
        text("rules", grey, 0.45, 18)
        for r in rec["rules"][-5:]:
            text(str(r)[:40], amber, 0.42, 18)
    y = h - 16
    cv2.putText(out, f"jev {rec.get('jev_ms', '-')} ms   perception {rec.get('perception_ms', '-')} ms   ${total_cost:.5f}",
                (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, grey, 1, cv2.LINE_AA)
    return out



def cmd_learn(a):
    """Episodes: play until the game ends, bank the episode, learn from a loss (a revision that must replay better than
    the pack it replaces), restart, and keep the revision only if it plays better than the incumbent's median episode."""
    from .chat import Chat
    from .device import open_device
    from .fallback import VLMFallback
    from .learn import Bank, Decision, better_episode, hints_text, improve, incident_of, median_episode, outcome
    from .loop import Agent
    from .pack import dump_pack, load_pack, load_pack_text
    from .sensors import open_sensor
    src = Path(find_pack(a.pack))
    pack = load_pack(src)
    pack_dir = src if src.is_dir() else src.parent
    bank = Bank(a.bank or (pack_dir / "bank"))
    learned = Path(a.out or (pack_dir / "pack.learned.yaml"))
    if learned.exists() and not a.fresh:
        pack = load_pack_text(learned.read_text(), pack.name)
        print(f"continuing from {learned} (v{bank.version})", file=sys.stderr)
    chat = Chat()
    device = open_device(a.device, pack.size)
    jev = open_sensor(a.sensor, timeout=float(pack.raw.get("sensor_timeout_s", os.environ.get("ANYGAME_JEV_TIMEOUT", "4"))))
    fallback = VLMFallback(chat) if a.fallback else None
    score_read = pack.raw.get("score_read") or ("score" if "score" in pack.reads else None)
    version, incumbent = bank.version, None
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    # lessons: what survived trial here and on other packs in the pool, shown to the model when it revises
    from .pool import fetch_pool, pool_lessons
    pool_hints = [] if a.fresh else pool_lessons(fetch_pool(), exclude=pack.name)     # --fresh: nothing from the pool, not even lessons
    read_kinds = {str(r.get("kind")) for r in pack.reads.values()}
    try:
        import itertools
        first = len(bank.episodes) + 1
        for n in (itertools.count(first) if a.episodes <= 0 else range(first, first + a.episodes)):
            agent = Agent(pack, device, jev, None, log_path=str(bank.path / f"episode-{n}.jsonl"), max_ticks=a.max_ticks)
            agent.fallback, agent.goal = fallback, a.goal or ""
            agent.stall_ticks = 40          # a game that ended without the pack noticing ends the episode too
            recs, decisions = [], []
            def _rec(rec, frame):
                recs.append(rec)
                if rec.get("choice") and rec.get("choice") != "fallback":
                    decisions.append(Decision(rec, frame.copy(), getattr(agent, "last_state", None)))
                    del decisions[:-12]
            agent.on_record = _rec
            if hasattr(device, "reload"):
                device.reload()          # after the agent is built (its OCR worker is warm), so the game does not run unattended
            try:
                last = agent.run()
            finally:
                agent.close()
            if str(last.get("reason", "")).startswith("stalled") and fallback is not None:
                # the pack could not tell that the game ended: one look by the vision model labels the episode
                verdict = fallback.outcome(device.frame(), a.goal or pack.play[:300])
                last["reason"] = f"stalled: {verdict['outcome']} ({verdict['note']})"
                recs[-1]["reason"] = last["reason"]
                log(f"episode {n}: the screen stalled; the vision model says {verdict['outcome']}: {verdict['note']}")
            if not decisions and str(last.get("reason", "")).startswith("stalled") and "playing" in str(last.get("reason", "")):
                # never acted: the stalled frame itself is the incident, so the model can fix the read that gated us
                stalled_rec = {**last, "choice": "wait", "action": "wait", "never_acted": True}
                decisions.append(Decision(stalled_rec, device.frame().copy(), getattr(agent, "last_state", None)))
            ep = outcome(recs, n, version, score_read)
            log(f"episode {n}: {last.get('action')}{' · ' + str(last.get('reason')) if last.get('reason') else ''} after {agent.tick} ticks, ${agent.total_cost:.4f}" + (f", score {ep['score']}" if ep["score"] is not None else ""))
            if incumbent is not None:
                ref = median_episode(bank.of_version(incumbent[1]))
                if ref and better_episode(ep, ref) and not better_episode(ref, ep):
                    log(f"learn: v{version} played worse than v{incumbent[1]} ({ep['ticks']} vs {ref['ticks']} ticks); reverting")
                    bank.record_trial(version, False)
                    pack, version = load_pack_text(incumbent[0], pack.name), incumbent[1]
                    ep["version"] = version
                else:
                    log(f"learn: v{version} stays ({ep['ticks']} ticks vs the incumbent's median {ref['ticks'] if ref else 'n/a'})")
                    before_pack = load_pack_text(incumbent[0], pack.name)
                    bank.record_trial(version, True, kept_pack=pack, before=before_pack, reason=incumbent[2])
                    new_lessons = bank.lessons[len(bank.lessons) - max(0, len(bank.lessons) - incumbent[3]):]
                    if new_lessons:
                        pack.raw["lessons"] = (pack.raw.get("lessons") or []) + new_lessons
                        log(f"learn: {len(new_lessons)} lesson(s) kept in the pack")
                    learned.write_text(dump_pack(pack.raw))
                incumbent = None
            bank.add_episode(ep)
            if ep["lost"] and decisions:
                inc = incident_of(decisions, ep["reason"], agent.tick)
                earlier = bank.incidents()
                d = bank.add_incident(inc)
                log(f"learn: incident saved to {d}")
                try:
                    hints = hints_text((pack.raw.get("lessons") or []) + pool_hints, read_kinds)
                    res = improve(chat, pack, inc, bank.episodes, log, keep_rejected=bank.path / "rejected", others=earlier, hints=hints, calibrator=bank.calibrator())
                except Exception as e:  # noqa: BLE001
                    res = {"pack": None}
                    log(f"learn: {str(e)[:140]}")
                if res.get("pack") is not None:
                    incumbent = (dump_pack(pack.raw), version, ep["reason"], len(bank.lessons))
                    version += 1
                    pack = res["pack"]
                    bank.add_revision(version, res.get("features"), res["verdict"]["why"])
                    bank.save_version(version, dump_pack(pack.raw))
                    learned.write_text(dump_pack(pack.raw))
                    log(f"learn: v{version} on trial: {res['verdict']['why']}")
    finally:
        device.close()
    best = max(bank.episodes, key=lambda e: (e.get("won", False), not e.get("lost", True), e.get("ticks", 0), e.get("score") or 0))
    summary = {"episodes": len(bank.episodes), "version": version, "learned": str(learned) if learned.exists() else None,
               "best": {"n": best["n"], "ticks": best["ticks"], "reason": best["reason"], "score": best.get("score"), "version": best["version"]},
               "by_version": {str(v): [e["ticks"] for e in bank.of_version(v)] for v in sorted({e["version"] for e in bank.episodes})},
               "revisions": {"kept": sum(1 for r in bank.revisions if r.get("kept")), "reverted": sum(1 for r in bank.revisions if r.get("kept") is False), "on_trial": sum(1 for r in bank.revisions if r.get("kept") is None)},
               "lessons": len(bank.lessons), "calibrator": "active" if bank.calibrator().active else "idle"}
    print(json.dumps(summary, indent=1))


def cmd_stamp(a):
    """Write each pack's fixture fingerprints into its pack.yaml, so the pool can match a screen without images."""
    from .pool import stamp
    dirs = [Path(find_pack(n)).parent for n in a.packs] if a.packs else [Path(d) / e for d in PACKS_DIRS if d and os.path.isdir(d) for e in sorted(os.listdir(d)) if os.path.exists(os.path.join(d, e, "pack.yaml"))]
    for d in dirs:
        n = stamp(d)
        print(f"{d.name}: {n} screen(s) stamped" if n else f"{d.name}: no fixtures")

def cmd_render(a):
    """Frames from --record → an MP4 (ffmpeg from Playwright's bundle or PATH). With --log, each frame gets a
    side panel with that tick's action, probabilities, beliefs, rules, latency and cost."""
    import glob
    import shutil
    import subprocess
    import tempfile
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()      # pip install imageio-ffmpeg: a full static build with libx264
        except Exception:  # noqa: BLE001
            ff = None
    if not ff:
        sys.exit("ffmpeg not found: apt install ffmpeg, or pip install imageio-ffmpeg")
    frames = sorted(glob.glob(os.path.join(a.dir, "*.jpg")))
    if not frames:
        sys.exit(f"no frames in {a.dir}")
    src = a.dir
    if a.log:
        import cv2
        recs = {}
        for line in open(a.log):
            r = json.loads(line)
            recs[int(r["tick"])] = r
        src = tempfile.mkdtemp(prefix="anygame-render-")
        decision, cost = {}, 0.0
        for f in frames:
            tick = int(os.path.splitext(os.path.basename(f))[0])
            rec = recs.get(tick, {})
            if "total_cost_usd" in rec:
                cost = rec["total_cost_usd"]
            if rec.get("action_probs") or rec.get("nouls"):
                decision = rec
            # a waiting tick keeps showing the last decision's probabilities and beliefs under its own label
            shown = {**decision, "tick": tick, "action": rec.get("action", ""), "reason": rec.get("reason"), "rules": rec.get("rules") or decision.get("rules")}
            cv2.imwrite(os.path.join(src, os.path.basename(f)), _panel(cv2.imread(f), shown, cost), [cv2.IMWRITE_JPEG_QUALITY, 90])
    first = int(os.path.splitext(os.path.basename(frames[0]))[0])
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", str(first), "-i", os.path.join(src, "%05d.jpg"),
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", a.out]
    subprocess.run(cmd, check=True)
    print(f"wrote {a.out} ({len(frames)} frames at {a.fps} fps)")


def cmd_record(a):
    import cv2
    from .device import open_device
    from .pack import load_pack
    size = load_pack(find_pack(a.pack)).size if a.pack else (540, 960)
    dev = open_device(a.device, size)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    n, t_end = 0, time.time() + a.seconds
    try:
        while time.time() < t_end:
            cv2.imwrite(os.path.join(a.out, f"{n:05d}.png"), dev.frame())
            n += 1
            time.sleep(1.0 / a.hz)
    finally:
        dev.close()
    print(f"saved {n} frames to {a.out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="anygame", description="One paragraph, any game.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("packs").set_defaults(fn=cmd_packs)
    pl = sub.add_parser("play"); pl.add_argument("pack"); pl.add_argument("--device", default=os.environ.get("DEVICE", "adb")); pl.add_argument("--sensor", default="jev", help="jev | none | random[:seed] | llm:<model>")
    pl.add_argument("--fallback", nargs="?", const="yes", default=None, help="VLM fallback on screens the pack cannot read; optional path for the learned pack (default <pack>/pack.learned.yaml)")
    pl.add_argument("--goal", default=None, help="what the game is about, for the fallback")
    pl.add_argument("--hud", type=int, default=int(os.environ.get("HUD_PORT", "8080"))); pl.add_argument("--no-hud", dest="hud", action="store_const", const=0); pl.add_argument("--log", default="anygame.log.jsonl")
    pl.add_argument("--max-ticks", type=int); pl.add_argument("--hold", action="store_true", help="keep the HUD up after the game ends")
    pl.add_argument("--record", help="save annotated frames here (then `anygame render`)"); pl.set_defaults(fn=cmd_play)
    ln = sub.add_parser("learn", help="play episode after episode; a loss becomes a revision that must replay better; keep what plays better")
    ln.add_argument("pack"); ln.add_argument("--device", default=os.environ.get("DEVICE", "adb")); ln.add_argument("--sensor", default="jev")
    ln.add_argument("--episodes", type=int, default=5, help="0 = forever"); ln.add_argument("--max-ticks", type=int, default=None); ln.add_argument("--goal", default=None)
    ln.add_argument("--fallback", action="store_true", help="VLM fallback on screens the pack cannot read (restart prompts, game-over cards)")
    ln.add_argument("--bank", default=None, help="where episodes and incidents go (default <pack>/bank)"); ln.add_argument("--out", default=None, help="the learned pack (default <pack>/pack.learned.yaml)")
    ln.add_argument("--fresh", action="store_true", help="ignore an existing learned pack"); ln.set_defaults(fn=cmd_learn)
    st = sub.add_parser("stamp", help="write fixture fingerprints into pack.yaml (all packs, or the ones named)"); st.add_argument("packs", nargs="*"); st.set_defaults(fn=cmd_stamp)
    rd = sub.add_parser("render"); rd.add_argument("dir"); rd.add_argument("--out", default="demo.mp4"); rd.add_argument("--fps", type=float, default=4); rd.add_argument("--log", default=None, help="the run's --log file: draws a side panel per tick"); rd.set_defaults(fn=cmd_render)
    ev = sub.add_parser("eval"); ev.add_argument("pack"); ev.add_argument("--sensor", default="none", help="jev | none | random | llm:<model>"); ev.set_defaults(fn=cmd_eval)
    au = sub.add_parser("author", help="a slow model writes the pack from probe frames; the runtime checks it")
    au.add_argument("--device", required=True); au.add_argument("--game", required=True); au.add_argument("--out", required=True)
    au.add_argument("--play", default=None, help="how you want it played, one paragraph (optional)")
    au.add_argument("--rounds", type=int, default=3); au.add_argument("--frames", type=int, default=4); au.add_argument("--size", default="540x560")
    au.add_argument("--model", default=None, help="authoring model (deployment name on Azure); default $ANYGAME_LLM_MODEL, routed by $ANYGAME_LLM_BASE")
    au.add_argument("--play-ticks", type=int, default=0, help="after the pack passes, play it for N ticks")
    au.add_argument("--tune", type=int, default=0, help="rounds of play → digest → revised paragraph/questions/rules (needs --play-ticks)")
    au.add_argument("--sensor", default="jev", help="sensor used for the play rounds: jev | random | llm:<model>")
    au.add_argument("--score-read", default=None, help="read id that measures progress, for keeping the best pack")
    au.add_argument("--demo", default=None, help="a demonstration directory (from `anygame explore` or the extension) to author from instead of probing"); au.set_defaults(fn=cmd_author)
    ex = sub.add_parser("explore", help="let the vision model play for a while and write a demonstration for the author")
    ex.add_argument("--device", required=True); ex.add_argument("--out", required=True); ex.add_argument("--seconds", type=int, default=90)
    ex.add_argument("--game", default=""); ex.add_argument("--size", default="540x560"); ex.set_defaults(fn=cmd_explore)
    go = sub.add_parser("go", help="point it at a game: author a pack if none exists, then play with the HUD")
    go.add_argument("--learn", type=int, default=None, metavar="EPISODES", help="after the pack is known: play episode after episode, learn from every loss (0 = forever)")
    go.add_argument("device", help="web://<url or file>, pyboy://<rom>, adb://<host:port>"); go.add_argument("--game", default=None, help="the game's name and anything the model should know")
    go.add_argument("--play", default=None, help="how you want it played"); go.add_argument("--packs", default=os.environ.get("ANYGAME_HOME", os.path.expanduser("~/.anygame/packs")))
    go.add_argument("--hud", type=int, default=int(os.environ.get("HUD_PORT", "8080"))); go.add_argument("--max-ticks", type=int, default=None); go.add_argument("--size", default="540x560")
    go.add_argument("--model", default=None); go.add_argument("--tune", type=int, default=1); go.add_argument("--play-ticks", type=int, default=40); go.add_argument("--sensor", default="jev")
    go.add_argument("--fresh", action="store_true", help="from scratch: ignore a cached pack, the pool and its lessons"); go.add_argument("--explore", type=int, default=0, metavar="SECONDS", help="let the vision model play first and author from that demonstration"); go.add_argument("--rounds", type=int, default=3, help="authoring rounds until the pack passes its tests"); go.add_argument("--pack", default=None, help="use this bundled pack instead of authoring")
    go.set_defaults(fn=cmd_go)
    bt = sub.add_parser("battle", help="two packs on one screen, alternating turns")
    bt.add_argument("pack_a"); bt.add_argument("pack_b"); bt.add_argument("--device", required=True); bt.add_argument("--sensor", default="jev")
    bt.add_argument("--sensor-a", default=None); bt.add_argument("--sensor-b", default=None); bt.add_argument("--max-ticks", type=int, default=200); bt.add_argument("--log", default=None)
    bt.set_defaults(fn=cmd_battle)
    bn = sub.add_parser("bench", help="one pack, several seeds, one sensor: outcomes, latency and cost")
    bn.add_argument("pack"); bn.add_argument("--device", required=True, help="use {seed} where the seed goes"); bn.add_argument("--sensor", default="jev")
    bn.add_argument("--seeds", default="1,2,3"); bn.add_argument("--max-ticks", type=int, default=200); bn.add_argument("--score-read", default=None)
    bn.add_argument("--out", default="bench"); bn.add_argument("--append", default=None, help="append the summary row to this jsonl")
    bn.set_defaults(fn=cmd_bench)
    rc = sub.add_parser("record"); rc.add_argument("--device", required=True); rc.add_argument("--out", required=True); rc.add_argument("--seconds", type=int, default=20); rc.add_argument("--hz", type=float, default=2); rc.add_argument("--pack"); rc.set_defaults(fn=cmd_record)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
