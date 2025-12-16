#!/usr/bin/with-contenv bash
set -eu

PUID="${PUID:-1000}"

# IMPORTANT: linuxserver/webtop internals expect the user "abc" to exist.
# Do NOT rename or delete it.

if ! getent group abc >/dev/null 2>&1; then
  groupadd -g "$PUID" abc 2>/dev/null || true
fi

if ! getent passwd abc >/dev/null 2>&1; then
  useradd -u "$PUID" -g "$PUID" -d /config -s /bin/bash abc 2>/dev/null || true
fi

# Ensure abc matches PUID/PGID
usermod -u "$PUID" -g "$PUID" -d /config -s /bin/bash abc 2>/dev/null || true

# If dockremap exists and currently owns PUID, move it out of the way so
# getpwuid(PUID) resolves to chaba.
if getent passwd dockremap >/dev/null 2>&1; then
  DOCK_UID="$(getent passwd dockremap | cut -d: -f3)"
  if [ "$DOCK_UID" = "$PUID" ]; then
    DOCK_NEW_UID="913"
    if getent passwd "$DOCK_NEW_UID" >/dev/null 2>&1; then
      DOCK_NEW_UID="914"
    fi
    usermod -u "$DOCK_NEW_UID" dockremap 2>/dev/null || true
    if getent group dockremap >/dev/null 2>&1; then
      groupmod -g "$DOCK_NEW_UID" dockremap 2>/dev/null || true
    fi
  fi
fi

# Create chaba as an alias for the same uid/gid as abc (keep abc intact)
ABC_GID="$(getent passwd abc | cut -d: -f4)"

if ! getent passwd chaba >/dev/null 2>&1; then
  useradd -o -u "$PUID" -g "$ABC_GID" -d /config -s /bin/bash chaba 2>/dev/null || true
fi

usermod -o -u "$PUID" -g "$ABC_GID" -d /config -s /bin/bash chaba 2>/dev/null || true

# Ensure getpwuid(PUID) resolves to chaba by placing the chaba line first.
PASSWD_TMP="/tmp/passwd.chaba"
CHABA_LINE="$(getent passwd chaba || true)"
if [ -n "$CHABA_LINE" ]; then
  {
    printf '%s\n' "$CHABA_LINE"
    grep -v '^chaba:' /etc/passwd
  } >"$PASSWD_TMP"
  cat "$PASSWD_TMP" >/etc/passwd
fi
