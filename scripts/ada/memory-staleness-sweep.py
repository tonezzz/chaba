#!/usr/bin/env python3
"""Weekly staleness sweep — re-verifies aging memory-bank docs via the
iPhone approve/deny flow (knowledge-circle step 4; runbook:
request_iphone_confirmation in ssot.home-assistant.howto.yml).

sweep (default): find the stalest doc across Tony-visible writable banks
(status=active, last_verified older than --max-age days, sorted by
use_count desc then age), then ask ONE question per run —
input_text.devin_confirmation + persistent_notification +
notify.mobile_app_tony_ip with APPROVE_<tag> / DENY_<tag> actions.
One pending question at a time: the helper is single-slot, shared with
the devin confirmation flow.

--apply: read input_text.devin_confirmation; if it carries a verdict for
a pending stale-* tag, apply it — APPROVE bumps last_verified=today,
DENY retracts the doc (auditable, recallable via include_inactive) —
then reset the helper to idle and emit a chaba-event.

Suggested timers: sweep weekly, --apply daily (consumes answers).

Usage:
  memory-staleness-sweep.py             # ask about the stalest doc
  memory-staleness-sweep.py --apply     # consume a pending iPhone verdict
  memory-staleness-sweep.py --dry-run   # report only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
MDDB_BASE_URL = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
STATE = Path.home() / ".cache/ada-memory-staleness.json"

# iPhone confirmations go to Tony's phone — only sweep banks Tony can see
# (shared banks + tony-scoped; michael-personal docs never push here).
SWEEP_INSTANCE = "tony"
MAX_AGE_DAYS = 90
REASK_DAYS = 30
HELPER = "input_text.devin_confirmation"
NOTIFY_SERVICE = "mobile_app_tony_ip"
HA_HOST = "tony-dell"
HA_URL = "http://127.0.0.1:8123"
TAG_PREFIX = "stale-"
VERDICT_RE = re.compile(r"^(\w+) \[([^\]]+)\]")

EVENT_CMD = [
    "ssh", HA_HOST,
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py",
    "add", "-",
]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def _post(path: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(
        f"{MDDB_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST" if path != "/update" else "PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        if exc.code == 400 and "not found" in body.lower():
            return "missing"
        print(f"  {path} failed: HTTP {exc.code} {body}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  {path} failed: {exc}", file=sys.stderr)
        return None


def ha_call(path: str, payload: dict | None = None, timeout: int = 30):
    """HA REST on tony-ha via ssh tony-dell (HA binds loopback there).
    Token: home-assistant-token.env HA_LONG_LIVED_TOKEN, else nodered-ha.env."""
    pre = (
        "set -a; . ~/.config/secrets/home-assistant-token.env 2>/dev/null; "
        ". ~/.config/secrets/nodered-ha.env 2>/dev/null; "
        'TOKEN="${HA_LONG_LIVED_TOKEN:-$HASS_TOKEN}"; '
    )
    if payload is None:
        cmd = (f'curl -sf -H "Authorization: Bearer $TOKEN" {HA_URL}{path}')
    else:
        b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        cmd = (
            f'curl -sf -X POST -H "Authorization: Bearer $TOKEN" '
            f'-H "Content-Type: application/json" '
            f'-d "$(echo {b64} | base64 -d)" {HA_URL}{path}'
        )
    r = subprocess.run(["ssh", HA_HOST, pre + cmd],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print(f"  ha_call {path} failed: {r.stderr.strip()[:200]}",
              file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        return r.stdout


def helper_state() -> str:
    st = ha_call(f"/api/states/{HELPER}")
    return str(st.get("state") or "") if isinstance(st, dict) else ""


def emit_event(title: str, body: str, requires_response: bool = False) -> None:
    payload = json.dumps({
        "title": title, "category": "ada-memory",
        "source": "memory-staleness-sweep", "severity": "warn",
        "body": body, "requires_response": requires_response,
        "confidence": 0.8,
    })
    try:
        r = subprocess.run(EVENT_CMD, input=payload, capture_output=True,
                           text=True, timeout=30)
        print(f"event: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    except Exception as exc:
        print(f"event emit failed: {exc}")


def load_banks() -> dict[str, dict]:
    data = yaml.safe_load(SSOT.read_text())
    return data.get("banks") or {}


def _meta_first(meta: dict, key: str) -> str | None:
    v = meta.get(key)
    if isinstance(v, list):
        return str(v[0]) if v and v[0] else None
    return str(v) if v else None


def find_stale_docs(max_age_days: int, min_uses: int) -> list[dict]:
    """Stale = status active + last_verified older than the cutoff."""
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    out = []
    for name, spec in load_banks().items():
        if not spec.get("writable") or SWEEP_INSTANCE not in (spec.get("instances") or []):
            continue
        collection = str(spec.get("mddb_collection") or "").replace(
            "{instance}", SWEEP_INSTANCE)
        docs = _post("/search", {
            "collection": collection,
            "filterMeta": {"status": ["active"]},
            "limit": 200,
        })
        for d in docs or []:
            if not isinstance(d, dict):
                continue
            meta = d.get("meta") or {}
            verified = _meta_first(meta, "last_verified")
            if not verified or verified >= cutoff:
                continue
            try:
                uses = int(_meta_first(meta, "use_count") or 0)
            except ValueError:
                uses = 0
            if uses < min_uses:
                continue
            out.append({
                "bank": name, "collection": collection,
                "key": d.get("key"), "last_verified": verified,
                "use_count": uses,
                "snippet": str(d.get("contentMd") or "")[:140].split("\n")[0],
            })
    # Most-used first, then oldest — the load-bearing stale facts matter most.
    out.sort(key=lambda d: (-d["use_count"], d["last_verified"]))
    return out


def tag_for(collection: str, key: str) -> str:
    import hashlib
    return TAG_PREFIX + hashlib.sha1(f"{collection}:{key}".encode()).hexdigest()[:8]


def ask_iphone(doc: dict, tag: str, dry: bool) -> bool:
    question = f'Still true? "{doc["snippet"]}" [{tag}]'
    if len(question) > 240:
        question = question[:237] + "…"
    print(f"  ask {doc['collection']}:{doc['key']} — {question}")
    if dry:
        return True
    ok = ha_call("/api/services/input_text/set_value", {
        "entity_id": HELPER, "value": f"awaiting: {question}",
    })
    if ok is None:
        return False
    ha_call("/api/services/persistent_notification/create", {
        "notification_id": tag,
        "title": "Ada memory check",
        "message": f"{question}\n\nBank: {doc['bank']} · key: {doc['key']} · "
                   f"last verified {doc['last_verified']}",
    })
    ok = ha_call(f"/api/services/notify/{NOTIFY_SERVICE}", {
        "title": "Ada memory check",
        "message": question,
        "data": {"actions": [
            {"action": f"APPROVE_{tag}", "title": "Still true"},
            {"action": f"DENY_{tag}", "title": "Changed"},
        ]},
    })
    return ok is not None


def apply_pending(state: dict, dry: bool) -> int:
    pending = state.get("pending")
    if not pending:
        print("no pending staleness question")
        return 0
    tag = pending["tag"]
    raw = helper_state()
    print(f"helper: {raw!r}")
    m = VERDICT_RE.match(raw.strip())
    if not m or m.group(2) != tag:
        print("no verdict for pending tag yet")
        return 0
    verdict = m.group(1).upper()
    collection, key = pending["collection"], pending["key"]
    today = date.today().isoformat()
    if verdict.startswith("APPROVE"):
        doc = _post("/get", {"collection": collection, "key": key, "lang": "en"})
        if not isinstance(doc, dict):
            print(f"  cannot load {key} — leaving pending")
            return 1
        meta = dict(doc.get("meta") or {})
        meta["last_verified"] = [today]
        if not dry:
            _post("/update", {"collection": collection, "key": key,
                              "lang": "en", "meta": meta})
        print(f"  APPROVED {key} — last_verified={today}")
        emit_event("Ada memory re-verified",
                   f"{key} confirmed still true via iPhone.", False)
    elif verdict.startswith("DENY"):
        doc = _post("/get", {"collection": collection, "key": key, "lang": "en"})
        if not isinstance(doc, dict):
            print(f"  cannot load {key} — leaving pending")
            return 1
        meta = dict(doc.get("meta") or {})
        meta["status"] = ["retracted"]
        meta["retracted_reason"] = ["denied via iPhone staleness check"]
        meta["last_verified"] = [today]
        if not dry:
            _post("/update", {"collection": collection, "key": key,
                              "lang": "en", "meta": meta})
        print(f"  DENIED {key} — retracted")
        emit_event("Ada memory retracted via iPhone",
                   f"{key} denied in the staleness check and was retracted. "
                   "If it was wrong, add the corrected fact via vault or "
                   "'remember that…'.", True)
    else:
        print(f"  unrecognized verdict {verdict!r}")
        return 1
    if not dry:
        ha_call("/api/services/input_text/set_value",
                {"entity_id": HELPER, "value": "idle"})
        ha_call("/api/services/persistent_notification/dismiss",
                {"notification_id": tag})
        state.pop("pending", None)
        save_state(state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="consume a pending iPhone verdict")
    ap.add_argument("--max-age", type=int, default=MAX_AGE_DAYS,
                    help="last_verified older than this many days is stale")
    ap.add_argument("--min-uses", type=int, default=0,
                    help="only ask about docs surfaced at least this often")
    ap.add_argument("--reask-days", type=int, default=REASK_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    state = load_state()
    if args.apply:
        return apply_pending(state, args.dry_run)

    # One question at a time — the helper is single-slot and shared.
    if state.get("pending"):
        raw = helper_state()
        if raw.strip().startswith("awaiting"):
            print(f"still awaiting verdict for {state['pending']['tag']}")
            return 0
        print("pending tag but helper not awaiting — clearing")
        state.pop("pending", None)

    asked = state.setdefault("asked", {})
    reask_cutoff = (date.today() - timedelta(days=args.reask_days)).isoformat()
    stale = [d for d in find_stale_docs(args.max_age, args.min_uses)
             if asked.get(f"{d['collection']}:{d['key']}", "0000") < reask_cutoff]
    print(f"{len(stale)} stale doc(s) eligible")
    if not stale:
        save_state(state)
        return 0
    doc = stale[0]
    tag = tag_for(doc["collection"], doc["key"])
    if not ask_iphone(doc, tag, args.dry_run):
        return 1
    if not args.dry_run:
        state["pending"] = {"tag": tag, "collection": doc["collection"],
                            "key": doc["key"], "bank": doc["bank"],
                            "asked_at": date.today().isoformat()}
        asked[f"{doc['collection']}:{doc['key']}"] = date.today().isoformat()
        save_state(state)
        emit_event(
            "Ada memory staleness check sent",
            f"Asked whether {doc['collection']}:{doc['key']} is still true "
            f"(last verified {doc['last_verified']}, used {doc['use_count']}x).",
            False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
