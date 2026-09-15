#!/bin/sh
# Pre-commit: validate SSOT YAML before allowing the commit.
set -e
REPO=/home/tony/CascadeProjects/chaba
node "$REPO/scripts/ssot-validate-all.mjs" >/dev/null
