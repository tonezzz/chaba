#!/usr/bin/env python3
"""Local Ollama provider for the devin-cli miniapp. Streams /api/generate to stdout."""
import http.client
import json
import os
import sys


def main():
    prompt = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Hello'
    model = os.environ.get('OLLAMA_MODEL', 'llama3.2')
    host = os.environ.get('OLLAMA_HOST', 'localhost:11434')

    # Strip scheme and trailing slash, then split host:port.
    host = host.replace('http://', '').replace('https://', '').rstrip('/')
    if ':' in host:
        host_name, port_str = host.rsplit(':', 1)
        try:
            port = int(port_str)
        except ValueError:
            host_name = host
            port = 11434
    else:
        host_name = host
        port = 11434

    body = json.dumps({"model": model, "prompt": prompt, "stream": True}).encode()
    conn = http.client.HTTPConnection(host_name, port)
    conn.request("POST", "/api/generate", body, {"Content-Type": "application/json"})

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
            try:
                obj = json.loads(line.decode().strip())
            except Exception:
                continue
            text = obj.get("response", "")
            if text:
                print(text, end="", flush=True)
            if obj.get("done"):
                break
    finally:
        conn.close()

    print()


if __name__ == "__main__":
    main()
