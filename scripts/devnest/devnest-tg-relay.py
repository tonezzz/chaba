#!/usr/bin/env python3
"""Telegram ingress + card command router for the DevNest Home supergroup.

Capture: authenticates the chat and sender, records each update, and replies
in the originating topic. Commands (anchored whole-message forms only):

  explain|status <ref|card-id>   read-only card summary via board-api GET
  APPROVE <ref|card-id>          board-api /respond (open ask/request) or
  REJECT  <ref|card-id>          /action (review card -> close|hold)

Refs normalize like the board: bare digits -> OPS-XXXX, 'ops 0905'/'ops-0905'
-> OPS-0905, anything else must be an exact card id. Unknown or ambiguous
refs are refused and audited (STATE_DIR/audit.jsonl). Approvals only run for
TELEGRAM_APPROVER_IDS (default: callers labelled *tony). All board mutations
go through board-api HTTP — never card YAML or shell execution.

Topic registry (STATE_DIR/topics.json): durable thread_id -> binding map.
Permanent topics are General, Inbox, Control, Ops, Research, Education and
Archive; project topics are named 'PRJ <project-id> — <short title>'.
Identity always comes from the registered message_thread_id, never from a
topic's display title — Telegram does not send the title with ordinary
messages anyway. Unknown threads are quarantined (recorded, one notice, no
commands/intake). forum_topic_created/edited/closed/reopened service
messages keep the registry current; a missed registry can be rebuilt from
project manifests, which stay the source of truth alongside the board.

PDF intake in General/Inbox creates a 'PRJ …' forum topic via
createForumTopic, binds it to the project manifest + board card, and moves
project traffic there; if topic creation fails the reply carries the exact
manual topic name to create. PDFs inside a bound project topic attach to
that project. Topics are never deleted — rollback only marks the registry
entry. Loopback /send routes project notifications to the bound thread and
mirrors a copy to General only when the caller marks it a milestone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import hashlib
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("devnest-tg-relay")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
CHAT_IDS = {
    int(value.strip())
    for value in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if value.strip()
}
CALLERS = {}
for mapping in os.environ.get("TELEGRAM_USER_CALLERS", "").split(","):
    if ":" in mapping:
        user_id, label = mapping.split(":", 1)
        if user_id.strip().isdigit() and label.strip():
            CALLERS[int(user_id)] = label.strip()
SPEAKER = os.environ.get("TG_SPEAKER_TAG", "devnestha").strip() or "devnestha"
LISTEN = os.environ.get("TG_WEBHOOK_LISTEN", "127.0.0.1:8919")
STATE_DIR = Path(os.environ.get(
    "DEVNEST_TELEGRAM_STATE",
    str(Path.home() / ".local/share/devnest/telegram"),
))
PROJECTS_DIR = Path(os.environ.get(
    "DEVNEST_PROJECTS_DIR",
    str(Path.home() / ".local/share/devnest/projects"),
))
MAX_DOCUMENT_BYTES = int(os.environ.get(
    "DEVNEST_MAX_DOCUMENT_BYTES", str(20 * 1024 * 1024)))
OFFSET_FILE = STATE_DIR / "state.json"
UPDATES_FILE = STATE_DIR / "updates.jsonl"
AUDIT_FILE = STATE_DIR / "audit.jsonl"
TOPICS_FILE = STATE_DIR / "topics.json"
CONVERSATIONS_DIR = STATE_DIR / "conversations"
POLL_TIMEOUT = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "25"))
TEXT_POLICY = os.environ.get("DEVNEST_TEXT_POLICY", "private-retained")
BOARD_API = os.environ.get(
    "BOARD_API_BASE", "http://127.0.0.1:8787").rstrip("/")
# APPROVE/REJECT gate: explicit id allowlist wins; otherwise callers whose
# label ends in 'tony' (the board's owner identity, e.g. 'user-tony').
APPROVER_IDS = {
    int(value.strip())
    for value in os.environ.get("TELEGRAM_APPROVER_IDS", "").split(",")
    if value.strip()
} or {
    uid for uid, label in CALLERS.items()
    if label.strip().lower().endswith("tony")
}
COMMAND_RE = re.compile(
    r"^\s*(explain|status|approve|reject)\s+(.+?)\s*$", re.IGNORECASE)
BARE_VERB_RE = re.compile(
    r"^\s*(explain|status|approve|reject)\s*$", re.IGNORECASE)
_REF_RE = re.compile(r"^([A-Za-z]{3})-?(\d{1,4})$")
_NUMERIC_RE = re.compile(r"^\d{1,4}$")
_SPACED_REF_RE = re.compile(r"^([A-Za-z]{3})\s+(\d{1,4})$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")
LANES = {
    "general": "home",
    "control": "control",
    "inbox": "inbox",
    "build": "build",
    "review": "review",
    "research": "research",
    "ops": "ops",
    "ha lab": "ha-lab",
    "education": "education",
    "archive": "archive",
}
# Permanent forum topics, keyed case-insensitively by display name. The
# registry binds them to a thread_id the first time it sees them; identity
# is the thread_id forever after, never the name.
PERMANENT_TOPICS = {
    "general": {"lane": "home", "visibility": "public"},
    "inbox": {"lane": "inbox", "visibility": "public"},
    "control": {"lane": "control", "visibility": "private"},
    "ops": {"lane": "ops", "visibility": "private"},
    "research": {"lane": "research", "visibility": "public"},
    "education": {"lane": "education", "visibility": "public"},
    "archive": {"lane": "archive", "visibility": "archive"},
}
TOPIC_NAME_MAX = 128  # Telegram forum topic title limit
PROJECT_TOPIC_RE = re.compile(
    r"^\s*PRJ\s+([A-Za-z0-9][A-Za-z0-9_-]{2,80})\s*[—–-]\s*(.*)$")
FORBIDDEN_API_METHODS = {
    # The relay may create/close forum topics but must never delete them:
    # topic history is part of the project record.
    "deleteForumTopic",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _topic(msg: dict) -> tuple[str, int | None]:
    thread_id = msg.get("message_thread_id")
    # Telegram assigns the built-in 'General' forum topic thread_id 1;
    # both forms mean General.
    if thread_id in (None, 1):
        return "general", None
    # Telegram does not include the forum topic title in ordinary messages.
    return f"thread-{thread_id}", int(thread_id)


def _lane(topic: str) -> str:
    return LANES.get(topic.casefold(), "unknown")


def _state_offset() -> int | None:
    try:
        return int(json.loads(OFFSET_FILE.read_text()).get("offset"))
    except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_offset(offset: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OFFSET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset, "saved_at": _now()}))
    tmp.replace(OFFSET_FILE)


# --- durable topic registry -------------------------------------------------
#
# TOPICS_FILE maps message_thread_id -> binding:
#   {kind: permanent|project|quarantine, name, lane, visibility,
#    project_id, card_ref, card_id, status, thread_id, ...}
# The board card and the project manifest are the source of truth; the
# registry is their index onto Telegram thread ids and can be rebuilt from
# manifests (see _reconcile_topics). Entries are never deleted — rollback
# marks status='rolled_back'.


def _load_topics() -> dict:
    try:
        data = json.loads(TOPICS_FILE.read_text())
        if isinstance(data, dict) and isinstance(data.get("topics"), dict):
            return data
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass
    return {"version": 1, "topics": {}}


def _save_topics(registry: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOPICS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(TOPICS_FILE)


def _register_topic(thread_id: int, entry: dict) -> dict:
    """Insert or replace one binding and persist the registry."""
    registry = _load_topics()
    record = dict(entry)
    record.setdefault("status", "active")
    record.setdefault("created_at", _now())
    record["thread_id"] = int(thread_id)
    registry["topics"][str(int(thread_id))] = record
    _save_topics(registry)
    return record


def _topic_entry(thread_id: int | None) -> dict | None:
    """Registry binding for a thread, or None. A miss first reconciles the
    registry from project manifests (manifest stays source of truth, so a
    lost/corrupt topics.json heals itself on next lookup)."""
    if thread_id is None:
        return None
    entry = _load_topics()["topics"].get(str(int(thread_id)))
    if entry is None:
        _reconcile_topics()
        entry = _load_topics()["topics"].get(str(int(thread_id)))
    return dict(entry) if entry else None


def _manifest_path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "project.json"


def _load_manifest(project_id: str) -> dict | None:
    try:
        return json.loads(_manifest_path(project_id).read_text())
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def _reconcile_topics() -> dict:
    """Merge manifest-bound topics into the registry. Existing registry
    entries win — reconcile only fills gaps."""
    registry = _load_topics()
    changed = False
    try:
        manifests = sorted(PROJECTS_DIR.glob("*/project.json"))
    except OSError:
        manifests = []
    for path in manifests:
        try:
            manifest = json.loads(path.read_text())
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        topic = manifest.get("topic") or {}
        tid = topic.get("thread_id")
        if tid is None:
            continue
        key = str(int(tid))
        if key in registry["topics"]:
            continue
        project_id = str(manifest.get("project_id") or path.parent.name)
        registry["topics"][key] = {
            "kind": "project",
            "name": topic.get("name")
            or _project_topic_name(project_id, ""),
            "lane": "project",
            "visibility": "project",
            "project_id": project_id,
            "card_ref": manifest.get("card_ref"),
            "card_id": manifest.get("card_id") or project_id,
            "status": topic.get("status") or "active",
            "thread_id": int(tid),
            "bound_at": topic.get("bound_at"),
            "reconciled_at": _now(),
        }
        changed = True
    if changed:
        _save_topics(registry)
    return registry


def _project_title(caption: str, source_name: str) -> str:
    """Short human title for the PRJ topic name: caption first, filename
    stem as fallback."""
    title = " ".join((caption or "").split())[:60].strip()
    if not title:
        title = Path(source_name or "project").stem.replace("_", " ")
    return title.strip("—- ") or "project"


def _project_topic_name(project_id: str, title: str) -> str:
    name = f"PRJ {project_id} — {title}".rstrip(" —-")
    return name[:TOPIC_NAME_MAX]


def _parse_project_topic_name(name: str) -> tuple[str, str] | None:
    match = PROJECT_TOPIC_RE.match(name or "")
    if not match:
        return None
    return match.group(1), (match.group(2) or "").strip()


def _classify_topic_name(name: str) -> dict:
    """Classify a forum topic by its creation-event name: permanent,
    project (PRJ convention), or quarantine. Used only on forum_topic_*
    service events — never to identify ordinary messages."""
    title = (name or "").strip()
    permanent = PERMANENT_TOPICS.get(title.casefold())
    if permanent:
        return {"kind": "permanent", "name": title,
                "lane": permanent["lane"],
                "visibility": permanent["visibility"]}
    parsed = _parse_project_topic_name(title)
    if parsed:
        project_id, short_title = parsed
        return {"kind": "project", "name": title, "lane": "project",
                "visibility": "project", "project_id": project_id,
                "title": short_title}
    return {"kind": "quarantine", "name": title or None,
            "lane": "unknown", "visibility": "quarantine",
            "notified": False}


def _manifest_bind_topic(project_id: str, thread_id: int, chat_id: int,
                         name: str) -> dict | None:
    """Write the topic binding into the project manifest (source of
    truth). None when the project has no manifest yet."""
    path = _manifest_path(project_id)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    manifest["topic"] = {
        "thread_id": int(thread_id),
        "chat_id": int(chat_id),
        "name": name,
        "lane": "project",
        "visibility": "project",
        "status": "active",
        "bound_at": _now(),
    }
    manifest["at"] = _now()
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def _bind_project_topic(chat_id: int, thread_id: int, project_id: str,
                        card: dict, name: str) -> dict:
    """Bind a forum thread to a project: registry entry + manifest topic
    block + board card comment. Raises if the registry or manifest write
    fails; the card comment is best-effort."""
    manifest = _manifest_bind_topic(project_id, thread_id, chat_id, name)
    if manifest is None:
        raise LookupError(
            f"project {project_id} has no manifest to bind topic to")
    entry = _register_topic(thread_id, {
        "kind": "project",
        "name": name,
        "lane": "project",
        "visibility": "project",
        "project_id": project_id,
        "card_ref": card.get("ref") or manifest.get("card_ref"),
        "card_id": card.get("id") or manifest.get("card_id") or project_id,
        "bound_at": _now(),
    })
    try:
        _board_post("/comment", {
            "id": entry["card_id"],
            "from": "devnest-tg",
            "text": (f"TG topic bound: DevNestHA thread_id={thread_id} "
                     f"name='{name}' — project replies/notifications route "
                     f"there; only milestone summaries mirror to General."),
        })
    except Exception as exc:  # binding stands; the comment can be redone
        LOG.warning("card topic-bind comment failed for %s: %s",
                    project_id, exc)
        entry["card_bind_error"] = str(exc)[:200]
    return entry


def _rollback_topic_binding(thread_id: int, reason: str) -> dict | None:
    """Mark a binding rolled_back — the entry and the Telegram topic are
    kept; the registry never loses the association history."""
    registry = _load_topics()
    entry = registry["topics"].get(str(int(thread_id)))
    if entry is None:
        return None
    entry["status"] = "rolled_back"
    entry["rollback_reason"] = reason[:240]
    entry["rolled_back_at"] = _now()
    _save_topics(registry)
    _audit({"result": "topic_rolled_back", "thread_id": int(thread_id),
            "detail": reason[:240]})
    return entry


def _create_forum_topic(chat_id: int, name: str) -> int:
    result = _api("createForumTopic",
                  {"chat_id": chat_id, "name": name[:TOPIC_NAME_MAX]})
    thread_id = (result.get("result") or {}).get("message_thread_id")
    if thread_id is None:
        raise RuntimeError("createForumTopic returned no message_thread_id")
    return int(thread_id)


def _find_project_topic(project_id: str | None = None,
                        ref: str | None = None) -> dict | None:
    """Active project binding by project_id or card ref/id."""
    for entry in _load_topics()["topics"].values():
        if entry.get("kind") != "project":
            continue
        if entry.get("status") in ("rolled_back", "closed"):
            continue
        if project_id and entry.get("project_id") == project_id:
            return entry
        if ref and ref.upper() in (
                str(entry.get("card_ref") or "").upper(),
                str(entry.get("card_id") or "").upper()):
            return entry
    return None


def _forum_event(msg: dict) -> str | None:
    for kind in ("forum_topic_created", "forum_topic_edited",
                 "forum_topic_closed", "forum_topic_reopened"):
        if kind in msg:
            return kind.split("forum_topic_", 1)[1]
    return None


def _handle_forum_event(update: dict, msg: dict, chat_id: int,
                        thread_id: int, sender: dict, kind: str) -> None:
    """Register lifecycle events. 'created'/'edited' classify by name;
    'closed'/'reopened' only flip status — bindings are never deleted."""
    if thread_id is None:
        return
    event = {"update_id": update.get("update_id"),
             "message_id": msg.get("message_id"),
             "chat_id": chat_id, "thread_id": int(thread_id),
             "sender_id": sender.get("id"),
             "sender_label": CALLERS.get(sender.get("id"))}
    if kind in ("closed", "reopened"):
        entry = _topic_entry(thread_id) or {
            "kind": "quarantine", "lane": "unknown",
            "visibility": "quarantine", "name": None}
        entry["status"] = "closed" if kind == "closed" else "active"
        _register_topic(thread_id, entry)
        event["result"] = f"topic_{kind}"
        _audit(event)
        return
    name = ""
    if kind == "created":
        name = str((msg.get("forum_topic_created") or {}).get("name") or "")
    else:
        name = str((msg.get("forum_topic_edited") or {}).get("name") or "")
    if kind == "edited" and not name:
        # icon-only edits carry no name — never reclassify on them
        event["result"] = "topic_edited"
        _audit(event)
        return
    entry = _classify_topic_name(name)
    entry["created_by"] = sender.get("id")
    existing = _topic_entry(thread_id)
    if existing and existing.get("kind") == "project" \
            and entry.get("kind") == "project" \
            and existing.get("project_id") == entry.get("project_id"):
        for field in ("card_ref", "card_id", "bound_at"):
            if existing.get(field) and not entry.get(field):
                entry[field] = existing[field]
    if entry.get("kind") == "project":
        project_id = entry["project_id"]
        manifest = _load_manifest(project_id)
        if manifest:
            _manifest_bind_topic(project_id, thread_id, chat_id,
                                 entry["name"])
            entry["card_ref"] = manifest.get("card_ref")
            entry["card_id"] = manifest.get("card_id") or project_id
            try:
                _board_post("/comment", {
                    "id": entry["card_id"], "from": "devnest-tg",
                    "text": (f"TG topic bound: DevNestHA thread_id="
                             f"{thread_id} name='{entry['name']}'")})
            except Exception as exc:
                LOG.warning("card topic-bind comment failed for %s: %s",
                            project_id, exc)
    entry["notified"] = True
    _register_topic(thread_id, entry)
    event["result"] = f"topic_{kind}"
    event["topic_kind"] = entry["kind"]
    event["topic_name"] = entry.get("name")
    _audit(event)
    if entry["kind"] == "quarantine":
        notice = (f"[{SPEAKER}] topic '{entry.get('name')}' is not a "
                  f"registered lane — quarantined. Permanent topics: "
                  f"{', '.join(t.title() for t in PERMANENT_TOPICS)}; "
                  f"project topics: 'PRJ <project-id> — <title>'.")
    else:
        notice = (f"[{SPEAKER}] topic registered: {entry.get('name')} "
                  f"({entry['kind']}, lane={entry.get('lane')})")
    _send_text(chat_id, notice, thread_id)


def _quarantine_topic(chat_id: int, thread_id: int) -> None:
    """Unknown thread: quarantine it and post the policy notice once."""
    entry = _topic_entry(thread_id)
    if entry is None:
        entry = _register_topic(thread_id, {
            "kind": "quarantine", "name": None, "lane": "unknown",
            "visibility": "quarantine", "notified": False})
    _audit({"result": "topic_quarantined", "chat_id": chat_id,
            "thread_id": int(thread_id)})
    if entry.get("notified"):
        return
    entry["notified"] = True
    _register_topic(thread_id, entry)
    _send_text(
        chat_id,
        f"[{SPEAKER}] this topic is not registered — quarantined. "
        f"Permanent topics: {', '.join(t.title() for t in PERMANENT_TOPICS)}; "
        f"project topics use 'PRJ <project-id> — <title>'. Rename the topic "
        f"to register it.",
        thread_id,
    )


def _api(method: str, params: dict | None = None) -> dict:
    if method in FORBIDDEN_API_METHODS:
        raise RuntimeError(
            f"{method} is forbidden — forum topics are never deleted")
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    body = json.dumps(params or {}).encode()
    req = Request(
        f"{API_BASE}/bot{BOT_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urlopen(req, timeout=POLL_TIMEOUT + 15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", f"Telegram {method} failed"))
    return result


def _send_text(chat_id: int, text: str, thread_id: int | None = None) -> None:
    params: dict[str, object] = {"chat_id": chat_id, "text": text[:4000]}
    if thread_id is not None:
        params["message_thread_id"] = thread_id
    _api("sendMessage", params)


def _safe_filename(name: str) -> str:
    """Keep uploaded names useful without allowing path traversal."""
    base = Path(name or "telegram-document").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    return (base or "telegram-document")[:180]


def _download_document(document: dict,
                       project_id: str | None = None) -> tuple[Path, str, int]:
    """Download one bounded Telegram document and return path, hash, bytes.

    With project_id, the file attaches to that existing project (its
    manifest gains a 'sources' entry); without it the sha names a new
    project directory."""
    size = int(document.get("file_size") or 0)
    if size > MAX_DOCUMENT_BYTES:
        raise ValueError(
            f"document is {size} bytes; limit is {MAX_DOCUMENT_BYTES}")
    file_info = _api("getFile", {"file_id": document["file_id"]})
    file_path = str((file_info.get("result") or {}).get("file_path") or "")
    if not file_path or ".." in Path(file_path).parts:
        raise ValueError("Telegram returned an unsafe file path")
    url = f"{API_BASE}/file/bot{BOT_TOKEN}/{file_path}"
    name = _safe_filename(document.get("file_name") or file_path)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".telegram-", suffix=".part", dir=PROJECTS_DIR)
    digest = hashlib.sha256()
    count = 0
    try:
        with os.fdopen(fd, "wb") as out, urlopen(url, timeout=60) as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_DOCUMENT_BYTES:
                    raise ValueError(
                        f"document exceeded {MAX_DOCUMENT_BYTES} bytes")
                digest.update(chunk)
                out.write(chunk)
        sha = digest.hexdigest()
        pid = project_id or f"kk-video-{sha[:12]}"
        project_dir = PROJECTS_DIR / pid
        (project_dir / "source").mkdir(parents=True, exist_ok=True)
        destination = project_dir / "source" / name
        Path(temp_name).replace(destination)
        source_entry = {
            "filename": name,
            "sha256": sha,
            "bytes": count,
            "telegram_file_size": size or count,
            "at": _now(),
        }
        manifest_file = project_dir / "project.json"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())
            sources = manifest.get("sources")
            if not isinstance(sources, list):
                sources = ([manifest["source"]]
                           if isinstance(manifest.get("source"), dict) else [])
            if not any(s.get("sha256") == sha for s in sources):
                sources.append(source_entry)
            manifest["sources"] = sources
            manifest["at"] = _now()
        else:
            manifest = {
                "project_id": pid,
                "source": source_entry,
                "sources": [source_entry],
                "status": "intake_downloaded",
                "next": "requirements_extraction",
                "at": _now(),
            }
        manifest_file.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        return destination, sha, count
    except Exception:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass
        raise


def _ensure_project_card(project_id: str, source_name: str, sha: str,
                         caption: str) -> dict:
    """Create one private board project per source hash, idempotently."""
    for card in (_board_get("/cards").get("cards") or []):
        if str(card.get("id") or "") == project_id:
            return card
    return _board_post("/card", {
        "id": project_id,
        "title": f"KK short movie — {source_name}",
        "column": "backlog",
        "priority": "high",
        "program": "devnest",
        "tags": ["kk", "video", "devnest", "project"],
        "brief": (
            f"KK short-video intake from {source_name}; "
            f"source sha256={sha}. Requirements extraction and planning pending."
        ),
        "spec": (
            "Assess the attached KK source material for a short movie. "
            "Preserve page/source provenance, extract requirements, identify "
            "rights/consent risks, and prepare a creative brief, story beats, "
            "script, storyboard, shot list, asset matrix, preview plan, and "
            "QC plan before asking Tony. Telegram caption: " + caption[:500]
        ),
        "on_exists": "error",
    })


def _document_is_pdf(document: dict) -> bool:
    name = str(document.get("file_name") or "").lower()
    mime = str(document.get("mime_type") or "").lower()
    return mime == "application/pdf" or name.endswith(".pdf")


def _intake_ack(update: dict, msg: dict, chat_id: int,
                project_id: str, sha: str, count: int,
                detail: str) -> None:
    _audit({
        "update_id": update.get("update_id"),
        "message_id": msg.get("message_id"),
        "chat_id": chat_id,
        "result": "document_downloaded",
        "project_id": project_id,
        "sha256": sha,
        "bytes": count,
        "detail": detail,
    })


def _handle_document(update: dict, msg: dict, chat_id: int,
                     thread_id: int | None,
                     topic_entry: dict | None = None) -> None:
    document = msg.get("document") or {}
    if not _document_is_pdf(document):
        _audit({
            "update_id": update.get("update_id"),
            "message_id": msg.get("message_id"),
            "chat_id": chat_id,
            "result": "refused",
            "detail": "only PDF documents are accepted",
        })
        _send_text(chat_id, f"[{SPEAKER}] intake refused: send a PDF document",
                   thread_id)
        return
    if topic_entry is None:
        topic_entry = _topic_entry(thread_id)
    bound_project = None
    if (topic_entry or {}).get("kind") == "project" \
            and (topic_entry or {}).get("status") == "active":
        bound_project = (topic_entry or {}).get("project_id")
    try:
        if bound_project:
            # Same-topic intake: the thread is bound to a project, so the
            # PDF attaches to it — no new card, no new topic.
            destination, sha, count = _download_document(
                document, project_id=bound_project)
            _intake_ack(update, msg, chat_id, bound_project, sha, count,
                        "attached to bound project topic")
            _send_text(
                chat_id,
                f"[{SPEAKER}] INTAKE attached\n"
                f"project={bound_project}\nsha256={sha[:12]}\n"
                f"file={destination.name}",
                thread_id,
            )
            return
        destination, sha, count = _download_document(document)
        project_id = destination.parents[1].name
        source_name = str(document.get("file_name") or destination.name)
        caption = str(msg.get("caption") or "")
        card = _ensure_project_card(project_id, source_name, sha, caption)
        manifest_path = destination.parents[1] / "project.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["card_id"] = card.get("id") or project_id
        manifest["card_ref"] = card.get("ref")
        manifest["caption"] = caption[:1000]
        manifest["status"] = "intake_ready"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        card_label = card.get("ref") or card.get("id")
        topic_name = _project_topic_name(
            project_id, _project_title(caption, source_name))
        project_thread = None
        try:
            project_thread = _create_forum_topic(chat_id, topic_name)
            try:
                _bind_project_topic(
                    chat_id, project_thread, project_id, card, topic_name)
            except Exception as bind_exc:
                _rollback_topic_binding(project_thread, str(bind_exc))
                raise bind_exc
        except Exception as exc:
            # Topic creation/binding failed: intake still stands. The reply
            # carries the exact topic name so Tony can create it by hand —
            # the relay binds it when forum_topic_created arrives.
            LOG.warning("project topic creation failed for %s: %s",
                        project_id, exc)
            manifest["topic"] = {
                "status": "manual_pending",
                "suggested_name": topic_name,
                "chat_id": int(chat_id),
                "error": str(exc)[:240],
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            _audit({
                "update_id": update.get("update_id"),
                "message_id": msg.get("message_id"),
                "chat_id": chat_id,
                "result": "topic_manual_pending",
                "project_id": project_id,
                "card_ref": card.get("ref"),
                "suggested_name": topic_name,
                "detail": str(exc)[:240],
            })
            _send_text(
                chat_id,
                f"[{SPEAKER}] INTAKE downloaded\n"
                f"project={project_id}\nsha256={sha[:12]}\ncard={card_label}\n"
                f"topic setup: create a forum topic named '{topic_name}' — "
                "the relay binds it automatically when it is created",
                thread_id,
            )
            return
        _intake_ack(update, msg, chat_id, project_id, sha, count,
                    f"new project topic thread={project_thread}")
        _send_text(
            chat_id,
            f"[{SPEAKER}] INTAKE downloaded\n"
            f"project={project_id}\nsha256={sha[:12]}\ncard={card_label}\n"
            f"topic='{topic_name}' (thread {project_thread}) — project "
            "replies and notifications move there",
            thread_id,
        )
        _send_text(
            chat_id,
            f"[{SPEAKER}] project {project_id} open\n"
            f"card={card_label}\nsource={destination.name}\n"
            "keep project work in this topic; only milestone summaries "
            "mirror to General",
            project_thread,
        )
    except Exception as exc:
        LOG.warning("document intake failed: %s", exc)
        _audit({
            "update_id": update.get("update_id"),
            "message_id": msg.get("message_id"),
            "chat_id": chat_id,
            "result": "document_failed",
            "detail": str(exc)[:240],
        })
        _send_text(chat_id, f"[{SPEAKER}] INTAKE failed: {str(exc)[:240]}",
                   thread_id)


def _record(update: dict, msg: dict, chat: dict, sender: dict,
            topic: str, thread_id: int | None, lane: str,
            authorized: bool, topic_status: str = "registered") -> None:
    chat_id = int(chat["id"])
    sender_id = sender.get("id")
    text = msg.get("text") or msg.get("caption") or ""
    event = {
        "at": _now(),
        "update_id": update.get("update_id"),
        "message_id": msg.get("message_id"),
        "chat_id": chat_id,
        "chat_title": chat.get("title"),
        "chat_type": chat.get("type"),
        "message_thread_id": thread_id,
        "topic": topic,
        "topic_status": topic_status,
        "lane": lane,
        "sender_id": sender_id,
        "sender_label": CALLERS.get(sender_id),
        "authorization": "allowed" if authorized else "quarantined",
        "text_policy": TEXT_POLICY if authorized else "metadata-only",
    }
    if authorized and TEXT_POLICY != "metadata-only":
        event["text"] = text
    document = msg.get("document")
    if document:
        event["document"] = {
            "filename": _safe_filename(document.get("file_name") or ""),
            "mime_type": document.get("mime_type"),
            "bytes": document.get("file_size"),
            "file_id_present": bool(document.get("file_id")),
        }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with UPDATES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    conversation = CONVERSATIONS_DIR / str(chat_id) \
        / f"{_safe_filename(topic)}.jsonl"
    conversation.parent.mkdir(parents=True, exist_ok=True)
    with conversation.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


# --- board-api command surface (read via GET /cards; writes via POST only) --


def normalize_ref(token: str) -> str | None:
    """'0905' -> 'OPS-0905', 'ops 0911'/'OPS-0911' -> 'OPS-0911', or a slug."""
    t = re.sub(_SPACED_REF_RE, r"\1-\2", token.strip().strip(".,;:!?\"'`"))
    m = _REF_RE.match(t)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):04d}"
    if _NUMERIC_RE.match(t):
        return f"OPS-{int(t):04d}"
    if _SLUG_RE.match(t.lower()):
        return t.lower()
    return None


def parse_command(text: str) -> tuple[str, str] | None:
    """Anchored whole-message commands only — 'please explain 0905' is not
    one. Returns (verb, raw operand) or None."""
    m = COMMAND_RE.match(text or "")
    if m:
        return m.group(1).lower(), m.group(2)
    m = BARE_VERB_RE.match(text or "")
    if m:
        return m.group(1).lower(), ""
    return None


def _board_get(path: str) -> dict:
    req = Request(f"{BOARD_API}{path}")
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def _board_post(path: str, body: dict) -> dict:
    req = Request(
        f"{BOARD_API}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"board-api {path} -> {exc.code}: {detail}")


def _card_index() -> dict:
    data = _board_get("/cards")
    index: dict[str, list] = {}
    for card in data.get("cards", []):
        ref = str(card.get("ref") or "").strip().upper()
        cid = str(card.get("id") or "").strip()
        for key in (ref, cid):
            if key:
                index.setdefault(key, []).append(card)
    return index


def resolve_card(index: dict, operand: str) -> dict:
    """Exact ref-or-id resolution. One hit wins; zero/many refuse."""
    hits, seen = [], set()
    for key in (operand.upper(), operand.lower()):
        for card in index.get(key, []):
            cid = card.get("id")
            if cid not in seen:
                seen.add(cid)
                hits.append(card)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"unknown ref {operand} — no card matches")
    names = ", ".join(str(c.get("id")) for c in hits[:3])
    raise LookupError(f"ambiguous ref {operand} — matches: {names}")


def _open_requests(card: dict) -> list:
    return [r for r in card.get("requests") or []
            if r.get("status") not in ("answered", "closed")]


def _status_line(card: dict) -> str:
    col = str(card.get("column") or "backlog")
    a = card.get("action") or {}
    if a.get("status"):
        return f"{col} (action: {a.get('type') or '?'} {a['status']})"
    return col


def _phase_line(card: dict) -> str:
    a = card.get("action") or {}
    col = str(card.get("column") or "backlog")
    if a.get("status") == "running":
        return f"dispatch running on {a.get('runner') or 'unclaimed'}"
    if a.get("status") == "queued":
        return "queued for dispatch"
    if col == "review":
        return f"awaiting review ({card.get('review_kind') or 'verify'})"
    if col == "done":
        return "closed"
    if col == "doing":
        return "in progress"
    return col


def _verified_line(card: dict) -> str:
    checks = [c for c in card.get("checks") or [] if c.get("k") == "verify"]
    if checks:
        mark = {True: "ok", False: "failed"}.get(checks[-1].get("ok"), "pending")
        return f"{mark}: {str(checks[-1].get('how') or '')[:160]}"
    for entry in reversed(card.get("comms") or []):
        if "verif" in str(entry.get("text") or "").lower():
            return (f"{entry.get('from')}@{entry.get('at')}: "
                    f"{str(entry.get('text'))[:160]}")
    return "none recorded"


def _next_line(card: dict) -> str:
    a = card.get("action") or {}
    if card.get("column") == "done":
        return "none — card closed"
    if a.get("status") == "queued":
        return "queued — awaiting runner claim"
    if a.get("status") == "running":
        return "runner in progress — next: finish + verify"
    note = str(card.get("note") or "").strip()
    return note[:200] if note else "none recorded"


def _ask_line(card: dict) -> str:
    ask = card.get("ask")
    if isinstance(ask, str):
        ask = {"question": ask}
    if isinstance(ask, dict) and ask.get("status") != "answered" \
            and str(ask.get("question") or "").strip():
        return str(ask["question"])[:200]
    open_reqs = _open_requests(card)
    if open_reqs:
        bits = [str(r.get("ask") or r.get("needed") or r.get("id") or "?")[:80]
                for r in open_reqs[:2]]
        tail = f" (+{len(open_reqs) - 2} more)" if len(open_reqs) > 2 else ""
        return "; ".join(bits) + tail
    return "none"


def summarize_card(card: dict) -> str:
    """Deterministic status/phase/verified/next/ask — same card state in,
    same text out."""
    head = " ".join(x for x in (
        f"[{SPEAKER}]",
        str(card.get("ref") or ""),
        str(card.get("id") or ""),
        "—",
        str(card.get("title") or "")) if x)
    return "\n".join((
        head,
        f"status: {_status_line(card)}",
        f"phase: {_phase_line(card)}",
        f"verified: {_verified_line(card)}",
        f"next: {_next_line(card)}",
        f"ask: {_ask_line(card)}",
    ))


def _apply_decision(card: dict, verb: str) -> str:
    """Sanctioned mutation paths only: /respond for a pending question,
    /action for a review-column verdict. Nothing else mutates."""
    answer = f"{verb} via devnest-tg"
    open_reqs = _open_requests(card)
    if len(open_reqs) > 1:
        raise LookupError(
            f"{len(open_reqs)} open requests — name one on the board, "
            f"bare {verb.upper()} cannot pick")
    if len(open_reqs) == 1:
        rid = str(open_reqs[0].get("id") or "request")
        res = _board_post("/respond", {
            "id": card["id"], "request_id": rid,
            "answer": answer, "from": "tony"})
        return f"answered {rid} ({res.get('message', 'ok')})"
    ask = card.get("ask")
    ask_open = (isinstance(ask, str) and ask.strip()) or \
        (isinstance(ask, dict) and ask.get("status") != "answered"
         and str(ask.get("question") or "").strip())
    if ask_open:
        res = _board_post("/respond", {
            "id": card["id"], "answer": answer, "from": "tony"})
        return f"answered ask ({res.get('message', 'ok')})"
    if card.get("column") == "review":
        do = "close" if verb == "approve" else "hold"
        res = _board_post("/action", {
            "id": card["id"], "do": do, "from": "tony"})
        return f"action {do} ({res.get('message', 'ok')})"
    raise LookupError(
        f"nothing pending — no open ask/request, column="
        f"{card.get('column')}")


def _audit(event: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    event.setdefault("at", _now())
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def handle_command(update: dict, msg: dict, chat_id: int, sender: dict,
                   topic: str, thread_id: int | None) -> bool:
    """Run a board command if the message is one. True = handled (the
    generic capture ack is skipped)."""
    parsed = parse_command(msg.get("text") or "")
    if not parsed:
        return False
    verb, operand_raw = parsed
    sender_id = sender.get("id")
    event = {
        "update_id": update.get("update_id"),
        "message_id": msg.get("message_id"),
        "sender_id": sender_id,
        "sender_label": CALLERS.get(sender_id),
        "command": verb, "operand": operand_raw,
        "chat_id": chat_id, "topic": topic, "thread_id": thread_id,
    }

    def refuse(reason: str) -> None:
        event["result"] = "refused"
        event["detail"] = reason
        _audit(event)
        LOG.warning("refused %s %r sender=%s: %s",
                    verb, operand_raw, sender_id, reason)
        _send_text(chat_id, f"[{SPEAKER}] {verb} refused: {reason}", thread_id)

    operand = normalize_ref(operand_raw) if operand_raw else None
    event["normalized"] = operand
    if operand is None:
        refuse("usage: explain <ref|card-id>, APPROVE <ref>, REJECT <ref>"
               if not operand_raw
               else f"unparseable ref {operand_raw!r}")
        return True
    if verb in ("approve", "reject") and sender_id not in APPROVER_IDS:
        refuse("sender not in approver allowlist")
        return True
    try:
        card = resolve_card(_card_index(), operand)
    except LookupError as exc:
        refuse(str(exc))
        return True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError,
            RuntimeError) as exc:
        refuse(f"board-api unavailable: {exc}")
        return True
    event["card"] = card.get("id")
    if verb in ("explain", "status"):
        _send_text(chat_id, summarize_card(card), thread_id)
        event["result"] = "explained"
        _audit(event)
        LOG.info("explained %s for sender=%s topic=%s",
                 card.get("id"), sender_id, topic)
        return True
    try:
        outcome = _apply_decision(card, verb)
    except (LookupError, RuntimeError, ValueError) as exc:
        refuse(str(exc))
        return True
    event["result"] = f"{verb}d"
    event["detail"] = outcome
    _audit(event)
    LOG.info("%s %s (%s) for sender=%s: %s",
             verb.upper(), card.get("ref"), card.get("id"), sender_id, outcome)
    _send_text(
        chat_id,
        f"[{SPEAKER}] {verb.upper()} {card.get('ref') or card.get('id')}: "
        f"{outcome}",
        thread_id,
    )
    return True


def handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    sender = msg.get("from") or {}
    topic, thread_id = _topic(msg)
    forum_kind = _forum_event(msg)
    if forum_kind and chat_id in CHAT_IDS and thread_id is not None:
        # Topic structure is a group-level fact: registration honours any
        # member's create/edit event, gated on the chat allowlist alone.
        _handle_forum_event(
            update, msg, chat_id, thread_id, sender, forum_kind)
    entry = _topic_entry(thread_id)
    if entry:
        topic = str(entry.get("name") or topic)
        lane = str(entry.get("lane") or "unknown")
        topic_status = str(entry.get("kind") or "registered")
    elif thread_id is None:
        lane = _lane("general")
        topic_status = "general"
    else:
        lane = "unknown"
        topic_status = "unknown"
    sender_id = sender.get("id")
    authorized = chat_id in CHAT_IDS and sender_id in CALLERS
    _record(update, msg, chat, sender, topic, thread_id, lane, authorized,
            topic_status)
    if forum_kind:
        return
    if not authorized:
        LOG.warning("quarantined chat=%s sender=%s topic=%s",
                    chat_id, sender_id, topic)
        if chat_id in CHAT_IDS and sender_id is not None:
            _send_text(
                chat_id,
                f"[{SPEAKER}] sender not authorized; user id={sender_id}",
                thread_id,
            )
        return
    if topic_status in ("unknown", "quarantine") or \
            (entry or {}).get("status") in ("rolled_back", "closed"):
        _quarantine_topic(chat_id, thread_id)
        return
    if handle_command(update, msg, chat_id, sender, topic, thread_id):
        return
    if msg.get("document"):
        _handle_document(update, msg, chat_id, thread_id, entry)
        return
    message_id = msg.get("message_id")
    LOG.info("captured update=%s chat=%s sender=%s topic=%s lane=%s",
             update.get("update_id"), chat_id, sender_id, topic, lane)
    _send_text(
        chat_id,
        f"[{SPEAKER}] captured topic={topic} lane={lane} message={message_id}",
        thread_id,
    )


def route_send(body: dict) -> dict:
    """Outbound send with project-topic routing and opt-in General mirror.

    thread resolution: explicit message_thread_id wins; else project_id or
    card_ref/card_id resolves through the registry — unbound projects are an
    error, never a silent post to General. milestone=true (or
    mirror='general') additionally mirrors the text to General."""
    chat_id = int(body.get("chat_id") or next(iter(CHAT_IDS)))
    text = str(body["text"])
    thread_id = body.get("message_thread_id")
    project_id = str(body.get("project_id") or "").strip() or None
    ref = str(body.get("card_ref") or body.get("card_id") or "") \
        .strip() or None
    entry = None
    if thread_id is None and (project_id or ref):
        entry = _find_project_topic(project_id=project_id, ref=ref)
        if entry is None:
            raise LookupError(
                f"no active topic bound for project={project_id or '-'} "
                f"card={ref or '-'}")
        thread_id = entry.get("thread_id")
    if thread_id is not None:
        thread_id = int(thread_id)
    _send_text(chat_id, text, thread_id)
    mirrored = False
    milestone = body.get("milestone") in (True, 1, "true", "True", "yes") \
        or str(body.get("mirror") or "").strip().lower() == "general"
    if milestone and thread_id is not None:
        _send_text(chat_id, text, None)
        mirrored = True
    return {
        "ok": True,
        "chat_id": chat_id,
        "message_thread_id": thread_id,
        "project_id": (entry or {}).get("project_id"),
        "mirrored_general": mirrored,
    }


class PushHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({
            "ok": True,
            "mode": "poll",
            "chat_ids": sorted(CHAT_IDS),
            "state_dir": str(STATE_DIR),
            "topics": len(_load_topics()["topics"]),
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/send":
            self.send_error(404)
            return
        size = int(self.headers.get("content-length", "0"))
        try:
            body = json.loads(self.rfile.read(size))
            result = route_send(body)
            encoded = json.dumps(result).encode()
            self.send_response(200)
        except LookupError as exc:
            encoded = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(404)
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            encoded = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
        except Exception as exc:  # outbound API errors are caller-visible
            encoded = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(502)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.info("http: " + fmt, *args)


def serve_http() -> None:
    host, _, port = LISTEN.rpartition(":")
    server = ThreadingHTTPServer((host or "127.0.0.1", int(port or "8919")),
                                 PushHandler)
    server.serve_forever()


def poll() -> None:
    offset = _state_offset()
    while True:
        try:
            params: dict[str, object] = {
                "timeout": POLL_TIMEOUT,
                "limit": 50,
                "allowed_updates": json.dumps(["message", "edited_message"]),
            }
            if offset is not None:
                params["offset"] = offset
            result = _api("getUpdates", params)
            for update in result.get("result", []):
                update_id = int(update["update_id"])
                offset = update_id + 1
                # Persist after capture, before acknowledgement: a restart can
                # at worst repeat a Telegram acknowledgement, not lose input.
                # A poison update must not wedge the loop — it is logged,
                # skipped past, and the offset still advances.
                try:
                    handle_update(update)
                except Exception:
                    LOG.exception("update %s failed", update_id)
                _save_offset(offset)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            LOG.warning("poll error: %s", exc)
            time.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not CHAT_IDS:
        raise SystemExit("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    if not CALLERS:
        raise SystemExit("TELEGRAM_USER_CALLERS is empty")
    threading.Thread(target=serve_http, daemon=True).start()
    LOG.info("capture relay listening on %s", LISTEN)
    registry = _reconcile_topics()
    LOG.info("topic registry: %d binding(s) at %s",
             len(registry["topics"]), TOPICS_FILE)
    poll()


if __name__ == "__main__":
    main()
