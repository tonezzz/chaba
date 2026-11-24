#!/usr/bin/env python3
"""lesson-polish pack run — deterministic audit + report + polish queue.

(card lesson-audit-scheduled / AUD-0831 — the self-perpetuating loop)

Runs on any worker (idc03 job, dell/colab manual). Calls the board-api
/lesson read door, applies the R1-R5 policy rules, writes the audit
report under docs/reports/lesson-audit/, posts a one-line comms
summary, and — when R1/R3/R4 flags exist — re-arms the standing
lesson-polish-run dispatch card so the Fable polish pass picks the
flagged lessons up automatically. The agent polish pass stays a second
pack; this script only audits, reports, and queues it.

Env:
  LESSON_API                 /lesson door (default tailnet board-api)
  BOARD_API / RUNNER_API     board base for /card + /comment writes —
                             default http://127.0.0.1:8787 when it
                             answers (idc03 jobs), else the tailnet
                             base derived from LESSON_API
  LESSON_OUT                 artifact dir (default
                             docs/reports/lesson-audit next to the
                             repo root)
  LESSON_AUDIT_WORKERS       parallel op:get workers (default 8;
                             1 = serial)
  LESSON_POLISH_QUEUE        '0' disables the polish-card queue
                             (report-only mode)
  LESSON_POLISH_CARD         standing polish card id
                             (default lesson-polish-run)
  LESSON_AUDIT_CARD          card receiving the daily comms line +
                             degraded-run alerts
                             (default lesson-audit-scheduled)
  LESSON_AUDIT_STATE         queue-dedup state file (default
                             ~/.local/state/lesson-audit/polish.json)
  LESSON_POLISH_MIN_INTERVAL_H  min hours between re-arms when the
                             R1/R3/R4 flag signature is unchanged
                             (default 20 — ~1 queue/day on a stuck
                             flag set; a CHANGED signature re-arms
                             immediately)
  LESSON_AUDIT_MAX_GET_ERR   skip queueing when more than this
                             fraction of op=gets fail (default 0.2)

Flags that trigger the polish queue: R1 (level/next_review), R3
(split-rule pointer), R4 (series orphan). R2 thin/junk stays
human-gated (deletion needs Tony) and R5 Thai has curated exemptions —
neither queues agent spend.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API = os.environ.get("LESSON_API",
                     "https://idc03.taila0626a.ts.net:10000/lesson")
TODAY = date.today().isoformat()
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = os.environ.get(
    "LESSON_OUT",
    str(REPO_ROOT / "docs" / "reports" / "lesson-audit"))
os.makedirs(OUT, exist_ok=True)

POLISH_FLAG_PREFIXES = ("R1:", "R3:", "R4:")
POLISH_CARD = os.environ.get("LESSON_POLISH_CARD", "lesson-polish-run")
AUDIT_CARD = os.environ.get("LESSON_AUDIT_CARD", "lesson-audit-scheduled")
STATE_PATH = Path(os.environ.get(
    "LESSON_AUDIT_STATE",
    str(Path.home() / ".local" / "state" / "lesson-audit" / "polish.json")))
MIN_INTERVAL_H = float(os.environ.get("LESSON_POLISH_MIN_INTERVAL_H", "20"))
MAX_GET_ERR = float(os.environ.get("LESSON_AUDIT_MAX_GET_ERR", "0.2"))
WORKERS = max(1, int(os.environ.get("LESSON_AUDIT_WORKERS", "8")))
QUEUE_ENABLED = os.environ.get("LESSON_POLISH_QUEUE", "1") != "0"
LOOPBACK_API = "http://127.0.0.1:8787"

# Standing spec — written once at card creation; on_exists:'queue'
# re-arms never rewrite it, so it must stay self-contained. The
# per-run flagged list travels in card comms + the audit JSON instead.
POLISH_SPEC = """Recurring lesson-polish pass — queued automatically by the
chaba-lessons-audit job (ssot.jobs.yml job chaba-lessons-audit, daily
07:40 on idc03) whenever the deterministic audit finds R1/R3/R4 policy
flags. STANDING card: each audit run re-arms it; this spec never
changes. The flagged list for the current run is the newest
'lesson-audit' comm on this card, and the full report is
docs/reports/lesson-audit/latest.json in the served checkout
(idc03 ~/CascadeProjects/chaba-tony-dell).

