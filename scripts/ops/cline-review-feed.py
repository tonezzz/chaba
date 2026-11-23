#!/usr/bin/env python3
"""cline-review-feed — drain the Chaba review column's mechanical subset
through the con01 Cline kanban board (card cline-card-review-lane).

Each selected review card gets ONE disposable Cline task whose only job is
to weigh the evidence pasted into its prompt and write `verdict.json` +
`evidence.md` into the task worktree. This script then collects the diff,
verifies the artifacts, and reports a drafted verdict back to the card —
a comms line plus (when the card's question is a decision) a /request with
close/keep/requeue options. It NEVER moves or closes a card: qwen2.5:7b is
a weak model and the human keeps the gate.

Phases per run:
  1. SELECT   cline-suitable review cards (see is_cline_suitable).
  2. CREATE   one task per card, marker [CARDREVIEW:<id>], cap MAX_INFLIGHT
              tasks in backlog/in_progress at once.
  3. COLLECT  settled tasks -> worktree diff (bridge.collect_patch) ->
              artifact check (verdict.json + evidence.md exist, non-empty).
  4. REPORT   card comms + options request — deduped per
              (task_id, column, updatedAt): the 2026-10-29 lane-cms run
              re-posted "task 8b60e review-ready" 5x because the poll loop
              re-reported unchanged state; the state file fixes that.

Marker note: the marker is [CARDREVIEW:<id>], deliberately NOT the spec'd
[CARD:<id>] — scripts/ops/cline-board-mirror.py claims every task whose
prompt contains "[CARD:" as its own mirror projection and would rewrite or
delete live review tasks.

Runs on con01 (podman exec into the cline-kanban container, like
scripts/colab/packs/cline-kanban-nest-bridge/intake.py). Stdlib only.
Zero paid spend: provider/model are pinned to the bridge allowlist, which
is ollama-local + OR-free only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
BRIDGE_DIR = HERE.parents[1] / "colab" / "packs" / "cline-kanban-nest-bridge"
sys.path.insert(0, str(BRIDGE_DIR))
import bridge  # noqa: E402  (podman/kanban helpers, collect_patch, …)

API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
# board-api only accepts ada|chaba|devin|tony as comms authors
ACTOR = "devin"
MARKER_RE = re.compile(r"\[CARDREVIEW:([^\]]+)\]")
ALLOWED_MODELS = {
    ("ollama", "qwen3:4b"),
    ("ollama", "qwen2.5:7b"),
    ("openrouter", "or-free-nemotron-nano"),
    ("openrouter", "or-free-gemma31b"),
}
AUTO_INCIDENT_PREFIXES = (
    "logs-auto", "runner-auto", "cms-auto", "disk-auto", "vcast-auto")
PROMPT_MAX = 3800
TITLE_MAX = 110

# A card is unsuitable when its review question needs anything Cline's
# disposable workspace cannot see or touch. These patterns match on the
# concatenated title+spec+tags (case-insensitive).
EXCLUDE_RE = re.compile(
    r"\b(secret|secrets|credential|password|passkey|api[-_ ]?key|"
    r"private[-_ ]?key|cert(ificate)?[-_ ]?rotat|token[-_ ]?refresh|"
    r"deploy|redeploy|systemctl|service[-_ ]?restart|scp |ssh |"
    r"host[-_ ]?mutation|install|uninstall|migration on|prod[-_ ]?change|"
    r"credentials|wp-admin|database|mddb[-_ ]?write)\b",
    re.IGNORECASE)

INCIDENT_PROMPT = """You are evidence-checking Chaba auto-incident card "{title}".

Claimed condition (as recorded by the monitor):
{evidence}

Recent card comms (oldest to newest):
{comms}

You CANNOT reach the live hosts — judge only the evidence above. Write exactly two files into the workspace:

1. verdict.json — {{"verdict": "close"|"hold"|"investigate", "confidence": "low"|"medium"|"high", "reason": "<one line>"}}
   - "close" only when the comms/note show the condition resolved or the claim was a one-off blip followed by recovery evidence
   - "hold" when the claim looks real and unresolved but a human already has what they need
   - "investigate" when evidence is stale, contradictory, or the condition needs a live probe you cannot run
2. evidence.md — short markdown: what was claimed, what the comms show, why you picked the verdict, what a human should check before acting.

Do NOT invent probe results. Create the files with the editor/write tool — a reply without both files on disk is a failure. Do not commit, push, or open a PR.

