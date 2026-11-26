#!/usr/bin/env python3
"""jack-task — operator-side promotion lane for the shared Jack OpenCode IDE.

The OpenCode container (opencode-jack.surf-thailand.com) holds NO GitHub
credentials: no PAT, no SSH keys, no gh auth. Everything credentialed runs
here, on the idc02 host, as the operator. Jack works inside a per-task
worktree under /workspace/worktrees and may create LOCAL commits; push and
PR creation are operator commands that use a scoped token
(~/.config/secrets/jack-git.env, fine-grained PAT limited to the pilot
repos) that never enters the container.

Pipeline (see stacks/idc02/jack-ide/WORKSPACES.md):

    import -> new -> (Jack edits + local commits in the worktree)
    -> verify -> push -> pr -> HUMAN merge/deploy gate

Layout under the workspace root (~/.local/share/jack-ide/workspace,
bind-mounted into the container as /workspace):

    repos/<name>            operator-imported clones (origin remotes)
    worktrees/<repo>--<slug> per-task git worktrees on jack/<slug>
    shared/ incoming/ outputs/   as documented in WORKSPACES.md
    outputs/lane/           lane state: repos.json + tasks/<slug>.json
    outputs/lane/tasks/<slug>/   verdict.json + test-output.log

Config:
    ~/.config/jack-ide/repos.json     import allowlist (see repos.example.json)
    ~/.config/secrets/jack-git.env    JACK_GIT_TOKEN=... (see jack-git.env.example)

Env overrides (tests): JACK_IDE_WORKSPACE, JACK_IDE_REPOS_CONFIG,
JACK_IDE_GIT_ENV, JACK_TASK_TEST_TIMEOUT.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

WS_ENV = "JACK_IDE_WORKSPACE"
REPOS_ENV = "JACK_IDE_REPOS_CONFIG"
GITENV_ENV = "JACK_IDE_GIT_ENV"
TIMEOUT_ENV = "JACK_TASK_TEST_TIMEOUT"

LAYOUT_DIRS = ["repos", "worktrees", "shared", "incoming", "outputs"]
BRANCH_PREFIX = "jack/"

AGENTS_MD = """# Jack shared workspace — agent rules

Layout: `repos/` operator-imported clones, `worktrees/` per-task worktrees,
`shared/`, `incoming/`, `outputs/` (lane state under `outputs/lane/`).

Rules:
- Work only inside the worktree assigned to your task.
- Local `git add` / `git commit` / `git diff` are allowed inside that
  worktree. NEVER `git push`, `git fetch`-write, or use any credential —
  promotion is operator-run on the host via `jack-task`.
- Never write secrets, keys, tokens, or personal files anywhere here.
- When done, leave the worktree clean (all changes committed) and report
  what you changed; the operator runs `jack-task verify|push|pr`.
