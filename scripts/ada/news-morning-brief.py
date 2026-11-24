#!/usr/bin/env python3
"""AI/model/provider morning brief — daily private WP page + on-demand query
(card ai-news-education-morning-brief; procedure docs/kb/ai-news-to-
education-procedure.md).

Integrates with the existing news pipeline instead of a parallel store:
raw AI stories arrive in the `news` CPT via wp-news-fetch (AI feeds in
news-feeds.json), digests via wp-news-digest, situations via
wp-news-situation. This script only READS that CPT, writes ONE private
page (slug `ai-morning-brief`), and files durable lesson updates through
the board-api /lesson door.

Fixed brief sections (procedure doc):
  60-second scan / model-provider watch table / what changed for us
  (video, Gaussian/4D, local+Colab+Nest, Ada) / TRY-WATCH-NO-ACTION /
  sources+confidence / Education updates.

LLM drafts prose via the chat-local LiteLLM lane (free) with a gemini
fallback; deterministic code owns links, dates, dedup and the page
skeleton. If every LLM lane fails the page still publishes from raw
fields only — the generator never blocks the timer on a model.

Usage:
    news-morning-brief.py brief [--hours 30] [--dry-run]
                               [--no-lessons] [--max-lesson-updates 2]
    news-morning-brief.py ask "is the new qwen worth trying" [--json]
    news-morning-brief.py verify [--slug ai-morning-brief]
    news-morning-brief.py lesson-update --topic "..." --note "..." \
        [--link URL ...] [--dry-run]

Env:
    WP_BOARDS_ENV   path to wp-boards.env (parsed, never sourced)
    BOARD_API       board-api base (default tailnet idc03:10000)
    WP_PUBLIC_BASE  consumer base for private pages
                    (default https://boards.surf-thailand.com/wp)
"""
import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_rest
import litellm_chat

ICT = timezone(timedelta(hours=7))
BRIEF_SLUG = "ai-morning-brief"
BRIEF_TITLE = "AI morning brief"
PUBLIC_BASE = os.environ.get(
    "WP_PUBLIC_BASE", "https://boards.surf-thailand.com/wp").rstrip("/")
API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
MODEL = os.environ.get("NEWS_BRIEF_MODEL", "gemini-3.5-flash-lite")
LLM_MODEL = os.environ.get("NEWS_BRIEF_LLM", "chat-local")
AI_FEED_RE = re.compile(r"(?:^|[+-])(?:gn-ai-[\w-]+|hf-blog\w*)")
AI_RE = re.compile(
    r"\b(ai|llm|gpt|gemini|claude|chatgpt|openai|anthropic|deepmind|"
    r"llama|mistral|qwen|deepseek|gemma|sora|veo|runway|kling|hailuo|"
    r"diffusion|text-to-|image gen|video gen|gaussian splat|nerf|3dgs|"
    r"vllm|ollama|embedding|fine-?tun|lora|whisper|stable diffusion|"
    r"multimodal|reasoning model|foundation model|model release|"
    r"benchmark|inference|nvidia|gpu|accelerator)\b", re.I)
TAG_RE = re.compile(r"<[^>]+>")
MAX_CANDIDATES = 24
MAX_LESSON_UPDATES = 2


def _load_sibling(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _strip(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(s or ""))) \
        .strip()


def _when(iso):
    try:
        return datetime.fromisoformat(
            str(iso).replace("Z", "+00:00")).astimezone(ICT) \
            .strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(iso or "")[:16]


def _ba(path, body, timeout=60):
    """board-api JSON call (the unified mutation/read door)."""
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        return {"ok": False, "error": f"HTTP {e.code} {detail}"}
    except OSError as e:
        return {"ok": False, "error": f"unreachable: {e}"}


# ---------------------------------------------------------------- WP reads

