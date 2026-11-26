-- chaba_usage dataset + tables — DDL verbatim from
-- infra/bigquery-ledger-schema-2026-11-26.md (OPS-1460 / bigquery-usage-ledger-writer).
-- Project: gen-lang-client-0694401188 — region asia-southeast1.

CREATE SCHEMA IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage`
  OPTIONS (location = "asia-southeast1",
           description = "Durable usage, quota and verdict ledger for chaba/devnest agents");

CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.sessions` (
  session_id       STRING NOT NULL,
  source           STRING NOT NULL,
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
  quota_points     FLOAT64,
  prompt_tokens    INT64,
  cached_tokens    INT64,
  output_tokens    INT64,
  pr_url           STRING,
  pr_state         STRING,
  artifact         STRING,
  outcome_doc      STRING,
  error_reason     STRING,
  tags             ARRAY<STRING>,
  source_artifact  STRING,
  ingested_at      TIMESTAMP NOT NULL
)
PARTITION BY DATE(started_at)
CLUSTER BY source, card_ref
OPTIONS (partition_expiration_days = 365,
         description = "Per-session cost, tokens and PR outcome");

CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.daily_quota` (
  quota_date           DATE NOT NULL,
  source               STRING NOT NULL,
  used_pct_start       FLOAT64,
  used_pct_end         FLOAT64,
  quota_delta_points   FLOAT64,
  sessions             INT64,
  verified_prs         INT64,
  quota_points_per_pr  FLOAT64,
  dump_path            STRING,
  captured_at          TIMESTAMP NOT NULL,
  ingested_at          TIMESTAMP NOT NULL
)
PARTITION BY quota_date
CLUSTER BY source
OPTIONS (partition_expiration_days = 730,
         description = "Daily allowance usage from GCP Console captures + meter readings");

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
  ingested_at          TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, model
OPTIONS (partition_expiration_days = 365,
         description = "Model verdicts paired with the deterministic verifier");

CREATE TABLE IF NOT EXISTS `gen-lang-client-0694401188.chaba_usage.model_audit` (
  host         STRING NOT NULL,
  agent_model  STRING,
  verdict      STRING NOT NULL,
  checked_at   TIMESTAMP NOT NULL
)
PARTITION BY DATE(checked_at)
CLUSTER BY host
OPTIONS (partition_expiration_days = 180,
         description = "Which free model each dispatch host was pinned to");
