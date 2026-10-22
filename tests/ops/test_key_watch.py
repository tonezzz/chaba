"""key-watch judge/sink coverage (card key-watch-monitor, SEC-0499).

Pins the threshold contract — expiry <48h or quota >80% -> warn;
dead/expired -> alert — plus the no-secret-leak invariant: probe results
carrying real values must never surface them in findings/LINE/cards.
All tests run offline with synthetic probe results.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/key-watch.py"

spec = importlib.util.spec_from_file_location("key_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["key_watch"] = mod
spec.loader.exec_module(mod)

NOW = datetime.datetime.now(datetime.timezone.utc)


def _slot(kind="openrouter", **kw):
    s = {"id": kw.pop("id", "t-1"), "kind": kind,
         "host": "h1", "file": "~/.config/secrets/x.env", "var": "X"}
    s.update(kw)
    return s


class OpenRouterJudge(unittest.TestCase):
    def test_valid_clean(self):
        f = mod.judge(_slot(), {"status": "valid", "masked": "sk-or-…ab12",
                                "fp": "ab12",
                                "detail": {"expires_at": None, "usage": 1.0,
                                           "limit": 10.0,
                                           "limit_remaining": 9.0}})
        self.assertEqual(f["level"], "ok")

    def test_expires_within_48h_warns(self):
        exp = (NOW + datetime.timedelta(hours=12)).isoformat()
        f = mod.judge(_slot(), {"status": "valid", "masked": "m",
                                "fp": "f", "detail": {"expires_at": exp}})
        self.assertEqual(f["level"], "warn")
        self.assertIn("expires in", f["why"])

    def test_expired_alerts(self):
        exp = (NOW - datetime.timedelta(hours=1)).isoformat()
        f = mod.judge(_slot(), {"status": "valid", "masked": "m",
                                "fp": "f", "detail": {"expires_at": exp}})
        self.assertEqual(f["level"], "alert")
        self.assertIn("EXPIRED", f["why"])

    def test_limit_remaining_zero_alerts(self):
        f = mod.judge(_slot(), {"status": "valid", "masked": "m", "fp": "f",
                                "detail": {"expires_at": None, "usage": 10.0,
                                           "limit": 10.0,
                                           "limit_remaining": 0}})
        self.assertEqual(f["level"], "alert")

    def test_quota_over_80_warns(self):
        f = mod.judge(_slot(), {"status": "valid", "masked": "m", "fp": "f",
                                "detail": {"expires_at": None, "usage": 8.5,
                                           "limit": 10.0,
                                           "limit_remaining": 1.5}})
        self.assertEqual(f["level"], "warn")
        self.assertIn("%", f["why"])

    def test_dead_key_alerts(self):
        f = mod.judge(_slot(), {"status": "dead", "masked": "m",
                                "fp": "f", "detail": {"http": 401}})
        self.assertEqual(f["level"], "alert")

    def test_probe_error_is_unknown_not_alert(self):
        f = mod.judge(_slot(), {"status": "error", "masked": "m", "fp": "f",
                                "detail": {"http": -1, "body": "timeout"}})
        self.assertEqual(f["level"], "unknown")


class HAJudge(unittest.TestCase):
    def test_401_is_dead(self):
        f = mod.judge(_slot("ha", url="http://x:8123"),
                      {"status": "dead", "masked": "m", "fp": "f",
                       "detail": {"http": 401}})
        self.assertEqual(f["level"], "alert")
        self.assertIn("dead LLAT", f["why"])

    def test_200_ok(self):
        f = mod.judge(_slot("ha", url="http://x:8123"),
                      {"status": "valid", "masked": "m", "fp": "f",
                       "detail": {"message": "API running."}})
        self.assertEqual(f["level"], "ok")

    def test_unreachable_instance_is_unknown(self):
        f = mod.judge(_slot("ha", url="http://x:8123"),
                      {"status": "error", "masked": "m", "fp": "f",
                       "detail": {"http": -1, "body": "conn refused"}})
        self.assertEqual(f["level"], "unknown")


class CFJudge(unittest.TestCase):
    def test_dead(self):
        f = mod.judge(_slot("cf"), {"status": "dead", "masked": "m",
                                    "fp": "f",
                                    "detail": {"http": 401,
                                               "zones_http": 403}})
        self.assertEqual(f["level"], "alert")

    def test_cfat_quirk_still_valid(self):
        """verify rejects cfat_ but zones list works -> ok, not dead."""
        f = mod.judge(_slot("cf"), {"status": "valid", "masked": "m",
                                    "fp": "f",
                                    "detail": {"via": "zones",
                                               "note": "cfat quirk"}})
        self.assertEqual(f["level"], "ok")


class CommonJudge(unittest.TestCase):
    def test_missing_file_and_var_warn(self):
        for st in ("missing-file", "missing-var"):
            f = mod.judge(_slot(), {"status": st})
            self.assertEqual(f["level"], "warn", st)

    def test_host_unreachable_is_unknown(self):
        f = mod.judge(_slot(), {"status": "host-unreachable",
                                "detail": {"why": "timeout"}})
        self.assertEqual(f["level"], "unknown")

    def test_no_secret_in_why(self):
        secret = "sk-or-v1-REALSECRETVALUE1234567890"
        f = mod.judge(_slot(), {"status": "dead", "masked": "sk-or-…7890",
                                "fp": "7890", "detail": {"http": 401,
                                                         "body": secret}})
        self.assertNotIn(secret, f["why"])


class Drift(unittest.TestCase):
    def test_fp_mismatch_warns(self):
        f = mod.or_drift_finding({
            "or-a": {"fp": "aaa"}, "or-b": {"fp": "bbb"}})
        self.assertIsNotNone(f)
        self.assertEqual(f["level"], "warn")

    def test_same_fp_ok(self):
        self.assertIsNone(mod.or_drift_finding(
            {"or-a": {"fp": "aaa"}, "or-b": {"fp": "aaa"}}))

    def test_missing_slots_ignored(self):
        self.assertIsNone(mod.or_drift_finding(
            {"or-a": {"fp": "aaa"}, "or-b": {"status": "missing-file"}}))


class Sinks(unittest.TestCase):
    def test_card_id_stable(self):
        self.assertEqual(mod.card_id("OR-IDC03.Key"), "keywatch-or-idc03-key")

    def test_line_format(self):
        alerts = [{"id": "a", "level": "alert", "why": "dead"}]
        warns = [{"id": "w", "level": "warn", "why": "expires in 12h"}]
        text = mod.format_line(alerts, warns, [])
        self.assertIn("ALERT", text)
        self.assertIn("WARN", text)


if __name__ == "__main__":
    unittest.main()
