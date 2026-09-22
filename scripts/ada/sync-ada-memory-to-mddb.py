#!/usr/bin/env python3
"""Sync the Ada memory vault (docs/ada-memory/) to MDDB bank collections.

The vault is the human authoring tier for Ada's curated memory banks.
Each folder maps to one ada-ha-bank-* collection via the bank registry in
docs/ssot/apps/ssot.apps.ada-memory-banks.yml:

  shared bank        -> <bank>/            -> mddb_collection
  instance (multi)   -> <bank>/<instance>/ -> {instance} expanded per dir
  instance (single)  -> <bank>/            -> literal collection name

  general/            ada-ha-bank-general
  home/               ada-ha-bank-home
  people/             ada-ha-bank-people
  personal/tony/      ada-ha-bank-personal-tony
  personal/michael/   ada-ha-bank-personal-michael
  tony-projects/      ada-ha-bank-projects-tony
  note/               ada-ha-bank-note-tony
  inbox/              (never synced — voice notes land here for review)

Usage:
  sync-ada-memory-to-mddb.py [--dry-run]      # vault -> MDDB
  sync-ada-memory-to-mddb.py --export-inbox   # MDDB voice docs -> inbox/
  sync-ada-memory-to-mddb.py --delete-remote  # also delete remote-only docs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests
import yaml

REPO = Path(__file__).resolve().parents[2]
SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
SCHEMA_SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-memory-schema.yml"
VAULT = REPO / "docs/ada-memory"
MDDB = os.environ.get("ADA_MEMORY_MDDB_URL", "http://100.74.146.0:11023/v1").rstrip("/")

# Field lists are derived from the meta_schema block in
# ssot.apps.ada-memory-schema.yml — extend the schema there, not here.
_VAULT_STAMPED = ("bank", "scope", "source", "written_by")


def _load_meta_fields() -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        schema = yaml.safe_load(SCHEMA_SSOT.read_text()).get("meta_schema") or {}
        fields = tuple((schema.get("fields") or {}).keys())
        if fields:
            managed = fields
            declared = tuple(f for f in fields if f not in _VAULT_STAMPED)
            return declared, managed
    except Exception:
        pass
    # Fallback if the schema SSOT is unreadable.
    declared = (
        "kind", "status", "subject", "attribute", "valid_from", "last_verified",
        "valid_until", "applies_to", "supersedes", "superseded_by",
        "retracted_reason", "origin_source", "origin_written_by",
    )
    return declared, _VAULT_STAMPED + declared


META_FIELDS, MANAGED_FIELDS = _load_meta_fields()


def load_bank_map() -> list[dict]:
    """Derive [(dir, bank, collection, scope, writable)] from the SSOT registry."""
    banks = yaml.safe_load(SSOT.read_text()).get("banks") or {}
    out = []
    for name, spec in banks.items():
        scope = spec.get("scope", "shared")
        coll = spec.get("mddb_collection") or ""
        instances = spec.get("instances") or []
        entry = {"bank": name, "writable": bool(spec.get("writable"))}
        if scope == "instance" and len(instances) > 1 and "{instance}" in coll:
            # Genuinely multi-instance bank (personal) -> per-instance subdirs.
            for inst in instances:
                out.append({**entry, "dir": f"{name}/{inst}",
                            "collection": coll.replace("{instance}", inst),
                            "scope": inst})
        elif scope == "instance":
            # Single-instance bank (note, tony-projects) -> flat dir;
            # the {instance} placeholder just expands to the one instance.
            inst = instances[0] if instances else ""
            out.append({**entry, "dir": name,
                        "collection": coll.replace("{instance}", inst),
                        "scope": inst})
        else:
            out.append({**entry, "dir": name, "collection": coll, "scope": "shared"})
    return out


def parse_note(path: Path) -> dict | None:
    """Parse '--- frontmatter --- body' -> {frontmatter, body}. None if no fm."""
    text = path.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return None
    fm = yaml.safe_load(m.group(1)) or {}
    return {"frontmatter": fm, "body": m.group(2).strip()}


def build_meta(fm: dict, bank: str, scope: str, today: str) -> dict:
    meta = {
        "bank": [bank],
        "scope": [scope],
        "status": [str(fm.get("status") or "active")],
        "kind": [str(fm.get("kind") or "note")],
        # The vault is the writer of record — this is what lets the sync
        # distinguish "remote last touched by vault" (safe to overwrite)
        # from "remote last touched by voice/ada_remember" (conflict).
        "source": ["manual"],
        "written_by": [VAULT_WRITER],
        "valid_from": [str(fm.get("valid_from") or today)],
        "last_verified": [str(fm.get("last_verified") or today)],
    }
    # Preserve where the memory originally came from (e.g. a promoted
    # voice note keeps origin_source=voice).
    if fm.get("source") and fm["source"] != "manual":
        meta["origin_source"] = [str(fm["source"])]
    if fm.get("written_by") and fm["written_by"] != VAULT_WRITER:
        meta["origin_written_by"] = [str(fm["written_by"])]
    for field in ("subject", "attribute", "valid_until", "supersedes",
                  "superseded_by", "retracted_reason"):
        if fm.get(field):
            meta[field] = [str(fm[field])]
    if fm.get("applies_to"):
        at = fm["applies_to"]
        meta["applies_to"] = [str(a) for a in (at if isinstance(at, list) else [at])]
    return meta


class Mddb:
    def __init__(self, base: str, timeout: int = 20) -> None:
        self.base = base
        self.timeout = timeout
        self.s = requests.Session()

    def _post(self, path: str, payload: dict):
        r = self.s.post(f"{self.base}{path}", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_docs(self, collection: str) -> list[dict]:
        return self._post("/search", {"collection": collection, "limit": 1000})

    def add(self, collection: str, key: str, content: str, meta: dict) -> None:
        self._post("/add", {"collection": collection, "key": key,
                            "lang": "en", "contentMd": content, "meta": meta})

    def delete(self, collection: str, key: str) -> None:
        self._post("/delete", {"collection": collection, "key": key, "lang": "en"})


def _managed_meta(meta: dict) -> dict:
    return {k: v for k, v in (meta or {}).items() if k in MANAGED_FIELDS}


def _fm_to_meta(fm: dict) -> dict:
    """Frontmatter scalars/lists -> MDDB list-meta, for comparing an exported
    note's declared fields against the remote doc's stored meta."""
    return {
        k: ([str(x) for x in v] if isinstance(v, list) else [str(v)])
        for k, v in fm.items()
        if k in MANAGED_FIELDS and v not in (None, "", [])
    }


VAULT_WRITER = "obsidian-vault"


def _writer(doc: dict) -> str:
    return (doc.get("meta") or {}).get("written_by", [""])[0]


def _source(doc: dict) -> str:
    return (doc.get("meta") or {}).get("source", [""])[0]


def write_note_file(path: Path, meta: dict, body: str) -> None:
    fm = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
          for k, v in meta.items() if k in MANAGED_FIELDS or k == "key"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(fm, sort_keys=True) + "---\n" + body + "\n")


def _voice_owned(note: dict, remote_doc: dict) -> bool:
    """True when both sides of the conflict trace to voice writes: the remote
    doc was last written by ada_remember AND the vault file is a raw voice
    export (written_by=ada_remember in frontmatter — never curated). Only
    then is take-remote safe to apply automatically."""
    fm = note.get("frontmatter") or {}
    return (_writer(remote_doc) == "ada_remember"
            and str(fm.get("written_by") or "") == "ada_remember")


def sync(mddb: Mddb, mapping: list[dict], dry: bool, delete_remote: bool,
         take_remote: bool, take_vault: bool, resolve_voice: bool = False) -> int:
    today = date.today().isoformat()
    conflicts = 0
    for m in mapping:
        vdir = VAULT / m["dir"]
        notes = {}
        paths = {}
        if vdir.is_dir():
            for f in sorted(vdir.glob("*.md")):
                if f.name.startswith(("_", ".")) or f.name == "README.md":
                    continue
                note = parse_note(f)
                if note is None:
                    print(f"  skip (no frontmatter): {m['dir']}/{f.name}")
                    continue
                key = note["frontmatter"].get("key") or f"{m['bank']}/{f.stem}"
                notes[key] = note
                paths[key] = f

        remote = {d.get("key"): d for d in mddb.list_docs(m["collection"])}
        label = f"{m['dir']:<20} -> {m['collection']}"
        print(f"\n{label}  (vault: {len(notes)}, remote: {len(remote)})")

        for key, note in notes.items():
            meta = build_meta(note["frontmatter"], m["bank"], m["scope"], today)
            body = note["body"]
            old = remote.get(key)
            if old is not None and \
               (old.get("contentMd") or "") == body and \
               _managed_meta(old.get("meta")) == meta:
                print(f"  = {key} (unchanged)")
                continue
            if old is not None and _writer(old) != VAULT_WRITER and not take_vault:
                remote_managed = _managed_meta(old.get("meta"))
                declared = _fm_to_meta(note["frontmatter"])
                if (old.get("contentMd") or "") == body and declared == remote_managed:
                    # Vault file is just the untouched exported copy of the
                    # remote doc — nothing to push, nothing to fight over.
                    print(f"  = {key} (remote copy, unedited)")
                    continue
                # Someone other than the vault last wrote this doc (voice,
                # ada_remember, manual MDDB edit). Never overwrite blindly.
                if take_remote or (resolve_voice and _voice_owned(note, old)):
                    tag = "pulling remote -> vault" if take_remote else \
                        "voice-owned conflict, remote wins"
                    print(f"  v {key} ({tag})")
                    if not dry:
                        write_note_file(paths[key], old.get("meta") or {},
                                        old.get("contentMd") or "")
                    continue
                print(f"  CONFLICT {key} (remote written by "
                      f"{_writer(old) or _source(old) or 'unknown'}, vault differs — "
                      f"resolve manually or rerun with --take-remote/--take-vault)")
                conflicts += 1
                continue
            verb = "update" if old is not None else "create"
            print(f"  {'~' if old else '+'} {key} ({verb})")
            if not dry:
                mddb.add(m["collection"], key, body, meta)

        for key, doc in remote.items():
            if key in notes:
                continue
            src = _source(doc)
            if (delete_remote or _writer(doc) == VAULT_WRITER) and src != "voice":
                print(f"  - {key} (gone from vault / remote-only, deleted)")
                if not dry:
                    mddb.delete(m["collection"], key)
            else:
                tag = "voice" if src == "voice" else "remote-only"
                print(f"  ? {key} ({tag}, kept)")
    if conflicts:
        print(f"\n{conflicts} conflict(s) — remote content preserved")
    return conflicts


def export_inbox(mddb: Mddb, mapping: list[dict], dry: bool) -> None:
    today = date.today().isoformat()
    for m in mapping:
        if not m["writable"]:
            continue  # read-only banks never receive voice writes
        # Voice writes (source=voice, active) plus auto-extracted session
        # candidates (status=draft, any source) — both need human review.
        docs = [d for d in mddb.list_docs(m["collection"])
                if ((d.get("meta") or {}).get("source", [""])[0] == "voice"
                    and (d.get("meta") or {}).get("status", [""])[0] == "active")
                or (d.get("meta") or {}).get("status", [""])[0] == "draft"]
        if not docs:
            continue
        outdir = VAULT / "inbox" / m["bank"]
        for doc in docs:
            meta = dict(doc.get("meta") or {})
            key = doc.get("key") or "unknown"
            slug = key.split("/", 1)[-1] or key
            path = outdir / f"{slug}.md"
            if path.exists():
                print(f"  = {path.relative_to(VAULT)} (already exported)")
                continue
            meta["key"] = [key]
            print(f"  + {path.relative_to(VAULT)}")
            if not dry:
                write_note_file(path, meta, doc.get("contentMd") or "")


def main() -> int:
    global VAULT
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", type=Path, default=VAULT)
    ap.add_argument("--mddb", default=MDDB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-inbox", action="store_true",
                    help="export source=voice docs into inbox/<bank>/ instead of syncing")
    ap.add_argument("--delete-remote", action="store_true",
                    help="delete remote docs absent from vault (never source=voice)")
    ap.add_argument("--take-remote", action="store_true",
                    help="on conflict: pull the remote doc into the vault file")
    ap.add_argument("--resolve-voice", action="store_true",
                    help="on conflict: auto take-remote only when both sides are "
                         "voice-written (remote written_by=ada_remember and the "
                         "vault file is an uncurated voice export). Genuine "
                         "vault-vs-voice conflicts still report and skip.")
    ap.add_argument("--take-vault", action="store_true",
                    help="on conflict: force-push the vault version over remote")
    args = ap.parse_args()
    if args.take_remote and args.take_vault:
        ap.error("--take-remote and --take-vault are mutually exclusive")

    VAULT = args.vault
    mapping = load_bank_map()
    mddb = Mddb(args.mddb)

    if args.export_inbox:
        export_inbox(mddb, mapping, args.dry_run)
        return 0

    conflicts = sync(mddb, mapping, args.dry_run, args.delete_remote,
                     args.take_remote, args.take_vault, args.resolve_voice)
    if args.dry_run:
        print("\n(dry run — no writes)")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
