#!/usr/bin/env python3
"""Shared WP boards REST client + render_job writer.

Card render-job-writer-must-upload-output-to-78229c (OPS-0701 follow-up):
every scripts/ada/*.py WP writer hand-rolls the same plumbing — env-file
parse, Basic auth, the index.php?rest_route= quirk (the Plesk vhost 404s
/wp-json/; REST rides ?rest_route= and extra args ride as plain &params).
This module is the one place that lives now, plus the two operations the
render_job output convention needs:

  upload_media(source, filename=None, mime=None) -> attachment dict
      POST /wp/v2/media — raw bytes + Content-Type + Content-Disposition.
      `source` may be a path, bytes, binary file object, or an http(s)
      URL (fetched first — render backends like Veo hand back URLs, not
      files). Returns the WP attachment object; `source_url` is the
      canonical public URL, `id` feeds featured_media / chaba/v1/media.

  write_render_job(...) -> post dict
      The render_job writer contract (ssot.wp-boards.yml
      writers.render_job): when `output` is given it is uploaded to
      /wp/v2/media FIRST and the post's output_url meta is the returned
      source_url — never a filesystem path (job 117 stored
      /local/local-gen/... which 404'd in the browser and the file was
      later lost). featured_media gets the attachment id so the plugin's
      result-thumb column + single-view job card render it. Pass
      member_gated=True to store the chaba/v1/media/<id> REST URL
      instead (streams only to logged-in members).

Config — ~/.config/secrets/wp-boards.env (WP_SITE_URL/WP_APP_USER/
WP_APP_PASSWORD), parsed never sourced; WP_BOARDS_ENV overrides the path;
explicit env vars win. Fleet writers hit WP_SITE_URL (the origin) — the
public edge bot-checks script UAs (ssot.wp-boards.yml caveat).

Stdlib only. Import:
  sys.path.insert(0, "<repo>/scripts"); from lib.wp_boards import WpBoards
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_ENV = os.path.expanduser("~/.config/secrets/wp-boards.env")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# POST /wp/v2/media bodies ride PHP post_max_size/upload_max_filesize on
# the Plesk vhost — keep a sane ceiling so a runaway render doesn't hang
# the writer. Override with WP_MEDIA_MAX_BYTES.
MEDIA_MAX_BYTES = int(os.environ.get(
    "WP_MEDIA_MAX_BYTES", str(512 * 1024 * 1024)))
FETCH_TIMEOUT = int(os.environ.get("WP_MEDIA_FETCH_TIMEOUT", "120"))

# render_job meta keys the chaba-boards plugin registers (show_in_rest) —
# anything outside this set is dropped by WP anyway; keep the list here so
# callers get a loud typo error instead of a silently-empty meta field.
RENDER_JOB_META = {
    "kind", "prompt", "negative_prompt", "model", "model_file", "size_px",
    "steps", "sampler", "cfg_scale", "seed", "duration_s", "secs", "vae_s",
    "aspect", "res", "ref_url", "operation", "est_cost_usd", "parent_job",
    "chain_index", "host", "backend", "status", "requested_by", "source",
    "output_url", "rating", "error",
}


class WpBoardsError(RuntimeError):
    """WP REST failure — carries the HTTP status when there is one."""

    def __init__(self, msg, status=None, payload=None):
        super().__init__(msg)
        self.status = status
        self.payload = payload


def load_env(path: str | None = None) -> dict:
    """Parse a wp-boards.env KEY=VALUE file — never sourced (the app
    password carries shell-special chars). Explicit WP_* env vars win."""
    env = {}
    p = os.path.expanduser(path or os.environ.get("WP_BOARDS_ENV")
                           or DEFAULT_ENV)
    try:
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    missing = [k for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD")
               if not env.get(k)]
    if missing:
        raise WpBoardsError(
            f"missing {', '.join(missing)} — need them in {p} "
            f"(or WP_BOARDS_ENV)")
    return env


def _guess_mime(filename: str, hint: str | None = None) -> str:
    if hint:
        return hint
    mime = mimetypes.guess_type(filename)[0]
    return mime or "application/octet-stream"


def _filename_from_url(url: str) -> str:
    name = os.path.basename(urllib.parse.urlparse(url).path)
    return urllib.parse.unquote(name) or "render-output.bin"


class WpBoards:
    """Thin REST client for boards.surf-thailand.com (origin base)."""

    def __init__(self, env: dict | None = None, env_path: str | None = None,
                 base: str | None = None):
        env = env or load_env(env_path)
        self.base = (base or env["WP_SITE_URL"]).rstrip("/")
        self._auth = "Basic " + base64.b64encode(
            f"{env['WP_APP_USER']}:{env['WP_APP_PASSWORD']}".encode()
        ).decode()

    # -- transport ---------------------------------------------------------

    def api(self, method: str, route: str, data: dict | None = None,
            raw: bytes | None = None, ctype: str = "application/json",
            filename: str | None = None, timeout: int = 120):
        """One REST call. `route` is the full REST path ("/wp/v2/media",
        "/wp/v2/render_job?slug=x&status=any") — a literal '?' is
        normalized to '&' because the query slot is already occupied by
        rest_route (same convention as cam-snapshot-wp.py)."""
        route = route.replace("?", "&")
        url = (f"{self.base}/index.php?rest_route="
               f"{urllib.parse.quote(route, safe='/&=')}")
        body = raw if raw is not None else (
            json.dumps(data).encode() if data is not None else None)
        req = urllib.request.Request(url, data=body, method=method.upper())
        req.add_header("Authorization", self._auth)
        req.add_header("User-Agent", UA)
        if body is not None:
            req.add_header("Content-Type", ctype)
            if filename:
                req.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
                try:
                    return r.status, json.loads(payload)
                except ValueError:
                    return r.status, {"raw": payload[:400].decode(
                        errors="replace")}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read())
            except Exception:
                detail = {"raw": ""}
            raise WpBoardsError(
                f"{method} {route} -> {e.code}: "
                f"{json.dumps(detail)[:300]}", status=e.code,
                payload=detail) from e
        except Exception as e:
            raise WpBoardsError(f"{method} {route} -> {e}") from e

    # -- media -------------------------------------------------------------

    def _read_source(self, source, filename: str | None):
        """Normalize path|bytes|fileobj|http(s) URL -> (body, filename)."""
        if isinstance(source, (bytes, bytearray)):
            return bytes(source), filename or "render-output.bin"
        if hasattr(source, "read"):
            body = source.read()
            return body, filename or "render-output.bin"
        s = str(source)
        if re.match(r"^https?://", s):
            req = urllib.request.Request(s, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                body = r.read(MEDIA_MAX_BYTES + 1)
            if len(body) > MEDIA_MAX_BYTES:
                raise WpBoardsError(
                    f"source URL exceeds WP_MEDIA_MAX_BYTES "
                    f"({MEDIA_MAX_BYTES})")
            return body, filename or _filename_from_url(s)
        p = Path(s)
        if not p.is_file():
            raise WpBoardsError(f"output not found: {s}")
        return p.read_bytes(), filename or p.name

    def upload_media(self, source, filename: str | None = None,
                     mime: str | None = None) -> dict:
        """POST /wp/v2/media — the only sanctioned way render output
        reaches WP (ssot.wp-boards.yml writers.render_job)."""
        body, fname = self._read_source(source, filename)
        if not body:
            raise WpBoardsError(f"empty output for {fname}")
        status, res = self.api(
            "POST", "/wp/v2/media", raw=body,
            ctype=_guess_mime(fname, mime), filename=fname,
            timeout=max(120, len(body) // (512 * 1024) + 60))
        if status not in (200, 201) or not isinstance(res, dict) \
                or not res.get("id"):
            raise WpBoardsError(
                f"media upload failed {status}: {str(res)[:200]}",
                status=status, payload=res)
        return res

    # -- render_job ----------------------------------------------------------

    def member_media_url(self, attachment_id: int) -> str:
        """chaba/v1/media/<id> as a full URL — member-gated stream route
        registered by the chaba-boards plugin (is_user_logged_in)."""
        return (f"{self.base}/index.php?rest_route="
                f"/chaba/v1/media/{int(attachment_id)}")

    def find_post_by_slug(self, post_type: str, slug: str) -> int:
        _s, res = self.api(
            "GET", f"/wp/v2/{post_type}&slug={urllib.parse.quote(slug)}"
                   f"&status=any&per_page=1&_fields=id")
        if isinstance(res, list) and res:
            return int(res[0]["id"])
        return 0

    @staticmethod
    def render_title(prompt: str, when: datetime.date | None = None) -> str:
        """title_standard: render_job -> 'Render — {prompt-short} {date}'."""
        short = re.sub(r"\s+", " ", (prompt or "").strip())[:60].rstrip()
        d = (when or datetime.date.today()).isoformat()
        return f"Render — {short} {d}" if short else f"Render {d}"

    def write_render_job(self, *, kind: str, prompt: str = "",
                         status: str = "ok", output=None,
                         output_url: str | None = None,
                         member_gated: bool = False,
                         meta: dict | None = None,
                         slug: str | None = None,
                         title: str | None = None,
                         content: str = "",
                         post_status: str = "private",
                         dry_run: bool = False) -> dict:
        """Record one render_job post. `output` (path|bytes|URL) is
        uploaded to /wp/v2/media first and output_url becomes the returned
        source_url (or the member-gated chaba/v1/media URL). An explicit
        http(s) output_url is accepted as-is; a filesystem path is
        rejected — that is the bug this convention exists to kill."""
        m = {k: v for k, v in {
            "kind": kind, "prompt": prompt, "status": status,
            "source": "render-job-record",
            "host": os.uname().nodename,
        }.items() if v not in (None, "")}
        for k, v in (meta or {}).items():
            if k not in RENDER_JOB_META:
                raise WpBoardsError(
                    f"unknown render_job meta key: {k!r} "
                    f"(registered: {sorted(RENDER_JOB_META)})")
            if v not in (None, ""):
                m[k] = v

        featured_media = None
        if output is not None:
            if dry_run:
                m["output_url"] = "<would upload to /wp/v2/media>"
            else:
                att = self.upload_media(output)
                featured_media = att["id"]
                m["output_url"] = (
                    self.member_media_url(att["id"]) if member_gated
                    else att.get("source_url", ""))
        elif output_url:
            u = output_url.strip()
            if re.match(r"^chaba/v1/media/(\d+)$", u):
                u = self.member_media_url(int(u.rsplit("/", 1)[1]))
            if not re.match(r"^https?://", u):
                raise WpBoardsError(
                    "output_url must be a WP media URL "
                    "(source_url or chaba/v1/media/<id>) — got "
                    f"{u[:80]!r}; upload the file via upload_media() first")
            m["output_url"] = u

        body = {
            "title": title or self.render_title(prompt),
            "status": post_status,
            "content": content,
            "meta": m,
        }
        if slug:
            body["slug"] = slug
        if featured_media:
            body["featured_media"] = featured_media
        if dry_run:
            return {"dry_run": True, "post": body}

        existing = self.find_post_by_slug("render_job", slug) if slug else 0
        route = (f"/wp/v2/render_job/{existing}" if existing
                 else "/wp/v2/render_job")
        _s, res = self.api("POST", route, body)
        return res
