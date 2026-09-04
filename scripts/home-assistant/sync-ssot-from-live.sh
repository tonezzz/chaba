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
RESOURCES_REMOTE=${DEV_CONFIG}/.storage/lovelace_resources

ACTIVE_URL=$(ssh "${HOST}" "cat ${RESOURCES_REMOTE}" | python3 -c "import sys,json; d=json.load(sys.stdin); items=[i for i in d.get('data',{}).get('items',[]) if 'sunsynk-power-flow-card-fork' in i.get('url','')]; print(items[0]['url'] if items else '')" || true)
ACTIVE_VERSION=""
if [[ -n "${ACTIVE_URL}" ]]; then
    ACTIVE_VERSION=$(python3 -c "import re,sys; m=re.search(r'sunsynk-power-flow-card-fork-v(\d+)\.js', sys.argv[1]); print(m.group(1) if m else '')" "${ACTIVE_URL}")
fi

LATEST_BUNDLE=$(ssh "${HOST}" "ls -1 ${WWW_REMOTE}/sunsynk-power-flow-card-fork-v*.js 2>/dev/null | sort -V | tail -n1" || true)
LATEST_VERSION=""
if [[ -n "${LATEST_BUNDLE}" ]]; then
    LATEST_VERSION=$(basename "${LATEST_BUNDLE}" .js | sed 's/sunsynk-power-flow-card-fork-v//')
fi

if [[ -n "${ACTIVE_VERSION}" ]]; then
    VERSION="${ACTIVE_VERSION}"
    if [[ -n "${LATEST_VERSION}" && "${ACTIVE_VERSION}" != "${LATEST_VERSION}" ]]; then
        echo " -> warning: active resource v${ACTIVE_VERSION} differs from newest www bundle v${LATEST_VERSION}"
        echo "              (check lovelace_resources and www/ for drift)"
    fi
    if ! ssh "${HOST}" "test -f ${WWW_REMOTE}/sunsynk-power-flow-card-fork-v${VERSION}.js"; then
        echo " -> error: active resource points to missing bundle v${VERSION} in ${WWW_REMOTE}"
        exit 1
    fi
    echo " -> active bundle version: ${VERSION}"
elif [[ -n "${LATEST_VERSION}" ]]; then
    VERSION="${LATEST_VERSION}"
    echo " -> warning: no active sunsynk resource found; falling back to newest www bundle v${VERSION}"
else
    VERSION=""
fi

if [[ -n "${VERSION}" ]]; then
    python3 - <<PY
import re
with open("${CARDS_SSOT}", "r") as f:
    text = f.read()
text = re.sub(r"^((?:[ \t]*).bundle_version:)[ \t]*\d+.*$", r"\1 ${VERSION}", text, flags=re.MULTILINE)
text = re.sub(r"(sunsynk-power-flow-card-fork-)v\d+(\.js)", r"\1v${VERSION}\2", text)
with open("${CARDS_SSOT}", "w") as f:
    f.write(text)
PY
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
