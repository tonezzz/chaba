#!/usr/bin/env python3
"""Declare the wiki support pages the sinks reference — through the
/wiki/page door (card wiki-member-knowledge-surface-migrate-wp-3a1cf2).

The MediaWiki sinks render every lesson/report page inside a template
call; the template pages themselves live in the Template namespace
(แม่แบบ: on the Thai wiki) and can't be written through the kind-gated
sinks. This script creates/updates them via the guarded /wiki/page
endpoint — no wiki creds on the runner.

  default:    print the pages that would be written.
  --apply:    POST each to /wiki/page. Safe to rerun — a wiki edit is
              idempotent by content (Nochange on identical text).

Education:/Reports: titles also pass through here (index/portal pages),
but the door refuses them until the namespaces are registered in
LocalSettings — the Tony/Plesk step. Template pages are creatable any
time (Template ns always exists).
"""
import argparse, json, sys, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))

try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"

EDUCATION_TEMPLATE = """\
{| class="wikitable" style="float:right; margin-left:1em;"
! colspan="2" | Education
|-
| '''Topic''' || {{{topic|}}}
|-
| '''Level''' || {{{level|}}}
|-
| '''Source''' || {{{source|}}}
|-
| '''Learned''' || {{{learned_at|}}}
|-
| '''Next review''' || {{{next_review|}}}
|-
| '''Status''' || {{{status|}}}
|-
| '''Updated''' || {{{updated|}}}
|-
| '''Event''' || {{{event_id|}}}
|}
<noinclude>Lesson page header for the Education: namespace. Fields:
topic, level (intro|working|deep), source (chat|voice|link),
learned_at, next_review, status, updated, no_th, event_id. Written by
board-api's WikiLessonSink and scripts/wiki-lesson-migrate.py —
hand-edits get overwritten on the next machine write.</noinclude>
"""

REPORT_TEMPLATE = """\
{| class="wikitable" style="float:right; margin-left:1em;"
! colspan="2" | Report
|-
| '''Type''' || {{{report_type|}}}
|-
| '''Period''' || {{{period|}}}
|-
| '''Source''' || {{{source_key|}}}
|-
| '''Status''' || {{{status|}}}
|-
| '''Updated''' || {{{updated|}}}
|-
| '''Event''' || {{{event_id|}}}
|}
<noinclude>Member-facing report header for the Reports: namespace.
Fields: report_type, period, source_key, status, updated, event_id.
Living pages — machine-overwritten by board-api's WikiReportSink /
scripts/wiki-report-migrate.py.</noinclude>
"""

PAGES = [
    {"title": "แม่แบบ:Education", "wikitext": EDUCATION_TEMPLATE,
     "summary": "Education lesson template (chaba wiki migration)"},
    {"title": "แม่แบบ:Report", "wikitext": REPORT_TEMPLATE,
     "summary": "Member report template (chaba wiki migration)"},
]


def post(api, path, body):
    req = urllib.request.Request(
        f"{api}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the pages via /wiki/page")
    ap.add_argument("--api", default=API)
    a = ap.parse_args()

    if not a.apply:
        for p in PAGES:
            print(f"{p['title']}  ({len(p['wikitext'])} chars)")
        print(f"\n{len(PAGES)} support pages — dry-run; --apply writes "
              "via /wiki/page")
        return 0

    fail = 0
    for p in PAGES:
        try:
            r = post(a.api, "/wiki/page",
                     {"title": p["title"], "wikitext": p["wikitext"],
                      "summary": p["summary"], "from": "devin"})
            print(f"ok   {p['title']:<28} {r.get('action')} "
                  f"rev={r.get('revid')}")
        except Exception as e:
            fail += 1
            print(f"FAIL {p['title']:<28} {str(e)[:160]}")
    print(f"\n{len(PAGES) - fail} written, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
