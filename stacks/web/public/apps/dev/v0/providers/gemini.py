#!/usr/bin/env python3
"""Google Gemini provider for the devin-cli miniapp. Streams generateContent to stdout."""
import http.client
import json
import os
import sys
import urllib.parse


def main():
    prompt = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Hello'
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }).encode()

    path = (
        f"/v1/models/gemini-2.5-flash:streamGenerateContent"
        f"?alt=sse&key={urllib.parse.quote(api_key)}"
    )

    conn = http.client.HTTPSConnection("generativelanguage.googleapis.com")
    conn.request(
        "POST",
        path,
        body,
        {
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
            try:
                obj = json.loads(data)
                candidates = obj.get("candidates", [])
                if candidates:
                    text = (
                        candidates[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if text:
                        print(text, end="", flush=True)
            except Exception:
                continue
    finally:
        conn.close()

    print()


if __name__ == "__main__":
    main()
