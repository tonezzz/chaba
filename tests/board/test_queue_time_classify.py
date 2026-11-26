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

    def test_audit_lead_title_classifies_free_lane(self):
        """classifier-readonly-audit-class-reroute: an audit-class
        lead-in title routes to free_lane at queue time."""
        card = {"id": "c1",
                "title": "Audit unlanded Oct 6 dispatch artifacts "
                         "on Dell mirror",
                "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "free_lane")
        self.assertIn("kw:audit-ro", card["comms"][0]["text"])
        self.assertTrue(res.startswith("queued"))


class AuditRoClassifyTest(unittest.TestCase):
    """classifier-readonly-audit-class-reroute (parent
    devin-usage-reduction): titles that LEAD with
    audit/assessment/review/investigate/sweep route to free_lane
    (kw:audit-ro, conf 1.0) unless the TITLE carries a mutation verb.
    Title-scoped only — spec bodies are never scanned; explicit
    action.lane and the timer-alert pin keep precedence; the vendored
    runner-agent copy must agree."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.ra = _load("runner-agent")

    def setUp(self):
        # jevos is not under test — force the devin-safe fallback so
        # non-matching titles resolve identically offline.
        self._p = patch("urllib.request.urlopen",
                        side_effect=OSError("jevos stubbed"))
        self._p.start()
        self.addCleanup(self._p.stop)

    def _lane(self, title, **card):
        c = {"id": "a1", "title": title, "action": {}}
        c.update(card)
        return self.dr.classify_lane(c, with_detail=True)

    def test_audit_slug_and_bracket_tag_free_lane(self):
        for title in ("audit-miss-unlanded-oct06-dispatch-artifacts",
                      "audit-oc-mutating-command-0b3n5bce",
                      "[audit] mutating_command in opencode session X"):
            lane, src, conf = self._lane(title)
            self.assertEqual((lane, src, conf),
                             ("free_lane", "kw:audit-ro", 1.0), title)

    def test_lead_stems_free_lane(self):
        for title in ("Assess sys-mon coverage",
                      "Audit unlanded Oct 6 dispatch artifacts "
                      "on Dell mirror",
                      "Investigate devin-handoff job-ledger "
                      "terminal writes",
                      "Sweep stale mddb endpoint 100.74.146.0",
                      "assessment of queue starvation",
                      "[p1] review retention policy"):
            lane, src, conf = self._lane(title)
            self.assertEqual((lane, src), ("free_lane", "kw:audit-ro"),
                             title)

    def test_mutation_verb_in_title_vetoes(self):
        """'audit X then fix Y' is mutation work — the title veto
        keeps it off the read-only lane (spec bodies never scanned,
        so only TITLE verbs count)."""
        for title in ("Audit logs then fix the shipper",
                      "Assess coverage then deploy the fix",
                      "Review the rollout and create the patch",
                      "Investigate the leak and implement a guard",
                      "Sweep stale cards and merge the results"):
            lane, src, conf = self._lane(title)
            self.assertNotEqual((lane, src),
                                ("free_lane", "kw:audit-ro"), title)
        lane, src, conf = self._lane("Audit logs then fix the shipper")
        self.assertEqual((lane, src), ("devin", "fallback"))

    def test_fix_first_title_not_rerouted(self):
        lane, src, conf = self._lane("Fix audit-cast runaway guard")
        self.assertNotEqual((lane, src), ("free_lane", "kw:audit-ro"))

    def test_single_hyphen_component_name_not_rerouted(self):
        """vcast-audit-cast regression: 'audit-cast' names a component,
        not an audit task — the slug form needs >=2 hyphens."""
        lane, src, conf = self._lane(
            "audit-cast runaway guard fails — CB_RSS unbound variable")
        self.assertNotEqual((lane, src), ("free_lane", "kw:audit-ro"))

    def test_explicit_lane_wins(self):
        lane, src, conf = self.dr.classify_lane(
            {"title": "Audit unlanded dispatch artifacts",
             "action": {"lane": "devin"}}, with_detail=True)
        self.assertEqual((lane, src), ("devin", "explicit"))

    def test_timer_alert_pin_still_wins(self):
        lane, src, conf = self.dr.classify_lane(
            {"title": "Audit why the timer fails",
             "tags": ["timer-alert", "by:timer-sentinel"],
             "action": {}}, with_detail=True)
        self.assertEqual((lane, src), ("free_lane", "timer-alert"))

    def test_non_matching_title_jevos_fallback_unchanged(self):
        lane, src, conf = self._lane("Random ambiguous thing")
        self.assertEqual((lane, src, conf), ("devin", "fallback", 0.0))

    def test_spec_body_audit_mention_not_rerouted(self):
        """Only the TITLE decides — a mutation card whose spec says
        'audit X' must not reroute."""
        lane, src, conf = self._lane(
            "Ship the new dispatch pipeline",
            spec="first audit the current artifacts, then fix the "
                 "shipper and deploy")
        self.assertNotEqual((lane, src), ("free_lane", "kw:audit-ro"))

    def test_runner_agent_parity(self):
        """The vendored runner-agent classifier must agree on every
        audit-ro shape (dr's jevos is stubbed -> same 'devin')."""
        for title in ("audit-miss-unlanded-oct06-dispatch-artifacts",
                      "[audit] mutating_command in opencode session X",
                      "Assess sys-mon coverage",
                      "Audit logs then fix the shipper",
                      "audit-cast runaway guard fails — CB_RSS "
                      "unbound variable",
                      "Random ambiguous thing"):
            card = {"title": title, "action": {}}
            self.assertEqual(self.dr.classify_lane(card),
                             self.ra.classify_lane(card), title)


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
                "column": "backlog", "action": a}
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

    def test_oversized_prompt_not_routed(self):
        card = self._card(title="Summarize the report",
                          action={"task_class": "summary",
                                  "prompt": "x" * 7000})
        self.api.do_action(card, "queue", "devin")
        self.assertNotIn("executor", card["action"])


class ClaudeRouteUnitTest(unittest.TestCase):
    """dr.claude_route — the bounded-class auto-route to executor=claude
    (auto-route-bounded-card-classes-to-execu, PR #187 follow-up).
    Admitted: verify_only, repo_fix (needs verify-command evidence),
    report_triage. Excluded: any routing/host/label pin, deploy/push/
    prod intent, cross-repo mentions, unbounded classes."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")

    def _card(self, **kw):
        a = {"type": "dispatch"}
        a.update(kw.pop("action", {}))
        card = {"id": "cl1", "title": kw.pop("title", "t"),
                "action": a}
        card.update(kw)
        return card

    def test_verify_only_inferred(self):
        c = self._card(
            title="Verify-only: run pytest tests/board -q and confirm "
                  "green. Do not modify anything.")
        self.assertEqual(self.dr.claude_route(c), "verify_only")

    def test_verify_command_alone_is_verify_only(self):
        c = self._card(title="Run pytest tests/board -q and report "
                              "whether it passes")
        self.assertEqual(self.dr.claude_route(c), "verify_only")

    def test_repo_fix_needs_verify_command(self):
        c = self._card(title="Fix the off-by-one in parse_date; verify "
                              "with pytest tests/board/test_x.py")
        self.assertEqual(self.dr.claude_route(c), "repo_fix")
        # the verify step is what makes the class bounded — a fix
        # ask with no runnable check stays on the normal lanes
        c = self._card(title="Fix the typo in README")
        self.assertEqual(self.dr.claude_route(c), "")
        # a declared verify_* contract field counts as the evidence
        c = self._card(title="Fix the flaky retry",
                       action={"task_class": "repo_fix",
                               "verify_contains": "all tests pass"})
        self.assertEqual(self.dr.claude_route(c), "repo_fix")

    def test_report_triage_inferred(self):
        for title in ("Triage the overnight failures and write a report",
                      "Write a postmortem for the idc03 outage",
                      "Summarize yesterday's runner defers"):
            c = self._card(title=title)
            self.assertEqual(self.dr.claude_route(c),
                             "report_triage", title)

    def test_declared_task_class_routes(self):
        c = self._card(title="Check the timer",
                       action={"task_class": "verify_only"})
        self.assertEqual(self.dr.claude_route(c), "verify_only")

    def test_unadmitted_task_class_not_routed(self):
        c = self._card(title="Check the timer",
                       action={"task_class": "code_mutation"})
        self.assertEqual(self.dr.claude_route(c), "")
        # kk_mac classes are not claude classes either
        c = self._card(title="Summarize the report",
                       action={"task_class": "summary"})
        self.assertEqual(self.dr.claude_route(c), "")

    def test_routing_pins_win(self):
        for pin in ({"executor": "devin"}, {"executor": "claude"},
                    {"lane": "free_lane"}):
            c = self._card(title="Verify-only: check the timer",
                           action=pin)
            self.assertEqual(self.dr.claude_route(c), "", pin)

    def test_host_pins_not_routed(self):
        for pin in ("host", "target_host", "runner"):
            c = self._card(title="Verify-only: check the timer",
                           action={pin: "idc03"})
            self.assertEqual(self.dr.claude_route(c), "", pin)

    def test_labels_not_routed(self):
        # capability labels need a declared host set — the classifier
        # can't prove a claude-capable runner satisfies them
        c = self._card(title="Verify-only: check the timer",
                       action={"labels": ["gpu"]})
        self.assertEqual(self.dr.claude_route(c), "")

    def test_deploy_push_prod_not_routed(self):
        for title in ("Deploy the caddy config and verify it",
                      "Push the fix branch to origin",
                      "Restart the mddb service and verify health",
                      "Merge the PR into master"):
            c = self._card(title=title)
            self.assertEqual(self.dr.claude_route(c), "", title)

    def test_cross_repo_not_routed(self):
        # own repo is chaba (default) — naming another repo keeps the
        # card on the normal lanes
        c = self._card(title="Fix the ada-voice retry bug; verify with "
                              "pytest")
        self.assertEqual(self.dr.claude_route(c), "")
        # ...but naming only the card's own repo is fine
        c = self._card(title="Fix the chaba retry bug; verify with "
                              "pytest",
                       action={"repo": "chaba"})
        self.assertEqual(self.dr.claude_route(c), "repo_fix")

    def test_unbounded_ask_not_routed(self):
        c = self._card(title="Redesign the dispatch claim loop")
        self.assertEqual(self.dr.claude_route(c), "")

    def test_script_type_not_routed(self):
        c = self._card(title="Verify-only: check the timer",
                       action={"type": "script"})
        self.assertEqual(self.dr.claude_route(c), "")


class ClaudeAutoRouteQueueTest(unittest.TestCase):
    """Queue-time auto-route: /action do=queue stamps
    executor=claude + task_class + executor_source=queue for admitted
    bounded classes; a CLAUDE_LANES-ready runner serves it, every other
    host falls back to the normal lanes (try-first, never starves)."""

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
                       ("KK_MAC_LANES", "CLAUDE_LANES", "CLAUDE_DISPATCH",
                        "DISPATCH", "LABELS", "HOST")}
        self._saved_fn = {k: getattr(r, k) for k in
                          ("push_capable", "shutil_which",
                           "claude_lane_ready")}
        r.HOST = "clhost"
        r.LABELS = set()
        r.push_capable = lambda repo: True
        r.shutil_which = lambda name: True
        r.DISPATCH = str(REPO / "scripts/board/runner-agent.py")
        r.CLAUDE_DISPATCH = str(REPO / "scripts/board/runner-agent.py")
        r.claude_lane_ready = lambda: False

    def tearDown(self):
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(self.runner, k, v)

    def _card(self, **kw):
        a = {"type": "dispatch"}
        a.update(kw.pop("action", {}))
        card = {"id": "clq1", "title": kw.pop("title", "t"),
                "column": "backlog", "action": a}
        card.update(kw)
        return card

    def test_verify_card_auto_routes_with_source(self):
        card = self._card(
            title="Verify-only: run pytest tests/board -q; do not "
                  "modify")
        res = self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(a["executor"], "claude")
        self.assertEqual(a["executor_source"], "queue")
        self.assertEqual(a["task_class"], "verify_only")
        self.assertIn("auto-routed to executor=claude",
                      card["comms"][0]["text"])
        self.assertTrue(res.startswith("queued"))

    def test_repo_fix_card_auto_routes(self):
        card = self._card(title="Fix the flaky timer check; verify with "
                                "pytest tests/board -q")
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertEqual(a["executor"], "claude")
        self.assertEqual(a["task_class"], "repo_fix")

    def test_kk_mac_class_still_wins_first(self):
        # kk_mac is the cheaper bounded lane — a summarize card pins
        # kk_mac_local, never claude
        card = self._card(title="Summarize the overnight host report",
                          action={"task_class": "summary",
                                  "prompt": "Summarize it"})
        self.api.do_action(card, "queue", "devin")
        a = card["action"]
        self.assertEqual(a["executor"], "kk_mac_local")
        self.assertNotIn("executor_source", a)

    def test_exclusion_cards_not_rerouted(self):
        for title, action in (
                ("Deploy the fix and verify", {}),
                ("Verify-only: check the timer",
                 {"labels": ["gpu"]}),
                ("Verify-only: check the timer",
                 {"target_host": "idc02"}),
                ("Verify-only: check the timer",
                 {"executor": "devin"})):
            card = self._card(title=title, action=action)
            self.api.do_action(card, "queue", "devin")
            a = card["action"]
            self.assertNotEqual(a.get("executor"), "claude",
                                (title, action))
            self.assertNotIn("executor_source", a)

    def test_auto_pin_claimable_on_ready_host(self):
        card = self._card(
            title="Verify-only: run pytest tests/board -q; do not "
                  "modify")
        self.api.do_action(card, "queue", "devin")
        r = self.runner
        r.CLAUDE_LANES = True
        r.claude_lane_ready = lambda: True
        self.assertEqual(r.claimable(card), "dispatch")
        # a declared executor=claude card is NOT auto — same surface,
        # different contract (covered by ClaudeExecutorContractTest)

    def test_auto_pin_falls_back_on_unready_host(self):
        """The try-first guarantee: a queue-pinned auto card on a host
        that can't serve the lane is judged as undeclared — it takes
        the normal (devin) gates instead of starving or deferring."""
        card = self._card(
            title="Verify-only: run pytest tests/board -q; do not "
                  "modify")
        self.api.do_action(card, "queue", "devin")
        r = self.runner
        r.CLAUDE_LANES = False
        r.claude_lane_ready = lambda: False
        self.assertEqual(r.claimable(card), "dispatch")
        self.assertEqual(r.executor_defer_reason(card), "")

    def test_declared_claude_still_fails_closed(self):
        """No executor_source = author pin = the strict contract: an
        unservable declared claude card stays queued with the defer
        note — it never falls back."""
        card = self._card(title="do a thing",
                          action={"executor": "claude",
                                  "status": "queued"})
        r = self.runner
        r.CLAUDE_LANES = False
        r.claude_lane_ready = lambda: False
        self.assertEqual(r.claimable(card), "")
        self.assertIn("never silently fall back",
                      r.executor_defer_reason(card))


if __name__ == "__main__":
    unittest.main()
