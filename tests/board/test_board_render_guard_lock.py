"""board-render-guard must skip an overlapping tick instead of queueing.

The 60s render timer can outlive a tick when parsing the board takes
minutes. Blocking on /tmp/board-render.lock made systemd stack up stale
renders that kept landing after fresher ones (2026-11-23 incident).
"""
from __future__ import annotations

import fcntl
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_render_guard",
        REPO / "scripts" / "board" / "board-render-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RenderLockTest(unittest.TestCase):
    def _setup(self, td):
        mod = _load()
        p = Path(td)
        mod.RENDER_LOCK = p / "board-render.lock"
        mod.RENDERS = [Path("render-board.py"), Path("render-board2.py")]
        mod.STATE = p / "state.json"
        mod.LOCK = p / "board-api.lock"
        mod.CARD_DIR = p / "cards"
        return mod

    def test_lock_held_skips_tick_without_running_renderers(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self._setup(td)
            holder = mod.RENDER_LOCK.open("w")
            fcntl.flock(holder, fcntl.LOCK_EX)
            try:
                with mock.patch.object(mod.subprocess, "run") as run, \
                        mock.patch.object(mod, "upsert_card"):
                    self.assertEqual(mod.main(), 0)
                    run.assert_not_called()
            finally:
                fcntl.flock(holder, fcntl.LOCK_UN)
                holder.close()

    def test_lock_free_runs_both_renderers(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self._setup(td)
            with mock.patch.object(mod.subprocess, "run") as run, \
                    mock.patch.object(mod, "upsert_card"):
                run.return_value = mock.Mock(returncode=0)
                self.assertEqual(mod.main(), 0)
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
