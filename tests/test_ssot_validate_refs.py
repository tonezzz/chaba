import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ssot-validate-refs.py"
SPEC = importlib.util.spec_from_file_location("ssot_validate_refs", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ValidateRefsTests(unittest.TestCase):
    def test_git_base_ref_is_not_treated_as_ssot_path(self):
        refs = VALIDATOR.scan_refs(
            {"base_ref": "origin/master", "source_ref": "docs/ssot/example.yml"},
            "docs/ssot/example-card.yml",
            {},
        )

        self.assertEqual(
            refs,
            [
                (
                    "docs/ssot/example-card.yml",
                    "source_ref",
                    "docs/ssot/example.yml",
                )
            ],
        )
