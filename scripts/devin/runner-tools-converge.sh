#!/usr/bin/env bash
# runner-tools-converge — converge pinned runner tools, locally by default.
#
# Called by runner-tools-converge.timer (user scope, every 2h since
# 2026-11-27) on each managed host, or manually from any controller with the
# chaba checkout + ansible installed. Hosts with an active devin-task-* unit
# are excluded from the apply so a restart cannot kill a live dispatch.
#
# Two scopes (OPS-1478 / card runner-tools-converge-local-scope-fix):
#
#   local — every host running the timer converges ONLY itself
#     (deploy/audit --limit <inventory_hostname>). The original version ran
#     the playbooks fleet-wide FROM EVERY HOST: hosts without
#     ansible-playbook on PATH (idc03, mn01, tony-omen, con01) exited 1,
#     and hosts with it (tony-dell, idc02, tony-macbook) failed --check
#     whenever a fleet host was asleep — five false timer-alert cards on
#     2026-11-27 despite every installed hash matching the pin.
#
#   fleet — only the ansible controller (tony-dell; override with
#     RUNNER_CONVERGE_FLEET=1 for a manual run from another ansible host)
#     additionally converges every REACHABLE managed host, so ansible-less
#     hosts still get drift repaired nightly. Reachability is probed with
#     `ansible -m ping` first — an off-net portable host is skipped, not
#     failed. This is the fleet-wide check the card keeps on tony-dell;
#     the read-only drift view also lives in the ansible-runner-tool-guard
#     job (verify-runner-tools-sync.yml, 07:10 on tony-dell).
#
# Hosts without ansible-playbook exit 0 with a skip note (documented):
# their tools are still converged by sync-runner-tools.sh on every
# repo-sync tick and by the controller's fleet pass above.
set -uo pipefail

say() { echo "runner-tools-converge: $*"; }

# ~/.local/bin first: ansible-playbook lives there on tony-dell, and a
# minimal systemd PATH may not include it even when ansible is installed.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v ansible-playbook >/dev/null 2>&1; then
  say "SKIP: ansible-playbook not on PATH — local converge needs ansible; the fleet pass runs on tony-dell (exit 0)"
  exit 0
fi
if ! command -v ansible >/dev/null 2>&1 || ! command -v ansible-inventory >/dev/null 2>&1; then
  say "FAIL: ansible-playbook present but ansible/ansible-inventory missing — broken ansible install"
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Tests and manual dry-runs can point at a scratch checkout; production
# always derives ROOT from this script's location.
ROOT="${RUNNER_CONVERGE_ROOT:-$ROOT}"
ANS="$ROOT/ansible"
WORK="${TMPDIR:-/tmp}/runner-converge-$$"
mkdir -p "$WORK" || exit 1
trap 'rm -rf "$WORK"' EXIT

cd "$ANS" || exit 1

# The timer is shared across hosts, so scope every playbook call to the
# inventory host matching this machine's hostname (verified == inventory
# name on all managed hosts). Fail loudly if the name is unknown — a
# silent no-op would hide a real provisioning gap.
LOCAL_HOST="$(hostname -s 2>/dev/null || hostname)"
LOCAL_HOST="${LOCAL_HOST%%.*}"
if ! ansible-inventory --host "$LOCAL_HOST" >/dev/null 2>&1; then
  say "FAIL: hostname '$LOCAL_HOST' is not in the ansible inventory — cannot scope convergence to self"
  exit 1
fi

# A pinned tool must never be deployed from a dirty checkout: copy would
# install bytes that the post-copy hash assert cannot accept, leaving the
# installed tool drifted while the timer reports exit-code only. Verify every
# manifest source against its pin BEFORE running check/apply, and skip loudly
# with the offending path list. Check mode cannot catch this because the
# assert task is deliberately skipped under --check.
checkout_sources_clean() {
  python3 - "$ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest_path = root / "scripts" / "devin" / "runner-tooling.manifest.json"
try:
    manifest = json.loads(manifest_path.read_text())
except Exception as exc:
    print(f"cannot read {manifest_path}: {exc}")
    sys.exit(2)

dirty = []
for item in (manifest.get("tools") or {}).values():
    src = root / item["source"]
    if not src.is_file():
        dirty.append(f"{item['source']} (missing)")
        continue
    actual = hashlib.sha256(src.read_bytes()).hexdigest()
    if actual != item["sha256"]:
        dirty.append(
            f"{item['source']} (checkout {actual[:12]} != pin {item['sha256'][:12]})")
if dirty:
    print("DIRTY_PINNED_SOURCES=" + "|".join(dirty))
    sys.exit(1)
print("PINNED_SOURCES_OK")
PY
}

