# Justfile for chaba-h3 (Plesk static site)

_default:
    @just --list

# Build the legacy Reef Riders static mirror
build-reefriders:
    python3 scripts/reefriders/build.py

# Build the Reef Riders 01 static mirror
build-reefriders-01:
    python3 scripts/reefriders-01/build_new.py

# Start PHP dev server for local Plesk-like preview
serve-php:
    php -S 0.0.0.0:8123 -t public

# Build Tailwind CSS once
build-css:
    npm run build:css

# Watch and rebuild Tailwind CSS
watch-css:
    npm run watch:css

# Run Playwright end-to-end tests (starts PHP server, tears down after)
test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    cd /home/tony/CascadeProjects/chaba-h3
    npm run serve:php:quiet &
    server_pid=$!
    cleanup() { kill $server_pid 2>/dev/null || true; wait $server_pid 2>/dev/null || true; }
    trap cleanup EXIT
    for i in {1..30}; do
        if curl -s http://localhost:8123 >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    curl -s http://localhost:8123 >/dev/null 2>&1
    npx playwright test

# Run a single Playwright test file (example: raceman)
test-e2e-raceman:
    npx playwright test e2e/raceman.spec.js

# Show git status for deploy sanity check
deploy-status:
    git status
