#!/usr/bin/env bash
# promote-tony.sh — promote the household lane: tony-dev -> tony-ha.
#
# Thin wrapper over promote-lane.sh; see that script for the full option list.
# Default scope: dashboards,bundle (card fork + tony-test views).
#
# Until tony-dev is provisioned (card ha-dev-instances), source the old lane:
#   promote-tony.sh --from michael-dev [--views tpl,pfg2] --confirm
#
# Examples:
#   promote-tony.sh --dry-run
#   promote-tony.sh --scope bundle --confirm
#   promote-tony.sh --rollback --confirm
exec "$(dirname -- "${BASH_SOURCE[0]}")/promote-lane.sh" tony "$@"
