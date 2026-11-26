import json
import os
import tempfile
import unittest

import importlib.util
spec = importlib.util.spec_from_file_location(
    "consultant_fixture_validate", "scripts/ada/consultant-fixture-validate.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "consultant-tasks.jsonl")


class TestConsultantFixtureValidate(unittest.TestCase):

    def _write(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(json.dumps(l) if isinstance(l, dict) else l for l in lines))
        return path

    def test_shipped_fixture_is_valid(self):
        errors, n, counts = v.validate_fixture(FIXTURE)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(n, v.MIN_CASES)
        self.assertGreaterEqual(counts["answer"], v.MIN_PER_VERDICT)
        self.assertGreaterEqual(counts["escalate"], v.MIN_PER_VERDICT)

    def test_shipped_fixture_sources_are_real_cards(self):
        """Every case must cite a source that exists on disk (kanban card)."""
        with open(FIXTURE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                src = case.get("source")
                self.assertTrue(src, f"{case['id']}: missing source")
                self.assertTrue(
                    os.path.exists(os.path.join(os.path.dirname(FIXTURE), "..", src)),
                    f"{case['id']}: source {src} does not exist")

    def test_rejects_bad_expected(self):
        path = self._write([
            {"id": "a", "task": "t", "expected": "answer"},
            {"id": "b", "task": "t", "expected": "maybe"},
        ])
        errors, _, _ = v.validate_fixture(path, min_cases=0, min_per_verdict=0)
        self.assertTrue(any("expected" in e for e in errors))

    def test_rejects_duplicate_ids(self):
        path = self._write([
            {"id": "a", "task": "t", "expected": "answer"},
            {"id": "a", "task": "t2", "expected": "escalate"},
        ])
        errors, _, _ = v.validate_fixture(path, min_cases=0, min_per_verdict=0)
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_rejects_imbalanced_fixture(self):
        path = self._write([{"id": f"c{i}", "task": "t", "expected": "answer"}
                            for i in range(20)])
        errors, _, _ = v.validate_fixture(path)
        self.assertTrue(any("imbalanced" in e or "'escalate'" in e for e in errors))

    def test_rejects_missing_keys_and_bad_json(self):
        path = self._write([
            {"id": "a", "task": "t"},          # missing expected
            "not json at all{",
        ])
        errors, _, _ = v.validate_fixture(path, min_cases=0, min_per_verdict=0)
        self.assertTrue(any("missing 'expected'" in e for e in errors))
        self.assertTrue(any("invalid JSON" in e for e in errors))

        for path in [path]:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
