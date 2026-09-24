#!/usr/bin/env bash
# Rotate the shared GEMINI_API_KEY and HOME_ASSISTANT_TOKEN values across all
# ada env files on mn01, tony-dell, idc01.
#
# Files are matched by value fingerprint (last-4 chars), not filename —
# tony-dell carries both ada-ha-pwa.env and ada-pi-pwa.env with different
# tokens, and filename matching has already bitten us once.
#
# Fingerprint map (as of 2026-09-24):
#   GEMINI_API_KEY ...UEQA  — exposed shared key (all ada services + mddb
#                             embedding proxy). ...jjmw files are a separate
#                             key and are NOT touched.
#   HOME_ASSISTANT_TOKEN ...6823 — tony-ha token, remote URL (ada-ha-tony,
#                             ada-pi-pwa on mn01/idc01/tony-dell)
#   HOME_ASSISTANT_TOKEN ...d-uM — tony-ha token, loopback URL (ada-ha-pwa,
#                             ada-ha-tony, chaba-guest on tony-dell)
#   HOME_ASSISTANT_TOKEN ...M_sY — michael-ha token (ada-ha-michael)
#
# Secret values are never printed — only fingerprints and filenames.
#
# Usage:
#   rotate-ada-secrets.sh --gemini NEW [--ha-tony-remote NEW]
#       [--ha-tony-local NEW] [--ha-michael NEW] [--dry-run] [--no-restart]
set -euo pipefail

GEMINI_NEW="" HA_TONY_REMOTE="" HA_TONY_LOCAL="" HA_MICHAEL=""
DRY_RUN=0 NO_RESTART=0

while [ $# -gt 0 ]; do
  case "$1" in
    --gemini)         GEMINI_NEW="$2"; shift 2 ;;
    --ha-tony-remote) HA_TONY_REMOTE="$2"; shift 2 ;;
    --ha-tony-local)  HA_TONY_LOCAL="$2"; shift 2 ;;
    --ha-michael)     HA_MICHAEL="$2"; shift 2 ;;
    --dry-run)        DRY_RUN=1; shift ;;
    --no-restart)     NO_RESTART=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$GEMINI_NEW$HA_TONY_REMOTE$HA_TONY_LOCAL$HA_MICHAEL" ] || {
  echo "nothing to rotate — pass at least one --gemini/--ha-* flag" >&2; exit 2; }

# Value fingerprints to match (suffix of the CURRENT value in each file).
GEMINI_SUFFIX="UEQA"
HA_TONY_REMOTE_SUFFIX="6823"
HA_TONY_LOCAL_SUFFIX="d-uM"
HA_MICHAEL_SUFFIX="M_sY"

# Per-host restart list (only services whose env files hold rotated values).
restart_units() {
  case "$1" in
    mn01)      echo "ada-ha-tony.service ada-ha-michael.service" ;;
    tony-dell) echo "ada-pi-pwa.service chaba-guest.service chaba-guest-lan.service" ;;
    idc01)     echo "ada-ha-tony.service ada-ha-michael.service ada-pi-pwa.service gemini-ollama-proxy.service" ;;
  esac
}

for host in mn01 tony-dell idc01; do
  echo "=== $host ==="
  ssh "$host" GEMINI_NEW="$GEMINI_NEW" HA_TONY_REMOTE="$HA_TONY_REMOTE" \
    HA_TONY_LOCAL="$HA_TONY_LOCAL" HA_MICHAEL="$HA_MICHAEL" \
    GEMINI_SUFFIX="$GEMINI_SUFFIX" HA_TONY_REMOTE_SUFFIX="$HA_TONY_REMOTE_SUFFIX" \
    HA_TONY_LOCAL_SUFFIX="$HA_TONY_LOCAL_SUFFIX" HA_MICHAEL_SUFFIX="$HA_MICHAEL_SUFFIX" \
    DRY_RUN="$DRY_RUN" 'bash -s' <<'REMOTE'
set -euo pipefail
# Last-4 fingerprint of a var's value (quotes/whitespace stripped).
suffix_of() {
  local val
  val=$(grep -oE "^$1=.*" "$2" 2>/dev/null | head -1 | sed "s|^$1=||" | tr -d "\"' ")
  echo "${val: -4}"
}
replace_key() { # file var new
  [ "$DRY_RUN" = "1" ] || sed -i "s|^$2=.*|$2=$3|" "$1"
}
for f in "$HOME"/.config/secrets/*.env; do
  n=$(basename "$f")
  for var in GEMINI_API_KEY GOOGLE_API_KEY; do
    if [ -n "$GEMINI_NEW" ] && grep -q "^$var=" "$f" && [ "$(suffix_of "$var" "$f")" = "$GEMINI_SUFFIX" ]; then
      echo "  $n: $var -> new gemini key"
      replace_key "$f" "$var" "$GEMINI_NEW"
    fi
  done
  if grep -q "^HOME_ASSISTANT_TOKEN=" "$f"; then
    s=$(suffix_of HOME_ASSISTANT_TOKEN "$f")
    new=""
    case "$s" in
      "$HA_TONY_REMOTE_SUFFIX") [ -n "$HA_TONY_REMOTE" ] && new="$HA_TONY_REMOTE" ;;
      "$HA_TONY_LOCAL_SUFFIX")  [ -n "$HA_TONY_LOCAL" ]  && new="$HA_TONY_LOCAL" ;;
      "$HA_MICHAEL_SUFFIX")     [ -n "$HA_MICHAEL" ]     && new="$HA_MICHAEL" ;;
    esac
    if [ -n "$new" ]; then
      echo "  $n: HOME_ASSISTANT_TOKEN -> new token (was ...$s)"
      replace_key "$f" HOME_ASSISTANT_TOKEN "$new"
    fi
  fi
done
REMOTE

  if [ "$NO_RESTART" = "0" ] && [ "$DRY_RUN" = "0" ]; then
    units=$(restart_units "$host")
    # restart-if-active only — a stopped standby unit (mn01 ada-*) must stay down
    [ -n "$units" ] && ssh "$host" "for u in $units; do
      systemctl --user is-active --quiet \"\$u\" && { systemctl --user restart \"\$u\"; echo \"  \$u restarted\"; } || echo \"  \$u inactive — left stopped\"
    done" || true
  fi
done

[ "$DRY_RUN" = "1" ] && echo "(dry-run — nothing written, nothing restarted)"
echo "done. verify: curl the ada /auth/status endpoints on each host."
