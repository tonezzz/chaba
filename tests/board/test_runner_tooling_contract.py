"""Contract tests for lane retirement and runner-tooling pins.

Two drift failure modes from the 2026-11-20 Jules purge:

1. A lane is marked REMOVED in ssot.devnest-lanes.yml but a downstream
   allowlist still carries it. What actually merged upstream deleted
   scripts/jules/jules.py while runner-agent.py still had 107 Jules refs
   — a half-purge that every self-heal sync then propagated faithfully.
2. A deployable tool changed without its content pin being bumped.
   sync-runner-tools.sh refuses an unpinned/mismatched source, so the
   fleet silently keeps running the previous build.

Pure source / AST / JSON inspection: no network, git, or systemd.

No network, no git, no systemd — every seam is a file read.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANES = REPO / "docs" / "ssot" / "infrastructure" / "ssot.devnest-lanes.yml"
SYNC_SCRIPT = REPO / "scripts" / "devin" / "sync-runner-tools.sh"
MANIFEST = REPO / "scripts" / "devin" / "runner-tooling.manifest.json"

RETIRE_RE = re.compile(r"^\s*(removed|retired|deprecated|disabled|dead)\b",
                       re.I)
SYNC_RE = re.compile(r'^_sync_one\s+"([^"]+)"\s+"([^"]+)"')


def retired_lanes() -> list[str]:
    """Lane ids whose SSOT status declares the lane gone."""
    import yaml

    doc = yaml.safe_load(LANES.read_text()) or {}
    lanes = doc.get("lanes") or {}
    return sorted(
        key for key, val in lanes.items()
        if isinstance(val, dict)
        and RETIRE_RE.match(str(val.get("status") or ""))
    )


def literal_strings(node: ast.AST) -> set[str]:
    """String members of a literal set/list/tuple, or keys of a dict."""
    out: set[str] = set()
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.add(elt.value)
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.add(key.value)
    return out


def module_assignments(path: Path) -> dict[str, ast.AST]:
    """Top-level NAME = <literal> assignments, keyed by name."""
    tree = ast.parse(path.read_text())
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value
    return out


def sync_targets() -> list[tuple[str, str]]:
    """(source, dest) pairs from sync-runner-tools.sh's _sync_one calls."""
    return [(m.group(1), m.group(2))
            for line in SYNC_SCRIPT.read_text().splitlines()
            if (m := SYNC_RE.match(line))]


class RetiredLaneContractTest(unittest.TestCase):
    def test_ssot_still_declares_jules_retired(self):
        # If someone edits the SSOT back to "live", the contract below
        # loses its subject — fail loudly instead of passing vacuously.
        self.assertIn("jules", retired_lanes())

    def test_retired_lanes_absent_from_executor_tables(self):
        tables = {
            "scripts/board/dispatch_repos.py": ("EXECUTORS",
                                                "LANE_EXECUTORS"),
            "scripts/board/runner-agent.py": ("EXECUTORS",),
        }
        retired = set(retired_lanes())
        for rel, names in tables.items():
            assigns = module_assignments(REPO / rel)
            for name in names:
                self.assertIn(name, assigns, f"{rel} lost table {name}")
                granted = literal_strings(assigns[name])
                for lane in retired:
                    self.assertNotIn(
                        lane, granted,
                        f"{rel}:{name} still grants retired lane {lane!r}")

    def test_retired_lanes_absent_from_board_api_allowlist(self):
        tree = ast.parse((REPO / "scripts" / "board" / "board-api.py").read_text())
        allowed: set[str] = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Compare)
                    and any(isinstance(op, ast.NotIn) for op in node.ops)
                    and isinstance(node.left, ast.Name)
                    and node.left.id == "lane"):
                for comparator in node.comparators:
                    allowed |= literal_strings(comparator)
        self.assertTrue(allowed, "board-api lane allowlist not found")
        for lane in retired_lanes():
            self.assertNotIn(
                lane, allowed,
                f"board-api still accepts new pins on retired lane {lane!r}")

    def test_retired_lane_client_scripts_absent(self):
        for lane in retired_lanes():
            client_dir = REPO / "scripts" / lane
            self.assertFalse(
                client_dir.exists(),
                f"retired lane {lane!r} still has {client_dir.relative_to(REPO)}/")


