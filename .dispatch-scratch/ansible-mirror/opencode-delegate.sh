#!/usr/bin/env bash
# Send a prompt to an opencode-serve host and print the assistant reply.
# Usage: ./opencode-delegate.sh <host> <prompt...>
# Hosts: macbook omen dell con01 idc03 idc02 (or any Tailscale IP).
set -euo pipefail

host=${1:?usage: opencode-delegate.sh <host> <prompt...>}
shift
prompt=$*

passfile=${OPENCODE_SERVE_PASSWORD_FILE:-$HOME/.config/secrets/opencode-serve.password}
password=$(<"$passfile")
ip=$(awk -v h="$host" '$1 == h { print $2 }' "${OPENCODE_SERVE_HOSTS:-$HOME/ansible/serve-hosts.txt}")
if [[ -z "$ip" ]]; then
  # Allow a literal Tailscale IP or hostname as the first argument.
  ip=$host
fi

base="http://${ip}:4096"
auth=(-u "opencode:${password}")
sid=$(curl -fsS "${auth[@]}" -X POST "$base/api/session" -H 'Content-Type: application/json' -d '{}' \
  | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>process.stdout.write(JSON.parse(s).data.id))')
curl -fsS "${auth[@]}" -X POST "$base/api/session/${sid}/prompt" \
  -H 'Content-Type: application/json' \
  --data "$(node -e 'process.stdout.write(JSON.stringify({text: process.argv[1]}))' "$prompt")" >/dev/null

for _ in $(seq 1 30); do
  reply=$(curl -fsS "${auth[@]}" "$base/api/session/${sid}/message" \
    | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const m=JSON.parse(s).data||[];const a=m.find(x=>x.type==="assistant");if(a){process.stdout.write((a.content||[]).filter(c=>c.type==="text").map(c=>c.text).join("\n"))}})')
  if [[ -n "$reply" ]]; then
    printf '%s\n' "$reply"
    exit 0
  fi
  sleep 2
done
echo "no assistant reply within 60s (session ${sid})" >&2
exit 1