def _ai_relevant(post, tag_names):
    feeds = str((post.get("meta") or {}).get("source_feed") or "")
    if AI_FEED_RE.search(feeds):
        return True
    title = _strip((post.get("title") or {}).get("rendered"))
    if AI_RE.search(title):
        return True
    tags = tag_names or []
    return any(t in ("ai", "ai-models", "llm") for t in tags)


def collect_candidates(ns_wp, hours):
    """AI-relevant news items + digest parents in the window.

    Raw children of an in-window digest are covered by the parent — only
    parent==0 items are added so nothing double-counts."""
    after = (datetime.now(timezone.utc)
             - timedelta(hours=hours)).isoformat(timespec="seconds")
    posts = ns_wp.api(f"/wp/v2/news&after={after}&per_page=100"
                      "&orderby=date&order=desc")
    out = []
    for p in posts:
        tags = ns_wp.tag_names(p.get("tags") or [])
        if not _ai_relevant(p, tags):
            continue
        slug = p.get("slug") or ""
        if slug.startswith("d-"):
            kind = "digest"
        elif p.get("parent"):
            continue                      # covered by its digest parent
        else:
            kind = "item"
        meta = p.get("meta") or {}
        out.append({
            "id": p["id"], "slug": slug, "kind": kind,
            "title": _strip((p.get("title") or {}).get("rendered")),
            "link": p.get("link") or "",
            "source": meta.get("source_feed") or "feed",
            "date": p.get("date") or "",
            "brief": _strip((p.get("content") or {}).get("rendered"))[:400],
        })
    out.sort(key=lambda c: c["date"], reverse=True)
    return out[:MAX_CANDIDATES]


# ------------------------------------------------------------------ lessons

def lesson_rows():
    r = _ba("/lesson", {"op": "list", "limit": 500})
    if not r.get("ok", True) and "lessons" not in r:
        return []
    return r.get("lessons") or []


def lesson_url(row):
    if row.get("url"):
        return row["url"]
    return f"{PUBLIC_BASE}/lesson/{row.get('slug')}/"


def lesson_match(cands, rows, top=3):
    """Deterministic topic<->lesson overlap — which existing Education
    lessons today's AI news touches."""
    text = " ".join(c["title"] for c in cands).lower()
    words = {w for w in re.split(r"[^a-z0-9]+", text) if len(w) >= 4}
    scored = []
    for r in rows:
        topic = (r.get("topic") or "").lower()
        tw = {w for w in re.split(r"[^a-z0-9]+", topic) if len(w) >= 4}
        # hyphenated topic parts also count as single tokens
        score = len(words & tw)
        if score >= 2:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top]]


def _slugify_topic(topic):
    return "lesson-" + hashlib.md5(topic.lower().encode()).hexdigest()[:12]


def _wikitext_safe(s):
    """LLM prose -> safe wikitext bullet text (no markup injection)."""
    s = _strip(s)
    for bad in ("[[", "]]", "{{", "}}", "<", ">"):
        s = s.replace(bad, " ")
    lines = [re.sub(r"^[=*:#{|\s]+", "", ln) for ln in s.splitlines()]
    return re.sub(r"[ \t]+", " ", " ".join(lines)).strip()


