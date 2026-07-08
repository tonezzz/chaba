#!/bin/bash
set -e

# Activate Python virtualenv for helper tools
if [ -f /workspace/john/run/venv/bin/activate ]; then
    . /workspace/john/run/venv/bin/activate
fi

# If no arguments, print help
if [ $# -eq 0 ]; then
    exec ./john --help
fi

# Convenience shortcuts for common subcommands
CMD="$1"
shift

case "$CMD" in
    shell)
        exec bash "$@"
        ;;
    test)
        exec ./john --test=0 "$@"
        ;;
    benchmark)
        exec ./john --test "$@"
        ;;
    *)
        exec ./john "$CMD" "$@"
        ;;
esac