Procedure:
1. Refresh flags yourself — POST {API}/lesson
   {"op":"list","content":1} (one call returns every lesson WITH
   body; per-slug op=get rescans the whole wiki namespace and is too
   slow for a full pass), then apply
   scripts/lessons-audit.py:audit_one (or read the latest audit JSON).
   Act ONLY on R1/R3/R4 flags. R2 thin/junk and R5 Thai are out of
   scope: junk deletion is human-gated, and Thai exemptions live in
   scripts/lesson-thai-exceptions.yml + meta.no_th.
2. Polish each flagged lesson per the 7-dimension policy
   (docs/ssot/jobs/education/2026-10-24-lesson-polish.yml + AGENTS.md
   lesson-capture/split-rule duties):
   - R3:no-pointer — decision/verdict content needs an SSOT/KB pointer
     inside the EN body, BEFORE the <h3>ไทย</h3> section (pointers
     tail-appended after Thai get dropped on re-file).
   - R4:orphan — family lessons (ada-nest-*/trade-*/voice-*/ai-*) need
     a hub/sibling pointer line ("<fam> series — hub: <link>").
   - R1:overdue / no-next-review / level-invalid — review the lesson,
     then re-file via POST /lesson upsert with corrected meta
     (level in intro|working|deep; fresh next_review per spaced
     repetition — re-file preserves old dates by design, pass an
     explicit next_review override).
3. Fable lane for prose rewrites: LiteLLM gateway
   http://100.102.134.91:4000, model consult-claude
   (openrouter/anthropic/claude-fable-5.1) — scripts/ada/litellm_chat.py
   resolves LITELLM_URL/LITELLM_KEY from
   ~/.config/secrets/mddb-gemini.env. Keep edits additive: never drop
   existing pointers, Thai sections, or first-learn provenance.
4. Write ONLY through POST {API}/lesson (the board-api door) — no WP
   creds, no direct CPT writes, no deletes (human-gated).
5. Re-run the audit when done; post before/after flag counts and the
   per-lesson action list to this card AND to card lesson-audit-scheduled.
"""


API_TIMEOUT = float(os.environ.get("LESSON_API_TIMEOUT", "90"))


def api(body: dict) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(
        urllib.request.urlopen(req, timeout=API_TIMEOUT).read().decode())


_BOARD_BASE = None


def board_base() -> str:
    """Board-api base for writes. Loopback first (idc03 jobs get the
    trusted 'local' identity); tailnet base derived from LESSON_API as
    the portable fallback."""
    global _BOARD_BASE
    if _BOARD_BASE:
        return _BOARD_BASE
    explicit = os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
    if explicit:
        _BOARD_BASE = explicit.rstrip("/")
        return _BOARD_BASE
    try:
        urllib.request.urlopen(LOOPBACK_API + "/health", timeout=1.5).read()
        _BOARD_BASE = LOOPBACK_API
    except Exception:
        _BOARD_BASE = API[:-len("/lesson")].rstrip("/") \
            if API.endswith("/lesson") else API.rstrip("/")
    return _BOARD_BASE


def board_post(path: str, body: dict, timeout: int = 30) -> dict:
    """POST with one retry — the door answers 503 'lock saturated —
    retry' under flock contention (kanban-commit races every ~15min)."""
    url = board_base() + path
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            return json.loads(
                urllib.request.urlopen(req, timeout=timeout).read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 503 or attempt:
                raise
            time.sleep(12)
        except Exception:
            raise
    raise last


def audit_one(slug, topic, level, nxt, content):
    flags = []
    if level not in ("intro", "working", "deep"):
        flags.append("R1:level-invalid")
    if not nxt:
        flags.append("R1:no-next-review")
    elif nxt < TODAY:
        flags.append("R1:overdue")
    body_len = len(re.sub(r"<[^>]+>", "", content or "").strip())
    if body_len < 500:
        flags.append(f"R2:thin({body_len}ch)")
    if re.search(r"verdict|decision|winner|recommend", content or "", re.I) and \
       not re.search(r"devin-kb|SSOT|ai-workforce-eval|docs/tools", content or ""):
        flags.append("R3:no-pointer")
    if any(topic.lower().startswith(p) for p in ("ai-", "ada-nest-", "voice-")) and \
       not re.search(r"hub|family|related:|companion", content or "", re.I):
        flags.append("R4:orphan")
    if not re.search(r"[\u0e00-\u0e7f]", content or ""):
        flags.append("R5:consider-thai")
    return {"slug": slug, "topic": topic, "level": level, "next_review": nxt,
            "flags": flags, "body_chars": body_len}


def _get_content(slug: str):
    try:
        g = api({"op": "get", "slug": slug})
        return slug, g.get("content", ""), None
    except Exception as e:  # noqa: BLE001 — record, don't die
        return slug, "", str(e)


def flag_signature(rows: list) -> str:
    """Stable signature of the R1/R3/R4 flag set — queue dedup key.
    '' when nothing polish-worthy is flagged."""
    pairs = sorted(
        f"{r['slug']}|{f}"
        for r in rows for f in r["flags"]
        if f.startswith(POLISH_FLAG_PREFIXES))
    if not pairs:
        return ""
    return hashlib.sha1(json.dumps(pairs).encode()).hexdigest()[:16]


def polish_rows(rows: list) -> list:
    return [r for r in rows
            if any(f.startswith(POLISH_FLAG_PREFIXES) for f in r["flags"])]


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=1) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"warn: state write failed: {e}", file=sys.stderr)


