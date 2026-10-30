#!/usr/bin/env python3
"""cline-ready-package-mirror (KNB-1008) — project Chaba's queue + in-flight
+ lifecycle state onto the con01 Cline kanban board as a READ-ONLY
projection. Chaba stays the source of truth; the Cline board is
rebuildable display state.

Mechanism (proven by the KNB-1008 spike, 2026-10-30): the kanban app's
board state lives in board.json under locked read-modify-write; a direct
atomic edit (tmp+rename) is immediately live to `kanban task list` and
the UI — no agent session is spawned. This script never calls task
start; mirrored tasks carry no session and their prompt says so.

Mapping (Chaba -> Cline column):
  queued (action.status=queued)  -> backlog   title `#<pos> <t> [ready|wait]`
  claimed / running              -> in_progress  title `[<host>] <t>`
  card column = review           -> review
  card column = done             -> trash (renders as Done)
  anything else                  -> mirrored task is removed (not in pipeline)

Only tasks whose prompt carries the [CARD:<id>] marker are touched —
pilot/Nest-execution tasks are never modified.

Run: on con01 under cline-board-mirror.timer (job:cline-board-mirror,
rendered from ssot.jobs.yml) or by hand from any host with ssh con01.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

API = os.environ.get(
    "BOARD_API", os.environ.get(
        "RUNNER_API", "https://idc03.taila0626a.ts.net:10000")).rstrip("/")
CLINE_SSH = os.environ.get("CLINE_SSH", "").strip()
CLINE_CONTAINER = os.environ.get("CLINE_CONTAINER", "cline-kanban")
BOARD_JSON = os.environ.get(
    "CLINE_BOARD_JSON",
    "/root/.cline/kanban/workspaces/workspace/board.json")
MARKER = "[CARD:"
TITLE_MAX = 110
PROMPT_MAX = 3800
VISIBLE_ACTION_STATUS = {"queued", "claimed", "running"}

APPLY_JS = r"""
const fs = require('fs');
const ops = JSON.parse(fs.readFileSync(0, 'utf8'));
const p = process.env.BOARD_JSON;
const b = JSON.parse(fs.readFileSync(p, 'utf8'));
const find = (id) => {
  for (const col of b.columns) {
    const i = col.cards.findIndex(t => t.id === id);
    if (i >= 0) return {col, i};
  }
  return null;
};
for (const id of ops.deletes || []) {
  const f = find(id); if (f) f.col.cards.splice(f.i, 1);
}
for (const m of ops.moves || []) {
  const f = find(m.id); if (!f) continue;
  const [task] = f.col.cards.splice(f.i, 1);
  const dest = b.columns.find(c => c.id === m.to);
  if (!dest) { f.col.cards.splice(f.i, 0, task); continue; }
  if (m.title !== undefined) task.title = m.title;
  if (m.prompt !== undefined) task.prompt = m.prompt;
  task.updatedAt = Date.now();
  dest.cards.push(task);
}
for (const u of ops.updates || []) {
  const f = find(u.id); if (!f) continue;
  const t = f.col.cards[f.i];
  if (u.title !== undefined) t.title = u.title;
  if (u.prompt !== undefined) t.prompt = u.prompt;
  t.updatedAt = Date.now();
}
for (const c of ops.creates || []) {
  const dest = b.columns.find(x => x.id === c.column);
  if (!dest || find(c.task.id)) continue;
  const t = c.task; t.createdAt = Date.now(); t.updatedAt = Date.now();
  dest.cards.push(t);
}
const tmp = p + '.tmp';
fs.writeFileSync(tmp, JSON.stringify(b, null, 2));
fs.renameSync(tmp, p);
console.log(JSON.stringify({moves:(ops.moves||[]).length,
  updates:(ops.updates||[]).length, creates:(ops.creates||[]).length,
  deletes:(ops.deletes||[]).length}));
