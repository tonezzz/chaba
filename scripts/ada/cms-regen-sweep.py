#!/usr/bin/env python3
"""cms-regen-sweep.py — the missing runner for registry command-generators.

Registry docs in ada-cms-automation can declare
    generator: {kind: command, cmd: scripts/ada/foo.py, cwd: chaba,
                cost: {timeout_s: N}}
but until now nothing executed them on a schedule — pages like
health-digest declared a generator and still went days stale
(card stale-report-regen-lane, surfaced by standard-drift-digest.py).

Runs each due command-generator. Gating lives in the registry doc:
  enabled: false          -> skip
  run_now: true           -> run once, clear the flag (Regenerate button)
  interval_min + last_run -> due when elapsed >= interval
Safety: cmd must be a repo script under scripts/ (.py or .sh), args are
split on whitespace and must be plain tokens (no shell) — registry docs
are MDDB-writable, so treat cmd as untrusted input.

Writes back last_run / last_status / last_duration_s / last_count.

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
    REPO            default = this checkout root

Usage:
    cms-regen-sweep.py              # run due generators
    cms-regen-sweep.py --dry-run    # show what's due, run nothing
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
REGISTRY = "ada-cms-automation"
# cmd allowlist: a repo-relative script under scripts/ + plain-token args
CMD_RE = re.compile(r"^scripts/[a-zA-Z0-9_./-]+\.(py|sh)$")
ARG_RE = re.compile(r"^[a-zA-Z0-9_.,:/=+-]+$")


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}/{path.lstrip('/')}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "{}")


def _search_all(collection, page_size=500):
    docs, offset = [], 0
    while True:
        page = _post("search", {"collection": collection, "query": "",
                                "limit": page_size, "offset": offset})
        batch = page if isinstance(page, list) else page.get("results", [])
        docs += batch
        if len(batch) < page_size:
            return docs
        offset += page_size


def _due(cfg: dict, now: datetime) -> str | None:
    if cfg.get("enabled") is False:
        return "disabled"
    if cfg.get("run_now"):
        return None  # due now — Regenerate button
    last = cfg.get("last_run")
    interval = int(cfg.get("interval_min") or 0)
    if interval <= 0:
        return "manual (interval_min=0)"  # on-demand only — never auto-run
    if not last:
        return None  # never ran -> run once to seed
    try:
        last_dt = datetime.fromisoformat(str(last))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if now >= last_dt + timedelta(minutes=interval):
        return None
    return f"next at {last_dt + timedelta(minutes=interval):%H:%MZ}"


def _validate_cmd(gen: dict) -> list[str] | None:
    cmd = str(gen.get("cmd") or "").strip()
    if not cmd:
        name = str(gen.get("name") or "").strip()
        if name:
            cmd = f"scripts/ada/{name}.py"
        else:
            return None
    parts = shlex.split(cmd)
    if not parts or not CMD_RE.match(parts[0]):
        return None
    if any(not ARG_RE.match(a) for a in parts[1:]):
        return None
    script = (REPO / parts[0]).resolve()
    if not str(script).startswith(str(REPO.resolve()) + "/scripts/"):
        return None
    if not script.exists():
        return None
    return ["/usr/bin/python3", str(script), *parts[1:]]


def run_one(key: str, gen: dict, now: datetime) -> dict:
    argv = _validate_cmd(gen)
    if argv is None:
        return {"status": "rejected", "error":
                f"cmd {gen.get('cmd')!r} not on the scripts/ allowlist"}
    timeout = int((gen.get("cost") or {}).get("timeout_s") or 300)
    t0 = time.time()
    try:
        proc = subprocess.run(argv, cwd=REPO, capture_output=True,
                              text=True, timeout=timeout)
        return {"status": "ok" if proc.returncode == 0 else "error",
                "rc": proc.returncode,
                "tail": (proc.stdout + proc.stderr)[-400:],
                "duration_s": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f">{timeout}s",
                "duration_s": timeout}


def write_back(key: str, cfg: dict, res: dict, now: datetime) -> None:
    doc = _post("/get", {"collection": REGISTRY, "key": key,
                         "lang": "en"})
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta["updated"] = [now.isoformat(timespec="seconds")]
    meta["last_verified"] = [now.date().isoformat()]
    cfg.update({"last_run": now.isoformat(timespec="seconds"),
                "last_status": res["status"],
                "last_duration_s": res.get("duration_s", 0.0),
                "run_now": False})
    _post("/add", {"collection": REGISTRY, "key": key, "lang": "en",
                   "contentMd": json.dumps(cfg, ensure_ascii=False,
                                           indent=2),
                   "meta": meta}, timeout=120)


def main():
    now = datetime.now(timezone.utc)
    dry = "--dry-run" in sys.argv
    ran = skipped = failed = 0
    for d in _search_all(REGISTRY):
        try:
            cfg = json.loads(d.get("contentMd") or "{}")
        except json.JSONDecodeError:
            continue
        gen = cfg.get("generator") or {}
        if gen.get("kind") != "command":
            continue
        key = d.get("key") or "?"
        reason = _due(cfg, now)
        if reason:
            skipped += 1
            continue
        if dry:
            print(f"due: {key} — {gen.get('cmd')}")
            continue
        res = run_one(key, gen, now)
        try:
            write_back(key, cfg, res, now)
        except Exception as exc:
            print(f"warn: {key} write-back failed: {exc}",
                  file=sys.stderr)
        ran += 1
        if res["status"] != "ok":
            failed += 1
            print(f"FAIL {key}: {res.get('error') or res.get('tail')}",
                  file=sys.stderr)
    print(f"cms-regen-sweep: {ran} ran ({failed} failed), "
          f"{skipped} not due")
    return 0


if __name__ == "__main__":
    sys.exit(main())
