#!/usr/bin/env python3
"""News situations — flag, promote, index (card news-situation-summaries).

Digest parents on the WP `news` CPT already ARE evolving topic summaries
(topic/brief/diffs/Developments from news-digest.py). A "situation" is a
digest the household is tracking — flagged via meta `situation` =
watching|pinned, mirrored as the `situation-watching` / `situation-pinned`
post_tag so the flag works before chaba-boards 0.6.0 deploys (meta keys are
unregistered until then and REST silently drops them).

Signals are additive and never silent — every transition posts a WP comment
on the digest naming the actor and reason:

  auto-nominate   sweep: multi-source (>= --sources feeds) or disaster-desk
                  digests get watching. Never pins, never demotes.
  member-ask      ask "<text>": match the ask to a digest (embedding cosine,
                  ngram fallback) and promote one step — none->watching,
                  watching->pinned. Prints TH+EN briefs for the asker
                  (Ada/household reporting). Weak match -> exit 3, no write.
  comment         wp-comment-sync.py parses pin/unpin/watch commands on news
                  posts and calls the same transition path.
  sticky          pin also sets WP sticky so the digest floats on /wp/news/;
                  unpin/clear removes it.

Index: `index` upserts a private WP page (slug `situations`, TH-first) that
household members read at /wp/; the [chaba_situations] shortcode renders
the same list inside any page.

Usage:
    news-situation.py list [--json]
    news-situation.py set <id|slug> <watching|pinned|none> [--by X] [--note T]
    news-situation.py promote <id|slug> [--by X] [--note T]
    news-situation.py demote  <id|slug> [--by X] [--note T]
    news-situation.py ask "สรุปข่าวน้ำท่วม" [--by tony] [--json] [--dry-run]
    news-situation.py sweep [--sources 3] [--dry-run]
    news-situation.py index [--slug situations] [--dry-run]

Env:
    WP_BOARDS_ENV   path to wp-boards.env (parsed, never sourced)
"""
import argparse
import base64
import html
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ENV_PATH = os.environ.get(
    "WP_BOARDS_ENV",
    os.path.expanduser("~/.config/secrets/wp-boards.env"))
ICT = timezone(timedelta(hours=7))
UA = "chaba-news-situation/1.0"
TAG_RE = re.compile(r"<[^>]+>")
STATES = ("watching", "pinned")        # additive ladder order
TAG_FOR = {"watching": "situation-watching", "pinned": "situation-pinned"}
SITUATION_TAGS = set(TAG_FOR.values())
INDEX_SLUG = "situations"
ASK_THRESHOLD = 0.55                   # cosine floor for ask->digest match
DISASTER_CAT = "disaster"              # desk slug auto-nominates watching
DIGEST_SLUG_RE = re.compile(r"^d-")


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


