#!/usr/bin/env python3
"""Compare old static HTML pages with their YAML/bserver counterparts.

Checks status codes and normalised visible text. Run from the project root.
"""
import sys
import urllib.request
from html.parser import HTMLParser

BASE_URL = "http://localhost:8080"
PAIRS = [
    ("decisions.html", "/decisions"),
    ("infrastructure.html", "/infrastructure"),
]
# Note: index.html vs / is intentionally different now (new content added on the YAML page).

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts = []
        self.skip_tags = {"script", "style"}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            self.texts.append(data)

def visible_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return " ".join(parser.texts).split()

def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return resp.read().decode("utf-8")

def main() -> int:
    failed = False
    for old_path, new_path in PAIRS:
        old_url = f"{BASE_URL}/{old_path}"
        new_url = f"{BASE_URL}{new_path}"
        print(f"Checking {old_path} vs {new_path} ...")
        try:
            old_html = fetch(old_url)
            new_html = fetch(new_url)
        except Exception as exc:
            print(f"  FAIL: {exc}")
            failed = True
            continue

        old_text = visible_text(old_html)
        new_text = visible_text(new_html)
        if old_text == new_text:
            print(f"  OK: visible text matches ({len(old_text)} tokens)")
        else:
            print(f"  DIFF: visible text differs")
            # Show a few sample tokens from each
            print(f"    old[:20]: {old_text[:20]}")
            print(f"    new[:20]: {new_text[:20]}")
            failed = True

    if failed:
        print("Some pages did not match.")
        return 1
    print("All checked pages match.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
