#!/usr/bin/env python3
"""daily-ledger.py — LiteLLM spend ledger → CMS.

Pulls per-model/per-key spend for the trailing 24h and publishes the
`llm-gateway-spend-ledger` page into ada-cms-pages (same MDDB pattern as
embed-bench). Runs on idc03 where podman can read the spend DB directly;
falls back to the admin HTTP API when given LITELLM_MASTER_KEY.

    python3 scripts/litellm/daily-ledger.py            # json to stdout
    python3 scripts/litellm/daily-ledger.py --publish  # + CMS page
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

GW = os.environ.get("LITELLM_URL", "http://100.102.134.91:4000").rstrip("/")
MASTER = os.environ.get("LITELLM_MASTER_KEY", "")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023/v1")
PAGE_KEY = "llm-gateway-spend-ledger"

SQL = """
SELECT coalesce(api_key,'<master>') AS key_alias, model,
       count(*) AS calls, round(sum(spend)::numeric, 6) AS spend_usd,
       sum(total_tokens) AS tokens
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= now() - interval '24 hours'
GROUP BY 1,2 ORDER BY spend_usd DESC;
"""


def spend_via_psql():
    out = subprocess.run(
        ["podman", "exec", "litellm-db", "psql", "-U", "litellm", "-d", "litellm",
         "-At", "-F", "|", "-c", SQL],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    rows = []
    for line in out.stdout.strip().splitlines():
        key, model, calls, spend, toks = (line.split("|") + ["0"] * 5)[:5]
        rows.append({"key": key[:16] + "…", "model": model, "calls": int(calls or 0),
                     "spend_usd": float(spend or 0), "tokens": int(toks or 0)})
    return rows


def spend_via_api():
    req = urllib.request.Request(
        f"{GW}/global/spend/report?start_date={time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))}"
        f"&end_date={time.strftime('%Y-%m-%d', time.gmtime())}",
        headers={"Authorization": f"Bearer {MASTER}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    rows = []
    for grp in (data or []):
        meta = grp.get("metadata") or {}
        rows.append({"key": meta.get("api_key", "?")[:16] + "…",
                     "model": grp.get("model", "?"),
                     "calls": int(meta.get("api_calls", 0)),
                     "spend_usd": float(grp.get("spend", 0)),
                     "tokens": int(meta.get("total_tokens", 0))})
    return rows


def main():
    rows, source = None, None
    try:
        rows, source = spend_via_psql(), "postgres:LiteLLM_SpendLogs"
    except Exception as e:
        if not MASTER:
            sys.exit(f"psql failed ({e}) and no LITELLM_MASTER_KEY for API fallback")
        rows, source = spend_via_api(), "admin:/global/spend/report"

    total = round(sum(r["spend_usd"] for r in rows), 6)
    rep = {"run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "window": "24h", "source": source,
           "total_usd": total, "rows": rows}
    print(json.dumps(rep, indent=2))

    if "--publish" in sys.argv:
        body_rows = "\n".join(
            f"| {r['key']} | {r['model']} | {r['calls']} | {r['tokens']} | ${r['spend_usd']} |"
            for r in rows) or "| – | – | 0 | 0 | $0 |"
        body = f"""# LLM Gateway Spend Ledger

{rep['run']} — trailing 24h, source `{source}`.
Gateway: `http://100.102.134.91:4000` (idc03, tailnet-only). Admin UI: `/ui`.

**Total 24h spend: ${total}**

| key | model | calls | tokens | spend |
|---|---|---|---|---|
{body_rows}

Caps: proxy $50/30d; ada $10/30d; chaba $5/30d; bench $2/30d.
Routing: docs/ssot/infrastructure/ssot.llm-gateway.yml
"""
        req = urllib.request.Request(f"{MDDB}/add",
            data=json.dumps({
                "collection": "ada-cms-pages", "key": PAGE_KEY, "lang": "en",
                "contentMd": body,
                "meta": {"kind": ["page"], "slug": [PAGE_KEY],
                         "title": ["LLM Gateway Spend Ledger"], "format": ["markdown"],
                         "updated": [rep["run"]], "instance": ["idc03"]}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print(f"published → ada-cms-pages/{PAGE_KEY}")


if __name__ == "__main__":
    main()