- Do not edit anything under `outputs/lane/` — that is operator state.
"""

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
GITHUB_RE = re.compile(r"^https://github\.com/([^/]+)/(.+?)(?:\.git)?/?$")
SSH_GITHUB_RE = re.compile(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$")

# High-confidence secret shapes scanned on ADDED diff lines only.
SECRET_PATTERNS = [
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
]

ENV_ALLOW_SUFFIX = (".example", ".sample", ".template", ".dist")
FORBIDDEN_GLOBS = [
    "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks",
    "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*",
    "*.ppk", "*.kdbx",
]
FORBIDDEN_PARTS = {".ssh", "node_modules/.cache"}
FORBIDDEN_NAMES = {"credentials.json", "credentials", ".netrc", ".npmrc", ".pypirc"}

SCRUB_ENV_RE = re.compile(
    r"(?i)(TOKEN|SECRET|PASSW|CREDENTIAL|API[-_]?KEY|_KEY$|^KEY$|GH_|GITHUB_)")


# ---------------------------------------------------------------------------
# paths / config
# ---------------------------------------------------------------------------

def ws_root() -> Path:
    return Path(os.environ.get(WS_ENV, Path.home() / ".local/share/jack-ide/workspace")).expanduser().resolve()


def repos_config_path() -> Path:
    return Path(os.environ.get(REPOS_ENV, Path.home() / ".config/jack-ide/repos.json")).expanduser()


def git_env_path() -> Path:
    return Path(os.environ.get(GITENV_ENV, Path.home() / ".config/secrets/jack-git.env")).expanduser()


def lane_dir() -> Path:
    return ws_root() / "outputs" / "lane"


def tasks_dir() -> Path:
    return lane_dir() / "tasks"


def repos_registry_path() -> Path:
    return lane_dir() / "repos.json"


def manifest_path(slug: str) -> Path:
    return tasks_dir() / f"{slug}.json"


def task_dir(slug: str) -> Path:
    return tasks_dir() / slug


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_allowlist() -> list[dict]:
    cfg = load_json(repos_config_path(), [])
    if isinstance(cfg, dict):
        cfg = cfg.get("repos", [])
    out = []
    for i, entry in enumerate(cfg or []):
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("url"):
            raise SystemExit(f"repos config entry #{i} needs 'name' and 'url'")
        out.append({
            "name": str(entry["name"]),
            "url": str(entry["url"]),
            "default_branch": entry.get("default_branch"),
        })
    return out


def load_registry() -> dict:
    return load_json(repos_registry_path(), {})


def save_registry(reg: dict) -> None:
    save_json(repos_registry_path(), reg)


def load_manifest(slug: str) -> dict:
    path = manifest_path(slug)
    if not path.exists():
        raise SystemExit(f"no task manifest for '{slug}' — run: jack-task new <repo> {slug}")
    return load_json(path, {})


def save_manifest(slug: str, data: dict) -> None:
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    save_json(manifest_path(slug), data)


def git_token() -> str:
    try:
        for line in git_env_path().read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "JACK_GIT_TOKEN" and v.strip():
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def is_github_https(url: str) -> bool:
    return bool(GITHUB_RE.match(url))


def auth_args(url: str) -> list[str]:
    """git -c args injecting the scoped token — github.com https only, and
    only for this single git invocation (never persisted to config)."""
    tok = git_token()
    if tok and is_github_https(url):
        return ["-c", f"http.extraHeader=AUTHORIZATION: bearer {tok}"]
    return []


def git(cwd: Path, *args: str, url: str | None = None, check: bool = True,
        timeout: int = 300) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(cwd)]
    if url:
        cmd += auth_args(url)
    cmd += list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()[:800]}")
    return proc


def repo_dir(name: str) -> Path:
    return ws_root() / "repos" / name


def worktree_dir(slug_repo: str) -> Path:
    return ws_root() / "worktrees" / slug_repo


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(_args) -> int:
    root = ws_root()
    for d in LAYOUT_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    (tasks_dir()).mkdir(parents=True, exist_ok=True)
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text(AGENTS_MD)
    # Mount source for the supervised Tony<->Jack test (see jack-opencode.container).
    (root.parent / "tony-workspace").mkdir(parents=True, exist_ok=True)
    print(f"workspace: {root}")
    for d in LAYOUT_DIRS:
        print(f"  {d}/")
    print(f"  outputs/lane/  (lane state)")
    print(f"tony mount src: {root.parent / 'tony-workspace'}")
    if not repos_config_path().exists():
        print(f"note: no repo allowlist at {repos_config_path()} — "
              f"copy lane/repos.example.json there to enable `import`", file=sys.stderr)
    return 0


def cmd_repos(_args) -> int:
    allow = {e["name"]: e for e in load_allowlist()}
    reg = load_registry()
    names = sorted(set(allow) | set(reg))
    if not names:
        print("no repos — add entries to", repos_config_path())
        return 0
    for n in names:
        entry = allow.get(n, {})
        imported = n in reg
        mark = "imported" if imported else ("allowlisted" if entry else "registered-only")
        url = entry.get("url") or reg.get(n, {}).get("url", "?")
        print(f"{n:24} {mark:15} {url}")
    return 0


def cmd_import(args) -> int:
    name = args.name
    if not NAME_RE.match(name):
        raise SystemExit(f"bad repo name '{name}' — use [a-z0-9._-]")
    allow = {e["name"]: e for e in load_allowlist()}
    entry = allow.get(name)
    if not entry:
        raise SystemExit(f"'{name}' is not in the allowlist ({repos_config_path()}) — "
                         f"operator adds it there first")
    dest = repo_dir(name)
    if dest.exists():
        raise SystemExit(f"{dest} already exists — refusing to overwrite")
    ws_root().joinpath("repos").mkdir(parents=True, exist_ok=True)
    url = entry["url"]
    print(f"cloning {url} -> repos/{name}")
    proc = subprocess.run(
        ["git"] + auth_args(url) + ["clone", "--quiet", url, str(dest)],
        capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise SystemExit(f"clone failed:\n{proc.stderr.strip()[:800]}")
    # Resolve the default branch from the remote HEAD symref.
    default = entry.get("default_branch")
    if not default:
        head = git(dest, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
                   url=url, check=False)
        if head.returncode == 0 and head.stdout.strip().startswith("origin/"):
            default = head.stdout.strip().split("/", 1)[1]
        else:
            proc = git(dest, "ls-remote", "--symref", "origin", "HEAD",
                       url=url, check=False)
            m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", proc.stdout or "")
            default = m.group(1) if m else None
    if not default:
        raise SystemExit("could not determine default branch — set "
                         "'default_branch' in the repos allowlist entry")
    git(dest, "remote", "set-head", "origin", default)
    reg = load_registry()
    reg[name] = {"url": url, "path": f"repos/{name}", "default_branch": default,
                 "imported_at": now()}
    save_registry(reg)
    print(f"imported repos/{name} (default branch: {default})")
    return 0


def _require_imported(name: str) -> dict:
    reg = load_registry()
    if name not in reg:
        raise SystemExit(f"repo '{name}' is not imported — run: jack-task import {name}")
    d = repo_dir(name)
    if not (d / ".git").exists():
        raise SystemExit(f"repos/{name} is missing or not a git checkout")
    return reg[name]


def cmd_new(args) -> int:
    name, slug = args.repo, args.slug
    if not SLUG_RE.match(slug):
        raise SystemExit(f"bad slug '{slug}' — use [a-z0-9-]")
    info = _require_imported(name)
    if manifest_path(slug).exists():
        raise SystemExit(f"task '{slug}' already exists — pick another slug")
    wt_rel = f"worktrees/{name}--{slug}"
    wt = ws_root() / wt_rel
    if wt.exists():
        raise SystemExit(f"{wt_rel} already exists on disk")
    url = info["url"]
    base_ref = f"origin/{info['default_branch']}"
    print(f"fetching {name} origin...")
    git(repo_dir(name), "fetch", "--quiet", "origin", url=url)
    base_sha = git(repo_dir(name), "rev-parse", base_ref).stdout.strip()
    branch = f"{BRANCH_PREFIX}{slug}"
    git(repo_dir(name), "worktree", "add", "--quiet", str(wt),
        "-b", branch, base_ref)
    man = {
        "slug": slug, "repo": name, "branch": branch,
        "worktree": wt_rel, "base_branch": info["default_branch"],
        "base_sha": base_sha, "description": args.description or "",
        "test_command": args.test,
        "stage": "task", "head_sha": base_sha, "remote_sha": None,
        "pr_url": None, "pr_number": None,
        "created_at": now(), "created_by": "jack-task",
        "last_verdict": None,
    }
    save_manifest(slug, man)
    print(f"worktree ready: /workspace/{wt_rel}")
    print(f"branch: {branch}  (base {info['default_branch']} @ {base_sha[:10]})")
    print("next: Jack edits + commits locally; then `jack-task verify "
          f"{slug}` → `push` → `pr`")
    return 0


def cmd_status(args) -> int:
    mans = sorted(tasks_dir().glob("*.json")) if tasks_dir().exists() else []
    if args.slug:
        mans = [manifest_path(args.slug)] if manifest_path(args.slug).exists() else []
        if not mans:
            raise SystemExit(f"no task '{args.slug}'")
    if not mans:
        print("no tasks yet — jack-task new <repo> <slug>")
        return 0
    for p in mans:
        m = load_json(p, {})
        lv = m.get("last_verdict") or {}
        verdict = "pass" if lv.get("pass") else ("FAIL" if lv else "-")
        print(f"{m.get('slug','?'):28} {m.get('repo','?'):16} {m.get('stage','?'):8} "
              f"{m.get('branch','?'):28} verdict={verdict} pr={m.get('pr_url') or '-'}")
    return 0


# ---------------------------------------------------------------------------
# verify gates
# ---------------------------------------------------------------------------

def _is_env_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if not (base == ".env" or base == ".envrc" or base.startswith(".env.")):
        return False
    return not base.endswith(ENV_ALLOW_SUFFIX)


def _is_forbidden(path: str) -> str | None:
    p = path[2:] if path.startswith("./") else path
    parts = set(p.split("/"))
    if parts & FORBIDDEN_PARTS:
        return "forbidden-dir"
    base = p.rsplit("/", 1)[-1]
    if base in FORBIDDEN_NAMES or any(fnmatch_path(p, g) for g in FORBIDDEN_GLOBS):
        return "forbidden-name"
    if _is_env_file(p):
        return "env-file"
    return None


def fnmatch_path(path: str, pattern: str) -> bool:
    # tiny glob: * doesn't cross /, ** does — covers our pattern set
    return _glob(path=path, pat=pattern)


def _glob(path: str, pat: str) -> bool:
    import fnmatch
    if "/" not in pat:
        return fnmatch.fnmatch(path.rsplit("/", 1)[-1], pat)
    # translate ** -> .*, * -> [^/]*
    rx = ""
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            rx += "(?:.*/)?"; i += 3
        elif pat.startswith("**", i):
            rx += ".*"; i += 2
        elif pat[i] == "*":
            rx += "[^/]*"; i += 1
        else:
            rx += re.escape(pat[i]); i += 1
    return re.fullmatch(rx, path) is not None


def _scan_secrets(diff_text: str) -> list[dict]:
    hits = []
    cur_file = "?"
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            for name, rx in SECRET_PATTERNS:
                if rx.search(body):
                    hits.append({"file": cur_file, "pattern": name})
                    break
    return hits


def _run_tests(man: dict, wt: Path, cmd: str | None) -> dict:
    test_cmd = cmd or man.get("test_command")
    if not test_cmd:
        return {"status": "skipped", "reason": "no test command "
                "(--test or manifest test_command)"}
    timeout = int(os.environ.get(TIMEOUT_ENV, "600"))
    env = {k: v for k, v in os.environ.items() if not SCRUB_ENV_RE.search(k)}
    tdir = task_dir(man["slug"])
    tdir.mkdir(parents=True, exist_ok=True)
    log_path = tdir / "test-output.log"
    t0 = time.time()
    try:
        proc = subprocess.run(["bash", "-c", test_cmd], cwd=str(wt), env=env,
                              capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        rc = proc.returncode
    except subprocess.TimeoutExpired as e:
        out = f"TIMEOUT after {timeout}s\n" + (e.stdout or "")
        rc = 124
    log_path.write_text(out[-200_000:])
    return {"status": "pass" if rc == 0 else "fail", "command": test_cmd,
            "returncode": rc, "seconds": round(time.time() - t0, 1),
            "log": str(log_path.relative_to(ws_root()))}


def cmd_verify(args) -> int:
    slug = args.slug
    man = load_manifest(slug)
    wt_rel = man["worktree"]
    wt = ws_root() / wt_rel
    gates = {}
    head_sha = ""

    # gate: worktree identity + branch scope
    top = git(wt, "rev-parse", "--show-toplevel", check=False) if wt.exists() else None
    branch = git(wt, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip() if wt.exists() else ""
    gates["worktree"] = {"pass": bool(top and Path(top.stdout.strip()).resolve() == wt.resolve()),
                         "path": wt_rel}
    gates["branch_scope"] = {
        "pass": branch == man["branch"] and branch.startswith(BRANCH_PREFIX),
        "branch": branch, "expected": man["branch"]}

    if wt.exists():
        head_sha = git(wt, "rev-parse", "HEAD").stdout.strip()
        dirty = git(wt, "status", "--porcelain").stdout.strip()
        gates["clean_tree"] = {"pass": not dirty,
                               "note": "all changes must be committed locally" if dirty else "clean"}
    else:
        gates["clean_tree"] = {"pass": False, "note": "worktree missing"}

    # gate: diff scope — base must exist, collect changed paths + added lines
    base_ref = args.base or f"origin/{man['base_branch']}"
    changed, secret_hits, diff_stat = [], [], ""
    if wt.exists() and gates["worktree"]["pass"]:
        mb = git(wt, "merge-base", base_ref, "HEAD", check=False)
        if mb.returncode != 0:
            gates["base"] = {"pass": False, "ref": base_ref,
                             "note": "no merge-base — fetch/rebase first"}
        else:
            gates["base"] = {"pass": True, "ref": base_ref,
                             "merge_base": mb.stdout.strip()[:12]}
            names = git(wt, "diff", "--name-only", f"{base_ref}...HEAD").stdout.split()
            changed = names
            patch = git(wt, "diff", f"{base_ref}...HEAD").stdout
            secret_hits = _scan_secrets(patch)
            stat = git(wt, "diff", "--shortstat", f"{base_ref}...HEAD").stdout.strip()
            diff_stat = stat
            forbidden = [(p, _is_forbidden(p)) for p in names]
            forbidden = [(p, why) for p, why in forbidden if why]
            gates["forbidden_paths"] = {"pass": not forbidden,
                                        "hits": [{"file": p, "reason": w} for p, w in forbidden]}
            gates["secret_scan"] = {"pass": not secret_hits,
                                    "hits": secret_hits[:20],
                                    "scanned": "added diff lines"}
            gates["diff"] = {"pass": True, "files": len(names), "stat": diff_stat,
                             "files_list": names[:100]}
    else:
        gates.setdefault("base", {"pass": False, "ref": base_ref})
        gates.setdefault("forbidden_paths", {"pass": False})
        gates.setdefault("secret_scan", {"pass": False})

    # gate: tests (only when the tree gates pass — don't burn time on a bad diff)
    tree_ok = all(g.get("pass") for g in
                  (gates.get("worktree"), gates.get("branch_scope"),
                   gates.get("clean_tree"), gates.get("base"),
                   gates.get("forbidden_paths"), gates.get("secret_scan")))
    if tree_ok:
        gates["tests"] = _run_tests(man, wt, args.test)
    else:
        gates["tests"] = {"status": "skipped", "reason": "earlier gates failed"}

    passed = all(g.get("pass", g.get("status") in ("pass", "skipped"))
                 for g in gates.values())
    verdict = {
        "slug": slug, "repo": man["repo"], "branch": man.get("branch"),
        "head_sha": head_sha, "base_ref": base_ref,
        "checked_at": now(), "pass": passed, "gates": gates,
    }
    tdir = task_dir(slug)
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    man["last_verdict"] = {"pass": passed, "head_sha": head_sha,
                           "checked_at": verdict["checked_at"]}
    if passed:
        man["stage"] = "verified"
        man["head_sha"] = head_sha
    save_manifest(slug, man)

    print(f"verify {slug}: {'PASS' if passed else 'FAIL'}  head={head_sha[:10] or '-'}")
    for name, g in gates.items():
        ok = g.get("pass", g.get("status") in ("pass", "skipped"))
        print(f"  [{'ok' if ok else 'XX'}] {name}: {g.get('note') or g.get('reason') or g.get('stat') or ''}")
    if not passed:
        print(f"details: {tdir.relative_to(ws_root())}/verdict.json")
    return 0 if passed else 1


def _push_url_and_auth(repo_url: str):
    """Return (push_url, needs_token, warn)."""
    if is_github_https(repo_url):
        return repo_url, True, None
    if repo_url.startswith("git@github.com:"):
        return repo_url, False, "github SSH remote — push uses the HOST ssh key, not the scoped token"
    return repo_url, False, None


def cmd_push(args) -> int:
    slug = args.slug
    man = load_manifest(slug)
    wt = ws_root() / man["worktree"]
    if not wt.exists():
        raise SystemExit(f"worktree missing: {man['worktree']}")
    lv = man.get("last_verdict") or {}
    head = git(wt, "rev-parse", "HEAD").stdout.strip()
    if man.get("stage") not in ("verified", "pushed") or not lv.get("pass"):
        raise SystemExit("no passing verify verdict — run `jack-task verify "
                         f"{slug}` first (independent gate)")
    if lv.get("head_sha") != head:
        raise SystemExit(f"HEAD moved since verify ({(lv.get('head_sha') or '?')[:10]} -> "
                         f"{head[:10]}) — re-run `jack-task verify {slug}`")
    branch = man["branch"]
    if not branch.startswith(BRANCH_PREFIX) or branch == man["base_branch"]:
        raise SystemExit(f"refusing to push non-task branch '{branch}'")
    origin = git(repo_dir(man["repo"]), "remote", "get-url", "origin").stdout.strip()
    push_url, needs_token, warn = _push_url_and_auth(origin)
    if warn:
        print(f"warn: {warn}", file=sys.stderr)
    if needs_token and not git_token():
        raise SystemExit("github https remote needs JACK_GIT_TOKEN in "
                         f"{git_env_path()} (fine-grained PAT, contents+PR write)")
    print(f"pushing {branch} -> {re.sub(r'^https://', 'https://', push_url)}")
    proc = git(wt, "push", push_url, f"HEAD:refs/heads/{branch}",
               url=push_url if is_github_https(push_url) else None, check=False, timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"push failed:\n{proc.stderr.strip()[:800]}")
    # confirm the remote ref matches local HEAD
    ls = git(wt, "ls-remote", push_url, f"refs/heads/{branch}",
             url=push_url if is_github_https(push_url) else None, check=False)
    remote_sha = ""
    for line in (ls.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{branch}":
            remote_sha = parts[0]
    if remote_sha != head:
        raise SystemExit(f"push reported ok but remote sha {remote_sha[:10] or '?'} "
                         f"!= local {head[:10]} — investigate before PR")
    man["stage"] = "pushed"
    man["remote_sha"] = remote_sha
    man["pushed_at"] = now()
    save_manifest(slug, man)
    print(f"pushed {branch} @ {remote_sha[:10]} — PR is the next human-reviewed step")
    return 0


def _github_repo(origin_url: str):
    m = GITHUB_RE.match(origin_url) or SSH_GITHUB_RE.match(origin_url)
    if not m:
        return None
    return m.group(1), re.sub(r"\.git$", "", m.group(2))


def cmd_pr(args) -> int:
    slug = args.slug
    man = load_manifest(slug)
    if man.get("stage") not in ("pushed", "pr") or not man.get("remote_sha"):
        raise SystemExit("branch not pushed yet — run `jack-task push "
                         f"{slug}` first")
    if man.get("pr_url"):
        print(f"PR already open: {man['pr_url']}")
        return 0
    origin = git(repo_dir(man["repo"]), "remote", "get-url", "origin").stdout.strip()
    gh = _github_repo(origin)
    if not gh:
        raise SystemExit(f"origin {origin} is not a github.com repo — PR step needs github")
    owner, repo = gh
    branch, base = man["branch"], man["base_branch"]
    title = args.title or man.get("description") or f"{branch}: {slug}"
    body = args.body or (
        f"## Summary\n\n{man.get('description') or 'Jack shared-workspace task.'}\n\n"
        f"## Test plan\n\n"
        f"- lane verify: {(man.get('last_verdict') or {}).get('pass') and 'PASS' or 'see verdict'} "
        f"(head {(man.get('head_sha') or '')[:10]})\n"
        f"- test command: `{man.get('test_command') or 'none declared'}`\n\n"
        f"Card: {slug}\n\n"
        f"_Promoted via jack-task lane; merge remains a human gate._\n")
    payload = {"title": title, "head": branch, "base": base, "body": body}
    api = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    if args.dry_run:
        print(f"POST {api}\n{json.dumps(payload, indent=2)}")
        return 0
    tok = git_token()
    if not tok:
        raise SystemExit(f"PR creation needs JACK_GIT_TOKEN in {git_env_path()}")
    req = urllib.request.Request(
        api, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "jack-task-lane"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SystemExit(f"GitHub PR create failed: HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"GitHub PR create failed: {e}")
    man["stage"] = "pr"
    man["pr_url"] = data.get("html_url")
    man["pr_number"] = data.get("number")
    save_manifest(slug, man)
    print(f"PR #{data.get('number')}: {data.get('html_url')}")
    print("merge + deploy remain human gates — review the diff on GitHub.")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jack-task",
        description="Operator promotion lane for the shared Jack OpenCode workspace.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create workspace layout + agent rules")
    sub.add_parser("repos", help="list allowlisted/imported repos")

    pi = sub.add_parser("import", help="clone an allowlisted repo into repos/")
    pi.add_argument("name")

    pn = sub.add_parser("new", help="create per-task worktree + jack/<slug> branch")
    pn.add_argument("repo")
    pn.add_argument("slug")
    pn.add_argument("--description", default="")
    pn.add_argument("--test", default=None, help="test command run by verify")

    ps = sub.add_parser("status", help="show task pipeline state")
    ps.add_argument("slug", nargs="?")

    pv = sub.add_parser("verify", help="run secret/scope/test gates on the task diff")
    pv.add_argument("slug")
    pv.add_argument("--base", default=None, help="override base ref (default origin/<base_branch>)")
    pv.add_argument("--test", default=None, help="override test command")

    pp = sub.add_parser("push", help="push jack/<slug> via scoped token (verify must pass)")
    pp.add_argument("slug")

    pr = sub.add_parser("pr", help="open a GitHub PR for the pushed branch")
    pr.add_argument("slug")
    pr.add_argument("--title", default=None)
    pr.add_argument("--body", default=None)
    pr.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "init": cmd_init, "repos": cmd_repos, "import": cmd_import,
        "new": cmd_new, "status": cmd_status, "verify": cmd_verify,
        "push": cmd_push, "pr": cmd_pr,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