def lesson_update(topic, note, links, dry_run=False):
    """Append a dated 'News watch' section to an EXISTING lesson via the
    /lesson door (upsert by topic slug; mddb mirror stays fresh).

    source=wiki rows return wikitext — the appended block is written in
    wikitext and rides the door's html->wikitext pass (wikitext text
    survives that converter verbatim). source=wp rows get an HTML
    block. Lessons that do not exist are never created here."""
    slug = _slugify_topic(topic)
    got = _ba("/lesson", {"op": "get", "slug": slug})
    if not got.get("content"):
        return {"topic": topic, "status": "skipped",
                "reason": got.get("error") or "lesson not found"}
    content = got["content"]
    meta = got.get("meta") or {}
    src = got.get("source") or "wp"
    today = datetime.now(ICT).strftime("%Y-%m-%d")
    # dedupe on the heading text — it survives the door's html->wikitext
    # pass, unlike an HTML comment which the converter may drop
    marker = f"News watch — {today}"
    if marker in content:
        return {"topic": topic, "status": "skipped",
                "reason": "already updated today"}
    link_html = "".join(
        f'<li><a href="{html.escape(u)}">{html.escape(t)}</a></li>'
        for t, u in links)
    if src == "wiki":
        note_wt = _wikitext_safe(note)
        src_wt = "; ".join(
            f"[{u} {t}]" for t, u in links) or "(no links)"
        block = (f"\n\n== {marker} ==\n"
                 f"* {note_wt}\n* Sources: {src_wt}\n")
    else:
        block = (f'\n<h3>{marker}</h3>\n'
                 f"<p>{html.escape(_strip(note))}</p>\n<ul>{link_html}</ul>\n")
    merged = content.rstrip() + block
    if dry_run:
        return {"topic": topic, "status": "dry-run",
                "store": src, "appended": block[:200]}
    lsrc = meta.get("source") or ""
    lvl = meta.get("level") or ""
    body = {"topic": topic,
            "level": lvl if lvl in ("intro", "working", "deep")
                     else "working",
            "source": lsrc if lsrc in ("chat", "voice", "link") else "link",
            "content": merged,
            "status": meta.get("status") or "open",
            # wiki rows already carry their ไทย section in the wikitext
            # body; skipping the door's full-content re-translate keeps
            # the free-tier budget and preserves the section as-is.
            "no_th": src == "wiki"}
    r = _ba("/lesson", body)
    if r.get("error") and not r.get("slug"):
        return {"topic": topic, "status": "error",
                "reason": r.get("error")}
    return {"topic": topic, "status": r.get("action") or "updated",
            "store": src, "slug": r.get("slug"),
            "wiki_title": r.get("wiki_title") or got.get("wiki_title"),
            "url": r.get("url") or got.get("url")}


# ------------------------------------------------------------------- LLM

PROMPT = """You are the morning AI/model/provider analyst for a home lab
(video generation, Gaussian splatting, local LLMs, Colab, Nest jobs, an
voice assistant "Ada"). Below are {n} recent AI-relevant news items from
the household news store (JSON: i, kind, title, source, brief).

Return ONLY a JSON object (no prose, no code fences):
{{"scan": ["3 short bullets: what changed and why it matters"],
 "watch": [{{"i": <item index>, "model": "...", "provider": "...",
            "modality": "text|image|video|audio|3d|other",
            "efficiency": "measured/claimed efficiency note or empty",
            "use": "what we could use it for",
            "cost": "price/free-quota note or empty",
            "hardware": "relevant hardware or empty",
            "decision": "try|watch|no-action",
            "why": "one line",
            "confidence": "high|medium|low"}}],
 "impacts": {{"video": "one line or empty",
              "gaussian": "one line or empty",
              "local": "one line or empty (local/Colab/Nest)",
              "ada": "one line or empty (Ada/Chaba ops)"}},
 "education": [{{"topic": "<exact topic from the LESSONS list>",
                 "note": "why this lesson is relevant today"}}],
 "lesson_updates": [{{"topic": "<exact topic from the LESSONS list>",
                      "note": "2-3 sentence durable comparison/fact worth
                               appending to that lesson (no URLs — the
                               renderer adds source links)",
                      "refs": [<item indices that support it>]}}]}}

Rules: only include items that represent a real model/provider change —
exclude generic hype with no measurable difference. At most 8 watch rows,
3 education rows, 2 lesson_updates. Every lesson topic MUST come verbatim
from the LESSONS list or be omitted.

ITEMS:
{items}

LESSONS (topic — level):
{lessons}"""


def _payload(cands):
    return json.dumps(
        [{"i": i, "kind": c["kind"], "title": c["title"][:160],
          "source": c["source"], "brief": c["brief"][:240]}
         for i, c in enumerate(cands)], ensure_ascii=False)


