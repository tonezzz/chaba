#!/usr/bin/env bash
# Probe the merged proxy: ring failover, budgets, gateway leg.
set -u
cd "$(dirname "$0")"
MOCK=18999
PROXY=18998
export MOCK_PORT=$MOCK
node mock-upstream.mjs & MOCKPID=$!
sleep 0.5

run_proxy() { # env already exported by caller
  GEMINI_PROXY_PORT=$PROXY GEMINI_PROXY_HOST=127.0.0.1 \
    MDDB_OPS_URL=http://127.0.0.1:1 GEMINI_API_BASE=http://127.0.0.1:$MOCK \
    GEMINI_PROXY_MAX_RETRIES=1 FREE_GEMINI_CIRCUIT_MS=60000 \
    node ../../scripts/mddb/gemini-ollama-proxy.mjs & PROXYPID=$!
  sleep 0.7
}
embed() { curl -s -m 15 -X POST http://127.0.0.1:$PROXY/api/embed \
  -H 'Content-Type: application/json' ${1:+-H "x-embed-lane: $1"} \
  -d '{"input":["hello world"]}'; }
health() { curl -s http://127.0.0.1:$PROXY/health; }

echo "=== T1: ring failover — primary key bad, ring key good ==="
export GEMINI_API_KEY=KEY-bad-AAAA GEMINI_FREE_KEYS_01=KEY-good-BBBB
export GEMINI_API_KEY_PAID= PAID_X= OPENROUTER_API_KEY= EMBED_GATEWAY_BASE= LITELLM_KEY=
unset OPENROUTER_API_KEY EMBED_GATEWAY_BASE LITELLM_KEY GEMINI_API_KEY_PAID GEMINI_FREE_KEYS
run_proxy
embed | python3 -c 'import json,sys; d=json.load(sys.stdin); print("provider:",d.get("provider"),"fb:",d.get("fallback"))'
health | python3 -m json.tool | grep -E "free_keys|free_gemini_open|provider_mode"
kill $PROXYPID 2>/dev/null; wait $PROXYPID 2>/dev/null

echo "=== T2: hourly budget gate -> backup chain (paid serves) ==="
export GEMINI_API_KEY=KEY-good-BBBB GEMINI_API_KEY_PAID=KEY-paid-CCCC
export PAID_GEMINI_HOURLY_CAP=100 PAID_GEMINI_DAILY_CAP=1000
export FREE_GEMINI_HOURLY_BUDGET=1 FREE_GEMINI_BULK_DAILY_BUDGET=0 PAID_GEMINI_BULK_ALLOW=0
unset GEMINI_FREE_KEYS_01
run_proxy
embed | python3 -c 'import json,sys; d=json.load(sys.stdin); print("r1 provider:",d.get("provider"))'
embed | python3 -c 'import json,sys; d=json.load(sys.stdin); print("r2 provider:",d.get("provider"),"fb:",d.get("fallback"))'
embed bulk | python3 -c 'import json,sys; d=json.load(sys.stdin); print("bulk provider:",d.get("provider"),"fb:",d.get("fallback"))'
health | python3 -m json.tool | grep -E "free_calls_hour|free_calls_today|paid_calls"
kill $PROXYPID 2>/dev/null; wait $PROXYPID 2>/dev/null

echo "=== T3: gateway leg — free keys dead, gateway serves ==="
export GEMINI_API_KEY=KEY-bad-AAAA
export OPENROUTER_API_KEY= EMBED_GATEWAY_BASE=http://127.0.0.1:$MOCK EMBED_GATEWAY_MODEL=embedding LITELLM_KEY=sk-test
export FREE_GEMINI_HOURLY_BUDGET=0 PAID_GEMINI_BULK_ALLOW=1
unset GEMINI_API_KEY_PAID PAID_GEMINI_HOURLY_CAP PAID_GEMINI_DAILY_CAP
run_proxy
embed | python3 -c 'import json,sys; d=json.load(sys.stdin); print("provider:",d.get("provider"),"fb:",d.get("fallback"))'
health | python3 -m json.tool | grep -E "embed_gateway|provider_mode|free_keys"
kill $PROXYPID 2>/dev/null; wait $PROXYPID 2>/dev/null
unset GEMINI_API_KEY EMBED_GATEWAY_BASE LITELLM_KEY
kill $MOCKPID 2>/dev/null
