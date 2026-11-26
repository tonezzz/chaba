#!/usr/bin/env python3
"""Watch GitHub Actions runs and surface failures in-repo.

GH workflow results never reach reports/ or the focus inbox — CI failures
die in the GH UI (ssot.quality.yml coverage_gaps). This polls `gh run list`
per watched repo, writes a focus-inbox alert per NEW failed run (deduped
via a state file), and emits an L1 meta.yml + timeline event per
ssot.reports.yml. A failure for a (repo, workflow, branch) combo that
already has an unresolved inbox alert is suppressed — one open alert per
broken workflow, not one per run (lesson: 3 days of red SSOT CI wrote
~620 draft files).

Runs where `gh` is authenticated (tony-omen). With --git the alert files
are committed and pushed so downstream checkouts see them on pull — but
only on a checkout that can actually commit. On a stamped non-writer
checkout (exec/readonly/job — card
exec-checkout-generated-writes-focus-inb-da698a) --git dead-ends in the
pre-commit role block, so the watch automatically falls back to posting
alerts through board-api POST /inbox (the same door the other watchers
use). --api forces the API path explicitly; BOARD_API env overrides the
default endpoint.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
try:
    from checkout_role import checkout_role
except ImportError:  # scripts/lib not importable (e.g. copied standalone)
    def checkout_role(repo):  # noqa: ANN001
        return ""

INBOX_DIR = REPO_ROOT / "docs" / "ssot" / "focus-inbox"
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
# API-mode repeat suppression: one /inbox item per (repo, workflow, branch)
# per window — the remote inbox has no local open_item() view, so the state
# file carries the last-posted stamp per combo.
API_ALERT_REPEAT_H = float(os.environ.get("GH_RUNS_WATCH_ALERT_REPEAT_H", "24"))
STATE_FILE = Path(os.environ.get(
    "GH_RUNS_WATCH_STATE",
    Path.home() / ".local" / "state" / "chaba" / "gh-runs-watch.json"))
REPORTS_DIR = REPO_ROOT / "reports" / "gh-runs"
TIMELINE = Path(os.environ.get(
    "CHABA_REPORTS_DIR", Path.home() / "var" / "chaba" / "reports")) / "timeline.jsonl"
DEFAULT_REPOS = "tonezzz/chaba,tonezzz/ada-voice"
GH_TIMEOUT = int(os.environ.get("GH_RUNS_WATCH_TIMEOUT", "90"))
# gh on omen stores its token in the desktop keyring — in a headless
# systemd/ssh context the secret-service lookup blocks and every `gh`
# call hangs until the subprocess timeout (2026-10-13: every poll died
# at 60s and systemd TERM'd the unit). GH_TOKEN bypasses keyring auth
# entirely, so resolve one from env or the github-mcp secrets files.
TOKEN_FILES = ("github-mcp.env", "github-mcp-new.env")
TOKEN_KEYS = ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACCESS_TOKEN",
              "GITHUB_PERSONAL_ACCESS_TOKEN")

FIELDS = ("databaseId", "workflowName", "conclusion", "status",
          "headBranch", "createdAt", "displayTitle", "url")


def resolve_gh_token():
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    secrets = Path.home() / ".config" / "secrets"
    for fname in TOKEN_FILES:
        try:
            for line in (secrets / fname).read_text().splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                k, v = line.split("=", 1)
                if k.strip() in TOKEN_KEYS and v.strip():
                    return v.strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def gh_env():
    env = dict(os.environ)
    token = resolve_gh_token()
    if token:
        env["GH_TOKEN"] = token
    return env


def gh_runs(repo):
    try:
        out = subprocess.run(
            ["gh", "run", "list", "-R", repo, "--limit", "25",
             "--json", ",".join(FIELDS)],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
            env=gh_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"warn: gh run list {repo}: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        print(f"warn: gh run list {repo}: {out.stderr.strip()[:300]}",
              file=sys.stderr)
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as e:
        print(f"warn: gh run list {repo}: bad json: {e}", file=sys.stderr)
        return None


def load_state():
    """Return (seen_run_ids, alerted_combos). alerted_combos maps
    'repo|workflow|branch' -> last /inbox post ISO timestamp (API mode)."""
    try:
        doc = json.loads(STATE_FILE.read_text())
    except Exception:
        return set(), {}
    if isinstance(doc, list):  # legacy bare-list state
        return set(doc), {}
    return set(doc.get("seen", [])), dict(doc.get("alerts", {}))


def save_state(seen, alerts=None):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps({
            "seen": sorted(seen)[-500:],
            "alerts": dict(sorted((alerts or {}).items())[-500:]),
        }))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE_FILE)


def post_inbox(repo, run, now_iso):
    """Post one CI-failure alert through board-api POST /inbox."""
    wf = run.get("workflowName", "?")
    br = run.get("headBranch", "?")
    text = (f"GitHub Actions run failed on {repo}.\n"
            f"workflow={wf} branch={br} "
            f"sha-title={run.get('displayTitle')!r}\n"
            f"url={run.get('url')}\n"
            f"Detected {now_iso} by gh-runs-watch.")
    body = {
        "text": text,
        "label": f"gh-run {repo} / {wf}",
        "priority": "high",
        "tags": ["ci", "github-actions", repo.split("/")[-1],
                 "gh-runs-watch"],
        "owner": "tony",
        "session": "gh-runs-watch",
    }
    req = urllib.request.Request(
        f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return 200 <= r.status < 300


def alert_yaml(repo, run):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fname = (f"{stamp[:10]}-{stamp[11:19].replace(':', '')}"
             f"-gh-run-{repo.replace('/', '-')}-{run['databaseId']}.yml")
    body = f"""title: CI failure on {repo}
