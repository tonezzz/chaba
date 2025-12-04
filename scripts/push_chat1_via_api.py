import json
import pathlib
import sys
import urllib.error
import urllib.request

SITE = "chat1"
TONY_SECRET = "7d0bf0f6c1a94c19a8f5f0c771db22f2"
BASE_DIR = pathlib.Path("sites/tony/sites") / SITE
FILES = ["index.html", "style.css", "main.js"]
URL = "https://node-1.h3.surf-thailand.com/api/tony/deploy"

def build_payload():
    if not BASE_DIR.exists():
        raise SystemExit(f"Missing local directory: {BASE_DIR}")
    entries = []
    for relative in FILES:
        path = BASE_DIR / relative
        if not path.exists():
            raise SystemExit(f"Missing file: {path}")
        contents = path.read_text(encoding="utf-8")
        entries.append({
            "path": relative,
            "contents": contents,
            "encoding": "utf8"
        })
    return {
        "site": SITE,
        "clear": True,
        "files": entries
    }

def main():
    payload = build_payload()
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-tony-secret": TONY_SECRET,
            "User-Agent": "cascade-bot"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"status={response.status}")
            print(body or "(empty body)")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        print(f"HTTPError status={err.code}")
        print(detail or "(no body)")
        sys.exit(1)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Request failed: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
