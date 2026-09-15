#!/usr/bin/env python3
"""Stub `devin` binary for the devin-cli v0 demo."""
import sys
import time
import textwrap

def parse_args(argv):
    """Drop -p, --print, --permission-mode, and --, return the prompt."""
    prompt_words = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ('-p', '--print'):
            i += 1
            continue
        if arg == '--permission-mode' and i + 1 < len(argv):
            i += 2
            continue
        if arg.startswith('--permission-mode='):
            i += 1
            continue
        if arg == '--':
            i += 1
            while i < len(argv):
                prompt_words.append(argv[i])
                i += 1
            break
        if arg.startswith('-'):
            i += 1
            continue
        prompt_words.append(arg)
        i += 1
    return ' '.join(prompt_words) if prompt_words else '(no prompt)'

def main():
    prompt = parse_args(sys.argv[1:])

    print("Welcome to Devin CLI!")
    print()
    sys.stdout.flush()
    time.sleep(0.1)

    print(f"Prompt: {prompt}")
    print("Mode: normal")
    print()
    sys.stdout.flush()
    time.sleep(0.2)

    print("Thinking...")
    sys.stdout.flush()
    time.sleep(0.4)

    for action in ("Reading workspace files", "Planning changes", "Writing response"):
        print(f"  * {action}")
        sys.stdout.flush()
        time.sleep(0.3)

    print()
    print(textwrap.dedent(f"""\
        Hello! This is the **v0 stub** for the Devin CLI miniapp.

        You asked: "{prompt}"

        In a real setup, the local `devin -p` command would run here and
        stream back its actual output. For now, this stub lets you see how
        the web UI gives a command, watches progress, and receives the
        response.
    """))
    sys.stdout.flush()

if __name__ == '__main__':
    main()
