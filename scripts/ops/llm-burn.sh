#!/usr/bin/env bash
# llm-burn — LiteLLM spend rollup straight from the ledger DB on idc03.
#
# Usage:
#   llm-burn.sh [days]      totals per day + per-key/lane/tool breakdown (default 3)
#   llm-burn.sh today       just today, per lane+tool
#   llm-burn.sh keys        virtual-key registry (alias, models, budget)
#
# Lane/tool resolution rides the x-litellm-tags headers gemini_pool emits
# (ada-voice >= 6f98a95) — rows predating that show lane=untagged.
set -euo pipefail
MODE="${1:-3}"
DB="podman exec litellm-db psql -U litellm -d litellm -t -A -F'|'"

if [[ "$MODE" == "keys" ]]; then
  ssh -o BatchMode=yes idc03 "cat > /tmp/_lb.sql <<'SQL'
SELECT key_alias, left(token,10)||'…' AS key, coalesce(max_budget::text,'-') AS budget,
       coalesce(models::text,'{}') AS models, created_at::date
FROM \"LiteLLM_VerificationToken\" ORDER BY key_alias;
SQL
podman cp /tmp/_lb.sql litellm-db:/tmp/_lb.sql >/dev/null && podman exec litellm-db psql -U litellm -d litellm -f /tmp/_lb.sql"
  exit 0
fi

DAYS="$MODE"; [[ "$MODE" == "today" ]] && DAYS=1
ssh -o BatchMode=yes idc03 "cat > /tmp/_lb.sql <<'SQL'
SELECT '== per day (key alias) ==' AS h;
SELECT s.\"startTime\"::date AS day,
       coalesce(v.key_alias, left(s.api_key,10)) AS key_alias,
       s.model_group,
       count(*) AS calls,
       round(sum(s.total_tokens)/1000.0,1) AS tok_k,
       round(sum(s.spend)::numeric,4) AS usd
FROM \"LiteLLM_SpendLogs\" s
LEFT JOIN \"LiteLLM_VerificationToken\" v ON v.token = s.api_key
WHERE s.\"startTime\" > now() - interval '${DAYS} days'
GROUP BY 1,2,3 ORDER BY 1 DESC, 6 DESC;
SELECT '== per day (lane/tool tags) ==' AS h;
SELECT s.\"startTime\"::date AS day, t.tag,
       count(*) AS calls,
       round(sum(s.total_tokens)/1000.0,1) AS tok_k,
       round(sum(s.spend)::numeric,4) AS usd
FROM \"LiteLLM_SpendLogs\" s,
     jsonb_array_elements_text(s.request_tags) t(tag)
WHERE s.\"startTime\" > now() - interval '${DAYS} days'
  AND (t.tag LIKE 'lane=%' OR t.tag LIKE 'tool=%')
GROUP BY 1,2 ORDER BY 1 DESC, 5 DESC;
SQL
podman cp /tmp/_lb.sql litellm-db:/tmp/_lb.sql >/dev/null && podman exec litellm-db psql -U litellm -d litellm -f /tmp/_lb.sql"
