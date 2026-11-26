#!/usr/bin/env python3
"""ledger_write.py — MERGE writer for the chaba_usage BigQuery ledger.

Reads the local usage artifacts under infra/ (daily usage reports, cloud
session baselines, console meter captures, eval verdict JSONs) and upserts
them into the chaba_usage dataset via the BigQuery REST API. Auth is
application-default credentials (`gcloud auth application-default
print-access-token`); no key material is ever stored or printed.

Tables / natural keys (see infra/bigquery-ledger-schema-2026-11-26.md):

  sessions         session_id
  daily_quota      quota_date + source
  eval_verdicts    run_id + fixture_id + model
  model_audit      host + checked_at

Writes are MERGE-only — there is no plain INSERT path — so re-running the
same inputs never increases row counts.

Modes:

  --dry-run          print the typed rows and target table; write nothing
  --backfill         load rows from ALL matching artifacts (--limit N caps
                     rows per table; default 1000)
  --daily            load rows from the NEWEST artifact of each kind only
                     (the scheduled-report cadence); includes cli sessions

Every emitted row carries provenance: sessions.source_artifact and
daily_quota.dump_path point back at the repo-relative artifact it was
derived from.

Env overrides: CHABA_BQ_PROJECT, CHABA_BQ_DATASET, CHABA_BQ_MAX_BYTES,
BQ_ACCESS_TOKEN (skip gcloud), CHABA_BQ_LOCATION.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = REPO / "infra"
BQ_API = "https://bigquery.googleapis.com/bigquery/v2"
DEFAULT_MAX_BYTES = str(256 * 1024 * 1024)  # 256 MiB per query

PROJECT = os.environ.get("CHABA_BQ_PROJECT", "gen-lang-client-0694401188")
DATASET = os.environ.get("CHABA_BQ_DATASET", "chaba_usage")
MAX_BYTES = os.environ.get("CHABA_BQ_MAX_BYTES", DEFAULT_MAX_BYTES)

# column -> BigQuery type, mirroring scripts/bigquery/chaba_usage.ddl.sql
SCHEMAS = {
    "sessions": {
        "key": ["session_id"],
        "cols": {
            "session_id": "STRING", "source": "STRING", "card_ref": "STRING",
            "card_id": "STRING", "repo": "STRING", "lane": "STRING",
            "model": "STRING", "host": "STRING", "session_url": "STRING",
            "started_at": "TIMESTAMP", "ended_at": "TIMESTAMP",
            "status": "STRING", "status_detail": "STRING",
            "acus_consumed": "FLOAT64", "on_demand_usd": "FLOAT64",
            "quota_points": "FLOAT64", "prompt_tokens": "INT64",
            "cached_tokens": "INT64", "output_tokens": "INT64",
            "pr_url": "STRING", "pr_state": "STRING", "artifact": "STRING",
            "outcome_doc": "STRING", "error_reason": "STRING",
            "tags": "ARRAY<STRING>", "source_artifact": "STRING",
        },
    },
    "daily_quota": {
        "key": ["quota_date", "source"],
        "cols": {
            "quota_date": "DATE", "source": "STRING",
            "used_pct_start": "FLOAT64", "used_pct_end": "FLOAT64",
            "quota_delta_points": "FLOAT64", "sessions": "INT64",
            "verified_prs": "INT64", "quota_points_per_pr": "FLOAT64",
            "dump_path": "STRING", "captured_at": "TIMESTAMP",
        },
    },
    "eval_verdicts": {
        "key": ["run_id", "fixture_id", "model"],
        "cols": {
            "run_id": "STRING", "session_id": "STRING",
            "fixture_id": "STRING", "model": "STRING", "verdict": "STRING",
            "deterministic_verdict": "STRING", "agreement": "BOOL",
            "latency_ms": "INT64", "tokens_in": "INT64",
            "tokens_out": "INT64", "cost_usd": "FLOAT64",
            "escalated": "BOOL", "created_at": "TIMESTAMP",
        },
    },
    "model_audit": {
        "key": ["host", "checked_at"],
        "cols": {
            "host": "STRING", "agent_model": "STRING",
            "verdict": "STRING", "checked_at": "TIMESTAMP",
        },
    },
}

TABLE_ORDER = ["daily_quota", "eval_verdicts", "model_audit", "sessions"]

# tables carrying an ingested_at audit column (model_audit does not)
INGESTED_TABLES = {"sessions", "daily_quota", "eval_verdicts"}


def _token() -> str:
    tok = os.environ.get("BQ_ACCESS_TOKEN")
    if tok:
        return tok
    p = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"gcloud ADC token failed: {p.stderr.strip()[:200]}")
    return p.stdout.strip()


def bq_query(sql: str, params: list | None = None) -> dict:
    body = {
        "query": sql,
        "useLegacySql": False,
        "timeoutMs": 120000,
        "maximumBytesBilled": MAX_BYTES,
    }
    if params:
        body["queryParameters"] = params
        body["parameterMode"] = "NAMED"
    req = urllib.request.Request(
        f"{BQ_API}/projects/{PROJECT}/queries",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        raise RuntimeError(f"BigQuery HTTP {e.code}: {detail}") from e


def _param(name: str, bq_type: str, value):
    if bq_type == "ARRAY<STRING>":
        ptype = {"type": "ARRAY", "arrayType": {"type": "STRING"}}
    else:
        ptype = {"type": bq_type}
    p = {"name": name, "parameterType": ptype}
    if value is None:
        p["parameterValue"] = {}
        return p
    if bq_type == "ARRAY<STRING>":
        p["parameterValue"] = {"arrayValues": [
            {"value": str(v)} for v in value]}
    elif bq_type == "TIMESTAMP":
        p["parameterValue"] = {"value": to_ts(value)}
    elif bq_type == "BOOL":
        p["parameterValue"] = {"value": "true" if value else "false"}
    else:
        p["parameterValue"] = {"value": str(value)}
    return p


def to_ts(value) -> str | None:
    """Normalize a timestamp-ish value to RFC3339 for BigQuery TIMESTAMP."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(
            value, tz=timezone.utc).isoformat()
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def to_date(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s[:10] if len(s) >= 10 else None


def merge_row(table: str, row: dict) -> str:
    """Build a parameterized MERGE for one row. Returns (sql, params)."""
    spec = SCHEMAS[table]
    cols = spec["cols"]
    key = spec["key"]
    fqn = f"`{PROJECT}.{DATASET}.{table}`"

    select_parts = []
    params = []
    for i, (name, bq_type) in enumerate(cols.items()):
        raw = row.get(name)
        if name == "quota_date":
            raw = to_date(raw)
        elif bq_type == "TIMESTAMP":
            raw = to_ts(raw)
        pname = f"p{i}"
        select_parts.append(f"@{pname} AS `{name}`")
        params.append(_param(pname, bq_type, raw))

    on = " AND ".join(f"T.`{k}` = S.`{k}`" for k in key)
    updates = [f"`{c}` = IFNULL(S.`{c}`, T.`{c}`)"
               for c in cols if c not in key]
    if table in INGESTED_TABLES:
        updates.append("`ingested_at` = CURRENT_TIMESTAMP()")
    insert_cols = [c for c in cols]
    insert_vals = [f"S.`{c}`" for c in cols]
    if table in INGESTED_TABLES:
        insert_cols.append("ingested_at")
        insert_vals.append("CURRENT_TIMESTAMP()")
    sql = (
        f"MERGE {fqn} T\n"
        f"USING (SELECT {', '.join(select_parts)}) S\n"
        f"ON {on}\n"
        f"WHEN MATCHED THEN UPDATE SET {', '.join(updates)}\n"
        f"WHEN NOT MATCHED THEN INSERT ({', '.join('`'+c+'`' for c in insert_cols)}) "
        f"VALUES ({', '.join(insert_vals)})")
    return sql, params


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path, input_dir: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _meta_for(task: str, meta_dir: Path | None) -> dict:
    if not meta_dir:
        return {}
    f = meta_dir / task / "meta.json"
    if not f.is_file():
        return {}
    try:
        return _read_json(f)
    except Exception:
        return {}


def rows_from_daily_usage(path: Path, input_dir: Path,
                          meta_dir: Path | None,
                          sessions_db: Path | None,
                          include_cli: bool) -> list[tuple[str, dict]]:
    """Emit (table, row) candidates from one devin-daily-usage-*.json."""
    doc = _read_json(path)
    src = _rel(path, input_dir)
    checked_at = to_ts(doc.get("generated_at")) or to_ts(
        datetime.now(timezone.utc).isoformat())
    out: list[tuple[str, dict]] = []

    for r in (doc.get("local") or {}).get("rows") or []:
        task = r.get("task") or ""
        meta = _meta_for(task, meta_dir)
        out.append(("sessions", {
            "session_id": r.get("session"),
            "source": "devin_dispatch",
            "card_id": meta.get("card"),
            "repo": meta.get("repo"),
            "model": r.get("model"),
            "host": r.get("host"),
            "started_at": meta.get("started_at") or r.get("finished_at"),
            "ended_at": meta.get("finished_at"),
            "prompt_tokens": r.get("prompt"),
            "cached_tokens": r.get("cached"),
            "output_tokens": r.get("completion"),
            "source_artifact": src,
        }))

    cli_created = _cli_created_at(sessions_db) if include_cli else {}
    for r in (doc.get("local_cli") or {}).get("rows") or []:
        sid = r.get("id")
        started = cli_created.get(sid)
        if not started:
            continue  # started_at is NOT NULL; skip rows we cannot date
        out.append(("sessions", {
            "session_id": f"cli:{sid}",
            "source": "cli",
            "model": r.get("model"),
            "prompt_tokens": r.get("num_tokens"),
            "started_at": started,
            "tags": ["num_tokens_approx"],
            "source_artifact": src,
        }))

    for r in doc.get("cloud") or []:
        prs = r.get("pull_requests") or []
        pr = prs[0] if prs else {}
        tags = []
        if r.get("mode"):
            tags.append(f"devin_mode:{r['mode']}")
        out.append(("sessions", {
            "session_id": r.get("session_id"),
            "source": "devin_cloud",
            "card_ref": r.get("card_ref"),
            "session_url": r.get("url"),
            "started_at": r.get("launched_at"),
            "status": r.get("status"),
            "status_detail": r.get("status_detail"),
            "acus_consumed": r.get("acus_consumed"),
            "on_demand_usd": r.get("on_demand_usage"),
            "pr_url": pr.get("pr_url"),
            "pr_state": pr.get("pr_state"),
            "error_reason": r.get("stop_reason"),
            "tags": tags or None,
            "source_artifact": src,
        }))

    for r in doc.get("model_audit") or []:
        verdict = str(r.get("verdict") or "")
        if verdict.startswith("free-now"):
            verdict = "free-now"
        elif verdict.startswith("NOT-FREE"):
            verdict = "NOT-FREE"
        else:
            verdict = "unverified"
        out.append(("model_audit", {
            "host": r.get("host"),
            "agent_model": r.get("model"),
            "verdict": verdict,
            "checked_at": checked_at,
        }))

    return out


def _cli_created_at(db: Path | None) -> dict:
    """session name -> created_at ISO, from the Devin CLI sessions.db."""
    if not db or not Path(db).is_file():
        return {}
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {sid: datetime.fromtimestamp(
                int(created), tz=timezone.utc).isoformat()
                for sid, created in con.execute(
                    "select id, created_at from sessions")}
        finally:
            con.close()
    except Exception:
        return {}


def rows_from_baseline(path: Path, input_dir: Path) -> list[tuple[str, dict]]:
    """Emit devin_cloud session rows from a devin-cloud-session-baseline-*.json."""
    doc = _read_json(path)
    if not doc.get("session_id"):
        return []
    src = _rel(path, input_dir)
    tags = []
    for t in doc.get("tags") or []:
        tl = str(t).lower()
        if tl.startswith(("ada-", "dev-", "knb-", "ops-")):
            tags.append(f"card:{tl.upper()}")
    if doc.get("devin_mode"):
        tags.append(f"devin_mode:{doc['devin_mode']}")
    poll = doc.get("poll_1") or {}
    prs = doc.get("pull_requests") or []
    pr = prs[0] if prs else {}
    return [("sessions", {
        "session_id": doc.get("session_id"),
        "source": "devin_cloud",
        "card_ref": next((t[5:] for t in tags
                          if t.startswith("card:")), None),
        "session_url": doc.get("url"),
        "started_at": doc.get("created_at"),
        "status": doc.get("status"),
        "status_detail": poll.get("status_detail") or doc.get("status_detail"),
        "acus_consumed": doc.get("acus_consumed"),
        "pr_url": pr.get("pr_url"),
        "pr_state": pr.get("pr_state"),
        "tags": tags or None,
        "source_artifact": src,
    })]


def rows_from_console_capture(path: Path, input_dir: Path) -> list[tuple[str, dict]]:
    """Emit daily_quota rows from a devin-usage-console-*.json capture."""
    doc = _read_json(path)
    src = _rel(path, input_dir)
    out = []
    for r in doc.get("readings") or []:
        start = r.get("used_pct_start")
        end = r.get("used_pct_end")
        delta = (end - start) if (end is not None and start is not None) else None
        prs = r.get("verified_prs")
        ppr = (delta / prs) if (delta and prs) else r.get("quota_points_per_pr")
        out.append(("daily_quota", {
            "quota_date": to_date(r.get("quota_date") or doc.get("quota_date")),
            "source": r.get("source") or doc.get("source") or "console_capture",
            "used_pct_start": start,
            "used_pct_end": end,
            "quota_delta_points": delta if delta is not None
            else r.get("quota_delta_points"),
            "sessions": r.get("sessions"),
            "verified_prs": prs,
            "quota_points_per_pr": ppr,
            "dump_path": src,
            "captured_at": r.get("captured_at") or doc.get("captured_at"),
        }))
    return out


def rows_from_eval_verdicts(path: Path, input_dir: Path) -> list[tuple[str, dict]]:
    """Emit eval_verdicts rows from a verdict JSON/JSONL artifact."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix == ".jsonl":
        items = [json.loads(l) for l in text.splitlines() if l.strip()]
    else:
        doc = json.loads(text)
        items = doc if isinstance(doc, list) else doc.get("verdicts") or []
    out = []
    for v in items:
        if not isinstance(v, dict) or not v.get("fixture_id"):
            continue
        out.append(("eval_verdicts", {
            "run_id": v.get("run_id"),
            "session_id": v.get("session_id"),
            "fixture_id": v.get("fixture_id"),
            "model": v.get("model"),
            "verdict": v.get("verdict"),
            "deterministic_verdict": v.get("deterministic_verdict"),
            "agreement": v.get("agreement"),
            "latency_ms": v.get("latency_ms"),
            "tokens_in": v.get("tokens_in"),
            "tokens_out": v.get("tokens_out"),
            "cost_usd": v.get("cost_usd"),
            "escalated": v.get("escalated"),
            "created_at": v.get("created_at"),
        }))
    return out


def collect_rows(input_dir: Path, *, daily: bool, include_cli: bool,
                 meta_dir: Path | None, sessions_db: Path | None,
                 eval_glob: str) -> list[tuple[str, dict]]:
    files = sorted(input_dir.glob("*")) if input_dir.is_dir() else []

    def pick(pattern: str) -> list[Path]:
        hits = sorted(input_dir.glob(pattern))
        if daily and hits:
            hits = [hits[-1]]
        return hits

    rows: list[tuple[str, dict]] = []
    # sparse sources first so richer daily-report rows win MERGE updates
    for f in pick("devin-cloud-session-baseline-*.json"):
        rows += rows_from_baseline(f, input_dir)
    for f in pick("devin-daily-usage-*.json"):
        rows += rows_from_daily_usage(f, input_dir, meta_dir,
                                      sessions_db, include_cli)
    for f in pick("devin-usage-console-*.json"):
        rows += rows_from_console_capture(f, input_dir)
    for f in pick(eval_glob):
        rows += rows_from_eval_verdicts(f, input_dir)
    return rows


def apply_rows(rows: list[tuple[str, dict]], *, dry_run: bool,
               limit: int) -> dict:
    counts: dict[str, int] = {}
    written: dict[str, int] = {}
    capped: list[str] = []
    for table, row in rows:
        counts[table] = counts.get(table, 0) + 1
    # per-table cap
    seen: dict[str, int] = {}
    for table, row in rows:
        if dry_run:
            key = {k: row.get(k) for k in SCHEMAS[table]["key"]}
            print(json.dumps({"table": table, "key": key, "row": row},
                             default=str))
            written[table] = written.get(table, 0) + 1
            continue
        if seen.get(table, 0) >= limit:
            capped.append(table)
            continue
        sql, params = merge_row(table, row)
        resp = bq_query(sql, params)
        if resp.get("errors"):
            raise RuntimeError(f"MERGE {table} failed: {resp['errors']}")
        seen[table] = seen.get(table, 0) + 1
        written[table] = written.get(table, 0) + 1
    if capped:
        print(f"note: per-table limit {limit} reached for "
              f"{sorted(set(capped))}", file=sys.stderr)
    return {"candidates": counts, "written": written}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print typed rows + target table; write nothing")
    ap.add_argument("--backfill", action="store_true",
                    help="load from ALL matching artifacts")
    ap.add_argument("--daily", action="store_true",
                    help="load from the NEWEST artifact of each kind")
    ap.add_argument("--with-cli", action="store_true",
                    help="also ingest local_cli interactive sessions "
                         "(needs --sessions-db for started_at)")
    ap.add_argument("--limit", type=int, default=1000,
                    help="max rows per table per run (default 1000)")
    ap.add_argument("--input-dir", default=None,
                    help="artifact directory (default: <repo>/infra)")
    ap.add_argument("--task-meta-dir", default=str(
        Path.home() / ".local/share/devin-dispatch/tasks"),
        help="dispatch task dir for meta.json enrichment")
    ap.add_argument("--sessions-db", default=str(
        Path.home() / ".local/share/devin/cli/sessions.db"),
        help="Devin CLI sessions.db for cli-session timestamps")
    ap.add_argument("--eval-glob", default="**/*verdict*.json*",
                    help="glob (under input-dir) for eval verdict artifacts")
    args = ap.parse_args()

    if not (args.dry_run or args.backfill or args.daily):
        args.dry_run = True

    input_dir = Path(args.input_dir).expanduser() if args.input_dir \
        else (DEFAULT_INPUT_DIR if DEFAULT_INPUT_DIR.is_dir()
              else Path.cwd() / "infra")
    meta_dir = Path(args.task_meta_dir).expanduser()
    if not meta_dir.is_dir():
        meta_dir = None
    sessions_db = Path(args.sessions_db).expanduser()
    include_cli = args.with_cli or bool(args.daily)

    rows = collect_rows(
        input_dir, daily=bool(args.daily), include_cli=include_cli,
        meta_dir=meta_dir, sessions_db=sessions_db, eval_glob=args.eval_glob)

    result = apply_rows(rows, dry_run=args.dry_run, limit=args.limit)
    summary = {
        "ok": True, "dry_run": args.dry_run, "daily": args.daily,
        "input_dir": str(input_dir), "project": PROJECT,
        "dataset": DATASET, **result,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
