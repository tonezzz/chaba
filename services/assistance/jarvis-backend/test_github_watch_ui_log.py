import asyncio
import importlib
import sys
from types import ModuleType

import pytest


def _import_main_with_genai_stub():
    if "google" not in sys.modules:
        sys.modules["google"] = ModuleType("google")
    if "google.genai" not in sys.modules:
        sys.modules["google.genai"] = ModuleType("google.genai")
    if "google.genai.types" not in sys.modules:
        sys.modules["google.genai.types"] = ModuleType("google.genai.types")
    if "google.genai.errors" not in sys.modules:
        sys.modules["google.genai.errors"] = ModuleType("google.genai.errors")

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

    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


def test_github_watch_loop_appends_ui_log_events(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub()

    appended: list[dict] = []

    def fake_append(entries: list[dict]) -> int:
        appended.extend([dict(e) for e in (entries or [])])
        return len(entries or [])

    async def fake_broadcast(_user_id: str, _payload: dict) -> None:
        return

    seq = {"i": 0}

    async def fake_latest(*, owner: str, repo: str, branch: str | None, event: str | None) -> dict:
        seq["i"] += 1
        i = int(seq["i"])
        if i == 1:
            return {
                "ok": True,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "event": event,
                "run": {
                    "id": "1",
                    "name": "CI",
                    "status": "in_progress",
                    "conclusion": None,
                    "html_url": "https://example.invalid/run/1",
                },
            }
        if i == 2:
            return {
                "ok": True,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "event": event,
                "run": {
                    "id": "1",
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://example.invalid/run/1",
                },
            }
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "_append_ui_log_entries", fake_append)
    monkeypatch.setattr(main, "_broadcast_to_user", fake_broadcast)
    monkeypatch.setattr(main, "github_actions_latest", fake_latest)

    async def _run() -> None:
        task = asyncio.create_task(
            main._github_watch_loop(
                key="k",
                owner="o",
                repo="r",
                branch=None,
                event=None,
                poll_seconds=0.01,
                stop_on_completed=False,
                max_runtime_seconds=1.0,
            )
        )
        await asyncio.sleep(0.06)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    kinds = [e.get("kind") for e in appended if e.get("type") == "github_actions"]
    assert "run_detected" in kinds
    assert "run_completed" in kinds
    assert "watch_error" in kinds
