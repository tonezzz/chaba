"""Unit tests for the Flood Hub integration slice (card flood-hub-integration).

Covers the pure/keyless parts: the flood-hub:auto CMS block renderer +
apply/strip helpers in flood-news-update.py, the hub severity -> alert
mapping + dedup in flood-alert.py, and the status-doc freshness gate.
No network, no MDDB.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fnu = _load("flood_news_update", REPO / "scripts/ada/flood-news-update.py")
fa = _load("flood_alert", REPO / "scripts/ada/flood-alert.py")
fhp = _load("flood_hub_poll", REPO / "scripts/ada/flood-hub-poll.py")

NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)
NOW_ICT = NOW.astimezone(fnu.ICT)


def status_doc(alertable=None, generated_at=None, areas=None):
    return {
        "generated_at": generated_at or NOW.isoformat(timespec="seconds"),
        "areas": areas or {
            "chao-phraya": {"label": "Chao Phraya / Bangkok",
                            "gauges": 3, "max_severity": "SEVERE"},
        },
        "alertable": alertable or [],
    }


def gauge(gid="g1", sev="SEVERE", areas=("chao-phraya",), **kw):
    rec = {"gaugeId": gid, "severity": sev, "trend": "RISING",
           "issuedTime": "2026-11-24T00:00:00Z", "lat": 13.7, "lon": 100.5,
           "verified": True, "source": "GRDC", "areas": list(areas)}
    rec.update(kw)
    return rec


class PollSeverityTest(unittest.TestCase):
    def test_alertable_threshold(self):
        self.assertIn("ABOVE_NORMAL", fhp.ALERTABLE)
        self.assertIn("SEVERE", fhp.ALERTABLE)
        self.assertIn("EXTREME", fhp.ALERTABLE)
        self.assertNotIn("NO_FLOODING", fhp.ALERTABLE)
        self.assertNotIn("UNKNOWN", fhp.ALERTABLE)

    def test_rank_order(self):
        self.assertGreater(fhp.SEV_RANK["EXTREME"], fhp.SEV_RANK["SEVERE"])
        self.assertGreater(fhp.SEV_RANK["SEVERE"], fhp.SEV_RANK["ABOVE_NORMAL"])
        self.assertGreater(fhp.SEV_RANK["ABOVE_NORMAL"], fhp.SEV_RANK["NO_FLOODING"])


class HubBlockTest(unittest.TestCase):
    def test_render_empty(self):
        block = fnu.render_hub_block(status_doc(), NOW_ICT)
        self.assertIn(fnu.HUB_BEGIN, block)
        self.assertIn(fnu.HUB_END, block)
        self.assertIn("ไม่พบเกจ", block)

    def test_render_alertable(self):
        block = fnu.render_hub_block(
            status_doc(alertable=[gauge(siteName="Bang Phli weir")]), NOW_ICT)
        self.assertIn("วิกฤต", block)
        self.assertIn("Bang Phli weir", block)
        self.assertIn("Chao Phraya / Bangkok", block)

    def test_hub_lines_stable_across_stamps(self):
        a = fnu.render_hub_block(status_doc(alertable=[gauge()]), NOW_ICT)
        later = NOW_ICT + timedelta(hours=2)
        b = fnu.render_hub_block(status_doc(alertable=[gauge()]), later)
        self.assertEqual(fnu._hub_lines(a), fnu._hub_lines(b))

    def test_apply_inserts_after_news_block(self):
        body = "intro\n\n" + fnu.BLOCK_BEGIN + "\nnews\n" + fnu.BLOCK_END + "\n\n## Log\n"
        block = fnu.render_hub_block(status_doc(), NOW_ICT)
        out = fnu.apply_hub_block(body, block)
        self.assertLess(out.index(fnu.BLOCK_END), out.index(fnu.HUB_BEGIN))
        self.assertLess(out.index(fnu.HUB_END), out.index("## Log"))

    def test_apply_replaces_existing(self):
        block1 = fnu.render_hub_block(status_doc(), NOW_ICT)
        body = "x\n\n" + block1 + "\n\n## Log\n"
        block2 = fnu.render_hub_block(
            status_doc(alertable=[gauge()]), NOW_ICT)
        out = fnu.apply_hub_block(body, block2)
        self.assertEqual(out.count(fnu.HUB_BEGIN), 1)
        self.assertIn("g1", out)
        self.assertIn("วิกฤต", out)

    def test_strip(self):
        body = "intro\n\n" + fnu.render_hub_block(status_doc(), NOW_ICT) + "\n\n## Log\n"
        out = fnu.strip_hub_block(body)
        self.assertNotIn(fnu.HUB_BEGIN, out)
        self.assertIn("## Log", out)

    def test_get_hub_status_fresh(self):
        doc = {"contentMd": json.dumps(status_doc())}
        orig = fnu._post
        fnu._post = lambda *a, **k: doc
        try:
            self.assertIsNotNone(fnu.get_hub_status(NOW))
        finally:
            fnu._post = orig

    def test_get_hub_status_stale_and_missing(self):
        stale = {"contentMd": json.dumps(
            status_doc(generated_at=(NOW - timedelta(hours=48)).isoformat()))}
        orig = fnu._post
        fnu._post = lambda *a, **k: stale
        try:
            self.assertIsNone(fnu.get_hub_status(NOW))
        finally:
            fnu._post = orig
        fnu._post = lambda *a, **k: None
        try:
            self.assertIsNone(fnu.get_hub_status(NOW))
        finally:
            fnu._post = orig


class HubAlertTest(unittest.TestCase):
    def pages(self, **kw):
        return {"flood-report": (kw.get("cfg", {"feeds": [("f", "u")]}), []),
                "flood-report-nongdon-saraburi": ({"feeds": [("f", "u")]}, [])}

    def test_severe_maps_critical_above_normal_warning(self):
        st = {"items": {}}
        alerts = fa.select_hub_alerts(
            status_doc(alertable=[gauge(gid="a", sev="SEVERE"),
                                  gauge(gid="b", sev="ABOVE_NORMAL")]),
            self.pages(), st)
        levels = {a["key"]: a["level"] for a in alerts}
        self.assertEqual(levels["hub:a"], "critical")
        self.assertEqual(levels["hub:b"], "warning")

    def test_no_flooding_not_alertable(self):
        st = {"items": {}}
        self.assertEqual(fa.select_hub_alerts(
            status_doc(alertable=[gauge(sev="NO_FLOODING")]),
            self.pages(), st), [])

    def test_dedup_and_escalation(self):
        st = {"items": {"hub:a": {"level": "warning"}}}
        # same-or-lower severity suppressed
        self.assertEqual(fa.select_hub_alerts(
            status_doc(alertable=[gauge(gid="a", sev="ABOVE_NORMAL")]),
            self.pages(), st), [])
        # escalation re-alerts
        out = fa.select_hub_alerts(
            status_doc(alertable=[gauge(gid="a", sev="EXTREME")]),
            self.pages(), st)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["level"], "critical")

    def test_alert_min_off_suppresses(self):
        pages = {"flood-report": ({"feeds": [("f", "u")], "alert": False}, []),
                 "flood-report-nongdon-saraburi": ({"feeds": [("f", "u")]}, [])}
        st = {"items": {}}
        # gauge only in chao-phraya -> flood-report has alert off -> nothing
        self.assertEqual(fa.select_hub_alerts(
            status_doc(alertable=[gauge(areas=("chao-phraya",))]),
            pages, st), [])

    def test_saraburi_area_uses_leaf_page(self):
        pages = self.pages()
        pages["flood-report-nongdon-saraburi"] = (
            {"feeds": [("f", "u")], "alert_min": "critical"}, [])
        st = {"items": {}}
        # ABOVE_NORMAL on saraburi-lopburi only -> leaf wants critical -> no alert
        self.assertEqual(fa.select_hub_alerts(
            status_doc(alertable=[gauge(areas=("saraburi-lopburi",),
                                          sev="ABOVE_NORMAL")]),
            pages, st), [])
        # SEVERE on saraburi-lopburi -> critical >= critical -> alert
        out = fa.select_hub_alerts(
            status_doc(alertable=[gauge(areas=("saraburi-lopburi",),
                                          sev="SEVERE")]),
            pages, st)
        self.assertEqual(len(out), 1)
        self.assertIn("flood-report-nongdon-saraburi", out[0]["areas"])


if __name__ == "__main__":
    unittest.main()
