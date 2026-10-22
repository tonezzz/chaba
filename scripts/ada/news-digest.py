#!/usr/bin/env python3
"""News digest — cluster same-story `news` items, write a distilled parent
post per multi-source cluster, reparent the raw items under it.

WP is the filing cabinet; this script (idc03, systemd timer) is the analyst.
Parents carry the `synthesis` category + `digest`/`sources:N` tags; raw
children keep their desk categories and source tags.

Clustering: embedding cosine similarity (ollama-nomic-embed via LiteLLM —
local, free; catches Thai paraphrases) over titles only (content embeddings
over-merge on shared boilerplate). Union-find merge, threshold --sim
(default 0.85). Falls back to char-4-gram containment when embeddings are
unavailable. Items already parented keep their parent and pull new members
into that cluster; the parent regenerates, so an evolving story (rate
2,000 -> 1,900 -> 1,800) grows a chronological "Developments" timeline
under one parent instead of forking digests.

LLM: two lanes (card chat-local-free-lane). English synthesis {topic,
brief, diffs[]} defaults to the `chat-local` LiteLLM alias (qwen2.5:7b on
idc02 — free) via scripts/ada/litellm_chat.py; the Thai brief_th is a
small gemini translate call of that brief (Thai output stays on gemini).
NEWS_DIGEST_LLM=gemini restores the old single-call path — and any
chat-local failure falls back to it automatically so a digest run never
stalls on the local lane. Gemini side: gemini-3.5-flash-lite via
scripts/ada/gemini_rest.py, key from GEMINI_API_KEY env, else
~/.config/secrets/mddb-gemini.env or gemini-keys.env (FREE first). The
model never writes markup directly.

Usage:
    news-digest.py --dry-run              # show clusters, no writes/LLM
    news-digest.py                        # cluster + synthesize + reparent
    news-digest.py --hours 48 --sim 0.35

Env:
    WP_BOARDS_ENV    path to wp-boards.env (parsed, never sourced)
    GEMINI_API_KEY   or the secrets files above
    NEWS_DIGEST_LLM  chat-local (default; any LiteLLM alias) | gemini
    LITELLM_URL/LITELLM_KEY  else read from mddb-gemini.env
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
import litellm_chat

MODEL = os.environ.get("NEWS_DIGEST_MODEL", "gemini-3.5-flash-lite")
# chat-local (default) = LiteLLM job-class alias -> qwen2.5:7b on idc02;
# "gemini" = legacy single-call synthesis.
DIGEST_LLM = os.environ.get("NEWS_DIGEST_LLM", "chat-local")
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


def trigram_fallback(s):
    s = re.sub(r"\s+", " ", s)
    return {s[i:i+4] for i in range(len(s) - 3)} if len(s) > 3 else {s}


def _load_litellm():
    env = _load_env(os.path.expanduser("~/.config/secrets/mddb-gemini.env"))
    return env.get("LITELLM_URL"), env.get("LITELLM_KEY")


def embed(texts, url, key):
    """OpenAI-style embeddings via LiteLLM (ollama-nomic-embed — local, free)."""
    req = urllib.request.Request(
        url.rstrip("/") + "/embeddings",
        data=json.dumps({"model": "ollama-nomic-embed",
                         "input": texts}).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return [x["embedding"] for x in d["data"]]


def cos(a, b):
    import math
    return (sum(x * y for x, y in zip(a, b))
            / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))))


def cluster(items, threshold):
    """Union-find over embedding cosine similarity of title+lead.
    Embeddings catch same-story paraphrases (Thai included) that literal
    overlap misses; ollama-nomic-embed keeps it free/local."""
    texts = [norm(p["title"]["rendered"]) for p in items]
    try:
        url, key = _load_litellm()
        embs = embed(texts, url, key)
        sim = lambda a, b: cos(embs[a], embs[b])
    except Exception as e:
        print(f"warn: embeddings unavailable ({e}) — ngram fallback",
              file=sys.stderr)
        sigs = [trigram_fallback(t) for t in texts]
        def sim(a, b):
            return len(sigs[a] & sigs[b]) / min(len(sigs[a]), len(sigs[b])) \
                if sigs[a] and sigs[b] else 0.0
        threshold = min(threshold, 0.40)
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
            if sim(i, j) >= threshold:
                union(i, j)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(items[i])
    return list(groups.values())


PROMPT = """You are a news-digest writer. Below are {n} items covering the same
ongoing story from different outlets (JSON list of {{date, source, title,
text}}), in chronological order. The items may be follow-up reports on one
evolving story — facts like figures, locations or status can change between
them (e.g. a dam discharge rate dropping from 1,900 to 1,800).

Return ONLY a JSON object:
{{"topic": "short story label (max ~8 words)",
  "brief": "2-3 sentence neutral synthesis of the LATEST state of the story, "
           "mentioning what changed most recently",
  "brief_th": "Thai translation/adaptation of brief — same facts, natural "
              "Thai for a household reader (2-3 sentences)",
  "diffs": ["one line per notable difference in coverage/framing or per "
            "material fact change between updates — source name first"]}}

Items:
{items}"""

# Local-lane variant — English fields only; brief_th comes from a small
# gemini translate call afterwards (Thai output stays on gemini).
PROMPT_LOCAL = """You are a news-digest writer. Below are {n} items covering the
same ongoing story from different outlets (JSON list of {{date, source,
title, text}}), in chronological order. The items may be follow-up reports
on one evolving story — facts like figures, locations or status can change
between them (e.g. a dam discharge rate dropping from 1,900 to 1,800).

