# Dispatch outcome — lesson-polish-run (20261125-190732)

## Result

Recurring lesson-polish pass complete. Re-audited the full lesson corpus
through the board-api `/lesson` door (`POST /lesson {"op":"list","content":1}`
— the spec's literal `/lesson/lesson` path 404s; plain `/lesson` is the door),
applied `scripts/lessons-audit.py:audit_one`, and re-filed all **190
R1/R3/R4-flagged lessons**.

- **Before:** 227 lessons, 207 flagged total; 190 in polish scope
  (125 R1:overdue-only, 35 R1+R3, 16 R1:level-invalid, 10 R3-only,
  3 R1+R4, 1 level-invalid+no-next-review).
- **After:** 227 lessons, **0 R1/R3/R4 flags**. Remaining 59 flagged are
  out of scope: R2 thin ×6 (human-gated) + R5 consider-thai ×56
  (curated exemptions). Verified by a fresh `op:list content=1` +
  `audit_one` re-run; report at
  `docs/reports/lesson-audit/lesson-polish-after-2026-11-25.json`.

## Actions applied (all via the door, no deletes, no commits/pushes)

- 164 `next_review` → 2026-12-02 (explicit override; re-file preserves
  old dates by design).
- 17 level fixes: 16 `panelui-*` `reference`→`deep`, `ada-ha-mcp`
  blank→`working` (allowed: intro|working|deep).
- 48 pointer inserts (45 R3 SSOT/KB pointers with verified targets +
  3 R4 family hub pointers), all placed in the EN body BEFORE the
  `<h3>ไทย</h3>` section.
- 17 source sanitizations (16 panelui URL sources → `link`;
  `tony-agent-exploration` → `chat`) — the door rejects non-enum sources.
- ~35 Thai-free non-exempt lessons got automatic Thai sections via the
  door's `_gemini_thai` (R5 count dropped 66→56).

## Content-fidelity method

Lesson bodies are **wikitext**, but the door's write path converts
submitted content via `publication.html_to_wikitext` (meta.format
hardcoded `html`). Resubmitting raw wikitext shreds
`<syntaxhighlight>`/`<div>`/`<pre>` blocks (PanelUI lessons lost ~50%).
Fix: `html.escape()` the stored wikitext before POST — the parser emits
it back ~verbatim. Verified byte-identical on all 16 PanelUI bodies and
EN-identical on every other polished lesson except intended pointer
insertions.

## Two door hazards found and repaired

1. **Title-mismatch duplicates (17 lessons).** `/lesson` upserts by
   `lesson_wiki_title(topic)`, not the `lesson-<md5>` slug. The 16
   panelui-* lessons + trade-map live on non-canonical titles, so the
   door created duplicate canonical pages with degraded meta
   (learned_at reset, provenance lost). Repaired without deletes: restored
   provenance meta on the canonical pages via `POST /wiki/page` (raw
   wikitext, Education: allowlist), converted the 17 stale pages to
   `#REDIRECT` stubs (drop out of `op:list`, links still resolve), and
   re-filed each topic so `action=updated` and the MDDB mirror re-synced.
   Corpus back to 227 lessons / 0 dup topics.
2. **BODY_MAX=20000 truncation (5 lessons).** Lessons already at the
   ~20000-char migration cap lost tail chars when escaped resubmission
   pushed bodies over the limit. Recovered full bodies from the frozen
   WP archive (`op:get source:"wp"` → local `html_to_wikitext` →
   `/wiki/page`), restoring 20–24K complete bodies including sections
   the wiki copies lacked (e.g. ada-nest-hardware Test-010, ~2.9K chars).

## Card comms

Before/after counts + full 190-row per-lesson action list posted to
`lesson-polish-run` and `lesson-audit-scheduled`.

## Trail

- `docs/ssot/jobs/education/2026-11-25-lesson-polish-pass.yml` — full
  run record + follow-ups (slug-based upsert, BODY_MAX policy, spec
  updates for the escape trick and /wiki/page repair path).
- `docs/reports/lesson-audit/lesson-polish-after-2026-11-25.json` —
  post-pass audit report.

## Verify

```
POST https://idc03.taila0626a.ts.net:10000/lesson {"op":"list","content":1}
# then audit_one per row — expect 0 R1/R3/R4 flags, 227 lessons
```

lessons:
- /lesson write path takes HTML, not wikitext — html.escape() stored wikitext before resubmit or the converter eats <syntaxhighlight>/<pre>/<div> bodies (~50% loss on PanelUI lessons).
- /lesson upserts by lesson_wiki_title(topic), NOT the lesson-<md5> slug — lessons on non-canonical Education: titles get DUPLICATE pages with reset provenance; check wiki_title==lesson_wiki_title(topic) in audits.
- POST /wiki/page (from:"devin") writes raw wikitext under Education:/Reports:/Infrastructure: — the repair hatch for pages /lesson can't reach; also the only door that holds >20000 chars (publication.BODY_MAX truncates /lesson bodies silently).
- Frozen WP archive (op:get source:"wp") retains full pre-migration lesson HTML — recovery source when wiki bodies were cap-truncated; convert locally with scripts/board/publication.py:html_to_wikitext.
- Stale-title cleanup without deletes: rewrite page to '#REDIRECT [[canonical]]' — drops out of op:list (no Education template) while keeping inbound links live.
