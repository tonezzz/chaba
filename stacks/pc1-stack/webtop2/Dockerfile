FROM lscr.io/linuxserver/webtop:ubuntu-xfce

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg nodejs iputils-ping iproute2 dnsutils net-tools traceroute \
  && install -d -m 0755 /usr/share/keyrings \
  && curl -fsSL "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf.gpg" \
    | gpg --dearmor -o /usr/share/keyrings/windsurf-stable-archive-keyring.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/windsurf-stable-archive-keyring.gpg arch=amd64] https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/apt stable main" \
    > /etc/apt/sources.list.d/windsurf.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends windsurf \
  && printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    '' \
    'export DONT_PROMPT_WSL_INSTALL=1' \
    'export DISPLAY="${DISPLAY:-:1}"' \
    '' \
    'if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && ! printf "%s" "$DBUS_SESSION_BUS_ADDRESS" | grep -Eq "^(unix|tcp):"; then' \
    '  unset DBUS_SESSION_BUS_ADDRESS' \
    'fi' \
    '' \
    'if [ -z "${XDG_RUNTIME_DIR:-}" ]; then' \
    '  export XDG_RUNTIME_DIR="/tmp/runtime-${UID}"' \
    'fi' \
    '' \
    'mkdir -p "$XDG_RUNTIME_DIR"' \
    'chmod 700 "$XDG_RUNTIME_DIR" || true' \
    '' \
    'USER_DATA_DIR="${WINDSURF_USER_DATA_DIR:-/config/windsurf}"' \
    'mkdir -p "$USER_DATA_DIR" || true' \
    '' \
    'exec /usr/share/windsurf/windsurf --no-sandbox --user-data-dir="$USER_DATA_DIR" "$@"' \
    > /usr/local/bin/windsurf-webtop \
  && chmod 0755 /usr/local/bin/windsurf-webtop \
  && if [ -f /usr/share/applications/windsurf.desktop ]; then \
       sed -i 's|^Exec=.*|Exec=/usr/local/bin/windsurf-webtop %F|; /^NoDisplay=/d; s|^Name=.*|Name=Windsurf|; s|^StartupNotify=.*|StartupNotify=false|; /^Categories=/s/.*/Categories=TextEditor;Development;IDE;/' /usr/share/applications/windsurf.desktop; \
     fi \
  && if [ -f /usr/share/applications/windsurf-url-handler.desktop ]; then \
       sed -i 's|^Exec=.*|Exec=/usr/local/bin/windsurf-webtop --open-url %U|' /usr/share/applications/windsurf-url-handler.desktop; \
     fi \
  && rm -f /usr/share/applications/windsurf-webtop.desktop \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*
