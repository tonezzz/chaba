"""Unit tests for scripts/ada/flood-alert.py — the flood severity
watchdog.

Covers the three contracts the job relies on: the Thai/English severity
classifier tiers, per-page alert_min thresholding + state dedup/escalation
in select_alerts, and the batched push renderer. Pure functions only —
no network, no writes.
"""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/flood-alert.py"

spec = importlib.util.spec_from_file_location("flood_alert", SCRIPT)
fa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa)

PUB = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def item(title, desc="", pub=PUB):
    return {"title": title, "desc": desc, "pub": pub,
            "link": "https://x/" + title[:10], "source": "t"}


def cfg(**kw):
    base = {"feeds": [("f", "u")]}
    base.update(kw)
    return base


class ClassifyTest(unittest.TestCase):
    def test_critical_thai(self):
        self.assertEqual(
            fa.classify("อพยพด่วน! น้ำทะลักคันกั้นเข้าท่วมบางพลี"), "critical")
        self.assertEqual(
            fa.classify("เขื่อนแตก น้ำทะลักท่วมหมู่บ้าน"), "critical")
        self.assertEqual(fa.classify("มวลน้ำมหาศาลท่วมฉับพลัน"), "critical")

    def test_critical_english(self):
        self.assertEqual(
            fa.classify("Evacuations ordered as dike bursts"), "critical")
        self.assertEqual(
            fa.classify("Dam breach forces emergency declaration"),
            "critical")

    def test_warning(self):
        self.assertEqual(
            fa.classify("เฝ้าระวังน้ำท่วมฉับพลัน กทม."), "warning")
        self.assertEqual(
            fa.classify("เขื่อนเจ้าพระยาระบายน้ำตามปกติ"), "warning")
        self.assertEqual(
            fa.classify("Flash flood warning for Bangkok"), "warning")

    def test_info_baseline(self):
        self.assertEqual(
            fa.classify("ปรับปรุงถนนเทพารักษ์หลังน้ำลดแล้ว"), "info")
        self.assertEqual(
            fa.classify("Flood situation in Thailand improves"), "info")


class SelectAlertsTest(unittest.TestCase):
    def test_threshold_filters_below_min(self):
        pages = {"p": (cfg(alert_min="critical"),
                       [item("เฝ้าระวังน้ำท่วมฉับพลัน"),
                        item("เขื่อนแตก ทะลัก")])}
        out = fa.select_alerts(pages, {"items": {}}, "warning")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["level"], "critical")

    def test_off_page_skips(self):
        pages = {"p": (cfg(alert_min="off"), [item("เขื่อนแตก")])}
        self.assertEqual(fa.select_alerts(pages, {"items": {}}, "warning"),
                         [])

    def test_alert_false_skips(self):
        pages = {"p": (cfg(alert=False), [item("เขื่อนแตก")])}
        self.assertEqual(fa.select_alerts(pages, {"items": {}}, "warning"),
                         [])

    def test_state_suppresses_seen_same_level(self):
        it = item("อพยพ น้ำท่วมบางพลี")
        key = fa.fnu.dedup_key(it["title"])
        state = {"items": {key: {"level": "critical", "at": "x"}}}
        out = fa.select_alerts({"p": (cfg(), [it])}, state, "warning")
        self.assertEqual(out, [])

    def test_escalation_realerts(self):
        it = item("เขื่อนแตก ทะลัก")
        key = fa.fnu.dedup_key(it["title"])
        state = {"items": {key: {"level": "warning", "at": "x"}}}
        out = fa.select_alerts({"p": (cfg(), [it])}, state, "warning")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["level"], "critical")

    def test_cross_page_dedup_merges_areas(self):
        it = item("เขื่อนแตก ทะลัก")
        pages = {"a": (cfg(alert_label="home"), [it]),
                 "b": (cfg(alert_label="north"), [it])}
        out = fa.select_alerts(pages, {"items": {}}, "warning")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["areas"], {"home", "north"})

    def test_critical_sorts_first(self):
        pages = {"p": (cfg(), [item("เฝ้าระวังน้ำท่วม"),
                               item("อพยพด่วน เขื่อนแตก")])}
        out = fa.select_alerts(pages, {"items": {}}, "warning")
        self.assertEqual(out[0]["level"], "critical")


class RenderPushTest(unittest.TestCase):
    def test_title_marks_critical(self):
        alerts = [{"level": "critical", "areas": {"home"},
                   "item": item("เขื่อนแตก")}]
        title, body = fa.render_push(alerts)
        self.assertIn("critical", title.lower())
        self.assertIn("[CRIT]", body)

    def test_caps_items(self):
        alerts = [{"level": "warning", "areas": {"a"},
                   "item": item(f"เตือนภัย {i}")} for i in range(9)]
        title, body = fa.render_push(alerts)
        self.assertIn("+3 more", body)
        self.assertIn("9 new", title)


class StateTest(unittest.TestCase):
    def test_prune_drops_old(self):
        old = {"items": {
            "a": {"level": "warning", "at": "2026-09-01T00:00:00+00:00"},
            "b": {"level": "warning", "at": "2026-10-09T00:00:00+00:00"}}}
        fa.prune_state(old, datetime(2026, 10, 10, tzinfo=timezone.utc))
        self.assertEqual(list(old["items"]), ["b"])


if __name__ == "__main__":
    unittest.main()
