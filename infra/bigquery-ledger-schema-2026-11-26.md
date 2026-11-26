# BigQuery usage/score ledger — schema draft (2026-11-26)

Project: `gen-lang-client-0694401188` (Chaba). BigQuery API confirmed ENABLED; 0 datasets today. Suggested dataset `chaba_usage`, location `asia-southeast1` (Singapore) for latency/residency — change only if an existing analytics dataset must be co-located.

Principles: one row per durable fact; append-only with idempotent MERGE on natural key; partition by date, cluster by the fields we actually filter; no secrets in rows; every row carries a source pointer so it can be traced back to the local artifact it came from.

## DDL

```sql
CREATE SCHEMA IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage`
  OPTIONS (location = "asia-southeast1",
           description = "Durable usage, quota and verdict ledger for chaba/devnest agents");

-- One row per agent session (cloud handoff, host dispatch, or interactive CLI).
CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.sessions` (
  session_id       STRING NOT NULL,
  source           STRING NOT NULL,   -- devin_cloud | devin_dispatch | cli
  card_ref         STRING,
  card_id          STRING,
  repo             STRING,
  lane             STRING,
  model            STRING,
  host             STRING,
  session_url      STRING,
  started_at       TIMESTAMP NOT NULL,
  ended_at         TIMESTAMP,
  status           STRING,
  status_detail    STRING,
  acus_consumed    FLOAT64,
  on_demand_usd    FLOAT64,
  quota_points     FLOAT64,           -- daily meter delta attributed to this session
  prompt_tokens    INT64,
  cached_tokens    INT64,
  output_tokens    INT64,
  pr_url           STRING,
  pr_state         STRING,
  artifact         STRING,
  outcome_doc      STRING,
  error_reason     STRING,
  tags             ARRAY<STRING>,
  source_artifact  STRING,            -- local JSON/MD the row was derived from
  ingested_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(started_at)
CLUSTER BY source, card_ref
OPTIONS (partition_expiration_days = 365,
         description = "Per-session cost, tokens and PR outcome");

-- One row per day: the authoritative meter reading, capped at one row/day/source.
CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.daily_quota` (
  quota_date           DATE NOT NULL,
  source               STRING NOT NULL,     -- console_capture | operator
  used_pct_start       FLOAT64,
  used_pct_end         FLOAT64,
  quota_delta_points   FLOAT64,
  sessions             INT64,
  verified_prs         INT64,
  quota_points_per_pr  FLOAT64,
  dump_path            STRING,              -- AI Hub page dump on the bridge host
  captured_at          TIMESTAMP NOT NULL,
  ingested_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY quota_date
CLUSTER BY source
OPTIONS (partition_expiration_days = 730,
         description = "Daily allowance usage from GCP Console captures + meter readings");

-- One row per model judgment on a held-out fixture.
CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.eval_verdicts` (
  run_id               STRING NOT NULL,
  session_id           STRING,
  fixture_id           STRING NOT NULL,
  model                STRING NOT NULL,
  verdict              STRING NOT NULL,
  deterministic_verdict STRING,
  agreement            BOOL,
  latency_ms           INT64,
  tokens_in            INT64,
  tokens_out           INT64,
  cost_usd             FLOAT64,
  escalated            BOOL,
  created_at           TIMESTAMP NOT NULL,
  ingested_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, model
OPTIONS (partition_expiration_days = 365,
         description = "Model verdicts paired with the deterministic verifier");

-- Host model audit from the daily report (free-window tracking).
CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.model_audit` (
  host         STRING NOT NULL,
  agent_model  STRING,
  verdict      STRING NOT NULL,    -- free-now | NOT-FREE | unverified
  checked_at   TIMESTAMP NOT NULL
)
PARTITION BY DATE(checked_at)
CLUSTER BY host
OPTIONS (partition_expiration_days = 180,
         description = "Which free model each dispatch host was pinned to");
```

## Writer contract

- Natural keys: `sessions.session_id`, `daily_quota.(quota_date, source)`, `eval_verdicts.(run_id, fixture_id, model)`, `model_audit.(host, checked_at)`.
- Use MERGE, not plain INSERT, so a re-run of the daily report cannot double-count. Skeleton:

```sql
MERGE `gen-lang-client-0694401188.chaba_usage.sessions` T
USING (SELECT @session_id AS session_id, /* ...typed values... */) S
ON T.session_id = S.session_id
WHEN MATCHED THEN UPDATE SET
  status = S.status, status_detail = S.status_detail, ended_at = S.ended_at,
  acus_consumed = S.acus_consumed, quota_points = S.quota_points,
  pr_url = S.pr_url, pr_state = S.pr_state, ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT ROW;
```

- Auth from the existing ADC (`gcloud auth application-default print-access-token`) or a dedicated service account with `roles/bigquery.dataEditor` on the dataset. Never put a key in a card, repo or local report.
- Provenance: every row keeps `source_artifact` / `dump_path` pointing at the local file it came from, so a number can always be traced back.
- Cost: set `maximumBytesBilled` on queries; this dataset is small (tens of thousands of rows/year), so on-demand analysis cost should be negligible. Turn on billing alerts before scaling.

## Source → table mapping

| Existing artifact | Target table |
|---|---|
| `infra/devin-daily-usage-*.json` (`local`, `local_cli`, `model_audit`, `cloud`) | sessions (dispatch + CLI), model_audit |
| Devin v3 `--poll` output (`acus_consumed`, `pull_requests`) | sessions (devin_cloud) |
| `infra/gcp-quota-dump-*.json` + meter reading | daily_quota |
| `evals/**` results and held-out verifier output | eval_verdicts |

## Example queries

```sql
-- Real cost per verified PR (the baseline currently ≈ 4 quota-points/PR)
SELECT quota_date, verified_prs, quota_delta_points, quota_points_per_pr
FROM `gen-lang-client-0694401188.chaba_usage.daily_quota`
ORDER BY quota_date DESC LIMIT 15;

-- Spend by lane/model
SELECT source, model, COUNT(*) sessions, SUM(prompt_tokens + output_tokens) tokens,
       AVG(quota_points) avg_quota_points
FROM `gen-lang-client-0694401188.chaba_usage.sessions`
GROUP BY source, model ORDER BY sessions DESC;

-- Judge agreement vs deterministic verifier
SELECT model, COUNT(*) n, AVG(INT64(agreement)) agreement_rate, AVG(cost_usd) avg_cost
FROM `gen-lang-client-0694401188.chaba_usage.eval_verdicts`
GROUP BY model;
```

## Open decisions before implementation

1. Dataset region: `asia-southeast1` vs co-locating with an existing BigQuery-enabled analytics project.
2. Whether `daily_quota.quota_points` is per-session attribution or only a daily total (per-session needs meter deltas taken around each handoff).
3. Retention vs the 30d+ local task-dir reporting window — keep ≥365d here so pruning local dumps never loses history.
4. Who owns the MERGE writer: extend `scripts/devnest/devin_daily_usage_report.py`, or add a dedicated `scripts/bigquery/ledger-write.py`.
