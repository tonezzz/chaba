import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                     / "scripts" / "devnest"))
import kk_mac_remote_guard as g  # noqa: E402


class _CP:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


MEMPRESSURE = """The system has 68719476736 bytes of memory.
System-wide memory free percentage: 72%
"""
VMSTAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                              1000000.
Pages active:                            2000000.
Pages inactive:                          1000000.
Pages speculative:                        500000.
Pages purgeable:                          200000.
"""


class FreePctTests(unittest.TestCase):
    def test_memory_pressure_primary(self):
        pct, src = g.free_pct(runner=lambda *a, **k: _CP(MEMPRESSURE))
        self.assertEqual(pct, 72.0)
        self.assertEqual(src, "memory_pressure")

    def test_vm_stat_fallback(self):
        def runner(args, **k):
            if args[0] == "vm_stat":
                return _CP(VMSTAT)
            if args[0] == "getconf":
                return _CP("16384\n")
            if args[0] == "sysctl":
                return _CP(str(68719476736) + "\n")  # 64 GiB
            return _CP("")
        pct, src = g.free_pct(runner=runner)
        avail = 1000000 + 1000000 + 500000 + 200000
        expected = round(100.0 * avail * 16384 / 68719476736, 1)
        self.assertEqual(src, "vm_stat")
        self.assertAlmostEqual(pct, expected, places=1)

    def test_unmeasurable_returns_none(self):
        pct, src = g.free_pct(runner=lambda *a, **k: _CP("garbage"))
        self.assertIsNone(pct)
        self.assertEqual(src, "unmeasurable")


class _FakeResp:
    """Iterable fake for urllib response; close() ends iteration."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def close(self):
        self.closed = True

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        if self._lines:
            return self._lines.pop(0)
        time.sleep(0.02)
        if self.closed:
            raise StopIteration
        raise StopIteration


class GenerateGuardedTests(unittest.TestCase):
    def _payload(self):
        return {"model": "qwen3:8b", "prompt": "hi"}

    def test_completes_and_tracks_min(self):
        lines = [
            b'{"response": "he", "done": false}\n',
            b'{"response": "llo", "done": false}\n',
            b'{"response": "", "done": true, "eval_count": 5,'
            b' "eval_duration": 10}\n',
        ]
        pcts = iter([80.0, 70.0, 65.0, 62.0])
        with patch("urllib.request.urlopen",
                   return_value=_FakeResp(lines)):
            result, aborted, min_pct = g.generate_guarded(
                self._payload(), abort_floor_pct=50.0, poll_s=0.0,
                free_probe=lambda: next(pcts, 62.0))
        self.assertIsNone(aborted)
        self.assertEqual(result["response"], "hello")
        self.assertEqual(result["eval_count"], 5)
        self.assertEqual(min_pct, 62.0)

    def test_aborts_below_floor_and_closes(self):
        lines = [b'{"response": "partial", "done": false}\n']
        resp = _FakeResp(lines)
        pcts = iter([70.0, 55.0, 48.0, 48.0])
        with patch("urllib.request.urlopen", return_value=resp):
            result, aborted, min_pct = g.generate_guarded(
                self._payload(), abort_floor_pct=50.0, poll_s=0.0,
                free_probe=lambda: next(pcts, 48.0))
        self.assertEqual(aborted, "memory_floor")
        self.assertEqual(min_pct, 48.0)
        self.assertTrue(resp.closed)
        self.assertEqual(result["response"], "partial")

    def test_unmeasurable_aborts(self):
        pcts = iter([70.0, None])
        with patch("urllib.request.urlopen",
                   return_value=_FakeResp([])):
            result, aborted, _ = g.generate_guarded(
                self._payload(), abort_floor_pct=50.0, poll_s=0.0,
                free_probe=lambda: next(pcts, None))
        self.assertEqual(aborted, "memory_unmeasurable")


