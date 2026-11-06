#!/usr/bin/env python3
"""jules — minimal Jules REST API client for the DevNest `jules` lane.

Card: OPS-1048 (devnest-google-ai-pro-verify-new-cheap-l-522402).
Auth: JULES_API_KEY from ~/.config/secrets/jules.env (or process env).
Stdlib only — runs on any tailnet host with the env file.

Usage:
  jules.py create --repo owner/name [--branch main] --prompt "..."|--prompt-file f
                  [--title T] [--auto-pr] [--approve-plan]
  jules.py status <session-id-or-name>
  jules.py activities <session-id-or-name> [--limit N]
  jules.py wait   <session-id-or-name> [--timeout 3600] [--approve] [--interval 30]
  jules.py result <session-id-or-name>     # state + PR urls
  jules.py list  [--page-size N]
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

BASE = os.environ.get("JULES_API_BASE", "https://jules.googleapis.com/v1alpha")
ENV_FILE = Path(os.environ.get("JULES_ENV", "~/.config/secrets/jules.env")).expanduser()

TERMINAL = {"COMPLETED", "FAILED"}
AWAITING = {"AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK"}


def load_env():
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


ENV = load_env()
KEY = ENV.get("JULES_API_KEY", "")
if not KEY or KEY.startswith("__"):
    sys.exit("JULES_API_KEY missing — fill ~/.config/secrets/jules.env")


def req(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "x-goog-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        sys.exit(f"HTTP {e.code} {method} {path}: {detail}")


def sid(x):
    return x if x.startswith("sessions/") else f"sessions/{x}"


def source_name(repo):
    """Resolve owner/repo to the API source resource name."""
    owner, name = repo.split("/", 1)
    token = None
    while True:
        path = "/sources?pageSize=100" + (f"&pageToken={token}" if token else "")
        d = req("GET", path)
        for s in d.get("sources", []):
            gh = s.get("githubRepo") or {}
            if gh.get("owner") == owner and gh.get("repo") == name:
                return s["name"]
        token = d.get("nextPageToken")
        if not token:
            break
    sys.exit(f"repo {repo} not connected to Jules (install the GitHub app)")


def cmd_create(a):
    prompt = a.prompt
    if a.prompt_file:
        prompt = Path(a.prompt_file).read_text()
    if not prompt.strip():
        sys.exit("empty prompt")
    body = {
        "prompt": prompt,
        "sourceContext": {
            "source": source_name(a.repo),
            "githubRepoContext": {"startingBranch": a.branch},
        },
    }
    if a.title:
        body["title"] = a.title
    if a.auto_pr:
        body["automationMode"] = "AUTO_CREATE_PR"
    if a.approve_plan is not None:
        body["requirePlanApproval"] = a.approve_plan
    print(json.dumps(req("POST", "/sessions", body), indent=2))


def cmd_status(a):
    print(json.dumps(req("GET", f"/{sid(a.session)}"), indent=2))


def cmd_activities(a):
    d = req("GET", f"/{sid(a.session)}/activities?pageSize={a.limit}")
    for act in d.get("activities", []):
        ev = next((k for k in act if k not in
                   ("name", "id", "originator", "description", "createTime",
                    "artifacts")), "?")
        print(f"{act.get('createTime','?')} [{act.get('originator','?')}] "
              f"{ev}: {(act.get('description') or '')[:200]}")


def cmd_wait(a):
    deadline = time.time() + a.timeout
    while True:
        s = req("GET", f"/{sid(a.session)}")
        state = s.get("state", "?")
        print(f"[{time.strftime('%H:%M:%S')}] {state} {s.get('url','')}",
              flush=True)
        if state == "AWAITING_PLAN_APPROVAL" and a.approve:
            req("POST", f"/{sid(a.session)}:approvePlan", {})
            print("  -> plan approved", flush=True)
        if state in TERMINAL or (state in AWAITING and not a.approve) \
                or time.time() > deadline:
            print(json.dumps(s, indent=2))
            return
        time.sleep(a.interval)


def cmd_result(a):
    s = req("GET", f"/{sid(a.session)}")
    print(f"state: {s.get('state')}")
    print(f"url:   {s.get('url')}")
    for o in s.get("outputs", []):
        pr = o.get("pullRequest") or {}
        if pr:
            print(f"PR:    {pr.get('url')}  {pr.get('title','')}")
    if not s.get("outputs"):
        print("outputs: none")


def cmd_list(a):
    print(json.dumps(req("GET", f"/sessions?pageSize={a.page_size}"), indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--repo", required=True, help="owner/name")
    c.add_argument("--branch", default="main")
    c.add_argument("--prompt")
    c.add_argument("--prompt-file")
    c.add_argument("--title")
    c.add_argument("--auto-pr", action="store_true")
    c.add_argument("--approve-plan", action=argparse.BooleanOptionalAction,
                   default=None)
    c.set_defaults(f=cmd_create)

    for name, f in (("status", cmd_status), ("result", cmd_result)):
        s = sub.add_parser(name)
        s.add_argument("session")
        s.set_defaults(f=f)

    s = sub.add_parser("activities")
    s.add_argument("session")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(f=cmd_activities)

    s = sub.add_parser("wait")
    s.add_argument("session")
    s.add_argument("--timeout", type=int, default=3600)
    s.add_argument("--interval", type=int, default=30)
    s.add_argument("--approve", action="store_true",
                   help="auto-approve pending plans")
    s.set_defaults(f=cmd_wait)

    s = sub.add_parser("list")
    s.add_argument("--page-size", type=int, default=20)
    s.set_defaults(f=cmd_list)

    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