subtitle: "{run.get('workflowName', '?')} failed on {run.get('headBranch', '?')}"
icon: inbox
focus:
  label: "Fix CI: {repo} / {run.get('workflowName', '?')}"
  text: >-
    GitHub Actions run failed. workflow={run.get('workflowName')}
    branch={run.get('headBranch')} sha-title={run.get('displayTitle')!r}
    url={run.get('url')}
    Detected {stamp} by gh-runs-watch.
  branch: {repo.split('/')[-1]}
  priority: high
  status: draft
  tags: [ci, github-actions, {repo.split('/')[-1]}]
  safe_to_parallel:
    value: true
    reason: read-only failure report; fixing the check is independent work
ownership:
  owner: tony
  locked: false
  lock_reason: ""
source:
  date: {stamp[:10]}
"""
    return fname, body


def existing_alert(repo, run):
    """Return an unresolved inbox alert for the same repo/workflow/branch."""
    slug = repo.replace('/', '-')
    wf = run.get('workflowName', '?')
    br = run.get('headBranch', '?')
    for f in INBOX_DIR.glob(f"*gh-run-{slug}-*.yml"):
        try:
            txt = f.read_text()
        except OSError:
            continue
        if (f"workflow={wf}" in txt and f"branch={br}" in txt
                and "status: draft" in txt):
            return f
    return None


def emit_meta(now_iso, failures, errors):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    status = "delta" if failures else ("error" if errors else "ok")
    summary = (f"{len(failures)} new CI failure(s)"
               + (f", {errors} repo poll error(s)" if errors else ""))
    meta = {
        "node": "gh-runs-watch",
        "layer": "L1-producer",
        "purpose": "Surface GitHub Actions failures into the focus inbox",
        "generated_by": "scripts/audits/gh-runs-watch.py",
        "generated_at": now_iso,
        "status": status,
        "summary": summary,
        "sources": [r["url"] for r in failures],
        "children": [],
    }
    try:
        import yaml
        (REPORTS_DIR / "meta.yml").write_text(yaml.dump(
            meta, sort_keys=False, allow_unicode=True))
    except ImportError:
        (REPORTS_DIR / "meta.yml").write_text(
            "\n".join(f"{k}: {json.dumps(v, default=str)}" for k, v in meta.items()))
    try:
        TIMELINE.parent.mkdir(parents=True, exist_ok=True)
        with TIMELINE.open("a") as f:
            f.write(json.dumps({
                "ts": now_iso, "node": "gh-runs-watch", "layer": "L1",
                "status": status, "summary": summary,
                "ref": str(REPORTS_DIR / "meta.yml")}) + "\n")
    except OSError as e:
        print(f"warn: timeline emit failed: {e}", file=sys.stderr)


def git_commit_push(files):
    rels = [str(f.relative_to(REPO_ROOT)) for f in files]
    subprocess.run(["git", "-C", str(REPO_ROOT), "add", *rels], check=True)
    msg = "chore(ci): gh-runs-watch failure alerts"
    subprocess.run(["git", "-C", str(REPO_ROOT), "commit", "-m", msg],
                   check=True)
    # This runs in a non-served checkout that is often behind origin; a bare
    # push rejects non-ff and strands the alert commit locally (the recurring
    # "uncommitted findings" bug — card kanban-commit-single-writer). Replay
    # onto upstream via the shared safe-pull before each retry instead.
    safe_pull = REPO_ROOT / "scripts" / "git-safe-pull.sh"
    for _ in range(3):
        push = subprocess.run(["git", "-C", str(REPO_ROOT), "push"],
                              capture_output=True, text=True)
        if push.returncode == 0:
            return
        pull = subprocess.run(["bash", str(safe_pull), str(REPO_ROOT)],
                              capture_output=True, text=True)
        if pull.returncode != 0:
            break
    raise subprocess.CalledProcessError(
        push.returncode, push.args, output=push.stdout,
        stderr=push.stderr or (pull.stderr if pull else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=os.environ.get(
        "GH_RUNS_WATCH_REPOS", DEFAULT_REPOS),
        help="comma-separated owner/name repos to poll")
    ap.add_argument("--git", action="store_true",
                    help="commit+push new alert files (served checkouts "
                         "only — non-writer checkouts auto-fall back to "
                         "--api)")
    ap.add_argument("--api", action="store_true",
                    help="post alerts via board-api POST /inbox instead of "
                         "writing repo files (the non-writer path)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be alerted, write nothing")
    args = ap.parse_args()

    # --git on a stamped non-writer checkout can never land (pre-commit
    # role block) — the alert files would rot in the working tree. Route
    # those runs through board-api instead (card
    # exec-checkout-generated-writes-focus-inb-da698a).
    role = checkout_role(REPO_ROOT)
    api_mode = args.api or (args.git and bool(role) and role != "served")
    if api_mode and args.git and not args.api:
        print(f"note: chaba-role={role} — --git cannot commit here; "
              "posting alerts via board-api /inbox", file=sys.stderr)
    git_mode = args.git and not api_mode

    if not resolve_gh_token():
        print("warn: no GH_TOKEN in env or ~/.config/secrets/github-mcp*.env"
              " — gh may hang on keyring auth", file=sys.stderr)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen, alerted = load_state()
    failures, errors = [], 0
    for repo in [r.strip() for r in args.repos.split(",") if r.strip()]:
        runs = gh_runs(repo)
        if runs is None:
            errors += 1
            continue
        for run in runs:
            rid = f"{repo}#{run.get('databaseId')}"
            if rid in seen:
                continue
            seen.add(rid)
            if (run.get("status") == "completed"
                    and run.get("conclusion") == "failure"):
                run["_repo"] = repo
                failures.append(run)

    written, posted, suppressed = [], [], 0
    repeat_cutoff = datetime.now(timezone.utc).timestamp() \
        - API_ALERT_REPEAT_H * 3600
    for run in failures:
        repo = run["_repo"]
        wf = run.get("workflowName", "?")
        br = run.get("headBranch", "?")
        if api_mode:
            combo = f"{repo}|{wf}|{br}"
            try:
                last = datetime.fromisoformat(
                    alerted.get(combo, "")).timestamp()
            except (TypeError, ValueError):
                last = 0.0
            if last > repeat_cutoff:
                suppressed += 1
                print(f"DEDUP {repo} {wf} {br} — api alert posted "
                      f"{alerted.get(combo)}")
                continue
        elif existing_alert(repo, run):
            suppressed += 1
            print(f"DEDUP {repo} {wf} {br} — unresolved alert exists")
            continue
        fname, body = alert_yaml(repo, run)
        print(f"FAIL {repo} {wf} {br} -> "
              + (f"{BOARD_API}/inbox" if api_mode else fname))
        if args.dry_run:
            continue
        if api_mode:
            try:
                if post_inbox(repo, run, now_iso):
                    posted.append(combo)
                    alerted[combo] = now_iso
                else:
                    print(f"warn: /inbox post returned non-2xx for {repo}",
                          file=sys.stderr)
            except Exception as e:
                # API unreachable — fall back to a local file so the alert
                # is not lost entirely (lands when the checkout can commit,
                # or sits as evidence on a served checkout).
                print(f"warn: /inbox post failed ({e}) — writing local "
                      "alert file instead", file=sys.stderr)
                INBOX_DIR.mkdir(parents=True, exist_ok=True)
                f = INBOX_DIR / fname
                f.write_text(body)
                written.append(f)
        else:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            f = INBOX_DIR / fname
            f.write_text(body)
            written.append(f)
    print(f"polled {len(args.repos.split(','))} repo(s): "
          f"{len(failures)} new failure(s) ({suppressed} deduped), "
          f"{len(posted)} posted, {errors} error(s)")

    if not args.dry_run:
        save_state(seen, alerted)
        emit_meta(now_iso, failures, errors)
        if written and git_mode:
            try:
                git_commit_push(written)
                print("pushed alert commit")
            except subprocess.CalledProcessError as e:
                print(f"warn: git push failed: {e}", file=sys.stderr)
    # Poll errors are transient/non-fatal — the timer alert fired for a
    # single slow gh call. meta.yml records status=error for the timeline.
    if errors:
        print(f"warn: {errors} repo poll(s) failed this run", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
