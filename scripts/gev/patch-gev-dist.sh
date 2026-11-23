#!/usr/bin/env bash
# patch-gev-dist.sh — post-build patcher for the God's Eye View dist.
#
# Run in ~/gods-eye-view after `npm run build`, BEFORE staging dist/* into
# chaba's stacks/web/public/apps/gev/ (or the served dir). This script is
# the codified version of the manual patch list in AGENTS.md §"GEV Gemini
# Live voice deployment" — apply it every build, don't hand-edit.
#
#   ./patch-gev-dist.sh [dist-dir]         default ~/gods-eye-view/dist
#   ./patch-gev-dist.sh --check [dist-dir] verify-only; exit 1 if unpatched
#   ./patch-gev-dist.sh --self-test        run the fixture self-test
#
# Patches applied to dist/assets/*.js:
#   1. "/api/…"    → "/apps/gev/api/…"    (GEV API proxy is subpatched)
#   2. "/models/…" → "/apps/gev/models/…" (glTF models under the app path)
#   3. msaaSamples:4 → iPad/iPhone/iPod UA ternary ?1:4 — iPad WebGL
#      crashes at msaa 4; DO NOT drop this patch (card gev-map).
# And to dist/index.html:
#   4. inject <script src="/apps/gev/honest-fail.js" defer></script> —
#      the watchdog that turns a can't-render pane into a visible failure
#      state instead of a black pane; honest-fail.js is copied into dist/.
#
# All patches are idempotent (quote-bounded matches, presence checks).
set -euo pipefail

MODE=apply
case "${1:-}" in
  --check)     MODE=check; shift ;;
  --self-test) MODE=selftest; shift ;;
esac
DIST="${1:-$HOME/gods-eye-view/dist}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HONEST_FAIL_SRC="${GEV_HONEST_FAIL:-$REPO_ROOT/stacks/web/public/apps/gev/honest-fail.js}"

die() { echo "patch-gev-dist: $*" >&2; exit 1; }

# patch_js <file> — apply patches 1-3 in place (idempotent).
patch_js() {
  local f="$1"
  # 1+2. quote-bounded "/api/ and "/models/ prefixes -> under /apps/gev/.
  # The leading quote in the pattern means an already-patched
  # "/apps/gev/api/…" string cannot re-match, so re-runs are safe.
  sed -i -E \
    -e 's|(["'"'"'`])/api/|\1/apps/gev/api/|g' \
    -e 's|(["'"'"'`])/models/|\1/apps/gev/models/|g' \
    "$f"
  # 3. iPad/iPhone/iPod crash on msaa 4 — keep this patch. The ternary is
  # the documented workaround; once present the pattern no longer matches.
  sed -i -E \
    's|msaaSamples:4|msaaSamples:/iPad\|iPhone\|iPod/.test(navigator.userAgent)?1:4|g' \
    "$f"
}

# check_js <file> — exit-nonzero truth table for the same three patches.
check_js() {
  local f="$1" bad=0
  grep -qE '["'"'"'`]/api/' "$f" \
    && { echo "  UNPATCHED: $f still has \"/api/…\""; bad=1; }
  grep -qE '["'"'"'`]/models/' "$f" \
    && { echo "  UNPATCHED: $f still has \"/models/…\""; bad=1; }
  grep -q 'msaaSamples:4' "$f" \
    && { echo "  UNPATCHED: $f still has msaaSamples:4 (iPad crash)"; bad=1; }
  # only bundles that set msaaSamples at all must carry the ternary —
  # vendor chunks legitimately have none
  if grep -q 'msaaSamples' "$f"; then
    grep -q 'msaaSamples:/iPad' "$f" \
      || { echo "  MISSING: $f has no iPad msaaSamples ternary"; bad=1; }
  fi
  return $bad
}

inject_honest_fail() {
  local html="$1" src="$2"
  grep -q 'honest-fail\.js' "$html" \
    || sed -i 's|</head>|  <script src="/apps/gev/honest-fail.js" defer></script>\n</head>|' "$html"
  local dst="$(dirname "$html")/honest-fail.js"
  [ "$src" -ef "$dst" ] 2>/dev/null || cp "$src" "$dst"
}

