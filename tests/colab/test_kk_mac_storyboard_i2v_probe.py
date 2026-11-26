import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


REPO = Path(__file__).resolve().parents[2]
PACK_DIR = (REPO / "scripts/colab/packs/"
            "kk-mac-storyboard-i2v-probe-20261029")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KkMacStoryboardI2VProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_module("kk_mac_storyboard_i2v", PACK_DIR / "run_probe.py")

    def test_pack_is_single_offline_private_mps_probe(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(pack["needs"]["ram_gb"], 30)
        self.assertEqual(pack["needs"]["disk_gb"], 10)
        self.assertNotIn("gpu_gb", pack["needs"])
        self.assertIn("HF_HUB_OFFLINE=1", pack["run_sh"])
        self.assertIn("memory_pressure", pack["prep"])
        self.assertIn("ollama ps", pack["prep"])
        self.assertIn("^(ffmpeg|mlx|resolve|", pack["prep"])
        self.assertNotIn("ollama|", pack["prep"])
        self.assertNotIn("publish", pack)
        self.assertNotIn("qwen", pack["run_sh"].lower())

    def test_input_verifier_binds_image_and_page_to_v1_01_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            embed = root / "shot01.pt"
            image = root / "image-006.jpg"
            audit_path = root / "audit.json"
            embed.write_bytes(b"embedding")
            image.write_bytes(b"page nine image")
            rows = [{"page": p} for p in
                    [2, 2, 3, 4, 5, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39]]
            files = [
                {
                    "path": f"v1_01/images/image-{index:03d}.jpg",
                    "bytes": image.stat().st_size if index == 6 else 1,
                    "sha256": (
                        self.probe.IMAGE_SHA256
                        if index == 6 else str(index).zfill(64)),
                }
                for index in range(17)
            ]
            audit_path.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": self.probe.SOURCE_SHA256,
                    "image_rows": rows,
                    "extracted_files": files,
                }]
            }))

            def fake_hash(path):
                if path == embed:
                    return self.probe.EMBED_SHA256
                if path == image:
                    return self.probe.IMAGE_SHA256
                return hashlib.sha256(path.read_bytes()).hexdigest()

            with patch.object(self.probe, "sha256", side_effect=fake_hash):
                result = self.probe.verify_inputs(embed, image, audit_path)
            self.assertEqual(result["page"], 9)
            self.assertEqual(result["image"], "image-006.jpg")

            rows[6]["page"] = 8
            audit_path.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": self.probe.SOURCE_SHA256,
                    "image_rows": rows,
                    "extracted_files": files,
                }]
            }))
            with patch.object(self.probe, "sha256", side_effect=fake_hash):
                with self.assertRaisesRegex(ValueError, "not the approved page-9"):
                    self.probe.verify_inputs(embed, image, audit_path)


if __name__ == "__main__":
    unittest.main()
