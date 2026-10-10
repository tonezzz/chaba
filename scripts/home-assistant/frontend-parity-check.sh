#!/usr/bin/env bash
# frontend-parity-check.sh — per-lane twin diff between two HA instances.
#
# Usage:
#   frontend-parity-check.sh <lane>      dev<->prod twin diff (tony|ada|michael)
#   frontend-parity-check.sh --from A --to B    ad-hoc instance pair
#   frontend-parity-check.sh             legacy check: michael-ha <-> tony-ha
#
# Options:
#   --scope LIST   comma list: dashboards,resources,bundle,automations,
#                  helpers,users  (default: all)
#   --json         machine-readable report
#
# Compares (per scope): Lovelace dashboards (registry + per-view config),
# resource registrations, www card bundles by md5, automations/scripts/scenes
# (staging-guard artifacts normalized out — see ssot.home-assistant.lanes.yml
# destage policy), helper storage files, and users/groups/logins (never
# credential material).
#
# Exit 0 = parity, 1 = drift, 2 = an instance could not be reached/collected.
# Read-only; safe to run any time. Registry: ssot.home-assistant.lanes.yml.
set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
# shellcheck source=ha-lanes.sh
source "$SCRIPT_DIR/ha-lanes.sh"

FROM=""; TO=""; SCOPE="all"; JSON=0; LANE=""

usage() { sed -n '2,21p' "$0"; exit 0; }
die() { echo "[parity] ERROR: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
	case "$1" in
	--from)   FROM="$2"; shift 2 ;;
	--to)     TO="$2"; shift 2 ;;
	--scope)  SCOPE="$2"; shift 2 ;;
	--json)   JSON=1; shift ;;
	-h|--help) usage ;;
	-*)       die "unknown arg: $1" ;;
	*)
		[ -n "$LANE" ] && die "unexpected extra arg: $1"
		LANE="$1"; shift ;;
	esac
done

# --- resolve the pair --------------------------------------------------------
if [ -n "$LANE" ]; then
	lane_exists "$LANE" || die "unknown lane '$LANE' (see ssot.home-assistant.lanes.yml)"
	FROM=$(lane_field "$LANE" dev); TO=$(lane_field "$LANE" prod)
elif [ -n "$FROM" ] || [ -n "$TO" ]; then
	[ -n "$FROM" ] && [ -n "$TO" ] || die "--from and --to must be given together"
else
	# legacy behaviour: the original script compared tony-ha against
	# michael-ha as the reference instance
	echo "[parity] no lane given — legacy check michael-ha(A) vs tony-ha(B);"
	echo "[parity] prefer: frontend-parity-check.sh <tony|ada|michael>"
	FROM="michael-ha"; TO="tony-ha"; SCOPE="resources,bundle"
fi

inst_exists "$FROM" || die "unknown instance: $FROM"
inst_exists "$TO"   || die "unknown instance: $TO"

for inst in "$FROM" "$TO"; do
	if ! inst_up "$inst"; then
		planned=$(inst_field "$inst" planned 2>/dev/null || echo "")
		if [ "$planned" = "True" ] || [ "$planned" = "true" ]; then
			die "$inst is registered but not provisioned yet (planned twin — card ha-dev-instances)"
		fi
		die "$inst unreachable at $(inst_field "$inst" url)"
	fi
done

# --- collect + diff -----------------------------------------------------------
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
echo "[parity] collecting $FROM ..."
inst_collect "$FROM" "$tmp/A" || die "collection failed on $FROM"
echo "[parity] collecting $TO ..."
inst_collect "$TO" "$tmp/B" || die "collection failed on $TO"

args=("$tmp/A" "$tmp/B" --names "$FROM:$TO" --scope "$SCOPE")
[ "$JSON" -eq 1 ] && args+=(--json)
python3 "$SCRIPT_DIR/ha-twin-diff.py" "${args[@]}"
rc=$?

case $rc in
0) echo "[parity] PARITY OK ($FROM <-> $TO, scope=$SCOPE)" ;;
1) echo "[parity] DRIFT DETECTED ($FROM <-> $TO, scope=$SCOPE)" ;;
*) echo "[parity] diff engine error (rc=$rc)" ;;
esac
exit $rc
