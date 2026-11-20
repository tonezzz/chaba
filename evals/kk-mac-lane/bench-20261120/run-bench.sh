#!/bin/bash
# KK-Mac bounded lane bench — runs ON tony-dell (trusted ssh hop).
# Each model: unload -> cold call (summary) -> warm call (structured_extract)
# -> unload. The executor contract applies admission + the 60/50 memory
# guard and an independent verifier on every call.
set -u
B=/tmp/kk-bench-20261120
mkdir -p "$B"
cd "$HOME/CascadeProjects/chaba" || exit 1
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 kkkakk@kk-mac"

echo "== pre-state =="
$SSH 'memory_pressure -Q 2>/dev/null | tail -1; ~/.local/bin/smctemp -c 2>/dev/null; sysctl -n vm.loadavg; curl -fsS -m5 http://127.0.0.1:11434/api/ps'

unload() {
  $SSH "curl -fsS -m15 http://127.0.0.1:11434/api/generate -d '{\"model\":\"$1\",\"keep_alive\":0}' >/dev/null 2>&1"
}

run_one() { # model tag class prompt expect
  python3 scripts/devnest/kk_mac_executor.py run \
    --card kk-mac-local-llm-lane --task-id "bench-$2-$1" \
    --task-class "$3" --taskdir "$B/$1-$2" \
    --prompt-file "$B/$4" --expect-file "$B/$5" \
    --model "$1" --host kkkakk@kk-mac \
    > "$B/$1-$2.result.json" 2>"$B/$1-$2.err"
  echo "RC=$? $1/$2 $(python3 -c "import json;d=json.load(open('$B/$1-$2.result.json'));print(d.get('verdict'), d.get('reasons'))" 2>/dev/null || echo parse-err)"
}

for M in qwen3:8b gpt-oss:20b qwen3:30b-a3b; do
  echo "== model $M =="
  unload "$M"; sleep 2
  run_one "$M" cold-sum summary prompt-summary.txt expect-summary.json
  run_one "$M" warm-ext structured_extract prompt-extract.txt expect-extract.json
  unload "$M"
done

echo "== post-state =="
$SSH 'memory_pressure -Q 2>/dev/null | tail -1; ~/.local/bin/smctemp -c 2>/dev/null; sysctl -n vm.loadavg; curl -fsS -m5 http://127.0.0.1:11434/api/ps'
ls -la "$B"
