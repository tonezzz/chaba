#!/usr/bin/env bash
# secrets-backup — age-encrypted tarball of credential-shaped state,
# pushed to recovery hosts. Restore: age -d -i backup-age.key <file> | tar xz -C ~/
set -euo pipefail

KEY="$HOME/.config/secrets/backup-age.key"
PUB=$(grep -oP "public key: \K.*" "$KEY")
STAMP=$(date +%Y%m%d-%H%M)
OUT=$(mktemp -d)/secrets-$STAMP.tar.age
KEEP_DAYS=14
TARGETS=(idc02 idc01 tony-dell-m2m)

tar czf - -C "$HOME" \
  .config/secrets \
  .ssh \
  .config/rclone \
  .config/camwall.env \
  .config/systemd/user \
  2>/dev/null | age -r "$PUB" -o "$OUT" -

# verify artifact decrypts before shipping — undecryptable backups are worse
age -d -i "$KEY" "$OUT" | tar tzf - >/dev/null

for t in "${TARGETS[@]}"; do
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$t" \
    "mkdir -p ~/secrets-backup && find ~/secrets-backup -name secrets-*.tar.age -mtime +$KEEP_DAYS -delete"
  scp -o BatchMode=yes -o ConnectTimeout=15 -q "$OUT" "$t:~/secrets-backup/"
  echo "secrets-backup: pushed $(basename "$OUT") -> $t ($(du -h "$OUT" | cut -f1))"
done

rm -f "$OUT"
