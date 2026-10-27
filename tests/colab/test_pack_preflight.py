"""Tests for the KK video release preflight stage
(card kk-video-preflight-stage).

Covers:
  - pack-preflight validator: every check family, verdict semantics,
    deterministic + idempotent output, release/pack hash reference
  - the real kk-video release (repo packs + real policy.yml) validating
    clean against a synthetic project fixture
  - pack-dir validator copy kept byte-identical to the canonical script
  - nest-worker requires_unmet() claim-gate matrix
  - end-to-end: real scripts/colab/queue-runner.py in a sandbox nest —
    preflight-first ordering, pass lets dependents claim, fail blocks them
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
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "scripts/colab/pack-preflight.py"
PACK_DIR = (REPO / "scripts/colab/packs"
            / "kk-video-c9f99fee6146-preflight")
PACK_VALIDATOR = PACK_DIR / "pack-preflight.py"
POLICY = PACK_DIR / "policy.yml"
REPO_PACKS = REPO / "scripts/colab/packs"
RUNNER = REPO / "scripts/colab/queue-runner.py"
NEST_WORKER = REPO / "scripts/ada/nest-worker.py"
NEST_SUBMIT = REPO / "scripts/ada/nest-pack-submit.py"

NVIDIA_SMI_STUB = """#!/bin/bash
case "$*" in
  *"memory.total"*) echo "15360" ;;
  *) echo "0" ;;
