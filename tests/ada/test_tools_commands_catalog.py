import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


def _load():
    script = (Path(__file__).resolve().parents[2]
              / "scripts" / "ada" / "tools-commands-catalog.py")
    spec = importlib.util.spec_from_file_location(
        "tools_commands_catalog", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROVIDER_PY = '''\
CAMERA_DECLARATION = {
    "name": "ada_camera_snapshot",
    "description": "Take a still camera snapshot.",
}


def _builtin_declarations():
    return [{
        "name": "home_search",
        "description": "Find HA devices.",
    }, {
        "name": "ada_remember",
        "description": "Store a memory.",
    }]


CHABA_DECLARATIONS = [
    {
        "name": "ada_remember",
        "description": "Save a public guest memory.",
    },
]
'''

DROP_PY = '''\
DECLARATION = {
    "name": "kanban",
    "description": "Kanban board ops.",
}
'''

COMMON_PY = '''\
_ALIASES: dict[str, str] = {
    "cctv_snapshot": "ada_camera_snapshot",
    "traffic_camera": "ada_camera_snapshot",
}
'''

SCENARIO = {
    "name": "cam",
    "turns": [
        {"user": "Can you look at the pool camera?",
         "expect": {"calls": ["ada_camera_snapshot"]}},
    ],
}


def _scratch(root: Path) -> dict:
    """Minimal ada-voice tree + chaba registry; returns patched paths."""
    ada = root / "ada-voice"
    (ada / "backend" / "tools.d").mkdir(parents=True)
    (ada / "backend" / "tool_runner").mkdir(parents=True)
    (ada / "docs" / "ssot").mkdir(parents=True)
    (ada / "tests" / "scenarios-live").mkdir(parents=True)
    (ada / "backend" / "realtime_provider.py").write_text(PROVIDER_PY)
    (ada / "backend" / "tools.d" / "kanban.py").write_text(DROP_PY)
    (ada / "backend" / "tools.d" / "manifest.yml").write_text(yaml.safe_dump({
        "tools": {"kanban": {"module": "kanban", "policy": "read",
                             "secondary_allowed": True, "timeout_s": 180}}}))
    (ada / "backend" / "tool_guide.yml").write_text(
        "home_search: retry with a room name\n")
    (ada / "backend" / "tool_runner" / "common.py").write_text(COMMON_PY)
    (ada / "docs" / "ssot" / "ssot.tool-surface.yml").write_text(
        yaml.safe_dump({
            "count_cap": 112, "target_count": 38,
            "lazy_schemas": {"full_schema_tools": ["home_search"]},
            "families": {"camera": {
                "merge_card": "tools-merge-camera",
                "canonical": "ada_camera_snapshot",
                "scenario": "tool_merge_camera",
                "absorbed": ["cctv_snapshot", "traffic_camera"]}},
            "coverage_debt": ["kanban"],
        }))
    (ada / "tests" / "scenarios-live" / "cam.yaml").write_text(
        yaml.safe_dump(SCENARIO))
    registry = root / "ssot.tools.yml"
    registry.write_text(yaml.safe_dump({"tools": [
        {"name": "board.kanban", "backend": "board-api", "policy": "read",
         "surfaces": {"ada-voice": "kanban"}},
        {"name": "ha.search", "backend": "ha", "policy": "read",
         "surfaces": {"ada-voice": "home_search"}},
    ]}))
    return {
        "ADA_VOICE": ada, "PROVIDER": ada / "backend" / "realtime_provider.py",
        "TOOLS_D": ada / "backend" / "tools.d",
        "MANIFEST": ada / "backend" / "tools.d" / "manifest.yml",
        "TOOL_GUIDE": ada / "backend" / "tool_guide.yml",
        "ALIAS_FILE": ada / "backend" / "tool_runner" / "common.py",
        "SURFACE_YML": ada / "docs" / "ssot" / "ssot.tool-surface.yml",
        "SCEN_DIR": ada / "tests" / "scenarios-live",
        "REGISTRY": registry,
        "OUT_MD": root / "ada-tools-commands.md",
        "OUT_JSON": root / "ada-tools-commands.json",
    }


class TestToolsCommandsCatalog(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = _scratch(Path(self.tmp.name))
        self.patchers = [
            mock.patch.object(self.mod, key, value)
            for key, value in self.paths.items()]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def _collect(self):
        with mock.patch.object(self.mod.subprocess, "run",
                               side_effect=Exception("no git")):
            return self.mod.collect()

    def test_layers_and_counts(self):
        data = self._collect()
        self.assertEqual(data["counts"]["builtin"], 3)   # camera decl + 2 builtin
        self.assertEqual(data["counts"]["dropin"], 1)
        self.assertEqual(data["counts"]["guest"], 1)     # CHABA_DECLARATIONS
        layers = {(r["name"], r["layer"]) for r in data["rows"]}
        self.assertIn(("ada_remember", "builtin"), layers)
        self.assertIn(("ada_remember", "guest"), layers)  # same name, both seats

    def test_join_fields(self):
        data = self._collect()
        rows = {r["name"]: r for r in data["rows"]}
        kanban = rows["kanban"]
        self.assertEqual(kanban["backend"], "board-api")   # registry join
        self.assertEqual(kanban["timeout_s"], 180)          # manifest join
        self.assertTrue(kanban["secondary"])
        self.assertTrue(rows["home_search"]["guide"])       # tool_guide join
        self.assertEqual(rows["home_search"]["schema"], "full")
        self.assertEqual(
            rows["ada_camera_snapshot"]["triggers"],
            ["Can you look at the pool camera?"])           # scenario join
        self.assertEqual(rows["ada_camera_snapshot"]["family"], "camera")

    def test_aliases_and_family_status(self):
        data = self._collect()
        self.assertEqual(data["aliases"]["cctv_snapshot"], "ada_camera_snapshot")
        self.assertEqual(data["families"]["camera"]["status"], "merged")
        self.assertEqual(data["drift"]["coverage_debt"], ["kanban"])
        self.assertEqual(data["drift"]["unregistered_tools"],
                         ["ada_camera_snapshot", "ada_remember"])

    def test_render_and_check_roundtrip(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.main([]), 0)
        md = self.paths["OUT_MD"].read_text()
        self.assertIn("do not edit", md)
        self.assertIn("`kanban`", md)
        self.assertIn("merged", md)
        doc = json.loads(self.paths["OUT_JSON"].read_text())
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(len(doc["tools"]), 5)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.main(["--check"]), 0)

    def test_check_flags_stale(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.main([]), 0)
        self.paths["OUT_MD"].write_text("tampered\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.main(["--check"]), 1)


if __name__ == "__main__":
    unittest.main()