Return ONLY a JSON object (no prose, no code fences):
{{"topic": "short story label (max ~8 words)",
  "brief": "2-3 sentence neutral synthesis of the LATEST state of the story, "
           "mentioning what changed most recently",
  "diffs": ["one line per notable difference in coverage/framing or per "
            "material fact change between updates — source name first"]}}

Items:
{items}"""

PROMPT_TH = """Translate this English news brief into natural Thai for a
household reader — same facts, 2-3 sentences. Reply with the Thai text only.

Brief:
{brief}"""


def _payload(members, text_len=1200):
    return json.dumps(
        [{"date": m.get("date", "")[:16],
          "source": m.get("meta", {}).get("source_feed") or "feed",
          "title": norm(m["title"]["rendered"])[:200],
          "text": norm(m["content"]["rendered"])[:text_len]}
         for m in members], ensure_ascii=False)


def _translate_th(brief, key):
    """brief -> Thai, gemini only. Gateway `summary` class first (paid
    quota + fallbacks — the free key 429s under batch load); direct
    generateContent as last resort."""
    out = litellm_chat.chat(
        PROMPT_TH.format(brief=brief), model="summary",
        temperature=0.2, max_tokens=400, timeout=90,
        label="news-digest-th")
    if out:
        return out
    return gemini_rest.generate(
        PROMPT_TH.format(brief=brief), MODEL, key=key,
        label="news-digest-th") or ""


def synthesize(members, key):
    """{topic, brief, brief_th, diffs} — EN fields via chat-local (free)
    when DIGEST_LLM names a LiteLLM alias, brief_th via a small gemini
    translate; DIGEST_LLM=gemini or a local-lane failure -> the legacy
    single gemini call that produces all fields at once."""
    if DIGEST_LLM.lower() not in ("gemini", "google"):
        # Bounded payload for the CPU lane: qwen2.5:7b on idc02's 4 cores
        # evals ~20 tok/s — a 3k-token prompt + 900-token cap ran 5-7min
        # and every call timed out (2026-10-16..22). ~8 items x 400 chars
        # keeps the lede of each report and lands well under num_ctx=4096.
        out = litellm_chat.chat_json(
            PROMPT_LOCAL.format(n=min(len(members), 8),
                                items=_payload(members[:8], 400)),
            model=DIGEST_LLM, temperature=0.2, max_tokens=600,
            timeout=600, label="news-digest")
        if out:
            out["brief_th"] = _translate_th(out.get("brief") or "", key) \
                if out.get("brief") else ""
            return out
        print("  warn: chat-local synthesis unavailable — gemini fallback",
              file=sys.stderr)
    out = gemini_rest.generate_json(
        PROMPT.format(n=len(members), items=_payload(members)), MODEL, key=key)
    return out or {}


def _when(m):
    # site-local publish time, e.g. "14 Oct 20:41"
    try:
        return datetime.strptime(m["date"], "%Y-%m-%dT%H:%M:%S") \
            .strftime("%d %b %H:%M")
    except (KeyError, ValueError):
        return "?"


def render_content(topic, brief, diffs, members, brief_th=""):
    members = sorted(members, key=lambda m: m.get("date", ""))
    parts = [f"<p>{html.escape(brief)}</p>" if brief else ""]
    if brief_th:
        parts.append(f'<p class="brief-th" lang="th">'
                     f"<strong>สรุป:</strong> {html.escape(brief_th)}</p>")
    if diffs:
        lis = "".join(f"<li>{html.escape(d)}</li>" for d in diffs)
        parts.append(f"<p><strong>Coverage notes</strong></p><ul>{lis}</ul>")
    lis = "".join(
        f'<li>{html.escape(_when(m))} — '
        f'<a href="{html.escape(m["link"])}">'
        f'{html.escape(norm(m["title"]["rendered"])[:90])}</a>'
        f' — {html.escape(m.get("meta", {}).get("source_feed") or "feed")}</li>'
        for m in members)
    parts.append(f"<p><strong>Developments</strong></p><ul>{lis}</ul>")
    return "\n".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--sim", type=float, default=0.85,
                    help="cosine threshold for embedding clustering "
                         "(ngram fallback uses containment ≤0.40)")
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
        brief_th = res.get("brief_th") or ""
        diffs = res.get("diffs") or []
        content = render_content(topic, brief, diffs, g, brief_th=brief_th)
        cats = sorted({c for m in g for c in m.get("categories", [])})
        member_tag_ids = sorted({t for m in g for t in m.get("tags", [])})
        keep_meta, keep_tags = {}, set()
        if parent_id:
            # A digest update replaces only the fields we send — but meta
            # and tags are whole-list fields: re-assert what the parent
            # already carries (situation flag, situation-* tag, brief_th)
            # so regeneration never silently drops the situation state.
            try:
                cur = wp.api(f"/wp/v2/news/{parent_id}")
                keep_meta = {k: v for k, v in (cur.get("meta") or {}).items()
                             if k.startswith("situation") or k == "brief_th"}
                keep_tags = set(cur.get("tags") or [])
            except Exception as e:
                print(f"  warn: parent {parent_id} re-read failed: {e}",
                      file=sys.stderr)
        payload = {
            "title": f"Digest — {topic}",
            "status": "publish",
            "content": content,
            "categories": sorted(set(cats) | set(synth_cat)),
            "tags": sorted(set(member_tag_ids) | keep_tags | set(
                wp.tag_ids(["digest", f"sources:{len(feeds)}"]))),
            "meta": {**keep_meta,
                     "source_feed": "+".join(feeds),
                     "source_url": "", "published_at": "",
                     "brief_th": brief_th or keep_meta.get("brief_th", "")},
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
