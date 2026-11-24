"""Unit tests for the private PDF image inventory pack."""

import importlib.util
from pathlib import Path
import unittest

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / "scripts/colab/packs/kk-video-c9f99fee6146-pdf-image-audit"
          / "audit_pdf_images.py")
SPEC = importlib.util.spec_from_file_location("audit_pdf_images", SCRIPT)
audit_pdf_images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_pdf_images)
TEXT_DIFF_SCRIPT = (REPO / "scripts/colab/packs/"
                    "kk-video-c9f99fee6146-pdf-text-diff/diff_pdf_text.py")
TEXT_DIFF_SPEC = importlib.util.spec_from_file_location(
    "diff_pdf_text", TEXT_DIFF_SCRIPT)
diff_pdf_text = importlib.util.module_from_spec(TEXT_DIFF_SPEC)
TEXT_DIFF_SPEC.loader.exec_module(diff_pdf_text)


class PdfImageAuditTest(unittest.TestCase):
    def test_audit_pack_is_cpu_only_and_private(self):
        pack_path = (REPO / "scripts/colab/packs/"
                     "kk-video-c9f99fee6146-pdf-image-audit/pack.yml")
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        self.assertEqual(pack["needs"]["gpu_gb"], 0)
        self.assertNotIn("publish", pack)
        self.assertIn("projects/kk-video-c9f99fee6146/source/", pack["fetch"])
        self.assertIn("kk-video-c9f99fee6146-r4-preflight",
                      pack["requires"])

    def test_preview_waits_for_audit_and_visual_approval(self):
        pack_path = (REPO / "scripts/colab/packs/"
                     "kk-video-c9f99fee6146-preview/pack.yml")
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        self.assertIn("kk-video-c9f99fee6146-pdf-image-audit",
                      pack["requires"])
        self.assertIn("kk-video-c9f99fee6146-source-image-use-approved",
                      pack["requires"])

    def test_r4_preflight_rehashes_sources_and_validates_audit_pack(self):
        policy_path = (REPO / "scripts/colab/packs/"
                       "kk-video-c9f99fee6146-r4-preflight/policy.yml")
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        self.assertTrue(policy["source_required"])
        self.assertIn("kk-video-c9f99fee6146-pdf-image-audit",
                      policy["packs"])

    def test_text_diff_pack_is_cpu_only_and_private(self):
        pack_path = (REPO / "scripts/colab/packs/"
                     "kk-video-c9f99fee6146-pdf-text-diff/pack.yml")
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        self.assertEqual(pack["needs"]["gpu_gb"], 0)
        self.assertNotIn("publish", pack)
        self.assertIn("kk-video-c9f99fee6146-pdf-image-audit",
                      pack["requires"])

    def test_image_condition_probe_is_single_private_shot(self):
        pack_path = (REPO / "scripts/colab/packs/"
                     "kk-video-c9f99fee6146-image-conditioning-probe/pack.yml")
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        self.assertEqual(pack["needs"]["gpu_gb"], 14)
        self.assertNotIn("publish", pack)
        self.assertIn("kk-video-c9f99fee6146-pdf-image-audit",
                      pack["requires"])
        self.assertEqual(len(pack["artifacts"]), 3)

    def test_parse_page_count(self):
        self.assertEqual(
            audit_pdf_images.parse_pdf_pages(
                "Title: Private source\nPages: 40\nPage size: 612 x 792 pts"),
            40)

    def test_parse_image_rows_ignores_headers_and_tracks_pages(self):
        listing = """page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
1 0 image 800 600 rgb 3 8 jpeg no 10 0 96 96 25K 1.8%
1 1 smask 800 600 gray 1 8 image no 11 0 96 96 5K 1.1%
3 0 image 1200 900 rgb 3 8 jpeg no 22 0 144 144 42K 2.2%
"""
        rows = audit_pdf_images.parse_image_rows(listing)
        self.assertEqual([(r["page"], r["type"]) for r in rows],
                         [(1, "image"), (1, "smask"), (3, "image")])
        self.assertEqual((rows[0]["width"], rows[0]["height"]), (800, 600))

    def test_parse_page_count_requires_metadata(self):
        with self.assertRaises(ValueError):
            audit_pdf_images.parse_pdf_pages("no page metadata")

    def test_text_fingerprints_are_page_scoped_and_normalized(self):
        pages = audit_pdf_images.text_page_fingerprints(
            "first   page\fsecond\npage\f", 2)
        self.assertEqual([p["page"] for p in pages], [1, 2])
        self.assertEqual([p["chars"] for p in pages], [10, 11])
        self.assertNotEqual(pages[0]["sha256"], pages[1]["sha256"])

    def test_text_diff_normalizes_formfeeds_and_whitespace(self):
        self.assertEqual(
            diff_pdf_text.normalize_text("first   page\fsecond\npage"),
            ["first page", "second", "page"])


if __name__ == "__main__":
    unittest.main()
