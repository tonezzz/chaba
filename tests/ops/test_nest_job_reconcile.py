#!/usr/bin/env python3
"""Tests for scripts/ops/nest-job-reconcile.py — the read-only
cross-surface consistency check (OPS-0923).

reconcile() is pure: jobs (nest_job mirror rows), packs (Drive marker
state), index (packs-index fold), lease (queue/lease) are injected —
no rclone/WP needed.
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = importlib.util.spec_from_file_location(
    'nest_job_reconcile',
    os.path.join(ROOT, 'scripts', 'ops', 'nest-job-reconcile.py'))
njr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(njr)

NOW = 1_700_000_000.0


def job(slug, status, **meta):
    m = {'status': status}
    m.update(meta)
    return {'id': 1, 'slug': slug, 'title': slug,
            'modified': 'x', 'status': status, 'meta': m}


def codes(rep):
    return {(f['code'], f['subject']) for f in rep['findings']}


def sev(rep, code):
    return [f for f in rep['findings'] if f['code'] == code]


class DoneEvidenceTest(unittest.TestCase):
    """Terminal done must carry result_ref + verified evidence — the
    same contract do_job now enforces at write time; the reconciler
    catches legacy/false dones already in the mirror."""

    def test_clean_done_passes(self):
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', result_ref='packs/p1/done',
                 evidence='packs/p1/done', artifact_verified='true')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertEqual(rep['findings'], [])
        self.assertEqual(rep['summary']['error'], 0)

    def test_done_without_result_ref_is_error(self):
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', evidence='x')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('DONE-NO-RESULT-REF', 'p1'), codes(rep))
        self.assertEqual(rep['summary']['error'], 1)

    def test_done_with_ref_but_no_evidence_is_warn(self):
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', result_ref='packs/p1/done')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('DONE-UNVERIFIED', 'p1'), codes(rep))
        self.assertEqual(rep['summary']['error'], 0)

    def test_done_job_but_pack_not_done(self):
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', result_ref='r',
                 artifact_verified='true')],
            {'p1': {'done': False, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('DONE-NO-PACK-MARKER', 'p1'), codes(rep))

    def test_non_pack_done_skips_pack_checks(self):
        """kind=queue / ad-hoc jobs have no pack dir — done-evidence
        rules still apply, pack-marker checks don't."""
        rep = njr.reconcile(
            [job('misc-job', 'done', result_ref='r',
                 artifact_verified='true')],
            {}, {}, None, now=NOW)
        self.assertEqual(rep['findings'], [])


class PackMirrorDriftTest(unittest.TestCase):
    def test_pack_done_but_job_not_done(self):
        rep = njr.reconcile(
            [job('p1', 'running', pack='p1')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('PACK-DONE-JOB-NOT-DONE', 'p1'), codes(rep))
        # running vs terminal pack also flags the active-side check
        self.assertIn(('ACTIVE-JOB-PACK-TERMINAL', 'p1'), codes(rep))

    def test_pack_done_no_job_at_all(self):
        rep = njr.reconcile(
            [], {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('PACK-TERMINAL-NO-JOB', 'p1'), codes(rep))

    def test_index_done_counts_as_terminal(self):
        """packs-index is advisory but corroborates: index=done with no
        done FILE marker still counts as queue-terminal."""
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', result_ref='r',
                 artifact_verified='true')],
            {'p1': {'done': False, 'failed': False, 'claims': []}},
            {'p1': {'state': 'done', 'ts': NOW, 'worker': 'w'}},
            None, now=NOW)
        self.assertNotIn('DONE-NO-PACK-MARKER',
                         {c for c, _ in codes(rep)})

    def test_pack_failed_job_running_inconsistent(self):
        rep = njr.reconcile(
            [job('p1', 'running', pack='p1')],
            {'p1': {'done': False, 'failed': True, 'claims': []}},
            {}, None, now=NOW)
        self.assertIn(('PACK-FAILED-JOB-INCONSISTENT', 'p1'), codes(rep))

    def test_active_job_with_live_claim_is_clean(self):
        rep = njr.reconcile(
            [job('p1', 'running', pack='p1')],
            {'p1': {'done': False, 'failed': False,
                    'claims': ['worker-1']}},
            {'p1': {'state': 'claim', 'ts': NOW, 'worker': 'worker-1'}},
            None, now=NOW)
        self.assertEqual(rep['findings'], [])

    def test_active_job_no_claim_is_info(self):
        rep = njr.reconcile(
            [job('p1', 'claimed', pack='p1')],
            {'p1': {'done': False, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        f = sev(rep, 'ACTIVE-NO-CLAIM')
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]['severity'], 'info')


class ClaimAndLeaseTest(unittest.TestCase):
    def test_cancelled_job_lingering_claim(self):
        rep = njr.reconcile(
            [job('p1', 'cancelled', pack='p1')],
            {'p1': {'done': False, 'failed': False,
                    'claims': ['dead-worker']}},
            {}, None, now=NOW)
        self.assertIn(('CANCELLED-LINGER-CLAIM', 'p1'), codes(rep))

    def test_fresh_lease_on_terminal_job(self):
        lease = {'worker': 'colab', 'ts': NOW - 30, 'job': 'p1',
                 'phase': 'run'}
        rep = njr.reconcile(
            [job('p1', 'done', pack='p1', result_ref='r',
                 artifact_verified='true')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, lease, now=NOW)
        self.assertIn(('LEASE-ACTIVE-TERMINAL-JOB', 'p1'), codes(rep))

    def test_stale_lease_with_active_jobs(self):
        lease = {'worker': 'colab', 'ts': NOW - 3600, 'job': 'other',
                 'phase': 'run'}
        rep = njr.reconcile(
            [job('p1', 'running', pack='p1')],
            {'p1': {'done': False, 'failed': False,
                    'claims': ['w']}},
            {}, lease, now=NOW, stale_min=20)
        self.assertIn(('LEASE-STALE-WITH-ACTIVE-JOBS', 'queue/lease'),
                      codes(rep))

    def test_lease_for_unknown_job_is_context_only(self):
        """Manifest JOBS.py names don't always map to nest_job slugs —
        an unmatched lease job must not fabricate a finding."""
        lease = {'worker': 'colab', 'ts': NOW - 30,
                 'job': 'manifest-job-x', 'phase': 'run'}
        rep = njr.reconcile(
            [job('p1', 'running', pack='p1')],
            {'p1': {'done': False, 'failed': False,
                    'claims': ['w']}},
            {}, lease, now=NOW)
        self.assertNotIn('LEASE-ACTIVE-TERMINAL-JOB',
                         {c for c, _ in codes(rep)})
        self.assertTrue(rep['lease']['fresh'])


class ShapeTest(unittest.TestCase):
    def test_slug_fallback_join(self):
        """No meta.pack — slug matching a pack dir still joins."""
        rep = njr.reconcile(
            [job('p1', 'done', result_ref='r',
                 artifact_verified='true')],
            {'p1': {'done': True, 'failed': False, 'claims': []}},
            {}, None, now=NOW)
        self.assertEqual(rep['findings'], [])

    def test_empty_inputs(self):
        rep = njr.reconcile([], {}, {}, None, now=NOW)
        self.assertEqual(rep['findings'], [])
        self.assertEqual(rep['summary']['jobs'], 0)

    def test_jobs_without_status_skipped(self):
        rep = njr.reconcile(
            [{'slug': 'note-only', 'meta': {}}], {}, {}, None, now=NOW)
        self.assertEqual(rep['findings'], [])


if __name__ == '__main__':
    unittest.main()
