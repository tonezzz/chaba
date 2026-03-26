"""
Tests for payload bounding and Sheets logs retention (age + row cap).

Validates:
  A) _truncate_log_blob / _truncate_log_blob_marker
     - text truncated to <=2000 chars
     - JSON/blob truncated to <=50000 chars
     - structured _truncated marker included on truncation
     - no crash on None/empty/non-string inputs
  B) _sheets_logs_maybe_trim selection logic
     - row cap removes oldest-first, preserves header
     - age cap removes rows older than cutoff
     - both caps use the larger of the two removals
     - no trim when interval not elapsed (rate-limiting)
     - emits "sheets_logs_trimmed" log line
  C) _ws_record payload guard
     - >50 000-char payload is not written verbatim
     - record includes _truncated marker
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Module import helpers (same pattern used in other test files here)
# ---------------------------------------------------------------------------

def _stub_genai() -> None:
    for mod in ("google", "google.genai", "google.genai.types", "google.genai.errors"):
        if mod not in sys.modules:
            sys.modules[mod] = ModuleType(mod)
    try:
        setattr(sys.modules["google"], "genai", sys.modules["google.genai"])
    except Exception:
        pass
    try:
        setattr(sys.modules["google.genai"], "types", sys.modules["google.genai.types"])
    except Exception:
        pass
    try:
        setattr(sys.modules["google.genai"], "errors", sys.modules["google.genai.errors"])
    except Exception:
        pass


def _import_main() -> Any:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    _stub_genai()
    if "main" in sys.modules:
        return sys.modules["main"]
    return importlib.import_module("main")


# ---------------------------------------------------------------------------
# A) Payload bounding: _truncate_log_blob
# ---------------------------------------------------------------------------

class TestTruncateLogBlob:
    def setup_method(self) -> None:
        self.main = _import_main()

    def test_short_string_unchanged(self) -> None:
        result = self.main._truncate_log_blob("hello", limit=2000)
        assert result == "hello"

    def test_empty_string_unchanged(self) -> None:
        result = self.main._truncate_log_blob("", limit=2000)
        assert result == ""

    def test_none_treated_as_empty(self) -> None:
        result = self.main._truncate_log_blob(None, limit=2000)
        assert isinstance(result, str)

    def test_exactly_at_limit_unchanged(self) -> None:
        s = "x" * 2000
        assert self.main._truncate_log_blob(s, limit=2000) == s

    def test_over_limit_truncated(self) -> None:
        s = "a" * 3000
        result = self.main._truncate_log_blob(s, limit=2000)
        assert len(result) == 2000
        assert result == "a" * 2000

    def test_zero_limit_returns_full(self) -> None:
        # limit=0 means no limit (passthrough)
        s = "z" * 5000
        result = self.main._truncate_log_blob(s, limit=0)
        assert result == s

    def test_non_string_input_coerced(self) -> None:
        result = self.main._truncate_log_blob(12345, limit=2000)
        assert isinstance(result, str)

    def test_large_blob_truncated_to_50000(self) -> None:
        big = "B" * 100_000
        result = self.main._truncate_log_blob(big, limit=50_000)
        assert len(result) == 50_000


# ---------------------------------------------------------------------------
# A) Payload bounding: _truncate_log_blob_marker
# ---------------------------------------------------------------------------

class TestTruncateLogBlobMarker:
    def setup_method(self) -> None:
        self.main = _import_main()

    def test_short_text_no_truncation(self) -> None:
        text = "hello world"
        out, truncated = self.main._truncate_log_blob_marker(text, limit=2000)
        assert truncated is False
        assert out == text

    def test_text_over_2000_yields_marker(self) -> None:
        big_text = "T" * 3000
        out, truncated = self.main._truncate_log_blob_marker(big_text, limit=2000)
        assert truncated is True
        assert len(out) <= 2000
        parsed = json.loads(out)
        assert parsed.get("_truncated") is True
        assert parsed.get("len") == 3000
        assert "preview" in parsed

    def test_blob_over_50000_yields_marker(self) -> None:
        big_blob = "X" * 60_000
        out, truncated = self.main._truncate_log_blob_marker(big_blob, limit=50_000)
        assert truncated is True
        assert len(out) <= 50_000
        parsed = json.loads(out)
        assert parsed.get("_truncated") is True
        assert parsed.get("len") == 60_000

    def test_1mb_payload_does_not_crash(self) -> None:
        """Robustness: 1 MB payload must not raise; output must be bounded."""
        huge = "M" * 1_000_000
        out, truncated = self.main._truncate_log_blob_marker(huge, limit=50_000)
        assert isinstance(out, str)
        assert len(out) <= 50_000
        assert truncated is True

    def test_marker_contains_original_length(self) -> None:
        original_len = 5000
        s = "L" * original_len
        out, _ = self.main._truncate_log_blob_marker(s, limit=2000)
        parsed = json.loads(out)
        assert parsed["len"] == original_len

    def test_marker_preview_is_prefix_of_original(self) -> None:
        s = "ABCD" * 1000  # 4000 chars
        out, _ = self.main._truncate_log_blob_marker(s, limit=2000)
        parsed = json.loads(out)
        preview = parsed.get("preview", "")
        assert s.startswith(preview) or len(preview) == 0  # preview is a prefix or empty

    def test_none_input_no_truncation(self) -> None:
        out, truncated = self.main._truncate_log_blob_marker(None, limit=2000)
        assert truncated is False
        assert out == ""

    def test_empty_input_no_truncation(self) -> None:
        out, truncated = self.main._truncate_log_blob_marker("", limit=2000)
        assert truncated is False
        assert out == ""


# ---------------------------------------------------------------------------
# B) Sheets logs retention: trim selection logic
# ---------------------------------------------------------------------------

class TestSheetsLogsTrimLogic:
    """
    Tests for _sheets_logs_maybe_trim using mocked MCP tool calls.
    The function fetches rows, decides how many to remove, rewrites the sheet.
    """

    def setup_method(self) -> None:
        self.main = _import_main()

    def _make_rows(self, n: int, *, age_ms: int | None = None) -> list[list[Any]]:
        """Build n data rows. ts_ms = age_ms for all rows if given."""
        ts_ms = age_ms if age_ms is not None else int(time.time() * 1000)
        return [[f"type{i}", f"text{i}", "2024-01-01T00:00:00Z", ts_ms, "in", f"sid{i}", "", "{}"] for i in range(n)]

    def _make_response(self, header: list, rows: list) -> dict:
        return {"values": [header] + rows}

    async def _run_trim(
        self,
        *,
        rows: list[list[Any]],
        max_rows: int = 0,
        max_age_days: int = 0,
        last_trim: float | None = None,
        interval_s: int = 600,
    ) -> dict:
        """Run _sheets_logs_maybe_trim and return last trim result."""
        main = self.main
        header = ["type", "text", "ts", "ts_ms", "direction", "session_id", "trace_id", "msg_json"]

        call_log: list[tuple[str, dict]] = []

        async def fake_mcp_tools_call(tool: str, params: dict) -> Any:
            call_log.append((tool, params))
            if "values_get" in tool or tool.endswith("_get"):
                return {"content": [{"type": "text", "text": json.dumps(self._make_response(header, rows))}]}
            return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}

        main._SHEETS_LOGS_LAST_TRIM = last_trim
        main._SHEETS_LOGS_LAST_TRIM_RESULT = {}

        old_call = main._mcp_tools_call
        main._mcp_tools_call = fake_mcp_tools_call

        cfg = {
            "enabled": True,
            "max_rows": max_rows,
            "max_age_days": max_age_days,
            "trim_interval_seconds": interval_s,
        }

        try:
            await main._sheets_logs_maybe_trim(
                spreadsheet_id="test-ss-id",
                sheet_name="logs",
                cfg=cfg,
            )
        finally:
            main._mcp_tools_call = old_call

        return dict(main._SHEETS_LOGS_LAST_TRIM_RESULT), call_log

    def test_row_cap_removes_oldest_rows(self) -> None:
        rows = self._make_rows(100)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_rows=50))
        assert result.get("ok") is True
        assert result.get("removed") == 50
        assert result.get("reason") in ("rows", "both")

    def test_row_cap_noop_when_under_limit(self) -> None:
        rows = self._make_rows(20)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_rows=50))
        assert result.get("removed", 0) == 0

    def test_age_cap_removes_old_rows(self) -> None:
        # All rows are 10 days old (older than 7-day cutoff)
        old_ms = int((time.time() - 10 * 86400) * 1000)
        rows = self._make_rows(30, age_ms=old_ms)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_age_days=7))
        assert result.get("ok") is True
        assert result.get("removed", 0) > 0
        assert result.get("reason") in ("age", "both")

    def test_age_cap_keeps_fresh_rows(self) -> None:
        # All rows are 1 hour old (well within 7-day cutoff)
        fresh_ms = int((time.time() - 3600) * 1000)
        rows = self._make_rows(20, age_ms=fresh_ms)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_age_days=7))
        assert result.get("removed", 0) == 0

    def test_both_caps_use_max_of_two(self) -> None:
        # 60 rows, all old -> age would remove all 60, rows cap would remove 10
        old_ms = int((time.time() - 10 * 86400) * 1000)
        rows = self._make_rows(60, age_ms=old_ms)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_rows=50, max_age_days=7))
        assert result.get("ok") is True
        # max(60, 10) = 60 removed
        assert result.get("removed") == 60
        assert result.get("reason") in ("both", "age")

    def test_rate_limiting_skips_trim_if_too_soon(self) -> None:
        rows = self._make_rows(200)
        last_trim = time.time() - 10  # only 10s ago, interval=600
        result, calls = asyncio.run(self._run_trim(rows=rows, max_rows=50, last_trim=last_trim, interval_s=600))
        # Trim should be skipped; no sheet update calls
        update_calls = [c for c, _ in calls if "update" in c or "append" in c]
        assert len(update_calls) == 0

    def test_disabled_when_both_caps_zero(self) -> None:
        rows = self._make_rows(200)
        result, calls = asyncio.run(self._run_trim(rows=rows, max_rows=0, max_age_days=0))
        assert result.get("mode") == "disabled"
        assert result.get("removed", 0) == 0

    def test_empty_sheet_noop(self) -> None:
        result, calls = asyncio.run(self._run_trim(rows=[], max_rows=50))
        assert result.get("removed", 0) == 0

    def test_header_preserved_after_trim(self) -> None:
        """The rewrite must include the header row as first row."""
        rows = self._make_rows(100)
        written_values: list[list[list[Any]]] = []

        async def _run() -> None:
            main = self.main
            header = ["type", "text", "ts", "ts_ms", "direction", "session_id", "trace_id", "msg_json"]

            async def fake_mcp_tools_call(tool: str, params: dict) -> Any:
                if "values_get" in tool or tool.endswith("_get"):
                    return {"content": [{"type": "text", "text": json.dumps(self._make_response(header, rows))}]}
                if "values_update" in tool or tool.endswith("_update"):
                    vals = params.get("values", [])
                    written_values.append(vals)
                return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}

            main._SHEETS_LOGS_LAST_TRIM = None
            old_call = main._mcp_tools_call
            main._mcp_tools_call = fake_mcp_tools_call
            try:
                cfg = {"enabled": True, "max_rows": 50, "max_age_days": 0, "trim_interval_seconds": 600}
                await main._sheets_logs_maybe_trim(
                    spreadsheet_id="test-ss-id",
                    sheet_name="logs",
                    cfg=cfg,
                )
            finally:
                main._mcp_tools_call = old_call

        asyncio.run(_run())
        assert len(written_values) > 0
        first_written = written_values[0]
        assert len(first_written) > 0
        # First row of written data must be the header
        assert first_written[0] == ["type", "text", "ts", "ts_ms", "direction", "session_id", "trace_id", "msg_json"]

    def test_trim_logs_sheets_logs_trimmed(self, caplog: pytest.LogCaptureFixture) -> None:
        """Trim must emit a log line containing 'sheets_logs_trimmed'."""
        import logging
        rows = self._make_rows(100)

        async def _run() -> None:
            main = self.main
            header = ["type", "text", "ts", "ts_ms", "direction", "session_id", "trace_id", "msg_json"]

            async def fake_mcp_tools_call(tool: str, params: dict) -> Any:
                if "values_get" in tool or tool.endswith("_get"):
                    return {"content": [{"type": "text", "text": json.dumps(self._make_response(header, rows))}]}
                return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}

            main._SHEETS_LOGS_LAST_TRIM = None
            old_call = main._mcp_tools_call
            main._mcp_tools_call = fake_mcp_tools_call
            try:
                cfg = {"enabled": True, "max_rows": 50, "max_age_days": 0, "trim_interval_seconds": 600}
                with caplog.at_level(logging.INFO, logger="jarvis-backend"):
                    await main._sheets_logs_maybe_trim(
                        spreadsheet_id="test-ss-id",
                        sheet_name="logs",
                        cfg=cfg,
                    )
            finally:
                main._mcp_tools_call = old_call

        asyncio.run(_run())
        assert any("sheets_logs_trimmed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# C) _ws_record payload guard: large payload must not be written verbatim
# ---------------------------------------------------------------------------

class TestWsRecordPayloadGuard:
    def setup_method(self) -> None:
        self.main = _import_main()

    def test_large_ws_message_truncated_in_record(self, tmp_path: Any) -> None:
        """A message with a 1 MB JSON payload must produce a _truncated record on disk."""
        main = self.main
        import tempfile

        big_text = "Z" * 1_000_000
        msg = {"type": "text", "text": big_text}

        written_lines: list[str] = []

        # Patch _ws_record_daily_path and _sheets_logs_enqueue_ws
        record_path = str(tmp_path / "ws_record.jsonl")
        main._WS_RECORD_ENABLED = True
        main._WS_RECORD_LOCK = None

        old_path_fn = main._ws_record_daily_path
        old_enqueue = main._sheets_logs_enqueue_ws

        main._ws_record_daily_path = lambda: record_path

        async def fake_enqueue(ws: Any, direction: str, m: Any) -> None:
            return

        main._sheets_logs_enqueue_ws = fake_enqueue

        class FakeWS:
            class state:
                session_id = "test-session"
                trace_id = "test-trace"

        async def _run() -> None:
            await main._ws_record(FakeWS(), "in", msg)

        try:
            asyncio.run(_run())
        finally:
            main._ws_record_daily_path = old_path_fn
            main._sheets_logs_enqueue_ws = old_enqueue

        import os
        assert os.path.exists(record_path), "Record file should have been written"
        with open(record_path, encoding="utf-8") as f:
            content = f.read()

        # The raw big_text must NOT appear verbatim in the record
        assert big_text not in content, "1 MB payload must not be written verbatim"

        # The record must include the _truncated marker
        line = content.strip().splitlines()[0]
        rec = json.loads(line)
        msg_field = rec.get("msg")
        assert isinstance(msg_field, dict), f"msg should be truncated dict, got {type(msg_field)}"
        assert msg_field.get("_truncated") is True, "Record must include _truncated=True"
        assert "len" in msg_field, "Truncated record must include original len"
        # The recorded len must match the original JSON size (msg serialised to JSON before guard)
        original_msg_json = json.dumps(msg, ensure_ascii=False)
        assert msg_field["len"] == len(original_msg_json), (
            f"len in marker ({msg_field['len']}) must match original JSON length ({len(original_msg_json)})"
        )

    def test_small_ws_message_not_truncated(self, tmp_path: Any) -> None:
        """A small message must be written verbatim without _truncated marker."""
        main = self.main
        msg = {"type": "text", "text": "hello world"}

        record_path = str(tmp_path / "ws_record_small.jsonl")
        main._WS_RECORD_ENABLED = True
        main._WS_RECORD_LOCK = None

        old_path_fn = main._ws_record_daily_path
        old_enqueue = main._sheets_logs_enqueue_ws

        main._ws_record_daily_path = lambda: record_path

        async def fake_enqueue(ws: Any, direction: str, m: Any) -> None:
            return

        main._sheets_logs_enqueue_ws = fake_enqueue

        class FakeWS:
            class state:
                session_id = "test-session"
                trace_id = "test-trace"

        async def _run() -> None:
            await main._ws_record(FakeWS(), "out", msg)

        try:
            asyncio.run(_run())
        finally:
            main._ws_record_daily_path = old_path_fn
            main._sheets_logs_enqueue_ws = old_enqueue

        with open(record_path, encoding="utf-8") as f:
            line = f.read().strip()
        rec = json.loads(line)
        assert isinstance(rec.get("msg"), dict)
        # No _truncated key for small messages
        assert "_truncated" not in rec.get("msg", {})


# ---------------------------------------------------------------------------
# D) Config: JARVIS_SHEETS_LOGS_* env vars are recognised
# ---------------------------------------------------------------------------

class TestSheetsLogsCfg:
    def setup_method(self) -> None:
        self.main = _import_main()

    def test_default_max_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JARVIS_SHEETS_LOGS_MAX_ROWS", raising=False)
        cfg = self.main._sheets_logs_cfg()
        assert cfg["max_rows"] == 5000

    def test_default_max_age_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JARVIS_SHEETS_LOGS_MAX_AGE_DAYS", raising=False)
        cfg = self.main._sheets_logs_cfg()
        assert cfg["max_age_days"] == 7

    def test_default_trim_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JARVIS_SHEETS_LOGS_TRIM_INTERVAL_SECONDS", raising=False)
        cfg = self.main._sheets_logs_cfg()
        assert cfg["trim_interval_seconds"] == 600

    def test_custom_max_rows_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_SHEETS_LOGS_MAX_ROWS", "1234")
        cfg = self.main._sheets_logs_cfg()
        assert cfg["max_rows"] == 1234

    def test_custom_max_age_days_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_SHEETS_LOGS_MAX_AGE_DAYS", "14")
        cfg = self.main._sheets_logs_cfg()
        assert cfg["max_age_days"] == 14

    def test_custom_trim_interval_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_SHEETS_LOGS_TRIM_INTERVAL_SECONDS", "120")
        cfg = self.main._sheets_logs_cfg()
        assert cfg["trim_interval_seconds"] == 120