"""


def api_get(path: str) -> dict:
    try:
        with urllib.request.urlopen(API + path, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def cline_exec(argv: list, stdin: bytes = b"") -> str:
    """Run a command inside the cline-kanban container — directly when
    executing on con01 (CLINE_SSH empty), else over ssh."""
    if CLINE_SSH:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               CLINE_SSH, "podman", "exec"]
        cmd += (["-i"] if stdin else [])
        cmd += [CLINE_CONTAINER] + argv
    else:
        cmd = ["podman", "exec"]
        cmd += (["-i"] if stdin else [])
        cmd += [CLINE_CONTAINER] + argv
    r = subprocess.run(cmd, input=stdin or None,
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(
            f"cline exec failed rc={r.returncode}: {r.stderr.decode()[:300]}")
    return r.stdout.decode()


def load_board() -> dict:
    out = cline_exec(["cat", BOARD_JSON])
    return json.loads(out)


def apply_ops(ops: dict) -> str:
    env_prefix = []
    if CLINE_SSH:
        env_prefix = ["-e", f"BOARD_JSON={BOARD_JSON}"]
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               CLINE_SSH, "podman", "exec", "-i"] + env_prefix + \
              [CLINE_CONTAINER, "node", "-e", APPLY_JS]
        r = subprocess.run(cmd, input=json.dumps(ops).encode(),
                           capture_output=True, timeout=60)
    else:
        r = subprocess.run(
            ["podman", "exec", "-i", "-e", f"BOARD_JSON={BOARD_JSON}",
             CLINE_CONTAINER, "node", "-e", APPLY_JS],
            input=json.dumps(ops).encode(), capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(
            f"apply failed rc={r.returncode}: {r.stderr.decode()[:300]}")
    return r.stdout.decode().strip()


def task_id(card_id: str, taken: set) -> str:
    h = hashlib.sha1(card_id.encode()).hexdigest()
    for off in range(0, 30, 5):
        tid = "m" + h[off:off + 4]
        if tid not in taken:
            return tid
    return "m" + h[:4]


def mirrored_tasks(board: dict) -> dict:
    """task_id -> (column_id, task) for mirror-owned tasks only."""
    out = {}
    for col in board.get("columns") or []:
        for t in col.get("cards") or []:
            if MARKER in (t.get("prompt") or ""):
                out[t["id"]] = (col["id"], t)
    return out


def marker_card(prompt: str) -> str:
    i = prompt.find(MARKER)
    if i < 0:
        return ""
    return prompt[i + len(MARKER):].split("]", 1)[0].strip()


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def queued_desired(q: dict) -> tuple:
    """(title, prompt) for a queued card -> backlog task."""
    a = q.get("action") or {}
    if q.get("eligible"):
        tag = "ready:" + ",".join(q["eligible"][:3])
    elif q.get("blocked"):
        why = "; ".join(f"{h}:{r}" for h, r in
                        list(q["blocked"].items())[:3])
        tag = f"wait:{why}"
    else:
        tag = "wait:no runner report"
    title = clip(f"#{q.get('pos')} {q.get('title') or q['id']} [{tag}]",
                 TITLE_MAX)
    contract = " ".join(
        f"{k}={v}" for k, v in a.items() if v not in (None, "", []))
    prompt = clip(
        "MIRROR RECORD — Chaba board projection; do NOT start this task.\n\n"
        f"Card: {q['id']}  ref:{q.get('ref') or '-'}\n"
        f"Queue: #{q.get('pos')} (priority {q.get('priority') or '-'}, "
        f"updated {q.get('updated') or '-'})\n"
        f"Verdict: {tag}\n"
        f"Blocked: {json.dumps(q.get('blocked') or {}, ensure_ascii=False)}\n"
        f"Contract: {contract or '-'}\n"
        f"Unreported runners: {','.join(q.get('unreported') or []) or '-'}\n\n"
        f"{q.get('title') or ''}\n\n{CARD_NOTE}\n\n{MARKER}{q['id']}]",
        PROMPT_MAX)
    return title, prompt


def claimed_desired(c: dict) -> tuple:
    title = clip(f"[{c.get('host') or '?'}] {c.get('title') or c['id']}",
                 TITLE_MAX)
    prompt = clip(
        "MIRROR RECORD — Chaba board projection; do NOT start this task.\n\n"
        f"Card: {c['id']}  ref:{c.get('ref') or '-'}\n"
        f"State: {c.get('status')} on {c.get('host') or '?'} "
        f"(unit {c.get('unit') or '-'}, repo {c.get('repo') or '-'})\n\n"
        f"{c.get('title') or ''}\n\n{CARD_NOTE}\n\n{MARKER}{c['id']}]",
        PROMPT_MAX)
    return title, prompt


def review_desired(c: dict) -> tuple:
    title = clip(f"{c.get('title') or c['id']} [review]", TITLE_MAX)
    prompt = clip(
        "MIRROR RECORD — Chaba board projection; do NOT start this task.\n\n"
        f"Card: {c['id']}  ref:{c.get('ref') or '-'}\n"
        f"State: in Chaba review — pushed, awaiting merge/verify or a "
        f"human gate.\n\n{c.get('title') or ''}\n\n{MARKER}{c['id']}]",
        PROMPT_MAX)
    return title, prompt


CARD_NOTE = ("Close on the Chaba board — this task tracks the card; "
             "edits here do not write back.")


def main() -> int:
    q = api_get("/queue")
    if q.get("error"):
        print(f"warn: /queue unavailable: {q['error']}")
        return 1
    cards_doc = api_get("/cards")
    cards = cards_doc.get("cards") or []
    by_id = {c.get("id"): c for c in cards}

    board = load_board()
    tasks = mirrored_tasks(board)
    taken = {t["id"] for col in board.get("columns") or []
             for t in col.get("cards") or []}

    # desired: card_id -> (column, title, prompt)
    desired = {}
    for item in q.get("queued") or []:
        title, prompt = queued_desired(item)
        desired[item["id"]] = ("backlog", title, prompt)
    for c in q.get("claimed") or []:
        title, prompt = claimed_desired(c)
        desired[c["id"]] = ("in_progress", title, prompt)
    # lifecycle for already-mirrored cards only (don't mirror the whole
    # review column — the board shows the pipeline, not every gate)
    card_by_task = {}
    for tid, (col, t) in tasks.items():
        card_by_task[tid] = marker_card(t.get("prompt") or "")
    for tid, cid in card_by_task.items():
        if cid in desired:
            continue
        c = by_id.get(cid)
        if not c:
            desired[cid] = ("DELETE", "", "")
        elif c.get("column") == "review":
            desired[cid] = ("review", *review_desired(c))
        elif c.get("column") == "done":
            desired[cid] = ("trash", f"{c.get('title') or cid} [done]",
                            f"Done on Chaba.\n\n{MARKER}{cid}]")
        else:
            desired[cid] = ("DELETE", "", "")

    # task_id lookup by card marker for existing tasks
    task_for_card = {card_by_task[tid]: tid for tid in tasks
                     if card_by_task[tid]}

    ops = {"moves": [], "updates": [], "creates": [], "deletes": []}
    for cid, (want_col, title, prompt) in desired.items():
        tid = task_for_card.get(cid)
        if want_col == "DELETE":
            if tid:
                ops["deletes"].append(tid)
            continue
        if tid:
            cur_col, cur = tasks[tid]
            if cur_col != want_col:
                ops["moves"].append(
                    {"id": tid, "to": want_col,
                     "title": title, "prompt": prompt})
            elif cur.get("title") != title or cur.get("prompt") != prompt:
                ops["updates"].append(
                    {"id": tid, "title": title, "prompt": prompt})
        else:
            nid = task_id(cid, taken)
            taken.add(nid)
            ops["creates"].append({
                "column": want_col,
                "task": {"id": nid, "title": title, "prompt": prompt,
                         "startInPlanMode": False,
                         "autoReviewEnabled": False,
                         "autoReviewMode": "commit",
                         "agentId": "cline", "baseRef": "main"}})

    if not any(ops[k] for k in ops):
        print("mirror: no changes")
        return 0
    out = apply_ops(ops)
    print(f"mirror: applied {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
