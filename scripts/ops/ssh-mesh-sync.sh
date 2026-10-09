#!/usr/bin/env bash
# ssh-mesh-sync — keep the tailnet SSH mesh whole with zero attention.
#
# Two failure classes killed edges in practice (2026-10-09):
#   1. "Host key verification failed" under BatchMode — a host had never
#      ssh-keyscan'd the peer, so first contact dies silently in scripts.
#   2. Permission denied (publickey) — the peer's key was never authorized.
# Both are maintenance problems, not config problems: solve them by
# pushing pubkeys + hostkeys around the mesh on a timer.
#
# Mesh membership = hosts: in docs/ssot/infrastructure/ssot.host-capacity.yml
# (underscores -> dashes for ssh names). Excluded: michael-ha (HAOS keys
# live in addon config — edits don't persist) and macbook (off tailnet).
#
# Idempotent. Run on any host that reaches the mesh — intended as the
# ssh-mesh-sync.timer unit on tony-omen weekly + on-demand.
set -uo pipefail

REPO="${CHABA_REPO:-/home/tony/CascadeProjects/chaba}"
SSOT="$REPO/docs/ssot/infrastructure/ssot.host-capacity.yml"
EXCLUDE="macbook michael-ha"

# hosts: section -> top-level host keys -> ssh names (underscore -> dash)
HOSTS=$(awk '/^hosts:/{f=1;next} /^[a-z]/ && f{exit} f && /^  [a-z0-9_]+:/{gsub(":","",$1); gsub("_","-",$1); print $1}' "$SSOT")
[ -n "$HOSTS" ] || { echo "ssh-mesh-sync: no hosts parsed from $SSOT"; exit 1; }

ok=0; skipped=0
declare -A PUBS

# 1. Collect each reachable host's default pubkey.
for h in $HOSTS; do
  case " $EXCLUDE " in *" $h "*) continue;; esac
  if ! timeout 8 ssh -o BatchMode=yes -o ConnectTimeout=4 "$h" true 2>/dev/null; then
    echo "ssh-mesh-sync: $h unreachable — skipping"; skipped=$((skipped+1)); continue
  fi
  # default identity for outbound ssh on that host
  pub=$(ssh -o BatchMode=yes "$h" '
        for k in id_ed25519 id_cascade; do
          [ -f ~/.ssh/$k.pub ] && { cat ~/.ssh/$k.pub; exit 0; }
        done
        # none? mint a default so the host always has one
        ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "$(hostname)-mesh" -q
        cat ~/.ssh/id_ed25519.pub' 2>/dev/null)
  [ -n "$pub" ] && PUBS[$h]="$pub"
done

# 2. Per reachable host: install every peer pubkey into authorized_keys
#    (skip its own) and ssh-keyscan every peer into known_hosts.
for h in "${!PUBS[@]}"; do
  scan=$(echo "$HOSTS" | tr ' ' '\n' | grep -vFx "$h" | tr '\n' ' ')
  ssh -o BatchMode=yes "$h" bash -s -- "$scan" <<'EOS'
scan="$1"
ssh-keyscan -t ed25519 $scan 2>/dev/null >> ~/.ssh/known_hosts
sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts 2>/dev/null
EOS
  for p in "${!PUBS[@]}"; do
    [ "$p" = "$h" ] && continue
    key="${PUBS[$p]}"
    ssh -o BatchMode=yes "$h" \
      "grep -qF '${key:0:60}' ~/.ssh/authorized_keys 2>/dev/null || echo '$key' >> ~/.ssh/authorized_keys"
    ok=$((ok+1))
  done
done

echo "ssh-mesh-sync: ${#PUBS[@]} hosts synced, $ok key-checks, $skipped unreachable"
