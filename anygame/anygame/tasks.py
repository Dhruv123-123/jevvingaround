"""Tasks: goals the runtime can verify from the reads, and a setter that proposes new ones. SIMA 2's self-improvement
loop is a task setter plus a reward model over self-generated play; here the setter is the chat model looking at the
typed frame and the frame, the reward is the task's `done` condition evaluated by the compiler every tick, and the
practice is banked as success spans (positive incidents) the learning loop must keep allowed. The decider never
trains: it is told the task beside the paragraph, and what it learns is the pack."""
from __future__ import annotations
import json
import re
from typing import Any

import numpy as np

from .pack import Pack, PackError, TASK_CATEGORIES, check_tasks

SETTER = """You set practice tasks for a game-playing runtime. The player is a fast judgment model that sees only the
compiled reads below (labels, numbers, cells) and is told one task at a time beside the play notes. A task is
verified by the runtime from the reads, so its `done` must be a condition on a read id (or id.path into a read
that returns an object) that the frame makes true when the task is achieved, and that is false now.

Propose tasks that are achievable from this state within the limit, concrete, and varied across categories;
prefer the categories listed as weakest. Never propose a task whose done condition already holds, or one that
no read can verify. A task must be achievable again on any later frame, not only this one: never test the exact
cell of a located thing (the food moves, the head moves); test counts, scores, statuses, relations (around,
runs, margin) and thresholds instead. Answer with ONE JSON array of task objects:
[{"id": "<snake_case>", "instruction": "<one line the player follows>",
  "done": {"read": "<read id or id.path>", "equals"|"in"|"not"|"gte"|"lte": <value>}  (or a list of such conditions, all must hold),
  "when": {... optional: when the task is available ...},
  "hold_ticks": 1, "limit_ticks": <ticks>, "category": "<one of %s>"}]
No prose outside the array."""


def task_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per task and per category: attempts, completions, success rate, median ticks to complete."""
    by_task: dict[str, dict[str, Any]] = {}
    by_cat: dict[str, dict[str, Any]] = {}
    for r in results:
        for key, table in ((r.get("id"), by_task), (r.get("category", "other"), by_cat)):
            if key is None:
                continue
            t = table.setdefault(str(key), {"attempts": 0, "done": 0, "ticks": [], "category": r.get("category", "other")})
            t["attempts"] += 1
            if r.get("outcome") == "done":
                t["done"] += 1
                t["ticks"].append(int(r.get("ticks", 0)))
    for table in (by_task, by_cat):
        for t in table.values():
            t["rate"] = round(t["done"] / t["attempts"], 3) if t["attempts"] else None
            tk = sorted(t.pop("ticks"))
            t["median_ticks"] = tk[len(tk) // 2] if tk else None
    return {"tasks": by_task, "categories": by_cat}


def choose_order(tasks: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[str]:
    """The setter's preference: tasks in the weakest categories first, least attempted first within a category."""
    st = task_stats(results)
    def key(t: dict[str, Any]):
        c = st["categories"].get(t.get("category", "other"), {})
        tt = st["tasks"].get(t["id"], {})
        return (c.get("rate") if c.get("rate") is not None else -1.0, tt.get("attempts", 0))
    return [t["id"] for t in sorted(tasks, key=key)]


