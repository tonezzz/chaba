"""devnest_capacity_broker — normalized spec envelope (OPS-1002).

The shared capacity loop promises a full normalized envelope
(task_id/task_class/evidence/lane/model/expect/artifact/timeout/
fallback). Pinned: validation rules and defaults; no remote access —
normalize_spec is pure.
"""
from __future__ import annotations

import unittest

from scripts.devnest import devnest_capacity_broker as db


def base(**over):
    spec = {
        "task_id": "report-review-aaa111bbb222",
        "lane": "kk_mac_local",
        "task_class": "summary",
        "prompt": "Summarize. Source: reports/x.md",
    }
    spec.update(over)
    return spec


FN = "report-review-aaa111bbb222.json"


class NormalizeTests(unittest.TestCase):
    def test_valid_spec_fills_defaults(self):
        out = db.normalize_spec(base(), FN)
        self.assertEqual(out["model"], "qwen3:8b")
        self.assertEqual(out["expect"], {})
        self.assertEqual(out["timeout_s"], 600)
        self.assertEqual(out["fallback"], {"lane": "jevteam_hold"})
        self.assertIsNone(out["evidence"])
        self.assertIsNone(out["artifact"])

    def test_full_envelope_preserved(self):
        spec = base(evidence="reports/x.md",
                    expect={"facts": ["Omen"]},
                    artifact="reports/out.json",
                    timeout_s=300,
                    fallback="opencode_free")
        out = db.normalize_spec(spec, FN)
        self.assertEqual(out["evidence"], "reports/x.md")
        self.assertEqual(out["expect"], {"facts": ["Omen"]})
        self.assertEqual(out["artifact"], "reports/out.json")
        self.assertEqual(out["timeout_s"], 300)
        self.assertEqual(out["fallback"], "opencode_free")

    def test_filename_stem_must_match_task_id(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(), "other-name.json")

    def test_bad_lane_rejected(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(lane="shell"), FN)

    def test_unadmitted_kk_class_rejected(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(task_class="repo_mutation"), FN)

    def test_missing_task_class_rejected(self):
        spec = base()
        del spec["task_class"]
        with self.assertRaises(ValueError):
            db.normalize_spec(spec, FN)

    def test_evidence_or_prompt_required(self):
        spec = base()
        del spec["prompt"]
        with self.assertRaises(ValueError):
            db.normalize_spec(spec, FN)
        # evidence alone satisfies the envelope for colab lane
        spec = base(lane="colab", task_class="finite_eval")
        del spec["prompt"]
        spec["evidence"] = "evals/fixtures/x"
        spec["pack_source"] = "scripts/colab/packs/x"
        out = db.normalize_spec(spec, FN)
        self.assertEqual(out["evidence"], "evals/fixtures/x")

    def test_prompt_bound_for_kk(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(prompt="x" * 6001), FN)

    def test_artifact_root_gate(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(artifact="scripts/evil.py"), FN)
        with self.assertRaises(ValueError):
            db.normalize_spec(base(artifact="../out"), FN)
        out = db.normalize_spec(
            base(artifact="evals/kk-mac-lane/out/r.json"), FN)
        self.assertEqual(out["artifact"],
                         "evals/kk-mac-lane/out/r.json")

    def test_timeout_bounds(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(timeout_s=0), FN)
        with self.assertRaises(ValueError):
            db.normalize_spec(base(timeout_s=99999), FN)
        with self.assertRaises(ValueError):
            db.normalize_spec(base(timeout_s="soon"), FN)

    def test_fallback_type(self):
        with self.assertRaises(ValueError):
            db.normalize_spec(base(fallback=42), FN)


if __name__ == "__main__":
    unittest.main()
