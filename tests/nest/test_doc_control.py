"""Unit tests for scripts/nest/doc_control.py — the documentary
asset-identity / continuity control plane (ai-video-quality-control-plane).
No GPU, no network: exercises build/bibles/ledger/takes/verify/fixture on
tmp project dirs."""
import argparse
import importlib.util
import json
import tempfile
import unittest
import wave
from pathlib import Path

import yaml

MODULE = Path(__file__).parents[2] / "scripts" / "nest" / "doc_control.py"
SPEC = importlib.util.spec_from_file_location("doc_control", MODULE)
doc_control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doc_control)

SCRIPT = """
doc: test-doc
version: v1
status: draft
language_primary: th
narrator: tony-clone-vyncx
estimated_runtime_s: 6-8
shots:
  - shot: 1
    beat: board_the_ship
    object: earth
    characters: [kk]
    location: cockpit
    th: "สวัสดี"
    en: "Hello."
    est_s: 3
  - shot: 2
    beat: mars
    object: mars
    th: "ดาวอังคาร"
    en: "Mars."
    est_s: 4
"""

STORYBOARD = """
doc: test-doc
render:
  model: Lightricks/LTX-Video
  width: 640
  height: 384
  num_frames: 73
  steps: 40
  fps: 24
style_suffix: "cinematic documentary"
negative: "text, watermark"
qc:
  per_shot: [non-black-frames, duration-3.04s]
  regen_budget_per_shot: 2
shots:
  - shot: 1
    continuity: t2v
    prompt: "a ship cockpit window over Earth"
  - shot: 2
    continuity: i2v-from-shot-1
    prompt: "pull back to Mars"
"""

BIBLES = """
schema: nest-doc-bibles-v1
doc_id: test-doc
characters:
  - id: kk
    description: "young girl, symbolic non-identifying"
objects:
  - id: earth
    kind: planet
    facts: {diameter_km: 12756}
  - id: mars
    kind: planet
locations:
  - id: cockpit
    description: "small fictional tour ship cabin"
"""


def make_wav(path: Path, seconds: float, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)


def ledger_ns(extra, project):
    """extra = flag list -> append-mode namespace bound to project dir."""
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger_cmd")
    ap.add_argument("project", type=Path)
    ap.add_argument("--shot", type=int)
    ap.add_argument("--asset-id")
    ap.add_argument("--take")
    ap.add_argument("--event")
    ap.add_argument("--artifact")
    ap.add_argument("--qc-ok", action="store_true", default=None)
    ap.add_argument("--no-qc-ok", dest="qc_ok", action="store_false")
    ap.add_argument("--note")
    return ap.parse_args(["append", str(project)] + extra)


class DocControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc-control-"))
        self.proj = self.tmp / "project"
        (self.proj / "shots").mkdir(parents=True)
        (self.proj / "assets").mkdir()
        (self.proj / "qc").mkdir()
        (self.tmp / "in").mkdir()
        (self.tmp / "in" / "script.yml").write_text(SCRIPT)
        (self.tmp / "in" / "storyboard.yml").write_text(STORYBOARD)
        (self.proj / "assets" / "bibles.yml").write_text(BIBLES)
        self.manifest_path = self.proj / "shots" / "shot-manifest-v2.json"

    def build(self, vo_dir=None):
        args = argparse.Namespace(
            script=self.tmp / "in" / "script.yml",
            storyboard=self.tmp / "in" / "storyboard.yml",
            vo_dir=vo_dir, doc_id=None, out=self.manifest_path)
        self.assertEqual(doc_control.cmd_build(args), 0)
        return json.loads(self.manifest_path.read_text())

    def manifest(self):
        return json.loads(self.manifest_path.read_text())

    def append(self, shot, asset, take, event, artifact=None, qc_ok=None):
        extra = ["--shot", str(shot), "--asset-id", asset,
                 "--take", str(take), "--event", event]
        if artifact:
            extra += ["--artifact", artifact]
        if qc_ok is True:
            extra += ["--qc-ok"]
        elif qc_ok is False:
            extra += ["--no-qc-ok"]
        self.assertEqual(
            doc_control.cmd_ledger(ledger_ns(extra, self.proj)), 0)

    # ------------------------------------------------------------- build

    def test_build_manifest_schema_and_ids(self):
        m = self.build()
        self.assertEqual(m["schema"], doc_control.SCHEMA_MANIFEST)
        self.assertEqual(m["doc_id"], "test-doc")
        self.assertEqual([s["asset_id"] for s in m["shots"]],
                         ["test-doc-s01", "test-doc-s02"])
        s2 = m["shots"][1]
        self.assertEqual(s2["continuity"], "i2v-from-shot-1")
        self.assertEqual(s2["prev_shot"], 1)
        for k in ("pose", "depth", "scene", "camera", "scene_graph"):
            self.assertIsNone(s2["controls"][k])
        self.assertEqual(m["shots"][0]["vo"]["est_s"], 3)
        # slot = 73 frames / 24fps = 3.0416s
        self.assertAlmostEqual(m["shots"][0]["vo"]["effective_slot_s"],
                               73 / 24, places=3)

    def test_build_measures_scratch_vo(self):
        vo = self.tmp / "vo"
        make_wav(vo / "v3-vo-01.wav", 2.9)
        make_wav(vo / "v3-vo-02.wav", 4.6)
        m = self.build(vo_dir=vo)
        vo1 = m["shots"][0]["vo"]
        self.assertEqual(vo1["file"], "v3-vo-01.wav")
        self.assertAlmostEqual(vo1["measured_s"], 2.9, places=2)
        self.assertFalse(vo1["overrun"])
        # shot2: 4.6s measured vs 3.04s slot -> overrun beyond 15%
        self.assertTrue(m["shots"][1]["vo"]["overrun"])

    def test_vo_underrun_flag(self):
        vo = self.tmp / "vo"
        make_wav(vo / "v3-vo-01.wav", 0.2)
        m = self.build(vo_dir=vo)
        self.assertTrue(m["shots"][0]["vo"]["underrun"])

    # ------------------------------------------------------------ bibles

    def test_bibles_validate_ok_and_reject(self):
        ok = yaml.safe_load(BIBLES)
        self.assertEqual(doc_control.validate_bibles(ok, "test-doc"), [])
        bad = dict(ok)
        bad["schema"] = "wrong"
        self.assertTrue(doc_control.validate_bibles(bad))
        dup = dict(ok)
        dup["objects"] = ok["objects"] + [dict(ok["objects"][0])]
        self.assertTrue(any("duplicate" in e for e in
                            doc_control.validate_bibles(dup)))

    # ------------------------------------------------ ledger/takes/verify

    def test_ledger_takes_verify_roundtrip(self):
        self.build()
        self.append(1, "test-doc-s01", 1, "rendered",
                    artifact="qc/shots/s01-t1.mp4")
        self.append(1, "test-doc-s01", 1, "qc", qc_ok=True)
        self.append(1, "test-doc-s01", 1, "approved")
        self.append(2, "test-doc-s02", 1, "rendered",
                    artifact="qc/shots/s02-t1.mp4")

        takes = argparse.Namespace(project=self.proj)
        self.assertEqual(doc_control.cmd_takes(takes), 0)
        out = json.loads(
            (self.proj / "qc" / "approved-takes.json").read_text())
        self.assertEqual(out["schema"], doc_control.SCHEMA_TAKES)
        rows = {r["asset_id"]: r for r in out["shots"]}
        self.assertTrue(rows["test-doc-s01"]["approved"])
        self.assertEqual(rows["test-doc-s01"]["take"], 1)
        self.assertFalse(rows["test-doc-s02"]["approved"])

        ns = argparse.Namespace(project=self.proj,
                                require_artifacts=False)
        self.assertEqual(doc_control.cmd_verify(ns), 0)
        verdict = json.loads(
            (self.proj / "qc" / "control-verify.json").read_text())
        self.assertIn(verdict["verdict"], ("pass", "warn"))
        self.assertEqual(verdict["stage_coverage"]["pose"], "0/2")

        # break continuity: shot3 i2v link to a shot that does not exist
        m = self.manifest()
        m["shots"].append(dict(m["shots"][1], shot=3,
                               asset_id="test-doc-s03", prev_shot=9))
        self.manifest_path.write_text(json.dumps(m))
        self.assertEqual(doc_control.cmd_verify(ns), 1)

    def test_verify_fails_on_vo_overrun(self):
        vo = self.tmp / "vo"
        make_wav(vo / "v3-vo-01.wav", 2.9)
        make_wav(vo / "v3-vo-02.wav", 6.0)   # way over the 3.04s slot
        self.build(vo_dir=vo)
        ns = argparse.Namespace(project=self.proj,
                                require_artifacts=False)
        self.assertEqual(doc_control.cmd_verify(ns), 1)

    # ------------------------------------------------------------ fixture

    def test_fixture_grounded_in_manifest(self):
        self.build()
        ns = argparse.Namespace(project=self.proj)
        self.assertEqual(doc_control.cmd_fixture(ns), 0)
        fx = json.loads(
            (self.proj / "evals" / "test-doc-fixture-v1.json").read_text())
        self.assertEqual(fx["schema"], doc_control.SCHEMA_FIXTURE)
        self.assertEqual(fx["benchmarks"],
                         ["vbench", "t2v-compbench", "videoscore2"])
        self.assertEqual(len(fx["cases"]), 2)
        c1, c2 = fx["cases"]
        self.assertEqual(c1["scene_graph"]["objects"], ["earth"])
        self.assertEqual(c1["scene_graph"]["characters"], ["kk"])
        self.assertEqual(c1["scene_graph"]["location"], "cockpit")
        self.assertEqual(c1["scene_graph"]["facts"]["earth"],
                         {"diameter_km": 12756})
        self.assertEqual(c2["scene_graph"]["objects"], ["mars"])
        self.assertIn({"type": "continues_from", "shot": 1},
                      c2["scene_graph"]["relations"])


if __name__ == "__main__":
    unittest.main()
