#!/usr/bin/env bash
# runner-tools-converge — check -> apply -> audit -> board re-arm -> re-audit.
# Called by runner-tools-converge.timer (user scope) on each managed host, or
# manually from any controller with the chaba checkout + ansible installed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ANS="$ROOT/ansible"
WORK="${TMPDIR:-/tmp}/runner-converge-$$"
mkdir -p "$WORK" || exit 1
trap 'rm -rf "$WORK"' EXIT

cd "$ANS" || exit 1

echo "runner-tools-converge: check mode"
ansible-playbook playbooks/deploy-runner-tools.yml --check --diff > "$WORK/check.txt" 2>&1 || {
  echo "runner-tools-converge: check failed — see $WORK/check.txt"; exit 1; }

echo "runner-tools-converge: apply"
ansible-playbook playbooks/deploy-runner-tools.yml > "$WORK/apply.txt" 2>&1 || {
  echo "runner-tools-converge: apply failed — see $WORK/apply.txt"; exit 1; }

echo "runner-tools-converge: audit"
ansible-playbook playbooks/audit-runner-tools.yml > "$WORK/audit.txt" 2>&1
python3 "$ROOT/scripts/board/runner-drift-rearm.py" --audit-file "$WORK/audit.txt" || true

echo "runner-tools-converge: re-audit"
ansible-playbook playbooks/audit-runner-tools.yml > "$WORK/after.txt" 2>&1
python3 "$ROOT/scripts/board/runner-drift-rearm.py" --audit-file "$WORK/after.txt" --verify || true

echo "runner-tools-converge: done"