check_honest_fail() {
  local html="$1" bad=0
  grep -q 'honest-fail\.js' "$html" \
    || { echo "  UNPATCHED: index.html missing honest-fail.js inject"; bad=1; }
  [ -f "$(dirname "$html")/honest-fail.js" ] \
    || { echo "  MISSING: dist/honest-fail.js not staged"; bad=1; }
  return $bad
}

self_test() {
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/assets"
  cat > "$tmp/assets/index-TEST.js" <<'EOF'
const a = `/api/flights?x=1`, b = "/api/geocode", c = '/models/jet.glb';
const d = "https://other.example/api/leave-me-alone";
const viewer = new CesiumWidget(el, { msaaSamples:4 });
EOF
  cat > "$tmp/index.html" <<'EOF'
<html><head><title>gev</title></head><body></body></html>
EOF
  cp "$HONEST_FAIL_SRC" "$tmp/honest-fail-src.js"
  patch_js "$tmp/assets/index-TEST.js"
  inject_honest_fail "$tmp/index.html" "$tmp/honest-fail-src.js"
  # second run must be a no-op (idempotence)
  patch_js "$tmp/assets/index-TEST.js"
  inject_honest_fail "$tmp/index.html" "$tmp/honest-fail-src.js"
  local f="$tmp/assets/index-TEST.js"
  grep -q '/apps/gev/api/flights' "$f"   || die "self-test: /api/ not patched"
  grep -q '/apps/gev/api/geocode' "$f"   || die "self-test: /api/ dq not patched"
  grep -q '/apps/gev/models/jet.glb' "$f" || die "self-test: /models/ not patched"
  grep -q 'other.example/api/leave-me-alone' "$f" \
    || die "self-test: absolute URL was mangled"
  grep -q 'msaaSamples:/iPad|iPhone|iPod/.test(navigator.userAgent)?1:4' "$f" \
    || die "self-test: msaaSamples iPad ternary missing"
  ! grep -q 'msaaSamples:4' "$f"         || die "self-test: msaaSamples:4 remains"
  [ "$(grep -c 'honest-fail\.js' "$tmp/index.html")" -eq 1 ] \
    || die "self-test: honest-fail inject not idempotent"
  check_js "$f" || die "self-test: --check flags patched bundle"
  check_honest_fail "$tmp/index.html" || die "self-test: check honest-fail"
  rm -rf "$tmp"
  echo "SELFTEST-OK"
}

main() {
  case "$MODE" in
    selftest)
      [ -f "$HONEST_FAIL_SRC" ] || die "honest-fail.js not found at $HONEST_FAIL_SRC"
      self_test; return ;;
    check)
      [ -d "$DIST" ] || die "no dist dir at $DIST"
      local bad=0
      shopt -s nullglob
      local bundles=("$DIST"/assets/*.js)
      [ ${#bundles[@]} -gt 0 ] || die "no assets/*.js in $DIST"
      for f in "${bundles[@]}"; do check_js "$f" || bad=1; done
      [ -f "$DIST/index.html" ] || die "no index.html in $DIST"
      check_honest_fail "$DIST/index.html" || bad=1
      [ $bad -eq 0 ] && echo "patch-gev-dist: dist is fully patched"
      return $bad ;;
    apply)
      [ -d "$DIST" ] || die "no dist dir at $DIST — run npm run build first"
      [ -f "$HONEST_FAIL_SRC" ] || die "honest-fail.js not found at $HONEST_FAIL_SRC"
      shopt -s nullglob
      local bundles=("$DIST"/assets/*.js)
      [ ${#bundles[@]} -gt 0 ] || die "no assets/*.js in $DIST"
      for f in "${bundles[@]}"; do
        patch_js "$f"
        echo "patched $(basename "$f")"
      done
      [ -f "$DIST/index.html" ] || die "no index.html in $DIST"
      inject_honest_fail "$DIST/index.html" "$HONEST_FAIL_SRC"
      echo "honest-fail.js injected + staged"
      # re-run the checks so a no-op patch run still proves the end state
      MODE=check DIST="$DIST" main ;;
  esac
}

main "$@"
