"""gemini-wallet-watch per-key probe coverage (card
ada-voice-error-observability-surface-up-489f64, 2026-10-16).

The 2026-10-14 ada-ha-tony incident: GEMINI_API_KEY_TONY hit its project
cap -> Live 1011 -> voice died, while the shared PAID-key probe stayed
green. The watch now takes a repeatable --key-var probe list, keeps
per-key state, and alerts per key (kk group only for the kk lane's own
key). These tests pin that behavior without touching the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/gemini-wallet-watch.py"

spec = importlib.util.spec_from_file_location("gemini_wallet_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["gemini_wallet_watch"] = mod
spec.loader.exec_module(mod)


def _run(tmp: Path, argv_extra: list[str], probes: dict[str, dict],
         state: dict | None = None) -> tuple[int, list, dict]:
    """Run main() with probe/notify stubbed. Returns (exit, notify_calls,
    written_state). probes maps env var -> probe() result."""
    env = tmp / "keys.env"
    env.write_text("".join(f"{v}=dummy-{v}\n" for v in probes))
    st = tmp / "state.json"
    if state is not None:
        st.write_text(json.dumps(state))
    calls = []

    with mock.patch.object(mod, "probe",
                           side_effect=lambda key, model:
                           probes[_var_for(probes, key)]), \
         mock.patch.object(mod, "notify",
                           side_effect=lambda relay, targets:
                           calls.append(targets) or ["ok"] * len(targets)), \
         mock.patch.object(sys, "argv",
                         ["watch", "--env-file", str(env),
                          "--state", str(st)] + argv_extra):
        rc = mod.main()
    written = json.loads(st.read_text()) if st.exists() else {}
    return rc, calls, written


def _var_for(probes: dict, key: str) -> str:
    for var in probes:
        if key == f"dummy-{var}":
            return var
    raise AssertionError(f"unprobed key {key}")


class Verdict(unittest.TestCase):
    def test_credit_signals(self):
        self.assertEqual(mod._verdict(402, ""), "credit")
        self.assertEqual(mod._verdict(500, "1011 prepayment credits depleted"),
                         "credit")
        self.assertEqual(mod._verdict(500, "quota depleted"), "credit")

    def test_non_credit_signals(self):
        self.assertEqual(mod._verdict(200, ""), "ok")
        self.assertEqual(mod._verdict(429, ""), "quota")
        self.assertEqual(mod._verdict(503, "high demand"), "demand")
        self.assertEqual(mod._verdict(403, ""), "auth")
        self.assertEqual(mod._verdict(500, "weird"), "other")


class StateMigration(unittest.TestCase):
    def test_legacy_single_key_format(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "s.json"
            st.write_text(json.dumps({"status": "credit", "at": "x"}))
            loaded = mod._load_state(st)
        self.assertEqual(loaded["keys"]["GEMINI_API_KEY_PAID"]["status"],
                         "credit")

    def test_new_format_passthrough(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "s.json"
            st.write_text(json.dumps(
                {"keys": {"GEMINI_API_KEY_TONY": {"status": "quota"}}}))
            loaded = mod._load_state(st)
        self.assertEqual(loaded["keys"]["GEMINI_API_KEY_TONY"]["status"],
                         "quota")


class MultiKeyProbe(unittest.TestCase):
    def test_depleted_lane_key_alerts_and_exits_1(self):
        """TONY capped while PAID green -> one alert naming TONY's lane,
        exit 1 (the exact 2026-10-14 blind spot)."""
        with tempfile.TemporaryDirectory() as d:
            rc, calls, state = _run(
                Path(d),
                ["--key-var", "GEMINI_API_KEY_PAID",
                 "--key-var", "GEMINI_API_KEY_TONY"],
                {"GEMINI_API_KEY_PAID": {"verdict": "ok"},
                 "GEMINI_API_KEY_TONY": {"verdict": "credit",
                                         "detail": "1011"}})
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)
        flat = [t for c in calls for t in c]
        self.assertTrue(all(t["instance"] == "tony" for t in flat),
                        "tony key must not page the kk group")
        self.assertIn("GEMINI_API_KEY_TONY", flat[0]["text"])
        self.assertIn("ada-ha-tony", flat[0]["text"])
        self.assertEqual(state["keys"]["GEMINI_API_KEY_TONY"]["status"],
                         "credit")
        self.assertEqual(state["keys"]["GEMINI_API_KEY_PAID"]["status"], "ok")

    def test_kk_key_alerts_kk_group_in_thai(self):
        with tempfile.TemporaryDirectory() as d:
            rc, calls, _ = _run(
                Path(d), ["--key-var", "GEMINI_API_KEY_KK"],
                {"GEMINI_API_KEY_KK": {"verdict": "credit"}})
        self.assertEqual(rc, 1)
        flat = [t for c in calls for t in c]
        kk_msgs = [t for t in flat if t["instance"] == "kk"]
        self.assertEqual(len(kk_msgs), 1)
        self.assertIn("ada-kk", kk_msgs[0]["text"])

    def test_no_repeat_alert_while_still_depleted(self):
        with tempfile.TemporaryDirectory() as d:
            rc, calls, _ = _run(
                Path(d), ["--key-var", "GEMINI_API_KEY_TONY"],
                {"GEMINI_API_KEY_TONY": {"verdict": "credit"}},
                state={"keys": {"GEMINI_API_KEY_TONY": {"status": "credit"}}})
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])

    def test_recovery_notifies_once(self):
        with tempfile.TemporaryDirectory() as d:
            rc, calls, _ = _run(
                Path(d), ["--key-var", "GEMINI_API_KEY_TONY"],
                {"GEMINI_API_KEY_TONY": {"verdict": "ok"}},
                state={"keys": {"GEMINI_API_KEY_TONY": {"status": "credit"}}})
        self.assertEqual(rc, 0)
        flat = [t for c in calls for t in c]
        self.assertEqual(len(flat), 1)
        self.assertIn("healthy again", flat[0]["text"])

    def test_legacy_state_suppresses_repeat_alert(self):
        """A PAID wallet already alerted under the old {status: credit}
        format must not re-alert after the format migration."""
        with tempfile.TemporaryDirectory() as d:
            rc, calls, _ = _run(
                Path(d), ["--key-var", "GEMINI_API_KEY_PAID"],
                {"GEMINI_API_KEY_PAID": {"verdict": "credit"}},
                state={"status": "credit"})
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])

    def test_default_var_is_paid(self):
        with tempfile.TemporaryDirectory() as d:
            rc, calls, state = _run(
                Path(d), [],
                {"GEMINI_API_KEY_PAID": {"verdict": "ok"}})
        self.assertEqual(rc, 0)
        self.assertEqual(list(state["keys"]), ["GEMINI_API_KEY_PAID"])

    def test_missing_var_records_no_key_without_alert(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "keys.env"
            env.write_text("")  # no vars at all
            st = Path(d) / "state.json"
            with mock.patch.object(mod, "notify") as n, \
                 mock.patch.object(sys, "argv",
                     ["watch", "--env-file", str(env), "--state", str(st),
                      "--key-var", "GEMINI_API_KEY_MICHAEL"]):
                rc = mod.main()
            self.assertEqual(rc, 0)
            n.assert_not_called()
            self.assertEqual(json.loads(st.read_text())
                             ["keys"]["GEMINI_API_KEY_MICHAEL"]["status"],
                             "no-key")


if __name__ == "__main__":
    unittest.main()
