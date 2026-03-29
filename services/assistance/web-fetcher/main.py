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
    for ct in (
        os.getenv("WEB_FETCH_ALLOWED_CONTENT_TYPES")
        or "text/html,text/plain,application/json,application/rss+xml,application/atom+xml,application/xml,text/xml"
    ).split(",")
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
    if any(content_type == allowed for allowed in ALLOWED_CONTENT_TYPES):
        return True
    # Some feeds return non-standard but still-safe XML-ish content-types.
    if "xml" in content_type or "rss" in content_type or "atom" in content_type:
        return True
    return False


def _html_to_text(html: str) -> tuple[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")

    title: Optional[str] = None
    if soup.title and soup.title.string:
        title = str(soup.title.string).strip() or None

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = "\n".join(line.strip() for line in text.splitlines())
    text = "\n".join(line for line in text.splitlines() if line)
    return text.strip(), title


def _fallback_urls_for_upstream(url: str) -> list[str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").strip().lower()
    if not host:
        return []
    if host != "rss.cnn.com":
        return []
    if parts.scheme.lower() == "https":
        try:
            return [urlunsplit(parts._replace(scheme="http"))]
        except Exception:
            return []
    return []


async def _fetch_once(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    _enforce_ssrf(url)

    try:
        res = await client.get(url)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "upstream_request_failed",
                "url": url,
                "exception": e.__class__.__name__,
                "message": str(e),
            },
        )

    # Handle redirects manually so we can SSRF-check each hop.
    if res.status_code in (301, 302, 303, 307, 308):
        location = res.headers.get("location")
        if not location:
            raise HTTPException(status_code=502, detail="redirect_missing_location")
        try:
            base = httpx.URL(str(res.url))
            target = base.join(location)
            return {"redirect": True, "location": target.human_repr()}
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "redirect_location_invalid",
                    "url": str(res.url),
                    "location": str(location),
                    "exception": e.__class__.__name__,
                    "message": str(e),
                },
            )

    content_type = res.headers.get("content-type") or ""
    if not _content_type_allowed(content_type):
        raise HTTPException(
            status_code=415,
            detail={
                "error": "unsupported_content_type",
                "content_type": (content_type or "").strip(),
            },
        )

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": ", ".join(ALLOWED_CONTENT_TYPES),
    }

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False, verify=CA_BUNDLE) as client:
        def _is_retryable_upstream_error(exc: HTTPException) -> bool:
            try:
                return exc.status_code == 502 and isinstance(exc.detail, dict) and exc.detail.get("error") == "upstream_request_failed"
            except Exception:
                return False

        attempts = [url] + _fallback_urls_for_upstream(url)
        last_exc: Optional[HTTPException] = None

        for attempt_url in attempts:
            current = attempt_url
            try:
                for _ in range(MAX_REDIRECTS + 1):
                    result = await _fetch_once(client, current)
                    if not result.get("redirect"):
                        return {"ok": True, **result}
                    current = str(result["location"])
                raise HTTPException(status_code=508, detail="too_many_redirects")
            except HTTPException as e:
                last_exc = e
                if attempt_url != attempts[-1] and _is_retryable_upstream_error(e):
                    continue
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "web_fetcher_internal_error",
                        "url": str(current),
                        "exception": e.__class__.__name__,
                        "message": str(e),
                    },
                )

        if last_exc is not None:
            raise last_exc
        raise HTTPException(status_code=502, detail="upstream_request_failed")
