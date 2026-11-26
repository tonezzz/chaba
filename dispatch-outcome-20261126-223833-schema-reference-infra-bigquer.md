# Dispatch outcome — bigquery-usage-ledger-writer (OPS-1460)

## Result: DONE (card → review)

Dataset `chaba_usage` created on GCP project `gen-lang-client-0694401188`
(asia-southeast1) with all four tables; 15 rows backfilled (9 sessions,
1 daily_quota, 0 eval_verdicts, 5 model_audit); idempotency verified;
verification output posted to the card.

## What changed (worktree)

- `infra/` — vendored session-folder artifacts from idc02
  `~/tony-projects/infra/`: schema doc, devin-daily-usage-2026-11-26
  (.json/.md), gcp-quota-dump, cloud baseline (.json/.md), plus new
  `devin-usage-console-2026-11-26.{md,json}` recording the operator-read
  Devin meter (4%→12%, 2 PRs, 4 pts/PR) that had no file artifact.
- `scripts/bigquery/ledger_write.py` — stdlib-only MERGE writer
  (--dry-run / --backfill / --daily), BigQuery REST + ADC, per-table
  --limit, provenance on every row, maximumBytesBilled=256MiB.
- `scripts/bigquery/chaba_usage.ddl.sql` — applied DDL (see deviation
  below).
- `docs/ssot/infrastructure/ssot.reports.yml` — new `data_stores:`
  section registering the dataset, tables, owner, writer, schema pointer,
  and the billing-alert precondition.
- `docs/ssot/jobs/devnest/2026-11-26-bigquery-usage-ledger.yml` — full
  job doc with region/retention/writer-semantics decisions.

## Key findings / decisions

- The card's backfill spec was internally inconsistent ("6 local / 10
  rows" vs "expect sessions=9"; report actually has 7 dispatch + 5 audit
  hosts). Raised board request `bq-backfill-counts`; Tony answered
  **all-rows** → verification counts are 9/1/0/5, not the card's literal
  9/1/0/1.
- Schema doc DDL had two invalid-for-BigQuery constructs:
  `DEFAULT CURRENT_TIMESTAMP()` column default (not supported) and
  `PARTITION BY DATE(<date_col>)` on an already-DATE column. Applied DDL
  drops the default (writer sets ingested_at explicitly) and partitions
  daily_quota by the bare DATE column.
- BigQuery REST quirks learned: ARRAY params need
  `parameterType:{type:ARRAY,arrayType:{...}}`; NULL params need an
  explicit `"parameterValue": {}` — omitting it is a 400.
- `--limit` is per-table, not global (documented in job doc).
- eval_verdicts intentionally empty until ADA-1458 runs.
- Live copies also staged at idc02 `~/tony-projects/scripts/bigquery/`
  (the host where ADC + the infra artifacts live).

## How to verify

```
# on idc02 (ADC host):
cd ~/tony-projects/scripts/bigquery
python3 ledger_write.py --dry-run --input-dir ~/tony-projects/infra
python3 ledger_write.py --backfill --limit 10 --input-dir ~/tony-projects/infra
# counts: sessions=9 daily_quota=1 eval_verdicts=0 model_audit=5 (idempotent)
```

Card comms carry the full verification query output.

lessons:
- BigQuery REST: NULL query params need `"parameterValue": {}`; ARRAY<STRING> needs `parameterType:{type:"ARRAY",arrayType:{type:"STRING"}}` — "ARRAY<STRING>" as type is a 400.
- BigQuery rejects `DEFAULT CURRENT_TIMESTAMP()` as a column default and `PARTITION BY DATE()` on a DATE column — schema-doc DDL must be sanity-checked against real API errors, not assumed valid.
- devin-dispatch cards can carry internally inconsistent counts (card said 6 local/10 rows but expected 9 sessions); when spec math doesn't reconcile, raise a board request with options early and keep building — answers arrive via $TASK_DIR/answers.jsonl.
- The "infra/" session folder for devin-handoff artifacts lives on idc02 at ~/tony-projects/infra/, not in any repo — check remote hosts before declaring inputs missing.
- gcloud/ADC for project gen-lang-client-0694401188 exists only on idc02; ssh -o ProxyJump=none idc02 is the working path (ProxyJump via tony-omen is administratively prohibited).
