import argparse
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from typing import Any
import importlib.util


def _load_backend_module(main_py_path: str):
    spec = importlib.util.spec_from_file_location("jarvis_backend_main", main_py_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed_to_load_backend_module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class _FakeWS:
    def __init__(self, session_id: str | None = None):
        self.state = SimpleNamespace()
        self.state.session_id = session_id
        self.state.trace_id = None
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self.sent.append(payload)
        else:
            self.sent.append({"_non_dict": str(payload)})


async def _replay_text_events(*, backend: Any, recording_path: str, session_id: str | None, limit: int | None) -> int:
    ws = _FakeWS(session_id=session_id)
    count = 0

    with open(recording_path, "r", encoding="utf-8") as f:
        for line in f:
            if limit is not None and count >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("direction") != "in":
                continue
            msg = rec.get("msg")
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != "text":
                continue

            trace_id = msg.get("trace_id")
            if trace_id is not None:
                try:
                    ws.state.trace_id = str(trace_id)
                except Exception:
                    pass

            text = str(msg.get("text") or "").strip()
            if not text:
                continue

            await backend._dispatch_sub_agents(ws, text)  # type: ignore[attr-defined]
            count += 1

    # Print all emitted events
    for ev in ws.sent:
        sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay recorded Jarvis WS text events through backend sub-agent dispatch.")
    ap.add_argument("recording", help="Path to JSONL recording (JARVIS_WS_RECORD_PATH output)")
    ap.add_argument("--session-id", default=None, help="Optional session_id to attach to fake ws.state")
    ap.add_argument("--limit", type=int, default=None, help="Max number of inbound text events to replay")
    ap.add_argument(
        "--backend-main",
        default=os.path.join(os.path.dirname(__file__), "main.py"),
        help="Path to jarvis-backend main.py",
    )
    args = ap.parse_args()

    backend = _load_backend_module(args.backend_main)

    asyncio.run(
        _replay_text_events(
            backend=backend,
            recording_path=args.recording,
            session_id=args.session_id,
            limit=args.limit,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
