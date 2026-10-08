#!/usr/bin/env bash
# secrets-collect — pull EVERY host's credential-shaped state into one
# age-encrypted bundle per host, stored on tony-omen and mirrored to
# tony-dell. Complements idc03's secrets-backup.sh (which only covers
# idc03 and already pushes to idc01/idc02/tony-dell-m2m).
#
# Restore: age -d -i backup-age.key <file> | tar xz -C ~/
# Key lives at ~/.config/secrets/backup-age.key (same key idc03 uses —
# pubkey is embedded here, private half stays in the secrets dirs).
set -uo pipefail

AGE_PUB="age1h3cpfffp80t8hrkaey8wl0elemz4z46es56lwfuyw32kdkzjv4mqtnjd7z"
DEST="$HOME/secrets-backup/hosts"
MIRROR_HOST="tony-dell"
MIRROR_DIR="secrets-backup/hosts"
KEEP=7                       # bundles to keep per host
STAMP="$(date +%Y%m%d-%H%M)"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10"

# Hosts to sweep. tony-omen handled locally (no self-ssh needed).
HOSTS=(idc03 idc02 idc01 tony-dell mn01 tony-omen)

# Credential-shaped paths, relative to $HOME — same set as idc03's script.
PATHS=(.config/secrets .ssh .config/rclone .config/camwall.env
       .config/systemd/user
       .config/.wrangler .config/gh .git-credentials
       .config/devin/mcp_config.json
       .local/share/home-assistant-michael/ha-token
       .local/share/tuya/credentials.json
       .local/share/tuya/project-creds.json)

mkdir -p "$DEST"

collect() {
  local host="$1"
  local out="$DEST/${host}-${STAMP}.tar.age"
  local remote_cmd
  remote_cmd='cd "$HOME" && for p in '"${PATHS[*]}"'; do
    [ -e "$p" ] && printf "%s\n" "$p"
  done | tar czf - -T - 2>/dev/null'
  if [ "$host" = "tony-omen" ] || [ "$host" = "$(hostname)" ]; then
    eval "$remote_cmd" | age -r "$AGE_PUB" -o "$out" -
  else
    $SSH "$host" "$remote_cmd" | age -r "$AGE_PUB" -o "$out" -
  fi
  [ -s "$out" ] || { echo "FAIL $host: empty bundle"; rm -f "$out"; return 1; }
  echo "ok $host -> $(basename "$out") ($(du -h "$out" | cut -f1))"
}

fail=0
for h in "${HOSTS[@]}"; do
  collect "$h" || fail=$((fail+1))
done

# retention — keep newest $KEEP per host
for h in "${HOSTS[@]}"; do
  ls -t "$DEST/${h}-"*.tar.age 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
done

# mirror the whole hosts/ dir to tony-dell
if [ "$(hostname)" != "$MIRROR_HOST" ]; then
  $SSH "$MIRROR_HOST" "mkdir -p ~/$MIRROR_DIR"
  rsync -a --delete "$DEST/" "$MIRROR_HOST:$MIRROR_DIR/" \
    && echo "mirrored -> $MIRROR_HOST:$MIRROR_DIR"
fi

[ "$fail" -eq 0 ] || { echo "$fail host(s) failed"; exit 1; }