def weakest_categories(results: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[str]:
    st = task_stats(results)["categories"]
    have = {t.get("category", "other") for t in tasks}
    scored = sorted(((st[c]["rate"] if st[c]["rate"] is not None else 0.0, c) for c in st), key=lambda x: x[0])
    out = [c for _, c in scored[:2]]
    out += [c for c in TASK_CATEGORIES if c not in have and c not in out][:2]
    return out


def _data_url(frame: np.ndarray) -> str:
    from .author import _b64
    return _b64(frame)


def propose_tasks(chat, pack: Pack, frame: np.ndarray, values: dict[str, Any], results: list[dict[str, Any]] | None = None,
                  k: int = 3, log=lambda m: None, game: str = "") -> list[dict[str, Any]]:
    """Ask the chat model for up to k new tasks from the current typed frame and frame; returns the ones that validate
    against the pack's reads (and are not already there). Nothing is written: the caller decides where they go."""
    results = results or []
    reads = {rid: {kk: vv for kk, vv in r.items() if kk in ("kind", "options", "symbol", "in", "of", "zone", "parse")} for rid, r in pack.reads.items()}
    shown = {kk: vv for kk, vv in values.items() if not str(kk).endswith("_prev")}
    st = task_stats(results)
    weak = weakest_categories(results, pack.tasks)
    text = (f"Game: {game or pack.name}. Play notes: {pack.play[:600]}\n\nREADS (id → definition): {json.dumps(reads)[:2500]}\n\n"
            f"CURRENT VALUES: {json.dumps(shown, default=str)[:2500]}\n\nACTIONS: {[a.id for a in pack.actions]}\n\n"
            f"EXISTING TASKS: {json.dumps([{kk: t[kk] for kk in ('id', 'instruction', 'done', 'category', 'limit_ticks')} for t in pack.tasks])[:2000]}\n"
            f"RECORD per category (rate = completions / attempts): {json.dumps(st['categories'])}\nWEAKEST categories to prefer: {weak}\n\n"
            f"Propose up to {k} NEW tasks (ids not in the existing list).")
    messages = [{"role": "system", "content": SETTER % "|".join(TASK_CATEGORIES)},
                {"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": _data_url(frame)}}]}]
    out: list[dict[str, Any]] = []
    try:
        reply = chat.complete(messages, max_tokens=2500, temperature=0.3)[0]
    except Exception as e:  # noqa: BLE001
        log(f"tasks: setter failed: {str(e)[:120]}")
        return out
    m = re.search(r"\[.*\]", reply, re.S)
    try:
        arr = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        log("tasks: the setter's answer was not a JSON array")
        return out
    have = {t["id"] for t in pack.tasks}
    for t in arr if isinstance(arr, list) else []:
        if not isinstance(t, dict):
            continue
        t["id"] = re.sub(r"[^a-z0-9_]+", "_", str(t.get("id", "")).lower()).strip("_")[:40]
        if not t["id"] or t["id"] in have:
            continue
        try:
            ok = check_tasks([t], pack.reads, "setter")[0]
        except PackError as e:
            log(f"tasks: rejected {t.get('id')}: {str(e)[:100]}")
            continue
        # a task whose done condition already holds is not a task
        from .loop import Agent
        if all(Agent._cond(c, values) for c in ok["done"]):
            log(f"tasks: rejected {ok['id']}: already done on this frame")
            continue
        narrow = cell_task(ok, pack.reads)
        if narrow:
            log(f"tasks: rejected {ok['id']}: tests the exact cell of {narrow}; it would hold only on this frame")
            continue
        have.add(ok["id"])
        out.append(ok)
        if len(out) >= k:
            break
    return out


def cell_task(task: dict[str, Any], reads: dict[str, Any]) -> str:
    """The located read a task's condition pins to an exact cell (equals/in on a locate read), or ''. Such a task
    holds only on the frame it was written from: the same trap as a cell rule."""
    for c in list(task.get("done") or []) + ([task["when"]] if task.get("when") else []):
        rid = str(c.get("read", "")).split(".")[0]
        if (reads.get(rid) or {}).get("kind") == "locate" and ("equals" in c or "in" in c) and str(c.get("read")) == rid:
            return rid
    return ""


def tasks_text(tasks: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    """The task record as a line for logs and the revision prompt."""
    if not tasks:
        return ""
    st = task_stats(results)["tasks"]
    return "TASKS (practice goals; rate = completions / attempts): " + "; ".join(
        f"{t['id']} [{t.get('category', 'other')}] " + (f"{st[t['id']]['done']}/{st[t['id']]['attempts']}" if t["id"] in st else "untried") for t in tasks)
