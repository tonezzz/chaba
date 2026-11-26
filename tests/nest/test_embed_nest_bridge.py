"""Unit tests for embed-nest-bridge JobStore semantics (MEM-0805 lane B,
rebuilt 2026-11-24). No network — exercises the queue/claim/lease logic
directly with patched short timeouts."""
import importlib.util
import sys
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bridge = load("embed_nest_bridge", "scripts/nest/embed-nest-bridge.py")


class FastBridge(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(bridge, k) for k in
                       ("WAIT_S", "JOB_TTL_S", "LEASE_S", "WORKER_STALE_S",
                        "POLL_S")}
        bridge.WAIT_S = 0.4
        bridge.JOB_TTL_S = 0.3
        bridge.LEASE_S = 0.2
        bridge.WORKER_STALE_S = 30
        bridge.POLL_S = 0.01
        self.store = bridge.JobStore()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(bridge, k, v)

    def test_no_worker_fast_503(self):
        status, body = self.store.submit("bge-m3", ["hello"])
        self.assertEqual(status, 503)
        self.assertIn("no nest worker", body["error"])

    def test_claim_then_result_resolves_waiter(self):
        # worker long-poll counts as alive
        claimed = {}

        def worker():
            j = self.store.claim("w1", {"bge-m3"}, 2.0)
            claimed.update(j)
            self.store.resolve("w1", j["job_id"],
                               embeddings=[[0.1] * 8])

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.05)          # let the claim loop register the worker
        status, body = self.store.submit("bge-m3", ["a", "b"])
        t.join(3)
        self.assertEqual(status, 200)
        self.assertEqual(body["embeddings"], [[0.1] * 8])
        self.assertEqual(claimed["texts"], ["a", "b"])

    def test_model_caps_filter(self):
        got = {}

        def worker():
            j = self.store.claim("w-minilm", {"minilm"}, 0.5)
            got["job"] = j

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.05)
        status, _ = self.store.submit("bge-m3", ["x"])
        t.join(2)
        self.assertEqual(status, 503)          # nobody could take it
        self.assertIsNone(got.get("job"))      # caps filtered it out

    def test_lease_expiry_requeues_once(self):
        self.store._touch_worker("w1")
        job = bridge.Job("bge-m3", ["t"])
        self.store._pending.append(job)
        payload = self.store.claim("w1", {"bge-m3"}, 0.1)
        self.assertIsNotNone(payload)
        time.sleep(bridge.LEASE_S + 0.05)
        self.store.reap()
        # requeued -> claimable again by another worker
        again = self.store.claim("w2", {"bge-m3"}, 0.2)
        self.assertIsNotNone(again)
        self.assertEqual(again["job_id"], payload["job_id"])

    def test_double_lease_expiry_fails_waiter(self):
        bridge.JOB_TTL_S = 5.0   # outlive two lease cycles
        bridge.WAIT_S = 3.0      # waiter outlives the lease churn
        self.store._touch_worker("w1")
        out = {}

        def waiter():
            out["r"] = self.store.submit("bge-m3", ["t"])

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.05)
        # claim + let lease die twice
        for _ in range(2):
            j = self.store.claim("w1", {"bge-m3"}, 0.5)
            self.assertIsNotNone(j)
            time.sleep(bridge.LEASE_S + 0.05)
            self.store.reap()
        t.join(3)
        status, body = out["r"]
        self.assertEqual(status, 503)
        self.assertIn("lease", body["error"])

    def test_worker_error_propagates_503(self):
        def worker():
            j = self.store.claim("w1", {"bge-m3"}, 2.0)
            self.store.resolve("w1", j["job_id"], error="oom")

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.05)
        status, body = self.store.submit("bge-m3", ["t"])
        t.join(3)
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "oom")

    def test_resolve_unknown_job(self):
        self.assertFalse(self.store.resolve("w1", "job-nope",
                                            embeddings=[[1.0]]))

    def test_timed_out_submit_cancels_job(self):
        self.store._touch_worker("w1")
        status, _ = self.store.submit("bge-m3", ["t"])
        self.assertEqual(status, 503)
        # cancelled job must not be claimable afterwards
        self.assertIsNone(self.store.claim("w1", {"bge-m3"}, 0.05))


if __name__ == "__main__":
    unittest.main()
