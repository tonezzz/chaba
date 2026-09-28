#!/usr/bin/env python3
"""vocab-pages-sync.py — mirror each speaker's vocab/log memory doc into
their per-person CMS glossary page.

Ada appends coaching entries to vocab/log in the speaker's personal bank
(ada-ha-bank-personal-{person}) via the vocab_note tool. This script
rebuilds the '## From Ada' / '## จาก Ada' section of the matching
ada-cms-pages page (my-words, my-words-kk, ...) from those lines, leaving
the rest of the page (e.g. the Devin-maintained sections) untouched.

Runs inside the export-transcripts refresh chain; safe to run anytime —
idempotent, skips when nothing changed.

  vocab-pages-sync.py            # sync all known people
  vocab-pages-sync.py --dry-run  # show what would change
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

MDDB = "http://100.74.146.0:11023/v1"

# person -> (personal-bank collection, cms page slug)
PEOPLE = {
    "tony": ("ada-ha-bank-personal-tony", "my-words"),
    "kk": ("ada-ha-bank-personal-kk", "my-words-kk"),
}

SECTION_HEAD = {"en": "## From Ada", "th": "## จาก Ada"}
EMPTY_NOTE = {
    "en": "_(none yet — entries appear here when Ada recasts a word mid-conversation)_",
    "th": "_(ยังไม่มี — รายการจะโผล่เมื่อ Ada ใช้คำที่ถูกแทนในบทสนทนา)_",
}

LINE_RE = re.compile(r"^-\s+(.+?)\s*→\s*(.+?)\s*—\s*(\d{4}-\d{2}-\d{2})(?:\s*\((.+)\))?\s*$")


def api(path, body=None, method="POST"):
    req = urllib.request.Request(
        f"{MDDB}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method if body is None else "POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_doc(collection, key, lang="en"):
    try:
        return api("/get", {"collection": collection, "key": key, "lang": lang})
    except Exception:
        return None


def put_doc(collection, key, lang, content, meta):
    return api("/add", {"collection": collection, "key": key, "lang": lang,
                        "contentMd": content, "meta": meta})


def parse_vocab(body: str) -> list[dict]:
    out = []
    for line in (body or "").splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            out.append({"term": m.group(1), "correct": m.group(2),
                        "date": m.group(3), "note": m.group(4) or ""})
    return out


def render_section(entries: list[dict], lang: str) -> str:
    head = SECTION_HEAD[lang]
    if not entries:
        return f"{head}\n\n{EMPTY_NOTE[lang]}"
    lines = [head, ""]
    for e in entries:
        note = f" — {e['note']}" if e["note"] else ""
        lines.append(f"- **{e['term']}** → {e['correct']} ({e['date']}){note}")
    return "\n".join(lines)


def sync_person(person: str, dry: bool) -> str:
    bank, slug = PEOPLE[person]
    doc = get_doc(bank, "vocab/log")
    entries = parse_vocab((doc or {}).get("contentMd") or "")
    changed = []
    for lang in ("en", "th"):
        page = get_doc("ada-cms-pages", slug, lang)
        if page is None:
            continue
        body = page.get("contentMd") or ""
        head = SECTION_HEAD[lang]
        idx = body.find(head)
        if idx < 0:
            # page has no Ada section — append one
            new_body = body.rstrip("\n") + "\n\n" + render_section(entries, lang) + "\n"
        else:
            # keep everything before the section; our section runs to EOF
            # or to the next "## " heading, whichever comes first
            tail = body[idx:]
            nxt = tail.find("\n## ", 1)
            keep_tail = tail[nxt:] if nxt >= 0 else ""
            new_body = body[:idx].rstrip("\n") + "\n\n" + render_section(entries, lang)
            new_body += ("\n" + keep_tail.lstrip("\n")) if keep_tail else "\n"
        if new_body != body:
            changed.append(lang)
            if not dry:
                meta = dict(page.get("meta") or {})
                meta["updated"] = [datetime.now(timezone.utc).isoformat(timespec="seconds")]
                put_doc("ada-cms-pages", slug, lang, new_body, meta)
    return f"{person}: {len(entries)} vocab entries" + \
           (f" — updated {slug} [{'+'.join(changed)}]" if changed else " — no change")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for person in PEOPLE:
        try:
            print(sync_person(person, args.dry_run))
        except Exception as exc:
            print(f"{person}: sync failed — {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
