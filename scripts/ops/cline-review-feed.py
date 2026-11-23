#!/usr/bin/env python3
"""cline-review-feed (KNB-1009) — drain the Chaba review column's
mechanical/bounded subset through the con01 Cline kanban.

Flow per run (default: all phases, dry-run unless --execute):
  REPORT   for every [CARDREVIEW:<card>] task whose session ended, verify
           the declared artifacts (verdict.json parses + evidence.md
           non-empty), collect the worktree diff, post a verdict comms
           line to the Chaba card and raise a /request with
           close/keep/requeue options + a ★ suggestion. The task is then
           moved to the Cline board's review column. Nothing on the Chaba
           card is ever auto-closed — humans keep the gate.
  SELECT   pick cline-suitable review cards (auto-incident prefixes get an
           evidence-pack prompt; bounded deliverables get a done-condition
           check). Excludes cards with open human requests, secret/host
           mutation keywords, and cards already fed.
  CREATE   create + start Cline tasks (ollama only by default — zero paid
           spend) up to MAX_TASKS concurrent [CARDREVIEW:] tasks.

Dedupe (the lane-cms 5x-repost bug): a state file records the last
reported (task_id, column, updatedAt) per card; an unchanged tuple skips
reporting entirely, and the card's own comms/requests are scanned before
any write so a lost state file still cannot double-post.

Runs anywhere with `ssh con01` (CLINE_SSH, default con01) or locally on
con01 (CLINE_SSH=""). Cline's workspace is disposable: prompts carry the
card spec + evidence inline, never a repo mount or creds.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
CLINE_SSH = os.environ.get("CLINE_SSH", "con01").strip()
CONTAINER = os.environ.get("CLINE_CONTAINER", "cline-kanban")
BOARD_JSON = os.environ.get(
    "CLINE_BOARD_JSON",
    "/root/.cline/kanban/workspaces/workspace/board.json")
WORKTREE_ROOT = "/root/.cline/worktrees"
PROJECT_PATH = "/workspace"
RUNTIME_HOST = "0.0.0.0"
RUNTIME_PORT = "3485"
MARKER = "[CARDREVIEW:"
MIRROR_MARKER = "[CARD:"  # owned by cline-board-mirror — never touch

TITLE_MAX = 110
PROMPT_MAX = 3900
SPEC_CHARS = 2200
COMMS_KEEP = 12
ACTOR = "devin"

MAX_TASKS = 3
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen2.5:7b"
ALLOWED_MODELS = {("ollama", "qwen2.5:7b"), ("ollama", "qwen3:4b")}

INCIDENT_PREFIXES = (
    "logs-auto", "runner-auto", "cms-auto", "disk-auto", "vcast-auto")
EXCLUDE_WORDS = (
    "secret", "credential", "password", "apikey", "api-key", "token",
    "security", "deploy")
VERDICT_SUGGEST = {"close": "close", "hold": "keep", "investigate": "requeue"}
DECISION_OPTIONS = [
    {"id": "close", "label": "close card", "action": "close"},
    {"id": "keep", "label": "keep in review", "action": "none"},
    {"id": "requeue", "label": "requeue for another pass", "action": "retry"},
]
VERDICTS = {"close", "hold", "investigate"}

STATE_PATH = Path(os.environ.get(
    "XDG_STATE_HOME", Path.home() / ".local" / "state")) / \
    "chaba" / "cline-review-feed.json"

MOVE_JS = r"""
const fs = require('fs');
const p = process.env.BOARD_JSON;
const b = JSON.parse(fs.readFileSync(p, 'utf8'));
const id = process.env.TASK_ID, to = process.env.DEST_COL;
let found = null;
for (const col of b.columns) {
  const i = col.cards.findIndex(t => t.id === id);
  if (i >= 0) { found = {col, i}; break; }
}
if (!found) { console.log(JSON.stringify({moved: 0, why: 'not found'})); process.exit(0); }
const [task] = found.col.cards.splice(found.i, 1);
const dest = b.columns.find(c => c.id === to);
if (!dest) { found.col.cards.splice(found.i, 0, task);
  console.log(JSON.stringify({moved: 0, why: 'no dest'})); process.exit(0); }
