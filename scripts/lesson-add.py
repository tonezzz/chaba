#!/usr/bin/env python3
"""File a lesson into WP lesson CPT — Tony's education ledger.

One post per topic (slug lesson-<md5>): re-asking the same topic UPDATES the
post instead of forking. Agents (Devin/Ada) call this whenever Tony asks a
knowledge question worth retaining.

Usage:
  lesson-add.py --topic "cloud object storage" --level intro \
      --source chat --content-file /tmp/lesson.html [--next-review 2026-11-15]

Requires ~/.config/secrets/wp-boards.env (WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD).
Thai translation appended by default (--no-th to skip) via gemini_rest
flash-lite — lessons are bilingual surfaces, not EN-only.
"""
import argparse, base64, hashlib, json, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ada"))

ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"


def load_env(p):
    env = {}
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class WP:
    def __init__(self):
        env = load_env(ENV_PATH)
        self.base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'.encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": "chaba-lessons/1.0"}

    def api(self, route, data=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(u, data=body, headers=self.h,
                                     method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=45).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--level", default="intro",
                    choices=["intro", "working", "deep"])
    ap.add_argument("--source", default="chat",
                    choices=["chat", "voice", "link"])
    ap.add_argument("--content-file", required=True)
    ap.add_argument("--next-review", default="",
                    help="ISO date; default = learned_at + 7d (first spaced review)")
    ap.add_argument("--status", default="open")
    ap.add_argument("--no-th", action="store_true",
                    help="skip Thai translation section")
    a = ap.parse_args()

    content = Path(a.content_file).read_text()
    if not a.no_th:
        try:
            import gemini_rest, os, re
            key = os.environ.get("GEMINI_API_KEY_FREE")
            if not key:
                found = {}
                for f in (os.path.expanduser("~/.config/secrets/mddb-gemini.env"),
                          os.path.expanduser("~/.config/secrets/gemini-keys.env"),
                          os.path.expanduser("~/.config/secrets/gemini-api-key.env")):
                    try:
                        for ln in open(f):
                            m = re.match(r"^(GEMINI_API_KEY_FREE|GOOGLE_API_KEY|GEMINI_API_KEY)=(.*)$", ln.strip())
                            if m:
                                found.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))
                    except OSError:
                        pass
                key = (found.get("GEMINI_API_KEY_FREE") or found.get("GOOGLE_API_KEY")
                       or found.get("GEMINI_API_KEY"))
                if not key:
                    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            th = gemini_rest.generate(
                "Translate the following HTML lesson to natural Thai. "
                "Keep HTML tags, code, URLs, and proper names verbatim. "
                "Output ONLY the translated HTML.\n\n" + content,
                "gemini-3.5-flash-lite", key=key)
            if th and th.strip():
                content += "\n<hr>\n<h3>ไทย</h3>\n" + th.strip()
        except Exception as e:
            print(f"th-translation skipped: {e}", file=sys.stderr)

    slug = "lesson-" + hashlib.md5(a.topic.strip().lower().encode()).hexdigest()[:12]
    wp = WP()
    payload = {
        "title": f"Education — {a.topic}",
        "slug": slug,
        "status": "private",
        "content": content,
        "meta": {
            "topic": a.topic,
            "level": a.level,
            "source": a.source,
            "learned_at": str(date.today()),
            "next_review": a.next_review or str(date.today() + timedelta(days=7)),
            "status": a.status,
        },
    }
    existing = wp.api(f"/wp/v2/lesson&slug={slug}&status=private")
    if existing:
        pid = existing[0]["id"]
        wp.api(f"/wp/v2/lesson/{pid}", payload)
        print(f"updated {slug} (post {pid})")
    else:
        r = wp.api("/wp/v2/lesson", payload)
        print(f"created {slug} (post {r.get('id')})")


if __name__ == "__main__":
    main()
