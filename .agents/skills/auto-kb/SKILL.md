# Auto KB Creation Skill

Creates KB entries from KB review sections — for **stabilized, verified
findings only**. In-progress hypotheses and session narrative belong in
living docs (`info.md`, SSOT), not here.

**Automatic invocation**: at **session end** (finish-and-close), when the
session produced KB-worthy verified knowledge — per `ssot.windsurf.common.md`.
NOT per-response. Mid-session use is allowed only for a major verified
discovery, with user confirmation for new topics.

## What it does

1. Checks content against KB-worthy/negative triggers.
2. Checks redundancy via caller-supplied MDDB result
   (`MCP_REDUNDANCY_RESULT`/`MCP_REDUNDANCY_FILE`) or a local file-overlap
   fallback. High redundancy → skips and reports the similar entries.
3. Writes `<repo>/docs/kb/auto-kb-YYYYMMDD-<slug>.md` with frontmatter
   `category`, `status` (default `draft`), `created`, `source: auto-kb`.
4. Indexes the file by running `scripts/sync-kb-to-mddb.py --missing-only`
   itself — no separate assistant MCP step required.
5. Prints `AUTO_KB_RESULT {...}` as its last line. `"indexed": false`
   means created-but-pending; the `retry` field holds the command to
   finish indexing. Do not treat that run as fully successful.

## Status lifecycle

- `draft` — auto-generated, not yet verified. Default.
- `verified` — confirmed finding; set via `KB_STATUS=verified` or by
  editing frontmatter during review.
- `superseded` — replaced by a newer entry; link the replacement in the body.
- `archived` — moved under `docs/kb/archive/`; kept for history, not
  deleted. `sync-kb-to-mddb.py --sync-deletes` reconciles the index.

## Input

One of:

- CLI: `node auto-kb.mjs "<kb-review-content>" ["<context>"]`
- Env: `KB_REVIEW_CONTENT`, `KB_SESSION_CONTEXT`, `KB_STATUS`,
  `MCP_REDUNDANCY_FILE`/`MCP_REDUNDANCY_RESULT`, `KB_DIR` (override)
- Stdin: `echo "..." | node auto-kb.mjs`

## Quality gate — create entries only for

- Verified bug fixes / root causes
- Reusable workarounds and patterns
- New integrations or systems
- Config/performance findings with lasting operational value

## Do NOT create entries for

- Hypotheses or unverified conclusions (→ `info.md`/SSOT instead)
- Transient commands, one-off output, trivia, personal preference
- Session narrative or project state (→ `info.md`, job yml, handoff yml)

## Example usage

```bash
# Session-end capture of a verified finding
KB_REVIEW_CONTENT="config-template-card v1.3.6 requires variables as an object map..." \
KB_STATUS=verified \
  node .agents/skills/auto-kb/auto-kb.mjs

# With pre-computed MDDB redundancy result
KB_REVIEW_CONTENT="..." MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json \
  node .agents/skills/auto-kb/auto-kb.mjs

# Retry indexing after MDDB was unreachable
python3 scripts/sync-kb-to-mddb.py --missing-only
```

## Related documentation

- `.windsurf/workflows/auto-kb-creation.md` - Detailed workflow documentation
- `scripts/sync-kb-to-mddb.py` - Canonical KB→MDDB indexer
- `docs/kb/` - Existing KB entries for reference patterns
