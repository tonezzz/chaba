#!/usr/bin/env bash
# stick-own-nodekey.sh — give a portable stick its OWN tailnet nodekey.
#
# Card: tony-usb-own-nodekey (SEC-0303). Runbook: docs/kb/mn01-stick-standard.md
#
# Run ON the stick at the start of a stick session, or pipe it over ssh:
#   ssh tony@<stick-lan-ip> 'sudo bash -s' < scripts/ops/stick-own-nodekey.sh
#
# WHY NO `tailscale logout`: the stick's /var/lib/tailscale/tailscaled.state
# is a CLONE of real mn01's node key — stick and mn01 present the same
# nodekey, i.e. they are the SAME tailnet node fighting for one IP.
# `tailscale logout` expires that node key server-side and would knock the
# REAL mn01 offline until someone re-authenticates it. The safe fix is to
# stop presenting the cloned state and register fresh: mn01's node is never
# deleted, it simply becomes uncontested once the stick stops using it.
#
# Sequence:
#   1. systemctl stop tailscaled      (ends the mn01 session fight immediately)
#   2. move tailscaled.state aside    (forensics — proves which key was cloned)
#   3. systemctl start tailscaled     (fresh, empty state)
#   4. tailscale up --hostname=<name> (registers a NEW node key)
#   5. print the new identity         (record it in mn01-stick-standard.md)
#
# Auth: `tailscale up` prints a one-time login URL — approve the new node in
# the Tailscale admin console, or pass a reusable key via TS_AUTHKEY env.
#
# Env overrides:
#   STICK_NODE_NAME  tailnet node name (default: tony-usb — the stick's hostname)
#   TS_AUTHKEY       tailscale auth key for zero-touch join (optional)
#   STICK_STATE_DIR  tailscale state dir (default: /var/lib/tailscale)
set -euo pipefail

NODE_NAME="${STICK_NODE_NAME:-tony-usb}"
STATE_DIR="${STICK_STATE_DIR:-/var/lib/tailscale}"
STATE_FILE="$STATE_DIR/tailscaled.state"
LOG=/var/log/stick-own-nodekey.log

say() { echo "[stick-own-nodekey] $*" | tee -a "$LOG"; }

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo)" >&2; exit 1; }

say "host=$(hostname) target-node=$NODE_NAME"

# 1. Stop contesting mn01's node first — every second counts.
if systemctl is-active --quiet tailscaled 2>/dev/null; then
    say "stopping tailscaled (ends cloned-nodekey fight with mn01)"
    systemctl stop tailscaled
else
    say "tailscaled not active — continuing"
fi

# 2. Preserve the cloned state for forensics, then remove it.
if [ -f "$STATE_FILE" ]; then
    bak="$STATE_FILE.cloned-$(date +%Y%m%d-%H%M%S).bak"
    mv "$STATE_FILE" "$bak"
    say "moved cloned state -> $bak"
else
    say "no $STATE_FILE — already clean"
fi

# 3. Fresh daemon, empty state.
systemctl start tailscaled
sleep 2

# 4. Register as our own node.
UP_ARGS=(--hostname="$NODE_NAME")
if [ -n "${TS_AUTHKEY:-}" ]; then
    UP_ARGS+=(--auth-key="$TS_AUTHKEY")
    say "using TS_AUTHKEY (zero-touch join)"
fi
say "tailscale up ${UP_ARGS[*]}"
tailscale up "${UP_ARGS[@]}" || {
    say "tailscale up failed — if it printed a login URL, approve it in the"
    say "admin console and re-run this script (it is idempotent)."
    exit 1
}

# 5. Report the new identity for the runbook registry.
say "=== new tailnet identity ==="
tailscale status || true
echo "ipv4: $(tailscale ip -4 2>/dev/null | head -1)"
echo "ipv6: $(tailscale ip -6 2>/dev/null | head -1)"
if command -v python3 >/dev/null; then
    tailscale status --json 2>/dev/null | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin).get("Self", {})
    print("host:", s.get("HostName"))
    print("dns:",  s.get("DNSName", "").rstrip("."))
    print("key:",  s.get("Key", ""))
except Exception as e:
    print("self-json parse failed:", e)
' || true
fi
say "done — record this identity in docs/kb/mn01-stick-standard.md"
say "if a login URL was printed above, the node is NOT live until approved"
