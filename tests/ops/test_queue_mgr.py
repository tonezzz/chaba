"""Tests for queue-mgr — the ada-nest Drive->nest_job mirror (OPS-0759)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/queue-mgr.py"

spec = importlib.util.spec_from_file_location("queue_mgr", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["queue_mgr"] = mod
spec.loader.exec_module(mod)


def scan_fixture(**over):
    sc = {
        "packs": {},
        "jobs": [],
        "done_work": set(),
        "env_done": set(),
        "env_boot": "",
        "heartbeat": {"epoch": 0.0, "job": "", "phase": "",
                      "age_s": None},
        "runner": {},
        "lease": {},
    }
    sc.update(over)
    return sc


def pack(done="", failed="", claims=(), spec=None):
    return {"done": done, "failed": failed, "claims": list(claims),
            "spec": spec or {}}


class Derive(unittest.TestCase):
    def test_empty_store_root_queued(self):
        posts = mod.derive(scan_fixture())
        self.assertEqual(list(posts), [mod.ROOT_SLUG])
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "queued")
        self.assertEqual(posts[mod.ROOT_SLUG]["kind"], "queue")

    def test_pack_states(self):
        sc = scan_fixture(packs={
            "aaa-done": pack(done="42s boot=x"),
            "bbb-claim": pack(claims=["tony-dell-1234"]),
            "ccc-fail": pack(failed="run rc=1 worker=w"),
            "ddd-queued": pack(),
        })
        posts = mod.derive(sc)
        self.assertEqual(posts["aaa-done"]["status"], "done")
        self.assertEqual(posts["aaa-done"]["result_ref"],
                         "gdrive:ada-nest/packs/aaa-done/done")
        self.assertEqual(posts["aaa-done"]["parent"], mod.ROOT_SLUG)
        self.assertEqual(posts["bbb-claim"]["status"], "claimed")
        self.assertEqual(posts["bbb-claim"]["runner"], "tony-dell-1234")
        self.assertEqual(posts["bbb-claim"]["host"], "tony-dell")
        self.assertEqual(posts["ccc-fail"]["status"], "failed")
        self.assertIn("run rc=1", posts["ccc-fail"]["error"])
        self.assertEqual(posts["ddd-queued"]["status"], "queued")
        # done pack keeps its claim file -> runner attribution survives
        sc2 = scan_fixture(packs={
            "aaa-done": pack(done="42s", claims=["colab-deadbeef-9"])})
        p2 = mod.derive(sc2)["aaa-done"]
        self.assertEqual(p2["runner"], "colab-deadbeef-9")
        self.assertEqual(p2["host"], "colab-deadbeef")

    def test_heartbeat_names_running_pack(self):
        now = time.time()
        sc = scan_fixture(
            packs={"live-pack": pack(claims=["colab-aaa-1"])},
            heartbeat={"epoch": now, "job": "live-pack",
                       "phase": "run", "age_s": 5.0})
        posts = mod.derive(sc)
        self.assertEqual(posts["live-pack"]["status"], "running")
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "running")

    def test_stale_heartbeat_does_not_run(self):
        sc = scan_fixture(
            packs={"p1": pack(claims=["w-1"])},
            heartbeat={"epoch": time.time() - 9999, "job": "p1",
                       "phase": "run", "age_s": 9999.0})
        posts = mod.derive(sc)
        self.assertEqual(posts["p1"]["status"], "claimed")
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "running")

    def test_env_and_work_jobs(self):
        jobs = [{"name": "warmup", "scope": "env"},
                {"name": "real-job", "scope": "work"}]
        sc = scan_fixture(
            jobs=jobs, env_done={"warmup"}, env_boot="boot42",
            done_work={"real-job"})
        posts = mod.derive(sc)
        self.assertEqual(posts["job-warmup"]["status"], "done")
        self.assertIn("env-done/boot42/warmup.done",
                      posts["job-warmup"]["result_ref"])
        self.assertEqual(posts["job-real-job"]["status"], "done")
        self.assertIn("queue/done/real-job.done",
                      posts["job-real-job"]["result_ref"])
        self.assertEqual(posts["job-warmup"]["kind"], "sub")
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "done")

    def test_env_job_queued_when_not_in_boot(self):
        sc = scan_fixture(jobs=[{"name": "warmup", "scope": "env"}],
                          env_done=set(), env_boot="boot42")
        self.assertEqual(mod.derive(sc)["job-warmup"]["status"], "queued")

    def test_root_derivation_matrix(self):
        # pending only -> queued
        posts = mod.derive(scan_fixture(packs={"p": pack()}))
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "queued")
        # all done -> done
        posts = mod.derive(scan_fixture(
            packs={"a": pack(done="1s"), "b": pack(done="2s")}))
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "done")
        # done+failed mix -> done (failure visible per-child)
        posts = mod.derive(scan_fixture(
            packs={"a": pack(done="1s"), "b": pack(failed="x")}))
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "done")
        # all failed -> failed
        posts = mod.derive(scan_fixture(
            packs={"a": pack(failed="x"), "b": pack(failed="y")}))
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "failed")
        # claimed child -> running
        posts = mod.derive(scan_fixture(packs={"p": pack(claims=["w-1"])}))
        self.assertEqual(posts[mod.ROOT_SLUG]["status"], "running")

    def test_root_runner_from_lease(self):
        now = int(time.time())
        sc = scan_fixture(lease={"worker": "colab-deadbeef-42",
                                 "epoch": 7, "ts": now})
        posts = mod.derive(sc)
        self.assertEqual(posts[mod.ROOT_SLUG]["runner"],
                         "colab-deadbeef-42")
        # stale lease -> no runner attribution
        sc["lease"]["ts"] = now - 99999
        self.assertEqual(mod.derive(sc)[mod.ROOT_SLUG]["runner"], "")

    def test_done_posts_carry_evidence(self):
        """OPS-0923: every done write must satisfy the board-api
        terminal-done gate — result_ref plus evidence refs, or the
        mirror post 400s and the tick wedges."""
        sc = scan_fixture(packs={
            "aaa-done": pack(done="42s"),
            "bbb-claim": pack(claims=["w-1"])})
        posts = mod.derive(sc)
        self.assertEqual(posts["aaa-done"]["evidence"],
                         ["gdrive:ada-nest/packs/aaa-done/done"])
        self.assertNotIn("evidence", posts["bbb-claim"])
        # env/work job done markers carry evidence too
        sc2 = scan_fixture(jobs=[{"name": "j", "scope": "work"}],
                           done_work={"j"})
        self.assertEqual(mod.derive(sc2)["job-j"]["evidence"],
                         ["gdrive:ada-nest/queue/done/j.done"])
        # root done is derived — evidence = the children's done
        # markers (capped at 10, queue dir as fallback)
        sc3 = scan_fixture(packs={"a": pack(done="1s"),
                                  "b": pack(done="2s")})
        root = mod.derive(sc3)[mod.ROOT_SLUG]
        self.assertEqual(root["status"], "done")
        self.assertEqual(len(root["evidence"]), 2)
        self.assertTrue(all("/done" in e for e in root["evidence"]))


class Scan(unittest.TestCase):
    """scan() assembly over a faked rclone — inventory parsing, marker
    detection, env-boot selection."""

    def _fake_ok(self, *args, timeout=60):
        lsf, cat = self.LSF, self.CAT
        if args[0] == "lsf":
            path = args[1]
            fmt = args[args.index("--format") + 1] \
                if "--format" in args else None
            return "\n".join(lsf.get((path, fmt), [])) + "\n"
        if args[0] == "cat":
            return cat.get(args[1], "")
        return ""

    def test_scan_assembles_packs_and_boot(self):
        now = time.time()
        self.LSF = {
            (mod.PACKS, "pt"): [
                "aaa-done/pack.yml;2026-11-01 00:00:00",
                "aaa-done/done;2026-11-02 00:00:00",
                "aaa-done/claim/tony-dell-9;2026-11-01 01:00:00",
                "bbb-live/pack.yml;2026-11-03 00:00:00",
                "bbb-live/claim/colab-deadbeef-5;2026-11-03 01:00:00",
                "stray-file.txt;2026-11-01 00:00:00",
            ],
            (f"{mod.Q}/done", None): ["oldjob.done"],
            (f"{mod.Q}/env-done", "pt"): [
                "bootA/;2026-11-01 00:00:00",
                "bootB/;2026-11-20 00:00:00",
            ],
            (f"{mod.Q}/env-done/bootB", None): ["warmup.done"],
        }
        self.CAT = {
            f"{mod.Q}/JOBS.py": (
                "JOBS=[{'name':'warmup','scope':'env'},"
                "{'name':'oldjob','scope':'work'}]"),
            f"{mod.Q}/heartbeat": f"{now:.0f} bbb-live run\n",
            f"{mod.Q}/runner.id": json.dumps(
                {"boot_id": "bootB", "worker": "colab-x-1",
                 "ts": now}),
            f"{mod.Q}/lease": json.dumps(
                {"worker": "colab-x-1", "epoch": 3, "ts": now}),
        }
        with patch.object(mod, "rclone_ok", side_effect=self._fake_ok), \
                patch.object(mod, "fetch_pack_meta",
                             return_value={"aaa-done": {"name": "aaa-done"},
                                           "bbb-live": {"name": "bbb-live"}}):
            sc = mod.scan()
        self.assertIn("aaa-done", sc["packs"])
        self.assertEqual(sc["packs"]["aaa-done"]["claims"],
                         ["tony-dell-9"])
        self.assertEqual(sc["packs"]["aaa-done"]["done"], "1")
        self.assertNotIn("stray-file.txt", sc["packs"])
        self.assertEqual(sc["env_boot"], "bootB")     # runner.id boot wins
        self.assertEqual(sc["env_done"], {"warmup"})
        self.assertEqual(sc["done_work"], {"oldjob"})
        self.assertEqual(sc["heartbeat"]["job"], "bbb-live")
        posts = mod.derive(sc)
        self.assertEqual(posts["aaa-done"]["status"], "done")
        self.assertEqual(posts["bbb-live"]["status"], "running")
        self.assertEqual(posts["job-warmup"]["status"], "done")
        self.assertEqual(posts["job-oldjob"]["status"], "done")


class FingerprintAndComms(unittest.TestCase):
    def test_fp_stable_and_sensitive(self):
        p1 = {"slug": "s", "title": "t", "status": "queued",
              "kind": "pack", "parent": "ada-nest-queue"}
        p2 = dict(p1)
        self.assertEqual(mod.fingerprint(p1), mod.fingerprint(p2))
        p2["status"] = "done"
        self.assertNotEqual(mod.fingerprint(p1), mod.fingerprint(p2))

    def test_comms_transitions(self):
        old = {"status": "queued"}
        new = {"status": "claimed", "runner": "tony-dell-1",
               "slug": "p1", "title": "p1"}
        self.assertIn("claimed by tony-dell-1",
                      mod.transition_comms(old, new))
        new = {"status": "done", "result_ref": "gdrive:x",
               "slug": "p1", "title": "p1"}
        self.assertIn("done", mod.transition_comms(old, new))
        old = {"status": "claimed"}
        new = {"status": "queued", "slug": "p1", "title": "p1"}
        self.assertIn("released", mod.transition_comms(old, new))


class ManifestParse(unittest.TestCase):
    def test_parse_jobs_py(self):
        text = (REPO / "scripts/colab/JOBS.py").read_text()
        jobs = mod.parse_manifest(text)
        self.assertTrue(jobs)
        names = {j["name"] for j in jobs}
        self.assertIn("t4-session-warmup", names)
        self.assertTrue(all(j["scope"] for j in jobs))

    def test_parse_fallback_regex(self):
        text = "JOBS=[{'name':'a-b','scope':'env'},{'name':'c','scope':'work'}]"
        jobs = mod.parse_manifest(text)
        self.assertEqual([(j["name"], j["scope"]) for j in jobs],
                         [("a-b", "env"), ("c", "work")])


class HostFromWorker(unittest.TestCase):
    def test_strip_pid(self):
        self.assertEqual(mod._host_from_worker("tony-dell-1234"),
                         "tony-dell")
        self.assertEqual(mod._host_from_worker("colab-deadbeef-42"),
                         "colab-deadbeef")
        self.assertEqual(mod._host_from_worker("mn01-7"), "mn01")
        self.assertEqual(mod._host_from_worker(""), "")


class MainFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = mod.STATE
        mod.STATE = Path(self.tmp.name) / "state.json"
        self.posts = []

    def tearDown(self):
        mod.STATE = self.old_state
        self.tmp.cleanup()

    def _run(self, sc, api_ok=True):
        before = len(self.posts)

        def fake_api(path, payload, timeout=30):
            if not api_ok:
                raise OSError("boom")
            self.posts.append((path, payload))
            return {"post_id": len(self.posts) + 100, "action": "created"}

        with patch.object(mod, "scan", return_value=sc), \
                patch.object(mod, "api_post", side_effect=fake_api):
            rc = mod.main([])
        return rc, self.posts[before:]

    def test_first_tick_posts_root_then_children(self):
        sc = scan_fixture(packs={"p1": pack(claims=["w-1"])})
        rc, new = self._run(sc)
        self.assertEqual(rc, 0)
        slugs = [p["slug"] for _path, p in new]
        self.assertEqual(slugs[0], mod.ROOT_SLUG)   # parent first
        self.assertIn("p1", slugs)
        body = new[1][1]
        self.assertEqual(body["from"], "queue-mgr")
        self.assertEqual(body["parent"], mod.ROOT_SLUG)
        self.assertEqual(body["kind"], "pack")
        self.assertTrue(body["comms"])

    def test_second_tick_is_silent(self):
        sc = scan_fixture(packs={"p1": pack(claims=["w-1"])})
        self._run(sc)
        _rc, new = self._run(sc)
        self.assertEqual(new, [])                    # no new POSTs

    def test_transition_reposts_with_comms(self):
        sc1 = scan_fixture(packs={"p1": pack()})
        self._run(sc1)
        sc2 = scan_fixture(packs={"p1": pack(done="9s")})
        _rc, new = self._run(sc2)
        pack_posts = [p for _path, p in new if p["slug"] == "p1"]
        self.assertEqual(len(pack_posts), 1)
        last = pack_posts[0]
        self.assertEqual(last["status"], "done")
        self.assertIn("queued -> done", last["comms"])

    def test_api_failure_keeps_fp_unadvanced(self):
        sc = scan_fixture(packs={"p1": pack(done="1s")})
        self._run(sc, api_ok=False)
        st = json.loads(mod.STATE.read_text())
        self.assertEqual(st["posts"], {})           # nothing recorded
        # recovery: next good tick posts everything
        _rc, new = self._run(sc, api_ok=True)
        self.assertTrue(any(p["slug"] == "p1" for _path, p in new))

    def test_root_failure_skips_children(self):
        calls = []

        def fake_api(path, payload, timeout=30):
            calls.append(payload["slug"])
            if payload["slug"] == mod.ROOT_SLUG:
                raise OSError("wp down")
            return {"post_id": 1, "action": "created"}

        with patch.object(mod, "scan",
                          return_value=scan_fixture(
                              packs={"p1": pack()})), \
                patch.object(mod, "api_post", side_effect=fake_api):
            mod.main([])
        self.assertEqual(calls, [mod.ROOT_SLUG])    # children skipped

    def test_dry_run_writes_nothing(self):
        with patch.object(mod, "scan",
                          return_value=scan_fixture(
                              packs={"p1": pack()})), \
                patch.object(mod, "api_post") as api:
            self.assertEqual(mod.main(["--dry-run"]), 0)
            api.assert_not_called()
        self.assertFalse(mod.STATE.exists())

    def test_kill_switch(self):
        off = Path(self.tmp.name) / "off"
        off.touch()
        old = mod.OFF_FILE
        mod.OFF_FILE = off
        try:
            with patch.object(mod, "scan") as scan:
                self.assertEqual(mod.main([]), 0)
                scan.assert_not_called()
        finally:
            mod.OFF_FILE = old


if __name__ == "__main__":
    unittest.main()
