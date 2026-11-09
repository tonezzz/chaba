"""kk_mac_capacity_producer — filename-derived skip, atomic ready-marker
staging, incomplete-pack retry, and the hard 3/3 cap (OPS-1002
atomic-3-3, card devnest-capacity-aware-dispatch).

The Oct-31 incident: the producer cat'd every one of ~70 routed inbox
specs before reaching new work and timed out at 4min, leaving an
unsealed pack dir. Pinned here:

  - inbox filenames drive the skip decision; `rclone cat` only happens
    for packs that actually need staging
  - terminal / sealed (ready) / claimed packs are skipped cheaply;
    an unsealed unclaimed dir is RETRIED (re-staged + re-sealed)
  - staging = copy -> `rclone check --one-way` -> `ready` marker whose
    manifest hashes the remote file set
  - depth/new-work args are clamped to the OPS-1002 3/3 watermark
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.devnest import kk_mac_capacity_producer as kp
from scripts.ada import nest_pack_ready as npr

REMOTE = "fake:kk-llm"


class FakeRemote:
    """Drive stand-in: inbox specs + pack tree as {relpath: size-or-text}.

    models enough rclone for produce(): lsf (files-only / recursive /
    --format sp), cat, copy (local->remote), check, rcat. Counts calls
    so the test can pin 'no cat for skippable specs'."""

    def __init__(self, inbox=None, packs=None):
        self.inbox = dict(inbox or {})          # {filename: json-text}
        self.packs = {p: dict(files) for p, files in (packs or {}).items()}
        self.calls = []

    def rclone(self, *args, input_text=None):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "lsf":
            path = args[1]
            if path == f"{REMOTE}/inbox":
                return "\n".join(sorted(self.inbox))
            if path == f"{REMOTE}/packs":
                lines = []
                for pack, files in self.packs.items():
                    if not files:
                        lines.append(pack + "/")
                    for rel in files:
                        lines.append(f"{pack}/{rel}")
                return "\n".join(lines)
            # per-pack listing --format sp
            if path.startswith(f"{REMOTE}/packs/"):
                name = path.rsplit("/", 1)[-1]
                out = []
                for rel, body in self.packs.get(name, {}).items():
                    size = len(body) if isinstance(body, str) else body
                    out.append(f"{size};{rel}")
                return "\n".join(out)
            return ""
        if cmd == "cat":
            path = args[1]
            if path.startswith(f"{REMOTE}/inbox/"):
                return self.inbox[path.rsplit("/", 1)[-1]]
            raise RuntimeError("cat miss: " + path)
        if cmd == "copy":
            src = Path(args[1])
            dst = args[2].rstrip("/")
            name = dst.rsplit("/", 1)[-1]
            files = self.packs.setdefault(name, {})
            for f in src.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src).as_posix()
                    files[rel] = f.read_text()
            return ""
        if cmd == "check":
            # verify local ⊆ remote (the --one-way contract)
            src, dst = Path(args[1]), args[2].rstrip("/")
            name = dst.rsplit("/", 1)[-1]
            files = self.packs.get(name, {})
            for f in src.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src).as_posix()
                    if rel not in files:
                        raise RuntimeError(f"check: {rel} missing remote")
            return ""
        if cmd == "rcat":
            path, name = args[1], None
            name = path.split("/")[-2]
            rel = path.rsplit("/", 1)[-1]
            self.packs.setdefault(name, {})[rel] = input_text
            return ""
        raise RuntimeError(f"unmocked rclone {args}")

    def n_calls(self, *prefix):
        return sum(1 for c in self.calls
                   if c[:len(prefix)] == prefix)


def spec(task_id="report-review-aaa111bbb222"):
    return {
        "task_id": task_id, "lane": "kk_mac_local",
        "task_class": "summary", "model": "qwen3:8b",
        "prompt": "Summarize the report. Source: reports/x.md\n\nbody",
        "expect": {}, "timeout_s": 600,
    }


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.remote = FakeRemote()
        self._rclone, self._snap = kp.rclone, kp.snapshot
        kp.rclone = self.remote.rclone
        kp.snapshot = lambda **kw: {"eligible": True, "reasons": [],
                                    "host": "KKs-Mac-Studio"}
        self._tmp = tempfile.TemporaryDirectory()
        template = Path(self._tmp.name) / "kk-mac-llm-pack"
        (template / "inputs").mkdir(parents=True)
        (template / "pack.yml").write_text("name: kk-mac-llm-pack\n")
        self.template = template

    def tearDown(self):
        kp.rclone, kp.snapshot = self._rclone, self._snap
        self._tmp.cleanup()

    def run_produce(self, **kw):
        kw.setdefault("template", self.template)
        return kp.produce(remote=REMOTE, **kw)

    def test_sealed_terminal_claimed_skip_without_cat(self):
        self.remote.inbox = {
            "report-review-aaa111bbb222.json": json.dumps(spec()),
            "report-review-ccc333ddd444.json": json.dumps(
                spec("report-review-ccc333ddd444")),
            "report-review-eee555fff666.json": json.dumps(
                spec("report-review-eee555fff666")),
        }
        self.remote.packs = {
            "kk-mac-task-report-review-aaa111bbb222": {
                "pack.yml": "x", "ready": "{}", "done": "x"},
            "kk-mac-task-report-review-ccc333ddd444": {
                "pack.yml": "x", "ready": "{}"},
            "kk-mac-task-report-review-eee555fff666": {
                "pack.yml": "x", "claim/w": "1"},
        }
        out = self.run_produce()
        self.assertEqual(self.remote.n_calls("cat"), 0)
        self.assertIn("report-review-aaa111bbb222.json:terminal",
                      out["skipped"])
        self.assertIn("report-review-ccc333ddd444.json:already_staged",
                      out["skipped"])
        self.assertIn("report-review-eee555fff666.json:claimed",
                      out["skipped"])
        self.assertEqual(out["staged"], [])

    def test_incomplete_unclaimed_pack_retried(self):
        self.remote.inbox = {
            "report-review-aaa111bbb222.json": json.dumps(spec())}
        # the observed defect shape: a pack dir with no files, no seal
        self.remote.packs = {
            "kk-mac-task-report-review-aaa111bbb222": {}}
        out = self.run_produce()
        self.assertEqual(
            out["staged"], ["kk-mac-task-report-review-aaa111bbb222"])
        self.assertEqual(
            out["retried"], ["kk-mac-task-report-review-aaa111bbb222"])
        pack = self.remote.packs["kk-mac-task-report-review-aaa111bbb222"]
        self.assertIn("ready", pack)
        self.assertIn("pack.yml", pack)
        self.assertIn("inputs/task.json", pack)
        marker = npr.parse_marker(pack["ready"])
        self.assertIsNotNone(marker)
        remote_entries = {r: len(c) for r, c in pack.items()}
        ok, _ = npr.marker_valid(marker, remote_entries)
        self.assertTrue(ok)

    def test_new_task_staged_and_sealed(self):
        self.remote.inbox = {
            "report-review-aaa111bbb222.json": json.dumps(spec())}
        out = self.run_produce()
        self.assertEqual(
            out["staged"], ["kk-mac-task-report-review-aaa111bbb222"])
        pack = self.remote.packs["kk-mac-task-report-review-aaa111bbb222"]
        marker = npr.parse_marker(pack["ready"])
        self.assertEqual(marker["staged_by"], "kk_mac_capacity_producer")
        # check + remote manifest + rcat all happened after the copy
        self.assertEqual(self.remote.n_calls("check"), 1)
        self.assertEqual(self.remote.n_calls("rcat"), 1)

    def test_task_id_mismatch_rejected(self):
        bad = spec()
        bad["task_id"] = "different-id-9999"
        self.remote.inbox = {"report-review-aaa111bbb222.json":
                             json.dumps(bad)}
        out = self.run_produce()
        self.assertIn("report-review-aaa111bbb222.json:task_id_mismatch",
                      out["skipped"])
        self.assertEqual(out["staged"], [])

    def test_hard_cap_3_3_regardless_of_args(self):
        for i in range(6):
            tid = f"report-review-{i:012d}"[-12:]
            tid = f"report-review-{i:012x}"
            self.remote.inbox[f"{tid}.json"] = json.dumps(spec(tid))
        out = self.run_produce(max_depth=10, max_new=5)
        self.assertEqual(out["limits"]["max_depth"], 3)
        self.assertEqual(out["limits"]["max_new"], 3)
        self.assertTrue(out["limits"]["clamped"])
        self.assertEqual(len(out["staged"]), 3)

    def test_queue_at_capacity_blocks(self):
        self.remote.inbox = {
            "report-review-aaa111bbb222.json": json.dumps(spec())}
        for i in range(3):
            self.remote.packs[f"kk-mac-task-other-{i}"] = {
                "pack.yml": "x", "ready": "{}"}
        out = self.run_produce()
        self.assertEqual(out["queue_before"], 3)
        self.assertIn("queue_at_capacity", out["skipped"])
        self.assertEqual(out["staged"], [])

    def test_incomplete_dir_not_counted_as_depth(self):
        # two unsealed debris dirs + one sealed: depth is 1, room is 2
        self.remote.packs = {
            "kk-mac-task-debris-1": {},
            "kk-mac-task-debris-2": {"pack.yml": "x"},
            "kk-mac-task-sealed-1": {"pack.yml": "x", "ready": "{}"},
        }
        out = self.run_produce()
        self.assertEqual(out["queue_before"], 1)

    def test_ineligible_gate_short_circuits(self):
        kp.snapshot = lambda **kw: {"eligible": False,
                                    "reasons": ["heartbeat_stale"]}
        self.remote.inbox = {
            "report-review-aaa111bbb222.json": json.dumps(spec())}
        out = self.run_produce()
        self.assertFalse(out["eligible"])
        self.assertIn("admission_gate", out["skipped"])
        self.assertEqual(self.remote.n_calls("cat"), 0)

    def test_bad_filename_skipped(self):
        self.remote.inbox = {"BAD NAME.json": json.dumps(spec())}
        out = self.run_produce()
        self.assertIn("BAD NAME.json:bad_task_filename", out["skipped"])


if __name__ == "__main__":
    unittest.main()
