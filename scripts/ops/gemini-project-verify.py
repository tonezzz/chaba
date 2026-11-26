#!/usr/bin/env python3
"""Read-only Gemini key -> GCP project membership oracle (OPS-0018 step 4).

For each key, call GET /v1beta/models with x-goog-user-project set to a
candidate project. HTTP 200 means the key's owning project may use that
project; 403 means a different existing project; 400 means no such project.
POST :countTokens is used as a second endpoint. Key values are never printed.

Usage:
  python3 scripts/ops/gemini-project-verify.py
  python3 scripts/ops/gemini-project-verify.py --key GEMINI_API_KEY_PAID
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_KEYS_FILE = Path(
    os.environ.get("GEMINI_KEYS_FILE",
                   "~/.config/secrets/gemini-keys.env")).expanduser()
DEFAULT_PROJECTS = [
    "gen-lang-client-0854236591",  # PAID / TONY / KK (verified 2026-11-24)
    "gen-lang-client-0722326417",  # MICHAEL (free tier)
    "gen-lang-client-0694401188",  # archived ops key
    "517766007004",                # archived ops project number
]
BASE = "https://generativelanguage.googleapis.com/v1beta"


def load_keys(path):
    keys = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?(GEMINI_API_KEY_[A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m:
            value = m.group(2).strip().strip('"').strip("'")
            if value:
                keys[m.group(1)] = value
    return keys


def status(url, key, project, body=None):
    headers = {"x-goog-api-key": key, "x-goog-user-project": project}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # network/DNS failure is not a membership signal
        return f"error:{type(exc).__name__}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keys-file", type=Path, default=DEFAULT_KEYS_FILE)
    ap.add_argument("--key", action="append", help="key variable name (repeatable)")
    ap.add_argument("--project", action="append", help="candidate GCP project (repeatable)")
    ap.add_argument("--skip-count-tokens", action="store_true")
    args = ap.parse_args()

    keys = load_keys(args.keys_file)
    if args.key:
        missing = sorted(set(args.key) - set(keys))
        if missing:
            raise SystemExit(f"key variable(s) not in {args.keys_file}: {missing}")
        keys = {k: v for k, v in keys.items() if k in args.key}
    if not keys:
        raise SystemExit(f"no GEMINI_API_KEY_* entries in {args.keys_file}")
    projects = args.project or DEFAULT_PROJECTS

    result = {}
    for name, key in sorted(keys.items()):
        result[name] = {}
        for project in projects:
            codes = {"models": status(f"{BASE}/models", key, project)}
            if not args.skip_count_tokens:
                body = {"contents": [{"parts": [{"text": "ping"}]}]}
                codes["count_tokens"] = status(
                    f"{BASE}/models/gemini-3.5-flash-lite:countTokens",
                    key, project, body)
            result[name][project] = codes
    print(json.dumps({"method": "x-goog-user-project membership (200=member)",
                      "keys_file": str(args.keys_file), "results": result},
                     indent=2))
    print("derived_projects:", json.dumps({
        name: [p for p, c in rows.items() if c["models"] == 200]
        for name, rows in result.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
