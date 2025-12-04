import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request

SECRET = "7d0bf0f6c1a94c19a8f5f0c771db22f2"
PAYLOAD = {
    "ref": "refs/heads/main",
    "repository": {"full_name": "tonezzz/chaba"}
}
URL = "https://node-1.h3.surf-thailand.com/hooks/deploy"

def main() -> int:
    data = json.dumps(PAYLOAD).encode("utf-8")
    signature = "sha256=" + hmac.new(SECRET.encode("utf-8"), data, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        URL,
        data=data,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
            "User-Agent": "cascade-bot",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"status={response.status}")
            print(body or "(empty body)")
            return 0
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        print(f"HTTPError status={err.code}")
        print(detail or "(no body)")
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Request failed: {exc}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
