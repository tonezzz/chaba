"""Sandbox tests for the ada-nest release-pinning flow
(card devnest-colab-release-pinning).

Covers:
  - release.json manifest build + verify (missing/mismatch/extra files)
  - hash-aware done/failed markers (jh/ph/gh) + legacy rescue
  - pack materialization (code -> workspace, state preserved, stale files pruned)
  - publisher dry-run + full publish against a LOCAL rclone remote
  - launcher release gate (unpinned refuse, verified spawn, tamper refuse,
    notebook mismatch refuse)
  - end-to-end pinned runner drain with hash-stamped markers
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COLAB = REPO / "scripts/colab"
LIB = COLAB / "release_lib.py"
PUBLISHER = COLAB / "publish-release.py"
RUNNER_SRC = COLAB / "queue-runner.py"
LAUNCHER = COLAB / "queue-launcher-cell.py"
PREFLIGHT = COLAB / "preflight-cell.py"
REGISTRY = COLAB / "runtime_registry.py"
JOBS_SRC = COLAB / "JOBS.py"

NVIDIA_SMI_STUB = """#!/bin/bash
case "$*" in
  *"name,memory.total"*) echo "Tesla T4, 15360" ;;
  *"memory.total"*)      echo "15360" ;;
  *"memory.free"*)       echo "15000" ;;
  *"utilization.gpu,memory.used"*) echo "0, 0" ;;
  *) echo "0" ;;
