#!/usr/bin/env python3
"""Derive Yomi conversation display names from message fromName data."""
import json
import re
import time
import urllib.request
import urllib.error

API_BASE = "http://tony-dell:3000/api/yomi"
NAMES_FILE = "/home/tony/CascadeProjects/chaba-yomi/stacks/web/public/apps/yomi/conversations-names.json"

ID_RE = re.compile(r"^[uc][0-9a-f]{32}$")


def api_call(path):
    url = f"{API_BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"WARN: failed {url}: {e}")
        return {}


def derive_name(conv, messages):
    candidates = []
    for m in messages:
        name = m.get("fromName")
        if name and name != "Unknown":
            candidates.append(name)
    if not candidates:
        return None
    if conv.get("isGroup"):
        # For groups, use the first sender name as a placeholder; real group names need LINE.
        return candidates[0]
    # For 1-on-1, the first non-null fromName is the contact.
    return candidates[0]


def main():
    data = api_call("/conversations")
    conversations = data.get("conversations", [])
    names = {}
    for conv in conversations:
        conv_id = conv.get("id")
        current = conv.get("name", "")
        if not ID_RE.match(current):
            continue
        msg_data = api_call(f"/messages?chat={conv_id}&limit=20")
        messages = msg_data.get("messages", [])
        derived = derive_name(conv, messages)
        if derived:
            names[conv_id] = derived
            print(f"{conv_id} -> {derived}")
        else:
            print(f"{conv_id} -> (no fromName)")
        time.sleep(0.05)

    with open(NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(names)} names to {NAMES_FILE}")


if __name__ == "__main__":
    main()
