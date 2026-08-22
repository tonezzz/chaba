"""Fetch and extract readable text/HTML from a URL."""
import re
import urllib.error
import urllib.request


def _fetch_text(url):
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("url must be http or https")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _decode_entities(text):
    if not text:
        return ""
    # Minimal HTML entity decode for common cases
    replacements = [
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&nbsp;", " "),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return text


def _strip_tags(html):
    if not html:
        return ""
    return re.sub(r"<[^>]*>", " ", html)


def fetch_page(url, max_length=8000, raw=False):
    html = _fetch_text(url)

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = _decode_entities(_strip_tags(title_match.group(1) if title_match else "")).strip()

    desc_match = re.search(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
        html,
        re.IGNORECASE,
    ) or re.search(
        r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']',
        html,
        re.IGNORECASE,
    )
    description = desc_match.group(1) if desc_match else ""

    content_html = ""
    for tag in ("main", "article", "body"):
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
        if match:
            content_html = match.group(1)
            break
    if not content_html:
        content_html = html

    # Remove scripts, styles, and common structural clutter
    for tag in ("script", "style", "nav", "header", "footer", "aside"):
        content_html = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            " ",
            content_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

    text = _decode_entities(_strip_tags(content_html))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        text = text[:max_length] + "..."

    return {
        "url": url,
        "title": title,
        "description": description,
        "text": text,
        "html": html if raw else None,
    }
