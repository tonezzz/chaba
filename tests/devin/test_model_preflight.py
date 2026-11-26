"""Preflight guard for devin-dispatch model ids (devin-executor-model-routing).

The devin CLI accepts only ids listed by `devin models list`; a litellm/*
alias or stale pin dies inside the transient unit at launch ('Unknown
model'), burning a claim and minutes of wall clock — the 2026-10-28
tony-macbook Cline/Nest dispatch died on litellm/or-claude-fable-5.1
pre-inference. devin-dispatch.sh validates $DISPATCH_MODEL BEFORE
systemd-run via _model_preflight; these tests drive the real script
end-to-end against a mocked `devin` binary, so no systemd, git, or
network side effects occur:

- rejected id  -> exit 2 with the reason, before repo resolution
- accepted id  -> preflight passes; the run proceeds to repo lookup
  (a bogus repo then exits 1 'unknown repo' — proof it got past the gate)
- unverifiable -> exit 3 (refuses rather than guesses)
- DEVIN_MODEL_PREFLIGHT=0 -> ops escape hatch bypasses the check

The mock emits the same `models list --format json` schema the real CLI
returns (families[].slug/aliases/variants[].model_uid/cost_tier) plus a
text-table fallback matching `devin models list` plain output.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DISPATCH = REPO / "scripts" / "devin" / "devin-dispatch.sh"

# Trimmed mirror of `devin models list --format json` (2026-11-24):
# one free family, one paid family — enough to prove accept/reject and
# the billable-tier warning path.
MODELS_JSON = {
    "families": [
        {
            "family_label": "SWE-2 Flash",
            "family_uid": "swe-2-flash",
            "slug": "swe-2-flash",
            "aliases": [],
            "variants": [
                {"model_uid": "swe-2-flash-medium", "cost_tier": "Free"},
                {"model_uid": "swe-2-flash-high", "cost_tier": "Free"},
            ],
        },
        {
            "family_label": "Claude Fable 5.2",
            "family_uid": "claude-fable-5.2",
            "slug": "claude-fable-5.2",
            "aliases": [],
            "variants": [
                {"model_uid": "claude-fable-5-2-medium",
                 "cost_tier": "High cost"},
            ],
        },
    ]
}

# `devin models list` plain-text shape: 'Name (slug)' family headers,
# 'aliases:' lines, and two-space-indented uid rows.
MODELS_TXT = """\
Available models (2 families)

SWE-2 Flash (swe-2-flash)
  swe-2-flash-medium    SWE-2 Flash Medium  [262K context, Free]
  swe-2-flash-high      SWE-2 Flash High    [262K context, Free]

Claude Fable 5.2 (claude-fable-5.2)
  claude-fable-5-2-medium    Claude Fable 5.2 Medium  [1M context, $8 / 1M Input]
"""

FAKE_DEVIN = """#!/usr/bin/env bash
# Mocked `devin` CLI — only `models list` is implemented.
if [[ "$1" == "models" && "$2" == "list" ]]; then
  MODE="{mode}"
  if [[ "$MODE" == "json" ]]; then
    if [[ "${{3:-}} ${{4:-}}" == "--format json" ]]; then
      cat <<'JSON'
{json}
JSON
      exit 0
    fi
    # JSON-capable CLI still answers the plain form
    cat <<'TXT'
Available models (2 families)

SWE-2 Flash (swe-2-flash)
  swe-2-flash-medium    SWE-2 Flash Medium  [262K context, Free]
TXT
    exit 0
  elif [[ "$MODE" == "text" ]]; then
    # No --format json support: fail that form, answer plain text.
    if [[ "${{3:-}}" == "--format" ]]; then exit 1; fi
    cat <<'TXT'
{txt}
TXT
    exit 0
  else
    # broken: every invocation fails -> preflight must refuse (rc 3)
    exit 1
  fi
