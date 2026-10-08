#!/usr/bin/env python3
"""claw-publish — write a sanitized board digest into the claw-channel
KV namespace (lab card lab-cf-kv-claw-channel).

Reads the kanban board (cards.json file or board-api /cards), strips
everything except id/title/column — no hosts, no paths, no secrets, no
card bodies — and writes KV key `digest:board`.

Two write paths:
  default      Cloudflare API (needs CF_API_TOKEN + CF_API_ACCOUNT_ID
               with Workers KV Storage edit; env file default
               ~/.config/secrets/cloudflare.env)
  --via-ingest POST to the worker's /claw/digest/board with
               X-Ingest-Key (env file ~/.config/secrets/claw-channel.env
               holding CLAW_INGEST_KEY) — for hosts without CF creds.

Usage:
  claw-publish.py [--source URL_OR_PATH] [--dry-run]
  claw-publish.py --via-ingest https://claw.surf-thailand.com
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = "http://127.0.0.1:8787/cards"  # board-api (prefix-stripped)
REPO_CARDS = (
    REPO / "stacks/web/public/apps/board/cards.json"  # render-board.py output
)
VALUES_YML = REPO / "docs/ssot/infrastructure/ssot.values.yml"
CF_ENV = Path.home() / ".config/secrets/cloudflare.env"
INGEST_ENV = Path.home() / ".config/secrets/claw-channel.env"
CF_API = "https://api.cloudflare.com/client/v4"
KV_NAMESPACE = "claw-channel"
DIGEST_KEY = "digest:board"


def load_env_file(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# Host tokens that must never leak into the public digest, even when a
# card title names them. Union of ssot.values.yml hosts: + static extras.
STATIC_HOSTS = {
    "idc01", "idc02", "idc03", "mn01", "kk-macbook",
    "tony-dell", "tony-omen", "tony-ha", "tony-dev", "michael-ha", "michael-dev",
    "ada-pi", "homeassistant",
}
IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
DOMAIN_RE = re.compile(r"\b[\w.-]+\.(?:ts\.net|local|lan)\b")
PATH_RE = re.compile(r"(?:/[\w.@+-]+){2,}|~[\w/-]+")


def host_tokens() -> list:
    hosts = set(STATIC_HOSTS)
    try:
        import yaml
        v = yaml.safe_load(VALUES_YML.read_text()) or {}
        for key, h in (v.get("hosts") or {}).items():
            hosts.add(str(key).replace("_", "-"))
            if isinstance(h, dict) and h.get("name"):
                hosts.add(str(h["name"]))
    except Exception:
        pass
    return sorted(hosts, key=len, reverse=True)


def scrub(text: str, hosts: list) -> str:
    """Redact hosts / IPs / paths from a title bound for the public KV."""
    if not text:
        return text
    for h in hosts:
        # \w boundaries only: hyphenated compounds (services-michael-ha)
        # still leak a host — scrub inside them too.
        text = re.sub(rf"(?<!\w){re.escape(h)}(?!\w)", "[host]", text)
    text = DOMAIN_RE.sub("[host]", text)
    text = IPV4_RE.sub("[ip]", text)
    return PATH_RE.sub("[path]", text)


def load_cards(source: str) -> dict:
    """Return the cards.json payload from a URL or a local file."""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=10) as r:
            return json.loads(r.read())
    return json.loads(Path(source).read_text())


def build_digest(payload: dict) -> dict:
    """Keep only id/title/column, scrubbed — digest is publicly readable.

    ids stay verbatim: they are the join key a claw uses to reference a
    card, and scrubbing them collides (logs-auto-idc01-* / -idc02-*).
    Host tokens inside id slugs are an accepted lab-scope leak; titles,
    which carry real prose, are scrubbed of hosts/IPs/paths."""
    hosts = host_tokens()
    cards = [
        {"id": c.get("id"), "title": scrub(c.get("title"), hosts),
         "column": c.get("column")}
        for c in payload.get("cards", [])
        if c.get("id")
    ]
    counts = {}
    for c in cards:
        counts[c["column"] or "?"] = counts.get(c["column"] or "?", 0) + 1
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "cards": sorted(cards, key=lambda c: (c["column"] or "", c["id"])),
    }


def cf_request(env: dict, method: str, path: str, body: bytes = None,
               content_type: str = "application/json") -> dict:
    req = urllib.request.Request(
        f"{CF_API}{path}", method=method, data=body,
        headers={"Authorization": f"Bearer {env['CF_API_TOKEN']}",
                 "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def publish_cf_api(env: dict, digest: bytes) -> str:
    acct = env["CF_API_ACCOUNT_ID"]
    ns = cf_request(env, "GET", f"/accounts/{acct}/storage/kv/namespaces")
    if not ns.get("success"):
        sys.exit(f"KV namespace list failed: {ns.get('errors')}")
    ns_id = next((n["id"] for n in ns["result"]
                  if n["title"] == KV_NAMESPACE), None)
    if not ns_id:
        sys.exit(f"KV namespace {KV_NAMESPACE!r} not found — run "
                 "stacks/edge/claw-channel/deploy.sh first")
    res = cf_request(
        env, "PUT",
        f"/accounts/{acct}/storage/kv/namespaces/{ns_id}"
        f"/values/{DIGEST_KEY}",
        body=digest, content_type="application/json")
    if not res.get("success"):
        sys.exit(f"KV put failed: {res.get('errors')}")
    return f"kv:{KV_NAMESPACE}/{DIGEST_KEY}"


def publish_ingest(env: dict, base_url: str, digest: bytes) -> str:
    url = f"{base_url.rstrip('/')}/digest/board"
    req = urllib.request.Request(
        url, method="POST", data=digest,
        headers={"X-Ingest-Key": env["CLAW_INGEST_KEY"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            sys.exit(f"ingest POST failed: HTTP {r.status}")
    return url


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    via_ingest = None
    source = DEFAULT_SOURCE
    i = 0
    while i < len(args):
        if args[i] == "--via-ingest":
            via_ingest = args[i + 1]
            i += 1
        elif args[i] == "--source":
            source = args[i + 1]
            i += 1
        i += 1

    try:
        payload = load_cards(source)
    except Exception as e:
        if source == DEFAULT_SOURCE and REPO_CARDS.exists():
            payload = load_cards(str(REPO_CARDS))
        else:
            sys.exit(f"cannot read board ({source}): {e}")

    digest = build_digest(payload)
    blob = json.dumps(digest, ensure_ascii=False).encode()
    if dry:
        print(blob.decode())
        print(f"-- {len(digest['cards'])} cards, {len(blob)} bytes "
              f"(dry run)", file=sys.stderr)
        return 0

    if via_ingest:
        env = {**load_env_file(INGEST_ENV), **os.environ}
        if not env.get("CLAW_INGEST_KEY"):
            sys.exit("CLAW_INGEST_KEY missing — set env or "
                     f"{INGEST_ENV}")
        where = publish_ingest(env, via_ingest, blob)
    else:
        env = {**load_env_file(CF_ENV), **os.environ}
        if not env.get("CF_API_TOKEN") or not env.get("CF_API_ACCOUNT_ID"):
            sys.exit("CF_API_TOKEN/CF_API_ACCOUNT_ID missing — set env "
                     f"or {CF_ENV}")
        where = publish_cf_api(env, blob)

    print(f"published digest:board ({len(digest['cards'])} cards, "
          f"{len(blob)} bytes) -> {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
