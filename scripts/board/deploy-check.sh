#!/usr/bin/env bash
# deploy-check — verify a board static UI change made it all the way to users.
#
# Checks, in order: source committed locally; canonical writer on idc03 has
# the change in its generated index.html; served root (idc02) byte-matches
# canonical; live HTTP page serves the same bytes; no stale nested copy.
#
# Wired as an ignored-failure ExecStartPost on web-srv-sync.service: a
# mismatch writes a warning to the journal but does not fail the sync.
# Exit 0 = all checks passed, 1 = at least one failed.
set -uo pipefail

REPO=/home/tony/CascadeProjects/chaba
SERVED=/home/tony/web-srv/public/apps/board2
CANON_HOST="${DEPLOY_CHECK_HOST:-idc03}"
CANON_REMOTE='~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/board2'
MARKER="${DEPLOY_CHECK_MARKER:-Card cycle control}"
fail=0

pass() { echo "deploy-check: OK   $1"; }
bad()  { echo "deploy-check: FAIL $1" >&2; fail=1; }

# 1. source committed (HEAD, not just the working tree)
src_hits=$(git -C "$REPO" show HEAD:scripts/render-board2.py 2>/dev/null | grep -cF "$MARKER")
if [ "${src_hits:-0}" -gt 0 ] 2>/dev/null; then
  pass "source committed in $(git -C "$REPO" rev-parse --short HEAD)"
else
  bad "renderer in local HEAD lacks marker '$MARKER' — commit before deploying"
fi

# 2. canonical generated artifact on the writer
remote=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$CANON_HOST" \
  "f=$CANON_REMOTE/index.html; printf '%s %s' \"\$(sha256sum \"\$f\" | cut -d' ' -f1)\" \"\$(grep -cF \"$MARKER\" \"\$f\")\"" 2>/dev/null)
remote_hash=${remote%% *}
remote_hits=${remote##* }
if [ "$remote_hits" -gt 0 ] 2>/dev/null; then
  pass "idc03 generated artifact contains marker ($remote_hits hits)"
else
  bad "idc03 generated artifact missing marker — run chaba-repo-sync + chaba-board-render"
fi

# 3. served tree matches canonical
local_hash=$(sha256sum "$SERVED/index.html" 2>/dev/null | cut -d' ' -f1)
if [ -n "$remote_hash" ] && [ "$local_hash" = "$remote_hash" ]; then
  pass "served index.html byte-matches idc03 ($local_hash)"
else
  bad "served index.html != idc03 (local=${local_hash:-none}, canon=${remote_hash:-none}) — run web-srv-sync"
fi

# 4. live HTTP serves the same bytes
http_hash=$(curl -fsS -m 10 http://127.0.0.1:8088/apps/board2/index.html 2>/dev/null | sha256sum | cut -d' ' -f1)
if [ "$http_hash" = "$local_hash" ] && [ -n "$http_hash" ]; then
  pass "live :8088 serves the same index.html"
else
  bad "live :8088 serves different bytes (http=${http_hash:-none}) — check Caddy/mirror"
fi

# 5. stale nested copy from an old ad-hoc deploy
if [ -d "$SERVED/board2" ]; then
  echo "deploy-check: WARN stale nested $SERVED/board2 — remove from idc03 canonical tree" >&2
else
  pass "no stale nested board2/ copy"
fi

exit "$fail"
