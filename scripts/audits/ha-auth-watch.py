#!/usr/bin/env python3
"""Watch HA instances for invalid-authentication attempts.

Deleted/revoked long-lived tokens can't be restored (HA stores only the
hash). The recovery path is: mint a new token, update whatever used the
old one — which requires knowing who the consumer is. HA logs
"Login attempt or request with invalid authentication from <ip>"; this
polls /api/error_log per instance, writes one focus-inbox alert per NEW
failure source (deduped via state file + unresolved-alert check, same
pattern as gh-runs-watch), and emits an L1 meta.yml + timeline event.

Instances are defined inline; token paths stay out of the alert body —
only source IP/client and instance name are recorded.
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import websockets
except ImportError:
    websockets = None

REPO_ROOT = Path(__file__).resolve().parents[2]
INBOX_DIR = REPO_ROOT / "docs" / "ssot" / "focus-inbox"
STATE_FILE = Path(os.environ.get(
    "HA_AUTH_WATCH_STATE",
    Path.home() / ".local" / "state" / "chaba" / "ha-auth-watch.json"))
REPORTS_DIR = REPO_ROOT / "reports" / "ha-auth"
TIMELINE = Path(os.environ.get(
    "CHABA_REPORTS_DIR", Path.home() / "var" / "chaba" / "reports")) / "timeline.jsonl"

# (name, base_url, token_file_or_env_file)
INSTANCES = [
    ("michael-ha", "http://michael-ha:8123",
     Path.home() / ".local/share/home-assistant-michael/ha-token"),
    ("tony-ha", "https://tony-dell.taila0626a.ts.net:8123",
     Path.home() / ".config/secrets/home-assistant-token.env"),
]

FAIL_RE = re.compile(
    r"invalid authentication from (?P<src>\S+?)(?:\s+\(\S+\))?\.\s"
    r"*Requested URL", re.IGNORECASE)


def load_token(path):
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(
            r"\s*(?:export\s+)?"
            r"(?:HASS_TOKEN|HOME_ASSISTANT_TOKEN|HA_LONG_LIVED_TOKEN)=(.+)",
            line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raw = text.strip()
    return raw or None


async def fetch_failures(name, base, token):
    """Return (src_ip, timestamp) pairs for invalid-auth log entries."""
    if websockets is None:
        print("warn: python3-websockets not installed", file=sys.stderr)
        return None
    ws_url = re.sub(r"^http", "ws", base.rstrip("/")) + "/api/websocket"
    try:
        async with websockets.connect(ws_url, open_timeout=15) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            r = json.loads(await ws.recv())
            if r.get("type") != "auth_ok":
                print(f"warn: {name} ws auth failed: {r.get('message')}",
                      file=sys.stderr)
                return None
            await ws.send(json.dumps({"id": 1, "type": "system_log/list"}))
            resp = json.loads(await ws.recv())
    except Exception as e:
        print(f"warn: {name} ws poll failed: {e}", file=sys.stderr)
        return None
    out = []
    for entry in resp.get("result") or []:
        msgs = entry.get("message") or []
        text = " ".join(str(m) for m in msgs)
        m = FAIL_RE.search(text)
        if m:
            when = entry.get("timestamp") or ""
            out.append((m.group("src"), str(when), text[:300]))
    return out


def load_state():
    try:
        return set(json.loads(STATE_FILE.read_text()).get("seen", []))
    except Exception:
        return set()


def save_state(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"seen": sorted(seen)[-500:]}))


def alert_yaml(inst, src, ts, line):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_src = re.sub(r"[^A-Za-z0-9_.-]", "_", src)
    fname = (f"{stamp[:10]}-{stamp[11:19].replace(':', '')}"
             f"-ha-auth-{inst}-{safe_src}.yml")
    body = f"""title: HA auth failure on {inst}
subtitle: "invalid-authentication attempt from {src}"
icon: inbox
focus:
  label: "HA auth failure: {inst} from {src}"
  text: >-
    Home Assistant logged a login/API attempt with invalid
    authentication. instance={inst} source={src}
    log_ts={ts} Detected {stamp} by ha-auth-watch. If this follows a
    revoked or deleted token, mint a replacement long-lived token and
    update the consumer.
  branch: chaba
  priority: medium
  status: draft
  tags: [security, home-assistant, auth]
  safe_to_parallel:
    value: true
    reason: read-only alert; remediation is per-consumer
ownership:
  owner: tony
  locked: false
  lock_reason: ""
source:
  date: {stamp[:10]}
"""
    return fname, body


def existing_alert(inst, src):
    safe_src = re.sub(r"[^A-Za-z0-9_.-]", "_", src)
    for f in INBOX_DIR.glob(f"*ha-auth-{inst}-{safe_src}.yml"):
        try:
            if "status: draft" in f.read_text():
                return f
        except OSError:
            continue
    return None


def emit_meta(now_iso, failures, errors):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    status = "delta" if failures else ("error" if errors else "ok")
    summary = (f"{len(failures)} new invalid-auth source(s)"
               + (f", {errors} poll error(s)" if errors else ""))
    meta = {
        "node": "ha-auth-watch",
        "layer": "L1-producer",
        "purpose": "Surface HA invalid-authentication attempts into the focus inbox",
        "generated_by": "scripts/audits/ha-auth-watch.py",
        "generated_at": now_iso,
        "status": status,
        "summary": summary,
        "sources": [f"{i}/{s}" for i, s, _t, _l in failures],
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
                "ts": now_iso, "node": "ha-auth-watch", "layer": "L1",
                "status": status, "summary": summary,
                "ref": str(REPORTS_DIR / "meta.yml")}) + "\n")
    except OSError as e:
        print(f"warn: timeline emit failed: {e}", file=sys.stderr)


def git_commit_push(files):
    rels = [str(f.relative_to(REPO_ROOT)) for f in files]
    subprocess.run(["git", "-C", str(REPO_ROOT), "add", *rels], check=True)
    subprocess.run(["git", "-C", str(REPO_ROOT), "commit",
                    "-m", "chore(security): ha-auth-watch failure alerts"],
                   check=True)
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
    ap.add_argument("--git", action="store_true",
                    help="commit+push new alert files")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be alerted, write nothing")
    args = ap.parse_args()

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = load_state()
    failures, errors = [], 0
    for name, base, tok_path in INSTANCES:
        token = load_token(tok_path)
        if not token:
            print(f"warn: {name}: no token at {tok_path}", file=sys.stderr)
            errors += 1
            continue
        found = asyncio.run(asyncio.wait_for(
            fetch_failures(name, base, token), timeout=45))
        if found is None:
            errors += 1
            continue
        for src, ts, text in found:
            key = f"{name}|{src}|{ts}"
            if key in seen:
                continue
            seen.add(key)
            failures.append((name, src, ts, text))

    written, suppressed = [], 0
    for inst, src, ts, line in failures:
        if existing_alert(inst, src):
            suppressed += 1
            print(f"DEDUP {inst} {src} — unresolved alert exists")
            continue
        fname, body = alert_yaml(inst, src, ts, line)
        print(f"FAIL {inst} {src} @ {ts} -> {fname}")
        if not args.dry_run:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            f = INBOX_DIR / fname
            f.write_text(body)
            written.append(f)
    print(f"polled {len(INSTANCES)} instance(s): "
          f"{len(failures)} new auth-failure line(s) ({suppressed} deduped), "
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
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