# Never restart runner-agent underneath a live dispatch: a drift apply fires
# the restart handler in deploy-runner-tools.yml, which would kill an in-flight
# devin-task-* unit on that host. Self is checked locally; remote hosts over
# tailnet SSH. An SSH failure is treated as no active unit — reachability is
# handled by the fleet pass's ansible ping.
host_has_active_dispatch() {
  local h="$1"
  if [ "$h" = "$LOCAL_HOST" ]; then
    systemctl --user list-units --type=service --state=active --no-pager 2>/dev/null \
      | grep -q 'devin-task-'
  else
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$h" \
      'systemctl --user list-units --type=service --state=active --no-pager 2>/dev/null | grep -q "devin-task-"' \
      >/dev/null 2>&1
  fi
}

# check -> apply -> audit -> board re-arm -> re-audit, scoped by --limit.
converge() {
  local limit="$1" tag="$2"

  local source_check
  source_check="$(checkout_sources_clean 2>&1)" || {
    say "$tag: $source_check"
    say "$tag: skip this pass — refusing to deploy unpinned sources from $ROOT"
    return 0
  }
  say "$tag: $source_check"

  local -a targets=() busy=()
  IFS=: read -ra targets <<< "$limit"
  for h in "${targets[@]}"; do
    host_has_active_dispatch "$h" && busy+=("$h")
  done
  if [ "${#busy[@]}" -gt 0 ]; then
    say "$tag: active dispatch on ${busy[*]} — excluding from apply to avoid restarting runner-agent mid-task"
    if [ "${#busy[@]}" -eq "${#targets[@]}" ]; then
      say "$tag: all targets busy — skip this pass"
      return 0
    fi
    for h in "${busy[@]}"; do limit="$limit:!$h"; done
  fi

  say "$tag ($limit): check mode"
  ansible-playbook playbooks/deploy-runner-tools.yml --check --diff --limit "$limit" \
    > "$WORK/$tag-check.txt" 2>&1 || {
      say "$tag: check failed — see $WORK/$tag-check.txt"; return 1; }

  say "$tag ($limit): apply"
  ansible-playbook playbooks/deploy-runner-tools.yml --limit "$limit" \
    > "$WORK/$tag-apply.txt" 2>&1 || {
      say "$tag: apply failed — see $WORK/$tag-apply.txt"; return 1; }

  say "$tag ($limit): audit"
  ansible-playbook playbooks/audit-runner-tools.yml --limit "$limit" \
    > "$WORK/$tag-audit.txt" 2>&1 || true
  python3 "$ROOT/scripts/board/runner-drift-rearm.py" \
    --audit-file "$WORK/$tag-audit.txt" || true

  say "$tag ($limit): re-audit"
  ansible-playbook playbooks/audit-runner-tools.yml --limit "$limit" \
    > "$WORK/$tag-after.txt" 2>&1 || true
  python3 "$ROOT/scripts/board/runner-drift-rearm.py" \
    --audit-file "$WORK/$tag-after.txt" --verify || true
}

rc=0
converge "$LOCAL_HOST" local || rc=1

# Fleet pass — controller only, and only for hosts that answer ansible
# ping right now. Self is excluded (the local pass just covered it).
if [ "$LOCAL_HOST" = "tony-dell" ] || [ "${RUNNER_CONVERGE_FLEET:-0}" = "1" ]; then
  reachable="$(ANSIBLE_BECOME=false ansible 'all:!macos:!disabled' -m ping \
    2>"$WORK/ping.err" | awk '/ \| SUCCESS/{print $1}' | sort -u)"
  fleet_hosts="$(printf '%s\n' "$reachable" | grep -v '^$' | grep -vx "$LOCAL_HOST" | paste -sd: -)"
  if [ -z "$fleet_hosts" ]; then
    say "fleet: no other reachable managed hosts — see $WORK/ping.err if unexpected"
  else
    say "fleet: reachable hosts: $fleet_hosts"
    converge "$fleet_hosts" fleet || rc=1
  fi
fi

say "done (rc=$rc)"
exit "$rc"