def synthesize(cands, lesson_topics):
    """LLM draft -> dict, or None. chat-local first (free), gemini
    fallback; both bounded so a slow lane can't stall the timer."""
    lessons = "\n".join(f"- {t}" for t in lesson_topics) or "(none)"
    prompt = PROMPT.format(n=len(cands), items=_payload(cands),
                           lessons=lessons)
    out = litellm_chat.chat_json(
        prompt, model=LLM_MODEL, temperature=0.2, max_tokens=1600,
        timeout=300, label="news-brief",
        tags="service=news-brief,job=wp-news-morning-brief,route=synth")
    if out:
        return out, "chat-local"
    print("  warn: chat-local unavailable — gemini fallback", file=sys.stderr)
    key = None
    try:
        nd = _load_sibling("news-digest.py")
        key = nd._load_gemini_key()
    except Exception:
        pass
    out = gemini_rest.generate_json(
        prompt, MODEL, key=key, timeout=180,
        tags="service=news-brief,job=wp-news-morning-brief,route=synth")
    return (out, "gemini") if out else (None, "none")


# ----------------------------------------------------------------- render

def render_brief(cands, res, edu_rows, edu_notes, lesson_results,
                 fallback, now):
    esc = html.escape
    parts = [f"<h1>AI + technology morning brief — "
             f"{now.strftime('%Y-%m-%d')}</h1>"]
    if fallback:
        parts.append('<p><em>Deterministic fallback — the LLM lanes were '
                     'unavailable; sections show raw fields only.</em></p>')

    # 60-second scan
    parts.append("<h2>60-second scan</h2><ul>")
    scan = (res or {}).get("scan") or []
    if scan:
        for b in scan[:3]:
            parts.append(f"<li>{esc(_strip(b))}</li>")
    else:
        for c in cands[:3]:
            parts.append(f"<li>New: <a href='{esc(c['link'])}'>"
                         f"{esc(c['title'][:90])}</a> "
                         f"<small>({esc(c['source'])})</small></li>")
        if not cands:
            parts.append("<li>No AI/model/provider news in the window.</li>")
    parts.append("</ul>")

    # model/provider watch table
    parts.append("<h2>Model/provider watch</h2>")
    watch = (res or {}).get("watch") or []
    parts.append("<table border='1' cellpadding='4' cellspacing='0'>"
                 "<tr><th>model</th><th>provider</th><th>modality</th>"
                 "<th>measured/claimed efficiency</th><th>use</th>"
                 "<th>cost</th><th>hardware</th><th>decision</th></tr>")
    if watch:
        for w in watch[:8]:
            i = w.get("i")
            link = (f"<br><a href='{esc(cands[i]['link'])}'>source</a>"
                    if isinstance(i, int) and 0 <= i < len(cands) else "")
            parts.append("<tr>" + "".join(
                f"<td>{esc(_strip(str(w.get(k) or '—')))}{link if k == 'model' else ''}</td>"
                for k in ("model", "provider", "modality", "efficiency",
                          "use", "cost", "hardware", "decision")) + "</tr>")
    else:
        parts.append("<tr><td colspan='8'>No model/provider changes "
                     "qualified in this window.</td></tr>")
    parts.append("</table>")

    # what changed for us
    parts.append("<h2>What changed for us</h2><ul>")
    impacts = (res or {}).get("impacts") or {}
    for key, label in (("video", "video generation"),
                       ("gaussian", "Gaussian/4D scene work"),
                       ("local", "local / Colab / Nest"),
                       ("ada", "Ada / Chaba operations")):
        txt = _strip(impacts.get(key) or "")
        parts.append(f"<li><strong>{label}:</strong> "
                     f"{esc(txt) if txt else '— no direct impact found'}</li>")
    parts.append("</ul>")

    # recommended actions
    parts.append("<h2>Recommended actions</h2>")
    for verb in ("try", "watch", "no-action"):
        rows = [w for w in watch
                if str(w.get("decision", "")).lower().replace("_", "-")
                == verb]
        parts.append(f"<h3>{verb.upper()}</h3>")
        if rows:
            parts.append("<ul>")
            for w in rows:
                i = w.get("i")
                src = (f" — <a href='{esc(cands[i]['link'])}'>"
                       f"{esc(cands[i]['source'])}</a>"
                       if isinstance(i, int) and 0 <= i < len(cands)
                       else "")
                conf = w.get("confidence") or "?"
                parts.append(f"<li>{esc(_strip(str(w.get('model') or w.get('use') or 'item')))}"
                             f" — {esc(_strip(str(w.get('why') or '')))}"
                             f" <small>[{esc(str(conf))}]{src}</small></li>")
            parts.append("</ul>")
        else:
            parts.append("<p>—</p>")

    # sources and confidence
    parts.append("<h2>Sources and confidence</h2><ul>")
    conf_rank = {"high": 0, "medium": 1, "low": 2}
    seen = set()
    for w in sorted(watch, key=lambda x: conf_rank.get(
            str(x.get("confidence", "")).lower(), 3)):
        i = w.get("i")
        if not (isinstance(i, int) and 0 <= i < len(cands)):
            continue
        c = cands[i]
        if c["link"] in seen:
            continue
        seen.add(c["link"])
        parts.append(f"<li><a href='{esc(c['link'])}'>"
                     f"{esc(c['title'][:100])}</a> — "
                     f"{esc(c['source'])}, {_when(c['date'])} "
                     f"[confidence: {esc(str(w.get('confidence', '?')))}]</li>")
    if not seen:
        for c in cands[:10]:
            if c["link"] in seen:
                continue
            seen.add(c["link"])
            parts.append(f"<li><a href='{esc(c['link'])}'>"
                         f"{esc(c['title'][:100])}</a> — "
                         f"{esc(c['source'])}, {_when(c['date'])} "
                         "[confidence: unverified]</li>")
    parts.append("</ul>")

    # education updates
    parts.append("<h2>Education updates</h2><ul>")
    notes = edu_notes or {}
    for r in edu_rows[:5]:
        topic = r.get("topic") or ""
        note = _strip(notes.get(topic) or "")
        parts.append(f"<li><a href='{esc(lesson_url(r))}'>"
                     f"{esc(topic)}</a>"
                     + (f" — {esc(note)}" if note else "")
                     + "</li>")
    for lr in lesson_results:
        if lr.get("status") in ("updated", "created", "dry-run"):
            url = lr.get("url") or ""
            parts.append(f"<li>Lesson updated: "
                         f"<strong>{esc(lr['topic'])}</strong>"
                         + (f" — <a href='{esc(url)}'>open</a>"
                            if url else "")
                         + f" <small>[{esc(lr['status'])}]</small></li>")
        elif lr.get("status") == "error":
            parts.append(f"<li>Lesson update failed: "
                         f"{esc(lr['topic'])} — {esc(lr.get('reason',''))}</li>")
    if not edu_rows and not lesson_results:
        parts.append("<li>No Education lesson matched today's AI news.</li>")
    parts.append("</ul>")

    parts.append(f"<p><small>Generated {_when(now.isoformat())} ICT by "
                 "news-morning-brief.py — raw stories live in News CPT, "
                 "durable comparisons land in Education lessons. "
                 "Procedure: docs/kb/ai-news-to-education-procedure.md</small></p>")
    return "\n".join(parts)


