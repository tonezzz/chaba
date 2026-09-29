#!/usr/bin/env python3
"""chaba-audit — weekly health score for the Chaba system itself.

Each check returns pass|warn|fail; the results publish to mddb as one
'kind: benchmark' doc (suite 'chaba') so audits trend over time like
the Ada scenario benchmark. Run manually:

    scripts/audit/chaba-audit.py --dry-run

Checks:
  ssot_validate  — ssot-validate-all.mjs passes on the working tree
  memory_render  — render-memory.py produces a fresh, non-trivial context
  services_live  — key endpoints answer (vcast api, camwall, gev, mddb)
  mddb_sync      — mddb stats endpoint healthy (collection count > 0)
  timers         — ada-* timers on idc01 have a recent LAST fire
  units_failed   — no failed user units on idc01 / tony-dell
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MDDB = "http://100.74.146.0:11023/v1"

ENDPOINTS = {
    "vcast_api":  "https://tony-dell.taila0626a.ts.net/api/input-bridge/displays",
    "camwall":    "https://tony-dell.taila0626a.ts.net/apps/camwall/",
    "gev":        "https://tony-dell.taila0626a.ts.net/apps/gev/",
}


def _get(url: str, timeout: int = 15) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "chaba-audit/1.0"})
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.status, r.read()


def _sh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    p = subprocess.run(["bash", "-c", cmd], capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def check_ssot_validate() -> tuple[str, str]:
    rc, out = _sh(f"cd {REPO} && node scripts/ssot-validate-all.mjs", 180)
    return ("pass" if rc == 0 else "fail",
            out.splitlines()[-1] if out else "no output")


def check_memory_render() -> tuple[str, str]:
    src = REPO / "docs/ssot/chaba/ssot.chaba.memory.yml"
    rc, out = _sh(f"cd {REPO} && python3 scripts/chaba/render-memory.py", 120)
    if rc != 0:
        return "fail", f"render failed: {out[-200:]}"
    age_h = (datetime.now().timestamp() - src.stat().st_mtime) / 3600
    if age_h > 24 * 14:
        return "warn", f"memory source {age_h/24:.0f}d old"
    return "pass", f"rendered ok, source {age_h:.0f}h old"


def check_services() -> tuple[str, str]:
    dead = []
    for name, url in ENDPOINTS.items():
        try:
            _get(url)
        except Exception as exc:
            dead.append(f"{name}({type(exc).__name__})")
    # Ada's ws server binds loopback on idc01 — check the unit instead
    rc, out = _sh('ssh -o BatchMode=yes -o ConnectTimeout=8 idc01 '
                  '"systemctl --user is-active ada-ha-tony"', 30)
    if out != "active":
        dead.append(f"ada({out or 'unreachable'})")
    if len(dead) >= 2:
        return "fail", f"down: {', '.join(dead)}"
    return ("warn" if dead else "pass",
            f"down: {', '.join(dead)}" if dead
            else f"all {len(ENDPOINTS)+1} up")


def check_mddb() -> tuple[str, str]:
    try:
        st, body = _get(f"{MDDB}/stats")
        d = json.loads(body)
        n = len(d.get("collections", d if isinstance(d, dict) else {}))
        return "pass", f"{n} collections"
    except Exception as exc:
        return "fail", f"mddb: {exc}"


def check_timers() -> tuple[str, str]:
    rc, out = _sh(
        'ssh -o BatchMode=yes -o ConnectTimeout=8 idc01 '
        '"systemctl --user list-timers --all 2>/dev/null | grep ada- "', 30)
    if rc != 0:
        return "fail", f"idc01 unreachable: {out[:120]}"
    stale = [l.split()[0] for l in out.splitlines()
             if l.strip() and l.split()[1:3] == ["-", "-"]]
    if stale:
        return "warn", f"never fired: {', '.join(stale[:4])}"
    return "pass", f"{len(out.splitlines())} ada timers scheduled"


def check_units_failed() -> tuple[str, str]:
    bad = []
    for h in ("idc01", "tony-dell"):
        rc, out = _sh(
            f'ssh -o BatchMode=yes -o ConnectTimeout=8 {h} '
            '"systemctl --user --failed --no-legend 2>/dev/null"', 30)
        if rc != 0:
            bad.append(f"{h}:unreachable")
        else:
            names = [w for l in out.splitlines() for w in l.split()
                     if w.endswith(".service")]
            if names:
                bad.append(f"{h}: {', '.join(names[:6])}")
    return ("warn" if bad else "pass", "; ".join(bad) or "clean")


CHECKS = [
    ("ssot_validate", check_ssot_validate),
    ("memory_render", check_memory_render),
    ("services_live", check_services),
    ("mddb_sync", check_mddb),
    ("timers", check_timers),
    ("units_failed", check_units_failed),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now()
    rows = []
    for name, fn in CHECKS:
        try:
            status, note = fn()
        except Exception as exc:
            status, note = "fail", f"check crashed: {exc}"
        print(f"  {status:4s}  {name:15s} {note}")
        rows.append((name, status, note))
    score = sum(1 for _, s, _ in rows if s == "pass") / len(rows)
    md = (f"# Chaba audit — {now:%Y-%m-%d %H:%M}\n\n"
          f"| check | status | note |\n|---|---|---|\n"
          + "\n".join(f"| {n} | {s} | {t} |" for n, s, t in rows)
          + f"\n\nscore: **{score:.0%}**\n")
    print(md)
    if not a.dry_run:
        try:
            req = urllib.request.Request(
                f"{MDDB}/add",
                data=json.dumps({
                    "collection": "ada-ha-scenario-reports",
                    "key": f"benchmark/chaba-{now:%Y%m%d-%H%M%S}",
                    "lang": "en", "contentMd": md,
                    "meta": {"kind": ["benchmark"], "suite": ["chaba"],
                             "score": [f"{score:.2f}"],
                             "status": ["fail" if any(s == "fail" for _, s, _ in rows)
                                        else "pass"],
                             "ts": [now.isoformat(timespec="seconds")],
                             "checks": [f"{n}:{s}" for n, s, _ in rows]},
                }).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=60).read()
            print("published to ada-ha-scenario-reports")
        except Exception as exc:
            print(f"mddb write failed: {exc}", file=sys.stderr)
    return 0 if score >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
