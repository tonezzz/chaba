#!/usr/bin/env python3
"""Generate/verify stacks/web/public/apps/apps.yml from the public app directories."""
import argparse
import re
import subprocess
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
APPS_DIR = REPO / "stacks" / "web" / "public" / "apps"
APPS_YML = APPS_DIR / "apps.yml"
BASE_URL = "https://tony-dell.taila0626a.ts.net"
SKIP_PATHS = {"", ".", "shared", "shared/js", "shared/tests"}
SKIP_PATTERNS = ["yomi/media", "yomi/fetch-data", "trade/data/imported"]


def app_id_from_path(rel):
    return rel.replace("/", "-")


def href_from_path(rel):
    return f"/apps/{rel}/"


def parse_index_html(index_html):
    text = index_html.read_text(encoding="utf-8", errors="ignore")
    title_match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
    desc_match = re.search(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    )
    if not desc_match:
        desc_match = re.search(
            r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
            text,
            re.IGNORECASE,
        )
    title = title_match.group(1).strip() if title_match else None
    description = desc_match.group(1).strip() if desc_match else None
    return title, description


def should_skip(rel):
    if rel in SKIP_PATHS:
        return True
    for pat in SKIP_PATTERNS:
        if pat in rel:
            return True
    return False


def discover_apps():
    apps = []
    for index_html in APPS_DIR.rglob("index.html"):
        rel = index_html.parent.relative_to(APPS_DIR).as_posix()
        if should_skip(rel):
            continue
        title, description = parse_index_html(index_html)
        if not title:
            continue
        apps.append(
            {
                "id": app_id_from_path(rel),
                "title": title,
                "description": description or f"{title} app",
                "icon": "📱",
                "href": href_from_path(rel),
                "rel": rel,
            }
        )
    return sorted(apps, key=lambda a: a["id"])


def load_apps_yml():
    if not APPS_YML.exists():
        return {"title": "Apps", "nav": [], "apps": []}
    return yaml.safe_load(APPS_YML.read_text())


def save_apps_yml(data):
    APPS_YML.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def generate():
    data = load_apps_yml()
    discovered = discover_apps()
    existing_by_href = {a["href"]: a for a in data.get("apps", [])}
    existing_by_id = {a["id"]: a for a in data.get("apps", [])}

    merged = []
    for app in discovered:
        href = app["href"]
        rel = app.pop("rel", None)
        existing = existing_by_href.get(href)
        if existing:
            # preserve the existing id/icon, but refresh title/description from the page
            existing.setdefault("title", app["title"])
            existing.setdefault("description", app["description"])
            if not existing.get("title"):
                existing["title"] = app["title"]
            if not existing.get("description"):
                existing["description"] = app["description"]
            if not existing.get("icon"):
                existing["icon"] = app["icon"]
            merged.append(existing)
        else:
            # only auto-add top-level apps, not nested ones that haven't been manually registered
            if "/" in rel:
                print(f"[skip] {app['id']}: {app['title']} ({href}) — nested, not in apps.yml")
                continue
            merged.append(app)
            print(f"[+] {app['id']}: {app['title']} -> {href}")

    # keep any existing apps that are not directory-based (e.g. proxy apps)
    for existing in data.get("apps", []):
        if not any(a.get("href") == existing["href"] for a in merged):
            merged.append(existing)

    data["apps"] = sorted(merged, key=lambda a: a.get("id", ""))
    save_apps_yml(data)
    print(f"Wrote {len(merged)} apps to {APPS_YML}")


def verify(local=True, live=False, timeout=5):
    data = load_apps_yml()
    apps = data.get("apps", [])
    errors = []
    warnings = []

    ids = set()
    hrefs = set()
    for app in apps:
        if app["id"] in ids:
            errors.append(f"Duplicate id: {app['id']}")
        if app["href"] in hrefs:
            errors.append(f"Duplicate href: {app['href']}")
        ids.add(app["id"])
        hrefs.add(app["href"])

    if local:
        for app in apps:
            href = app["href"]
            if not href.startswith("/apps/"):
                continue
            rel = href[len("/apps/"):].strip("/")
            local_path = APPS_DIR / rel / "index.html"
            if not local_path.exists():
                warnings.append(f"{app['id']} ({href}) has no local index.html (may be a proxy app)")

    if live:
        urls = [f"{BASE_URL}{app['href']}" for app in apps]
        results = {}

        def check(url):
            try:
                out = subprocess.run(
                    ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout), url],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 2,
                )
                return int(out.stdout.strip()) if out.stdout.strip().isdigit() else 0
            except Exception as e:
                return f"err: {e}"

        with ThreadPoolExecutor(max_workers=8) as ex:
            future_to_url = {ex.submit(check, url): url for url in urls}
            for future in future_to_url:
                results[future_to_url[future]] = future.result()

        for app in apps:
            url = f"{BASE_URL}{app['href']}"
            code = results.get(url, "?")
            if code != 200:
                errors.append(f"{app['id']}: {url} -> {code}")
            else:
                print(f"[OK] {app['id']}: {url}")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("\nVerify passed")


def main():
    parser = argparse.ArgumentParser(description="Manage the public apps.yml list.")
    parser.add_argument("--generate", "-g", action="store_true", help="Update apps.yml from directories")
    parser.add_argument("--verify", "-v", action="store_true", help="Verify apps.yml consistency")
    parser.add_argument("--live", "-l", action="store_true", help="Also do live HTTP checks (requires --verify)")
    parser.add_argument("--timeout", "-t", type=int, default=5, help="HTTP timeout for live checks")
    args = parser.parse_args()

    if args.generate:
        generate()
    if args.verify:
        verify(local=True, live=args.live, timeout=args.timeout)


if __name__ == "__main__":
    main()
