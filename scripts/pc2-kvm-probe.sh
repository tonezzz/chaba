#!/usr/bin/env sh
set -eu

: "${PC2_SSH_USER:?Set PC2_SSH_USER}"
: "${PC2_SSH_HOST:?Set PC2_SSH_HOST}"
: "${PC2_SSH_KEY_PATH:?Set PC2_SSH_KEY_PATH}"

PC2_SSH_PORT=${PC2_SSH_PORT:-22}

echo "[PC2] Probing virtualization/KVM on $PC2_SSH_HOST as $PC2_SSH_USER"

ssh \
  -i "$PC2_SSH_KEY_PATH" \
  -p "$PC2_SSH_PORT" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$PC2_SSH_USER@$PC2_SSH_HOST" <<'EOF'
set -eu

echo "== hostname =="
hostname

echo

echo "== id =="
id

echo

echo "== systemd-detect-virt =="
(systemd-detect-virt || true)

echo

echo "== cpu flags (vmx/svm) =="
(grep -E -m1 -o "\<(vmx|svm)\>" /proc/cpuinfo && echo OK) || echo "no vmx/svm flag"

echo

echo "== /dev/kvm =="
(ls -l /dev/kvm && echo OK) || echo "NO /dev/kvm"

echo

echo "== kvm group =="
(getent group kvm || true)

echo

echo "== kvm modules =="
(lsmod | grep -E "^kvm(_amd|_intel)?\b" || true)

echo

echo "== dmesg (kvm|svm|vmx) last 50 lines =="
((dmesg 2>/dev/null || true) | grep -E -i "kvm|svm|vmx" | tail -n 50) || true
EOF

echo "[PC2] probe completed."
