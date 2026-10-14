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
are committed and pushed so downstream checkouts see them on pull.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INBOX_DIR = REPO_ROOT / "docs" / "ssot" / "focus-inbox"
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
    try:
        return set(json.loads(STATE_FILE.read_text()).get("seen", []))
    except Exception:
        return set()


def save_state(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"seen": sorted(seen)[-500:]}))


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
                    help="commit+push new alert files")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be alerted, write nothing")
    args = ap.parse_args()

    if not resolve_gh_token():
        print("warn: no GH_TOKEN in env or ~/.config/secrets/github-mcp*.env"
              " — gh may hang on keyring auth", file=sys.stderr)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = load_state()
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

    written, suppressed = [], 0
    for run in failures:
        if existing_alert(run["_repo"], run):
            suppressed += 1
            print(f"DEDUP {run['_repo']} {run.get('workflowName')} "
                  f"{run.get('headBranch')} — unresolved alert exists")
            continue
        fname, body = alert_yaml(run["_repo"], run)
        print(f"FAIL {run['_repo']} {run.get('workflowName')} "
              f"{run.get('headBranch')} -> {fname}")
        if not args.dry_run:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            f = INBOX_DIR / fname
            f.write_text(body)
            written.append(f)
    print(f"polled {len(args.repos.split(','))} repo(s): "
          f"{len(failures)} new failure(s) ({suppressed} deduped), "
          f"{errors} error(s)")

    if not args.dry_run:
        save_state(seen)
        emit_meta(now_iso, failures, errors)
        if written and args.git:
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