task.updatedAt = Date.now();
dest.cards.push(task);
const tmp = p + '.tmp';
fs.writeFileSync(tmp, JSON.stringify(b, null, 2));
fs.renameSync(tmp, p);
console.log(JSON.stringify({moved: 1}));
"""

INCIDENT_PROMPT = """You are evidence-checking Chaba auto-incident card "{title}".

Claimed condition (as recorded by the monitor):
{claim}

Recent card comms (oldest to newest):
{comms}

You work in a disposable workspace with NO access to the chaba repo or live hosts — judge the claim only from the evidence inline above.
Produce TWO files in the workspace:
- verdict.json — {{"verdict": "close|hold|investigate", "confidence": "low|medium|high", "reason": "<one line>"}} where close=evidence shows the condition resolved, hold=unverifiable/likely still open, investigate=evidence contradicts or is missing.
- evidence.md — what the evidence shows, the gaps, and the suggested human action.
You MUST create both files with the editor/write tool — do NOT paste contents as chat text; a reply without files on disk is a failure. Do not commit, push, or open a PR.

{marker}]"""

DELIVERABLE_PROMPT = """You are reviewing Chaba kanban card "{title}" — a bounded deliverable that reports itself done and sits in the review column waiting on a human verdict.

Card spec:
{spec}
{note_block}
Recent card comms (oldest to newest):
{comms}

You work in a disposable workspace with NO access to the chaba repo or live hosts — judge the done-claim only from the evidence inline above.
Produce TWO files in the workspace:
- verdict.json — {{"verdict": "close|hold|investigate", "confidence": "low|medium|high", "reason": "<one line>"}} where close=evidence supports the done-condition, hold=unverifiable, investigate=evidence contradicts or is missing.
- evidence.md — what the evidence shows, the gaps, and the suggested human action.
You MUST create both files with the editor/write tool — do NOT paste contents as chat text; a reply without files on disk is a failure. Do not commit, push, or open a PR.

