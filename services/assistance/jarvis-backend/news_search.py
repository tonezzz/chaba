"""Thai news-finding skill: fetch RSS feeds, filter by keyword, format Thai brief."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("jarvis-backend.news_search")

# ---------------------------------------------------------------------------
# Default RSS feed list – operators can override via NEWS_RSS_FEEDS (CSV)
# ---------------------------------------------------------------------------
_DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/thai/rss.xml",
    "https://www.thairath.co.th/rss/news.rss",
    "https://www.bangkokpost.com/rss/data/topstories.xml",
]

_THAI_NEWS_PREFIXES = [
    "หาข่าวที่เกี่ยวกับ",
    "หาข่าวเกี่ยวกับ",
    "ค้นข่าวที่เกี่ยวกับ",
    "ค้นข่าวเกี่ยวกับ",
    "ข่าวเกี่ยวกับ",
    "หาข่าว",
    "ค้นข่าว",
]

_FETCH_TIMEOUT = float(os.getenv("NEWS_FETCH_TIMEOUT_SECONDS", "10"))
_MAX_ARTICLES_DEFAULT = int(os.getenv("NEWS_MAX_ARTICLES", "10"))


def _validate_feed_url(url: str) -> None:
    """Raise ValueError if *url* is not a safe public https/http URL.

    Blocks private/loopback/link-local addresses to prevent SSRF.
    Operators who need custom feeds should set NEWS_RSS_FEEDS; those URLs
    are still validated here at fetch time.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsafe URL scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Missing host in feed URL")
    # Block localhost by name
    if host in ("localhost",):
        raise ValueError(f"Feed URL host not allowed: {host!r}")
    # Block private/loopback/link-local IP literals
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"Feed URL resolves to a non-public address: {host!r}")
    except ValueError as exc:
        # Re-raise our own ValueError (non-public IP); ignore "not an IP" errors
        if "non-public" in str(exc) or "not allowed" in str(exc):
            raise


def get_feed_list() -> List[str]:
    """Return RSS feed URLs from env or built-in defaults."""
    raw = (os.getenv("NEWS_RSS_FEEDS") or "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(_DEFAULT_FEEDS)


def extract_keywords(query: str) -> List[str]:
    """Strip Thai news prefixes and return keyword tokens from *query*."""
    q = query.strip()
    for prefix in sorted(_THAI_NEWS_PREFIXES, key=len, reverse=True):
        if q.startswith(prefix):
            q = q[len(prefix):].strip()
            break
    if not q:
        return []
    keywords: List[str] = []
    if q:
        keywords.append(q)
    parts = q.split()
    if len(parts) > 1:
        keywords.extend(parts)
    return list(dict.fromkeys(k for k in keywords if k))


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text or "")


def parse_rss(xml_text: str) -> List[Dict[str, str]]:
    """Parse RSS 2.0 XML and return list of article dicts."""
    articles: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("RSS parse error: %s", exc)
        return articles

    for item in root.findall(".//item"):
        title = _strip_html(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if title or link:
            articles.append(
                {"title": title, "link": link, "description": desc, "pubDate": pub_date}
            )
    return articles


def score_article(article: Dict[str, str], keywords: List[str]) -> int:
    """Return keyword-hit count for *article*."""
    haystack = (
        (article.get("title") or "") + " " + (article.get("description") or "")
    ).lower()
    return sum(1 for kw in keywords if kw.lower() in haystack)


async def _fetch_rss(url: str) -> List[Dict[str, str]]:
    """Fetch and parse a single RSS feed URL.

    Raises ValueError for unsafe URLs (SSRF guard) before making any request.
    """
    _validate_feed_url(url)
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT, follow_redirects=False
    ) as client:
        resp = await client.get(url, headers={"User-Agent": "jarvis-backend/1.0"})
        resp.raise_for_status()
        return parse_rss(resp.text)


async def search_news(
    query: str,
    feeds: Optional[List[str]] = None,
    max_articles: int = _MAX_ARTICLES_DEFAULT,
) -> Dict[str, Any]:
    """Search RSS feeds for articles matching *query*.

    Returns a dict with keys: brief, sources, articles, query, keywords.
    """
    if feeds is None:
        feeds = get_feed_list()

    keywords = extract_keywords(query)
    if not keywords:
        return {
            "brief": "ไม่พบคำค้นหา กรุณาระบุหัวข้อที่ต้องการค้นหา",
            "sources": [],
            "articles": [],
            "query": query,
            "keywords": [],
        }

    all_articles: List[Dict[str, str]] = []
    fetch_errors: List[str] = []

    for feed_url in feeds:
        try:
            articles = await _fetch_rss(feed_url)
            for a in articles:
                a["_feed"] = feed_url
            all_articles.extend(articles)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch %s: %s", feed_url, exc)
            fetch_errors.append(f"{feed_url}: {exc}")

    # Score, filter, deduplicate
    scored = [(a, score_article(a, keywords)) for a in all_articles]
    scored = [(a, s) for a, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])

    seen_titles: Set[str] = set()
    results: List[Dict[str, str]] = []
    for a, _s in scored:
        title = (a.get("title") or "").strip()
        if title in seen_titles:
            continue
        seen_titles.add(title)
        results.append(a)
        if len(results) >= max_articles:
            break

    if not results:
        keyword_str = " ".join(keywords[:3])
        msg = (
            f'ไม่พบข่าวที่เกี่ยวข้องกับ "{keyword_str}" ในขณะนี้\n'
            "ลองใช้คำค้นหาอื่น หรือรอสักครู่แล้วลองใหม่อีกครั้ง"
        )
        return {
            "brief": msg,
            "sources": [],
            "articles": [],
            "query": query,
            "keywords": keywords,
        }

    keyword_str = " ".join(keywords[:3])
    lines = [f'พบข่าวเกี่ยวกับ "{keyword_str}" จำนวน {len(results)} รายการ:\n']
    sources: List[str] = []
    for i, a in enumerate(results, 1):
        title = a.get("title", "").strip()
        link = a.get("link", "").strip()
        lines.append(f"{i}. {title}")
        if link:
            lines.append(f"   🔗 {link}")
            sources.append(link)

    return {
        "brief": "\n".join(lines),
        "sources": sources,
        "articles": results,
        "query": query,
        "keywords": keywords,
    }