fi
exit 0
"""


def _fake_devin(directory: Path, mode: str) -> Path:
    path = directory / "devin"
    path.write_text(FAKE_DEVIN.format(
        mode=mode, json=json.dumps(MODELS_JSON), txt=MODELS_TXT))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _run_dispatch(devin_bin: Path, model: str, extra_env=None):
    """`devin-dispatch start` against a bogus repo: anything past the
    preflight dies at repo resolution (exit 1), so exit codes cleanly
    separate 'rejected by preflight' (2/3) from 'accepted' (1)."""
    env = dict(os.environ)
    env.update({
        "DEVIN_BIN": str(devin_bin),
        "DISPATCH_DIR": str(devin_bin.parent / "dispatch"),
        "DISPATCH_MODEL": model,
        "HOME": str(devin_bin.parent),  # keep any stray wt/task dirs local
    })
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(DISPATCH), "start", "no-such-repo", "preflight probe"],
        capture_output=True, text=True, timeout=60, env=env)


class ModelPreflightTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_litellm_alias_rejected_before_repo_check(self):
        """The exact tony-macbook failure: a litellm/* alias must never
        reach `devin --model` — rejected with rc 2 before systemd-run."""
        fake = _fake_devin(self.dir, "json")
        r = _run_dispatch(fake, "litellm/gemini-3.5-flash-lite")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not accepted by the devin CLI", r.stderr)
        self.assertIn("litellm/", r.stderr)
        # nothing was launched: no task dir, no worktree
        self.assertFalse((self.dir / "dispatch" / "tasks").exists())
        self.assertEqual(
            list(Path(self.dir / "CascadeProjects").glob("dispatch-wt-*")),
            [])

    def test_unknown_bare_id_rejected(self):
        fake = _fake_devin(self.dir, "json")
        r = _run_dispatch(fake, "swe-9-imaginary")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not accepted by the devin CLI", r.stderr)

    def test_listed_free_id_passes_preflight(self):
        """swe-2-flash-medium is the DEVIN_LANE_MODELS free_lane pick —
        it must pass the gate (then die at the bogus repo, rc 1)."""
        fake = _fake_devin(self.dir, "json")
        r = _run_dispatch(fake, "swe-2-flash-medium")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("unknown repo", r.stderr)

    def test_billable_id_passes_with_warning(self):
        """A listed but paid id is allowed (explicit pin = the budget-
        approval path) — the preflight notes the cost tier, doesn't
        block it."""
        fake = _fake_devin(self.dir, "json")
        r = _run_dispatch(fake, "claude-fable-5-2-medium")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("unknown repo", r.stderr)
        self.assertIn("billable", r.stderr)

    def test_text_table_fallback(self):
        """CLIs without --format json: the plain `models list` table
        still proves accept/reject."""
        fake = _fake_devin(self.dir, "text")
        ok = _run_dispatch(fake, "swe-2-flash-medium")
        self.assertEqual(ok.returncode, 1, ok.stderr)
        self.assertIn("unknown repo", ok.stderr)
        bad = _run_dispatch(fake, "litellm/gemini-3.5-flash-lite")
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertIn("not accepted by the devin CLI", bad.stderr)

    def test_unverifiable_cli_refuses(self):
        """`models list` failing entirely -> refuse (rc 3), never
        launch an unverifiable model."""
        fake = _fake_devin(self.dir, "broken")
        r = _run_dispatch(fake, "swe-2-flash-medium")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("cannot verify model", r.stderr)

    def test_preflight_disabled_escape_hatch(self):
        """DEVIN_MODEL_PREFLIGHT=0 is the ops override — a bad id then
        reaches repo resolution like any other launch."""
        fake = _fake_devin(self.dir, "json")
        r = _run_dispatch(fake, "litellm/gemini-3.5-flash-lite",
                          {"DEVIN_MODEL_PREFLIGHT": "0"})
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("unknown repo", r.stderr)


if __name__ == "__main__":
    unittest.main()
