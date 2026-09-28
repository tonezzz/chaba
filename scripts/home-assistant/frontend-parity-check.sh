#!/usr/bin/env bash
# frontend-parity-check.sh — verify tony-ha serves the same Lovelace frontend
# bundles and resource registrations as michael-ha (the reference instance).
#
# Compares:
#   1. md5 of shared frontend files (www/community/* + flat /local/ cards
#      that exist on both hosts — tony-ha-only ada/chaba cards are skipped)
#   2. registered resource URL lists (.storage/lovelace_resources on each)
#
# Exit 0 = parity, 1 = drift detected. Read-only; safe to run any time.
set -uo pipefail

MHA="ssh -o BatchMode=yes -o ConnectTimeout=10 -i $HOME/.ssh/michael-ha michael-ha"
DELL="ssh -o BatchMode=yes -o ConnectTimeout=10 tony-dell"
SHARED=(layout-card.js canvas-gauge-card.js config-template-card.js \
        pro-v-weather-card.js nimbus-weather-card.js)

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "== bundle md5s =="
$MHA 'cd /config/www && md5sum community/lovelace-card-mod/card-mod.js \
      community/apexcharts-card/apexcharts-card.js \
      community/ha-sankey-chart/ha-sankey-chart.js \
      layout-card.js canvas-gauge-card.js config-template-card.js \
      pro-v-weather-card.js nimbus-weather-card.js 2>/dev/null' \
    | awk '{print $2, $1}' | sort > "$tmp/mha.md5" || \
    { echo "FAIL: cannot reach michael-ha"; exit 1; }

$DELL 'cd ~/.config/home-assistant/www && md5sum community/lovelace-card-mod/card-mod.js \
       community/apexcharts-card/apexcharts-card.js \
       community/ha-sankey-chart/ha-sankey-chart.js \
       layout-card.js canvas-gauge-card.js config-template-card.js \
       pro-v-weather-card.js nimbus-weather-card.js 2>/dev/null' \
    | awk '{print $2, $1}' | sort > "$tmp/tha.md5" || \
    { echo "FAIL: cannot reach tony-dell"; exit 1; }

drift=0
diff "$tmp/mha.md5" "$tmp/tha.md5" > "$tmp/md5.diff" || true
if [ -s "$tmp/md5.diff" ]; then
    sed 's/^/  DIFF /' "$tmp/md5.diff"
    drift=1
fi

echo "== registered resources =="
$MHA 'cat /config/.storage/lovelace_resources' > "$tmp/mha.res.json"
$DELL 'cat ~/.config/home-assistant/.storage/lovelace_resources' > "$tmp/tha.res.json"
python3 - "$tmp/mha.res.json" "$tmp/tha.res.json" <<'PY'
import json, re, sys
def urls(p):
    d = json.load(open(p))
    items = d["data"]["items"] if "data" in d else d.get("resources", d)
    return {i["url"].split("?")[0] for i in items}
mha, tha = (urls(a) for a in sys.argv[1:3])
# versioned filenames (pfg3d-card-vNNN.js) skew independently per host —
# normalize the stem for presence, then report version skew separately
norm = lambda u: re.sub(r"-v\d+(\.js)$", r"\1", u)
nmha, ntha = {norm(u) for u in mha}, {norm(u) for u in tha}
shared_missing = sorted(nmha - ntha)
extra_only     = sorted(u for u in ntha - nmha
                        if "chaba" not in u and "ada-" not in u
                        and "vcast" not in u and "youtube" not in u
                        and "album" not in u)
skew = [f"{a} vs {b}" for a in mha for b in tha
        if norm(a) == norm(b) and a != b]
if shared_missing:
    print("  MISSING on tony-ha:"); [print("   -", u) for u in shared_missing]
if extra_only:
    print("  EXTRA on tony-ha (non-chaba):"); [print("   +", u) for u in extra_only]
if skew:
    print("  VERSION SKEW (same card, different pinned bundle):")
    [print("   ~", s) for s in skew]
if not shared_missing and not extra_only and not skew:
    print("  resource sets consistent")
sys.exit(1 if shared_missing else 0)
PY
[ $? -ne 0 ] && drift=1

if [ "$drift" -eq 0 ]; then echo "PARITY OK"; else echo "DRIFT DETECTED"; fi
exit "$drift"
