#!/usr/bin/env bash
# Rotate an Ada backend's ADA_API_KEY: generate a new key on the host,
# update the env file, restart the service, print the new unlock URL.
# Usage: rotate-ada-key.sh <tony|michael|ada-voice>
set -euo pipefail

instance="${1:-}"
case "$instance" in
  tony)    host=idc03; env_name=tony-ha/backend.env;    svc=ada-ha-tony.service ;;
  michael) host=idc03; env_name=michael-ha/backend.env; svc=ada-ha-michael.service ;;
  # The root PWA is now served by the Tony lane; no separate ada-voice unit exists.
  ada-voice) host=idc03; env_name=tony-ha/backend.env; svc=ada-ha-tony.service ;;
  *) echo "usage: $0 <tony|michael|ada-voice>" >&2; exit 2 ;;
esac

ssh "$host" "
  set -euo pipefail
  f=~/.config/secrets/$env_name
  k=\$(openssl rand -hex 24)
  if grep -q '^ADA_API_KEY=' \"\$f\"; then
    sed -i \"s/^ADA_API_KEY=.*/ADA_API_KEY=\$k/\" \"\$f\"
  else
    printf 'ADA_API_KEY=%s\n' \"\$k\" >> \"\$f\"
  fi
  systemctl --user restart $svc
"
echo "rotated $instance ($svc restarted)"

# Print the fresh deep-link.
"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/ada-key-url.sh" "$instance"
