#!/usr/bin/env bash
# promote-michael.sh — promote the card lane: mn-ha-dev (mn01) -> michael-ha.
#
# Thin wrapper over promote-lane.sh; see that script for the full option list.
# Default scope: dashboards,bundle (pfg3d-card + tony-test views).
#
# NOTE (2026-10-10): this is now a wrapper — the standalone script predated
# the --confirm release gate and carried stale defaults (tony-dell dev host,
# sunsynk-power-flow-card-fork base). promote-lane.sh reads the live registry
# (ssot.home-assistant.lanes.yml): mn-ha-dev is on mn01 since the
# 2026-11-25 migration (idc03 2026-10-09 -> idc02 2026-10-26 -> mn01 2026-11-25), bundle base is pfg3d-card.
#
# Examples:
#   promote-michael.sh --dry-run
#   promote-michael.sh --views g1,g2,tpl --confirm
#   promote-michael.sh --rollback --confirm
exec "$(dirname -- "${BASH_SOURCE[0]}")/promote-lane.sh" michael "$@"