def queue_decision(state: dict, signature: str, now: datetime) -> str:
    """-> clean | new-flags | retry | throttled."""
    if not signature:
        return "clean"
    if state.get("signature") != signature:
        return "new-flags"
    try:
        last = datetime.fromisoformat(str(state.get("queued_at") or ""))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        last = None
    if last and (now - last) < timedelta(hours=MIN_INTERVAL_H):
        return "throttled"
    return "retry"


def flagged_lines(rows: list, cap: int = 25) -> str:
    lines = []
    for r in rows[:cap]:
        pf = [f for f in r["flags"]
              if f.startswith(POLISH_FLAG_PREFIXES)]
        lines.append(f"- `{r['slug']}` {r.get('topic') or ''} — "
                     + ", ".join(f"`{f}`" for f in pf))
    if len(rows) > cap:
        lines.append(f"- …and {len(rows) - cap} more (see audit JSON)")
    return "\n".join(lines)


def queue_polish(rows: list, decision: str, report_path: str,
                 dry_run: bool) -> dict:
    """Re-arm the standing polish card + post the flagged list as a
    comm. Returns the report['polish'] block."""
    out = {"decision": decision, "card": POLISH_CARD}
    if decision in ("clean", "throttled"):
        return out
    summary = (f"lesson-audit {TODAY}: {len(rows)} lesson(s) with "
               f"R1/R3/R4 flags -> {decision} "
               f"({POLISH_CARD})")
    detail = (f"{summary}\nflagged:\n{flagged_lines(rows)}\n"
              f"full report: {report_path}")
    card_body = {
        "id": POLISH_CARD,
        "title": "lesson-polish: Fable pass on audit-flagged lessons "
                 "(auto-queued)",
        "brief": "Auto-queued by chaba-lessons-audit when R1/R3/R4 "
                 "flags > 0 — the Fable polish pass; standing card, "
                 "re-armed each audit run (AUD-0831 loop).",
        "spec": POLISH_SPEC.replace("{API}", API),
        "action": {"type": "dispatch", "repo": "chaba",
                   "executor": "devin"},
        "priority": "medium",
        "program": "chaba-ci",
        "tags": ["lesson", "education", "polish", "scheduled"],
        "queue": True,
        "on_exists": "queue",
        "from": "chaba",
        "text": "auto-queued by chaba-lessons-audit job",
    }
    comment_body = {"id": POLISH_CARD, "from": "chaba", "text": detail}
    if dry_run:
        out.update({"dry_run": True, "card_body": card_body,
                    "comment": detail})
        return out
    try:
        r = board_post("/card", card_body, timeout=60)
        out["queue_resp"] = r.get("message", r)
    except Exception as e:  # noqa: BLE001
        out["queue_error"] = str(e)
        print(f"warn: polish queue failed: {e}", file=sys.stderr)
        return out
    try:
        board_post("/comment", comment_body, timeout=30)
        out["comment"] = "posted"
    except Exception as e:  # noqa: BLE001
        out["comment_error"] = str(e)
        print(f"warn: polish-card comment failed: {e}", file=sys.stderr)
    return out