def _news_digest():
    """Import sibling news-digest.py for embed/cos/norm/trigram fallback."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "news-digest.py")
    spec = importlib.util.spec_from_file_location("news_digest", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class WP:
    def __init__(self):
        env = _load_env(ENV_PATH)
        for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
            if k not in env:
                raise SystemExit(f"missing {k} in {ENV_PATH}")
        self.base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'.encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": UA}
        self._cats = None
        self._tags = None

    def api(self, route, data=None, method=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            u, data=body, headers=self.h,
            method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(f"WP {method or 'GET'} {route}: "
                               f"{e.code} {detail}") from e

    def cat_names(self, ids):
        if self._cats is None:
            self._cats = {c["id"]: c["slug"]
                          for c in self.api("/wp/v2/categories&per_page=100")}
        return [self._cats.get(i, str(i)) for i in ids]

    def tag_ids(self, names):
        if self._tags is None:
            self._tags = {t["name"].lower(): t["id"]
                          for t in self.api("/wp/v2/tags&per_page=100")}
        ids = []
        for n in names:
            k = n.lower()
            if k not in self._tags:
                self._tags[k] = self.api("/wp/v2/tags", {"name": n})["id"]
            ids.append(self._tags[k])
        return ids

    def tag_names(self, ids):
        if self._tags is None:
            self.tag_ids([])
        by_id = {v: k for k, v in self._tags.items()}
        return [by_id.get(i, str(i)) for i in ids]


def strip(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(s or ""))).strip()


def brief_th_of(post):
    """Thai brief for a digest: meta.brief_th once chaba-boards 0.6.0
    registers the key; until then fall back to the สรุป paragraph
    news-digest renders into the post body."""
    m = ((post.get("meta") or {}).get("brief_th") or "").strip()
    if m:
        return m
    body = (post.get("content") or {}).get("rendered", "")
    hit = re.search(r'<p class="brief-th"[^>]*>\s*<strong>สรุป:</strong>\s*'
                    r"(.*?)</p>", body, re.S)
    return strip(hit.group(1)) if hit else ""


def effective_state(post, wp=None):
    """meta first, tag mirror second. '' = not a situation."""
    m = ((post.get("meta") or {}).get("situation") or "").strip().lower()
    if m in STATES:
        return m
    tags = post.get("_tag_names")
    if tags is None:
        ids = post.get("tags") or []
        tags = wp.tag_names(ids) if (wp and ids) else []
    return next((s for s in STATES if TAG_FOR[s] in tags), "")


def digest_posts(wp, hours=24 * 14, per_page=100):
    """Recently-modified digest parents (slug d-*) — the evolving summaries.
    modified_after (not after) so a long-running situation whose parent was
    created weeks ago stays in the window while it keeps updating."""
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)
             ).isoformat(timespec="seconds")
    posts = wp.api(f"/wp/v2/news&modified_after={after}&per_page={per_page}"
                   "&orderby=modified&order=desc")
    return [p for p in posts if DIGEST_SLUG_RE.match(p.get("slug") or "")]


def source_count(post):
    feeds = (post.get("meta") or {}).get("source_feed") or ""
    n = len([f for f in feeds.split("+") if f and f != "?"])
    if n:
        return n
    tags = post.get("_tag_names") or []
    counts = [int(t.split(":", 1)[1]) for t in tags
              if t.startswith("sources:") and t.split(":", 1)[1].isdigit()]
    return max(counts) if counts else 0


def comment(wp, post_id, text, dry_run=False):
    """Transition trail — every flag change is announced on the post."""
    if dry_run:
        print(f"  [dry] comment on {post_id}: {text}")
        return None
    try:
        return wp.api("/wp/v2/comments",
                      {"post": post_id, "content": text}).get("id")
    except Exception as e:
        print(f"  warn: comment on {post_id} failed: {e}", file=sys.stderr)
        return None


def sync_meta_from_tag(wp, post, state, dry_run=False):
    """Backfill registered meta when only the tag mirror holds the flag —
    flags set before chaba-boards 0.6.0 deployed had their meta silently
    dropped by REST (unregistered keys). Silent in WP: the transition
    comment was already posted, this is convergence not a transition.
    Returns True when a write was (or would be) made."""
    m = post.get("meta") or {}
    if (m.get("situation") or "").strip().lower() == state:
        return False
    if not dry_run:
        wp.api(f"/wp/v2/news/{post['id']}", {"meta": {
            "situation": state,
            "situation_since": m.get("situation_since")
                               or datetime.now(ICT).strftime("%Y-%m-%d %H:%M"),
            "situation_by": m.get("situation_by") or "tag-sync"}})
    return True


def set_state(wp, post, state, by="system", note="", dry_run=False):
    """Apply one ladder position: meta + tag mirror + sticky + comment.
    state '' clears. Idempotent — returns (old, new, changed)."""
    old = effective_state(post, wp)
    if old == state:
        if state:
            sync_meta_from_tag(wp, post, state, dry_run)
        return old, state, False

    pid = post["id"]
    # keep raw tag ids — only drop ids whose resolved name is a situation tag
    tag_ids_now = list(post.get("tags") or [])
    names_now = wp.tag_names(tag_ids_now)
    keep = [i for i, n in zip(tag_ids_now, names_now)
            if n not in SITUATION_TAGS]
    if state:
        keep += wp.tag_ids([TAG_FOR[state]])
    meta = {"situation": state, "situation_since": "", "situation_by": ""}
    if state:
        meta["situation_since"] = datetime.now(ICT).strftime("%Y-%m-%d %H:%M")
        meta["situation_by"] = by
    payload = {"tags": sorted(set(keep)), "meta": meta}
    if state == "pinned":
        payload["sticky"] = True
    elif old == "pinned" or not state:
        payload["sticky"] = False

    title = strip((post.get("title") or {}).get("rendered"))
    arrow = f"{old or '—'} → {state or '—'}"
    if not dry_run:
        try:
            wp.api(f"/wp/v2/news/{pid}", payload)
        except RuntimeError as e:
            # hierarchical CPTs reject `sticky` on some WP versions —
            # drop it and retry rather than lose the flag write.
            if "sticky" in payload and "sticky" in str(e):
                print("  warn: sticky unsupported on news — flag only",
                      file=sys.stderr)
                payload.pop("sticky")
                wp.api(f"/wp/v2/news/{pid}", payload)
            else:
                raise
    trail = f"situation {arrow} — by {by}"
    if note:
        trail += f" — {note}"
    comment(wp, pid, trail, dry_run)
    print(f"  {pid} {title[:60]!r}: {arrow} (by {by})")
    return old, state, True


def promote_step(state):
    return "pinned" if state == "watching" else ("watching" if not state
                                                 else "pinned")


def demote_step(state):
    return "watching" if state == "pinned" else ""


def find_post(wp, ident):
    if str(ident).isdigit():
        return wp.api(f"/wp/v2/news/{int(ident)}")
    r = wp.api(f"/wp/v2/news&slug={urllib.parse.quote(str(ident))}&per_page=1")
    if isinstance(r, list) and r:
        return r[0]
    raise SystemExit(f"no news post for {ident!r}")


# ---------------------------------------------------------------- commands

def cmd_list(wp, args):
    posts = digest_posts(wp)
    rows = []
    for p in posts:
        p["_tag_names"] = wp.tag_names(p.get("tags") or [])
        st = effective_state(p)
        if not st and not args.all:
            continue
        rows.append({"id": p["id"], "state": st or "—",
                     "sources": source_count(p),
                     "by": (p.get("meta") or {}).get("situation_by") or "",
                     "since": (p.get("meta") or {}).get("situation_since") or "",
                     "title": strip(p["title"]["rendered"]),
                     "link": p.get("link")})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("no situation digests")
    for r in rows:
        icon = {"pinned": "📌", "watching": "👁"}.get(r["state"], " ")
        print(f"{icon} {r['id']:<6} {r['state']:<8} src:{r['sources']:<2} "
              f"{r['title'][:80]}")
    return 0


def cmd_set(wp, args, verb=None):
    post = find_post(wp, args.ident)
    post["_tag_names"] = wp.tag_names(post.get("tags") or [])
    cur = effective_state(post)
    if verb == "promote":
        target = promote_step(cur)
    elif verb == "demote":
        target = demote_step(cur)
    else:
        target = "" if args.state in ("none", "clear", "") else args.state
        if target not in STATES and target != "":
            raise SystemExit(f"state must be watching|pinned|none")
    old, new, changed = set_state(wp, post, target, by=args.by,
                                  note=args.note, dry_run=args.dry_run)
    if not changed:
        print(f"  unchanged (already {new or '—'})")
    return 0


def cmd_ask(wp, args):
    """Member-ask hook: match ask text -> digest, promote one step,
    answer with the digest's briefs. This is the function Ada/agents call."""
    posts = digest_posts(wp)
    if not posts:
        print("no digests to match against", file=sys.stderr)
        return 3
    nd = _news_digest()
    ask_text = nd.norm(args.text)
    cand_texts = [nd.norm(strip(p["title"]["rendered"]) + " "
                            + strip((p.get("content") or {})
                                    .get("rendered", ""))[:400])
                  for p in posts]
    try:
        url, key = nd._load_litellm()
        embs = nd.embed([ask_text] + cand_texts, url, key)
        scores = [nd.cos(embs[0], e) for e in embs[1:]]
    except Exception as e:
        print(f"warn: embeddings unavailable ({e}) — ngram fallback",
              file=sys.stderr)
        a = nd.trigram_fallback(ask_text)
        scores = [len(a & nd.trigram_fallback(t))
                  / max(1, min(len(a), len(nd.trigram_fallback(t))))
                  for t in cand_texts]
    best = max(range(len(posts)), key=lambda i: scores[i])
    title = strip(posts[best]["title"]["rendered"])
    print(f"best match: [{scores[best]:.3f}] {posts[best]['id']} {title!r}")
    if scores[best] < args.threshold:
        print(f"below threshold {args.threshold} — no promotion "
              f"(suggestion-only: rerun with --threshold to override)")
        return 3

    post = posts[best]
    post["_tag_names"] = wp.tag_names(post.get("tags") or [])
    cur = effective_state(post)
    if args.dry_run:
        new = cur
        print(f"[dry] would promote {cur or '—'} -> {promote_step(cur)}")
    else:
        _, new, _ = set_state(wp, post, promote_step(cur), by=args.by,
                              note=f'member ask: "{args.text[:120]}"')
    meta = post.get("meta") or {}
    out = {"post_id": post["id"], "title": title, "link": post.get("link"),
           "state": new or cur, "score": round(scores[best], 3),
           "brief_th": brief_th_of(post),
           "brief_en": re.sub(r"</?[^>]+>", "",
                              (post.get("content") or {})
                              .get("rendered", "")).strip()[:400]}
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        if out["brief_th"]:
            print(f"TH: {out['brief_th']}")
        print(f"EN: {out['brief_en'][:300]}")
        print(f"-> {out['state']} {out['link']}")
    return 0


