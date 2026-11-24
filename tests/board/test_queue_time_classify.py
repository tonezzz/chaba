import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import json

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]

def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class QueueClassifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.api = _load("board-api")
        cls.api.dr = cls.dr

    def setUp(self):
        self.api.CARD_DIR = Path("/tmp/nonexistent")
        self.api.now = lambda: "2026-10-31T00:00:00Z"
        self.api.comms_add = lambda card, frm, text: card.setdefault("comms", []).append({"from": frm, "text": text})
        self.api.save = lambda p, c: None
        self.api.queue_starve_warn = lambda c: ""
        self.api.queue_unclaimable_warn = lambda c: ""
        self.api.HOST = "localhost"

    def test_kw_hit(self):
        card = {"id": "c1", "title": "remove unused config", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "codemod")
        self.assertIn("classified as codemod", card["comms"][0]["text"])
        self.assertEqual(card["action"]["status"], "queued")
        self.assertTrue(res.startswith("queued"))

    @patch("urllib.request.urlopen")
    def test_jevos_down_fallback(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("jevos down")
        card = {"id": "c1", "title": "Random ambiguous thing", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "devin")
        self.assertIn("fallback conf 0.00", card["comms"][0]["text"])

    def test_explicit_action_model_wins(self):
        card = {"id": "c1", "title": "remove unused config", "action": {"model": "my-custom-model"}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "codemod")
        self.assertEqual(card["action"]["model"], "my-custom-model")

    def test_manual_refuses(self):
        card = {"id": "c1", "title": "hardware rotation", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "manual")
        self.assertEqual(card["action"].get("status"), "idle")
        self.assertEqual(res, "classified as manual — queue skipped")
        # audit comm names the matched keyword so false positives are
        # diagnosable from the card alone
        self.assertIn("kw:hardware", card["comms"][-1]["text"])
        self.assertEqual(card["action"]["lane_source"], "kw")
        self.assertTrue(card.get("awaiting_action"))

    @patch("urllib.request.urlopen")
    def test_spend_in_spec_body_not_manual(self, mock_urlopen):
        """dispatch-lane-classifier-spend-false-manual (2026-11-17): a
        context-free 'spend' mention in the spec body must not force
        manual — the work itself is dispatchable."""
        mock_urlopen.side_effect = Exception("jevos down")
        card = {"id": "c1",
                "title": "idc03: gemini proxy paid-fallback spam — "
                         "free circuit open",
                "spec": "every request falls through to the paid model — "
                        "this is uncontrolled spend, not just load",
                "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertNotEqual(card["action"]["lane"], "manual")
        self.assertTrue(res.startswith("queued"))

    @patch("urllib.request.urlopen")
    def test_costs_money_option_in_spec_not_manual(self, mock_urlopen):
        """Second 2026-11-17 false positive: spec lists a priced option
        as a Tony decision — the non-spend work stays dispatchable."""
        mock_urlopen.side_effect = Exception("jevos down")
        card = {"id": "c1",
                "title": "idc03: structural capacity — resize VPS or "
                         "migrate heavy services",
                "spec": "OPTIONS: (a) resize VPS to 32GB (costs money — "
                        "Tony decision); (b) migrate services. TASK: "
                        "implement the non-spend option(s)",
                "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertNotEqual(card["action"]["lane"], "manual")
        self.assertTrue(res.startswith("queued"))

    def test_spend_phrase_in_title_still_manual(self):
        card = {"id": "c1", "title": "Approve OR top-up — this costs "
                                     "money", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "manual")
        self.assertIn("kw:costs money", card["comms"][-1]["text"])

    def test_explicit_lane_wins_over_manual_title(self):
        card = {"id": "c1", "title": "hardware rotation",
                "action": {"lane": "devin"}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "devin")
        self.assertTrue(res.startswith("queued"))
        self.assertNotIn("lane_source", card["action"])

    @patch("urllib.request.urlopen")
    def test_stamped_lane_reclassifies_on_requeue(self, mock_urlopen):
        """A lane the classifier stamped (lane_source present) is
        re-evaluated each queue — the fixed classifier unsticks cards
        it previously misrouted instead of leaving them manual."""
        mock_urlopen.side_effect = Exception("jevos down")
        card = {"id": "c1",
                "title": "idc03: gemini proxy paid-fallback spam",
                "spec": "uncontrolled spend",
                "action": {"status": "idle", "lane": "manual",
                           "lane_source": "kw"}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertNotEqual(card["action"]["lane"], "manual")
        self.assertEqual(card["action"]["status"], "queued")
        self.assertTrue(res.startswith("queued"))

    def test_classify_reports_explicit_source(self):
        """classify_lane honors an author lane (no lane_source) even on
        a manual-keyword title — and reports source='explicit'."""
        lane, src, conf = self.dr.classify_lane(
            {"title": "hardware rotation",
             "action": {"lane": "devin"}}, with_detail=True)
        self.assertEqual((lane, src), ("devin", "explicit"))
        # a classifier-stamped lane is NOT explicit — it re-classifies
        lane, src, conf = self.dr.classify_lane(
            {"title": "hardware rotation",
             "action": {"lane": "codemod", "lane_source": "kw"}},
            with_detail=True)
        self.assertEqual((lane, src), ("manual", "kw:hardware"))

    def test_host_mention_does_not_preempt_cheaper_lane(self):
        """DEV-0045 reroute: a bare 'host' mention in an ops/report spec
        must not route a bounded read-only task onto devin ahead of
        free_lane (devin used to be evaluated first)."""
        lane, src, conf = self.dr.classify_lane({
            "title": "report graph: producer metas never reach renderer",
            "spec": "read-only check of the host's failing report graph",
            "action": {},
        }, with_detail=True)
        self.assertEqual((lane, src), ("free_lane", "kw:report"))

    def test_timer_sentinel_alert_classifies_free_lane(self):
        """DEV-0045 chosen slice: auto-generated timer-sentinel alerts are
        bounded diagnoses; the generic 'failing' keyword must not send
        them to devin."""
        card = {"id": "timer-alert-idc03-log-shipper",
                "title": "Timer log-shipper on idc03 failing",
                "tags": ["timer-alert", "auto", "by:timer-sentinel"],
                "action": {}}
        self.assertEqual(self.dr.classify_lane(card, with_detail=True)[:2],
                         ("free_lane", "timer-alert"))
        card["action"]["lane"] = "devin"
        self.assertEqual(self.dr.classify_lane(card, with_detail=True)[:2],
                         ("devin", "explicit"))

    def test_plain_failing_task_still_devin(self):
        """The narrow sentinel tag rule must not re-route ordinary
        multi-step failure work."""
        card = {"title": "deployment pipeline failing", "action": {}}
        self.assertEqual(self.dr.classify_lane(card), "devin")


class KkMacRouteUnitTest(unittest.TestCase):
    """dr.kk_mac_route — the bounded read-only auto-route rule
    (kk-mac-auto-lane-classifier). Positive: an admitted task class or
    unambiguous keywords. Negative: any routing pin, host pin, mutation
    intent, or an over-budget prompt."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")

    def _card(self, **kw):
        a = {"type": "dispatch"}
        a.update(kw.pop("action", {}))
        card = {"id": "kk1", "title": kw.pop("title", "t"),
                "action": a}
        card.update(kw)
        return card

    def test_declared_task_class_routes(self):
        c = self._card(action={"task_class": "summary",
                               "prompt": "Summarize the digest"})
        self.assertEqual(self.dr.kk_mac_route(c), "summary")

    def test_keyword_infers_task_class(self):
        c = self._card(title="Summarize the overnight host report")
        self.assertEqual(self.dr.kk_mac_route(c), "summary")
        c = self._card(title="Extract the host list from this digest")
        self.assertEqual(self.dr.kk_mac_route(c), "structured_extract")

    def test_held_class_keywords_not_routed(self):
        # safe_route/operator_brief keywords were removed while the
        # classes are unadmitted (kk-mac-admitted-classes-narrow) — a
        # held-class inference must never reach queue validation
        for title in ("Triage this alert into a lane",
                      "Write an operator brief for last night"):
            c = self._card(title=title)
            self.assertEqual(self.dr.kk_mac_route(c), "", title)

    def test_executor_pin_wins(self):
        c = self._card(action={"executor": "devin",
                               "task_class": "summary"})
        self.assertEqual(self.dr.kk_mac_route(c), "")

    def test_lane_pin_wins(self):
        c = self._card(title="Summarize the report",
                       action={"lane": "free_lane"})
        self.assertEqual(self.dr.kk_mac_route(c), "")

    def test_host_pins_not_routed(self):
        for pin in ("host", "target_host", "runner"):
            c = self._card(title="Summarize the report",
                           action={"task_class": "summary", pin: "idc03"})
            self.assertEqual(self.dr.kk_mac_route(c), "", pin)

    def test_mutation_intent_not_routed(self):
        c = self._card(title="Summarize then deploy the fix",
                       action={"task_class": "summary"})
        self.assertEqual(self.dr.kk_mac_route(c), "")

    def test_unadmitted_task_class_not_routed(self):
        c = self._card(title="Summarize the report",
                       action={"task_class": "code_mutation"})
        self.assertEqual(self.dr.kk_mac_route(c), "")

    def test_oversized_prompt_not_routed(self):
        c = self._card(title="Summarize x",
                       action={"task_class": "summary",
                               "prompt": "x" * 6001})
        self.assertEqual(self.dr.kk_mac_route(c), "")
        c["action"]["prompt"] = "x" * 6000
        self.assertEqual(self.dr.kk_mac_route(c), "summary")

    def test_script_type_not_routed(self):
        c = self._card(action={"type": "script", "task_class": "summary",
                               "prompt": "Summarize the digest"})
        self.assertEqual(self.dr.kk_mac_route(c), "")


class KkMacAutoRouteQueueTest(unittest.TestCase):
    """Queue-time auto-route: /action do=queue stamps
    executor=kk_mac_local + task_class, and a KK_MAC_LANES=1 runner
    then serves the card through claimable()."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.api = _load("board-api")
        cls.api.dr = cls.dr
        cls.runner = _load("runner-agent")

    def setUp(self):
        self.api.CARD_DIR = Path("/tmp/nonexistent")
        self.api.now = lambda: "2026-10-31T00:00:00Z"
        self.api.comms_add = lambda card, frm, text: card.setdefault("comms", []).append({"from": frm, "text": text})
        self.api.save = lambda p, c: None
        self.api.queue_starve_warn = lambda c: ""
        self.api.queue_unclaimable_warn = lambda c: ""
        self.api.HOST = "localhost"
        r = self.runner
        self._saved = {k: getattr(r, k) for k in
                       ("KK_MAC_LANES", "LABELS", "HOST")}
        self._saved_fn = {k: getattr(r, k) for k in
                          ("push_capable", "shutil_which")}
        r.HOST = "kkhost"
        r.LABELS = set()

    def tearDown(self):
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(self.runner, k, v)

    def _card(self, **kw):
        a = {"type": "dispatch"}
        a.update(kw.pop("action", {}))
        card = {"id": "kkq1", "title": kw.pop("title", "t"),
                "action": a}
        card.update(kw)
        return card

    def test_task_class_summary_auto_routes_and_is_claimable(self):
        card = self._card(
            action={"task_class": "summary",
                    "prompt": "Summarize the last 24h of host events"})
        res = self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(a["executor"], "kk_mac_local")
        self.assertEqual(a["task_class"], "summary")
        self.assertIn("auto-routed to executor=kk_mac_local",
                      card["comms"][0]["text"])
        self.assertTrue(res.startswith("queued"))
        # ...and a KK_MAC_LANES=1 runner serves it at claim time
        self.runner.KK_MAC_LANES = True
        self.assertEqual(self.runner.claimable(card), "dispatch")

    def test_keyword_only_card_auto_routes(self):
        card = self._card(title="Summarize the overnight host report")
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertEqual(a["executor"], "kk_mac_local")
        self.assertEqual(a["task_class"], "summary")

    def test_executor_pin_not_rerouted(self):
        card = self._card(action={"executor": "devin",
                                  "task_class": "summary"})
        self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["executor"], "devin")
        self.assertNotIn("lane", card["action"])

    def test_lane_pin_not_rerouted(self):
        card = self._card(title="Summarize the report",
                          action={"lane": "free_lane"})
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertNotIn("executor", a)
        self.assertEqual(a["lane"], "free_lane")

    def test_host_pin_not_rerouted(self):
        card = self._card(title="Summarize the probe report",
                          action={"task_class": "summary",
                                  "host": "idc03"})
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertNotIn("executor", a)
        self.assertEqual(a["lane"], "free_lane")  # 'probe' kw fallback

    @patch("urllib.request.urlopen")
    def test_mutation_intent_not_rerouted(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("jevos down")
        card = self._card(title="Summarize then deploy the restart",
                          action={"task_class": "summary"})
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertNotIn("executor", a)
        self.assertEqual(a["lane"], "devin")

    def test_oversized_prompt_not_rerouted(self):
        card = self._card(title="Summarize the report",
                          action={"task_class": "summary",
                                  "prompt": "x" * 7000})
        self.api.do_action(card, "queue", "devin")
        self.assertNotIn("executor", card["action"])


if __name__ == "__main__":
    unittest.main()
