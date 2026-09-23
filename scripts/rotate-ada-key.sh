#!/usr/bin/env bash
# Rotate an Ada backend's ADA_API_KEY: generate a new key on the host,
# update the env file, restart the service, print the new unlock URL.
# Usage: rotate-ada-key.sh <tony|michael|ada-pi>
set -euo pipefail

instance="${1:-}"
case "$instance" in
  tony)    host=mn01;      env_name=ada-ha-tony.env;    svc=ada-ha-tony.service ;;
  michael) host=mn01;      env_name=ada-ha-michael.env; svc=ada-ha-michael.service ;;
  ada-pi)  host=idc01;     env_name=ada-pi-pwa.env;     svc=ada-pi-pwa.service ;;
  *) echo "usage: $0 <tony|michael|ada-pi>" >&2; exit 2 ;;
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