def cmd_sweep(wp, args):
    """Auto-nominate: multi-source or disaster-desk digests -> watching.
    Suggestion-only: never pins, never demotes, never touches flagged posts."""
    posts = digest_posts(wp)
    cats = wp.api("/wp/v2/categories&per_page=100")
    disaster_ids = {c["id"] for c in cats if c.get("slug") == DISASTER_CAT}
    disaster_ids |= {c["id"] for c in cats if c.get("parent") in disaster_ids}
    nom = synced = 0
    for p in posts:
        p["_tag_names"] = wp.tag_names(p.get("tags") or [])
        st = effective_state(p)
        if st:
            if sync_meta_from_tag(wp, p, st, dry_run=args.dry_run):
                synced += 1
                print(f"  {p['id']}: meta <- tag ({st})")
            continue
        why = []
        if source_count(p) >= args.sources:
            why.append(f"{source_count(p)} sources")
        if set(p.get("categories") or []) & disaster_ids:
            why.append("disaster desk")
        if not why:
            continue
        nom += 1
        set_state(wp, p, "watching", by="auto-nominate",
                  note=" + ".join(why), dry_run=args.dry_run)
    print(f"sweep: {nom} nominated, {synced} meta-backfilled "
          f"(of {len(posts)} digests)")
    return 0


