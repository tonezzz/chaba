"""Tests for the in-band live memory guard (card kk-mac-live-memory-guard,
MEM-1043): pre-load floor, mid-stream abort below 50% / on critical
pressure, unload-only-task-loaded-model, and run_task/executor wiring."""
import json
import queue
import unittest
from unittest.mock import patch

from scripts.devnest import kk_mac_llm as llm
from scripts.devnest import kk_mac_memory as km


def _snap(free, memstatus=None, ok=True):
    return {"ok": ok, "free_pct": free, "level": None,
            "memstatus_pct": memstatus, "raw": "", "at": "t",
            "error": None}


def _probe_seq(snaps):
    """mem_probe returning snaps in order, holding the last one."""
    it = iter(list(snaps))
    last = snaps[-1] if snaps else _snap(80.0)

    def probe():
        try:
            return next(it)
        except StopIteration:
            return last
    return probe


def _ndjson(*events):
    return [json.dumps(e).encode() + b"\n" for e in events]


def _fake_stream(lines, box_error=None):
    """open_stream stand-in: queue the NDJSON lines then EOS (None)."""
    q = queue.Queue()
    for ln in lines:
        q.put(ln)
    q.put(None)
    state = {"aborted": False}
    box = {"error": box_error}

    def abort():
        state["aborted"] = True
    return q, abort, box, state


def _gen_kwargs(**over):
    kw = {"host": "local", "model": "qwen2.5:32b",
          "mem_probe": _probe_seq([_snap(80.0)]),
          "resident": lambda: set(),
          "unload": lambda m: True,
          "poll_s": 0.01,
          "max_unmeasurable": 3}
    kw.update(over)
    return kw


