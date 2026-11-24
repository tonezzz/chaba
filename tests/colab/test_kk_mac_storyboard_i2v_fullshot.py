import ast
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
PACK_DIR = (REPO / "scripts/colab/packs/"
            "kk-mac-storyboard-i2v-fullshot01-20261030")


class KkMacStoryboardI2VFullshotTest(unittest.TestCase):
    def test_pack_is_private_offline_and_gated_by_short_i2v_probe(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(
            pack["requires"], ["kk-mac-storyboard-i2v-probe-20261029"])
        self.assertEqual(pack["needs"]["ram_gb"], 30)
        self.assertEqual(pack["timeout_s"], 3600)
        self.assertIn("HF_HUB_OFFLINE=1", pack["run_sh"])
        self.assertIn("memory_pressure", pack["prep"])
        self.assertIn("ollama ps", pack["prep"])
        self.assertNotIn("publish", pack)
        self.assertEqual(len(pack["artifacts"]), 3)

    def test_runner_is_syntax_valid_and_uses_full_shot_settings(self):
        source = (PACK_DIR / "run_fullshot.py").read_text()
        ast.parse(source)
        self.assertIn("FRAMES, STEPS = 73, 40", source)
        self.assertIn("base.FRAMES = FRAMES", source)
        self.assertIn("base.STEPS = STEPS", source)
        self.assertIn("base.inspect_video = inspect_fullshot", source)
        self.assertNotIn("edge-tts", source)


if __name__ == "__main__":
    unittest.main()
