#!/usr/bin/env python3
"""News digest — cluster same-story `news` items, write a distilled parent
post per multi-source cluster, reparent the raw items under it.

WP is the filing cabinet; this script (idc03, systemd timer) is the analyst.
Parents carry the `synthesis` category + `digest`/`sources:N` tags; raw
children keep their desk categories and source tags.

Clustering: char-trigram Jaccard on normalized title+lead text — language
agnostic (works on Thai, which has no word boundaries). Union-find merge,
threshold --sim (default 0.30). Items already parented keep their parent
and can pull new members into that cluster.

LLM: gemini-3.5-flash-lite via scripts/ada/gemini_rest.py. Key from
GEMINI_API_KEY env, else ~/.config/secrets/mddb-gemini.env or
gemini-keys.env (FREE first). Prompt returns JSON {topic, brief, diffs[]}
which we render — the model never writes markup directly.

Usage:
    news-digest.py --dry-run              # show clusters, no writes/LLM
    news-digest.py                        # cluster + synthesize + reparent
    news-digest.py --hours 48 --sim 0.35

Env:
    WP_BOARDS_ENV   path to wp-boards.env (parsed, never sourced)
    GEMINI_API_KEY  or the secrets files above
"""
import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_rest

MODEL = os.environ.get("NEWS_DIGEST_MODEL", "gemini-3.5-flash-lite")
ENV_PATH = os.environ.get("WP_BOARDS_ENV",
                          os.path.expanduser("~/.config/secrets/wp-boards.env"))
SECRET_FILES = [os.path.expanduser("~/.config/secrets/mddb-gemini.env"),
                os.path.expanduser("~/.config/secrets/gemini-keys.env")]
TAG_RE = re.compile(r"<[^>]+>")
SYNTH_CAT = "synthesis"


def _load_env(path):
    env = {}
    try:
        for line in open(path):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _load_gemini_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for f in SECRET_FILES:
        env = _load_env(f)
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_FREE", "GOOGLE_API_KEY"):
            if env.get(k):
                return env[k]
    return None


class WP:
    def __init__(self):
        env = _load_env(ENV_PATH)
        self.base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'.encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": "chaba-news-digest/1.0"}
        self._cats = None
        self._tags = None

    def api(self, route, data=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(u, data=body, headers=self.h,
                                     method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=45).read())

    def cat_ids(self, slugs):
        if self._cats is None:
            self._cats = {c["slug"]: c["id"]
                          for c in self.api("/wp/v2/categories&per_page=100")}
        return [self._cats[s] for s in slugs if s in self._cats]

    def cat_names(self, ids):
        if self._cats is None:
            self.cat_ids([])
        by_id = {v: k for k, v in self._cats.items()}
        return [by_id.get(i, str(i)) for i in ids]

    def tag_ids(self, names):
        if self._tags is None:
            self._tags = {t["name"].lower(): t["id"]
                          for t in self.api("/wp/v2/tags&per_page=100")}
        ids = []
        for n in names:
            k = n.lower()
            if k not in self._tags:
                try:
                    self._tags[k] = self.api("/wp/v2/tags", {"name": n})["id"]
                except Exception as e:
                    print(f"  warn: tag {n!r} create failed: {e}",
                          file=sys.stderr)
                    continue
            ids.append(self._tags[k])
        return ids


def norm(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ",
                  html.unescape(s or ""))).strip().lower()


def trigrams(s):
    s = re.sub(r"\s+", " ", s)
    return {s[i:i+3] for i in range(len(s) - 2)} if len(s) > 2 else {s}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def cluster(items, threshold):
    """Union-find over trigram-Jaccard similarity of title+lead."""
    sigs = [trigrams(norm(f"{p['title']['rendered']} "
                        f"{p['content']['rendered'][:600]}"))
            for p in items]
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if jaccard(sigs[i], sigs[j]) >= threshold:
                union(i, j)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(items[i])
    return list(groups.values())


PROMPT = """You are a news-digest writer. Below are {n} items covering the same
story from different outlets (JSON list of {{source, title, text}}).

Return ONLY a JSON object:
{{"topic": "short story label (max ~8 words)",
  "brief": "2-3 sentence neutral synthesis of what happened",
  "diffs": ["one line per notable difference in coverage/framing — source name first"]}}

Items:
{items}"""


