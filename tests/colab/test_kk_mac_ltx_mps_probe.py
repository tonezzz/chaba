import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "scripts/colab/packs/kk-mac-ltx-mps-probe-20261029"
SPEC = importlib.util.spec_from_file_location(
    "kk_mac_ltx_mps_probe", PACK_DIR / "run_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class KkMacLtxMpsPackTests(unittest.TestCase):
    def test_pack_is_one_bounded_mac_probe(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(pack["name"], "kk-mac-ltx-mps-probe-20261029")
        self.assertEqual(pack["timeout_s"], 3600)
        self.assertEqual(pack["needs"]["ram_gb"], 30)
        self.assertEqual(pack["needs"]["disk_gb"], 10)
        self.assertNotIn("gpu_gb", pack["needs"])
        self.assertEqual(len(pack["artifacts"]), 3)

    def test_probe_uses_pinned_revision_and_single_shot_settings(self):
        self.assertEqual(
            PROBE.REVISION, "8984fa25007f376c1a299016d0957a37a2f797bb")
        self.assertEqual((PROBE.WIDTH, PROBE.HEIGHT, PROBE.FRAMES,
                          PROBE.STEPS, PROBE.FPS), (640, 384, 73, 40, 24))

    def test_pack_shell_blocks_network_and_has_valid_syntax(self):
        pack = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertIn("HF_HUB_OFFLINE=1", pack["run_sh"])
        for command in (pack["prep"], pack["run_sh"]):
            result = subprocess.run(
                ["bash", "-n"], input=command, text=True,
                capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_sha256_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "probe.txt"
            path.write_bytes(b"verified probe")
            self.assertEqual(
                PROBE.sha256_file(path),
                "ff2393dc0a6ac1ca8fded3a3c97996b779c8019c3b6c7180900dff7f3ce9d74e",
            )


if __name__ == "__main__":
    unittest.main()
