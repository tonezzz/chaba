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


def _fake_rc(pack_entries, inbox):
    """pack_entries: raw lsf -R lines for packs/; inbox: {name: spec}."""
    def fake(*args, input_text=None):
        if args[0] == "lsf" and args[1].endswith("/packs"):
            return "".join(f"{x}\n" for x in pack_entries)
        if args[0] == "lsf" and args[1].endswith("/inbox"):
            return "".join(f"{n}\n" for n in inbox)
        if args[0] == "cat":
            name = args[1].rsplit("/", 1)[-1]
            return json.dumps(inbox[name])
        raise AssertionError(f"unexpected rclone call: {args}")
    return fake


class ProducerTests(unittest.TestCase):
    def _produce(self, pack_entries, inbox, **kw):
        cats = []

        def spy_rc(*args, input_text=None):
            if args[0] == "cat":
                cats.append(args[1])
            return _fake_rc(pack_entries, inbox)(*args, input_text=input_text)

        with (
            patch.object(producer, "snapshot",
                         return_value={"eligible": True}),
            patch.object(producer, "rclone", side_effect=spy_rc),
            patch.object(producer, "stage_task",
                         side_effect=lambda task, **k:
                         f"kk-mac-task-{task['task_id']}"),
        ):
            result = producer.produce(remote="gdrive:x/kk-llm", **kw)
        return result, cats

    def test_already_staged_skips_without_cat(self):
        inbox = {"task-a.json": _spec("task-a"),
                 "task-b.json": _spec("task-b")}
        packs = ["kk-mac-task-task-a/pack.yml\n",
                 "kk-mac-task-task-a/inputs/task.json\n"]
        result, cats = self._produce(packs, inbox)
        self.assertEqual(result["staged"], ["kk-mac-task-task-b"])
        self.assertEqual(cats, ["gdrive:x/kk-llm/inbox/task-b.json"])
        self.assertIn("task-a.json:already_staged", result["skipped"])

    def test_empty_pack_dir_does_not_wedge_spec(self):
        # Failed upload leaves a bare dir entry — no pack.yml, no files.
        inbox = {"task-a.json": _spec("task-a")}
        packs = ["kk-mac-task-task-a/\n"]
        result, _ = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 0)
        self.assertEqual(result["staged"], ["kk-mac-task-task-a"])

    def test_terminal_pack_frees_queue_slot(self):
        # done/failed packs leave the live queue but still count as
        # staged — inbox specs are one-shot, never re-run.
        inbox = {"task-a.json": _spec("task-a")}
        packs = ["kk-mac-task-task-a/pack.yml\n",
                 "kk-mac-task-task-a/done\n"]
        result, _ = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 0)
        self.assertEqual(result["staged"], [])
        self.assertIn("task-a.json:already_staged", result["skipped"])

    def test_queue_at_capacity(self):
        inbox = {"task-b.json": _spec("task-b")}
        packs = [f"kk-mac-task-t{i}/pack.yml\n" for i in range(3)]
        result, cats = self._produce(packs, inbox)
        self.assertEqual(result["queue_before"], 3)
        self.assertEqual(result["staged"], [])
        self.assertIn("queue_at_capacity", result["skipped"])
        self.assertEqual(cats, [])


if __name__ == "__main__":
    unittest.main()
