#!/usr/bin/env bash
# verify.sh — full offline check suite for the disposable Jack stack.
# Exercises: unit tests -> mock deploy -> healthcheck -> failure
# injection -> recovery -> rollback. Exits non-zero on any failure.
set -u
cd "$(dirname "$0")"
fail=0
step() { echo; echo "=== $1 ==="; }

step "1/6 unit tests"
if python3 -m unittest discover -s tests -v; then
  echo "unit tests: PASS"
else
  echo "unit tests: FAIL"; fail=1
fi

step "2/6 mock deploy"
./rollback.sh >/dev/null 2>&1 || true   # ensure clean slate
python3 mock/mock_stack.py 0 >mock/mock.log 2>&1 &
MOCK_PID=$!
for i in $(seq 1 30); do
  [ -f mock/.env.mock ] && break; sleep 0.2
done
if [ ! -f mock/.env.mock ]; then
  echo "mock deploy: FAIL (no .env.mock)"; cat mock/mock.log; fail=1
else
  echo "mock deploy: PASS (pid $MOCK_PID)"
fi

step "3/6 healthcheck (healthy)"
set -a; . ./mock/.env.mock; set +a
if ./healthcheck.sh; then
  echo "healthcheck healthy: PASS"
else
  echo "healthcheck healthy: FAIL"; fail=1
fi

step "4/6 failure injection"
PORT="${JACK_MOCK_PORT:-$(python3 -c 'import json;print(json.load(open("mock/state.json"))["port"])')}"
curl -fsS -m 5 -X POST "http://127.0.0.1:$PORT/mock/fail" >/dev/null
if ./healthcheck.sh >/tmp/jack-hc-fail.log 2>&1; then
  echo "failure injection: FAIL (healthcheck passed while backend down)"
  fail=1
else
  echo "failure injection: PASS (healthcheck correctly failed)"
fi

step "5/6 recovery"
curl -fsS -m 5 -X POST "http://127.0.0.1:$PORT/mock/ok" >/dev/null
if ./healthcheck.sh >/dev/null 2>&1; then
  echo "recovery: PASS"
else
  echo "recovery: FAIL"; fail=1
fi

step "6/6 rollback drill"
./rollback.sh
if [ -f mock/state.json ]; then
  echo "rollback: FAIL (state file remains)"; fail=1
else
  echo "rollback: PASS (clean state)"
fi
# post-rollback healthcheck must fail — nothing should be listening
if ./healthcheck.sh >/dev/null 2>&1; then
  echo "post-rollback: FAIL (stack still healthy after rollback)"
  fail=1
else
  echo "post-rollback: PASS (stack down as expected)"
fi

step "result"
if [ "$fail" -eq 0 ]; then
  echo "verify.sh: ALL CHECKS PASSED"
  exit 0
else
  echo "verify.sh: FAILURES PRESENT"
  exit 1
fi
