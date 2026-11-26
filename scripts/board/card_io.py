#!/usr/bin/env python3
"""card_io — shared atomic write for kanban card YAML (and kin).

2026-11-19 incident (card kanban-card-torn-write-investigation-b4034e):
idc03's disk filled to 0 during the mddb-ops backup window (~02:55 ICT);
every board writer that did a direct ``path.write_text(yaml.safe_dump())``
tore its target mid-scalar (merge-sweep's locked_edit fallback hit three
dispatch cards — blobs cut at page boundaries). board-api's save() was
already tmp+rename and only left 0-byte ``.yml.tmp`` shells — proof the
atomic shape is the right one. This module extends that contract to
every mutator:

  atomic_write_text(p, text)
      serialize -> <name>.<pid>.tmp in the SAME dir -> flush + fsync ->
      os.replace -> fsync dir. The fsync-before-rename also covers the
      delayed-allocation failure mode: without it, a write can land in
      page cache, get renamed, and then lose its tail when writeback
      hits ENOSPC — the atomic rename alone is not durable.

  atomic_dump_card(p, card, **kw)
      yaml.safe_dump + round-trip validation (mirrors board-api.save's
      refuse-before-touch rule) -> atomic_write_text.

On any failure the tmp is removed and the target file is left UNTOUCHED
— a torn tmp never reaches the real path.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

import yaml

# libyaml C pair — same semantics as SafeDumper/SafeLoader, ~10-20x
# faster. The flock-serialized writers (board-api save, kanban-commit
# alert cards, merge-sweep locked edits) were paying multi-second
# pure-Python dumps on fat cards inside the card lock
# (board-api-lock-contention, 2026-11-20).
_YAML_DUMP = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
_YAML_LOAD = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def atomic_write_text(p: Path, text: str) -> None:
    """Replace `p` with `text` atomically (tmp + fsync + rename)."""
    p = Path(p)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(p)
        try:
            dfd = os.open(p.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def json_safe(obj):
    """Rewrite date/datetime scalars to ISO strings, in place.

    PyYAML resolves a bare ``created: 2026-11-09`` to datetime.date and
    ``...T..:..:..``/``... ..:..:..`` to datetime.datetime; any consumer
    doing a plain ``json.dumps(card)`` then dies with TypeError — the
    2026-11-09 board-api /cards 502 outage (reader side fixed by
    ``default=str`` at ca8d850275; card board-api-date-serialization-
    outage). Normalizing at write time persists the value as a string,
    which the emitter quotes because a plain scalar would re-resolve as
    a timestamp — so the file parses back as str and stays JSON-safe
    for every downstream consumer. Dict keys are left alone (card keys
    are always strings); tuples become lists since YAML has one seq
    type anyway.
    """
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = json_safe(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = json_safe(v)
    elif isinstance(obj, tuple):
        return [json_safe(v) for v in obj]
    return obj


def atomic_dump_card(p: Path, card: dict, **dump_kw) -> None:
    """safe_dump `card` to `p` atomically; refuse a dump that won't
    re-parse as a mapping BEFORE the file is touched (same contract as
    board-api.save — 2026-10-11 incident: 3 malformed cards wedged the
    render loop 2.5h)."""
    dump_kw.setdefault("allow_unicode", True)
    dump_kw.setdefault("sort_keys", False)
    dump_kw.setdefault("width", 110)
    dump_kw.setdefault("Dumper", _YAML_DUMP)
    json_safe(card)
    text = yaml.dump(card, **dump_kw)
    if not isinstance(yaml.load(text, Loader=_YAML_LOAD), dict):
        raise ValueError(
            f"refusing to write {Path(p).name}: serialized card did not "
            "re-parse as a mapping")
    atomic_write_text(p, text)
