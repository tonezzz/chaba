#!/bin/bash
# kanban-sync — one tick of the kanban <-> CMS loop.
#   1. ff-pull the dedicated worktree to origin/master
#   2. health lanes: cms-auto-health -> cms-auto-* cards,
#      logs-kanban -> logs-auto-* cards, gev-auto-health -> gev-auto-*
#      cards, vcast-auto-health -> vcast-auto-* cards,
#      runner-fleet-health -> runner-auto-* cards
#      (all write files under docs/ssot/kanban/cards/)
#   2b. request-sweep: open requests targeting tony unanswered >12h get
#      ONE batched escalation push (stamps escalated_at, never repeats)
#   3. commit + push ONLY cards/ changes the health checks made
#   4. kanban-cms: render the live board into the dev-kanban CMS page
#
# Runs from a dedicated detached worktree so a busy/dirty main checkout
# (chaba-tony-dell) can never block it. Self-bootstraps the worktree.
# Push races with other sessions just defer to the next tick.
set -u

SRC=$HOME/CascadeProjects/chaba-tony-dell
WT=$HOME/CascadeProjects/chaba-kanban-sync

if [ ! -d "$WT" ]; then
    git -C "$SRC" fetch origin -q || exit 1
    git -C "$SRC" worktree add --detach "$WT" origin/master || exit 1
fi
cd "$WT" || exit 1
git fetch origin -q || { echo "fetch failed"; exit 1; }
if ! git merge --ff-only origin/master; then
    # a raced push leaves the detached HEAD one auto-commit ahead while
    # origin/master moved too — diverged, and ff-only then fails on EVERY
    # tick (kanban-sync wedged 2026-10-07). The local commits are only
    # generated card writes, so replaying them is safe.
    echo "ff-pull failed — rebasing local auto-commits onto origin/master"
    git rebase origin/master || { git rebase --abort 2>/dev/null; echo "rebase failed"; exit 1; }
fi

python3 scripts/ada/cms-auto-health.py || echo "health check failed (non-fatal)"
python3 scripts/ada/logs-kanban.py || echo "logs-kanban failed (non-fatal)"
python3 scripts/ada/gev-auto-health.py || echo "gev-auto-health failed (non-fatal)"
python3 scripts/ada/vcast-auto-health.py || echo "vcast-auto-health failed (non-fatal)"
# dispatch fleet bootstrap audit -> runner-auto-<host> cards (violations only)
python3 scripts/board/runner-fleet-health.py || echo "runner-fleet-health failed (non-fatal)"
# disk-trend: cards land in this worktree (committed below); reports go to
# the served checkout so the detached worktree stays ff-clean.
python3 scripts/ada/disk-trend-watch.py --reports-root "$SRC/reports" \
    || echo "disk-trend-watch failed (non-fatal)"
python3 scripts/board/request-sweep.py || echo "request-sweep failed (non-fatal)"
# release-lifecycle gate check: bounce `release:`-tracked cards in
# review/done that lack the required comms-tag evidence; stamps soak_until
# on first sight in review (the beta soak timer).
python3 scripts/ada/lifecycle-check.py || echo "lifecycle-check failed (non-fatal)"
# L2 'kanban' report node — stats read the live cards in the served
# checkout; outputs mirror back into $SRC (reports/kanban + web data).
python3 scripts/board/kanban-stats.py \
    --cards-dir "$SRC/docs/ssot/kanban/cards" \
    || echo "kanban-stats failed (non-fatal)"

git add docs/ssot/kanban/cards/ 2>/dev/null
if ! git diff --cached --quiet 2>/dev/null; then
    git commit -qm "kanban: cms-auto-health sync $(date -Iseconds)
"
    git push -q origin HEAD:master || echo "push raced — next tick retries"
fi

python3 scripts/ada/kanban-cms.py
