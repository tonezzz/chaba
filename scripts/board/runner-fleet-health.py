#!/usr/bin/env python3
"""runner-fleet-health — dispatch-host bootstrap audit -> kanban cards.

Probes every dispatch-capable host in ssot.kanban.yml runner_fleet and
writes/updates `runner-auto-<host>` cards so a provisioning gap becomes
tracked work instead of a stranded dispatch. Mirrors cms-auto-health /
gev-auto-health's lifecycle:

  violation      -> column=review, note = failing checks (incident log)
  recovers       -> column=done, note records the recovery time
  host leaves    -> its card auto-closes (ghost sweep)
  open >= 12h    -> priority bumped to high
  green fleet    -> no cards, silent

Checks per host (card runner-bootstrap-check — each maps to a real
stranding):
  git-identity       user.name+user.email resolvable — dispatch commits
                     need it (idc03: checkpoint+auto-merge failed)
  clone-*            ~/CascadeProjects/chaba exists, has .git, is not
                     >MAX_BEHIND commits behind origin/master (mn01 ghost
                     checkout; idc01 was 860 behind)
  remote-*           chaba's origin is fetchable; when it's fetch-only
                     (https, no push creds — by design) the merge-sweep
                     salvage path is probed: `git ls-remote <host>:<path>`
                     from here (runner branches are fetched over tailnet
                     ssh by merge-sweep, not pushed)
  runner-agent-*     ~/.local/bin/runner-agent exists, parses, matches
                     the repo copy (installed copies drift — mn01 ran a
                     stale devin-dispatch missing DEVIN_MODEL passthrough)
  dispatch-repos-*   runner-agent's dr_module() resolution finds a
                     dispatch_repos that imports AND has close_out +
                     close_out_notes (idc01 AttributeError crash-loop)
  devin-cli          a devin binary resolves via devin-dispatch.sh's
                     order (PATH -> ~/.local/bin -> bundled desktop)

Runs inside kanban-sync.sh's tick on tony-dell (writes into its detached
worktree; committing is the wrapper's job). Remote probes ride one
`ssh <host> python3 -` per host — stdlib only, no yaml on the runner.

Env: CHABA_REPO, RUNNER_FLEET_HOSTS (override fleet parse),
     RUNNER_FLEET_MAX_BEHIND (default 200), RUNNER_FLEET_SKIP_SSH=1
     (probe everything locally — dev/debug).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
KANBAN_SSOT = REPO / "docs" / "ssot" / "kanban" / "ssot.kanban.yml"

HOST = os.uname().nodename
MAX_BEHIND = int(os.environ.get("RUNNER_FLEET_MAX_BEHIND", "200"))
ESCALATE_H = 12
SSH_TIMEOUT = 120          # probe includes one git fetch on the host
FALLBACK_HOSTS = ["tony-dell", "tony-omen", "idc01", "idc02", "idc03",
                  "mn01"]

# repo-side reference copies; installed drift is checked against these
REFS = {
    "runner_agent": REPO / "scripts" / "board" / "runner-agent.py",
    "devin_dispatch": REPO / "scripts" / "devin" / "devin-dispatch.sh",
    "dispatch_repos": REPO / "scripts" / "board" / "dispatch_repos.py",
}

HELP = {
    "unreachable":
        "ssh <host> fails — the runner can't be probed, claimed, or "
        "salvaged. Check tailscale + sshd + the key on the host.",
    "git":
        "git itself is missing/broken on the host — apt install git "
        "before anything else can work.",
    "git-identity":
        "ssh <host> 'git config --global user.name Devin; git config "
        "--global user.email 158243242+devin-ai-integration[bot]"
        "@users.noreply.github.com' (the 2026-10-09 fleet convention).",
    "clone-missing":
        "ssh <host> 'git clone https://github.com/tonezzz/chaba.git "
        "~/CascadeProjects/chaba' — it backs dispatch_repos imports and "
        "is the default dispatch repo.",
    "clone-no-git":
        "Directory exists but isn't a repo (mn01 ghost-checkout "
        "pattern). Move it aside and reclone.",
    "clone-stale":
        "ssh <host> 'git -C ~/CascadeProjects/chaba pull --ff-only' — "
        "stale clones crash runner-agent on missing dispatch_repos "
        "helpers (idc01, 860 behind).",
    "clone-fetch":
        "git fetch origin fails on the host — check egress/DNS to "
        "github.com from <host>.",
    "remote-push":
        "Clone's origin is fetch-only AND `git ls-remote <host>:<path>` "
        "fails from tony-dell — neither runner-push nor merge-sweep "
        "salvage can land its session branches.",
    "runner-agent":
        "Redeploy: scp scripts/board/runner-agent.py "
        "<host>:~/.local/bin/runner-agent && ssh <host> chmod +x "
        "~/.local/bin/runner-agent",
    "devin-dispatch":
        "Redeploy: scp scripts/devin/devin-dispatch.sh "
        "<host>:~/.local/bin/devin-dispatch && ssh <host> chmod +x "
        "~/.local/bin/devin-dispatch",
    "dispatch-repos":
        "Refresh ~/CascadeProjects/chaba on the host (pull --ff-only) — "
        "runner-agent imports dispatch_repos.py from that checkout.",
    "devin-cli":
        "Install the devin CLI on the host or keep it out of the "
        "dispatch-capable fleet (runner_fleet in ssot.kanban.yml).",
    "repo-checkout":
        "A declared dispatch repo checkout is missing/.git-less on the "
        "host — reclone it or drop it from that host's repos.conf.",
}


# ---------------------------------------------------------- host probe
# Runs via `ssh <host> python3 -` (or local python3 -). Stdlib only —
# runner hosts are not guaranteed to have PyYAML. Prints one JSON doc.
REMOTE_PROBE = r'''
import hashlib, json, os, subprocess, sys
from pathlib import Path

HOME = Path.home()
FETCH_REPO = "chaba"          # the canonical clone — the one we refresh+count
DR_ATTRS = ["close_out", "close_out_notes"]  # runner-agent finish path needs both

def run(cmd, timeout=30, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return 127, "", str(e)

def sha(p):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    except Exception:
        return None

def repos_table():
    """host's $DISPATCH_DIR/repos.conf, else the devin-dispatch builtin."""
    conf = Path(os.environ.get("DISPATCH_DIR",
                               HOME / ".local/share/devin-dispatch")) / "repos.conf"
    table = {}
    try:
        for ln in conf.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            if not ln:
                continue
            p = ln.split()
            table[p[0]] = {"path": str(Path(p[1]).expanduser()),
                           "branch": p[2] if len(p) > 2 else "master"}
    except Exception:
        pass
    if not table:
        table = {"chaba": {"path": str(HOME / "CascadeProjects/chaba"),
                           "branch": "master"},
                 "ada-pi": {"path": str(HOME / "CascadeProjects/ada-pi"),
                            "branch": "main"},
                 "sunsynk-card": {"path": str(HOME /
                    "CascadeProjects/sunsynk-power-flow-card"),
                                  "branch": "main"},
                 "mddb-fork": {"path": str(HOME / "CascadeProjects/mddb-fork"),
                               "branch": "main"},
                 "gods-eye-view": {"path": str(HOME / "gods-eye-view"),
                                   "branch": "main"}}
    return table

