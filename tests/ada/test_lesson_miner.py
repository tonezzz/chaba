"""Unit tests for scripts/ada/lesson-miner.py — the offline transcripts
-> lesson CPT miner (card lesson-transcript-miner).

Covers the contracts that don't need an LLM: transcript parsing (same
'## Ada|## User [HH:MM:SS]' format as transcript-index.py), the
mechanical question-turn pre-filter (recall-biased: '?' / question
starters / Thai markers in, device commands and tiny turns out), Q->A
pairing, lesson-slug parity with lesson-add.py, and state dedup.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/lesson-miner.py"

spec = importlib.util.spec_from_file_location("lesson_miner", SCRIPT)
lm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lm)

TRANSCRIPT = """# Ada voice session abc123

## User [10:00:01]
turn on the kitchen lights

## Ada [10:00:03]
Done.

## User [10:01:00]
What is the difference between a relay and a contactor?

## Ada [10:01:20]
A relay is a small electrically operated switch for low-power control.
A contactor is a heavy-duty relay rated for high-current loads like
motors. Same principle, different scale.

## User [10:02:00]
ok

## User [10:03:00]
ทำไมเครื่องทำน้ำอุ่นถึงตัดไฟบ่อย

## Ada [10:03:30]
เครื่องทำน้ำอุ่นกินกระแสสูง ถ้าเบรกเกอร์เล็กเกินไปจะตัดบ่อย

## User [10:04:00]
remind me to call the electrician tomorrow
"""


class ParseTest(unittest.TestCase):
    def _parse(self, text=TRANSCRIPT):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-14-abc123.md"
            p.write_text(text, encoding="utf-8")
            return lm.parse_transcript(p)

    def test_session_meta(self):
        sid, date, turns = self._parse()
        self.assertEqual(sid, "abc123")
        self.assertEqual(date, "2026-10-14")
        self.assertEqual(len(turns), 8)

    def test_roles_and_text(self):
        _, _, turns = self._parse()
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[1]["role"], "ada")
        self.assertIn("kitchen lights", turns[0]["text"])
        self.assertEqual(turns[1]["stamp"], "10:00:03")


class CandidateTest(unittest.TestCase):
    def _cands(self, text=TRANSCRIPT):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-14-abc123.md"
            p.write_text(text, encoding="utf-8")
            _, _, turns = lm.parse_transcript(p)
        return lm.find_candidates(turns)

    def test_pairs_question_with_answer(self):
        cands = self._cands()
        qs = [c["q"] for c in cands]
        self.assertTrue(any("relay" in q for q in qs))
        relay = next(c for c in cands if "relay" in c["q"])
        self.assertIn("contactor", relay["a"])
        self.assertEqual(relay["stamp"], "10:01:00")

    def test_drops_commands_and_tiny_turns(self):
        cands = self._cands()
        joined = " ".join(c["q"] for c in cands)
        self.assertNotIn("kitchen lights", joined)
        self.assertNotIn("electrician tomorrow", joined)
        self.assertNotIn("\nok\n", joined)

    def test_thai_question_detected(self):
        cands = self._cands()
        self.assertTrue(any("เครื่องทำน้ำอุ่น" in c["q"] for c in cands))
        th = next(c for c in cands if "เครื่องทำน้ำอุ่น" in c["q"])
        self.assertIn("เบรกเกอร์", th["a"])

    def test_question_without_answer_dropped(self):
        t = ("# Ada voice session x\n\n## User [09:00:00]\n"
             "What is photosynthesis?\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-14-x.md"
            p.write_text(t, encoding="utf-8")
            _, _, turns = lm.parse_transcript(p)
        self.assertEqual(lm.find_candidates(turns), [])

    def test_answer_stops_at_next_user_turn(self):
        cands = self._cands()
        relay = next(c for c in cands if "relay" in c["q"])
        self.assertNotIn("เครื่องทำน้ำอุ่น", relay["a"])


class FilterTest(unittest.TestCase):
    def test_is_question_turn(self):
        self.assertTrue(lm.is_question_turn(
            "What is the difference between a hub and a switch?"))
        self.assertTrue(lm.is_question_turn(
            "ada, how does a heat pump work"))
        self.assertTrue(lm.is_question_turn(
            "อะไรคือสาเหตุของไฟตก"))
        self.assertFalse(lm.is_question_turn("what?"))
        self.assertFalse(lm.is_question_turn("turn on the lights please"))
        self.assertFalse(lm.is_question_turn("set a timer for ten minutes"))
        self.assertFalse(lm.is_question_turn("yes that's right"))


class SlugTest(unittest.TestCase):
    def test_parity_with_lesson_add(self):
        # lesson-add.py computes the same slug inline; keep in lockstep.
        import hashlib
        topic = "  Cloud Object Storage  "
        expect = ("lesson-" + hashlib.md5(
            topic.strip().lower().encode()).hexdigest()[:12])
        self.assertEqual(lm.lesson_slug(topic), expect)
        self.assertEqual(lm.lesson_slug("cloud object storage"),
                         lm.lesson_slug("Cloud Object Storage"))


class StateTest(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertEqual(lm.load_state(p), {"scanned": {}, "filed": {}})
            st = {"scanned": {"a.md": 123}, "filed": {"lesson-x": {"topic": "t"}}}
            lm.save_state(p, st)
            self.assertEqual(lm.load_state(p), st)

    def test_corrupt_state_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text("{not json")
            self.assertEqual(lm.load_state(p), {"scanned": {}, "filed": {}})


if __name__ == "__main__":
    unittest.main()