def cmd_brief(ns_wp, args):
    now = datetime.now(ICT)
    cands = collect_candidates(ns_wp, args.hours)
    print(f"{len(cands)} AI-relevant candidates in {args.hours}h window")
    for c in cands[:10]:
        print(f"  [{c['kind']}] {c['title'][:80]} ({c['source']})")

    rows = lesson_rows()
    lesson_topics = [r.get("topic") or "" for r in rows if r.get("topic")]
    edu_rows = lesson_match(cands, rows)
    edu_notes = {}

    res, lane = synthesize(cands, lesson_topics) if cands else (None, "none")
    fallback = res is None
    if fallback:
        print("  warn: no LLM lane — deterministic fallback render",
              file=sys.stderr)
    else:
        print(f"  synthesis lane: {lane}")
        for e in (res.get("education") or []):
            t = str(e.get("topic") or "")
            if t:
                edu_notes[t] = str(e.get("note") or "")
        # keep only lessons that actually exist
        extra = [r for r in rows
                 if (r.get("topic") or "") in edu_notes
                 and r not in edu_rows]
        edu_rows = edu_rows + extra[:3]

    # durable comparisons -> existing Education lessons (bounded)
    lesson_results = []
    if not args.no_lessons and res:
        links_by_i = {i: (cands[i]["title"][:80], cands[i]["link"])
                      for i in range(len(cands)) if cands[i]["link"]}
        for lu in (res.get("lesson_updates") or [])[:args.max_lesson_updates]:
            topic = str(lu.get("topic") or "").strip()
            if not topic:
                continue
            refs = [links_by_i[i] for i in (lu.get("refs") or [])
                    if isinstance(i, int) and i in links_by_i][:4]
            if not refs:
                # fall back to the first candidate links
                refs = list(links_by_i.values())[:3]
            lesson_results.append(
                lesson_update(topic, str(lu.get("note") or ""), refs,
                              dry_run=args.dry_run))
            print(f"  lesson-update {topic}: "
                  f"{lesson_results[-1]['status']}")

    content = render_brief(cands, res, edu_rows, edu_notes,
                           lesson_results, fallback, now)
    if args.dry_run:
        print("\n----- page content (dry-run) -----\n")
        print(_strip(content)[:4000])
        return 0
    existing = ns_wp.api(f"/wp/v2/pages&slug={args.slug}&status=private")
    payload = {"title": f"{BRIEF_TITLE} — {now.strftime('%Y-%m-%d')}",
               "slug": args.slug, "status": "private", "content": content}
    if isinstance(existing, list) and existing:
        ns_wp.api(f"/wp/v2/pages/{existing[0]['id']}", payload)
        print(f"brief: updated page {existing[0]['id']} "
              f"({len(cands)} candidates, fallback={fallback})")
    else:
        r = ns_wp.api("/wp/v2/pages", payload)
        print(f"brief: created page {r.get('id')} "
              f"({len(cands)} candidates, fallback={fallback})")
    print(f"consumer URL: {PUBLIC_BASE}/{args.slug}/ "
          "(private — editor login required)")
    return 0


