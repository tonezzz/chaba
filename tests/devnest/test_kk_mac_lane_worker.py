import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.devnest.kk_mac_lane_worker as lw


def _inv(entries):
    """pack_name -> {relpath: mtime} inventory, nest-worker shape."""
    return entries


GOOD_TASK = {"task_id": "t-one", "task_class": "summary",
             "prompt": "summarize the evidence",
             "expect": {"facts": ["evidence"]}, "model": "qwen3:8b"}


class GateTests(unittest.TestCase):
    def test_env_kill_switch_denies(self):
        g = lw.gate(host="local", drain_file="/nonexistent-drain",
                    environ={"DEVNEST_KK_MAC_ENABLED": "false"})
        self.assertFalse(g["eligible"])
        self.assertIn("kk_disabled", g["reasons"])

    def test_drain_file_denies(self):
        with tempfile.NamedTemporaryFile() as f:
            g = lw.gate(host="local", drain_file=f.name, environ={})
        self.assertFalse(g["eligible"])
        self.assertIn("drain_file", g["reasons"])

    def test_local_host_uses_local_snapshot(self):
        with patch.object(lw.kk_mac_admission, "local_snapshot",
                          return_value={"eligible": True}) as ls, \
             patch.object(lw.kk_mac_admission, "snapshot") as snap:
            g = lw.gate(host="local", drain_file="", environ={})
        self.assertTrue(g["eligible"])
        ls.assert_called_once()
        snap.assert_not_called()

    def test_remote_host_uses_heartbeat_snapshot(self):
        with patch.object(lw.kk_mac_admission, "snapshot",
                          return_value={"eligible": True}) as snap, \
             patch.object(lw.kk_mac_admission, "local_snapshot") as ls:
            g = lw.gate(host="kk-mac", drain_file="", environ={})
        self.assertTrue(g["eligible"])
        snap.assert_called_once()
        ls.assert_not_called()

    def test_probe_exception_fails_closed(self):
        with patch.object(lw.kk_mac_admission, "local_snapshot",
                          side_effect=RuntimeError("boom")):
            g = lw.gate(host="local", drain_file="", environ={})
        self.assertFalse(g["eligible"])
        self.assertTrue(g["reasons"][0].startswith("gate_failed:"))


class PlanTests(unittest.TestCase):
    NOW = 1_000_000.0

    def test_terminal_and_signature_filters(self):
        inv = _inv({
            "pack-done": {"pack.yml": 1.0, "inputs/task.json": 2.0,
                          "done": 3.0},
            "pack-failed": {"pack.yml": 1.0, "failed": 2.0},
            "pack-video": {"pack.yml": 1.0, "inputs/req.json": 2.0},
            "pack-half": {"inputs/task.json": 2.0},
            "pack-ok": {"pack.yml": 1.0, "inputs/task.json": 2.0},
        })
        p = lw.plan("r", now=self.NOW, stale_claim_min=60,
                    fallback_retry_min=30, inventory=inv)
        self.assertEqual(p["candidates"], ["pack-ok"])
        self.assertIn("pack-video:not_llm_pack", p["skipped"])
        self.assertIn("pack-half:no_pack_yml", p["skipped"])

    def test_live_claim_blocks_and_stale_claim_releases(self):
        inv = _inv({
            "pack-live": {"pack.yml": 1.0, "inputs/task.json": 2.0,
                          "claim/w1": self.NOW - 60},
            "pack-stale": {"pack.yml": 1.0, "inputs/task.json": 2.0,
                           "claim/w-dead": self.NOW - 4000},
        })
        p = lw.plan("r", now=self.NOW, stale_claim_min=60,
                    fallback_retry_min=30, inventory=inv)
        self.assertEqual(p["candidates"], ["pack-stale"])
        self.assertEqual(p["stale_claims"][0][0], "pack-stale")

    def test_fresh_fallback_holds_stale_retries(self):
        inv = _inv({
            "pack-held": {"pack.yml": 1.0, "inputs/task.json": 2.0,
                          "fallback": self.NOW - 60},
            "pack-retry": {"pack.yml": 1.0, "inputs/task.json": 2.0,
                           "fallback": self.NOW - 4000},
        })
        p = lw.plan("r", now=self.NOW, stale_claim_min=60,
                    fallback_retry_min=30, inventory=inv)
        self.assertEqual(p["candidates"], ["pack-retry"])
        self.assertEqual(p["stale_fallbacks"], ["pack-retry"])
        self.assertTrue(any(s.startswith("pack-held:fallback_held")
                            for s in p["skipped"]))