class RunTests(unittest.TestCase):
    def _payload(self, **kw):
        p = {"model": "qwen3:8b", "prompt": "hi",
             "entry_floor_pct": 60.0, "abort_floor_pct": 50.0,
             "unload_after": True}
        p.update(kw)
        return p

    def test_preflight_abort_below_entry(self):
        with patch.object(g, "free_pct",
                          return_value=(55.0, "memory_pressure")):
            out, code = g.run(self._payload())
        self.assertEqual(code, 2)
        self.assertEqual(out["verdict"], "preflight_abort")
        self.assertIn("55.0", out["reason"])
        self.assertEqual(out["memory"]["pre_pct"], 55.0)

    def test_unmeasurable_fails_closed(self):
        with patch.object(g, "free_pct",
                          return_value=(None, "unmeasurable")):
            out, code = g.run(self._payload())
        self.assertEqual(code, 2)
        self.assertEqual(out["verdict"], "memory_unmeasurable")

    def test_success_unloads_task_loaded_model(self):
        calls = []
        gen = {"response": "ok", "eval_count": 3, "eval_duration": 9,
               "load_duration": 4, "total_duration": 20,
               "done": True, "done_reason": "stop"}
        with patch.object(g, "free_pct",
                          return_value=(70.0, "memory_pressure")), \
             patch.object(g, "resident_models", return_value=set()), \
             patch.object(g, "generate_guarded",
                          return_value=(gen, None, 55.0)), \
             patch.object(g, "unload_model",
                          side_effect=lambda m: calls.append(m) or True):
            out, code = g.run(self._payload())
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["verdict"], "ok")
        self.assertEqual(out["response"], "ok")
        self.assertEqual(calls, ["qwen3:8b"])
        self.assertTrue(out["memory"]["unloaded"])
        self.assertTrue(out["memory"]["loaded_by_task"])

    def test_never_unloads_owner_resident_model(self):
        calls = []
        gen = {"response": "ok", "eval_count": 3}
        with patch.object(g, "free_pct",
                          return_value=(70.0, "memory_pressure")), \
             patch.object(g, "resident_models",
                          return_value={"qwen3:8b"}), \
             patch.object(g, "generate_guarded",
                          return_value=(gen, None, 60.0)), \
             patch.object(g, "unload_model",
                          side_effect=lambda m: calls.append(m)):
            out, code = g.run(self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertFalse(out["memory"]["unloaded"])
        self.assertFalse(out["memory"]["loaded_by_task"])

    def test_abort_still_unloads_partial_load(self):
        calls = []
        gen = {"response": "par", "eval_count": None}
        with patch.object(g, "free_pct",
                          return_value=(70.0, "memory_pressure")), \
             patch.object(g, "resident_models", return_value=set()), \
             patch.object(g, "generate_guarded",
                          return_value=(gen, "memory_floor", 48.0)), \
             patch.object(g, "unload_model",
                          side_effect=lambda m: calls.append(m) or True):
            out, code = g.run(self._payload())
        self.assertEqual(code, 2)
        self.assertEqual(out["verdict"], "memory_abort")
        self.assertFalse(out["ok"])
        # the model may be partially resident — must still be unloaded
        self.assertEqual(calls, ["qwen3:8b"])
        self.assertEqual(out["memory"]["min_during_pct"], 48.0)

    def test_empty_response_is_ollama_error(self):
        gen = {"response": "  ", "eval_count": 0}
        with patch.object(g, "free_pct",
                          return_value=(70.0, "memory_pressure")), \
             patch.object(g, "resident_models", return_value=set()), \
             patch.object(g, "generate_guarded",
                          return_value=(gen, None, 60.0)), \
             patch.object(g, "unload_model", return_value=True):
            out, code = g.run(self._payload())
        self.assertEqual(code, 2)
        self.assertEqual(out["verdict"], "ollama_error")


if __name__ == "__main__":
    unittest.main()
