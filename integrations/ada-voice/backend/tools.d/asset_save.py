"""asset_save — keep a photo as a persona asset (card
persona-photo-store).

Saves an image the lane already received — the /relay-img/arch/ URL or
archive path from a "photo received" turn, the chat's latest inbound
image when no source is named — or any fetchable image URL, into the
persona-assets store under the media archive
(LINE_MEDIA_ARCHIVE_DIR/persona-assets/, publicly served by the relay
at /relay-img/arch/persona-assets/) and upserts an 'assets/<slug>'
memory doc carrying meta.image_url in the caller's personal bank.

Recall side (same card): _doc_to_hit surfaces meta.image_url on search
hits and ada_memory_search promotes the first image-bearing hit to a
top-level image_url — the relay's tool_result image scan attaches it
to the reply with no chat_send round-trip. Explicit resends still
work: chat_send(image_url=<the url>) verbatim.

Env:
    LINE_MEDIA_ARCHIVE_DIR — must match the relay (default
        ~/.local/share/ada/line-media)
    ADA_RELAY_PUBLIC_BASE / LINE_PUBLIC_IMG_BASE — public base for the
        /relay-img/arch/ hop (same chain ada_render_image uses)
    ADA_ASSET_MAX_BYTES — fetch/read cap (default 15 MiB)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ARCHIVE_DIR = Path(os.environ.get(
    "LINE_MEDIA_ARCHIVE_DIR",
    os.path.expanduser("~/.local/share/ada/line-media"))).expanduser()
ASSET_DIR = Path(os.environ.get(
    "ADA_PERSONA_ASSET_DIR", str(ARCHIVE_DIR / "persona-assets"))
).expanduser()
MAX_BYTES = int(os.environ.get("ADA_ASSET_MAX_BYTES",
                               str(15 * 1024 * 1024)))
_MANIFEST_TAIL_LINES = 8000

DECLARATION = {
    "name": "asset_save",
    "description": (
        "Save a photo as a persona asset — stores the image under the "
        "media archive and writes an assets/<slug> memory doc with "
        "meta.image_url so memory search re-shows it. media_url= "
        "defaults to this chat's latest inbound image."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Asset slug, e.g. 'kk-crv' — becomes the "
                               "key assets/<slug> and the filename. "
                               "Default: derived from description.",
            },
            "description": {
                "type": "string",
                "description": "What the photo shows / why it's kept — "
                               "becomes the doc body Ada recalls later.",
            },
            "media_url": {
                "type": "string",
                "description": "Image source: the /relay-img/arch/ URL "
                               "or archive path from a 'photo received' "
                               "note, or any fetchable image URL. Omit "
                               "to use this chat's latest inbound image.",
            },
            "bank": {
                "type": "string",
                "description": "Optional bank override — default is the "
                               "caller's personal bank.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}

_IMG_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"RIFF", "image/webp", ".webp"),  # + WEBP at offset 8, checked below
)


def _public_base() -> str:
    return (os.environ.get("ADA_RELAY_PUBLIC_BASE")
            or os.environ.get("LINE_PUBLIC_IMG_BASE")
            or "https://157.85.102.125.sslip.io/relay-img").rstrip("/")


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _resolve_archive(spec: str) -> tuple[Path | None, str | None]:
    """Map a media_url/path arg to a file under ARCHIVE_DIR — the same
    confinement doc_read applies: only relay-archived bytes are local
    reads; anything else must come in as a fetchable URL."""
    s = spec.strip()
    if not s:
        return None, "empty media source"
    url_path = None
    if s.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        url_path = urlparse(s).path
    elif s.startswith("/relay-img/"):
        url_path = s
    if url_path is not None:
        if url_path.startswith("/relay-img/arch/"):
            cand = ARCHIVE_DIR / url_path[len("/relay-img/arch/"):]
        else:
            return None, ("only /relay-img/arch/ URLs resolve locally — "
                          "pass a fetchable image URL instead")
    else:
        cand = Path(s)
        if cand.is_absolute():
            if not _under(cand, ARCHIVE_DIR):
                return None, ("path is outside the LINE media archive — "
                              "asset_save only reads files the relay "
                              "archived")
        elif "/" in s:
            cand = ARCHIVE_DIR / s
        else:
            hits = sorted(ARCHIVE_DIR.glob(f"*/{s}")) \
                if ARCHIVE_DIR.is_dir() else []
            hits = [h for h in hits if _under(h, ARCHIVE_DIR) and h.is_file()]
            if not hits:
                return None, f"no archived file named {s!r}"
            cand = hits[-1]
    if ".." in cand.parts:
        return None, "path escapes the media archive — refused"
    cand = cand.resolve()
    if not _under(cand, ARCHIVE_DIR):
        return None, "path escapes the media archive — refused"
    if not cand.is_file():
        return None, f"no archived file at {s!r}"
    return cand, None


def _manifest_tail() -> list[dict]:
    mf = ARCHIVE_DIR / "manifest.jsonl"
    if not mf.is_file():
        return []
    try:
        lines = mf.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-_MANIFEST_TAIL_LINES:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def _latest_chat_image(chat_id: str) -> tuple[Path | None, dict | None]:
    """Newest kind=image manifest line for this chat -> (archive path,
    manifest entry). The relay stamps chat_id on every archived item."""
    if not chat_id:
        return None, None
    for e in reversed(_manifest_tail()):
        if (str(e.get("kind") or "") == "image"
                and str(e.get("chat_id") or "") == chat_id):
            p = Path(str(e.get("path") or ""))
            if p.is_file() and _under(p, ARCHIVE_DIR):
                return p, e
            # path missing/stale — rebuild from chat dir + message id.
            mid = str(e.get("message_id") or "")
            mime = str(e.get("mime") or "")
            ext = {"image/jpeg": ".jpg", "image/png": ".png",
                   "image/webp": ".webp", "image/gif": ".gif"}.get(mime)
            if mid and ext:
                cand = ARCHIVE_DIR / _chat_slug(chat_id) / f"{mid}{ext}"
                if cand.is_file():
                    return cand, e
            return None, e
    return None, None


def _chat_slug(chat_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", chat_id).strip("-") or "chat"


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    """(mime, ext) from magic bytes — LINE/relay both key off the real
    bytes, never the declared content-type."""
    for magic, mime, ext in _IMG_MAGIC:
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime, ext
    return None


async def _fetch_url(url: str) -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=30.0,
                                 follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise RuntimeError(f"fetch {r.status_code}")
            chunks, total = [], 0
            async for chunk in r.aiter_bytes(65536):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError(
                        f"image exceeds {MAX_BYTES // (1024 * 1024)} MiB")
                chunks.append(chunk)
            return b"".join(chunks)


async def run(runner: Any, name: str = "", description: str = "",
              media_url: str = "", bank: str = ""
              ) -> dict[str, Any]:
    from backend import memory_ops
    from backend.memory_banks import _slug
    from backend.tool_runner.common import session_chat_id

    if runner.mddb is None or runner.banks is None or runner.memory is None:
        return {"ok": False,
                "error": "memory banks are not available on this instance"}

    identity = runner._memory_identity()

    # -- resolve the bank: explicit bank= wins; else the caller's
    # writable personal bank (person-scoped for identified speakers).
    bank_name = str(bank or "").strip()
    if not bank_name:
        b = memory_ops.persona_bank_for(runner.banks, identity)
        if b is None:
            return {"ok": False,
                    "error": "no personal bank for this identity — "
                             "pass bank= explicitly"}
        bank_name = b.name
    elif bank_name == "personal" and identity:
        bank_name = runner.banks.personal_bank_name(identity)
    try:
        bank_cfg = runner.banks.bank(bank_name)
    except KeyError:
        return {"ok": False, "error": f"unknown memory bank {bank_name!r}"}

    # -- the same write gates ada_remember's dispatch layer applies:
    # person_policies + writable + allowed_tools via the unified ACL
    # (tool='ada_remember' — the bank configs' write-tool list), plus
    # ADA_READ_ONLY. Confirmed-policy banks can't be honored here —
    # the tools.d confirmed/confirm_token args are consumed upstream
    # and never reach run() — so refuse honestly instead of minting a
    # confirmation flow that can't complete.
    if bank_cfg.write_policy == "confirmed":
        return {"ok": False,
                "error": f"memory bank '{bank_cfg.name}' requires "
                         "confirmed writes — asset_save can't run the "
                         "confirmation flow; omit bank= to use your "
                         "personal bank"}
    try:
        runner._check_memory_write_allowed(
            "ada_remember", {"bank": bank_cfg.name}, None, None)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    # -- resolve the image source.
    src = str(media_url or "").strip()
    src_path: Path | None = None
    src_url: str | None = None
    manifest_entry: dict | None = None
    if src:
        if src.startswith(("http://", "https://")) and \
                "/relay-img/arch/" not in src:
            src_url = src
        else:
            src_path, err = _resolve_archive(src)
            if err:
                return {"ok": False, "error": err}
    else:
        chat_id = session_chat_id(runner, "line")
        src_path, manifest_entry = _latest_chat_image(chat_id)
        if src_path is None:
            return {"ok": False,
                    "error": "no inbound image found for this chat — "
                             "pass media_url= with the /relay-img/arch/ "
                             "URL from the 'photo received' note"}

    # -- load bytes.
    try:
        if src_path is not None:
            if src_path.stat().st_size > MAX_BYTES:
                return {"ok": False,
                        "error": f"image exceeds "
                                 f"{MAX_BYTES // (1024 * 1024)} MiB"}
            data = src_path.read_bytes()
        else:
            assert src_url is not None
            data = await _fetch_url(src_url)
    except Exception as exc:
        return {"ok": False, "error": f"could not load image: {exc}"}
    if not data:
        return {"ok": False, "error": "image source is empty"}
    sniffed = _sniff_image(data)
    if sniffed is None:
        return {"ok": False,
                "error": "source is not a supported image "
                         "(jpeg/png/gif/webp only)"}
    mime, ext = sniffed

    # -- store under persona-assets/ with content-hash dedupe.
    sha = hashlib.sha256(data).hexdigest()
    slug = _slug(str(name or "").strip()
                 or str(description or "").strip()
                 or str((manifest_entry or {}).get("file_name") or ""))
    slug = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", slug) or "asset"
    if slug in ("note", "asset"):
        # _slug's empty-fallback ('note') and a bare 'asset' collide
        # across unnamed or Thai-described saves — pin a content hash
        # so each photo keeps its own doc key.
        slug = f"asset-{sha[:8]}"
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{slug}{ext}"
    dest = ASSET_DIR / fname
    if dest.exists() and \
            hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
        fname = f"{slug}-{sha[:8]}{ext}"
        dest = ASSET_DIR / fname
    if not dest.exists():
        dest.write_bytes(data)
    public_url = f"{_public_base()}/arch/persona-assets/{fname}"

    # -- upsert the assets/<slug> doc in the caller's bank. Same
    # pipeline as ada_remember bank writes: content scan first, then
    # non-admin callers' writes park in the pending lane (route='asset'
    # replays through memory_ops.asset_remember on approval) while
    # {full: true} identities write directly.
    desc = str(description or "").strip() or (
        f"Saved photo asset '{slug}'.")
    if manifest_entry:
        sender = str(manifest_entry.get("sender") or "")
        ts = str(manifest_entry.get("ts") or "")[:16]
        desc += (f"\nReceived from {sender} at {ts}."
                 if sender or ts else "")
    body = (
        f"{desc}\n\n"
        f"image_url: {public_url}\n"
        "To re-show this photo, ask for it — memory search attaches the "
        "top image-bearing hit automatically. Explicit resend: "
        f"chat_send image_url={public_url} verbatim."
    )
    key = f"assets/{slug}"
    subject = str(name or slug)
    refused = runner._scan_memory_write(
        route="asset", bank=bank_cfg.name, text=body,
        extra=" ".join(x for x in (slug, public_url) if x))
    if refused is not None:
        return refused
    if runner._memory_staging_required("asset"):
        return await runner._stage_memory_write(
            route="asset", bank=bank_cfg.name, key=key, text=body,
            args={"image_url": public_url, "subject": subject,
                  "slug": slug})
    try:
        res = await memory_ops.asset_remember(
            runner.mddb, runner.banks, runner.memory.instance,
            bank_cfg.name, key, body, public_url,
            subject=subject, session_id=runner.session_id,
            person_entity=identity)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    out = {"ok": True, "bank": res.get("bank", bank_cfg.name),
           "key": res.get("key", key), "verb": res.get("verb"),
           "image_url": public_url, "file": fname,
           "bytes": len(data), "mime": mime,
           "note": "photo saved — the image attached to this reply; "
                   "do NOT resend it via chat_send"}
    if res.get("queued_for_retry"):
        out["queued_for_retry"] = True
        out["note"] = res.get("note") or out["note"]
    if src_path is not None:
        out["source"] = str(src_path)
    else:
        out["source"] = src_url
    return out