out = {"nodename": os.uname().nodename}

rc, _, _ = run(["git", "--version"])
out["git_ok"] = rc == 0

# git identity — committer ident resolves global+repo+env, i.e. exactly
# what a dispatch checkpoint commit needs.
rc, so, se = run(["git", "var", "GIT_COMMITTER_IDENT"], cwd=str(HOME))
_, gn, _ = run(["git", "config", "--global", "user.name"])
_, ge, _ = run(["git", "config", "--global", "user.email"])
out["ident"] = {"ok": rc == 0, "detail": so or se,
                "global_name": gn, "global_email": ge}

# dispatch repo checkouts
repos = {}
for name, ent in repos_table().items():
    p = Path(ent["path"])
    e = {"path": str(p), "exists": p.is_dir(),
         "has_git": (p / ".git").exists()}
    if not e["has_git"]:
        repos[name] = e
        continue
    _, e["remote"], rse = run(["git", "-C", str(p),
                               "remote", "get-url", "origin"])
    _, e["ssh_cmd"], _ = run(["git", "-C", str(p),
                              "config", "core.sshCommand"])
    _, e["head_branch"], _ = run(["git", "-C", str(p),
                                  "rev-parse", "--abbrev-ref", "HEAD"])
    _, e["shallow"], _ = run(["git", "-C", str(p),
                              "rev-parse", "--is-shallow-repository"])
    base = f"origin/{ent['branch']}"
    if name == FETCH_REPO:
        # real fetch — the count must be against today's origin, not
        # whatever the ref last saw (these checkouts never auto-pull)
        frc, _, fse = run(["git", "-C", str(p), "fetch", "-q",
                           "origin", ent["branch"]], timeout=45)
        e["fetch_ok"] = frc == 0
        if frc:
            e["fetch_err"] = (fse or "")[:200]
    brc, bso, bse = run(["git", "-C", str(p), "rev-list", "--count",
                         f"HEAD..{base}"])
    e["behind"] = int(bso) if brc == 0 and bso.isdigit() else None
    e["behind_err"] = "" if brc == 0 else (bse or "")[:160]
    repos[name] = e
