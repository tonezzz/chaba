#!/usr/bin/env python3
"""OpenAI provider for the devin-cli miniapp. Streams chat completion to stdout."""
import http.client
import json
import os
import sys


def main():
    prompt = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Hello'
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }).encode()

    conn = http.client.HTTPSConnection("api.openai.com")
    conn.request(
        "POST",
        "/v1/chat/completions",
        body,
        {
            "Authorization": f"Bearer {api_key}",
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
                delta = obj.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    print(text, end="", flush=True)
            except Exception:
                continue
    finally:
        conn.close()

    print()


if __name__ == "__main__":
    main()