def cmd_ask(ns_wp, args):
    """On-demand query: embed the ask, score recent news titles + lesson
    topics, return newest source-backed matches first."""
    nd = _load_sibling("news-digest.py")
    after = (datetime.now(timezone.utc)
             - timedelta(days=args.days)).isoformat(timespec="seconds")
    posts = ns_wp.api(f"/wp/v2/news&after={after}&per_page=100"
                      "&orderby=date&order=desc")
    items = [{"title": _strip((p.get("title") or {}).get("rendered")),
              "link": p.get("link") or "",
              "source": (p.get("meta") or {}).get("source_feed") or "feed",
              "date": p.get("date") or "",
              "kind": "digest" if (p.get("slug") or "").startswith("d-")
                      else "item"}
             for p in posts
             if not (p.get("parent") and not (p.get("slug") or "")
                     .startswith("d-"))]
    rows = lesson_rows()
    lessons = [{"topic": r.get("topic") or "", "url": lesson_url(r),
                "level": r.get("level") or ""} for r in rows]

    q = nd.norm(args.text)
    news_texts = [nd.norm(i["title"]) for i in items]
    lesson_texts = [nd.norm(l["topic"]) for l in lessons]
    scores_n, scores_l = [], []
    try:
        url, key = nd._load_litellm()
        embs = nd.embed([q] + news_texts + lesson_texts, url, key)
        scores_n = [nd.cos(embs[0], e) for e in embs[1:1 + len(news_texts)]]
        scores_l = [nd.cos(embs[0], e)
                    for e in embs[1 + len(news_texts):]]
        mode = "embedding"
    except Exception as e:
        print(f"warn: embeddings unavailable ({e}) — ngram fallback",
              file=sys.stderr)
        a = nd.trigram_fallback(q)
        def jac(t):
            b = nd.trigram_fallback(t)
            return len(a & b) / max(1, min(len(a), len(b))) \
                if a and b else 0.0
        scores_n = [jac(t) for t in news_texts]
        scores_l = [jac(t) for t in lesson_texts]
        mode = "ngram"

    top_n = sorted(range(len(items)),
                   key=lambda i: -scores_n[i])[: args.top]
    top_l = sorted(range(len(lessons)),
                   key=lambda i: -scores_l[i])[: min(3, args.top)]
    out = {"query": args.text, "mode": mode,
           "news": [{**items[i], "score": round(scores_n[i], 3)}
                    for i in top_n if scores_n[i] > 0.05],
           "lessons": [{**lessons[i], "score": round(scores_l[i], 3)}
                       for i in top_l if scores_l[i] > 0.05]}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"query: {args.text!r} ({mode})")
    for n in out["news"]:
        print(f"  [{n['score']:.2f}] {n['kind']} {_when(n['date'])} "
              f"{n['title'][:90]}\n      {n['link']}")
    for l in out["lessons"]:
        print(f"  [{l['score']:.2f}] lesson {l['topic']} -> {l['url']}")
    return 0