esac
exit 0
"""


def sha(p: Path):
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RL = load_module(LIB, "release_lib")


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def write_release(root: Path, rel_id="rel-test-0001", *,
                  queue_files=None, packs=None, gap_packs=None,
                  tamper=None, deploy_notebook=True):
    """Stage a complete pinned release under <root>/releases/<rel_id>/ +
    queue/ACTIVE_RELEASE.json + deployed notebook. Returns manifest dict.
    queue_files: {relpath: content} — defaults ship the REAL runner,
    registry, release_lib, cells, JOBS.py and a tiny notebook."""
    rel_dir = root / "releases" / rel_id
    qd = rel_dir / "queue"
    qd.mkdir(parents=True)
    files = {}
    if queue_files is None:
        queue_files = {
            "runner.py": RUNNER_SRC.read_bytes(),
            "JOBS.py": JOBS_SRC.read_bytes(),
            "runtime_registry.py": REGISTRY.read_bytes(),
            "release_lib.py": LIB.read_bytes(),
            "preflight-cell.py": PREFLIGHT.read_bytes(),
            "queue-launcher-cell.py": LAUNCHER.read_bytes(),
            "ada-nest-job-console.ipynb":
                b'{"cells": [], "nbformat": 4, "nbformat_minor": 0}\n',
        }
    for rel, content in queue_files.items():
        p = qd / rel if "/" not in rel else rel_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes)
                      else content.encode())
        files[f"queue/{rel}" if "/" not in rel else rel] = sha(p)
    for kind, spec in (("packs", packs), ("gap-packs", gap_packs)):
        for name, fmap in (spec or {}).items():
            for rel, content in fmap.items():
                p = rel_dir / kind / name / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content if isinstance(content, bytes)
                              else content.encode())
                files[f"{kind}/{name}/{rel}"] = sha(p)
    pack_rollup = {"packs": {}, "gap_packs": {}}
    for kind_dir, kind_key in (("packs", "packs"),
                               ("gap-packs", "gap_packs")):
        spec = packs if kind_dir == "packs" else gap_packs
        for name in (spec or {}):
            pre = f"{kind_dir}/{name}/"
            # keys are release-relpaths minus the 'packs/' prefix —
            # identical to the publisher's roll-up convention
            fshas = {r[len(kind_dir) + 1:]: s
                     for r, s in files.items() if r.startswith(pre)}
            pack_rollup[kind_key][name] = {
                "sha256": RL.content_hash(fshas), "files": len(fshas)}
    manifest = {
        "schema": 1, "release_id": rel_id, "commit": "cafe" * 10,
        "generated_at": int(time.time()),
        "files": files,
        "packs": pack_rollup.get("packs", {}),
        "gap_packs": pack_rollup.get("gap_packs", {}),
    }
    mbytes = (json.dumps(manifest, indent=1) + "\n").encode()
    (rel_dir / "release.json").write_bytes(mbytes)
    if tamper:
        for rel, content in tamper.items():
            p = rel_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content if isinstance(content, bytes)
                          else content.encode())
    q = root / "queue"
    q.mkdir(parents=True, exist_ok=True)
    (q / "ACTIVE_RELEASE.json").write_text(json.dumps({
        "schema": 1, "release_id": rel_id,
        "release_sha256": hashlib.sha256(mbytes).hexdigest(),
        "commit": manifest["commit"], "activated_at": int(time.time()),
        "previous": None}))
    if deploy_notebook:
        nb = rel_dir / "queue" / "ada-nest-job-console.ipynb"
        if nb.exists():
            shutil.copy2(nb, q / "ada-nest-job-console.ipynb")
    return manifest


class ReleaseSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nest-rel-"))
        self.root = self.tmp / "ada-nest"
        self.q = self.root / "queue"
        self.q.mkdir(parents=True)
        self.old_env = {k: os.environ.get(k) for k in (
            "NEST_ROOT", "NEST_QUEUE", "NEST_RUNTIME_TTL_S", "PATH",
            "NEST_QUEUE_SETTLE_S", "NEST_RELEASE_DIR", "NEST_RELEASE_ID",
            "NEST_RELEASE_SHA")}
        os.environ["NEST_ROOT"] = str(self.root)
        os.environ["NEST_QUEUE"] = str(self.q)
        os.environ["NEST_RUNTIME_TTL_S"] = "60"
        os.environ["NEST_QUEUE_SETTLE_S"] = "0.2"
        for k in ("NEST_RELEASE_DIR", "NEST_RELEASE_ID", "NEST_RELEASE_SHA"):
            os.environ.pop(k, None)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir(exist_ok=True)
        smi = self.bindir / "nvidia-smi"
        smi.write_text(NVIDIA_SMI_STUB)
        smi.chmod(smi.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = f"{self.bindir}:{os.environ['PATH']}"

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestVerifyRelease(ReleaseSandbox):
    def test_clean_release_verifies(self):
        m = write_release(self.root, packs={
            "smoke": {"pack.yml": "name: smoke\nrun: |\n  print(1)\n"}})
        self.assertEqual(
            RL.verify_release(str(self.root), "rel-test-0001", m), [])

    def test_missing_file_detected(self):
        m = write_release(self.root)
        (self.root / "releases/rel-test-0001/queue/JOBS.py").unlink()
        problems = RL.verify_release(str(self.root), "rel-test-0001", m)
        self.assertTrue(any("missing" in p for p in problems))

    def test_hash_mismatch_detected(self):
        m = write_release(self.root)
        (self.root / "releases/rel-test-0001/queue/JOBS.py"
         ).write_text("JOBS = [{'name': 'tampered'}]\n")
        problems = RL.verify_release(str(self.root), "rel-test-0001", m)
        self.assertTrue(any("hash mismatch" in p for p in problems))

    def test_undeclared_file_detected(self):
        m = write_release(self.root)
        (self.root / "releases/rel-test-0001/queue/evil.py"
         ).write_text("print('hi')")
        problems = RL.verify_release(str(self.root), "rel-test-0001", m)
        self.assertTrue(any("undeclared" in p for p in problems))

    def test_pointer_sha_mismatch_makes_resolve_bad(self):
        m = write_release(self.root)
        ptr = json.loads((self.q / "ACTIVE_RELEASE.json").read_text())
        ptr["release_sha256"] = "0" * 64
        (self.q / "ACTIVE_RELEASE.json").write_text(json.dumps(ptr))
        status, *_ = RL.resolve_active(str(self.root), str(self.q))
        self.assertEqual(status, "bad")


class TestMarkers(ReleaseSandbox):
    def test_marker_fresh_hash_match(self):
        m = self.tmp / "m.done"
        RL.stamp_marker(str(m), 3.0, "boot1", 7, "rel-x", "ph",
                        "ab" * 32, "info")
        self.assertEqual(RL.marker_fresh(str(m), "ph", "ab" * 32),
                         (True, "ph=abababababab match"))

    def test_marker_stale_hash_mismatch(self):
        m = self.tmp / "m.done"
        RL.stamp_marker(str(m), 3.0, "boot1", 7, "rel-x", "ph",
                        "ab" * 32, "")
        fresh, why = RL.marker_fresh(str(m), "ph", "cd" * 32)
        self.assertFalse(fresh)
        self.assertIn("stale", why)

    def test_marker_legacy_no_hash(self):
        m = self.tmp / "m.done"
        m.write_text("12s boot=b ep=3\n")
        fresh, why = RL.marker_fresh(str(m), "ph", "ab" * 32)
        self.assertFalse(fresh)
        self.assertIn("legacy", why)


class TestMaterialize(ReleaseSandbox):
    def test_sync_prunes_and_preserves_state(self):
        src = self.tmp / "src" / "pack-a"
        ws = self.root / "packs" / "pack-a"
        (src / "inputs").mkdir(parents=True)
        (src / "pack.yml").write_text("name: pack-a\n")
        (src / "inputs" / "x.txt").write_text("v1")
        (src / "old.py").write_text("x=1")
        (ws / "out").mkdir(parents=True)
        (ws / "out" / "keep.txt").write_text("state")
        files = RL.materialize_pack(str(src), str(ws), "rel-1")
        self.assertIn("pack.yml", files)
        # state preserved
        self.assertTrue((ws / "out" / "keep.txt").exists())
        # second materialize with a removed file prunes it
        (src / "old.py").unlink()
        (src / "new.py").write_text("x=2")
        files = RL.materialize_pack(str(src), str(ws), "rel-2")
        self.assertFalse((ws / "old.py").exists())
        self.assertTrue((ws / "new.py").exists())
        tracker = json.loads((ws / ".release-src.json").read_text())
        self.assertEqual(tracker["release_id"], "rel-2")

    def test_ws_pack_matches(self):
        m = write_release(self.root, packs={
            "p1": {"pack.yml": "name: p1\n", "inputs/a.txt": "data"}})
        ws = self.root / "packs" / "p1"
        self.assertFalse(
            RL.ws_pack_matches(str(ws), m, "packs/p1"))
        RL.materialize_pack(str(self.root / "releases/rel-test-0001"
                                / "packs/p1"), str(ws), "rel-test-0001")
        (ws / "model").mkdir()                      # state dir — ignored
        self.assertTrue(
            RL.ws_pack_matches(str(ws), m, "packs/p1"))


class TestLauncherGate(ReleaseSandbox):
    def setUp(self):
        super().setUp()
        self.launcher = load_module(LAUNCHER, "ql_cell")

    def test_unpinned_refuses(self):
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("REFUSED", str(cm.exception))

    def test_verified_release_spawns(self):
        write_release(self.root)
        spawned = []
        self.launcher.spawn = lambda *a, **k: spawned.append(a)
        self.launcher.main()
        self.assertEqual(len(spawned), 1)
        q, rel_id, rel_dir, msha = spawned[0]
        self.assertEqual(rel_id, "rel-test-0001")

    def test_tampered_release_refuses(self):
        write_release(self.root)
        (self.root / "releases/rel-test-0001/queue/JOBS.py"
         ).write_text("JOBS = [{'name': 'evil'}]\n")
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("REFUSED", str(cm.exception))
        self.assertIn("hash mismatch", str(cm.exception))

    def test_notebook_mismatch_refuses(self):
        write_release(self.root)
        (self.q / "ada-nest-job-console.ipynb").write_text(
            '{"cells": ["edited"], "nbformat": 4}\n')
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("notebook", str(cm.exception).lower())

    def test_pointer_to_missing_release_refuses(self):
        (self.q / "ACTIVE_RELEASE.json").write_text(json.dumps({
            "release_id": "rel-ghost", "release_sha256": "x" * 64}))
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("release.json unreadable", str(cm.exception))

    def test_preflight_reports_and_validates(self):
        import io, contextlib
        write_release(self.root)
        pc = load_module(PREFLIGHT, "pf_cell")
        pc.HB_S = 9999
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pc.main()
        self.assertIn("RELEASE-OK rel-test-0001", buf.getvalue())

    def test_preflight_bad_release_refuses(self):
        write_release(self.root)
        (self.root / "releases/rel-test-0001/queue/runner.py"
         ).write_text("# tampered\n")
        pc = load_module(PREFLIGHT, "pf_cell2")
        with self.assertRaises(SystemExit) as cm:
            pc.main()
        self.assertIn("RELEASE-BAD", str(cm.exception))

    def test_preflight_unpinned_warns_not_refuses(self):
        import io, contextlib
        (self.root / "packs").mkdir(parents=True)
        shutil.copy(REGISTRY, self.q / "runtime_registry.py")
        pc = load_module(PREFLIGHT, "pf_cell3")
        pc.HB_S = 9999
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pc.main()
        self.assertIn("UNPINNED", buf.getvalue())


class TestPinnedRunnerE2E(ReleaseSandbox):
    """Real runner.py out of a release dir against the sandbox nest."""

    def write_pack(self, name, code=b"ok\n"):
        rel = {
            "pack.yml": (
                f"name: {name}\n"
                "needs:\n  egress_only_ok: true\n"
                "timeout_s: 60\n"
                f"artifacts:\n  - packs/{name}/out/result.txt\n"
                "run: |\n"
                "  import os\n"
                "  os.makedirs(f'{PACK_DIR}/out', exist_ok=True)\n"
                "  open(f'{PACK_DIR}/out/result.txt','w')"
                ".write('v2\\n')\n"),
            "inputs/code.txt": code,
        }
        return rel

    def stage_jobs(self, rel_q):
        (rel_q / "JOBS.py").write_text("JOBS = []\n")

    def manifest_for(self, jobs=True, packs=None, rel_id="rel-e2e-1"):
        qf = {
            "runner.py": RUNNER_SRC.read_bytes(),
            "runtime_registry.py": REGISTRY.read_bytes(),
            "release_lib.py": LIB.read_bytes(),
            "queue-launcher-cell.py": LAUNCHER.read_bytes(),
            "ada-nest-job-console.ipynb": b'{"cells":[]}\n',
        }
        if jobs:
            qf["JOBS.py"] = b"JOBS = []\n"
        return write_release(self.root, rel_id,
                             queue_files=qf, packs=packs)

    def run_runner(self, rel_id, timeout=120):
        runner = (self.root / "releases" / rel_id / "queue/runner.py")
        return subprocess.run(
            [sys.executable, "-u", str(runner)],
            capture_output=True, text=True, timeout=timeout,
            env=dict(os.environ))

    def test_pinned_drain_stamps_hashes_and_materializes(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        self.manifest_for(packs=packs)
        r = self.run_runner("rel-e2e-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        done = self.root / "packs/a-pack/done"
        self.assertTrue(done.exists())
        txt = done.read_text()
        self.assertIn("rel=rel-e2e-1", txt)
        self.assertIn("ph=", txt)
        # code materialized into the workspace from the release
        self.assertTrue(
            (self.root / "packs/a-pack/inputs/code.txt").exists())
        self.assertTrue(
            (self.root / "packs/a-pack/out/result.txt").exists())
        self.assertFalse((self.q / "runner.id").exists())
        self.assertIn("release: rel-e2e-1", r.stdout)

    def test_stale_marker_cannot_skip_new_code(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        self.manifest_for(packs=packs)
        ws = self.root / "packs/a-pack"
        ws.mkdir(parents=True)
        (ws / "done").write_text("9s boot=b ep=1 rel=old ph=deadbeef\n")
        r = self.run_runner("rel-e2e-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("a-pack: DONE", r.stdout)      # re-ran
        self.assertIn("rel=rel-e2e-1", (ws / "done").read_text())

    def test_fresh_marker_skips(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        m = self.manifest_for(packs=packs)
        ph = m["packs"]["a-pack"]["sha256"]
        ws = self.root / "packs/a-pack"
        ws.mkdir(parents=True)
        (ws / "done").write_text(
            f"9s boot=b ep=1 rel=rel-e2e-1 ph={ph[:12]}\n")
        r = self.run_runner("rel-e2e-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("a-pack: SKIP", r.stdout)
        self.assertFalse((ws / "out/result.txt").exists())

    def test_legacy_marker_rescued_when_ws_identical(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        m = self.manifest_for(packs=packs)
        ws = self.root / "packs/a-pack"
        RL.materialize_pack(
            str(self.root / "releases/rel-e2e-1/packs/a-pack"),
            str(ws), "rel-e2e-1")
        (ws / "done").write_text("9s boot=b ep=1 some-info\n")
        r = self.run_runner("rel-e2e-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SKIP", r.stdout)
        self.assertIn("legacy-rescued", r.stdout)
        self.assertIn("ph=", (ws / "done").read_text())

    def test_legacy_marker_reruns_when_ws_differs(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        self.manifest_for(packs=packs)
        ws = self.root / "packs/a-pack"
        ws.mkdir(parents=True)
        (ws / "pack.yml").write_text("name: a-pack\n# different\n")
        (ws / "done").write_text("9s boot=b ep=1\n")
        r = self.run_runner("rel-e2e-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("a-pack: DONE", r.stdout)

    def test_tampered_release_runner_exits(self):
        packs = {"a-pack": self.write_pack("a-pack")}
        self.manifest_for(packs=packs)
        (self.root / "releases/rel-e2e-1/packs/a-pack/pack.yml"
         ).write_text("name: a-pack\n# tampered after publish\n")
        r = self.run_runner("rel-e2e-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.root / "packs/a-pack/done").exists())

    def test_runner_self_hash_refuses(self):
        """A runner file that still contains the resolution code but is
        not the pinned bytes must refuse — covers stale-copy launches."""
        self.manifest_for()
        rel_runner = self.root / "releases/rel-e2e-1/queue/runner.py"
        rel_runner.write_text(RUNNER_SRC.read_text()
                              + "\n# post-publish tamper\n")
        r = self.run_runner("rel-e2e-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not the pinned one", r.stdout + r.stderr)


class TestPublisher(ReleaseSandbox):
    """publish-release.py against a temp git repo + a LOCAL rclone remote
    (rclone treats plain paths as local remotes — full publish path)."""

    def make_git_repo(self):
        repo = self.tmp / "repo"
        src = repo / "scripts/colab"
        src.mkdir(parents=True)
        for f in ("queue-runner.py", "JOBS.py", "runtime_registry.py",
                  "preflight-cell.py", "queue-launcher-cell.py",
                  "queue-runner-cell.py", "gap-runner.py",
                  "gap-launcher-cell.py", "release_lib.py",
                  "build-job-console.py", "img_gen.py",
                  "ada-nest-job-console.ipynb"):
            shutil.copy2(COLAB / f, src / f)
        (src / "packs/tiny").mkdir(parents=True)
        (src / "packs/tiny/pack.yml").write_text("name: tiny\n")
        (src / "gap-packs/g1").mkdir(parents=True)
        (src / "gap-packs/g1/pack.json").write_text('{"name":"g1"}\n')
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-b", "master", str(repo)],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "c1"],
                       check=True, capture_output=True, env=env)
        return repo

    def publish(self, repo, remote, *extra):
        return subprocess.run(
            [sys.executable, str(PUBLISHER), "--repo", str(repo),
             "--remote", str(remote), "--ref", "master", "--no-fetch",
             *extra],
            capture_output=True, text=True, timeout=120)

    def test_dry_run_changes_nothing(self):
        repo = self.make_git_repo()
        remote = self.tmp / "remote"
        r = self.publish(repo, remote, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[dry-run]", r.stdout)
        self.assertFalse((remote / "queue/ACTIVE_RELEASE.json").exists())
        self.assertFalse((remote / "releases").exists())

    def full_publish(self):
        """Publish once into a local remote; returns (repo, remote, rel_id)."""
        repo = self.make_git_repo()
        remote = self.tmp / "remote"
        (remote / "queue").mkdir(parents=True)
        (remote / "queue/runner.py").write_text("legacy\n")
        r = self.publish(repo, remote)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ptr = json.loads(
            (remote / "queue/ACTIVE_RELEASE.json").read_text())
        return repo, remote, ptr["release_id"]

    def test_full_publish_verify_pointer_and_notebook(self):
        repo, remote, rel = self.full_publish()
        ptr = json.loads(
            (remote / "queue/ACTIVE_RELEASE.json").read_text())
        self.assertTrue(rel.startswith("rel-"))
        manifest = json.loads(
            (remote / "releases" / rel / "release.json").read_text())
        self.assertEqual(
            ptr["release_sha256"],
            sha(remote / "releases" / rel / "release.json"))
        # every manifest file verifies remotely
        for relp, want in manifest["files"].items():
            self.assertEqual(
                sha(remote / "releases" / rel / relp), want, relp)
        self.assertIn("tiny", manifest["packs"])
        self.assertIn("g1", manifest["gap_packs"])
        # deployed notebook == released notebook
        self.assertEqual(
            sha(remote / "queue/ada-nest-job-console.ipynb"),
            manifest["files"]["queue/ada-nest-job-console.ipynb"])
        # legacy copy purged
        self.assertFalse((remote / "queue/runner.py").exists())
        # second publish — unchanged -> no-op
        r2 = self.publish(repo, remote)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("nothing to publish", r2.stdout)

    def test_rollback_repoints(self):
        repo, remote, rel1 = self.full_publish()
        # commit a colab change -> new release
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        (repo / "scripts/colab/packs/tiny/pack.yml"
         ).write_text("name: tiny\n# v2\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "c2"],
                       check=True, capture_output=True, env=env)
        r = self.publish(repo, remote)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ptr2 = json.loads(
            (remote / "queue/ACTIVE_RELEASE.json").read_text())
        self.assertNotEqual(ptr2["release_id"], rel1)
        self.assertEqual(ptr2["previous"], rel1)
        # rollback: repoint at the first release
        r3 = self.publish(repo, remote, "--activate", rel1)
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        ptr3 = json.loads(
            (remote / "queue/ACTIVE_RELEASE.json").read_text())
        self.assertEqual(ptr3["release_id"], rel1)
        self.assertEqual(ptr3["previous"], ptr2["release_id"])

    def test_verify_subcommand(self):
        repo, remote, rel1 = self.full_publish()
        r = self.publish(repo, remote, "--verify", rel1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("verified", r.stdout)
        # tamper remotely -> verify fails
        (remote / "releases" / rel1 / "queue/JOBS.py"
         ).write_text("JOBS=[]\n")
        r = self.publish(repo, remote, "--verify", rel1)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