class LoadTaskTests(unittest.TestCase):
    def test_rejects(self):
        self.assertIsNone(lw._load_task("{bad", "p"))
        self.assertIsNone(lw._load_task("[1]", "p"))
        self.assertIsNone(lw._load_task(json.dumps(
            {**GOOD_TASK, "task_class": "video_render"}), "p"))
        self.assertIsNone(lw._load_task(json.dumps(
            {**GOOD_TASK, "prompt": " "}), "p"))
        self.assertIsNone(lw._load_task(json.dumps(
            {**GOOD_TASK, "prompt": "x" * 6001}), "p"))

    def test_accepts_bounded(self):
        for tc in ("summary", "operator_brief", "structured_extract",
                   "safe_route"):
            t = lw._load_task(json.dumps({**GOOD_TASK,
                                          "task_class": tc}), "p")
            self.assertEqual(t["task_class"], tc)


class _FakeCompleted:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


class PassOnceTests(unittest.TestCase):
    def _remote(self, task=None):
        """In-memory remote pack store for a pass (remote root 'r')."""
        task = task or GOOD_TASK
        return {"r/packs/pack-a/pack.yml": "name: pack-a\n",
                "r/packs/pack-a/inputs/task.json": json.dumps(task)}

    def _nw(self, remote):
        """Patch every nest-worker remote op against the dict store."""
        state = dict(remote)

        def rc(*args, check=True, timeout=900):
            cmd = args[0]
            if cmd == "deletefile":
                state.pop(args[1], None)
            elif cmd == "copy":
                src, dst = args[1], args[2]
                excl = [args[i + 1] for i, a in enumerate(args)
                        if a == "--exclude" and i + 1 < len(args)]
                if os.path.isdir(dst) or dst.startswith("/"):
                    # remote -> local: materialize under dst
                    prefix = src.rstrip("/") + "/"
                    for k, v in state.items():
                        if k.startswith(prefix):
                            rel = k[len(prefix):]
                            if any(rel.startswith(e.rstrip("*"))
                                   for e in excl):
                                continue
                            fp = Path(dst) / rel
                            fp.parent.mkdir(parents=True,
                                            exist_ok=True)
                            fp.write_text(str(v))
                else:
                    # local -> remote: upload every file under src
                    for fp in Path(src).rglob("*"):
                        if fp.is_file():
                            rel = fp.relative_to(src)
                            state[f"{dst.rstrip('/')}/{rel}"] = \
                                fp.read_text(errors="replace")
            return _FakeCompleted()

        def rcat(path, text):
            state[path] = text

        def cat(path):
            return state.get(path, "")

        def lsf(path):
            prefix = path.rstrip("/") + "/"
            return sorted(
                k[len(prefix):] for k in state if k.startswith(prefix)
                and "/" not in k[len(prefix):])

        return state, {"rc": rc, "rcat": rcat, "cat": cat, "lsf": lsf}

    def _run(self, remote, *, verdict="pass", gate=True, task=None):
        state, ops = self._nw(remote)
        inv = {"pack-a": {"pack.yml": 1.0, "inputs/task.json": 2.0}}
        with patch.object(lw.NW, "rc", side_effect=ops["rc"]), \
             patch.object(lw.NW, "rcat", side_effect=ops["rcat"]), \
             patch.object(lw.NW, "cat", side_effect=ops["cat"]), \
             patch.object(lw.NW, "lsf", side_effect=ops["lsf"]), \
             patch.object(lw.NW, "pack_inventory", return_value=inv), \
             patch.object(lw.NW, "verify_artifacts",
                          return_value=(True, "")), \
             patch.object(lw.time, "sleep"), \
             patch.object(lw, "gate",
                          return_value={"eligible": gate, "reasons": []}):
            rep = lw.pass_once(
                "r", host="local", worker="w1",
                workdir=tempfile.mkdtemp(), max_packs=1,
                stale_claim_min=60, fallback_retry_min=30,
                drain_file="",
                run_contract=lambda env, taskdir=None:
                    {"verdict": verdict, "reasons": [],
                     "checks": {}, "wall_seconds": 0.5})
        return rep, state

    def test_gate_deny_claims_nothing(self):
        rep, state = self._run(self._remote(), gate=False)
        self.assertEqual(rep["claimed"], [])
        self.assertNotIn("r/packs/pack-a/done", state)

    def test_pass_writes_done_and_releases_claim(self):
        rep, state = self._run(self._remote(), verdict="pass")
        self.assertEqual(rep["claimed"], ["pack-a"])
        self.assertIn("r/packs/pack-a/done", state)
        self.assertNotIn("r/packs/pack-a/claim/w1", state)

    def test_fallback_writes_hold_marker(self):
        rep, state = self._run(self._remote(), verdict="fallback")
        self.assertIn("r/packs/pack-a/fallback", state)
        self.assertNotIn("r/packs/pack-a/done", state)
        self.assertNotIn("r/packs/pack-a/claim/w1", state)

    def test_fail_writes_terminal_marker(self):
        rep, state = self._run(self._remote(), verdict="failed")
        self.assertIn("r/packs/pack-a/failed", state)

    def test_unadmitted_pack_never_claimed(self):
        bad = {**GOOD_TASK, "task_class": "video_render"}
        rep, state = self._run(self._remote(task=bad))
        self.assertEqual(rep["claimed"], [])
        self.assertFalse(any(k.startswith("r/packs/pack-a/claim")
                             for k in state))
        self.assertNotIn("r/packs/pack-a/done", state)