{marker}]"""


# ---------- container / kanban plumbing (same shape as the nest bridge)

def _exec_cmd(argv, stdin=b"", env=()):
    """podman exec argv; over ssh the whole remote command is shlex-joined —
    argv elements carry shell metachars ($O, |, >, quotes) that the remote
    login shell would otherwise re-expand."""
    base = ["podman", "exec"]
    base += (["-i"] if stdin else [])
    for e in env:
        base += ["--env", e]
    base += [CONTAINER] + list(argv)
    if CLINE_SSH:
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                CLINE_SSH, shlex.join(base)]
    return base


def cline_exec(argv, stdin=b"", timeout=60, allowed_codes=(0,), env=()):
    r = subprocess.run(_exec_cmd(argv, stdin, env), input=stdin or None,
                       capture_output=True, timeout=timeout)
    if r.returncode not in allowed_codes:
        raise RuntimeError(
            f"cline exec failed rc={r.returncode}: {r.stderr.decode()[:300]}")
    return r.stdout.decode()


def _read_container_file(path):
    r = subprocess.run(
        _exec_cmd(["cat", "--", path]), capture_output=True,
        text=True, timeout=30)
    return r.stdout if r.returncode == 0 else ""


def run_container(argv, timeout=60, allowed_codes=(0,), env=()):
    """Run inside the container; the kanban CLI drops stdout past ~8KB on a
    pipe, so redirect to files and read them back (bridge.py pattern)."""
    stamp = f"{os.getpid()}-{time.time_ns()}"
    out_t, err_t, rc_t = (f"/tmp/crf-{stamp}.{s}" for s in ("out", "err", "rc"))
    env = [f"KANBAN_RUNTIME_HOST={RUNTIME_HOST}",
           f"KANBAN_RUNTIME_PORT={RUNTIME_PORT}",
           f"O={out_t}", f"E={err_t}", f"R={rc_t}", *env]
    cmd = _exec_cmd(
        ["sh", "-c", '"$@" >"$O" 2>"$E"; printf "%s" "$?" >"$R"',
         "sh", *argv], env=env)
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = _read_container_file(out_t)
        stderr = _read_container_file(err_t)
        rc_raw = _read_container_file(rc_t).strip()
        rc = int(rc_raw) if rc_raw.isdigit() else -1
    finally:
        subprocess.run(_exec_cmd(["rm", "-f", out_t, err_t, rc_t]),
                       capture_output=True, timeout=30)
    if rc not in allowed_codes:
        detail = (stderr or stdout).strip()[:400]
        raise RuntimeError(f"container command failed ({rc}): {detail}")
    return stdout


def run_kanban(args, timeout=60):
    out = run_container(["kanban", *args], timeout=timeout)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kanban CLI returned invalid JSON: {out[:300]}") \
            from exc
    if payload.get("ok") is not True:
        raise RuntimeError(f"kanban error: {payload.get('error', 'unknown')}")
    return payload


def load_board():
    return json.loads(cline_exec(["cat", BOARD_JSON]))


def review_tasks(board):
    """card_id -> (task, column_id) for feed-owned tasks only."""
    out = {}
    for col in board.get("columns") or []:
        for t in col.get("cards") or []:
            p = t.get("prompt") or ""
            if MARKER in p:
                cid = p.split(MARKER, 1)[1].split("]", 1)[0].strip()
                out[cid] = (t, col["id"])
    return out


def agent_ended(task_id):
    out = run_container([
        "sh", "-c",
        "grep '\"agent_end\"' /root/.cline/data/logs/hooks.jsonl 2>/dev/null"
        f" | grep '\"rootSessionId\":\"{task_id}-' | tail -1",
    ], allowed_codes=(0, 1))
    return bool(out.strip())


def collect_patch(worktree, out_path):
    tracked = run_container(["git", "-C", worktree, "diff", "--binary", "HEAD"])
    untracked = run_container([
        "git", "-C", worktree, "ls-files", "--others",
        "--exclude-standard", "-z"])
    chunks = [tracked] if tracked else []
    for rel in (p for p in untracked.split("\0") if p):
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe untracked path in worktree: {rel}")
        diff = run_container(
            ["git", "-C", worktree, "diff", "--binary", "--no-index",
             "--", "/dev/null", f"{worktree}/{rel}"], allowed_codes=(0, 1))
        if diff:
            chunks.append(diff)
    patch = "".join(chunks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(patch)
    tmp.replace(out_path)
    return patch


def move_task(task_id, dest_col, execute):
    if not execute:
        return {"dry": True}
    out = run_container(
        ["node", "-e", MOVE_JS],
        env=[f"BOARD_JSON={BOARD_JSON}", f"TASK_ID={task_id}",
             f"DEST_COL={dest_col}"])
    return json.loads(out)


# ---------- chaba board-api

def api_get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read())


def api_post(path, body):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------- state

def load_state(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"cards": {}}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    tmp.replace(path)


# ---------- select

def slugify(s, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:n].strip("-") or "x"


def open_human_requests(card):
    out = []
    for r in card.get("requests") or []:
        if r.get("status") != "open":
            continue
        if str(r.get("id") or "").startswith("cline-drafted-verdict"):
            continue  # our own pending decision — still "fed", not awaiting
        if r.get("to", "tony") == "tony":
            out.append(r)
    return out


def classify(card, fed_ids):
    """-> (kind, reason) kind in incident|deliverable|None(skip)."""
    cid = card.get("id") or ""
    if card.get("column") != "review":
        return None, "not in review"
    if cid in fed_ids:
        return None, "already has a CARDREVIEW task"
    if open_human_requests(card):
        return None, "open request awaiting tony"
    if any(str(r.get("id") or "").startswith("cline-drafted-verdict")
           and r.get("status") == "open"
           for r in card.get("requests") or []):
        return None, "cline verdict request already pending"
    hay = " ".join([cid, str(card.get("title") or ""),
                    " ".join(card.get("tags") or [])]).lower()
    if any(w in hay for w in EXCLUDE_WORDS):
        return None, "excluded keyword (secret/host mutation surface)"
    if cid.startswith(INCIDENT_PREFIXES):
        return "incident", "auto-incident evidence check"
    spec = str(card.get("spec") or "").strip()
    note = str(card.get("note") or "").strip()
    if spec or note:
        return "deliverable", "bounded deliverable / done-claim check"
    return None, "no spec or claim to check"


def comms_excerpt(card, budget=1400):
    """Newest comms lines that fit — oldest drop first. Never let comms
    tail-truncate the prompt (the instructions + marker sit at the END —
    a blind [:PROMPT_MAX] slice cut them off once, leaving a task that
    produced nothing)."""
    lines = []
    for m in reversed((card.get("comms") or [])[-COMMS_KEEP:]):
        text = re.sub(r"\s+", " ", str(m.get("text") or ""))[:220]
        line = f"- {m.get('at')} {m.get('from')}: {text}"
        if sum(len(l) + 1 for l in lines) + len(line) + 1 > budget:
            break
        lines.append(line)
    return "\n".join(reversed(lines)) or "- (none)"


def build_prompt(card, kind):
    cid = card["id"]
    title = str(card.get("title") or cid).strip()
    spec = str(card.get("spec") or "").strip()
    note = str(card.get("note") or "").strip()
    if kind == "incident":
        prompt = INCIDENT_PROMPT.format(
            title=title, claim=(note or spec or "(none recorded)")[:SPEC_CHARS],
            comms=comms_excerpt(card), marker=f"{MARKER}{cid}")
    else:
        prompt = DELIVERABLE_PROMPT.format(
            title=title, spec=spec[:SPEC_CHARS] or "(no spec)",
            note_block=(f"\nCard note: {note[:600]}\n" if note else ""),
            comms=comms_excerpt(card), marker=f"{MARKER}{cid}")
    # hard cap with room for the kanban CLI's own limit — comms budget
    # above keeps the instructions+marker tail intact
    if len(prompt) > PROMPT_MAX:
        head, sep, tail = prompt.rpartition("\n\n[CARDREVIEW:")
        prompt = head[:PROMPT_MAX - len(sep + tail + "]") - 20] + \
            "\n…[truncated]" + sep + tail + "]"
    return prompt


def task_title(card):
    return f"[REV] {str(card.get('title') or card['id']).strip()} " \
           f"[{card['id']}]"[:TITLE_MAX]


# ---------- report phase

def verdict_files(worktree):
    """-> (verdict_dict|None, err) — cheap verifier: declared artifacts
    exist + non-empty; verdict.json parses with a known verdict."""
    vj = run_container(["cat", f"{worktree}/verdict.json"],
                       allowed_codes=(0, 1))
    em = run_container(["cat", f"{worktree}/evidence.md"],
                       allowed_codes=(0, 1))
    if not vj.strip():
        return None, "verdict.json missing/empty"
    if not em.strip():
        return None, "evidence.md missing/empty"
    try:
        v = json.loads(vj)
    except json.JSONDecodeError:
        return None, "verdict.json is not valid JSON"
    if str(v.get("verdict") or "").lower() not in VERDICTS:
        return None, f"verdict '{v.get('verdict')}' not in {sorted(VERDICTS)}"
    return v, ""


def task_reported(card, task_id):
    """Any feed comms naming this task — verdict OR artifact-failure."""
    for m in card.get("comms") or []:
        t = str(m.get("text") or "")
        if ("cline review verdict" in t or "cline review task" in t) \
                and task_id in t:
            return True
    return False


def request_sig(cid, tid):
    return hashlib.sha1(f"{cid}:{tid}".encode()).hexdigest()[:6]


def decision_pending(card, cid, tid):
    """A cline-drafted-verdict request for THIS task, or any still-open
    one (don't stack a second decision while one awaits Tony)."""
    for r in card.get("requests") or []:
        rid = str(r.get("id") or "")
        if not rid.startswith("cline-drafted-verdict"):
            continue
        if rid.endswith(request_sig(cid, tid)) or r.get("status") == "open":
            return r
    return None


def report_card(card, task, col, provider, model, out_root, state, execute):
    """Verify artifacts, post verdict comms + decision request. Returns a
    status string. Dedupe: skip when last-reported (task_id, column,
    updatedAt) is unchanged; comms/requests scanned as the cross-host
    backstop."""
    cid = card["id"]
    tid = task["id"]
    key = [tid, col, task.get("updatedAt")]
    st = state["cards"].setdefault(cid, {})
    if st.get("last_reported") == key:
        return "deduped (unchanged task state)"

    worktree = f"{WORKTREE_ROOT}/{tid}/workspace"
    v, err = verdict_files(worktree)
    if v is None:
        if not task_reported(card, tid):
            text = (f"cline review task {tid} ended but artifact check "
                    f"failed: {err} — needs human eyes (no verdict "
                    f"extracted). Worktree {worktree}.")
            if execute:
                api_post("/comment", {"id": cid, "from": ACTOR,
                                      "text": text})
            st["last_reported"] = key
            return f"reported artifact-failure ({err})"
        st["last_reported"] = key
        return "deduped (artifact failure already posted)"

    patch_path = out_root / cid / f"{tid}.patch"
    patch = ""
    if execute:
        try:
            patch = collect_patch(worktree, patch_path)
        except RuntimeError as e:
            patch_path = None
            print(f"  warn: patch collect failed for {tid}: {e}",
                  file=sys.stderr)

    verdict = str(v.get("verdict")).lower()
    reason = re.sub(r"\s+", " ", str(v.get("reason") or ""))[:200]
    did = []
    if not task_reported(card, tid):
        text = (f"cline review verdict ({provider}/{model}, task {tid}): "
                f"{verdict.upper()} — {reason}. Artifacts "
                f"verdict.json+evidence.md verified in worktree"
                + (f"; patch {len(patch.encode())}B at {patch_path}."
                   if patch_path else "."))
        if execute:
            api_post("/comment", {"id": cid, "from": ACTOR, "text": text})
        did.append("comment")

    if not decision_pending(card, cid, tid):
        rid = (f"cline-drafted-verdict-{verdict}-{slugify(reason, 6)}-"
               f"{request_sig(cid, tid)}")
        body = {"id": cid, "request_id": rid,
                "ask": f"Cline drafted verdict '{verdict}' ({reason}). "
                       f"One-word decision:",
                "options": DECISION_OPTIONS,
                "suggested": VERDICT_SUGGEST[verdict], "from": ACTOR}
        if execute:
            api_post("/request", body)
        did.append(f"request {rid}")

    st["last_reported"] = key
    st["verdict"] = verdict
    return "reported " + "+".join(did) if did else "deduped (already posted)"


# ---------- main

def main():
    global API
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="perform writes (default: dry-run)")
    ap.add_argument("--phase", choices=["all", "report", "select"],
                    default="all")
    ap.add_argument("--card", help="restrict to one card id")
    ap.add_argument("--max-tasks", type=int, default=MAX_TASKS)
    ap.add_argument("--provider", default=DEFAULT_PROVIDER)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--state", type=Path, default=STATE_PATH)
    ap.add_argument("--out-dir", type=Path,
                    default=STATE_PATH.parent / "cline-review-feed")
    ap.add_argument("--api", default=API)
    args = ap.parse_args()
    if (args.provider, args.model) not in ALLOWED_MODELS:
        print(f"provider/model {args.provider}/{args.model} not in "
              f"allowlist {sorted(ALLOWED_MODELS)}", file=sys.stderr)
        return 2
    API = args.api.rstrip("/")

    state = load_state(args.state)
    cards_doc = api_get("/cards")
    cards = {c["id"]: c for c in cards_doc.get("cards") or []}
    board = load_board()
    fed = review_tasks(board)

    # --- REPORT phase: collect ended tasks, post verdicts back ----------
    if args.phase in ("all", "report"):
        for cid, (task, col) in sorted(fed.items()):
            if args.card and cid != args.card:
                continue
            tid = task["id"]
            if col == "trash":
                continue
            card = cards.get(cid)
            if not card:
                continue
            ended = col == "review" or agent_ended(tid)
            sess = task.get("session") or {}
            if sess.get("exitCode") not in (None, 0):
                ended = True
            if not ended:
                if col == "backlog":
                    # never started (start deferred/lost) — kick it; the
                    # CLI no-ops on a live session
                    if args.execute:
                        try:
                            run_kanban(["task", "start", "--task-id", tid,
                                        "--project-path", PROJECT_PATH],
                                       timeout=90)
                            print(f"report: {cid} task {tid} was queued "
                                  f"— started")
                        except (RuntimeError,
                                subprocess.TimeoutExpired) as e:
                            print(f"report: {cid} task {tid} start "
                                  f"failed: {e}", file=sys.stderr)
                    else:
                        print(f"report: {cid} task {tid} queued in "
                              f"backlog — would start")
                else:
                    print(f"report: {cid} task {tid} still running "
                          f"({col}) — skip")
                continue
            res = report_card(card, task, col, args.provider, args.model,
                              args.out_dir, state, args.execute)
            print(f"report: {cid} task {tid}: {res}")
            if col != "review" and \
                    (res.startswith("reported") or res.startswith("deduped")):
                mv = move_task(tid, "review", args.execute)
                print(f"  move {tid} -> review: {mv}")
        if args.execute:
            save_state(args.state, state)

    # --- SELECT + CREATE phase -----------------------------------------
    if args.phase in ("all", "select"):
        board = load_board() if args.execute else board
        fed = review_tasks(board)
        in_flight = sum(1 for _, (t, c) in fed.items()
                        if c in ("backlog", "in_progress"))
        room = max(0, args.max_tasks - in_flight)
        print(f"select: {in_flight} CARDREVIEW task(s) in flight, "
              f"room for {room}")
        picks = []
        for c in cards.values():
            if args.card and c["id"] != args.card:
                continue
            kind, why = classify(c, fed)
            if kind:
                picks.append((c, kind, why))
        # incidents first (cheapest mechanical checks), then stalest review
        picks.sort(key=lambda p: (0 if p[1] == "incident" else 1,
                                  str(p[0].get("updated") or "")))
        print(f"select: {len(picks)} suitable review card(s)")
        for c, kind, why in picks[:room]:
            cid = c["id"]
            print(f"create: {cid} ({kind}: {why})")
            if not args.execute:
                continue
            prompt = build_prompt(c, kind)
            created = run_kanban([
                "task", "create",
                "--title", task_title(c),
                "--prompt", prompt,
                "--project-path", PROJECT_PATH,
                "--base-ref", "main",
                "--start-in-plan-mode", "false",
                "--auto-review-enabled", "false",
                "--agent-id", "cline",
                "--cline-provider", args.provider,
                "--cline-model", args.model])
            tid = (created.get("task") or {}).get("id")
            if not tid:
                print(f"  create failed: {created}", file=sys.stderr)
                continue
            print(f"  created task {tid}")
            try:
                run_kanban(["task", "start", "--task-id", tid,
                            "--project-path", PROJECT_PATH], timeout=90)
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"  start deferred: {e}", file=sys.stderr)
            st = state["cards"].setdefault(cid, {})
            st["task_id"] = tid
            st["kind"] = kind
        if args.execute:
            save_state(args.state, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
