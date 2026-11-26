import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "ops" / "install-kk-llm-worker.sh"


class KkMacWorkerInstallerTests(unittest.TestCase):
    def render(self, interval="60"):
        env = os.environ.copy()
        env.update({
            "KK_MAC_HOME": "/Users/tester",
            "CHABA_ROOT": "/Users/tester/CascadeProjects/chaba",
            "KK_WORKER_INTERVAL": interval,
        })
        return subprocess.run(
            ["bash", str(INSTALLER), "--print"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_print_is_valid_plist_and_defaults_to_sixty_seconds(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        plist = plistlib.loads(result.stdout.encode())
        self.assertEqual(plist["Label"], "net.adanest.kk-llm-worker")
        self.assertEqual(plist["StartInterval"], 60)

    def test_payload_is_the_live_lane_worker(self):
        # the rendered LaunchAgent must invoke kk_mac_lane_worker.py on
        # the dedicated kk-llm queue — the payload that is actually live
        # on kk-mac, not the generic nest-worker of the first installer
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        plist = plistlib.loads(result.stdout.encode())
        args = plist["ProgramArguments"]
        joined = " ".join(args)
        self.assertIn("scripts/devnest/kk_mac_lane_worker.py", joined)
        self.assertIn("--remote gdrive:ada-nest/kk-llm", joined)
        self.assertIn("--host local", joined)
        self.assertIn("--max-packs 1", joined)
        self.assertNotIn("nest-worker.py", joined)
        self.assertNotIn("--once", joined)

    def test_rejects_aggressive_interval(self):
        result = self.render("15")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(">= 30", result.stderr)

    def test_print_does_not_write_a_file(self):
        with tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env.update({"KK_MAC_HOME": home, "KK_WORKER_INTERVAL": "90"})
            result = subprocess.run(
                ["bash", str(INSTALLER), "--print"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(
                (Path(home) / "Library/LaunchAgents/"
                 "net.adanest.kk-llm-worker.plist").exists()
            )


if __name__ == "__main__":
    unittest.main()
