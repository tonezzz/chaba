import ast
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
PACK_DIR = (REPO / "scripts/colab/packs/"
            "kk-video-c9f99fee6146-voice-clone-probe")


class KkVoiceCloneProbeTest(unittest.TestCase):
    def test_pack_is_private_and_t4_compatible(self):
        pack = yaml.safe_load(
            (PACK_DIR / "pack.yml").read_text(encoding="utf-8"))
        self.assertEqual(pack["needs"]["gpu_gb"], 14)
        self.assertEqual(pack["needs"]["ram_gb"], 8)
        self.assertIn("kk-video-c9f99fee6146-preview", pack["requires"])
        self.assertNotIn("publish", pack)
        self.assertTrue(pack.get("venv"))

    def test_probe_script_is_syntax_valid_and_uses_local_clone_model(self):
        script = (PACK_DIR / "run_probe.py").read_text(encoding="utf-8")
        ast.parse(script)
        self.assertIn('TTS(model="v2")', script)
        self.assertIn("faster_whisper", script)
        self.assertIn("sf.read(wav_path", script)
        self.assertIn("model.transcribe(\n        audio", script)
        self.assertNotIn("edge-tts", script)
        self.assertIn('"public_release": False', script)


if __name__ == "__main__":
    unittest.main()
