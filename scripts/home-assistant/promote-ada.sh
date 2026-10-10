#!/usr/bin/env bash
# promote-ada.sh — promote the private lane: ada-dev -> ada-ha.
#
# Thin wrapper over promote-lane.sh; see that script for the full option list.
# Default scope: dashboards (ada lane has no forked card bundle).
#
# Examples:
#   promote-ada.sh --dry-run                                  # plan + parity diff
#   promote-ada.sh --scope dashboards --views chaba-nest --confirm
#   promote-ada.sh --scope helpers --restart --confirm
exec "$(dirname -- "${BASH_SOURCE[0]}")/promote-lane.sh" ada "$@"
