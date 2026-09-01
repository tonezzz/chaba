#!/bin/bash
# Launch Google Chrome with browser cache on tmpfs (ramdisk).
# Profile stays in ~/.config/google-chrome; only disk and media caches go to /tmp.

CACHE_DIR=/tmp/chrome-main-cache
MEDIA_DIR=/tmp/chrome-main-media
mkdir -p "$CACHE_DIR" "$MEDIA_DIR"

CHROME_FLAGS=(--disk-cache-dir="$CACHE_DIR" --media-cache-dir="$MEDIA_DIR")

if [ "$XDG_SESSION_TYPE" = "wayland" ] && [ -n "$WAYLAND_DISPLAY" ]; then
    exec /usr/bin/google-chrome-stable "${CHROME_FLAGS[@]}" "$@"
else
    exec /usr/bin/google-chrome-stable --ozone-platform=x11 "${CHROME_FLAGS[@]}" "$@"
fi
