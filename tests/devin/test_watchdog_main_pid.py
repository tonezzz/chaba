"""Regression test: Devin extension server workers are not the GUI main PID."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devin/devin-desktop-watchdog.sh"
INSTALLER = REPO / "scripts/devin/install-devin-host.sh"


class MainPidSelection(unittest.TestCase):
    def test_watchdog_selftest_rejects_renderer_and_server_workers(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, XDG_STATE_HOME=home)
            result = subprocess.run(
                ["bash", str(SCRIPT), "--selftest-main-pid"],
                capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("selftest: ok", result.stdout)

    def test_watchdog_only_installer_skips_privileged_apparmor(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            fakebin = root / "bin"
            fakebin.mkdir()
            (root / ".local/bin").mkdir(parents=True)
            crontab_file = root / "crontab"
            crontab_file.touch()
            sysctl_marker = root / "sysctl-called"
            sudo_marker = root / "sudo-called"
            (fakebin / "crontab").write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-l\" ]; then\n"
                "  [ -f \"$FAKE_CRONTAB\" ] && cat \"$FAKE_CRONTAB\" || exit 1\n"
                "elif [ \"$1\" = \"-\" ]; then\n"
                "  cat >\"$FAKE_CRONTAB\"\n"
                "fi\n")
            (fakebin / "sysctl").write_text(
                "#!/bin/sh\ntouch \"$FAKE_SYSCTL_MARKER\"\necho 1\n")
            (fakebin / "sudo").write_text(
                "#!/bin/sh\ntouch \"$FAKE_SUDO_MARKER\"\nexit 0\n")
            for path in fakebin.iterdir():
                path.chmod(0o755)
            env = dict(
                os.environ,
                HOME=home,
                XDG_STATE_HOME=str(root / "state"),
                PATH=f"{fakebin}:/usr/bin:/bin",
                FAKE_CRONTAB=str(crontab_file),
                FAKE_SYSCTL_MARKER=str(sysctl_marker),
                FAKE_SUDO_MARKER=str(sudo_marker),
            )
            result = subprocess.run(
                ["bash", str(INSTALLER), "--watchdog-only"],
                capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 0,
                             result.stderr + result.stdout)
            self.assertTrue((root / ".local/bin/devin-desktop-watchdog.sh")
                            .is_file())
            self.assertIn("devin-desktop-watchdog.sh",
                          crontab_file.read_text())
            self.assertFalse(sysctl_marker.exists())
            self.assertFalse(sudo_marker.exists())


if __name__ == "__main__":
    unittest.main()
