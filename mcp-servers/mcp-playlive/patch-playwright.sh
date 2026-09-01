#!/bin/bash
# Remove Playwright's --disable-dev-shm-usage from the bundled Chrome launch
# defaults on tony-dell. tony-dell has a 7.5G /dev/shm, so the flag only slows
# things down.

BUNDLE=/home/tony/.local/playlive/node_modules/playwright-core/lib/coreBundle.js

if [ ! -f "$BUNDLE" ]; then
    echo "playwright coreBundle not found: $BUNDLE" >&2
    exit 0
fi

# remove the flag and its trailing comma if present, and warn if already absent
if grep -q -- '--disable-dev-shm-usage' "$BUNDLE"; then
    python3 -c "
import sys
path = '$BUNDLE'
with open(path) as f:
    text = f.read()
with open(path, 'w') as f:
    f.write(text.replace('      "--disable-dev-shm-usage",
', ''))
print('patched', path)
"
else
    echo "--disable-dev-shm-usage already absent; nothing to patch" >&2
fi