def audit_comment(line: str, dry_run: bool) -> None:
    """One-line daily report on the audit card — the 'card comms' half
    of the spec (the digest half is chaba-education-report 10 min
    later)."""
    body = {"id": AUDIT_CARD, "from": "chaba", "text": line[:500]}
    if dry_run:
        print(f"[dry-run] POST /comment {AUDIT_CARD}: {line[:160]}")
        return
    try:
        board_post("/comment", body, timeout=30)
    except Exception as e:  # noqa: BLE001 — reporting must not kill run
        print(f"warn: audit comms failed: {e}", file=sys.stderr)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print intended board writes; post nothing")
    args = ap.parse_args()

    try:
        # content=1: wiki op:list already scans every page — rows come
        # back with bodies and NO per-slug gets are needed (the old
        # serial/parallel get loop was the 10m-timeout cause; on the
        # wiki store each get rescans the whole namespace). wp/mddb
        # lists ignore the param and rows lack "content" -> the get
        # fallback below still covers them.
        d = api({"op": "list", "content": 1})
    except Exception as e:  # noqa: BLE001
        print(f"audit: /lesson list failed: {e}", file=sys.stderr)
        return 2
    lessons = d.get("lessons", [])

    contents = {l["slug"]: l["content"] for l in lessons
                if isinstance(l.get("content"), str)}
    missing = [l.get("slug", "") for l in lessons
               if l.get("slug") not in contents]
    get_errors = 0
    if missing:
        # fallback for sources whose list rows carry no content
        # (wp/mddb, or an older board-api without content=1) —
        # parallel op:get. On the wiki store this path should be
        # empty; if it isn't, the door predates the bulk read.
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for slug, content, err in ex.map(_get_content, missing):
                contents[slug] = content
                if err:
                    get_errors += 1

    rows = []
    for l in lessons:
        rows.append(audit_one(l["slug"], l.get("topic", ""),
                              l.get("level", ""), l.get("next_review", ""),
                              contents.get(l.get("slug"), "")))
    flagged = [r for r in rows if r["flags"]]
    prows = polish_rows(rows)
    counts = {}
    for r in flagged:
        for f in r["flags"]:
            counts[f] = counts.get(f, 0) + 1

    now = datetime.now(timezone.utc)
    sig = flag_signature(prows)
    state = load_state()
    decision = queue_decision(state, sig, now)
    degraded = bool(lessons) and \
        get_errors / max(1, len(lessons)) > MAX_GET_ERR
    if degraded and decision in ("new-flags", "retry"):
        decision = "degraded-skip"

    report = {"generated": now.isoformat(), "total": len(rows),
              "flagged": len(flagged), "flag_counts": counts,
              "get_errors": get_errors,
              "flagged_rows": flagged,
              "polish": {"decision": decision, "signature": sig,
                         "polish_flagged": len(prows)}}
    dated = os.path.join(OUT, f"lesson-audit-{TODAY}.json")
    latest = os.path.join(OUT, "latest.json")
    rel = os.path.relpath(dated, REPO_ROOT)

    preamble = (f"lesson-audit {TODAY}: {len(rows)} lessons, "
                f"{len(flagged)} flagged ({', '.join(
                    f'{k} x{v}' for k, v in sorted(counts.items())) or 'none'})")
    if get_errors:
        preamble += f", get-errors {get_errors}"

    polish = report["polish"]
    if QUEUE_ENABLED and decision in ("new-flags", "retry"):
        res = queue_polish(prows, decision, rel, args.dry_run)
        polish.update(res)
        if not args.dry_run and "queue_error" not in res:
            state.update({"signature": sig,
                          "queued_at": now.isoformat(),
                          "decision": decision})
            save_state(state)
        tail = (f"polish {decision} -> {POLISH_CARD}"
                if "queue_error" not in res
                else f"polish queue FAILED: {res['queue_error']}")
    elif QUEUE_ENABLED and decision == "throttled":
        tail = f"polish throttled (unchanged flags, <{MIN_INTERVAL_H:g}h)"
    elif QUEUE_ENABLED and decision == "degraded-skip":
        tail = (f"polish skipped — degraded fetch "
                f"({get_errors}/{len(lessons)} get errors)")
    elif not QUEUE_ENABLED:
        tail = "polish queue disabled (LESSON_POLISH_QUEUE=0)"
    else:
        tail = "no R1/R3/R4 flags — polish not queued"

    for p in (dated, latest):
        with open(p, "w") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)

    audit_comment(f"{preamble}; {tail} — {rel}", args.dry_run)
    print(f"audit: {len(rows)} lessons, {len(flagged)} flagged "
          f"({len(prows)} R1/R3/R4) -> {dated} [{tail}]")
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