class ToolingPinTest(unittest.TestCase):
    def setUp(self):
        manifest = json.loads(MANIFEST.read_text())
        self.pins = manifest["tools"]

    def test_every_synced_tool_is_pinned(self):
        targets = sync_targets()
        self.assertTrue(targets, "no _sync_one calls found — parser drifted")
        self.assertEqual({src for src, _ in targets},
                         {v["source"] for v in self.pins.values()},
                         "manifest sources must cover exactly the synced tools")
        self.assertEqual({Path(dest).name for _, dest in targets},
                         {v["dest"] for v in self.pins.values()},
                         "manifest dests must cover exactly the installed names")

    def test_pin_hashes_match_sources(self):
        for key, pin in self.pins.items():
            source = REPO / pin["source"]
            self.assertTrue(source.exists(), f"{key}: missing {pin['source']}")
            got = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(
                got, pin["sha256"],
                f"{key}: source changed without a pin bump — update "
                f"{MANIFEST.relative_to(REPO)} in the same commit")

    def test_pin_hashes_are_full_sha256(self):
        for key, pin in self.pins.items():
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$",
                             f"{key}: pin must be a full lowercase sha256")


class ToolingPinGateMergeTest(unittest.TestCase):
    """Regression for the ops-1036 conflict-resolution shape (OPS-1326).

    Both parents are individually consistent: master has its source and
    matching pin, the session branch has its source and matching pin.
    Taking the SOURCE from one parent and the MANIFEST (pins) from the
    other merges cleanly but leaves a stale pin that sync-runner-tools.sh
    refuses to install — all six hosts drift. The husky pre-merge-commit
    gate and the merge-sweep contract check must catch that committed
    pair, not either side alone.

    Pure-function tests: no git, network, or systemd.
    """

    SOURCE = "scripts/board/runner-agent.py"
    UNRELATED = "docs/readme.md"
    BRANCH_SHA = hashlib.sha256(b"branch source bytes").hexdigest()
    MASTER_SHA = hashlib.sha256(b"master source bytes").hexdigest()

    @classmethod
    def setUpClass(cls):
        # scripts/board is not on sys.path under pytest; load by path.
        spec = importlib.util.spec_from_file_location(
            "chaba_tooling_pin_gate",
            REPO / "scripts" / "board" / "tooling_pin_gate.py")
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)

    @classmethod
    def _pins(cls, sha):
        return {"runner_agent": (cls.SOURCE, sha)}

    def test_source_from_branch_pins_from_master_blocks(self):
        master_pins = self._pins(self.MASTER_SHA)
        merged_pins = dict(master_pins)              # manifest from master
        bad = self.gate.find_mismatches(
            merged_pins, master_pins,
            lambda src: self.BRANCH_SHA,             # source from branch
            {self.SOURCE, self.gate.MANIFEST})
        self.assertEqual([(k, got) for k, _, got, _ in bad],
                         [("runner_agent", self.BRANCH_SHA)])

    def test_source_from_master_pins_from_branch_blocks(self):
        master_pins = self._pins(self.MASTER_SHA)
        merged_pins = self._pins(self.BRANCH_SHA)    # manifest from branch
        bad = self.gate.find_mismatches(
            merged_pins, master_pins,
            lambda src: self.MASTER_SHA,             # source from master
            {self.SOURCE, self.gate.MANIFEST})
        self.assertEqual([key for key, _, _, _ in bad], ["runner_agent"])

    def test_both_sides_from_branch_is_clean(self):
        master_pins = self._pins(self.MASTER_SHA)
        merged_pins = self._pins(self.BRANCH_SHA)
        bad = self.gate.find_mismatches(
            merged_pins, master_pins,
            lambda src: self.BRANCH_SHA,
            {self.SOURCE, self.gate.MANIFEST})
        self.assertEqual(bad, [])

    def test_untouched_inherited_mismatch_does_not_block(self):
        # master is already stale and this commit touches only docs —
        # an inherited mismatch must block unrelated work.
        master_pins = self._pins("stale-pin-from-master")
        bad = self.gate.find_mismatches(
            dict(master_pins), dict(master_pins),
            lambda src: self.BRANCH_SHA, {self.UNRELATED})
        self.assertEqual(bad, [])

    def test_source_change_without_pin_bump_blocks(self):
        head_pins = self._pins(self.MASTER_SHA)
        bad = self.gate.find_mismatches(
            dict(head_pins), head_pins,
            lambda src: self.BRANCH_SHA, {self.SOURCE})
        self.assertEqual([key for key, _, _, _ in bad], ["runner_agent"])

    def test_pin_change_without_source_change_blocks(self):
        head_pins = self._pins(self.MASTER_SHA)
        bad = self.gate.find_mismatches(
            self._pins(self.BRANCH_SHA), head_pins,
            lambda src: self.MASTER_SHA, {self.gate.MANIFEST})
        self.assertEqual([key for key, _, _, _ in bad], ["runner_agent"])

    def test_relevant_paths_covers_manifest_and_sources(self):
        pins = self._pins(self.MASTER_SHA)
        self.assertEqual(self.gate.relevant_paths(pins),
                         {self.gate.MANIFEST, self.SOURCE})

    def test_parse_pins_tolerates_malformed_manifest(self):
        self.assertEqual(self.gate.parse_pins(b"not json"), {})


if __name__ == "__main__":
    unittest.main()
