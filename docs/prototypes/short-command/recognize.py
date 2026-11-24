#!/usr/bin/env python3
"""CLI for the short command recognizer.

    python3 recognize.py "turn on the kitchen light"
    echo "กี่โมงแล้ว" | python3 recognize.py --stdin
    python3 recognize.py --trace "explain 0905"

Env knobs:
    SCR_COMMANDS   path to commands.json (default: alongside this file)
    SCR_EMBED_URL  optional embedding endpoint for T1 (POST {"text"} ->
                   {"embedding": [...]}); unset = lexical scorer
    SCR_ROUTER_URL optional local-LLM router for T2; unset = disabled
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scr import Recognizer

COMMANDS = os.environ.get(
    "SCR_COMMANDS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "commands.json"))


def main(argv):
    trace = "--trace" in argv
    args = [a for a in argv[1:] if a != "--trace"]
    r = Recognizer(COMMANDS)
    if "--stdin" in args:
        lines = [l.rstrip("\n") for l in sys.stdin if l.strip()]
    elif args:
        lines = [" ".join(args)]
    else:
        print(__doc__)
        return 2
    for line in lines:
        res = r.recognize(line)
        print(json.dumps({"input": line, **res}, ensure_ascii=False))
        if trace and res["status"] != "no_match":
            print("  -> %s via %s (score=%s, %sms)"
                  % (res["intent"], res["tier"], res["score"],
                     res["elapsed_ms"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
