#!/usr/bin/env bash
# tony-dell multi-WAN active-backup: wired (enp0s31f6) primary, iPhone (TONY-IP) Wi-Fi backup.
# Runs as root. Switches default-route metric to Wi-Fi if wired internet fails.

set -uo pipefail

WIRED_CON="Wired connection 1"
WIRED_DEV="enp0s31f6"
WIFI_CON="TONY-IP"
WIFI_DEV="wlx00761100125e"
GATEWAY_IP="8.8.8.8"
PING_COUNT=2
PING_WAIT=2
STATE_FILE="/var/lib/tony-dell-wan-failover/primary"
LOG_FILE="/var/log/tony-dell-wan-failover.log"
FAILOVER_THRESHOLD=3

log() {
    local ts
    ts=$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%SZ')
    printf '%s %s\n' "$ts" "$*" | tee -a "$LOG_FILE" >/dev/null
    printf '%s %s\n' "$ts" "$*"
}

mkdir -p /var/lib/tony-dell-wan-failover
mkdir -p "$(dirname "$LOG_FILE")"

PRIMARY=""
FAIL_COUNT=0
if [[ -f "$STATE_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$STATE_FILE"
fi
: "${PRIMARY:=wired}"
: "${FAIL_COUNT:=0}"

default_dev() {
    ip -4 route show default | awk '{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}'
}

ping_dev() {
    local dev=$1
    ping -c "$PING_COUNT" -W "$PING_WAIT" -I "$dev" -q "$GATEWAY_IP" >/dev/null 2>&1
}

get_gw() {
    local con=$1
    nmcli -g IP4.GATEWAY con show "$con" 2>/dev/null | head -n1
}

set_wired_primary() {
    local wired_gw wifi_gw
    wired_gw=$(get_gw "$WIRED_CON")
    wifi_gw=$(get_gw "$WIFI_CON")
    [[ -z "$wired_gw" ]] && { log "no-wired-gateway"; return 1; }
    ip -4 route replace default via "$wired_gw" dev "$WIRED_DEV" metric 100 2>/dev/null || true
    if [[ -n "$wifi_gw" ]]; then
        ip -4 route replace default via "$wifi_gw" dev "$WIFI_DEV" metric 2000 2>/dev/null || true
    fi
    log "switched-to-wired wired_gw=$wired_gw"
}

set_wifi_primary() {
    local wired_gw wifi_gw
    wired_gw=$(get_gw "$WIRED_CON")
    wifi_gw=$(get_gw "$WIFI_CON")
    [[ -z "$wifi_gw" ]] && { log "no-wifi-gateway"; return 1; }
    if [[ -n "$wired_gw" ]]; then
        ip -4 route replace default via "$wired_gw" dev "$WIRED_DEV" metric 2000 2>/dev/null || true
    fi
    ip -4 route replace default via "$wifi_gw" dev "$WIFI_DEV" metric 100 2>/dev/null || true
    log "switched-to-wifi wifi_gw=$wifi_gw"
}

CURRENT_DEV=$(default_dev)
log "state primary=$PRIMARY fail_count=$FAIL_COUNT current_default_dev=${CURRENT_DEV:-none}"

if ping_dev "$WIRED_DEV"; then
    if [[ "$PRIMARY" != "wired" || "$CURRENT_DEV" != "$WIRED_DEV" ]]; then
        if set_wired_primary; then
            PRIMARY="wired"
            FAIL_COUNT=0
        fi
    else
        FAIL_COUNT=0
    fi
else
    log "wired-internet-fail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    if [[ "$FAIL_COUNT" -ge "$FAILOVER_THRESHOLD" && "$PRIMARY" == "wired" ]]; then
        if set_wifi_primary; then
            PRIMARY="wifi"
        fi
    fi
fi

printf 'PRIMARY=%s\nFAIL_COUNT=%s\n' "$PRIMARY" "$FAIL_COUNT" > "$STATE_FILE"
