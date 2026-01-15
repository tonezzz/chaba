#!/usr/bin/env bash
set -euo pipefail

export STACK=pc1-stack
exec bash ./scripts/stack-self.sh
