#!/usr/bin/env python3
"""Read and sanitize the live Ada HA chaba-admin dashboard snapshot."""

import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SECRET_QUERY_KEYS = {
    "api_key",
    "access_token",
    "token",
    "key",
    "passcode",
    "password",
    "secret",
}
SECRET_FIELD_NAMES = SECRET_QUERY_KEYS | {"authorization"}
DEFAULT_REMOTE_PATH = "/home/tony/.config/ada-ha/.storage/lovelace.chaba_admin"
DEFAULT_OUTPUT = "docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json"


def sanitize_snapshot(value, counts=None):
    """Redact credential fields and URL query values without changing layout."""
    if counts is None:
        counts = {"redacted": 0}

    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_FIELD_NAMES:
                result[key] = "<redacted>"
                counts["redacted"] += 1
            else:
                result[key] = sanitize_snapshot(item, counts)
        return result
    if isinstance(value, list):
        return [sanitize_snapshot(item, counts) for item in value]
    if not isinstance(value, str) or "://" not in value:
        return value

    try:
        parts = urlsplit(value)
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return value
    if not query:
        return value

    sanitized = []
    changed = False
    for key, item in query:
        if key.lower() in SECRET_QUERY_KEYS:
            sanitized.append((key, "<redacted>"))
            counts["redacted"] += 1
            changed = True
        else:
            sanitized.append((key, item))
    if not changed:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sanitized), parts.fragment))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="tony-omen")
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    raw = subprocess.run(
        ["ssh", args.host, "cat", args.remote_path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    snapshot = json.loads(raw)
    counts = {"redacted": 0}
    safe_snapshot = sanitize_snapshot(snapshot, counts)
    output = Path(args.output)
    if not output.parent.is_dir():
        raise SystemExit(f"snapshot directory does not exist: {output.parent}")
    output.write_text(json.dumps(safe_snapshot, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote sanitized snapshot: {output} ({counts['redacted']} values redacted)")


if __name__ == "__main__":
    main()
