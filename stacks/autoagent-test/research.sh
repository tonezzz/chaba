#!/bin/bash
# Hands-off research script - sends query and auto-exits

QUERY="${1:-research topic}"
echo -e "$QUERY\nexit\nexit" | auto deep-research --local_env True 2>&1