class LocalHostModeTests(unittest.TestCase):
    def test_llm_local_call_skips_ssh(self):
        from scripts.devnest import kk_mac_llm
        sent = {}

        class _Resp:
            def read(self):
                return json.dumps({"response": "ok",
                                   "eval_count": 3}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            sent["url"] = req.full_url
            sent["body"] = json.loads(req.data)
            return _Resp()

        def bad_ssh(*a, **k):
            raise AssertionError("ssh must not run for local host")

        out = kk_mac_llm.call_remote(
            "p", host="local", model="qwen3:8b", format="json",
            ssh_run=bad_ssh, urlopen=fake_urlopen)
        self.assertEqual(out["response"], "ok")
        self.assertEqual(sent["url"],
                         "http://127.0.0.1:11434/api/generate")
        self.assertEqual(sent["body"]["format"], "json")
        self.assertFalse(sent["body"]["think"])

    def test_remote_call_uses_ssh(self):
        from scripts.devnest import kk_mac_llm

        class _R:
            returncode = 0
            stdout = json.dumps({"response": "hi"}).encode()
            stderr = b""

        calls = []

        def fake_ssh(cmd, **kw):
            calls.append(cmd)
            return _R()

        out = kk_mac_llm.call_remote("p", host="kk-mac",
                                     ssh_run=fake_ssh)
        self.assertEqual(out["response"], "hi")
        self.assertEqual(calls[0][0], "ssh")

    def test_memory_local_sample_on_linux(self):
        from scripts.devnest import kk_mac_memory
        if os.uname().sysname != "Linux":
            self.skipTest("linux-only procfs path")
        s = kk_mac_memory.sample("local")
        self.assertTrue(s["ok"])
        self.assertGreater(s["free_pct"], 0)


if __name__ == "__main__":
    unittest.main()
