#!/usr/bin/env bash
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
HOST=tony-dell
DEV_CONFIG=/home/tony/.config/michael-dev
STORAGE_REMOTE=${DEV_CONFIG}/.storage/lovelace.tony_test
WWW_REMOTE=${DEV_CONFIG}/www

DASHBOARD_LOCAL=${REPO}/docs/home-assistant/dashboards/tony-test-current.json

CARDS_SSOT=${REPO}/docs/ssot/infrastructure/ssot.home-assistant.cards.yml
DASHBOARDS_SSOT=${REPO}/docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml
ENTITIES_SSOT=${REPO}/docs/ssot/infrastructure/ssot.home-assistant.entities.yml

TODAY=$(date +%Y-%m-%d)

echo "Syncing live Lovelace snapshot from ${HOST}..."
mkdir -p "$(dirname "${DASHBOARD_LOCAL}")"
ssh "${HOST}" "cat ${STORAGE_REMOTE}" > "${DASHBOARD_LOCAL}"
echo " -> ${DASHBOARD_LOCAL}"

echo "Determining active card bundle version..."
LATEST_BUNDLE=$(ssh "${HOST}" "ls -1 ${WWW_REMOTE}/sunsynk-power-flow-card-fork-v*.js 2>/dev/null | sort -V | tail -n1" || true)
if [[ -n "${LATEST_BUNDLE}" ]]; then
    VERSION=$(basename "${LATEST_BUNDLE}" .js | sed 's/sunsynk-power-flow-card-fork-v//')
    echo " -> active bundle version: ${VERSION}"
    sed -i "s/^  bundle_version: .*/  bundle_version: ${VERSION}/" "${CARDS_SSOT}"
    sed -i "s|^    deployed_as: .*|    deployed_as: /local/sunsynk-power-flow-card-fork-v${VERSION}.js|" "${CARDS_SSOT}"
else
    echo " -> no bundle found on remote; leaving version unchanged"
fi

echo "Updating last_verified dates..."
for f in "${CARDS_SSOT}" "${DASHBOARDS_SSOT}" "${ENTITIES_SSOT}"; do
    if [[ -f "${f}" ]]; then
        sed -i "s/^  last_verified: '.*'/  last_verified: '${TODAY}'/" "${f}"
    fi
done

echo "Running SSOT validators..."
(
    cd "${REPO}"
    node scripts/ssot-validate-all.mjs \
        docs/ssot/infrastructure/ssot.home-assistant.cards.yml \
        docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml \
        docs/ssot/infrastructure/ssot.home-assistant.entities.yml \
        docs/ssot/infrastructure/ssot.home-assistant.howto.yml \
        docs/ssot/infrastructure/ssot.home-assistant.design.yml \
        docs/ssot/infrastructure/ssot.home-assistant.yml \
        docs/ssot/infrastructure/ssot.home-assistant.michael.dev.yml >/dev/null
    python3 scripts/ssot-validate-refs.py >/dev/null
)

echo
echo "Done. Review changes with:"
echo "  git diff --stat"
