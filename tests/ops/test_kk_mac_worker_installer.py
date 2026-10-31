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
        self.assertIn("--once", plist["ProgramArguments"])

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
