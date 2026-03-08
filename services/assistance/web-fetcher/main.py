import ipaddress
import os
import re
import socket
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import Body, FastAPI, HTTPException


app = FastAPI(title="web-fetcher", version="0.1.0")


MAX_BYTES = int(os.getenv("WEB_FETCH_MAX_BYTES", "2000000"))
MAX_REDIRECTS = int(os.getenv("WEB_FETCH_MAX_REDIRECTS", "5"))
CONNECT_TIMEOUT_S = float(os.getenv("WEB_FETCH_CONNECT_TIMEOUT_S", "5"))
READ_TIMEOUT_S = float(os.getenv("WEB_FETCH_READ_TIMEOUT_S", "15"))

CA_BUNDLE = str(os.getenv("WEB_FETCH_CA_BUNDLE") or "/etc/ssl/certs/ca-certificates.crt").strip()

ALLOWED_CONTENT_TYPES = tuple(
    ct.strip().lower()
    for ct in (os.getenv("WEB_FETCH_ALLOWED_CONTENT_TYPES") or "text/html,text/plain,application/json").split(",")
    if ct.strip()
)


def _normalize_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="missing_url")

    # Strip surrounding angle brackets that sometimes appear in chat.
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()

    parts = urlsplit(url)

    if parts.scheme.lower() not in ("http", "https"):
        raise HTTPException(status_code=400, detail="unsupported_scheme")

    if not parts.netloc:
        raise HTTPException(status_code=400, detail="missing_host")

    if parts.username or parts.password:
        raise HTTPException(status_code=400, detail="userinfo_not_allowed")

    # Basic control-char / whitespace protection.
    if re.search(r"[\x00-\x20\x7f]", url):
        raise HTTPException(status_code=400, detail="invalid_url_chars")

    return urlunsplit(parts)


def _is_ip_denied(ip: ipaddress._BaseAddress) -> bool:  # type: ignore[name-defined]
    # Deny SSRF-sensitive ranges.
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:  # type: ignore[name-defined]
    # Resolve both A/AAAA.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="dns_resolution_failed")

    ips: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            ips.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    if not ips:
        raise HTTPException(status_code=400, detail="dns_resolution_failed")
    return ips


def _enforce_ssrf(url: str) -> None:
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise HTTPException(status_code=400, detail="missing_host")

    ips = _resolve_host_ips(host)
    for ip in ips:
        if _is_ip_denied(ip):
            raise HTTPException(status_code=403, detail="blocked_host_ip")


def _content_type_allowed(content_type_header: str) -> bool:
    content_type = (content_type_header or "").split(";")[0].strip().lower()
    if not content_type:
        return False
    return any(content_type == allowed for allowed in ALLOWED_CONTENT_TYPES)


def _html_to_text(html: str) -> tuple[str, Optional[str]]:
    soup = BeautifulSoup(html, "lxml")

    title: Optional[str] = None
    if soup.title and soup.title.string:
        title = str(soup.title.string).strip() or None

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = "\n".join(line.strip() for line in text.splitlines())
    text = "\n".join(line for line in text.splitlines() if line)
    return text.strip(), title


async def _fetch_once(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    _enforce_ssrf(url)

    res = await client.get(url)

    # Handle redirects manually so we can SSRF-check each hop.
    if res.status_code in (301, 302, 303, 307, 308):
        location = res.headers.get("location")
        if not location:
            raise HTTPException(status_code=502, detail="redirect_missing_location")
        return {"redirect": True, "location": httpx.URL(location, base=res.url).human_repr()}

    content_type = res.headers.get("content-type") or ""
    if not _content_type_allowed(content_type):
        raise HTTPException(status_code=415, detail="unsupported_content_type")

    # Streaming byte limit enforcement
    total = 0
    chunks: list[bytes] = []
    async for chunk in res.aiter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(status_code=413, detail="response_too_large")
        chunks.append(chunk)

    body = b"".join(chunks)
    try:
        text = body.decode(res.encoding or "utf-8", errors="replace")
    except Exception:
        text = body.decode("utf-8", errors="replace")

    base_ct = content_type.split(";")[0].strip().lower()
    title: Optional[str] = None
    if base_ct == "text/html":
        text, title = _html_to_text(text)

    return {
        "redirect": False,
        "status_code": res.status_code,
        "final_url": str(res.url),
        "content_type": base_ct,
        "title": title,
        "text": text,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "web-fetcher"}


@app.post("/fetch")
async def fetch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = _normalize_url(str(payload.get("url") or ""))

    timeout = httpx.Timeout(timeout=READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
    headers = {
        "User-Agent": "web-fetcher/0.1 (+https://example.invalid)",
        "Accept": ", ".join(ALLOWED_CONTENT_TYPES),
    }

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False, verify=CA_BUNDLE) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            result = await _fetch_once(client, current)
            if not result.get("redirect"):
                return {"ok": True, **result}
            current = str(result["location"])

        raise HTTPException(status_code=508, detail="too_many_redirects")
