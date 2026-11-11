import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import yaml


class TestRenderJobsCatalog(unittest.TestCase):
    def test_calendar_schedules_roundtrip_as_strings(self):
        script = Path(__file__).resolve().parents[1] / "scripts/render-jobs-catalog.py"
        spec = importlib.util.spec_from_file_location("render_jobs_catalog", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        jobs = [
            {"id": "calendar", "host": "con01", "on_calendar": "*-*-* 06:45:00"},
            {"id": "minute", "host": "con01", "on_calendar": "*:0/5"},
            {"id": "missing", "host": "con01"},
            {"id": "periodic", "host": "con01", "every": "15m"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "jobs.yml"
            manifest.write_text(yaml.safe_dump({"jobs": jobs}))
            out = root / "generated"
            with mock.patch.object(module, "MANIFEST", manifest), \
                    mock.patch.object(sys, "argv", [str(script), "--out", str(out)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                module.main()
            data = yaml.safe_load((out / "jobs.con01.yml").read_text())
        self.assertEqual({j["id"]: j["schedule"] for j in data["jobs"]}, {
            "calendar": "*-*-* 06:45:00", "minute": "*:0/5",
            "missing": "-", "periodic": "every 15m",
        })
