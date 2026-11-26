"""Unit tests for cms-report-add.py — the governed kk-CMS report writer.

No network: _post, get_page and index regeneration are patched with fakes.
The contract pinned here is what keeps a "create a report" request honest:
pinned lane->collection, SSOT domain, MDDB's camelCase contentMd field,
no silent overwrite, post-write read-back, index regeneration.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/cms-report-add.py"
spec = importlib.util.spec_from_file_location("cms_report_add", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["cms_report_add"] = mod
spec.loader.exec_module(mod)

NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)


def args(**kw):
    base = dict(lane="kk", slug="water-report", title="Water report",
                domain="home", summary="Watering schedule",
                card="kk-cms-only-memory-pilot-acceptance", source="voice",
                fresh_for="7d", lang="en", written_by="test",
                public=False, overwrite=False, no_index=False,
                mddb="http://fake/v1")
    base.update(kw)
    return SimpleNamespace(**base)


def test_lane_map_and_camelcase_payload() -> None:
    assert mod.LANES["kk"] == "ada-cms-pages-kk"
    assert mod.LANES["kk-dev"] == "ada-cms-pages-kk-dev"
    body = mod.payload(args(), "line one\n", NOW)
    assert body["collection"] == "ada-cms-pages-kk"
    assert body["key"] == "water-report"
    assert body["contentMd"] == "line one\n"
    assert "content_md" not in body


def test_meta_contract() -> None:
    meta = mod.payload(args(source="voice,manual"), "body", NOW)["meta"]
    for field in ("kind", "domain", "status", "slug", "title", "format",
                  "updated", "summary", "fresh_for", "written_by"):
        assert isinstance(meta.get(field), list) and meta[field], field
    assert meta["kind"] == ["report"]
    assert meta["status"] == ["active"]
    assert meta["sources"] == ["voice", "manual"]
    assert "public" not in meta


def test_validate_refuses_bad_spec() -> None:
    assert mod.validate(args(), "body") == []
    errs = mod.validate(args(lane="live", slug="Bad Slug", domain="nope",
                             title="", summary="", public=True, source=""),
                        "")
    assert len(errs) >= 5
    assert any("lane" in e for e in errs)
    assert any("domain" in e for e in errs)
    assert any("--public requires --source" in e for e in errs)


def test_write_refuses_existing_without_overwrite() -> None:
    existing = {"key": "water-report", "contentMd": "old body", "meta": {}}
    with mock.patch.object(mod, "get_page", return_value=existing), \
            mock.patch.object(mod, "_post") as post:
        try:
            mod.write(args(), "new body")
        except SystemExit as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("expected refusal")
        post.assert_not_called()


def test_write_verifies_and_reindexes() -> None:
    posted = []
    written = {"key": "water-report", "contentMd": "new body", "meta": {}}
    with mock.patch.object(mod, "get_page", side_effect=[None, written]), \
            mock.patch.object(mod, "_post", side_effect=lambda m, p, b: posted.append((p, b)) or {}), \
            mock.patch.object(mod, "dt") as fake_dt, \
            mock.patch.object(mod.cms_index, "regen_reports_index",
                              return_value=True) as regen:
        fake_dt.datetime.now.return_value = NOW
        result = mod.write(args(), "new body")
    assert posted[0][0] == "add"
    assert posted[0][1]["contentMd"] == "new body"
    assert result == {"page": "ada-cms-pages-kk/water-report (en)",
                      "verified": True, "indexed": True,
                      "bytes": len("new body"), "previous": False}
    regen.assert_called_once_with("http://fake/v1", "test",
                                  collection="ada-cms-pages-kk",
                                  instance="kk")


def test_overwrite_records_prior_revision() -> None:
    existing = {"key": "water-report", "contentMd": "old body", "meta": {}}
    with mock.patch.object(mod, "get_page",
                           side_effect=[existing,
                                        {"key": "water-report",
                                         "contentMd": "new body", "meta": {}}]), \
            mock.patch.object(mod, "_post") as post, \
            mock.patch.object(mod, "dt") as fake_dt, \
            mock.patch.object(mod.cms_index, "regen_reports_index",
                              return_value=True):
        fake_dt.datetime.now.return_value = NOW
        mod.write(args(overwrite=True), "new body")
    meta = post.call_args[0][2]["meta"]
    assert meta["supersedes"] == ["water-report"]
    assert any("prior sha256:" in line for line in meta["timeline"])
