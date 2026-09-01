#!/bin/bash
# Launch Google Chrome with browser cache on tmpfs (ramdisk).
# Profile stays in ~/.config/google-chrome; only disk and media caches go to /tmp.

CACHE_DIR=/tmp/chrome-main-cache
MEDIA_DIR=/tmp/chrome-main-media
mkdir -p "" ""

CHROME_FLAGS=(--disk-cache-dir="" --media-cache-dir="")

if [ "" = "wayland" ] && [ -n "" ]; then
    exec /usr/bin/google-chrome-stable "" ""
else
    exec /usr/bin/google-chrome-stable --ozone-platform=x11 "" ""
fi
