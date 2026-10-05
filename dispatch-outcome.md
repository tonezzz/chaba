# dispatch outcome — inbox-triage-round-2 (symptom sweep)

## What was done

Triaged `docs/ada-memory/inbox/general/` — 222 files (201 `extract-*` dated
2026-09-20→2026-10-02 plus 21 stray notes, including 6 newer 10-04 items).
Each file's frontmatter `key` was matched against its MDDB bank doc
(`ada-ha-bank-general`, 230 docs, cross-checked `ada-ha-bank-devin-handoff`,
223 docs — no inbox key lived there).

Classification result — **every file's bank doc was already resolved**:

| bank doc status | files | action |
|---|---|---|
| superseded | 53 | → `inbox/processed/` |
| retracted | 63 | → `inbox/processed/` |
| active + vault file exists | 100 | → `inbox/processed/` (stale dup) |
| active + no vault file | 5 | promoted to `general/` (round-2 "P" convention: status→active, session_id dropped, body verified identical to MDDB doc) |
| active, stale vs live doc | 1 | `yomi-vs-line-bot.md` → `inbox/processed/` (doc rewritten devin-side 10-04: Yomi offline; promoting the stale copy would conflict) |
| draft / missing / live | 0 | — |

**0 live items** found (no open bugs, no awaiting-user requests, no drafts).
`inbox/general/` is now empty; `inbox/processed/` holds 217 archived files.
No MDDB writes — no bank doc statuses were changed.

## Where

- Job trail: `docs/ssot/jobs/ada/2026-10-04-inbox-general-symptom-sweep.yml`
- Decision artifacts: `.triage2/` (bank dumps, per-file `report.json`, `actions.json`, `classify.py`)

## Not done / notes

- Root cause untouched per card: overnight focus pipeline exits 1 (separate
  card). `export_inbox` in `scripts/ada/sync-ada-memory-to-mddb.py` re-exports
  draft + voice/active docs — processed files may re-accumulate until the
  pipeline fix lands.
- Other bank inboxes still populated (out of scope): devin-handoff 86,
  note 31, people 52, personal 142, personal-kk 27, personal-testo 1,
  purchase 13, tony-projects 101.

## Verify

    ls docs/ada-memory/inbox/general | wc -l      # 0
    ls docs/ada-memory/inbox/processed | wc -l    # 217
    # spot-check a promoted file:
    cat docs/ada-memory/general/extract-2026-10-04-e7afe759ba-4.md
