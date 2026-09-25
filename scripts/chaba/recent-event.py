#!/usr/bin/env python3
"""recent-event.py — append one event to ~/.local/share/chaba/recent-events.yml.

The hot tier of chaba memory: one line per thing that just happened.
Called by the session-end hook and ad-hoc by agents for notable events.
Rendered into L0 context by render-memory.py source kind `recent-events`;
entries age out via ttl_hours — promote to focus or consolidate to MDDB
before they cool off.
"""
import argparse
import pathlib
import sys
import time

import yaml

STORE = pathlib.Path("~/.local/share/chaba/recent-events.yml").expanduser()
KEEP = 20  # stored cap; render shows fewer (max_entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="one-line event summary")
    ap.add_argument("--text", dest="text_opt")
    ap.add_argument("--ref", help="optional pointer — path, key, or url")
    ap.add_argument("--ttl-hours", type=int, default=72)
    args = ap.parse_args()
    text = args.text_opt or args.text
    if not text:
        ap.error("event text required (positional or --text)")

    doc = {"entries": []}
    if STORE.exists():
        try:
            doc = yaml.safe_load(STORE.read_text()) or {"entries": []}
        except Exception:
            pass
    entries = [e for e in doc.get("entries", []) if isinstance(e, dict)]

    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "text": text}
    if args.ref:
        entry["ref"] = args.ref
    if args.ttl_hours != 72:
        entry["ttl_hours"] = args.ttl_hours

    # Refresh-on-re-mention: same --ref (or identical text with no ref)
    # bumps ts in place so a still-active thread doesn't age out.
    merged = False
    for e in entries:
        if args.ref and e.get("ref") == args.ref:
            e["ts"], e["text"] = entry["ts"], text
            merged = True
            break
        if not args.ref and e.get("text", "").casefold() == text.casefold():
            e["ts"] = entry["ts"]
            merged = True
            break
    if not merged:
        entries.append(entry)

    entries.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(yaml.safe_dump({"entries": entries[:KEEP]},
                                    allow_unicode=True, sort_keys=False))
    print(f"event: {text[:60]} ({len(entries[:KEEP])} entries)")


if __name__ == "__main__":
    sys.exit(main())
