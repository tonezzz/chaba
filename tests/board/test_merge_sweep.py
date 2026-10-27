"""End-to-end tests for merge-sweep (scripts/board/merge-sweep.py —
card dispatch-merge-sweep).

Builds a bare origin + a 'served' clone + a separate 'runner' clone with
a dispatch session worktree in a tmpdir — the stranded-branch case: the
runner finished work but never reached origin, so the sweep fetches the
head over the runner's path and merges into the served checkout.

Covers: clean merge lands + verified stamp, strict stop-and-report
conflicts (no side taken), dirty worktree flag, failed-run flag,
in-flight skip, stale-running rescue, comms task_id resolution, the
zombie flag, the verified gate (2026-10-09 nest-mgr incident:
exit==0 evidence + real deliverable + auto_done_when, else fail +
requeue), and the verified drain (2026-10-10 kanban-review-auto-close:
verified verify/absent-kind cards close themselves; decide/triage and
open-request cards hold in review, idempotently). No network, no
systemd — all git ops stay in the tmpdir;
the 'remote runner' is exercised through the local code path (identical
git semantics, ssh is only the transport). The task dir fixture writes
exit_code=0 — the evidence tier the verified gate prefers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "merge_sweep", REPO / "scripts" / "board" / "merge-sweep.py")
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)

TID = "20990101-000000-test-sweep"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)


def commit(repo: Path, path: str, content: str, msg: str) -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    git(repo, "add", path)
    r = git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", msg)
    assert r.returncode == 0, r.stderr


class Case(unittest.TestCase):
    """One fixture per test: origin(bare) + served(clone, the merge
    target) + runner(clone) + session worktree + card dir."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {}
        for k in ("DISPATCH_DIR", "CHABA_REPO", "MERGE_SWEEP_TARGETS",
                  "BOARD_API", "ZOMBIE_AGE_H", "ZOMBIE_IDLE_MIN"):
            self._env[k] = os.environ.get(k)
        os.environ["DISPATCH_DIR"] = str(self.tmp / "dispatch")
        os.environ["BOARD_API"] = "http://127.0.0.1:9"  # refuse fast

        # bare origin with a base commit
        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare", "-b",
                            "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        commit(seed, "file.txt", "base\n", "base")
        r = git(seed, "push", "-q", "-u", "origin", "master")
        assert r.returncode == 0, r.stderr

        # the served checkout (merge target) and the runner's clone
        self.served = self.tmp / "served"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.served)], capture_output=True)
        # merges run inside served — needs local identity (global may
        # be unset, e.g. tony-dell has none)
        git(self.served, "config", "user.name", "t")
        git(self.served, "config", "user.email", "t@t")
        self.runner_repo = self.tmp / "runner-repo"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.runner_repo)], capture_output=True)

        # session worktree on the 'runner' (linked wt of runner-repo)
        self.wt = self.tmp / f"dispatch-wt-{TID}"
        r = git(self.runner_repo, "worktree", "add", "-q",
                str(self.wt), "-b", f"dispatch/{TID}", "origin/master")
        assert r.returncode == 0, r.stderr

        # task registry on the 'runner' (local probe reads DISPATCH_DIR)
        task = self.tmp / "dispatch" / "tasks" / TID
        task.mkdir(parents=True)
        (task / "meta.json").write_text(json.dumps(
            {"repo": "chaba", "worktree": str(self.wt),
             "branch": f"dispatch/{TID}",
             "default_branch": "master",
             "unit": f"devin-task-{TID}"}))
        # default exit evidence: a clean exit. The verified gate's other
        # tiers (meta.result, unit, journal, finish comms) are exercised
        # by removing/overwriting this file per test.
        (task / "exit_code").write_text("0\n")
        self.task_dir = task

        # cards dir + merge target map (module-level constants patched)
        self.cards = self.tmp / "cards-repo/docs/ssot/kanban/cards"
        self.cards.mkdir(parents=True)
        self._mod = {
            "CARD_DIR": ms.CARD_DIR, "SERVED": dict(ms.SERVED),
            "API": ms.API, "RENDER": ms.RENDER,
            "ZOMBIE_AGE_S": ms.ZOMBIE_AGE_S,
            "ZOMBIE_IDLE_S": ms.ZOMBIE_IDLE_S,
        }
        ms.CARD_DIR = self.cards
        ms.SERVED = {"chaba": str(self.served)}
        ms.API = "http://127.0.0.1:9"
        ms.RENDER = Path("/nonexistent-render")

    def tearDown(self) -> None:
        for k, v in self._mod.items():
            setattr(ms, k, v)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    # ------------------------------------------------------- helpers
    def write_card(self, cid: str = "test-card", **kw) -> dict:
        card = {"id": cid, "column": "review",
                "action": {"type": "dispatch", "status": "done",
                           "task_id": TID, "repo": "chaba"},
                "comms": []}
        card.update(kw)
        (self.cards / f"{cid}.yml").write_text(
            yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
        return card

    def read_card(self, cid: str = "test-card") -> dict:
        return yaml.safe_load((self.cards / f"{cid}.yml").read_text())

    def remote_has(self, ref: str, path: str) -> bool:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             f"{ref}:{path}"], capture_output=True, text=True)
        return r.returncode == 0

    def remote_master_parents(self) -> int:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "cat-file", "-p",
             "master"], capture_output=True, text=True)
        return r.stdout.count("\nparent ")

    # --------------------------------------------------------- tests
    def test_stranded_branch_merges_and_verifies(self):
        commit(self.wt, "feature.py", "print('hi')\n", "work")
        card = self.write_card()
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertGreaterEqual(self.remote_master_parents(), 2)  # --no-ff
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertTrue(any("merge-sweep" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])

    def test_nothing_produced_fails_and_requeues(self):
        # the nest-mgr repro: clean unit exit, but the branch head is
        # the base tip — zero commits, no outcome doc -> NOT verified;
        # the attempt is marked failed and requeued.
        before = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             "master"], capture_output=True, text=True).stdout.strip()
        card = self.write_card()  # wt head == base — nothing new
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)
        c = self.read_card()
        a = c["action"]
        self.assertIs(a.get("verified"), False)  # checked, NOT verified
        self.assertEqual(a.get("status"), "queued")  # retry path
        # attempts counts claims (mark_start) — the gate failure itself
        # doesn't consume a dispatch slot
        self.assertFalse(a.get("attempts"))
        self.assertNotIn("task_id", a)
        self.assertTrue(a.get("last_failure"))
        self.assertTrue(any("verified gate failed" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        after = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             "master"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(before, after)

    def test_empty_session_on_moved_base_fails_and_stamps(self):
        # the exact 2026-10-25/26 burn (dispatch-empty-closeout-
        # verification-gap): zero commits, origin/master moved on after
        # the worktree was cut — the head is an old base commit on the
        # first-parent chain, NOT delivered work. The gate fails the
        # attempt, requeues, and stamps sweep.zero_commit for the QC
        # scoreboard.
        commit(self.served, "moved.txt", "upstream moved\n", "upstream")
        r = git(self.served, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr
        card = self.write_card()  # wt head == old base commit
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        a = c["action"]
        self.assertIs(a.get("verified"), False)
        self.assertEqual(a.get("status"), "queued")
        self.assertTrue((a.get("sweep") or {}).get("zero_commit"),
                        a.get("sweep"))
        self.assertIn("nothing committed",
                      str(a.get("last_failure") or ""))

    def test_terminal_column_never_touched(self):
        # KNB-0893: a card already in done is terminal — the sweep must
        # not rewrite its workflow fields even when action.status
        # disagrees (a stale checkout shows exactly this shape).
        card = self.write_card(
            column="done",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "done")
        self.assertEqual(c["action"]["status"], "running")

    def test_bookkeeping_write_preserves_updated(self):
        # KNB-0893 vector: a stamp/comms write must NOT fabricate a
        # newer `updated` — on a stale checkout that stamp then wins
        # the card-union scalar merge and resurrects upstream's newer
        # column/status. Workflow mutations (fail_attempt) still bump.
        card = self.write_card(
            column="review",
            updated="2026-10-20 00:00",
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba"})
        ms.stamp("test-card", "probe_flag", "x", dry=False)
        c = self.read_card()
        self.assertEqual(c.get("updated"), "2026-10-20 00:00")
        self.assertEqual((c["action"].get("sweep") or {})
                         .get("probe_flag"), "x")
        # a real workflow mutation still touches updated
        self.assertTrue(ms.fail_attempt(card, "gate evidence", dry=False))
        c = self.read_card()
        self.assertNotEqual(c.get("updated"), "2026-10-20 00:00")
        self.assertIs(c["action"].get("verified"), False)

    def test_failed_unit_work_not_merged_requeued(self):
        # unit crashed after committing — unmerged partial work is not
        # auto-merged; the card requeues with the exit evidence.
        commit(self.wt, "partial.py", "x=1\n", "partial work")
        (self.task_dir / "exit_code").write_text("1\n")
        card = self.write_card()
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "partial.py"))
        a = self.read_card()["action"]
        self.assertIs(a.get("verified"), False)
        self.assertEqual(a.get("status"), "queued")
        self.assertIn("exit_code=1", a.get("last_failure") or "")

    def test_gate_failure_respects_attempt_cap(self):
        # max_attempts counts total dispatches (attempts is bumped at
        # claim): attempts=2 at the default cap -> marked failed, no
        # requeue.
        (self.task_dir / "exit_code").write_text("1\n")
        commit(self.wt, "p.py", "x=1\n", "partial")
        card = self.write_card(
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "attempts": 2})
        ms.sweep_card(card, {}, dry=False)
        a = self.read_card()["action"]
        self.assertEqual(a.get("status"), "failed")
        self.assertIs(a.get("verified"), False)
        self.assertFalse(self.remote_has("master", "p.py"))

    def test_no_exit_record_with_work_holds(self):
        # produced work, mergeable, but no usable exit record anywhere
        # (pre-exit_code era) -> merge lands, verified is withheld and
        # flagged for a human instead of stamped on faith.
        (self.task_dir / "exit_code").unlink()
        commit(self.wt, "legacy.py", "x=1\n", "old-session work")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertTrue(self.remote_has("master", "legacy.py"))
        c = self.read_card()
        self.assertNotEqual(c["action"].get("verified"), True)
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("verify_hold"))

    def test_auto_done_when_defers_to_kanban_act(self):
        # produced work + clean exit but the card's own contract fails —
        # merge lands, verified is deferred to kanban-act.
        commit(self.wt, "feat.py", "x=1\n", "work")
        card = self.write_card(
            auto_done_when=["file_exists:no-such-file-deadbeef"])
        ms.sweep_card(card, {}, dry=False)
        self.assertTrue(self.remote_has("master", "feat.py"))
        c = self.read_card()
        self.assertNotEqual(c["action"].get("verified"), True)
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("verify_deferred"))

    def test_auto_done_when_verified_true_idiom(self):
        # the documented dispatch idiom: a self 'verified_true:' entry
        # counts the a+b gate itself.
        commit(self.wt, "feat2.py", "x=1\n", "work")
        card = self.write_card(auto_done_when=["verified_true:"])
        ms.sweep_card(card, {}, dry=False)
        self.assertIs(self.read_card()["action"].get("verified"), True)

    def test_outcome_doc_only_counts_as_work(self):
        # research sessions can deliver only dispatch-outcome-<tid>.md
        commit(self.wt, f"dispatch-outcome-{TID}.md", "# done\n",
               "outcome")
        card = self.write_card()
        ms.sweep_card(card, {}, dry=False)
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertTrue(
            self.remote_has("master", f"dispatch-outcome-{TID}.md"))

    def test_already_merged_work_verifies(self):
        # branch landed earlier through a merge's second parent: the
        # gate diffs it against that merge's first parent and sees the
        # delivered files.
        commit(self.wt, "landed.py", "x=1\n", "work")
        r = git(self.runner_repo, "push", "-q", "origin",
                f"dispatch/{TID}")
        assert r.returncode == 0, r.stderr
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(other)], capture_output=True)
        git(other, "config", "user.name", "t")
        git(other, "config", "user.email", "t@t")
        r = git(other, "fetch", "-q", "origin", f"dispatch/{TID}")
        assert r.returncode == 0, r.stderr
        r = git(other, "merge", "--no-ff", "--no-edit", "-m", "m",
                "FETCH_HEAD")
        assert r.returncode == 0, r.stderr
        r = git(other, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr
        card = self.write_card()
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertTrue(any("already in" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])

    def test_verified_card_drains_to_done(self):
        # kanban-review-auto-close: a verified review card closes
        # itself — no git work needed (verified implies merged).
        commit(self.wt, "x.py", "x=1\n", "work")
        card = self.write_card(
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "x.py"))
        c = self.read_card()
        self.assertEqual(c["column"], "done")
        self.assertEqual(c["action"]["status"], "done")
        self.assertEqual((c.get("auto_close") or {}).get("by"),
                         "merge-sweep")
        self.assertTrue(any("auto-closed" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        # drained — the next pass is a pure skip
        self.assertFalse(ms.sweep_card(self.read_card(), {}, dry=False))

    def test_verified_stale_running_drains(self):
        # the observed stuck state: merged+verified but status still
        # 'running' and column 'doing' — the already-merged path runs
        # the same close decision and flips both. Post-2026-10-26:
        # verified+running is a field regression, not a stale session —
        # NO stale_running flag/noise on a delivered card.
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "done")
        self.assertEqual(c["action"]["status"], "done")
        self.assertNotIn("stale_running",
                         c["action"].get("sweep") or {})

    def test_verified_session_gone_drains_not_flags(self):
        # the 2026-10-26 nest-node-hardware resurrection: auto-merged +
        # auto-closed at 07:16, then a union-merge/stale-write
        # regression flipped the file back to doing+running while the
        # runner's worktree was already GC'd. The sweep must re-close
        # the card — never stamp stale_running/session_gone on a
        # delivered one (merge-sweep-resurrects-closed-cards).
        self._kill_session()
        card = self.write_card(
            column="doing",
            auto_close={"by": "merge-sweep", "at": "2026-10-26 07:16",
                        "note": "verified — closing itself"},
            comms=[{"at": "2026-10-26 07:16", "from": "chaba",
                    "text": "merge-sweep: verified — auto-closed "
                            "(column -> done)"}],
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "done")
        self.assertEqual(c["action"]["status"], "done")
        sweep = c["action"].get("sweep") or {}
        self.assertNotIn("stale_running", sweep)
        self.assertNotIn("session_gone", sweep)
        self.assertFalse(any("may be gone" in m.get("text", "")
                             for m in c.get("comms") or []), c["comms"])
        # healed — the next pass leaves it alone
        self.assertFalse(ms.sweep_card(self.read_card(), {}, dry=False))

    def test_terminal_column_never_touched(self):
        # a done card is out of scope even when action.status regressed
        # to running — the sweep must not stamp, comment, or rewrite
        # workflow fields on a card it did not open.
        self.write_card(
            column="done",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        before = (self.cards / "test-card.yml").read_text()
        card = self.read_card()
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertEqual((self.cards / "test-card.yml").read_text(),
                         before)

    def test_deliberate_reopen_not_redrained(self):
        # a verified card reopened on purpose — the lifecycle guard's
        # '[lifecycle] bounced done->doing' (or a human 'moved done
        # ->') — owns its workflow fields; the drain must not fight it.
        self._kill_session()
        card = self.write_card(
            column="doing",
            auto_close={"by": "merge-sweep", "at": "2026-10-26 07:16",
                        "note": "verified — closing itself"},
            comms=[
                {"at": "2026-10-26 07:16", "from": "chaba",
                 "text": "merge-sweep: verified — auto-closed "
                         "(column -> done)"},
                {"at": "2026-10-26 08:49", "from": "chaba",
                 "text": "[lifecycle] bounced done->doing — card "
                         "declares a `verify:` criterion but closed "
                         "with no evidence comms."}],
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "doing")
        self.assertNotIn("session_gone", c["action"].get("sweep") or {})

    def test_verified_decide_card_holds_in_review(self):
        # review_kind:decide is Tony's call — verified but never
        # auto-closed; a doing card surfaces into review instead.
        card = self.write_card(
            column="doing", review_kind="decide",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "review")
        self.assertEqual(c["action"]["status"], "done")
        self.assertNotIn("auto_close", c)
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("close_held"))
        # held and stable — the next pass changes nothing, posts nothing
        n_comms = len(self.read_card().get("comms") or [])
        self.assertFalse(ms.sweep_card(self.read_card(), {}, dry=False))
        self.assertEqual(
            len(self.read_card().get("comms") or []), n_comms)

    def test_verified_open_request_holds(self):
        # an open request blocks the close even when everything else
        # is green — same contract kanban-act enforces.
        card = self.write_card(
            requests=[{"id": "q1", "ask": "ok?", "status": "open"}],
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertEqual(c["column"], "review")
        self.assertNotIn("auto_close", c)
        self.assertTrue(any("held in review" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        # the hold explanation posts once, not every pass
        self.assertFalse(ms.sweep_card(self.read_card(), {}, dry=False))

    def test_verified_triage_card_holds(self):
        # triage = sweep-generated cleanup — also a human skim, not
        # auto-closed (only verify/absent closes).
        card = self.write_card(
            review_kind="triage",
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "verified": True})
        ms.sweep_card(card, {}, dry=False)
        c = self.read_card()
        self.assertEqual(c["column"], "review")
        self.assertNotIn("auto_close", c)

    def test_verified_unmerged_commits_flag_not_regated(self):
        # anomalous: a verified stamp but new commits sit on the
        # session branch — flag for a human, never requeue or
        # silently merge work the stamp never covered.
        commit(self.wt, "late.py", "x=1\n", "post-verify commits")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)  # stands
        self.assertNotEqual(c["action"].get("status"), "queued")
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("verified_unmerged"))
        self.assertFalse(self.remote_has("master", "late.py"))

    def test_fresh_verify_auto_closes_on_merge(self):
        # the stamp path closes too — a clean merge + green gate ends
        # with the card in done, not review.
        commit(self.wt, "auto.py", "x=1\n", "work")
        card = self.write_card(review_kind="verify")
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertEqual(c["column"], "done")
        self.assertTrue((c.get("auto_close") or {}).get("note"))

    # --------------------------------------------------- patch relay
    # runner-push-cred-gap (the 2026-10-14 ADA-0673 / idc03 daa0e0a
    # incident): a runner without push creds strands its branch; its
    # close-out relays the head as a git bundle through board-api into
    # $DISPATCH_DIR/patch-inbox — the sweep consumes it like the
    # runner's own remote. And the stamp itself is gated on the head
    # being PROVABLY on origin — a runner-local head never verifies.

    def _relay_bundle(self, cid: str = "test-card") -> str:
        """Export the wt's head the way dr.relay_session does and drop
        it in the patch-inbox with the sidecar board-api writes."""
        head = git(self.wt, "rev-parse", "HEAD").stdout.strip()
        inbox = self.tmp / "dispatch" / "patch-inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        b = dr.export_bundle(self.wt, "origin/master", head, ref="HEAD",
                             out_dir=inbox)
        self.assertIn("path", b, b)
        name = f"{cid}-{head[:10]}.bundle"
        b["path"].rename(inbox / name)
        (inbox / (name + ".json")).write_text(json.dumps(
            {"repo": "chaba", "branch": f"dispatch/{TID}",
             "base": "master", "head": head, "task_id": TID,
             "exit_code": "0", "host": "no-push-runner"}))
        return head

    def _kill_session(self) -> None:
        """Make the runner's session unfindable: no meta, no worktree,
        no branch in any whitelisted repo."""
        shutil.rmtree(self.task_dir)
        shutil.rmtree(self.wt)
        git(self.runner_repo, "worktree", "prune")
        git(self.runner_repo, "branch", "-D", f"dispatch/{TID}")

    def test_relay_bundle_lands_and_verifies(self):
        # runner gone, push impossible — the relayed bundle carries the
        # work to origin anyway, and the stamp is honest about the path
        commit(self.wt, "relay.py", "x=1\n", "work")
        head = self._relay_bundle()
        self._kill_session()
        card = self.write_card()
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertTrue(self.remote_has("master", "relay.py"))
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        # the salvaged session branch lands on origin too — 'the branch
        # is on origin' holds literally, not just 'in base history'
        r = git(self.served, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"{head}", r.stdout)
        self.assertTrue(any("patch-relay" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])

    def test_session_gone_without_relay_still_flags(self):
        # unchanged behavior: no session AND no bundle -> the honest
        # 'may be gone' flag, never a verified stamp (the flag fires;
        # sweep_card's return stays False like before)
        commit(self.wt, "gone.py", "x=1\n", "work")
        self._kill_session()
        card = self.write_card()
        ms.sweep_card(card, {}, dry=False)
        c = self.read_card()
        self.assertNotEqual(c["action"].get("verified"), True)
        self.assertFalse(self.remote_has("master", "gone.py"))
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("session_gone"))

    def test_head_absent_from_origin_is_not_verified(self):
        # the card's headline regression: a merge reported 'landed' but
        # the head is provably NOT on origin (push creds dead) — the
        # verified stamp must be withheld, flag_once'd, never faked.
        commit(self.wt, "x.py", "x=1\n", "work")
        head = git(self.wt, "rev-parse", "HEAD").stdout.strip()
        # the served repo's creds die between fetch and push — merge
        # claims landed but nothing reached origin
        git(self.served, "remote", "set-url", "origin",
            str(self.tmp / "gone.git"))
        fake = {"merged": True,
                "sha": "0" * 40}
        card = self.write_card()
        with mock.patch.object(ms, "merge_strict", return_value=fake):
            self.assertTrue(ms.sweep_card(card, {}, dry=False))
        c = self.read_card()
        self.assertNotEqual(c["action"].get("verified"), True, c)
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("verify_no_origin"), c)
        self.assertTrue(any("not provable on origin" in
                            m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        self.assertFalse(self.remote_has("master", "x.py"))

    def test_conflict_posts_request_not_wrong_merge(self):
        commit(self.wt, "file.txt", "session\n", "session change")
        # upstream moves the same path after the branch was cut
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(other)], capture_output=True)
        commit(other, "file.txt", "upstream\n", "upstream change")
        r = git(other, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        card = self.write_card()
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)
        c = self.read_card()
        # master still carries upstream — no side was silently taken
        body = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:file.txt"], capture_output=True, text=True).stdout
        self.assertIn("upstream", body)
        reqs = c.get("requests") or []
        self.assertTrue(any(r.get("id") == "merge-conflict"
                            and "file.txt" in (r.get("ask") or "")
                            for r in reqs), reqs)
        self.assertNotEqual(c["action"].get("verified"), True)
        # a second sweep doesn't raise a duplicate while it stays open
        card2 = self.read_card()
        ms.sweep_card(card2, {}, dry=False)
        c2 = self.read_card()
        self.assertEqual(
            sum(1 for r in c2.get("requests") or []
                if str(r.get("id", "")).startswith("merge-conflict")), 1)

    def _commit_symlink(self, name: str, target: str,
                        msg: str) -> None:
        os.symlink(target, self.wt / name)
        git(self.wt, "add", name)
        r = git(self.wt, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-qm", msg)
        assert r.returncode == 0, r.stderr

    def test_venv_symlink_shadow_blocks_merge(self):
        # the 2026-10-10 incident: `.venv/` in .gitignore never matched
        # the committed `.venv` SYMLINK — the guard must hold the merge.
        commit(self.wt, ".gitignore", ".venv/\n", "ignore venv dir")
        self._commit_symlink(".venv", "/nonexistent/venv", "worktree venv")
        commit(self.wt, "real.py", "x=1\n", "real work")
        card = self.write_card()
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", ".venv"))
        self.assertFalse(self.remote_has("master", "real.py"))
        c = self.read_card()
        self.assertNotEqual(c["action"].get("verified"), True)
        head = dr._rev_parse(self.runner_repo, f"dispatch/{TID}") or ""
        self.assertEqual((c["action"].get("sweep") or {})
                         .get("shadow_blocked"), head[:12])
        self.assertTrue(any("shadow" in m.get("text", "")
                            and ".venv" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        # same head — next pass does not re-merge or re-post
        n_comms = len(c.get("comms") or [])
        self.assertFalse(ms.sweep_card(self.read_card(), {}, dry=False))
        self.assertEqual(len(self.read_card().get("comms") or []),
                         n_comms)

    def test_dirpattern_file_shadow_blocks_merge(self):
        # a plain file whose name is ignored only as a directory —
        # `.venv/` covers `cache/` here — is the same shadow class.
        commit(self.wt, ".gitignore", "cache/\n", "ignore cache dir")
        commit(self.wt, "cache", "not a dir\n", "oops a file")
        commit(self.wt, "ok.py", "x=1\n", "real work")
        card = self.write_card()
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "cache"))
        c = self.read_card()
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("shadow_blocked"))
        self.assertTrue(any("cache/" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])

    def test_shadow_fixed_branch_merges_next_pass(self):
        # after flagging, a new head without the shadow must merge —
        # the stamp is head-keyed, not permanent.
        commit(self.wt, ".gitignore", ".venv/\n", "ignore")
        self._commit_symlink(".venv", "/nonexistent", "bad")
        card = self.write_card()
        ms.sweep_card(card, {}, dry=False)
        self.assertTrue((self.read_card()["action"].get("sweep") or {})
                        .get("shadow_blocked"))
        # fix: untrack the symlink (bare rule added too, like 172f25e)
        git(self.wt, "rm", "-q", "--cached", ".venv")
        os.unlink(self.wt / ".venv")
        commit(self.wt, ".gitignore", ".venv/\n.venv\n", "bare name")
        commit(self.wt, "good.py", "x=1\n", "work")
        self.assertTrue(ms.sweep_card(self.read_card(), {}, dry=False))
        self.assertTrue(self.remote_has("master", "good.py"))
        self.assertFalse(self.remote_has("master", ".venv"))
        self.assertIs(self.read_card()["action"].get("verified"), True)

    def test_dirty_worktree_flagged_not_fetched(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        (self.wt / "leftover.md").write_text("uncommitted\n")
        card = self.write_card()
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "feature.py"))
        c = self.read_card()
        self.assertTrue(any("dirty" in m.get("text", "")
                            for m in c.get("comms") or []))
        self.assertEqual(
            (c["action"].get("sweep") or {}).get("dirty"), 1)

    def test_failed_run_flagged_not_merged(self):
        commit(self.wt, "partial.py", "x=1\n", "partial")
        card = self.write_card(
            action={"type": "dispatch", "status": "failed",
                    "task_id": TID, "repo": "chaba"})
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "partial.py"))
        c = self.read_card()
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("failed_noted"))

    def test_running_active_skipped(self):
        commit(self.wt, "live.py", "x=1\n", "wip")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        active = {TID: {"unit": f"devin-task-{TID}", "age_s": 60,
                        "idle_s": 5}}
        self.assertFalse(ms.sweep_card(card, active, dry=False))
        self.assertFalse(self.remote_has("master", "live.py"))

    def test_stale_running_branch_rescued(self):
        commit(self.wt, "done.py", "x=1\n", "finished-but-unreported")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertTrue(self.remote_has("master", "done.py"))
        c = self.read_card()
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("stale_running"))
        self.assertIs(c["action"].get("verified"), True)

    def test_task_id_from_comms(self):
        commit(self.wt, "comms.py", "x=1\n", "work")
        card = {"id": "test-card", "column": "review",
                "action": {"type": "dispatch", "status": "done",
                           "runner": "nowhere"},
                "comms": [{"at": "2026-01-01 00:00", "from": "nowhere",
                           "text": f"started devin-task-{TID} on "
                                   f"nowhere (dispatch)"}]}
        (self.cards / "test-card.yml").write_text(
            yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
        # prove tid resolved from comms and the merge pipeline ran —
        # the 'nowhere' runner can't really fetch, so stub the
        # transport to the local path (same git semantics)
        probed = {}
        orig_probe, orig_fetch = ms.session_probe, ms.fetch_session

        def spy_probe(host, tid):
            probed["tid"] = tid
            return orig_probe("", tid)

        def spy_fetch(repo, host, probe):
            return orig_fetch(repo, "", probe)
        ms.session_probe, ms.fetch_session = spy_probe, spy_fetch
        try:
            ms.sweep_card(card, {}, dry=False)
        finally:
            ms.session_probe, ms.fetch_session = orig_probe, orig_fetch
        self.assertEqual(probed.get("tid"), TID)
        self.assertTrue(self.remote_has("master", "comms.py"))

    def test_zombie_flag_once(self):
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        host_units = {"mn01": [{"task": TID,
                                "unit": f"devin-task-{TID}.service",
                                "age_s": 30 * 3600,
                                "idle_s": 3 * 3600}]}
        n = ms.sweep_zombies(host_units, {TID: card}, dry=False)
        self.assertEqual(n, 1)
        c = self.read_card()
        self.assertTrue(any("zombie" in m.get("text", "")
                            for m in c.get("comms") or []))
        # second sweep — already flagged, no repeat
        card2 = self.read_card()
        n2 = ms.sweep_zombies(host_units, {TID: card2}, dry=False)
        self.assertEqual(n2, 0)

    def test_runner_probe_feeds_script_on_stdin(self):
        # regression: `python3 -` reads the program from stdin — an
        # earlier version never passed input= so every probe silently
        # ran an empty program and returned {}
        res = ms.runner_probe("", "import json;print(json.dumps({'ok':1}))")
        self.assertEqual(res, {"ok": 1})
        res = ms.runner_probe("", "import json,sys;"
                                  "print(json.dumps({'a':sys.argv[1]}))",
                              "hello")
        self.assertEqual(res, {"a": "hello"})

    def test_zombie_below_threshold_ignored(self):
        card = self.write_card()
        host_units = {"mn01": [{"task": TID, "unit": "u",
                                "age_s": 7 * 3600,   # old enough…
                                "idle_s": 60}]}       # …but still alive
        n = ms.sweep_zombies(host_units, {TID: card}, dry=False)
        self.assertEqual(n, 0)


class TaskIdReTest(unittest.TestCase):
    """TASK_ID_RE must resolve both tid shapes from comms: devin-dispatch
    20261026-173617-<slug> AND runner-agent OpenCode lanes
    <card-id>-<epoch> (the 2026-10-26 devnest-fl-pilot-report stranded
    branch — finish consumed state.json before the sweep merged, and the
    comms fallback couldn't parse the opencode tid)."""

    def _hit(self, text):
        m = ms.TASK_ID_RE.search(text)
        return m.group(1) if m else None

    def test_devin_dispatch_tid(self):
        self.assertEqual(
            self._hit("started devin-task-20261026-173617-pilot-classes-1"
                      "-docs-config-ch on idc02 (dispatch)"),
            "20261026-173617-pilot-classes-1-docs-config-ch")

    def test_opencode_lane_tid(self):
        self.assertEqual(
            self._hit("started devin-task-devnest-fl-pilot-report-"
                      "1793011692 on tony-dell (dispatch)"),
            "devnest-fl-pilot-report-1793011692")

    def test_opencode_probe_tid(self):
        self.assertEqual(
            self._hit("devin-task-opencode-closeout-probe-dell-"
                      "1792968507"),
            "opencode-closeout-probe-dell-1792968507")

    def test_no_false_positives(self):
        for s in ("devin-task-short-123", "devin-task-abc",
                  "no unit here", "devin-task-123"):
            self.assertIsNone(self._hit(s))


if __name__ == "__main__":
    unittest.main()
