#!/usr/bin/env bash
# kanban-commit — persist live board edits (board-api/kanban-dispatch writes)
# into git from the served checkout. Runs from kanban-commit.timer every 15 min.
# Scoped `git add` — never touches other sessions' dirty files.
#
# Guards (card kanban-commit-conflict-marker-guard, incident 2026-10-05):
# a failed `pull --rebase` below leaves the repo mid-rebase with <<<<<<< /
# ======= / >>>>>>> in card files; the next tick used to stage+commit them,
# and the poisoned YAML then killed render-board + kanban-dispatch on parse.
# Now: refuse to commit while a rebase/merge/cherry-pick is in progress, and
# refuse when `git diff --cached --check` reports leftover conflict markers.
# On refuse: log the files to the journal (stderr) and upsert a review-column
# ops card so the skip is visible on the board — this class is silent
# otherwise.
set -uo pipefail
REPO="${KANBAN_REPO:-$HOME/CascadeProjects/chaba-tony-dell}"
cd "$REPO" || exit 1

ALERT_CARD_ID="ops-kanban-commit-guard"

alert_card() {
    # $1 = reason slug, $2 = detail line. Upserts the alert card under the
    # board write flock (direct card-YAML edits must hold it — board-api.py
    # docstring). Dedup: same note while open just bumps `updated`, so a
    # persistent poison doesn't spam comms every 15 min; a changed reason or
    # a re-hit after close appends comms and re-opens (column -> review).
    BAD_REASON="$1" BAD_NOTE="$2" python3 - "$REPO" "$ALERT_CARD_ID" <<'PY'
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

repo, cid = Path(sys.argv[1]), sys.argv[2]
reason, note = os.environ["BAD_REASON"], os.environ["BAD_NOTE"]
card_path = repo / "docs/ssot/kanban/cards" / f"{cid}.yml"
now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
try:
    with open("/tmp/board-api.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        card = yaml.safe_load(card_path.read_text()) \
            if card_path.exists() else {}
        if not isinstance(card, dict):
            card = {}
        comms = card.setdefault("comms", [])
        if card.get("column") == "done" or card.get("note") != note[:500]:
            comms.append({"at": now, "from": "chaba",
                          "text": f"commit refused ({reason}): {note}"[:500]})
        card.update(id=cid,
                    title="kanban-commit blocked: unsafe staged state",
                    column="review", note=note[:500], updated=now)
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(yaml.safe_dump(
            card, allow_unicode=True, sort_keys=False, width=110))
    render = repo / "scripts/render-board.py"
    if render.exists():
        # Tolerate failure — while a poisoned card exists the renderer
        # dies on yaml.safe_load; the alert still lands on the next
        # healthy render.
        subprocess.run([sys.executable, str(render)], cwd=repo,
                       check=False, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception as e:  # alerting must never crash the commit loop
    print(f"kanban-commit: alert card write failed: {e}", file=sys.stderr)
PY
}

gitdir=$(git rev-parse --git-dir)
if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] || \
   [ -f "$gitdir/MERGE_HEAD" ] || [ -f "$gitdir/CHERRY_PICK_HEAD" ]; then
    echo "kanban-commit: REFUSING to commit — rebase/merge/cherry-pick in progress ($gitdir)" >&2
    alert_card "rebase-in-progress" \
        "rebase/merge/cherry-pick in progress in $REPO — kanban-commit holding until resolved"
    exit 1
fi

git add docs/ssot/kanban/ stacks/web/public/apps/board/ 2>/dev/null
git diff --cached --quiet && exit 0   # nothing staged

check=$(git diff --cached --check)
if printf '%s\n' "$check" | grep -q 'conflict marker'; then
    hits=$(printf '%s\n' "$check" | grep 'conflict marker')
    echo "kanban-commit: REFUSING to commit — conflict markers staged:" >&2
    printf '%s\n' "$hits" >&2
    files=$(printf '%s\n' "$hits" | cut -d: -f1 | sort -u | paste -sd, -)
    alert_card "conflict-markers" "conflict markers staged in: $files"
    exit 1
fi

git -c user.name="kanban-bot" -c user.email="kanban-bot@chaba.local" \
    commit -m "board: live card updates ($(date '+%F %H:%M'))" >/dev/null || exit 1

git pull --rebase --autostash >/dev/null 2>&1 || true
git push origin master 2>&1 | tail -2
