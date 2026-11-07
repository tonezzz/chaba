import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
PACK_DIR = (REPO / "scripts/colab/packs/"
            "kk-video-c9f99fee6146-preview-v2")
SOURCE_SHA256 = "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KkVideoPreviewV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.render = load_module("kk_preview_v2", PACK_DIR / "run_preview_v2.py")
        cls.narration = load_module(
            "kk_narration_v2", PACK_DIR / "run_narration_v2.py")

    def test_pack_is_private_versioned_and_has_correct_prerequisites(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(pack["name"], "kk-video-c9f99fee6146-preview-v2")
        self.assertIn("kk-video-c9f99fee6146-source-image-use-approved",
                      pack["requires"])
        self.assertIn("kk-video-c9f99fee6146-voice-clone-probe",
                      pack["requires"])
        self.assertNotIn("publish", pack)
        self.assertNotIn("edge-tts", pack["prep"])
        self.assertEqual(pack["needs"]["gpu_gb"], 14)

    def test_scene_map_has_ten_ordered_storyboard_assignments(self):
        scene_map = yaml.safe_load(
            (PACK_DIR / "inputs/scene-map.yml").read_text())
        self.assertEqual(scene_map["source"]["sha256"], SOURCE_SHA256)
        self.assertEqual(
            [(item["shot"], item["storyboard_page"], item["storyboard_image"])
             for item in scene_map["shots"]],
            [(index, page, f"image-{index + 5:03d}")
             for index, page in enumerate(
                 [9, 12, 15, 18, 21, 24, 27, 30, 33, 36], start=1)])

    def test_resolve_images_binds_page_and_hash_to_audit(self):
        pages = [2, 2, 3, 4, 5, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39]
        scene_map = yaml.safe_load(
            (PACK_DIR / "inputs/scene-map.yml").read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image_dir = root / "v1_01/images"
            image_dir.mkdir(parents=True)
            records, rows = [], []
            for index, page in enumerate(pages):
                content = f"audited image {index}".encode()
                image = image_dir / f"image-{index:03d}.jpg"
                image.write_bytes(content)
                records.append({
                    "path": f"v1_01/images/{image.name}",
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                })
                rows.append({"page": page})
            audit = root / "audit.json"
            audit.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": SOURCE_SHA256,
                    "image_rows": rows,
                    "extracted_files": records,
                }]
            }))
            resolved = self.render.resolve_images(root, scene_map, audit)
            self.assertEqual(len(resolved), 10)
            self.assertEqual([item["page"] for item in resolved], pages[6:16])

            records[6]["sha256"] = "0" * 64
            audit.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": SOURCE_SHA256,
                    "image_rows": rows,
                    "extracted_files": records,
                }]
            }))
            with self.assertRaisesRegex(ValueError, "hash/size verification"):
                self.render.resolve_images(root, scene_map, audit)

    def test_narration_requires_four_contiguous_fifteen_second_cues(self):
        with tempfile.TemporaryDirectory() as temp:
            srt = Path(temp) / "narration.srt"
            blocks = [
                f"{index}\n00:00:{(index - 1) * 15:02d},000 --> "
                f"00:00:{index * 15:02d},000\nThai cue {index}"
                for index in range(1, 5)
            ]
            srt.write_text("\n\n".join(blocks), encoding="utf-8")
            cues = self.narration.parse_cues(srt)
            self.assertEqual(len(cues), 4)
            self.assertEqual([cue["start"] for cue in cues], [0, 15, 30, 45])

            srt.write_text("\n\n".join(blocks[:3]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected four"):
                self.narration.parse_cues(srt)


if __name__ == "__main__":
    unittest.main()
