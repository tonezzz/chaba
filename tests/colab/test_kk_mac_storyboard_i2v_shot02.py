import ast
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
PACK_DIR = (REPO / "scripts/colab/packs/"
            "kk-mac-storyboard-i2v-shot02-20261030")


class KkMacStoryboardI2VShot02Test(unittest.TestCase):
    def test_pack_is_private_offline_and_waits_for_shot01(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(
            pack["requires"],
            ["kk-mac-storyboard-i2v-probe-20261029",
             "kk-mac-storyboard-i2v-fullshot01-20261030"])
        self.assertEqual(pack["needs"]["ram_gb"], 30)
        self.assertEqual(pack["needs"]["disk_gb"], 10)
        self.assertIn("HF_HUB_OFFLINE=1", pack["run_sh"])
        self.assertIn("memory_pressure", pack["prep"])
        self.assertIn("ollama ps", pack["prep"])
        self.assertNotIn("publish", pack)

    def test_scene_map_is_bound_to_page12_and_shot02_inputs(self):
        mapping = yaml.safe_load(
            (PACK_DIR / "inputs/scene-map.yml").read_text())
        self.assertEqual(mapping["source"]["sha256"],
                         "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34")
        self.assertEqual(mapping["shot"]["number"], 2)
        self.assertEqual(mapping["shot"]["storyboard_page"], 12)
        self.assertEqual(mapping["shot"]["storyboard_image"], "image-007")
        self.assertEqual(mapping["shot"]["embedding"], "shot02.pt")

    def test_runner_is_syntax_valid_and_private(self):
        source = (PACK_DIR / "run_scene.py").read_text()
        ast.parse(source)
        self.assertIn("HEIGHT, WIDTH, FRAMES, STEPS, FPS, SEED = 384, 640, 73, 40, 24, 42", source)
        self.assertIn("public_release", source)
        self.assertIn("weights_only=True", source)
        self.assertNotIn("edge-tts", source)


if __name__ == "__main__":
    unittest.main()
