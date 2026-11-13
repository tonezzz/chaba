import json
import unittest
from unittest.mock import patch

from scripts.devnest import kk_mac_capacity_producer as producer


def _spec(task_id="task-a"):
    return {
        "task_id": task_id,
        "task_class": "summary",
        "prompt": "summarize this",
    }


def _fake_rc(pack_entries, inbox, moves):
    """pack_entries: raw lsf -R lines for packs/; inbox: {name: spec-or-raw};
    moves: list that records (src, dst) moveto calls."""
    def fake(*args, input_text=None):
        if args[0] == "lsf" and args[1].endswith("/packs"):
            return "".join(f"{x}\n" for x in pack_entries)
        if args[0] == "lsf" and args[1].endswith("/inbox"):
            return "".join(f"{n}\n" for n in inbox)
        if args[0] == "cat":
            name = args[1].rsplit("/", 1)[-1]
            spec = inbox[name]
            return spec if isinstance(spec, str) else json.dumps(spec)
        if args[0] == "moveto":
            moves.append((args[1], args[2]))
            return ""
        raise AssertionError(f"unexpected rclone call: {args}")
    return fake


class ProducerTests(unittest.TestCase):
    def _produce(self, pack_entries, inbox, **kw):
        cats = []
        moves = []

        def spy_rc(*args, input_text=None):
            if args[0] == "cat":
                cats.append(args[1])
            return _fake_rc(pack_entries, inbox, moves)(
                *args, input_text=input_text)

        with (
            patch.object(producer, "snapshot",
                         return_value={"eligible": True}),
            patch.object(producer, "rclone", side_effect=spy_rc),
            patch.object(producer, "stage_task",
                         side_effect=lambda task, **k:
                         f"kk-mac-task-{task['task_id']}"),
        ):
            result = producer.produce(remote="gdrive:x/kk-llm", **kw)
        return result, cats, moves

    def test_already_staged_skips_without_cat(self):
        inbox = {"task-a.json": _spec("task-a"),
                 "task-b.json": _spec("task-b")}
        packs = ["kk-mac-task-task-a/pack.yml\n",
                 "kk-mac-task-task-a/inputs/task.json\n"]
        result, cats, moves = self._produce(packs, inbox)
        self.assertEqual(result["staged"], ["kk-mac-task-task-b"])
        self.assertEqual(cats, ["gdrive:x/kk-llm/inbox/task-b.json"])
        self.assertIn("task-a.json:already_staged", result["skipped"])
        self.assertEqual(sorted(moves), sorted([
            ("gdrive:x/kk-llm/inbox/task-a.json",
             "gdrive:x/kk-llm/inbox/done/task-a.json"),
            ("gdrive:x/kk-llm/inbox/task-b.json",
             "gdrive:x/kk-llm/inbox/done/task-b.json"),
        ]))

    def test_invalid_spec_is_quarantined(self):
        inbox = {"bad.json": "{not json", "task-a.json": _spec("task-a")}
        result, cats, moves = self._produce([], inbox)
        self.assertIn("bad.json:JSONDecodeError", result["skipped"])
        self.assertEqual(result["staged"], ["kk-mac-task-task-a"])
        self.assertIn(
            ("gdrive:x/kk-llm/inbox/bad.json",
             "gdrive:x/kk-llm/inbox/quarantine/bad.json"), moves)
        self.assertIn(
            ("gdrive:x/kk-llm/inbox/task-a.json",
             "gdrive:x/kk-llm/inbox/done/task-a.json"), moves)

    def test_dry_run_moves_nothing(self):
        inbox = {"task-a.json": _spec("task-a")}
        result, _, moves = self._produce([], inbox, dry_run=True)
        self.assertEqual(result["staged"], ["kk-mac-task-task-a"])
        self.assertEqual(moves, [])

    def test_empty_pack_dir_does_not_wedge_spec(self):
        # Failed upload leaves a bare dir entry — no pack.yml, no files.
        inbox = {"task-a.json": _spec("task-a")}
        packs = ["kk-mac-task-task-a/\n"]
        result, _, _ = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 0)
        self.assertEqual(result["staged"], ["kk-mac-task-task-a"])

    def test_terminal_pack_frees_queue_slot(self):
        # done/failed packs leave the live queue but still count as
        # staged — inbox specs are one-shot, never re-run.
        inbox = {"task-a.json": _spec("task-a")}
        packs = ["kk-mac-task-task-a/pack.yml\n",
                 "kk-mac-task-task-a/done\n"]
        result, _, _ = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 0)
        self.assertEqual(result["staged"], [])
        self.assertIn("task-a.json:already_staged", result["skipped"])

    def test_queue_at_capacity(self):
        inbox = {"task-b.json": _spec("task-b")}
        packs = [f"kk-mac-task-t{i}/pack.yml\n" for i in range(3)]
        result, cats, _ = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 3)
        self.assertEqual(result["staged"], [])
        self.assertIn("queue_at_capacity", result["skipped"])
        self.assertEqual(cats, [])


if __name__ == "__main__":
    unittest.main()
