#!/usr/bin/env bash
# run_arm.sh <arm> — execute one eval arm with timing + log capture.
# Usage: run_arm.sh opencode|cline
# Expects: arms/<arm>/ is a fresh git repo; brief already injected by caller.
set -u
EVAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARM="$1"
ARM_DIR="$EVAL_DIR/arms/$ARM"
RES_DIR="$EVAL_DIR/results/$ARM"
mkdir -p "$RES_DIR"

PROMPT="$(cat "$EVAL_DIR/brief/task-brief.md")"
export LITELLM_KEY_EVAL="${LITELLM_KEY_EVAL:-$LITELLM_KEY_BENCH}"
# Contain agent state inside the worktree but OUTSIDE the arm repo —
# agents run `git add -A`; session dirs must never be committable.
export HOME="$EVAL_DIR/arms/.$ARM.home"
mkdir -p "$HOME"
[ -f "$HOME/.gitconfig" ] || cat > "$HOME/.gitconfig" <<'GITCFG'
[user]
  name = eval-agent
  email = eval-agent@localhost
[init]
  defaultBranch = main
GITCFG
export GIT_AUTHOR_NAME=eval-agent GIT_AUTHOR_EMAIL=eval-agent@localhost
export GIT_COMMITTER_NAME=eval-agent GIT_COMMITTER_EMAIL=eval-agent@localhost

START=$(date +%s)
echo "{\"arm\":\"$ARM\",\"start_epoch\":$START,\"start_iso\":\"$(date -Is)\"}" \
  > "$RES_DIR/run.json"

cd "$ARM_DIR"
case "$ARM" in
  opencode)
    OPENCODE_CONFIG="$EVAL_DIR/harness/opencode.eval.json" \
      timeout 3000 opencode run --format json "$PROMPT" \
      > "$RES_DIR/events.jsonl" 2> "$RES_DIR/stderr.log"
    ;;
  cline)
    CLINE_BIN="$EVAL_DIR/.tools/cline/node_modules/@cline/cli-linux-x64/bin/cline"
    CLINE_DATA="$EVAL_DIR/arms/.cline-data-$ARM"
    mkdir -p "$CLINE_DATA"
    # one-time provider auth into the isolated data dir (no TTY needed)
    "$CLINE_BIN" auth -p openai-native -k "$LITELLM_KEY_EVAL" \
      -m bench -b "http://100.102.134.91:4000/v1" \
      --data-dir "$CLINE_DATA" > "$RES_DIR/auth.log" 2>&1 || {
        echo "cline auth failed"; cat "$RES_DIR/auth.log"; exit 3; }
    timeout 3000 "$CLINE_BIN" --json --data-dir "$CLINE_DATA" \
      -c "$ARM_DIR" "$PROMPT" \
      > "$RES_DIR/events.jsonl" 2> "$RES_DIR/stderr.log"
    ;;
  *) echo "unknown arm $ARM" >&2; exit 2 ;;
esac
RC=$?
END=$(date +%s)
python3 - "$RES_DIR/run.json" "$ARM" "$START" "$END" "$RC" <<'PY'
import json, sys
p, arm, s, e, rc = sys.argv[1:6]
d = json.load(open(p))
d.update({"end_epoch": int(e), "end_iso": __import__("datetime").datetime.now().astimezone().isoformat(),
          "wall_seconds": int(e) - int(s), "exit_code": int(rc)})
json.dump(d, open(p, "w"), indent=2)
PY
echo "arm $ARM finished rc=$RC wall=$((END-START))s"
exit $RC