def cmd_verify(ns_wp, args):
    """Confirm the private page exists and print the consumer URL —
    'a successful generator without a readable page is not a run'."""
    hits = ns_wp.api(f"/wp/v2/pages&slug={args.slug}&status=private")
    if not (isinstance(hits, list) and hits):
        print(f"verify: FAIL — no private page slug {args.slug!r}")
        return 1
    p = hits[0]
    print(f"verify: ok — page {p['id']} status={p.get('status')} "
          f"modified={p.get('modified')}")
    print(f"consumer URL: {PUBLIC_BASE}/{args.slug}/")
    print("note: private page — requires WP editor login to view")
    return 0


def cmd_lesson_update(args):
    links = [(t, u) for t, u in (args.link or [])]
    if not links:
        links = [("source", u) for u in args.url or []]
    r = lesson_update(args.topic, args.note, links, dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("status") not in ("error", "skipped") else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("brief", help="daily run: build + publish page")
    p.add_argument("--hours", type=float, default=30,
                   help="candidate window (default 30h — covers the "
                        "overnight gap between daily runs)")
    p.add_argument("--slug", default=BRIEF_SLUG)
    p.add_argument("--no-lessons", action="store_true",
                   help="skip durable-comparison lesson updates")
    p.add_argument("--max-lesson-updates", type=int,
                   default=MAX_LESSON_UPDATES)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("ask", help="on-demand news+education query")
    p.add_argument("text")
    p.add_argument("--days", type=float, default=7)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("verify", help="confirm private page + consumer URL")
    p.add_argument("--slug", default=BRIEF_SLUG)

    p = sub.add_parser("lesson-update",
                       help="append a dated News watch block to one "
                            "existing lesson")
    p.add_argument("--topic", required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--link", action="append", default=[],
                   metavar="TITLE|URL")
    p.add_argument("--url", action="append", default=[])
    p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    if args.cmd == "lesson-update":
        # --link TITLE|URL pairs
        args.link = [tuple(x.split("|", 1)) for x in args.link
                     if "|" in x]
        return cmd_lesson_update(args)
    ns = _load_sibling("news-situation.py")
    wp = ns.WP()
    if args.cmd == "brief":
        return cmd_brief(wp, args)
    if args.cmd == "ask":
        return cmd_ask(wp, args)
    if args.cmd == "verify":
        return cmd_verify(wp, args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