def synthesize(members, key):
    payload = [{"source": m.get("meta", {}).get("source_feed") or "feed",
                "title": norm(m["title"]["rendered"])[:200],
                "text": norm(m["content"]["rendered"])[:1200]}
               for m in members]
    out = gemini_rest.generate_json(
        PROMPT.format(n=len(members), items=json.dumps(payload,
                                                       ensure_ascii=False)),
        MODEL, key=key)
    return out or {}


def render_content(topic, brief, diffs, members):
    parts = [f"<p>{html.escape(brief)}</p>" if brief else ""]
    if diffs:
        lis = "".join(f"<li>{html.escape(d)}</li>" for d in diffs)
        parts.append(f"<p><strong>Coverage notes</strong></p><ul>{lis}</ul>")
    lis = "".join(
        f'<li><a href="{html.escape(m["link"])}">{html.escape(norm(m["title"]["rendered"])[:90])}</a>'
        f' — {html.escape(m.get("meta", {}).get("source_feed") or "feed")}</li>'
        for m in members)
    parts.append(f"<p><strong>Sources ({len(members)})</strong></p><ul>{lis}</ul>")
    return "\n".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--sim", type=float, default=0.30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wp = WP()
    after = (datetime.now(timezone.utc)
             - timedelta(hours=args.hours)).isoformat(timespec="seconds")
    posts = wp.api(f"/wp/v2/news&after={after}&per_page=100"
                   "&orderby=date&order=desc")
    # flat items only — digest parents also match /news, exclude by slug prefix
    items = [p for p in posts if not p["slug"].startswith("d-")]
    print(f"{len(items)} items since {after} ({len(posts)-len(items)} digests skipped)")

    groups = cluster(items, args.sim)
    groups = [g for g in groups
              if len({m.get("meta", {}).get("source_feed") for m in g}) >= 2]
    print(f"{len(groups)} multi-source clusters")

    synth_cat = wp.cat_ids([SYNTH_CAT])
    if not synth_cat and not args.dry_run:
        sys.exit(f"category {SYNTH_CAT!r} missing — create it first")

    made = upd = repar = 0
    for g in groups:
        slugs = sorted(m["slug"] for m in g)
        feeds = sorted({m.get("meta", {}).get("source_feed") or "?" for m in g})
        if args.dry_run:
            print(f"\n  cluster ({len(g)} items, {len(feeds)} feeds) {feeds}")
            for m in g:
                print(f"    - {norm(m['title']['rendered'])[:80]}")
            continue

        # reuse an existing parent when cluster members already share one
        parent_ids = [m["parent"] for m in g if m.get("parent")]
        parent_id = max(set(parent_ids), key=parent_ids.count) \
            if parent_ids else None

        res = synthesize(g, _load_gemini_key())
        topic = res.get("topic") or norm(g[0]["title"]["rendered"])[:60]
        brief = res.get("brief") or ""
        diffs = res.get("diffs") or []
        content = render_content(topic, brief, diffs, g)
        cats = sorted({c for m in g for c in m.get("categories", [])})
        member_tag_ids = sorted({t for m in g for t in m.get("tags", [])})
        payload = {
            "title": f"Digest — {topic}",
            "status": "publish",
            "content": content,
            "categories": sorted(set(cats) | set(synth_cat)),
            "tags": member_tag_ids + wp.tag_ids(
                ["digest", f"sources:{len(feeds)}"]),
            "meta": {"source_feed": "+".join(feeds),
                     "source_url": "", "published_at": ""},
        }
        try:
            if parent_id:
                wp.api(f"/wp/v2/news/{parent_id}", payload)
                upd += 1
            else:
                slug = "d-" + hashlib.md5("|".join(slugs).encode()).hexdigest()
                parent_id = wp.api("/wp/v2/news", {**payload,
                                                   "slug": slug})["id"]
                made += 1
            for m in g:
                if m.get("parent") != parent_id:
                    wp.api(f"/wp/v2/news/{m['id']}", {"parent": parent_id})
                    repar += 1
            print(f"  digest {parent_id}: {topic!r} ({len(g)} sources/items)")
        except Exception as e:
            print(f"  warn: digest write failed: {e}", file=sys.stderr)
    print(f"total: {made} new digests, {upd} updated, {repar} reparented")


if __name__ == "__main__":
    main()