def render_index(wp, rows):
    now = datetime.now(ICT).strftime("%Y-%m-%d %H:%M")
    def row(r):
        brief = r.get("brief_th") or r["meta"].get("brief_th") or ""
        icon = "📌" if r["state"] == "pinned" else "👁"
        s = (f'<li style="margin-bottom:.9em"><strong>'
             f'<a href="{html.escape(r["link"])}">{html.escape(r["title"])}'
             f'</a></strong> {icon}')
        if brief:
            s += f'<br><span lang="th">{html.escape(brief)}</span>'
        s += (f'<br><small style="opacity:.65">'
              f'{html.escape(r["state"])} · {r["sources"]} แหล่งข่าว'
              + (f' · ตั้งแต่ {html.escape(r["since"])}' if r["since"] else '')
              + (f' · โดย {html.escape(r["by"])}' if r["by"] else '')
              + '</small></li>')
        return s
    pinned = [r for r in rows if r["state"] == "pinned"]
    watching = [r for r in rows if r["state"] == "watching"]
    parts = ['<p lang="th"><strong>สถานการณ์ที่กำลังติดตาม</strong> — '
             'สรุปข่าวที่มีอัปเดตต่อเนื่อง (รวมจากหลายแหล่งข่าว)</p>']
    if pinned:
        parts.append("<h3>📌 ปักหมุด / Pinned</h3><ul>"
                     + "".join(row(r) for r in pinned) + "</ul>")
    if watching:
        parts.append("<h3>👁 เฝ้าระวัง / Watching</h3><ul>"
                     + "".join(row(r) for r in watching) + "</ul>")
    if not rows:
        parts.append("<p>ตอนนี้ไม่มีสถานการณ์ที่ติดตาม</p>")
    parts.append(
        f'<p><small>อัปเดต {now} น. (ICT) โดย news-situation.py — '
        'คอมเมนต์ "pin"/"unpin"/"watch" ใต้ข่าวเพื่อเปลี่ยนสถานะ · '
        'สถานการณ์ถูกเสนออัตโนมัติเมื่อข่าวมีหลายแหล่งหรืออยู่ในดูแลภัยพิบัติ'
        "</small></p>")
    return "\n".join(parts)


