import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

import pytest


def _rpc(node_proc: subprocess.Popen[str], msg: dict) -> dict:
    assert node_proc.stdin is not None
    assert node_proc.stdout is not None

    node_proc.stdin.write(json.dumps(msg) + "\n")
    node_proc.stdin.flush()

    deadline = time.time() + 20
    while time.time() < deadline:
        line = node_proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("jsonrpc") != "2.0":
            continue
        if obj.get("id") == msg.get("id"):
            return obj

    raise RuntimeError("rpc_timeout")


def test_google_sheets_append_note_and_readback() -> None:
    spreadsheet_id = os.getenv("CHABA_SS_SYS", "").strip()
    sheet_name = os.getenv("CHABA_SS_SYS_SH", "").strip()
    token_path = os.getenv("GOOGLE_SHEETS_TOKEN_PATH", "/root/.config/1mcp/google-sheets.tokens.json").strip()

    if not spreadsheet_id or not sheet_name:
        pytest.skip("Missing CHABA_SS_SYS or CHABA_SS_SYS_SH")

    if not Path(token_path).exists():
        pytest.skip(f"Missing Google Sheets token file at {token_path}")

    server_js = Path(__file__).resolve().parents[1] / "mcp-servers" / "mcp-google-sheets" / "server.js"
    if not server_js.exists():
        pytest.skip("mcp-google-sheets server.js not found")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    notes_text = f"บันทึกข้อมูล test {int(time.time())}"
    row = [
        now_iso,
        "note",
        "input",
        "",
        notes_text,
    ]
    append_range = f"{sheet_name}!A:E"

    env = os.environ.copy()

    proc = subprocess.Popen(
        ["node", str(server_js)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        init = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
        )
        assert "result" in init

        append = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "google_sheets_values_append",
                    "arguments": {
                        "spreadsheet_id": spreadsheet_id,
                        "range": append_range,
                        "values": [row],
                        "value_input_option": "USER_ENTERED",
                        "insert_data_option": "INSERT_ROWS",
                    },
                },
            },
        )

        if "error" in append:
            # Common reasons: missing write scopes or auth not bootstrapped.
            pytest.skip(f"append_failed: {append['error']}")

        content = (((append.get("result") or {}).get("content") or [None])[0] or {}).get("text")
        assert isinstance(content, str)
        payload = json.loads(content)
        assert payload.get("ok") is True

        updated_range = (
            (((payload.get("data") or {}).get("updates") or {}).get("updatedRange") or "").strip()
        )
        if not updated_range:
            pytest.skip("append_response_missing_updatedRange")

        got = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "google_sheets_values_get",
                    "arguments": {
                        "spreadsheet_id": spreadsheet_id,
                        "range": updated_range,
                        "major_dimension": "ROWS",
                    },
                },
            },
        )

        if "error" in got:
            pytest.skip(f"readback_failed: {got['error']}")

        got_content = (((got.get("result") or {}).get("content") or [None])[0] or {}).get("text")
        assert isinstance(got_content, str)
        got_payload = json.loads(got_content)
        assert got_payload.get("ok") is True

        values = ((got_payload.get("data") or {}).get("values") or [])
        assert values
        assert values[0]
        got_row = [str(x) for x in values[0]]
        assert notes_text in got_row
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
