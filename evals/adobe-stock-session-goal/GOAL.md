# Session Goal — Adobe Stock reuse QC (read-only)

**Goal id:** `adobe-stock-reuse-qc-v1`
**Card:** `openchamber-session-goals-adobe-stock-qc`
**Executor:** an OpenChamber (ocb/opencode) session — any approved model/profile
**Posture:** READ-ONLY. This goal exists to test whether a Session Goal can
drive a bounded review to a verifiable stop. It must not create cards, upload
assets, generate images, license assets, or publish anything.

## Named campaign idea

`campaign_idea = "remote work home office"`

This is the idea string passed verbatim to the reuse report. In the current
index it resolves to campaign `AS-2026-11-05-REMOTE-WORK-001`; treat the
campaign_id returned by the report as authoritative — do not assume it.

## Steps

1. **Call the Adobe Stock reuse MCP report exactly once:**
   `ada_adobe_stock_reuse(campaign_idea="remote work home office", compact=false)`.
   Capture the full report. If the call fails, retry once; if it still fails,
   record the failure in `open_questions` and continue with what is known —
   do not loop on the tool.
2. **List candidate assets with provenance.** For every asset the report
   returns, copy its provenance fields verbatim (`sha256`, `provider`,
   `job_id`, `source_ref`, `campaign_id` — whatever the report carries; never
   invent or normalize values). Attach a reuse `decision`
   (`reuse|remix|reject|hold`), a one-line `reason`, and `preview_status`
   (`available|thumbnail-only|unavailable|unknown`).
3. **Flag missing previews.** `missing_previews` = every asset_id with no
   `preview_url`/`thumbnail_url` in the report. An empty list is a valid
   answer — write `[]`, do not omit the key.
4. **Flag open questions.** Anything ambiguous: assets with partial
   provenance, QC state the report does not resolve, preview URLs that are
   present but not fetchable, conflicts between report fields. An empty list
   is valid.
5. **Write the artifacts** (below) into the session working directory.
6. **Record the run** in `run.json` (below).
7. **STOP.** When the four stop conditions hold, emit one final summary
   message and end the session. Do not continue iterating, do not ask
   follow-up questions, do not start adjacent work.

## Stop condition — ALL must hold before the final message

1. The reuse MCP report was called and its result captured
   (`report.tool` + `report.called_at` recorded in the JSON artifact).
2. `candidates[]` covers every asset the report returned, each with a
   provenance block copied from the report.
3. `missing_previews[]` and `open_questions[]` are written (empty list OK).
4. `policy.mutations_performed` is `[]`, every `policy.*_requested` /
   `policy.cards_created` / `policy.published` flag is `false`, and
   `no_mutation_receipt` is present.

If a condition cannot be met (e.g., the MCP report is unreachable), write
what is known, mark the gap in `open_questions`, set
`run.json.stop_reason` to `blocked:<reason>`, and stop anyway — a blocked
stop with an honest artifact beats a loop.

## Required artifacts (session working directory)

- `adobe-stock-reuse-report.md` — human-readable markdown: campaign idea,
  report summary, candidate table (asset_id, decision, preview_status,
  provenance), missing previews, open questions, policy statement.
- `adobe-stock-reuse-report.json` — the structured artifact:

```json
{
  "goal_id": "adobe-stock-reuse-qc-v1",
  "campaign_idea": "remote work home office",
  "campaign_id": "<id returned by the report>",
  "report": {
    "tool": "ada_adobe_stock_reuse",
    "called_at": "<ISO-8601>",
    "asset_count": 0,
    "report_ref": "<report id/path/summary if the tool returns one>"
  },
  "candidates": [
    {
      "asset_id": "<id>",
      "decision": "reuse|remix|reject|hold",
      "reason": "<one line>",
      "preview_status": "available|thumbnail-only|unavailable|unknown",
      "provenance": {
        "sha256": "<verbatim>",
        "provider": "<verbatim>",
        "job_id": "<verbatim or null>",
        "source_ref": "<verbatim>",
        "campaign_id": "<verbatim>"
      }
    }
  ],
  "missing_previews": ["<asset_id>", "..."],
  "open_questions": ["<string>", "..."],
  "policy": {
    "mutations_performed": [],
    "cards_created": false,
    "adobe_upload": false,
    "generation_requested": false,
    "licensing_requested": false,
    "published": false
  },
  "no_mutation_receipt": {
    "statement": "<one-line attestation>",
    "checked_at": "<ISO-8601>"
  }
}
```

- `run.json` — the run record:

```json
{
  "goal_id": "adobe-stock-reuse-qc-v1",
  "session_id": "<ocb/opencode session id if exposed>",
  "executor": "<host + agent/profile used>",
  "model": "<model id if exposed, else null>",
  "started_at": "<ISO-8601>",
  "finished_at": "<ISO-8601>",
  "turns": 0,
  "cost_usd": null,
  "tokens": {"input": null, "output": null},
  "artifact_dir": ".",
  "stop_reason": "acceptance-met | blocked:<reason>",
  "verifier": "evals/adobe-stock-session-goal/verify.py"
}
```

`cost_usd` may be `null` when the executor does not meter cost — record
`null`, never estimate silently. `turns` = assistant turns/messages in the
session (from the ocb/opencode session record or event log).

## Hard boundaries

- Read-only MCP/report calls and local artifact writes ONLY.
- Forbidden: kanban card creation or any board write, asset upload,
  image generation, licensing, publishing, Adobe Stock mutation, service
  restarts, git commits/pushes.
- Do not ask clarifying questions mid-run — record them in
  `open_questions` and proceed with the stated defaults.
- Do not fabricate provenance, asset ids, URLs, or report contents. If the
  report lacks a field, record `null` and note it in `open_questions`.