class GuardedGenerateTests(unittest.TestCase):
    def test_preload_floor_blocks_before_stream(self):
        opened = []

        def open_stream(*a, **k):
            opened.append(1)
            return _fake_stream([])[:3]
        out = llm.generate_guarded(
            "p", mem_probe=_probe_seq([_snap(55.0)]),
            open_stream=open_stream, **{
                k: v for k, v in _gen_kwargs().items()
                if k != "mem_probe"})
        self.assertIsNotNone(out["abort_reason"])
        self.assertIn("memory_preload_floor", out["abort_reason"])
        self.assertEqual(opened, [])
        self.assertFalse(out["loaded_by_task"] or out["unloaded"])

    def test_preload_sample_failure_fails_closed(self):
        out = llm.generate_guarded(
            "p", mem_probe=_probe_seq([_snap(None, ok=False)]),
            open_stream=lambda *a: _fake_stream([])[:3],
            **{k: v for k, v in _gen_kwargs().items()
               if k != "mem_probe"})
        self.assertIn("memory_sample_failed", out["abort_reason"])

    def test_clean_run_collects_response_and_usage(self):
        lines = _ndjson(
            {"response": "hello "},
            {"response": "world"},
            {"done": True, "eval_count": 5, "eval_duration": 7,
             "load_duration": 3, "prompt_eval_count": 9,
             "total_duration": 10})
        q, abort, box, state = _fake_stream(lines)
        out = llm.generate_guarded(
            "p", open_stream=lambda *a: (q, abort, box),
            mem_probe=_probe_seq([_snap(80.0)] * 50),
            **{k: v for k, v in _gen_kwargs().items()
               if k != "mem_probe"})
        self.assertIsNone(out["abort_reason"])
        self.assertEqual(out["response"], "hello world")
        self.assertEqual(out["usage"]["eval_count"], 5)
        self.assertEqual(out["usage"]["prompt_eval_count"], 9)
        self.assertTrue(out["loaded_by_task"])
        self.assertTrue(out["unloaded"])

    def test_threshold_crossing_aborts_mid_stream(self):
        # silent "load" window: no lines at all — only memory ticks
        probes = [_snap(80.0), _snap(80.0), _snap(45.0)]
        q = queue.Queue()  # never receives EOS — abort must fire
        state = {"aborted": False}

        def abort():
            state["aborted"] = True
        out = llm.generate_guarded(
            "p", mem_probe=_probe_seq(probes),
            open_stream=lambda *a: (q, abort, {"error": None}),
            poll_s=0.01, max_unmeasurable=3,
            host="local", model="m",
            resident=lambda: set(), unload=lambda m: True)
        self.assertIsNotNone(out["abort_reason"])
        self.assertIn("memory_pressure_abort", out["abort_reason"])
        self.assertTrue(state["aborted"])
        self.assertEqual(out["min_free_pct"], 45.0)

    def test_critical_pressure_aborts_even_above_free_floor(self):
        # free% fine but kernel memorystatus critical -> still aborts
        probes = [_snap(80.0), _snap(70.0, memstatus=30.0)]
        q = queue.Queue()
        state = {"aborted": False}

        def abort():
            state["aborted"] = True
        out = llm.generate_guarded(
            "p", mem_probe=_probe_seq(probes),
            open_stream=lambda *a: (q, abort, {"error": None}),
            poll_s=0.01, host="local", model="m",
            resident=lambda: set(), unload=lambda m: True)
        self.assertIsNotNone(out["abort_reason"])
        self.assertIn("memory_pressure_critical", out["abort_reason"])

    def test_unmeasurable_aborts_after_streak(self):
        probes = [_snap(80.0)] + [_snap(None, ok=False)] * 10
        q = queue.Queue()
        out = llm.generate_guarded(
            "p", mem_probe=_probe_seq(probes),
            open_stream=lambda *a: (queue.Queue(), lambda: None,
                                    {"error": None}),
            poll_s=0.01, max_unmeasurable=3,
            host="local", model="m",
            resident=lambda: set(), unload=lambda m: True)
        self.assertEqual(out["abort_reason"], "memory_unmeasurable")

    def test_owner_resident_model_is_never_unloaded(self):
        unloaded = []
        lines = _ndjson({"response": "ok"},
                        {"done": True, "eval_count": 1})
        q, abort, box, _ = _fake_stream(lines)
        out = llm.generate_guarded(
            "p", open_stream=lambda *a: (q, abort, box),
            mem_probe=_probe_seq([_snap(80.0)] * 50),
            host="local", model="qwen2.5:32b",
            resident=lambda: {"qwen2.5:32b"},   # owner had it resident
            unload=lambda m: unloaded.append(m) or True,
            poll_s=0.01)
        self.assertIsNone(out["abort_reason"])
        self.assertFalse(out["loaded_by_task"])
        self.assertFalse(out["unloaded"])
        self.assertEqual(unloaded, [])
        self.assertEqual(out["resident_before"], ["qwen2.5:32b"])

    def test_unknown_residency_never_unloads(self):
        unloaded = []
        lines = _ndjson({"response": "ok"}, {"done": True})
        q, abort, box, _ = _fake_stream(lines)
        out = llm.generate_guarded(
            "p", open_stream=lambda *a: (q, abort, box),
            mem_probe=_probe_seq([_snap(80.0)] * 50),
            host="local", model="m",
            resident=lambda: None,   # /api/ps probe failed -> unknown
            unload=lambda m: unloaded.append(m) or True,
            poll_s=0.01)
        self.assertFalse(out["loaded_by_task"])
        self.assertEqual(unloaded, [])

    def test_model_name_normalization(self):
        # "Qwen2.5:32B:Latest" must match resident "qwen2.5:32b"
        lines = _ndjson({"response": "ok"}, {"done": True})
        q, abort, box, _ = _fake_stream(lines)
        out = llm.generate_guarded(
            "p", open_stream=lambda *a: (q, abort, box),
            mem_probe=_probe_seq([_snap(80.0)] * 50),
            host="local", model="Qwen2.5:32B:Latest",
            resident=lambda: {"qwen2.5:32b"},
            unload=lambda m: True, poll_s=0.01)
        self.assertFalse(out["loaded_by_task"])


