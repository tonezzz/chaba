#!/usr/bin/env bash
# kk-mac-models — park/fetch model weights between kk-mac (active set) and
# tony-dell ~/model-archive (canonical LAN library).
#
# Runs ON tony-dell. Requires ~/.config/secrets/kk-mac-password.txt (line 1=pass).
#
#   kk-mac-models.sh list                     models live on kk-mac + sizes
#   kk-mac-models.sh archive                  models parked on dell + sizes
#   kk-mac-models.sh park-ollama <name:tag>   move ollama model kk-mac -> dell
#   kk-mac-models.sh fetch-ollama <name:tag>  move ollama model dell -> kk-mac
#   kk-mac-models.sh park-hf <org--name>      move HF cache dir kk-mac -> dell
#   kk-mac-models.sh fetch-hf <org--name>     move HF cache dir dell -> kk-mac
#
# Ollama parking resolves manifest -> blob digests, rsyncs exact files, then
# `ollama rm` on kk-mac (clean delete). HF dirs are self-contained.
# NOTE: kk-mac needs the store dirs group-writable (staff) — one-time setup:
#   chmod -R g+w /Users/adanest/.ollama /Users/adanest/.cache

set -euo pipefail
KK_HOST="${KK_MAC_HOST:-192.168.2.80}"
KK_USER=kkkakk
PWFILE=~/.config/secrets/kk-mac-password.txt
ARC=~/model-archive
SSH="sshpass -f $PWFILE ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no"
SCP="sshpass -f $PWFILE scp -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no"
KSTORE=/Users/adanest/.ollama/models
KHF=/Users/adanest/.cache/huggingface/hub

kssh() { $SSH $KK_USER@$KK_HOST "$@"; }

case "${1:-}" in
  list)
    echo "== ollama (kk-mac)"; kssh "/opt/homebrew/bin/ollama ls"
    echo "== hf cache (kk-mac)"; kssh "du -sh $KHF/models--* 2>/dev/null"
    echo "== disk"; kssh "df -h / | tail -1" ;;
  archive)
    find $ARC/ollama/manifests -type f 2>/dev/null | sed "s|.*/library/|ollama: |;s|/|:|"
    find $ARC/hf -maxdepth 1 -name "models--*" -exec du -sh {} \; 2>/dev/null
    du -sh $ARC 2>/dev/null ;;
  park-ollama)
    M="${2:?name:tag}"; NAME="${M%%:*}"; TAG="${M##*:}"
    MP="$KSTORE/manifests/registry.ollama.ai/library/$NAME/$TAG"
    BLOBS=$(kssh "python3 -c \"
import json; m=json.load(open('$MP'))
print(' '.join('sha256-'+l['digest'].split(':')[1] for l in [m.get('config',{})]+m.get('layers',[])))\"")
    [ -z "$BLOBS" ] && { echo "no manifest for $M"; exit 1; }
    mkdir -p $ARC/ollama/blobs $ARC/ollama/manifests/registry.ollama.ai/library/$NAME
    for b in $BLOBS; do
      $SCP -q $KK_USER@$KK_HOST:$KSTORE/blobs/$b $ARC/ollama/blobs/$b
    done
    $SCP -q $KK_USER@$KK_HOST:$MP $ARC/ollama/manifests/registry.ollama.ai/library/$NAME/$TAG
    kssh "/opt/homebrew/bin/ollama rm $M && echo 'parked+removed $M'" ;;
  fetch-ollama)
    M="${2:?name:tag}"; NAME="${M%%:*}"; TAG="${M##*:}"
    MP="$ARC/ollama/manifests/registry.ollama.ai/library/$NAME/$TAG"
    BLOBS=$(python3 -c "
import json; m=json.load(open('$MP'))
print(' '.join('sha256-'+l['digest'].split(':')[1] for l in [m.get('config',{})]+m.get('layers',[])))")
    for b in $BLOBS; do
      $SCP -q $ARC/ollama/blobs/$b $KK_USER@$KK_HOST:$KSTORE/blobs/$b
    done
    kssh "mkdir -p $KSTORE/manifests/registry.ollama.ai/library/$NAME"
    $SCP -q $MP $KK_USER@$KK_HOST:$KSTORE/manifests/registry.ollama.ai/library/$NAME/$TAG
    kssh "chmod -R g+w $KSTORE/blobs $KSTORE/manifests 2>/dev/null; /opt/homebrew/bin/ollama ls | grep $NAME && echo 'fetched $M'" ;;
  park-hf)
    D="models--${2:?org--name}"
    mkdir -p $ARC/hf
    sshpass -f $PWFILE rsync -a -e "ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no" \
      $KK_USER@$KK_HOST:$KHF/$D/ $ARC/hf/$D/
    kssh "rm -rf $KHF/$D && echo 'parked+removed $D'" ;;
  fetch-hf)
    D="models--${2:?org--name}"
    [ -d "$ARC/hf/$D" ] || { echo "not in archive: $D"; exit 1; }
    sshpass -f $PWFILE rsync -a -e "ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no" \
      $ARC/hf/$D/ $KK_USER@$KK_HOST:$KHF/$D/
    kssh "chmod -R g+w $KHF/$D && echo 'fetched $D'" ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