out["repos"] = repos

# installed dispatch executables — deployed as single-file copies
inst = {}
for key, path in (("runner_agent", HOME / ".local/bin/runner-agent"),
                  ("devin_dispatch", HOME / ".local/bin/devin-dispatch")):
    e = {"path": str(path), "exists": path.exists(),
         "exec": os.access(path, os.X_OK), "sha": sha(path)}
    if e["exists"]:
        if key == "runner_agent":
            rc, so, se = run([sys.executable, "-c",
                              "import sys;compile(open(sys.argv[1]).read(),"
                              "sys.argv[1],'exec')", str(path)])
        else:
            rc, so, se = run(["bash", "-n", str(path)])
        e["syntax_ok"] = rc == 0
        if rc:
            e["syntax_err"] = (se or so)[:160]
    inst[key] = e
out["installed"] = inst

# dispatch_repos resolution — mirror runner-agent.dr_module() exactly:
# $DISPATCH_REPOS_DIR, dir of the installed runner-agent,
# ~/CascadeProjects/chaba/scripts/board.
dr = {"resolved_dir": None, "import_ok": False, "missing": list(DR_ATTRS)}
cands = []
if os.environ.get("DISPATCH_REPOS_DIR"):
    cands.append(Path(os.environ["DISPATCH_REPOS_DIR"]))
cands.append(HOME / ".local/bin")
cands.append(HOME / "CascadeProjects/chaba/scripts/board")
for d in cands:
    f = d / "dispatch_repos.py"
    if not f.exists():
        continue
    dr["resolved_dir"] = str(d)
    dr["path"] = str(f)
    dr["sha"] = sha(f)
    sys.path.insert(0, str(d))
    try:
        import dispatch_repos as mod
        dr["import_ok"] = True
        dr["missing"] = [a for a in DR_ATTRS if not hasattr(mod, a)]
    except Exception as ex:
        dr["import_err"] = f"{type(ex).__name__}: {ex}"
    break
out["dispatch_repos"] = dr

# devin CLI — devin-dispatch.sh's own resolution order:
# PATH -> ~/.local/bin -> bundled desktop binary.
devin = {"path": None}
rc, so, _ = run(["sh", "-c", "command -v devin"])
cands = ([so] if rc == 0 and so else []) + [
    str(HOME / ".local/bin/devin"),
    "/usr/share/devin-desktop/resources/app/extensions/windsurf/devin/bin/devin"]