class RunTaskGuardedTests(unittest.TestCase):
    def setUp(self):
        self.gate = {"eligible": True, "reasons": []}

    def _run(self, **kw):
        args = _gen_kwargs(**kw)
        with patch("scripts.devnest.kk_mac_llm.snapshot",
                   return_value=self.gate):
            return llm.run_task("summary", "summarize", **args)

    def test_guarded_is_default_and_reports_evidence(self):
        lines = _ndjson({"response": "a summary"},
                        {"done": True, "eval_count": 3})
        q, abort, box, _ = _fake_stream(lines)
        r = self._run(open_stream=lambda *a: (q, abort, box),
                      mem_probe=_probe_seq([_snap(80.0)] * 50))
        self.assertTrue(r["ok"])
        self.assertEqual(r["response"], "a summary")
        self.assertIn("memory_guard", r)
        self.assertTrue(r["memory_guard"]["loaded_by_task"])
        self.assertIsNone(r["memory_guard"]["abort_reason"])

    def test_guard_abort_returns_not_ok(self):
        probes = [_snap(80.0), _snap(80.0), _snap(40.0)]
        q = queue.Queue()
        r = self._run(mem_probe=_probe_seq(probes),
                      open_stream=lambda *a: (q, lambda: None,
                                              {"error": None}))
        self.assertFalse(r["ok"])
        self.assertIn("memory_pressure_abort", r["abort_reason"])
        self.assertIn("memory_guard", r)

    def test_memory_guard_false_keeps_raw_path(self):
        class FakeRun:
            def __call__(self, command, **kwargs):
                import subprocess
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=json.dumps({"response": "raw"}).encode(),
                    stderr=b"")
        # host=kk-mac -> raw ssh path; memory_guard=False bypasses guard
        with patch("scripts.devnest.kk_mac_llm.snapshot",
                   return_value=self.gate):
            r = llm.run_task("summary", "p", host="kk-mac",
                             ssh_run=FakeRun(), memory_guard=False)
        self.assertTrue(r["ok"])
        self.assertNotIn("memory_guard", r)


class ResidentUnloadTests(unittest.TestCase):
    """kk_mac_memory resident_models/unload_model transport logic."""

    def test_resident_models_remote_parse(self):
        import subprocess
        payload = json.dumps({"models": [
            {"name": "qwen2.5:32b", "model": "qwen2.5:32b:latest"},
            {"name": "Qwen3:8B"},
        ]}).encode()

        def run(cmd, data=None, timeout=None):
            self.assertIn("/api/ps", " ".join(cmd))
            return subprocess.CompletedProcess(cmd, 0,
                                               stdout=payload, stderr=b"")
        names = km.resident_models("kk-mac", run=run)
        self.assertEqual(names, {"qwen2.5:32b", "qwen3:8b"})

    def test_resident_models_failure_is_none(self):
        def run(cmd, data=None, timeout=None):
            import subprocess
            return subprocess.CompletedProcess(cmd, 1, stdout=b"",
                                               stderr=b"no")
        self.assertIsNone(km.resident_models("kk-mac", run=run))

    def test_unload_model_posts_keep_alive_zero(self):
        import subprocess
        seen = {}

        def run(cmd, data=None, timeout=None):
            seen["cmd"] = cmd
            seen["data"] = data
            return subprocess.CompletedProcess(
                cmd, 0, stdout=b'{"done": true}', stderr=b"")
        self.assertTrue(km.unload_model("kk-mac", "qwen2.5:32b",
                                        run=run))
        body = json.loads(seen["data"])
        self.assertEqual(body["keep_alive"], 0)
        self.assertEqual(body["model"], "qwen2.5:32b")
        self.assertIn("--data-binary", " ".join(seen["cmd"]))

    def test_unload_model_local_urlopen(self):
        calls = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"done": true}'

        def urlopen(req, timeout=None):
            calls.append(req)
            return Resp()
        self.assertTrue(km.unload_model("local", "m1",
                                        urlopen=urlopen))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].full_url.endswith("/api/generate"))
        self.assertEqual(json.loads(calls[0].data)["keep_alive"], 0)


if __name__ == "__main__":
    unittest.main()