esac
exit 0
"""


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PF = load_module(VALIDATOR, "pack_preflight")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_project(root: Path, source_bytes=b"PDF-BYTES", pid=None,
                 declare_sha=None, materialize_source=True) -> dict:
    """A minimal but valid kk-video project fixture. Default: project_id
    embeds the real source sha prefix so the provenance binding holds.
    For a fixed project_id, declare_sha carries the manifest hash and the
    source binary can be left unmaterialized (warn path)."""
    proj = root / "project"
    sha = _sha(source_bytes)
    pid = pid or f"kk-video-{sha[:12]}"
    for d in ("source", "brief", "story", "shots", "assets", "qc",
              "packs"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    if materialize_source:
        (proj / "source" / "src.pdf").write_bytes(source_bytes)
    (proj / "project.json").write_text(json.dumps({
        "project_id": pid,
        "status": "preview_batch_ready",
        "sources": [{"filename": "src.pdf",
                     "sha256": declare_sha or sha,
                     "bytes": len(source_bytes)}],
        "card_id": pid,
    }, indent=1))
    (proj / "brief" / "creative-brief.md").write_text(
        "# brief\n" + "Sacred Father teaser. " * 20 + "\n")
    (proj / "story" / "scene-plan.md").write_text(
        "# scenes\n- scene 1 [fact] real memory of the father\n"
        "- scene 2 [dream] river sequence\n"
        + "padding line. " * 20 + "\n")
    (proj / "shots" / "prompt-pack-v1.md").write_text(
        "# prompts\nshot 1 (fact): warm kitchen\n"
        "shot 2 (dream): floating house\n" + "x " * 120 + "\n")
    (proj / "assets" / "rights-matrix.md").write_text(
        "# rights\nidentity policy: symbolic non-identifying characters; "
        "real likeness only where explicitly approved.\n")
    (proj / "qc" / "preflight.md").write_text(
        "# qc\nThai narration voice th-TH-PremwadeeNeural; "
        "Thai subtitles teaser.th.srt + English subtitles teaser.en.srt\n")
    (proj / "packs" / "preview-plan.yml").write_text(
        "plan: private teaser 60-90s\nnarration: Thai voice\n"
        "subtitles: [th, en]\n")
    return {"dir": proj, "sha": sha, "pid": pid}


def make_policy(root: Path, pid: str, pack_names=()) -> Path:
    p = root / "policy.yml"
    lines = [f"project_id: {pid}", "source_required: false",
             "required_files:",
             "  - {path: brief/creative-brief.md, min_bytes: 50}",
             "  - {path: story/scene-plan.md, min_bytes: 50}",
             "  - {path: shots/prompt-pack-v1.md, min_bytes: 50}",
             "  - {path: assets/rights-matrix.md, min_bytes: 20}",
             "  - {path: qc/preflight.md, min_bytes: 20}",
             "fact_dream:",
             "  files: [story/scene-plan.md]",
             "  require_labels: [fact, dream]",
             "identity:",
             "  evidence_files: [assets/rights-matrix.md]",
             "  required_terms: [symbolic]",
             "  allowed_values: [symbolic, mixed]",
             "  manifest_keys: [identity_policy, likeness_policy]",
             "audio:",
             "  evidence_files: [qc/preflight.md]",
             "  narration_re: '(?i)thai.{0,80}narrat|th-TH'",
             "  subtitle_res:",
             "    th: '(?i)\\bth(ai)?\\b.{0,60}(subtitle|srt|caption)'",
             "    en: '(?i)\\ben(glish)?\\b.{0,60}(subtitle|srt|caption)'",
             "packs:"]
    lines += [f"  - {n}" for n in pack_names] or ["  []"]
    p.write_text("\n".join(lines) + "\n")
    return p


def make_pack(packs_dir: Path, name: str, body: str | None = None) -> Path:
    d = packs_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pack.yml").write_text(
        body or (
            f"name: {name}\n"
            "needs:\n  gpu_gb: 0\n  disk_gb: 2\n  egress_only_ok: true\n"
            "timeout_s: 120\n"
            f"artifacts:\n  - packs/{name}/out.txt\n"
            "run: |\n  open(f'{PACK_DIR}/out.txt','w').write('ok')\n"))
    return d


class ValidatorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pack-preflight-"))
        self.proj = make_project(self.tmp)
        self.packs = self.tmp / "packs"
        self.packs.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pf(self, project_dir=None, pack_names=(), policy=None):
        policy = policy or make_policy(
            self.tmp, self.proj["pid"], pack_names)
        return PF.run_preflight(str(policy),
                                str(project_dir if project_dir is not None
                                    else self.proj["dir"]),
                                str(self.packs))

    def verdict(self, report, cid):
        c = next((x for x in report["checks"] if x["id"] == cid), None)
        return c["status"] if c else None

    # -- project-side checks -------------------------------------------

    def test_happy_path_passes_and_is_deterministic(self):
        make_pack(self.packs, "aa-pack")
        policy = make_policy(self.tmp, self.proj["pid"], ["aa-pack"])
        r1 = PF.run_preflight(str(policy), str(self.proj["dir"]),
                              str(self.packs))
        r2 = PF.run_preflight(str(policy), str(self.proj["dir"]),
                              str(self.packs))
        self.assertEqual(r1["verdict"], "pass")
        self.assertEqual(json.dumps(r1, sort_keys=True),
                         json.dumps(r2, sort_keys=True))
        self.assertIn("aa-pack", r1["packs"])
        self.assertRegex(r1["packs"]["aa-pack"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(r1["release_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("project.json", r1["inputs_sha256"])

    def test_cli_writes_artifacts_and_exit_codes(self):
        make_pack(self.packs, "aa-pack")
        policy = make_policy(self.tmp, self.proj["pid"], ["aa-pack"])
        rc = PF.main(["--policy", str(policy),
                      "--project", str(self.proj["dir"]),
                      "--packs", str(self.packs), "--out", str(self.out)])
        self.assertEqual(rc, 0)
        j1 = (self.out / "preflight.json").read_bytes()
        m1 = (self.out / "preflight.md").read_text()
        self.assertIn("PASS", m1)
        rc = PF.main(["--policy", str(policy),
                      "--project", str(self.proj["dir"]),
                      "--packs", str(self.packs), "--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertEqual(j1, (self.out / "preflight.json").read_bytes(),
                         "idempotent re-run must be byte-identical")

    def test_missing_project_dir_fails(self):
        r = self.run_pf(project_dir=self.tmp / "nope")
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(self.verdict(r, "project_manifest"), "fail")
        for cid in ("planning_files", "fact_dream_labels",
                    "identity_policy", "audio_subtitle_decision"):
            self.assertEqual(self.verdict(r, cid), "fail")

    def test_source_hash_binding_fails_on_wrong_suffix(self):
        # a source list that does not contain the project-id's sha12
        manifest_path = self.proj["dir"] / "project.json"
        m = json.loads(manifest_path.read_text())
        m["sources"][0]["sha256"] = "f" * 64
        manifest_path.write_text(json.dumps(m))
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "source_provenance"), "fail")

    def test_materialized_source_mismatch_fails(self):
        (self.proj["dir"] / "source" / "src.pdf").write_bytes(b"tampered")
        r = self.run_pf()
        self.assertEqual(r["verdict"], "fail")
        self.assertIn("mismatch", next(
            c["detail"] for c in r["checks"]
            if c["id"] == "source_provenance"))

    def test_unmaterialized_source_warns_not_fails(self):
        shutil.rmtree(self.proj["dir"] / "source")
        r = self.run_pf()
        self.assertEqual(r["verdict"], "warn")   # hash binding still held
        self.assertEqual(self.verdict(r, "source_provenance"), "warn")

    def test_missing_planning_file_fails(self):
        (self.proj["dir"] / "assets" / "rights-matrix.md").unlink()
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "planning_files"), "fail")
        self.assertEqual(self.verdict(r, "identity_policy"), "fail")

    def test_missing_dream_label_fails(self):
        p = self.proj["dir"] / "story" / "scene-plan.md"
        p.write_text("# scenes\n- scene 1 [fact] real memory\n"
                     "- scene 2 [note] river sequence\n")
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "fact_dream_labels"), "fail")

    def test_missing_symbolic_term_fails(self):
        p = self.proj["dir"] / "assets" / "rights-matrix.md"
        p.write_text(p.read_text().replace("symbolic", "stylised"))
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "identity_policy"), "fail")

    def test_manifest_identity_value_outside_allowed_fails(self):
        mp = self.proj["dir"] / "project.json"
        m = json.loads(mp.read_text())
        m["identity_policy"] = "full real likeness for everyone"
        mp.write_text(json.dumps(m))
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "identity_policy"), "fail")

    def test_missing_english_subtitle_evidence_fails(self):
        (self.proj["dir"] / "qc" / "preflight.md").write_text(
            "# qc\nThai narration voice th-TH; Thai subtitles "
            "teaser.th.srt only\n")
        r = self.run_pf()
        self.assertEqual(self.verdict(r, "audio_subtitle_decision"),
                         "fail")

    # -- pack-side checks ----------------------------------------------

    def test_pack_syntax_both_run_fields_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [packs/aa-pack/o.txt]\n"
                  "run: 'print(1)'\nrun_sh: 'echo hi'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:syntax"), "fail")

    def test_needs_undeclared_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0}\n"
                  "artifacts: [packs/aa-pack/o.txt]\nrun: 'print(1)'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:needs"), "fail")

    def test_artifact_glob_outside_prefix_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [public/aa-pack/o.txt]\n"
                  "run: 'print(1)'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:artifacts"),
                         "fail")

    def test_artifact_glob_into_other_pack_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [packs/other-pack/o.txt]\n"
                  "run: 'print(1)'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:artifacts"),
                         "fail")

    def test_publish_dest_banned_prefix_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [packs/aa-pack/o.txt]\n"
                  "publish: {out: www/public/aa}\nrun: 'print(1)'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:output_privacy"),
                         "fail")

    def test_banned_public_publish_token_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [packs/aa-pack/o.txt]\n"
                  "run: 'youtube_upload(\"out.mp4\")'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:banned_flags"),
                         "fail")

    def test_banned_paid_key_fails(self):
        make_pack(self.packs, "aa-pack",
                  "name: aa-pack\nneeds: {gpu_gb: 0, disk_gb: 2}\n"
                  "timeout_s: 60\nartifacts: [packs/aa-pack/o.txt]\n"
                  "paid: true\nrun: 'print(1)'\n")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:banned_flags"),
                         "fail")

    def test_banned_token_in_project_plan_fails(self):
        (self.proj["dir"] / "packs" / "preview-plan.yml").write_text(
            "plan: teaser\nupload: youtube\n")
        make_pack(self.packs, "aa-pack")
        r = self.run_pf(pack_names=["aa-pack"])
        self.assertEqual(self.verdict(r, "pack:aa-pack:banned_flags"),
                         "fail")

    def test_missing_declared_pack_fails(self):
        r = self.run_pf(pack_names=["ghost-pack"])
        self.assertEqual(self.verdict(r, "pack:ghost-pack:syntax"),
                         "fail")
        self.assertEqual(r["packs"]["ghost-pack"]["sha256"], None)

    def test_release_hash_changes_with_pack_content(self):
        make_pack(self.packs, "aa-pack")
        policy = make_policy(self.tmp, self.proj["pid"], ["aa-pack"])
        r1 = PF.run_preflight(str(policy), str(self.proj["dir"]),
                              str(self.packs))
        with open(self.packs / "aa-pack" / "pack.yml", "a") as f:
            f.write("# touched\n")
        r2 = PF.run_preflight(str(policy), str(self.proj["dir"]),
                              str(self.packs))
        self.assertNotEqual(r1["packs"]["aa-pack"]["sha256"],
                            r2["packs"]["aa-pack"]["sha256"])
        self.assertNotEqual(r1["release_sha256"], r2["release_sha256"])


class TestRealRelease(unittest.TestCase):
    """The real repo packs under the real policy — must validate clean."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pack-preflight-real-"))
        # real policy's project_id — declared source sha binds the id's
        # suffix; binary left unmaterialized (warn, not fail)
        self.proj = make_project(
            self.tmp, pid="kk-video-c9f99fee6146",
            declare_sha="c9f99fee6146" + "0" * 52,
            materialize_source=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repo_packs_pass_real_policy(self):
        report = PF.run_preflight(
            str(POLICY), str(self.proj["dir"]), str(REPO_PACKS))
        fails = [c for c in report["checks"] if c["status"] == "fail"]
        self.assertEqual(fails, [],
                         "real release must pass: "
                         + json.dumps(fails, indent=1))
        self.assertIn(report["verdict"], ("pass", "warn"))
        for name in ("kk-video-c9f99fee6146-embeds",
                     "kk-video-c9f99fee6146-preview",
                     "kk-video-c9f99fee6146-preflight"):
            self.assertRegex(report["packs"][name]["sha256"],
                             r"^[0-9a-f]{64}$", name)

    def test_pack_validator_copy_is_byte_identical(self):
        self.assertEqual(hashlib.sha256(VALIDATOR.read_bytes()).hexdigest(),
                         hashlib.sha256(
                             PACK_VALIDATOR.read_bytes()).hexdigest(),
                         "pack copy drifted from canonical "
                         "scripts/colab/pack-preflight.py — re-cp it")

    def test_real_pack_requires_point_at_preflight(self):
        import yaml
        for name in ("kk-video-c9f99fee6146-embeds",
                     "kk-video-c9f99fee6146-preview"):
            spec = yaml.safe_load(
                (REPO_PACKS / name / "pack.yml").read_text())
            self.assertIn("kk-video-c9f99fee6146-preflight",
                          spec.get("requires") or [], name)

    def test_submit_validator_accepts_new_fields(self):
        import yaml
        sub = load_module(NEST_SUBMIT, "nest_pack_submit")
        for name in ("kk-video-c9f99fee6146-preflight",
                     "kk-video-c9f99fee6146-embeds",
                     "kk-video-c9f99fee6146-preview"):
            spec = yaml.safe_load(
                (REPO_PACKS / name / "pack.yml").read_text())
            errs = sub.validate(spec, name)
            self.assertEqual(errs, [], f"{name}: {errs}")


class TestNestWorkerGate(unittest.TestCase):
    def setUp(self):
        self.nw = load_module(NEST_WORKER, "nest_worker_it")

    def gate(self, spec, entries, files):
        self.nw.lsf = lambda p: entries.get(p.rsplit('/', 1)[-1], [])
        self.nw.cat = lambda p: files.get(p, "")
        return self.nw.requires_unmet(spec, "remote")

    def test_requirement_not_done_blocks(self):
        self.assertIn("not done", self.gate(
            {"requires": ["zz-preflight"]},
            {"zz-preflight": ["pack.yml"]}, {}))

    def test_preflight_fail_verdict_blocks(self):
        self.assertIn("verdict", self.gate(
            {"requires": ["zz-preflight"]},
            {"zz-preflight": ["done", "preflight.json"]},
            {"remote/packs/zz-preflight/preflight.json":
             '{"verdict": "fail"}'}))

    def test_preflight_pass_unblocks(self):
        self.assertEqual("", self.gate(
            {"requires": ["zz-preflight"]},
            {"zz-preflight": ["done", "preflight.json"]},
            {"remote/packs/zz-preflight/preflight.json":
             '{"verdict": "pass"}'}))

    def test_preflight_done_but_verdict_missing_blocks(self):
        self.assertIn("missing", self.gate(
            {"requires": ["zz-preflight"]},
            {"zz-preflight": ["done"]}, {}))

    def test_plain_requirement_needs_done_only(self):
        self.assertEqual("", self.gate(
            {"requires": ["aa-embeds"]},
            {"aa-embeds": ["done"]}, {}))

    def test_no_requires_is_open(self):
        self.assertEqual("", self.gate({}, {}, {}))


class TestRunnerGateE2E(unittest.TestCase):
    """Real queue-runner.py against a sandbox nest."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nest-gate-"))
        self.root = self.tmp / "ada-nest"
        self.q = self.root / "queue"
        (self.root / "packs").mkdir(parents=True)
        self.q.mkdir()
        (self.q / "JOBS.py").write_text("JOBS = []\n")
        self.old_env = {k: os.environ.get(k)
                        for k in ("NEST_ROOT", "NEST_QUEUE",
                                  "NEST_QUEUE_SETTLE_S", "PATH")}
        os.environ["NEST_ROOT"] = str(self.root)
        os.environ["NEST_QUEUE"] = str(self.q)
        os.environ["NEST_QUEUE_SETTLE_S"] = "0.2"
        bindir = self.tmp / "bin"
        bindir.mkdir()
        smi = bindir / "nvidia-smi"
        smi.write_text(NVIDIA_SMI_STUB)
        smi.chmod(smi.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                  | stat.S_IXOTH)
        os.environ["PATH"] = f"{bindir}:{os.environ['PATH']}"

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_pack(self, name, requires=None, verdict=None, fail=False):
        d = self.root / "packs" / name
        d.mkdir(parents=True)
        reqs = ("requires:\n" + "".join(f"  - {r}\n" for r in requires)
                if requires else "")
        if verdict is not None:
            run = ("run: |\n  import os, json\n"
                   "  json.dump({'verdict': '%s'}, "
                   "open(f'{PACK_DIR}/preflight.json','w'))\n"
                   % verdict)
            if fail:
                run += "  raise RuntimeError('preflight failed')\n"
            arts = f"  - packs/{name}/preflight.json\n"
        else:
            run = ("run: |\n  open(f'{PACK_DIR}/out.txt','w')"
                   ".write('ok\\n')\n")
            arts = f"  - packs/{name}/out.txt\n"
        (d / "pack.yml").write_text(
            f"name: {name}\n{reqs}"
            "needs:\n  egress_only_ok: true\n"
            "timeout_s: 60\n"
            f"artifacts:\n{arts}{run}")

    def run_queue(self):
        proc = subprocess.run(
            [sys.executable, "-u", str(RUNNER)],
            capture_output=True, text=True, timeout=180,
            env=dict(os.environ))
        return proc.returncode, proc.stdout + proc.stderr

    def test_pass_preflight_orders_before_dependents(self):
        # names chosen so alphabetical order is the WRONG order —
        # only requires-aware ordering lets both drain in one launch
        self.write_pack("aa-video", requires=["zz-preflight"])
        self.write_pack("zz-preflight", verdict="pass")
        rc, out = self.run_queue()
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "packs" / "zz-preflight" / "done")
                        .exists(), out)
        self.assertTrue((self.root / "packs" / "aa-video" / "done")
                        .exists(), out)

    def test_failed_preflight_blocks_dependents(self):
        self.write_pack("aa-video", requires=["zz-preflight"])
        self.write_pack("zz-preflight", verdict="fail", fail=True)
        rc, out = self.run_queue()
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / "packs" / "zz-preflight" / "done")
                         .exists())
        self.assertFalse((self.root / "packs" / "aa-video" / "done")
                         .exists())
        claim_dir = self.root / "packs" / "aa-video" / "claim"
        self.assertFalse(claim_dir.exists() and any(claim_dir.iterdir()),
                         "blocked pack must never take a claim")
        self.assertIn("requires unmet", out)
        self.assertIn("PREFLIGHT", out.upper())

    def test_done_preflight_fail_verdict_still_blocks(self):
        # a stale done marker + fail verdict must not unblock dependents
        pf = self.root / "packs" / "zz-preflight"
        pf.mkdir(parents=True)
        (pf / "pack.yml").write_text("name: zz-preflight\n")
        (pf / "done").write_text("old\n")
        (pf / "preflight.json").write_text('{"verdict": "fail"}')
        self.write_pack("aa-video", requires=["zz-preflight"])
        rc, out = self.run_queue()
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / "packs" / "aa-video" / "done")
                         .exists())
        self.assertIn("requires unmet", out)

    def test_missing_requirement_skips_cleanly(self):
        self.write_pack("aa-video", requires=["ghost-pack"])
        rc, out = self.run_queue()
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / "packs" / "aa-video" / "done")
                         .exists())
        self.assertIn("requires ghost-pack: not done", out)

    def test_existing_done_requirement_unblocks(self):
        dep = self.root / "packs" / "dep-embeds"
        dep.mkdir(parents=True)
        (dep / "pack.yml").write_text("name: dep-embeds\n")
        (dep / "done").write_text("earlier\n")
        self.write_pack("aa-video", requires=["dep-embeds"])
        rc, out = self.run_queue()
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "packs" / "aa-video" / "done")
                        .exists(), out)


if __name__ == "__main__":
    unittest.main()