def cmd_index(wp, args):
    posts = digest_posts(wp)
    rows = []
    for p in posts:
        p["_tag_names"] = wp.tag_names(p.get("tags") or [])
        st = effective_state(p)
        if not st:
            continue
        meta = p.get("meta") or {}
        rows.append({"id": p["id"], "state": st, "meta": meta,
                     "brief_th": brief_th_of(p),
                     "sources": source_count(p),
                     "since": meta.get("situation_since") or "",
                     "by": meta.get("situation_by") or "",
                     "title": strip(p["title"]["rendered"]),
                     "link": p.get("link") or ""})
    rows.sort(key=lambda r: (r["state"] != "pinned", r["since"]), )
    content = render_index(wp, rows)
    if args.dry_run:
        print(content)
        return 0
    existing = wp.api(f"/wp/v2/pages&slug={args.slug}&status=private")
    payload = {"title": "Situations — สถานการณ์ที่กำลังติดตาม",
               "slug": args.slug, "status": "private", "content": content}
    if existing:
        wp.api(f"/wp/v2/pages/{existing[0]['id']}", payload)
        print(f"index: updated page {existing[0]['id']} "
              f"({len(rows)} situations)")
    else:
        r = wp.api("/wp/v2/pages", payload)
        print(f"index: created page {r.get('id')} ({len(rows)} situations)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true",
                   help="include unflagged digests")
    p.add_argument("--json", action="store_true")

    for name in ("set", "promote", "demote"):
        p = sub.add_parser(name)
        p.add_argument("ident", help="post id or slug")
        if name == "set":
            p.add_argument("state",
                           choices=["watching", "pinned", "none", "clear"])
        p.add_argument("--by", default="cli")
        p.add_argument("--note", default="")
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("ask")
    p.add_argument("text")
    p.add_argument("--by", default="member-ask")
    p.add_argument("--threshold", type=float, default=ASK_THRESHOLD)
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("sweep")
    p.add_argument("--sources", type=int, default=3,
                   help="auto-nominate digests with >= N source feeds")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("index")
    p.add_argument("--slug", default=INDEX_SLUG)
    p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    wp = WP()
    if args.cmd == "list":
        return cmd_list(wp, args)
    if args.cmd in ("set", "promote", "demote"):
        return cmd_set(wp, args, verb=None if args.cmd == "set" else args.cmd)
    if args.cmd == "ask":
        return cmd_ask(wp, args)
    if args.cmd == "sweep":
        return cmd_sweep(wp, args)
    if args.cmd == "index":
        return cmd_index(wp, args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