{marker}"""

DELIVERABLE_PROMPT = """You are reviewing Chaba kanban card "{title}" — a bounded deliverable that reports itself done and sits in the review column waiting on a human verdict.

Card spec:
{evidence}

Recent card comms (oldest to newest):
{comms}

You CANNOT see the repo or live systems — judge only whether the reported evidence supports the claimed done-condition. Write exactly two files into the workspace:

1. verdict.json — {{"verdict": "close"|"hold"|"investigate", "confidence": "low"|"medium"|"high", "reason": "<one line>"}}
   - "close" when the comms/spec show the done-condition met by named evidence
   - "hold" when it looks done but the evidence is thin and a human should glance first
   - "investigate" when evidence is missing, contradictory, or the done-condition was never demonstrated
2. evidence.md — short markdown: the done-condition, the evidence found, gaps, why you picked the verdict.

Do NOT invent verification results. Create the files with the editor/write tool — a reply without both files on disk is a failure. Do not commit, push, or open a PR.

{marker}"""


# ---------- board api ----------

def api_get(path, timeout=30):
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def api_post(path, body, timeout=30):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def get_card(cid):
    out = api_get(
        f"/card/{cid}?fields=id,title,column,updated,priority,tags,spec,"
        f"note,requests,action,comms")
    return out.get("card") if out.get("ok") else None


# ---------- state (dedupe + tracking) ----------

def load_state(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"cards": {}}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def report_key(task):
    return "|".join(str(task.get(k) or "")
                    for k in ("id", "column", "updatedAt"))


# ---------- select ----------

def open_requests(card):
    return [r for r in (card.get("requests") or [])
            if isinstance(r, dict) and r.get("status") not in
            (None, "answered", "closed")]


def card_class(card):
    cid = card.get("id") or ""
    if cid.startswith(AUTO_INCIDENT_PREFIXES):
        return "incident"
    return "deliverable"


def is_cline_suitable(card):
    """(ok, reason) — conservative: when in doubt, leave for a human."""
    cid = card.get("id") or "?"
    if card.get("column") != "review":
        return False, "not in review"
    if open_requests(card):
        return False, "open human request awaiting answer"
    text = " ".join(str(x) for x in (
        card.get("title"), card.get("spec"), card.get("note"),
        " ".join(card.get("tags") or [])))
    m = EXCLUDE_RE.search(text)
    if m:
        return False, f"excluded keyword '{m.group(0)}'"
    if not (card.get("spec") or card.get("note") or card.get("comms")):
        return False, "no spec/note/comms to review from"
    return True, card_class(card)


def select_cards(limit, only_ids=None):
    doc = api_get("/cards?column=review&fields=id&limit=1000")
    if doc.get("error"):
        raise RuntimeError(f"/cards failed: {doc['error']}")
    picked, skipped = [], []
    for stub in doc.get("cards") or []:
        cid = stub.get("id")
        if only_ids and cid not in only_ids:
            continue
        card = get_card(cid)
        if not card:
            skipped.append((cid, "fetch failed"))
            continue
        ok, why = is_cline_suitable(card)
        if ok:
            picked.append(card)
        else:
            skipped.append((cid, why))
        if len(picked) >= limit and not only_ids:
            break
    return picked, skipped


# ---------- prompt ----------

def clip(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def comms_digest(card, keep=6, chars=900):
    lines = []
    for m in (card.get("comms") or [])[-keep:]:
        lines.append(
            f"- {m.get('at', '?')} {m.get('from', '?')}: "
            f"{(m.get('text') or '').strip()}")
    return clip("\n".join(lines), chars) or "(none)"


def build_prompt(card):
    cid = card["id"]
    kind = card_class(card)
    evidence = "\n\n".join(x for x in (
        clip(card.get("note"), 600) and f"note: {clip(card.get('note'), 600)}",
        clip(card.get("spec"), 1600)) if x) or "(none recorded)"
    tpl = INCIDENT_PROMPT if kind == "incident" else DELIVERABLE_PROMPT
    return clip(tpl.format(
        title=clip(card.get("title") or cid, 140),
        evidence=evidence, comms=comms_digest(card),
        marker=f"[CARDREVIEW:{cid}]"), PROMPT_MAX)


# ---------- create / collect ----------

def card_of_task(task):
    m = MARKER_RE.search(task.get("prompt") or "")
    return m.group(1) if m else None


def feed_tasks(tasks):
    """card_id -> task for tasks owned by this lane."""
    return {card_of_task(t): t for t in tasks if card_of_task(t)}


def inflight(tasks):
    return [t for t in feed_tasks(tasks).values()
            if t.get("column") in ("backlog", "in_progress")]


def create_task(card, provider, model):
    prompt = build_prompt(card)
    cid = card["id"]
    out = bridge.run_kanban([
        "task", "create",
        "--title", clip(f"[REV] {card.get('title') or cid} [{cid}]", TITLE_MAX),
        "--prompt", prompt,
        "--project-path", "/workspace",
        "--base-ref", "main",
        "--start-in-plan-mode", "false",
        "--auto-review-enabled", "false",
        "--agent-id", "cline",
        "--cline-provider", provider,
        "--cline-model", model,
    ])
    task = out.get("task")
    if not isinstance(task, dict) or not task.get("id"):
        raise RuntimeError(f"create response for {cid} lacks task.id")
    return task


def ensure_started(task):
    if bridge.should_start_task(task):
        try:
            bridge.run_kanban([
                "task", "start", "--task-id", task["id"],
                "--project-path", "/workspace"], timeout=90)
        except (subprocess.TimeoutExpired, RuntimeError):
            pass


def settled(task):
    session = task.get("session") or {}
    exit_code = session.get("exitCode")
    if exit_code not in (None, 0):
        return "failed"
    if task.get("column") in ("review", "trash"):
        return "done"
    if exit_code == 0:
        return "done"
    if not session and bridge.agent_ended(task["id"]):
        return "done"  # session record lost; artifacts decide
    return None


def collect_task_artifacts(task, out_dir):
    """Return (verdict_dict, evidence_text, patch_bytes, changed_files)."""
    before = []  # worktree set isn't tracked across runs; match by task id
    wt = bridge.choose_task_worktree(before, bridge.get_worktrees(),
                                     task["id"])
    patch_path = out_dir / f"{task['id']}.patch"
    patch, changed = bridge.collect_patch(wt["path"], patch_path)
    base = wt["path"]
    verdict_raw = bridge.read_expected_file(base, "verdict.json").strip()
    evidence = bridge.read_expected_file(base, "evidence.md").strip()
    if not verdict_raw:
        raise RuntimeError("verdict.json missing or empty")
    if not evidence:
        raise RuntimeError("evidence.md missing or empty")
    try:
        verdict = json.loads(verdict_raw)
    except json.JSONDecodeError:
        # weak models sometimes write escaped JSON ({\"verdict\": ...})
        # instead of a raw object — unescape and retry once
        verdict = json.loads(verdict_raw.replace('\\"', '"'))
    if isinstance(verdict, str):
        verdict = json.loads(verdict)
    if verdict.get("verdict") not in ("close", "hold", "investigate"):
        raise RuntimeError(f"bad verdict value: {verdict.get('verdict')!r}")
    return verdict, evidence, len(patch.encode()), changed


# ---------- report ----------

SUGGEST = {"close": "close", "hold": "keep", "investigate": "requeue"}


def post_verdict(card, task, verdict, patch_bytes, changed,
                 provider, model, st, dry_run):
    cid = card["id"]
    v = verdict.get("verdict")
    reason = clip(verdict.get("reason") or "", 200)
    text = (
        f"cline review verdict ({provider}/{model}, task {task['id']}): "
        f"{v.upper()} — {reason}. Artifacts verdict.json+evidence.md "
        f"verified in worktree patch ({patch_bytes}B; "
        f"{', '.join(changed[:6])}). Weak-model draft — human gate stays; "
        f"decision request posted with options.")
    req = {
        "id": cid, "from": ACTOR,
        "ask": f"Cline drafted verdict '{v}' ({reason}). One-word decision:",
        "options": [
            {"id": "close", "label": "close card", "action": "close"},
            {"id": "keep", "label": "keep in review", "action": "none"},
            {"id": "requeue", "label": "requeue for another pass",
             "action": "retry"},
        ],
        "suggested": SUGGEST.get(v, "keep"),
    }
    if dry_run:
        return {"comment": "dry-run", "request": req}
    res_c = api_post("/comment", {"id": cid, "from": ACTOR, "text": text})
    res_r = api_post("/request", req) if not st.get("request_raised") \
        else {"skipped": "request already raised"}
    return {"comment": res_c, "request": res_r,
            "ok": not res_c.get("error")
            and not res_r.get("error")}


def run_collect(tasks, state, args, dry_run):
    owned = feed_tasks(tasks)
    results = []
    for cid, st in state["cards"].items():
        task = owned.get(cid)
        if not task or task.get("id") != st.get("task_id"):
            continue
        if st.get("reported_key") == report_key(task) and \
                st.get("request_raised"):
            continue  # unchanged since last report — the dedupe fix
        why = settled(task)
        if not why:
            results.append({"card": cid, "status": "waiting",
                            "column": task.get("column")})
            continue
        if why == "failed":
            results.append({"card": cid, "status": "task-failed"})
            continue
        out_dir = args.out / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            verdict, evidence, nbytes, changed = \
                collect_task_artifacts(task, out_dir)
        except Exception as exc:
            # artifacts not ready/bad — report once per new task state
            if st.get("reported_key") != report_key(task):
                if not dry_run:
                    res = api_post("/comment", {
                        "id": cid, "from": ACTOR,
                        "text": f"cline review task {task['id']} settled but "
                                f"artifact check failed: {exc}. Left for "
                                f"human review — no auto-close."})
                    if not res.get("error"):
                        st["reported_key"] = report_key(task)
            results.append({"card": cid, "status": "artifact-fail",
                            "error": str(exc)})
            continue
        st["verdict"] = verdict.get("verdict")
        rep = post_verdict(get_card(cid) or card, task, verdict, nbytes,
                           changed, args.provider, args.model, st, dry_run)
        if not dry_run and rep.get("ok"):
            # only latch after the comms actually landed — a failed post
            # must retry next pass, not be deduped away
            st["reported_key"] = report_key(task)
            st["request_raised"] = True
        results.append({"card": cid, "status": "reported",
                        "verdict": verdict.get("verdict"), "report": rep})
    return results


# ---------- main ----------

def main():
    global API
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=API)
    ap.add_argument("--state", type=Path, default=Path(
        os.environ.get("CLINE_REVIEW_STATE",
                       "~/.local/state/cline-review-feed.json")).expanduser())
    ap.add_argument("--out", type=Path, default=Path(
        os.environ.get("CLINE_REVIEW_OUT",
                       "~/.local/state/cline-review-feed")).expanduser())
    ap.add_argument("--card", action="append", help="only this card id")
    ap.add_argument("--limit", type=int, default=3,
                    help="max new tasks this run (and selection scan cap)")
    ap.add_argument("--max-inflight", type=int, default=3)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--poll-s", type=int, default=60)
    ap.add_argument("--wait-s", type=int, default=0,
                    help="keep collecting until this deadline (0 = one pass)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    API = args.api.rstrip("/")
    if (args.provider, args.model) not in ALLOWED_MODELS:
        ap.error(f"{args.provider}/{args.model} not in free-lane allowlist")

    state = load_state(args.state)
    state.setdefault("cards", {})
    deadline = time.monotonic() + args.wait_s if args.wait_s else None

    while True:
        tasks = bridge.list_tasks("/workspace")
        results = run_collect(tasks, state, args, args.dry_run)

        # fill up to the inflight cap
        room = args.max_inflight - len(inflight(tasks))
        if room > 0:
            picked, skipped = select_cards(
                min(args.limit, room), only_ids=set(args.card or []) or None)
            for cid, why in skipped:
                print(f"skip {cid}: {why}", flush=True)
            for card in picked:
                cid = card["id"]
                st = state["cards"].setdefault(cid, {})
                existing = feed_tasks(tasks).get(cid)
                if existing:  # idempotent — marker already on the board
                    st["task_id"] = existing["id"]
                    ensure_started(existing)
                    results.append({"card": cid, "status": "existing",
                                    "task_id": existing["id"]})
                    continue
                if args.dry_run:
                    results.append({"card": cid, "status": "dry-run",
                                    "prompt": build_prompt(card)})
                    continue
                try:
                    task = create_task(card, args.provider, args.model)
                    st["task_id"] = task["id"]
                    ensure_started(task)
                    results.append({"card": cid, "status": "created",
                                    "task_id": task["id"]})
                    print(f"created review task {task['id']} for {cid}",
                          flush=True)
                except Exception as exc:
                    results.append({"card": cid, "status": "create-failed",
                                    "error": str(exc)})
        if not args.dry_run:
            save_state(args.state, state)
        print(json.dumps(results, indent=1, default=str), flush=True)

        pending = [r for r in results
                   if r.get("status") in ("waiting", "created")
                   or (r.get("status") == "existing" and not
                       state["cards"].get(r["card"], {})
                       .get("request_raised"))]
        if not deadline or not pending or time.monotonic() >= deadline:
            return 0
        time.sleep(args.poll_s)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"cline-review-feed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
