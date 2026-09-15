#!/usr/bin/env python3
"""Anthropic Claude provider for the devin-cli miniapp. Streams messages to stdout."""
import http.client
import json
import os
import sys


def main():
    prompt = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Hello'
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }).encode()

    conn = http.client.HTTPSConnection("api.anthropic.com")
    conn.request(
        "POST",
        "/v1/messages",
        body,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    resp = conn.getresponse()
    if resp.status != 200:
        print(f"Error: {resp.status} {resp.reason}", file=sys.stderr)
        err = resp.read().decode()
        if err:
            print(err, file=sys.stderr)
        sys.exit(1)

    try:
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode().strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                t = obj.get("type")
                text = ""
                if t == "content_block_delta":
                    text = obj.get("delta", {}).get("text", "")
                elif t == "content_block_start":
                    text = obj.get("content_block", {}).get("text", "")
                if text:
                    print(text, end="", flush=True)
            except Exception:
                continue
    finally:
        conn.close()

    print()


if __name__ == "__main__":
    main()