for c in cands:
    if c and Path(c).exists():
        devin["path"] = c
        break
if devin["path"]:
    rc, so, se = run([devin["path"], "--version"], timeout=20)
    devin["version"] = (so or se).splitlines()[0][:80] if rc == 0 else None
out["devin"] = devin

print(json.dumps(out))
'''


def sh(cmd: list, timeout: int = 60,
       stdin: str = "") -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, input=stdin or None)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def fleet() -> list[str]:
    """Dispatch hosts from ssot.kanban.yml's runner_fleet prose — the
    '<host>:' labels in that string. Env override wins; empty parse
    falls back to the hardcoded table."""
    env = os.environ.get("RUNNER_FLEET_HOSTS")
    if env:
        return [h.strip() for h in env.split(",") if h.strip()]
    def _find(d, key):
        if isinstance(d, dict):
            for k, v in d.items():
                if k == key:
                    return v
                r = _find(v, key)
                if r is not None:
                    return r
        return None

    try:
        doc = yaml.safe_load(KANBAN_SSOT.read_text()) or {}
        text = str(_find(doc, "runner_fleet") or "")
        hosts = re.findall(r"\b(tony-[\w-]+|idc\d+|mn\d+)\s*:", text)
        seen = []
        for h in hosts:
            if h not in seen:
                seen.append(h)
        if seen:
            return seen
    except Exception:
        pass
    return list(FALLBACK_HOSTS)


def probe(host: str) -> dict | None:
    """One JSON doc from the host; None on unreachable/undecodable."""
    local = host == HOST or os.environ.get("RUNNER_FLEET_SKIP_SSH")
    cmd = ([sys.executable, "-"] if local else
           ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            host, "python3", "-"])
    r = sh(cmd, timeout=SSH_TIMEOUT, stdin=REMOTE_PROBE)
    if r.returncode != 0:
        return {"_error": ((r.stderr or r.stdout).strip()[:200]
                           or f"probe rc={r.returncode}")}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_error": f"undecodable probe output: "
                          f"{r.stdout[:160]}"}


def salvage_ok(host: str, chaba_path: str) -> bool:
    """merge-sweep's actual mechanism: git fetch <host>:<path> over
    tailnet ssh from tony-dell. ls-remote probes it without writing."""
    r = sh(["git", "-c", "core.sshCommand=ssh", "ls-remote",
            f"{host}:{chaba_path}", "HEAD"], timeout=30)
    return r.returncode == 0


def push_capable(repo: dict) -> bool:
    url = repo.get("remote") or ""
    return url.startswith(("git@", "ssh://")) or \
        bool(repo.get("ssh_cmd"))


def judge(host: str, d: dict, refsha: dict) -> tuple[list, list]:
    """-> (violations, notes). Each violation is (help_key, detail)."""
    v, notes = [], []
    if d.get("_error"):
        return [("unreachable", f"probe failed: {d['_error']}")], notes

    git_ok = d.get("git_ok", True)
    if not git_ok:
        v.append(("git", "git --version failed — no git on host"))

    ident = d.get("ident") or {}
    if git_ok and not ident.get("ok"):
        v.append(("git-identity",
                  f"git committer ident unresolvable "
                  f"(user.name={ident.get('global_name') or 'unset'} "
                  f"user.email={ident.get('global_email') or 'unset'}) — "
                  f"dispatch checkpoint/merge commits will fail"))

    repos = d.get("repos") or {}
    chaba = repos.get("chaba") or {}
    if not git_ok:
        pass  # every repo check would be noise — the git violation says it
    elif not chaba.get("exists"):
        v.append(("clone-missing",
                  f"{chaba.get('path', '~/CascadeProjects/chaba')} does "
                  f"not exist"))
    elif not chaba.get("has_git"):
        v.append(("clone-no-git",
                  f"{chaba['path']} exists but has no .git — the mn01 "
                  f"ghost-checkout failure"))
    else:
        behind = chaba.get("behind")
        if not chaba.get("remote"):
            v.append(("remote-push", "chaba clone has no origin remote"))
        if chaba.get("fetch_ok") is False:
            if behind:
                v.append(("clone-fetch",
                          f"git fetch origin failed AND {behind} commits "
                          f"behind last-fetched ref — clone can't "
                          f"refresh ({chaba.get('fetch_err', '')[:80]})"))
            else:
                notes.append(f"chaba fetch failed but clone was current "
                             f"at last fetch — transient? "
                             f"({chaba.get('fetch_err', '')[:80]})")
        elif behind is None:
            notes.append(f"chaba behind-count unknown "
                         f"({chaba.get('behind_err') or 'shallow?'})")
        elif behind > MAX_BEHIND:
            v.append(("clone-stale",
                      f"chaba clone {behind} commits behind "
                      f"origin/master (limit {MAX_BEHIND})"))
        if chaba.get("remote") and not push_capable(chaba):
            if host != HOST and not salvage_ok(host, chaba["path"]):
                v.append(("remote-push",
                          f"origin is fetch-only "
                          f"({chaba['remote']}) and dell cannot "
                          f"ls-remote {host}:{chaba['path']} — "
                          f"merge-sweep can't salvage branches"))
            elif host != HOST:
                notes.append("chaba origin is fetch-only (by design — "
                             "no push creds); merge-sweep salvage path "
                             "verified")
            else:
                notes.append("chaba origin is fetch-only (no push "
                             "creds on this clone)")
        elif chaba.get("remote"):
            notes.append("chaba origin is push-capable")

    for name, e in (repos.items() if git_ok else []):
        if name == "chaba":
            continue
        if not e.get("exists"):
            notes.append(f"no {name} checkout — host can't take "
                         f"action.repo={name} cards")
            continue
        if not e.get("has_git"):
            v.append(("repo-checkout",
                      f"{name}: {e['path']} exists but has no .git"))
            continue
        if not e.get("remote"):
            v.append(("repo-checkout",
                      f"{name}: no origin remote"))
        b = e.get("behind")
        if b is not None and b > MAX_BEHIND:
            v.append(("repo-checkout",
                      f"{name}: {b} commits behind "
                      f"origin/{e.get('head_branch') or '?'} "
                      f"(limit {MAX_BEHIND}, last-fetched basis)"))

    inst = d.get("installed") or {}
    for key, label in (("runner_agent", "runner-agent"),
                       ("devin_dispatch", "devin-dispatch")):
        e = inst.get(key) or {}
        if not e.get("exists"):
            v.append((label, f"~/.local/bin/{label} missing — host "
                             f"can't {'claim cards' if key == 'runner_agent' else 'start dispatch sessions'}"))
            continue
        if not e.get("exec"):
            v.append((label, f"~/.local/bin/{label} not executable"))
        if e.get("syntax_ok") is False:
            v.append((label, f"~/.local/bin/{label} fails syntax check: "
                             f"{e.get('syntax_err', '')}"))
        elif refsha.get(key) and e.get("sha") and \
                e["sha"] != refsha[key]:
            v.append((label, f"~/.local/bin/{label} sha {e['sha']} != "
                             f"repo {refsha[key]} — installed copy "
                             f"drifted; redeploy"))

    dr = d.get("dispatch_repos") or {}
    if not dr.get("resolved_dir"):
        v.append(("dispatch-repos",
                  "no dispatch_repos.py resolvable — runner-agent "
                  "close-out would crash (dr_module() finds nothing)"))
    elif not dr.get("import_ok"):
        v.append(("dispatch-repos",
                  f"dispatch_repos import fails: "
                  f"{dr.get('import_err', '?')}"))
    elif dr.get("missing"):
        v.append(("dispatch-repos",
                  f"dispatch_repos at {dr['path']} lacks "
                  f"{', '.join(dr['missing'])} — the idc01 "
                  f"crash-loop"))
    elif refsha.get("dispatch_repos") and dr.get("sha") and \
            dr["sha"] != refsha["dispatch_repos"]:
        notes.append(f"dispatch_repos copy differs from repo "
                     f"(sha {dr['sha']} vs {refsha['dispatch_repos']}) "
                     f"— functional attrs present")

    devin = d.get("devin") or {}
    if not devin.get("path"):
        v.append(("devin-cli", "no devin binary resolvable (PATH, "
                               "~/.local/bin, bundled) — dispatch cards "
                               "can't start"))
    elif devin["path"].startswith("/usr/share/devin-desktop"):
        notes.append(f"devin resolves only to the bundled desktop copy "
                     f"({devin.get('version') or 'version unknown'}) — "
                     f"devin-dispatch.sh warns this may be stale")
    else:
        notes.append(f"devin: {devin['path']}"
                     + (f" ({devin['version']})"
                        if devin.get("version") else ""))
    return v, notes


# ------------------------------------------------------------ cards
def card_path(host: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in host)
    return CARDS / f"runner-auto-{safe}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def upsert_card(path: Path, host: str, violations: list,
                notes: list, now: float, today: str) -> str:
    card = load_card(path)
    opened = card.get("updated") if card.get("column") == "review" \
        else today
    try:
        age_h = (now - time.mktime(
            time.strptime(str(opened), "%Y-%m-%d"))) / 3600
    except (ValueError, TypeError):
        age_h = 0
    fails = "; ".join(detail for _, detail in violations)
    help_lines = [f"- {k}: {HELP[k]}" for k, _ in violations]
    note = f"Failing: {fails}."
    if notes:
        note += " Info: " + "; ".join(notes) + "."
    card.update({
        "id": f"runner-auto-{host}",
        "title": f"Runner host `{host}` fails {len(violations)} "
                 f"dispatch bootstrap check(s)",
        "brief": (f"Automated fleet audit found provisioning gaps on "
                  f"{host} that will strand dispatch cards. Read the "
                  f"note, fix on the host, close the card."),
        "column": "review",
        "review_kind": "triage",
        "generated": "runner-fleet-health",
        "program": "chaba-ci",
        "area": "dispatch",
        "priority": "high" if age_h >= ESCALATE_H else "medium",
        "note": note[:900],
        "help": "Per-check fixes:\n" + "\n".join(help_lines),
        "updated": opened,
    })
    if path.exists() and card == load_card(path):
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return "updated"


def close_card(path: Path, host: str, today: str, why: str) -> bool:
    card = load_card(path)
    if card.get("column") != "review" or \
            card.get("generated") != "runner-fleet-health":
        return False
    card["column"] = "done"
    card["note"] = f"Auto-recovered {today}: {why}."
    card["updated"] = today
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return True


def main() -> int:
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    refsha = {k: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
              if p.exists() else None for k, p in REFS.items()}
    hosts = fleet()
    n_bad = n_ok = n_close = 0
    for host in hosts:
        d = probe(host)
        try:
            violations, notes = judge(host, d or {"_error": "no probe"},
                                      refsha)
        except Exception as e:
            violations, notes = [("unreachable",
                                  f"judge crashed: {type(e).__name__}: "
                                  f"{e}")], []
        path = card_path(host)
        if violations:
            n_bad += 1
            rc = upsert_card(path, host, violations, notes, now, today)
            for k, detail in violations:
                print(f"FAIL {host}/{k}: {detail}", file=sys.stderr)
        else:
            n_ok += 1
            if path.exists() and close_card(
                    path, host, today, "all bootstrap checks pass"):
                n_close += 1
    # retired fleet hosts never get probed — close their stale cards.
    for path in CARDS.glob("runner-auto-*.yml"):
        host = path.stem.removeprefix("runner-auto-")
        if host not in hosts and close_card(
                path, host, today, "host left the dispatch fleet"):
            n_close += 1
    print(f"runner-fleet-health: {n_bad} hosts failing, {n_ok} ok, "
          f"{n_close} cards auto-closed ({len(hosts)} hosts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
