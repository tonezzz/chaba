#!/usr/bin/env bash
# mn01-canary.sh — nightly standby-verification for mn01 (Ada standby + burst lane).
# Verifies: ada-pi checkout freshness, .venv import smoke, secrets presence,
# mddb REST reachability, idc01 ada services (the things mn01 stands by for),
# tailscale up. Emits a chaba-admin event via EVENT_SSH (LAN ssh to dell).
# Exit 0 on all-ok, 1 on any failure.
set -uo pipefail

EVENT_SSH="${EVENT_SSH:-192.168.2.67}"
ADA_REPO="${ADA_REPO:-$HOME/CascadeProjects/ada-pi}"
MDDB_URL="${MDDB_URL:-http://100.74.146.0:11023}"

fails=()
ok()   { echo "ok   $1"; }
fail() { echo "FAIL $1"; fails+=("$1"); }

# 1. tailscale up
tailscale status >/dev/null 2>&1 && ok "tailscale" || fail "tailscale down"

# 2. ada-pi checkout tracks origin/main (stale standby = useless standby)
if git -C "$ADA_REPO" rev-parse --verify HEAD >/dev/null 2>&1; then
    local_head=$(git -C "$ADA_REPO" rev-parse HEAD)
    remote_head=$(git -C "$ADA_REPO" ls-remote origin main 2>/dev/null | cut -f1)
    if [ -z "$remote_head" ]; then
        fail "ada-pi: cannot reach origin (network?)"
    elif [ "$local_head" = "$remote_head" ]; then
        ok "ada-pi @ ${local_head:0:7} (current)"
    else
        fail "ada-pi behind origin (local ${local_head:0:7} != remote ${remote_head:0:7})"
    fi
else
    fail "ada-pi checkout missing at $ADA_REPO"
fi

# 3. .venv import smoke — the process must actually start
if (cd "$ADA_REPO" && ./.venv/bin/python3 -c "import backend.tool_runner") 2>/dev/null; then
    ok "ada-pi venv imports"
else
    fail "ada-pi venv/import broken"
fi

# 4. secrets present + non-empty
for f in ada-ha-tony.env ada-ha-michael.env ada-ha-tony-keys.json ada-ha-michael-keys.json ada-vault.env; do
    [ -s "$HOME/.config/secrets/$f" ] && ok "secret $f" || fail "secret missing/empty: $f"
done

# 5. mddb REST alive (Ada memory + dispatch ledger both die without it)
code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -X POST "$MDDB_URL/v1/search" \
        -H 'content-type: application/json' -d '{"collection":"ada-ha-bank-general","q":"x","top_k":1}' 2>/dev/null)
[ "$code" = "200" ] && ok "mddb REST" || fail "mddb REST ($code)"

# 6. idc01 ada services — the primary we're standing by for
svc_out=$(ssh -o BatchMode=yes -o ConnectTimeout=8 idc01 \
    'systemctl --user is-active ada-pi-pwa ada-ha-tony ada-ha-michael 2>/dev/null' || echo "ssh-fail")
if echo "$svc_out" | grep -q "ssh-fail"; then
    fail "idc01 ssh unreachable"
else
    n=$(echo "$svc_out" | grep -c "^active$")
    [ "$n" -eq 3 ] && ok "idc01 ada services 3/3" || fail "idc01 ada services $n/3 active"
fi

# --- emit ---
sev=info; [ ${#fails[@]} -gt 0 ] && sev=warn
body="mn01-canary $(date +%F\ %T): ${#fails[@]} failure(s): ${fails[*]:-none}"
payload=$(SEV="$sev" BODY="$body" python3 - <<'PY'
import json, os
print(json.dumps({"title": "mn01 canary", "category": "ops-canary",
    "source": "mn01-canary", "severity": os.environ["SEV"],
    "requires_response": os.environ["SEV"] != "info",
    "body": os.environ["BODY"]}))
PY
)
printf '%s\n' "$payload" | ssh -o BatchMode=yes -o ConnectTimeout=8 "$EVENT_SSH" \
    "python3 ~/.config/home-assistant/scripts/chaba-event-log.py add -" >/dev/null 2>&1 \
    && echo "event posted" || echo "event post failed"
echo "$body"
[ ${#fails[@]} -eq 0 ]
